from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx

from app.config import get_settings
from app.models import Client, Order


class PaymentProviderError(RuntimeError):
    """A payment provider could not create or confirm a checkout."""


@dataclass(frozen=True)
class CheckoutSession:
    provider: str
    provider_order_id: str | None
    checkout_url: str | None


def _minor_units(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


async def create_checkout(
    *,
    payment_id: UUID,
    order: Order,
    client: Client,
    email: str,
    saved_provider_token: str | None = None,
) -> CheckoutSession:
    settings = get_settings()
    if settings.payment_provider == "mock":
        return CheckoutSession(
            provider="mock",
            provider_order_id=f"mock-{payment_id}",
            checkout_url=f"http://localhost:8000/api/v1/payments/mock/{payment_id}/complete",
        )
    if settings.payment_provider != "paymob":
        raise PaymentProviderError("PAYMENT_PROVIDER must be 'mock' or 'paymob'")
    if not all(
        [
            settings.paymob_secret_key,
            settings.paymob_public_key,
            settings.paymob_card_integration_id,
            settings.paymob_notification_url,
            settings.payment_token_encryption_key,
        ]
    ):
        raise PaymentProviderError(
            "Paymob credentials, callback URL, and saved-token encryption key are required"
        )

    billing = {
        "apartment": "NA",
        "first_name": client.first_name,
        "last_name": client.last_name,
        "street": "Infinity order",
        "building": "NA",
        "floor": "NA",
        "city": "Cairo",
        "country": "EG",
        "email": email,
        "phone_number": client.phone,
        "postal_code": "NA",
        "state": "NA",
    }
    if order.shipping_address:
        billing.update(
            {
                "street": order.shipping_address.get("line1", "NA"),
                "apartment": order.shipping_address.get("line2") or "NA",
                "city": order.shipping_address.get("city", "Cairo"),
                "state": order.shipping_address.get("region", "NA"),
                "country": order.shipping_address.get("country", "EG"),
                "postal_code": order.shipping_address.get("postal_code") or "NA",
            }
        )
    request_body: dict[str, Any] = {
        "amount": _minor_units(order.total_amount),
        "currency": order.currency,
        "payment_methods": [settings.paymob_card_integration_id],
        "items": [
            {
                "name": item.product_name_snapshot,
                "amount": _minor_units(item.unit_price),
                "description": item.sku_snapshot,
                "quantity": item.quantity,
            }
            for item in order.items
        ],
        "billing_data": billing,
        "special_reference": str(order.id),
        "expiration": 3600,
        "notification_url": settings.paymob_notification_url,
        "extras": {"infinity_order_id": str(order.id), "payment_id": str(payment_id)},
    }
    if saved_provider_token:
        request_body["card_tokens"] = [saved_provider_token]

    secret = settings.paymob_secret_key.get_secret_value()
    api_base = settings.paymob_api_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client_http:
            response = await client_http.post(
                f"{api_base}/v1/intention/",
                headers={"Authorization": f"Token {secret}"},
                json=request_body,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PaymentProviderError("Paymob could not create the payment checkout") from exc

    client_secret = result.get("client_secret")
    provider_order_id = result.get("intention_order_id")
    if not client_secret or provider_order_id is None:
        raise PaymentProviderError("Paymob returned an incomplete checkout response")
    query = urlencode(
        {"publicKey": settings.paymob_public_key.get_secret_value(), "clientSecret": client_secret}
    )
    checkout_url = f"{settings.paymob_checkout_base_url.rstrip('/')}/?{query}"
    return CheckoutSession("paymob", str(provider_order_id), checkout_url)


_TRANSACTION_HMAC_FIELDS = (
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order_id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
)
_TOKEN_HMAC_FIELDS = (
    "card_subtype",
    "created_at",
    "email",
    "id",
    "masked_pan",
    "merchant_id",
    "order_id",
    "token",
)


def _hmac_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return "" if value is None else str(value)


def _nested(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def paymob_callback_hmac(payload: dict[str, Any], secret: str, *, token_event: bool) -> str:
    obj = payload.get("obj") if isinstance(payload.get("obj"), dict) else {}
    if token_event:
        source = obj
        fields = _TOKEN_HMAC_FIELDS
    else:
        source = dict(obj)
        order = source.get("order") if isinstance(source.get("order"), dict) else {}
        source["order_id"] = order.get("id")
        source["source_data"] = source.get("source_data") or {}
        fields = _TRANSACTION_HMAC_FIELDS
    message = "".join(_hmac_value(_nested(source, field)) for field in fields)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha512).hexdigest()


def verify_paymob_callback(
    payload: dict[str, Any], supplied_hmac: str | None, secret: str, *, token_event: bool
) -> bool:
    if not supplied_hmac:
        return False
    expected = paymob_callback_hmac(payload, secret, token_event=token_event)
    return hmac.compare_digest(expected.lower(), supplied_hmac.lower())
