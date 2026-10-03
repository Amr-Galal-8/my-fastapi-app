from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.dependencies import CurrentClient, SessionDep
from app.models import (
    Client,
    ClientPaymentMethod,
    Inventory,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from app.payments import verify_paymob_callback
from app.schemas import MockCardSave, OrderRead, PaymentMethodRead
from app.security import encrypt_provider_token, token_fingerprint

router = APIRouter(prefix="/api/v1", tags=["Payments"])


@router.get("/clients/me/payment-methods", response_model=list[PaymentMethodRead])
async def list_payment_methods(
    client: CurrentClient, session: SessionDep
) -> list[ClientPaymentMethod]:
    result = await session.scalars(
        select(ClientPaymentMethod)
        .where(ClientPaymentMethod.client_id == client.id, ClientPaymentMethod.is_active.is_(True))
        .order_by(ClientPaymentMethod.is_default.desc(), ClientPaymentMethod.created_at.desc())
    )
    return list(result.all())


@router.delete("/clients/me/payment-methods/{method_id}", status_code=204)
async def remove_payment_method(
    method_id: UUID, client: CurrentClient, session: SessionDep
) -> None:
    await session.scalar(select(Client).where(Client.id == client.id).with_for_update(of=Client))
    method = await session.scalar(
        select(ClientPaymentMethod)
        .where(ClientPaymentMethod.id == method_id, ClientPaymentMethod.client_id == client.id)
        .with_for_update()
    )
    if method is None:
        raise HTTPException(status_code=404, detail="Saved payment method not found")
    was_default = method.is_default
    await session.delete(method)
    if was_default:
        replacement = await session.scalar(
            select(ClientPaymentMethod)
            .where(
                ClientPaymentMethod.client_id == client.id,
                ClientPaymentMethod.is_active.is_(True),
                ClientPaymentMethod.id != method.id,
            )
            .order_by(ClientPaymentMethod.created_at, ClientPaymentMethod.id)
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True
    await session.commit()


@router.put("/clients/me/payment-methods/{method_id}/default", response_model=PaymentMethodRead)
async def set_default_payment_method(
    method_id: UUID, client: CurrentClient, session: SessionDep
) -> ClientPaymentMethod:
    # Locking the parent serializes default-card changes for this client.
    await session.scalar(select(Client).where(Client.id == client.id).with_for_update(of=Client))
    method = await session.scalar(
        select(ClientPaymentMethod).where(
            ClientPaymentMethod.id == method_id,
            ClientPaymentMethod.client_id == client.id,
            ClientPaymentMethod.is_active.is_(True),
        )
    )
    if method is None:
        raise HTTPException(status_code=404, detail="Saved payment method not found")
    await session.execute(
        update(ClientPaymentMethod)
        .where(ClientPaymentMethod.client_id == client.id)
        .values(is_default=False)
    )
    method.is_default = True
    await session.commit()
    await session.refresh(method)
    return method


@router.post(
    "/clients/me/payment-methods/demo",
    response_model=PaymentMethodRead,
    status_code=201,
)
async def add_demo_payment_method(
    payload: MockCardSave, client: CurrentClient, session: SessionDep
) -> ClientPaymentMethod:
    """Add safe fake card display data for local demos; no card number is accepted."""
    settings = get_settings()
    if settings.payment_provider != "mock" or settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Demo payment methods are disabled")
    await session.scalar(select(Client).where(Client.id == client.id).with_for_update(of=Client))
    token = f"mock-method-{uuid4().hex}"
    existing_default = await session.scalar(
        select(ClientPaymentMethod.id).where(
            ClientPaymentMethod.client_id == client.id,
            ClientPaymentMethod.is_active.is_(True),
            ClientPaymentMethod.is_default.is_(True),
        )
    )
    method = ClientPaymentMethod(
        client_id=client.id,
        provider="mock",
        provider_method_id_encrypted=encrypt_provider_token(token),
        token_fingerprint=token_fingerprint(token),
        brand=payload.brand,
        last_four=payload.last_four,
        expiry_month=payload.expiry_month,
        expiry_year=payload.expiry_year,
        is_default=existing_default is None,
    )
    session.add(method)
    await session.commit()
    await session.refresh(method)
    return method


async def _release_reserved_stock(session: SessionDep, order: Order) -> None:
    for item in order.items:
        await session.execute(
            update(Inventory)
            .where(Inventory.branch_id == order.branch_id, Inventory.product_id == item.product_id)
            .values(quantity=Inventory.quantity + item.quantity)
        )


async def _lock_order_and_payment(
    session: SessionDep, order_id: UUID, payment_id: UUID
) -> tuple[Order | None, Payment | None]:
    # Every payment transition locks the order first, then the payment row.
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
        .with_for_update(of=Order)
    )
    if order is None:
        return None, None
    payment = await session.scalar(
        select(Payment)
        .where(Payment.id == payment_id, Payment.order_id == order.id)
        .with_for_update()
    )
    return order, payment


async def _finish_payment(
    session: SessionDep,
    order: Order,
    payment: Payment,
    *,
    success: bool,
    transaction_id: str | None,
) -> None:
    if payment.status != PaymentStatus.PENDING.value:
        return
    if transaction_id and not payment.provider_transaction_id:
        payment.provider_transaction_id = transaction_id
    if success:
        payment.status = PaymentStatus.PAID.value
        order.payment_status = PaymentStatus.PAID.value
        order.status = OrderStatus.CONFIRMED.value
    else:
        payment.status = PaymentStatus.FAILED.value
        order.payment_status = PaymentStatus.FAILED.value
        order.status = OrderStatus.CANCELLED.value
        await _release_reserved_stock(session, order)
    await session.commit()


@router.post("/payments/mock/{payment_id}/complete", response_model=OrderRead)
async def complete_mock_payment(
    payment_id: UUID,
    client: CurrentClient,
    session: SessionDep,
    success: bool = Query(default=True),
) -> Order:
    settings = get_settings()
    if settings.payment_provider != "mock" or settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Mock payments are disabled")
    reference = (
        await session.execute(
            select(Payment.id, Payment.order_id).where(
                Payment.id == payment_id, Payment.provider == "mock"
            )
        )
    ).one_or_none()
    if reference is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    order, payment = await _lock_order_and_payment(session, reference.order_id, reference.id)
    if payment is None or order is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if order.client_id != client.id:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.provider != "mock":
        raise HTTPException(status_code=404, detail="Payment not found")
    await _finish_payment(
        session, order, payment, success=success, transaction_id=f"mock-tx-{payment.id}"
    )
    refreshed = await session.scalar(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items), selectinload(Order.payment))
    )
    return refreshed or order


def _hmac_secret() -> str:
    secret = get_settings().paymob_hmac_secret
    if not secret:
        raise HTTPException(
            status_code=503, detail="Paymob callback verification is not configured"
        )
    return secret.get_secret_value()


@router.post("/webhooks/paymob")
async def receive_paymob_callback(
    request: Request,
    session: SessionDep,
    signature: Annotated[str | None, Query(alias="hmac")] = None,
) -> dict[str, bool]:
    settings = get_settings()
    if settings.payment_provider != "paymob":
        raise HTTPException(status_code=404, detail="Paymob integration is disabled")
    try:
        payload: dict[str, Any] = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid callback payload") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid callback payload")
    event_type = payload.get("type")
    token_event = event_type == "TOKEN"
    if event_type not in {"TOKEN", "TRANSACTION"}:
        raise HTTPException(status_code=400, detail="Unsupported callback type")
    if not verify_paymob_callback(payload, signature, _hmac_secret(), token_event=token_event):
        raise HTTPException(status_code=400, detail="Callback signature is invalid")

    obj = payload.get("obj")
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="Invalid callback payload")
    provider_order_id = str(
        obj.get("order_id") if token_event else (obj.get("order") or {}).get("id")
    )
    reference = (
        await session.execute(
            select(Payment.id, Payment.order_id).where(
                Payment.provider == "paymob", Payment.provider_order_id == provider_order_id
            )
        )
    ).one_or_none()
    if reference is None:
        # A valid duplicate or delayed callback should not disclose internal order data.
        return {"received": True}
    order, payment = await _lock_order_and_payment(session, reference.order_id, reference.id)
    if payment is None or order is None:
        # A valid duplicate or delayed callback should not disclose internal order data.
        return {"received": True}

    if token_event:
        if not settings.payment_token_encryption_key:
            raise HTTPException(
                status_code=503, detail="Provider-token encryption is not configured"
            )
        await session.scalar(
            select(Client).where(Client.id == order.client_id).with_for_update(of=Client)
        )
        token = obj.get("token")
        masked_pan = str(obj.get("masked_pan", ""))
        digits = "".join(character for character in masked_pan if character.isdigit())
        last_four = digits[-4:]
        if not isinstance(token, str) or not token or len(last_four) != 4:
            raise HTTPException(
                status_code=400, detail="Card-token callback is missing display metadata"
            )
        fingerprint = token_fingerprint(token)
        saved = await session.scalar(
            select(ClientPaymentMethod).where(
                ClientPaymentMethod.client_id == order.client_id,
                ClientPaymentMethod.provider == "paymob",
                ClientPaymentMethod.token_fingerprint == fingerprint,
            )
        )
        if saved is None:
            # Expiry fields are not covered by the provider's token-event HMAC.
            current_default = await session.scalar(
                select(ClientPaymentMethod.id).where(
                    ClientPaymentMethod.client_id == order.client_id,
                    ClientPaymentMethod.is_default.is_(True),
                    ClientPaymentMethod.is_active.is_(True),
                )
            )
            saved = ClientPaymentMethod(
                client_id=order.client_id,
                provider="paymob",
                provider_method_id_encrypted=encrypt_provider_token(token),
                token_fingerprint=fingerprint,
                brand=str(obj.get("card_subtype") or "Card")[:32],
                last_four=last_four,
                expiry_month=None,
                expiry_year=None,
                is_default=current_default is None,
            )
            session.add(saved)
        await session.commit()
        return {"received": True}

    amount_cents = obj.get("amount_cents")
    try:
        received_amount = Decimal(str(amount_cents)) / 100
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Callback amount is invalid") from None
    if (
        not received_amount.is_finite()
        or received_amount != payment.amount
        or obj.get("currency") != payment.currency
    ):
        raise HTTPException(
            status_code=400, detail="Callback amount or currency does not match the order"
        )
    if obj.get("pending") is True:
        return {"received": True}
    success = bool(obj.get("success")) and not bool(obj.get("error_occured"))
    transaction_id = str(obj.get("id")) if obj.get("id") is not None else None
    await _finish_payment(session, order, payment, success=success, transaction_id=transaction_id)
    return {"received": True}
