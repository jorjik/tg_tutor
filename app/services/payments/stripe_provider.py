from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from uuid import uuid4

import stripe as stripe_lib

from app.services.payments.base import PaymentProvider, WebhookResult

logger = logging.getLogger(__name__)

# Stripe считает суммы в минимальных единицах валюты (копейки/центы).
# Для RUB 1 рубль = 100 копеек, для USD 1 доллар = 100 центов.
_ZERO_DECIMAL_CURRENCIES = {"bif", "clp", "gnf", "jpy", "kmf", "krw",
                             "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof"}


def _to_stripe_amount(amount: Decimal, currency: str) -> int:
    if currency.lower() in _ZERO_DECIMAL_CURRENCIES:
        return int(amount)
    return int(amount * 100)


class StripeProvider(PaymentProvider):
    """Stripe Checkout Sessions (sandbox: тестовые ключи из dashboard.stripe.com)."""

    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key

    def _client(self) -> stripe_lib.StripeClient:
        return stripe_lib.StripeClient(self._secret_key)

    async def create_payment(
        self,
        *,
        telegram_id: int,
        plan_id: int,
        amount: Decimal,
        currency: str,
        description: str,
        return_url: str,
    ) -> str:
        """Создаёт Stripe Checkout Session и возвращает URL оплаты."""
        idempotency_key = str(uuid4())
        stripe_amount = _to_stripe_amount(amount, currency)

        def _sync() -> stripe_lib.checkout.Session:
            client = self._client()
            return client.checkout.sessions.create(
                params={
                    "mode": "payment",
                    "line_items": [
                        {
                            "price_data": {
                                "currency": currency.lower(),
                                "product_data": {"name": description},
                                "unit_amount": stripe_amount,
                            },
                            "quantity": 1,
                        }
                    ],
                    "metadata": {
                        "telegram_id": str(telegram_id),
                        "plan_id": str(plan_id),
                    },
                    "success_url": return_url,
                    "cancel_url": return_url,
                },
                options={"idempotency_key": idempotency_key},
            )

        session = await asyncio.to_thread(_sync)
        return session.url  # type: ignore[return-value]

    async def parse_webhook(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> WebhookResult | None:
        """Верифицирует Stripe webhook и возвращает результат.

        Stripe подписывает тело запроса через заголовок Stripe-Signature.
        Если STRIPE_WEBHOOK_SECRET не задан — верификация пропускается (только для dev).
        """
        from app.config import get_settings
        webhook_secret = get_settings().stripe_webhook_secret

        sig_header = headers.get("stripe-signature", "")

        def _construct() -> stripe_lib.Event:
            if webhook_secret:
                return stripe_lib.Webhook.construct_event(
                    body, sig_header, webhook_secret
                )
            # dev-режим: разбираем тело без верификации подписи
            import json
            return stripe_lib.Event.construct_from(
                json.loads(body), stripe_lib.api_key
            )

        try:
            event = await asyncio.to_thread(_construct)
        except stripe_lib.error.SignatureVerificationError as exc:
            raise ValueError(f"Stripe signature invalid: {exc}") from exc

        if event["type"] != "checkout.session.completed":
            return None

        session = event["data"]["object"]
        if session.get("payment_status") != "paid":
            return None

        meta = session.get("metadata") or {}
        telegram_id_str = meta.get("telegram_id", "")
        plan_id_str = meta.get("plan_id", "")

        if not telegram_id_str or not plan_id_str:
            logger.warning("Stripe webhook: missing metadata telegram_id/plan_id")
            return None

        currency = (session.get("currency") or "usd").upper()
        amount_total = session.get("amount_total") or 0
        if currency.lower() in _ZERO_DECIMAL_CURRENCIES:
            amount = Decimal(amount_total)
        else:
            amount = Decimal(amount_total) / 100

        return WebhookResult(
            provider_payment_id=session["id"],
            telegram_id=int(telegram_id_str),
            plan_id=int(plan_id_str),
            amount=amount,
            currency=currency,
            succeeded=True,
        )
