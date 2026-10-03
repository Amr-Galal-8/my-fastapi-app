import hmac
import json
from collections import Counter
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.dependencies import CurrentAccount, CurrentClient, SessionDep, StaffAccount
from app.models import (
    Account,
    Branch,
    Client,
    ClientAddress,
    ClientPaymentMethod,
    Inventory,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentMethodType,
    PaymentStatus,
    Product,
)
from app.payments import PaymentProviderError, create_checkout
from app.schemas import OrderCreate, OrderRead, OrderStatusUpdate
from app.security import decrypt_provider_token

router = APIRouter(prefix="/api/v1", tags=["Orders"])


async def _load_order(session: SessionDep, order_id: UUID) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.payment))
    )


@router.post("/orders", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    client: CurrentClient,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120),
) -> Order:
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise HTTPException(status_code=422, detail="Idempotency-Key cannot be empty")
    request_fingerprint = None
    if idempotency_key:
        serialized_request = json.dumps(
            payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        request_fingerprint = hmac.new(
            get_settings().jwt_secret.get_secret_value().encode(), serialized_request, sha256
        ).hexdigest()
    if idempotency_key:
        existing = await session.scalar(
            select(Order)
            .where(Order.client_id == client.id, Order.idempotency_key == idempotency_key)
            .options(selectinload(Order.items), selectinload(Order.payment))
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different request",
                )
            return existing
    branch = await session.get(Branch, payload.branch_id)
    if branch is None or not branch.is_active:
        raise HTTPException(status_code=404, detail="Active branch not found")

    shipping_address = None
    if payload.shipping_address_id is not None:
        address = await session.scalar(
            select(ClientAddress).where(
                ClientAddress.id == payload.shipping_address_id,
                ClientAddress.client_id == client.id,
            )
        )
        if address is None:
            raise HTTPException(status_code=404, detail="Saved address not found")
        shipping_address = {
            "recipient_name": address.recipient_name,
            "phone": address.phone,
            "line1": address.line1,
            "line2": address.line2,
            "city": address.city,
            "region": address.region,
            "postal_code": address.postal_code,
            "country": address.country,
        }
    elif payload.shipping_address is not None:
        shipping_address = payload.shipping_address.model_dump()

    quantities: Counter[UUID] = Counter()
    for line in payload.items:
        quantities[line.product_id] += line.quantity
    product_ids = sorted(quantities, key=str)
    products = list(
        (
            await session.scalars(
                select(Product).where(Product.id.in_(product_ids), Product.is_active.is_(True))
            )
        ).all()
    )
    product_by_id = {product.id: product for product in products}
    if len(product_by_id) != len(product_ids):
        raise HTTPException(status_code=404, detail="One or more active products were not found")

    saved_token: str | None = None
    if payload.payment_method_id:
        method = await session.scalar(
            select(ClientPaymentMethod).where(
                ClientPaymentMethod.id == payload.payment_method_id,
                ClientPaymentMethod.client_id == client.id,
                ClientPaymentMethod.is_active.is_(True),
            )
        )
        if method is None:
            raise HTTPException(status_code=404, detail="Saved payment method not found")
        if method.provider != get_settings().payment_provider:
            raise HTTPException(
                status_code=409, detail="Saved card belongs to another payment provider"
            )
        if method.provider != "mock":
            saved_token = decrypt_provider_token(method.provider_method_id_encrypted)
    if payload.payment_method == PaymentMethodType.CASH_ON_DELIVERY and payload.payment_method_id:
        raise HTTPException(status_code=422, detail="Cash on delivery cannot use a saved card")

    total = sum(
        (
            product_by_id[product_id].unit_price * quantity
            for product_id, quantity in quantities.items()
        ),
        Decimal("0.00"),
    )
    order_id = uuid4()
    order_number = f"INF-{order_id.hex[:12].upper()}"
    card_payment = payload.payment_method == PaymentMethodType.CARD
    order = Order(
        id=order_id,
        order_number=order_number,
        client_id=client.id,
        branch_id=branch.id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        fulfillment_method=payload.fulfillment_method.value,
        payment_method=payload.payment_method.value,
        status=(OrderStatus.PAYMENT_PENDING if card_payment else OrderStatus.CONFIRMED).value,
        payment_status=(PaymentStatus.PENDING if card_payment else PaymentStatus.COD_DUE).value,
        total_amount=total,
        currency=get_settings().payment_currency,
        shipping_address=shipping_address,
        client_note=payload.client_note,
    )
    order.items = [
        OrderItem(
            product_id=product_by_id[product_id].id,
            sku_snapshot=product_by_id[product_id].sku,
            product_name_snapshot=product_by_id[product_id].name,
            quantity=quantity,
            unit_price=product_by_id[product_id].unit_price,
            line_total=product_by_id[product_id].unit_price * quantity,
        )
        for product_id, quantity in quantities.items()
    ]
    provider = get_settings().payment_provider if card_payment else "offline"
    order.payment = Payment(
        provider=provider,
        status=(PaymentStatus.PENDING if card_payment else PaymentStatus.COD_DUE).value,
        amount=total,
        currency=order.currency,
    )

    try:
        for product_id in product_ids:
            changed = await session.execute(
                update(Inventory)
                .where(
                    Inventory.branch_id == branch.id,
                    Inventory.product_id == product_id,
                    Inventory.quantity >= quantities[product_id],
                )
                .values(quantity=Inventory.quantity - quantities[product_id])
            )
            if changed.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient inventory for product {product_by_id[product_id].sku}",
                )
        session.add(order)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError:
        await session.rollback()
        if idempotency_key:
            existing = await session.scalar(
                select(Order)
                .where(Order.client_id == client.id, Order.idempotency_key == idempotency_key)
                .options(selectinload(Order.items), selectinload(Order.payment))
            )
            if existing:
                if existing.request_fingerprint != request_fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key was already used with a different request",
                    ) from None
                return existing
        raise HTTPException(status_code=409, detail="Order conflicts with existing data") from None

    if card_payment:
        order = await _load_order(session, order.id)
        if order is None or order.payment is None:
            raise HTTPException(status_code=500, detail="Order payment could not be loaded")
        account = await session.get(Account, client.account_id)
        try:
            checkout = await create_checkout(
                payment_id=order.payment.id,
                order=order,
                client=client,
                email=account.email if account else "client@infinity.local",
                saved_provider_token=saved_token,
            )
        except PaymentProviderError as exc:
            for item in order.items:
                await session.execute(
                    update(Inventory)
                    .where(
                        Inventory.branch_id == order.branch_id,
                        Inventory.product_id == item.product_id,
                    )
                    .values(quantity=Inventory.quantity + item.quantity)
                )
            order.status = OrderStatus.CANCELLED.value
            order.payment_status = PaymentStatus.FAILED.value
            order.payment.status = PaymentStatus.FAILED.value
            await session.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from None
        order.payment.provider = checkout.provider
        order.payment.provider_order_id = checkout.provider_order_id
        order.payment.checkout_url = checkout.checkout_url
        await session.commit()
    reloaded = await _load_order(session, order.id)
    return reloaded or order


@router.get("/orders", response_model=list[OrderRead])
async def list_my_orders(
    client: CurrentClient,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Order]:
    result = await session.scalars(
        select(Order)
        .where(Order.client_id == client.id)
        .options(selectinload(Order.items), selectinload(Order.payment))
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.all())


@router.get("/orders/{order_id}", response_model=OrderRead)
async def read_order(order_id: UUID, account: CurrentAccount, session: SessionDep) -> Order:
    """Clients see only their orders; staff can inspect company orders."""
    order = await _load_order(session, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if account.role == "client":
        profile = await session.scalar(select(Client).where(Client.account_id == account.id))
        if profile is None or profile.id != order.client_id:
            raise HTTPException(status_code=404, detail="Order not found")
    elif account.role not in {"employee", "admin"}:
        raise HTTPException(status_code=403, detail="You do not have permission to view this order")
    return order


@router.get("/admin/orders", response_model=list[OrderRead])
async def list_all_orders(
    _: StaffAccount,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[Order]:
    result = await session.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.payment))
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.all())


@router.patch("/admin/orders/{order_id}/status", response_model=OrderRead)
async def update_order_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    _: StaffAccount,
    session: SessionDep,
) -> Order:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.payment))
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    allowed = {
        OrderStatus.PAYMENT_PENDING.value: {OrderStatus.CANCELLED.value},
        OrderStatus.CONFIRMED.value: {OrderStatus.PROCESSING.value, OrderStatus.CANCELLED.value},
        OrderStatus.PROCESSING.value: {
            OrderStatus.READY_FOR_PICKUP.value,
            OrderStatus.SHIPPED.value,
            OrderStatus.CANCELLED.value,
        },
        OrderStatus.READY_FOR_PICKUP.value: {
            OrderStatus.COMPLETED.value,
            OrderStatus.CANCELLED.value,
        },
        OrderStatus.SHIPPED.value: {OrderStatus.COMPLETED.value},
    }
    if payload.status.value not in allowed.get(order.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move order from {order.status} to {payload.status.value}",
        )
    if (
        payload.status == OrderStatus.READY_FOR_PICKUP
        and order.fulfillment_method != "store_pickup"
    ):
        raise HTTPException(status_code=409, detail="Only pickup orders can be marked ready")
    if payload.status == OrderStatus.SHIPPED and order.fulfillment_method != "home_delivery":
        raise HTTPException(status_code=409, detail="Only delivery orders can be marked shipped")
    if payload.status == OrderStatus.CANCELLED and order.payment_status == PaymentStatus.PAID.value:
        raise HTTPException(
            status_code=409, detail="Paid orders require a refund before cancellation"
        )
    if payload.status == OrderStatus.CANCELLED:
        for item in order.items:
            await session.execute(
                update(Inventory)
                .where(
                    Inventory.branch_id == order.branch_id, Inventory.product_id == item.product_id
                )
                .values(quantity=Inventory.quantity + item.quantity)
            )
        if order.payment:
            order.payment.status = PaymentStatus.FAILED.value
        order.payment_status = PaymentStatus.FAILED.value
    elif (
        payload.status == OrderStatus.COMPLETED
        and order.payment_method == PaymentMethodType.CASH_ON_DELIVERY.value
    ):
        order.payment_status = PaymentStatus.PAID.value
        if order.payment:
            order.payment.status = PaymentStatus.PAID.value
    order.status = payload.status.value
    await session.commit()
    refreshed = await _load_order(session, order.id)
    return refreshed or order
