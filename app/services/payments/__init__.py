from __future__ import annotations

from app.services.payments.base import PaymentProvider
from app.services.payments.stripe_provider import StripeProvider
from app.services.payments.yookassa_provider import YooKassaProvider


def get_provider(settings) -> PaymentProvider:  # type: ignore[type-arg]
    """Возвращает провайдер оплаты согласно настройке PAYMENT_PROVIDER."""
    if settings.payment_provider == "yookassa":
        return YooKassaProvider(
            shop_id=settings.yookassa_shop_id,
            secret_key=settings.yookassa_secret_key,
        )
    return StripeProvider(secret_key=settings.stripe_secret_key)


__all__ = ["PaymentProvider", "StripeProvider", "YooKassaProvider", "get_provider"]
