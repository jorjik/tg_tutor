from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from uuid import uuid4

from app.services.payments.base import PaymentProvider, WebhookResult

logger = logging.getLogger(__name__)


class YooKassaProvider(PaymentProvider):
    """ЮKassa (yookassa.ru). Тестовый контур: shop_id=100500, secret_key=test_..."""

    def __init__(self, shop_id: str, secret_key: str) -> None:
        self._shop_id = shop_id
        self._secret_key = secret_key

    def _configure(self) -> None:
        from yookassa import Configuration  # type: ignore[import-untyped]
        Configuration.account_id = self._shop_id
        Configuration.secret_key = self._secret_key

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
        idempotency_key = str(uuid4())

        def _sync() -> str:
            self._configure()
            from yookassa import Payment  # type: ignore[import-untyped]
            payment = Payment.create(
                {
                    "amount": {"value": f"{amount:.2f}", "currency": currency},
                    "confirmation": {
                        "type": "redirect",
                        "return_url": return_url,
                    },
                    "capture": True,
                    "description": description,
                    "metadata": {
                        "telegram_id": str(telegram_id),
                        "plan_id": str(plan_id),
                    },
                },
                idempotency_key,
            )
            return payment.confirmation.confirmation_url

        return await asyncio.to_thread(_sync)

    async def parse_webhook(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> WebhookResult | None:
        """Разбирает вебхук ЮKassa.

        ЮKassa не использует HMAC-подпись в заголовках — рекомендует
        проверять IP отправителя (список на yookassa.ru/developers).
        Дополнительная верификация: перечитываем платёж по ID через API.
        """
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Невалидный JSON в теле вебхука: {exc}") from exc

        event_type = payload.get("type")
        if event_type != "notification":
            return None

        obj = payload.get("object", {})
        obj_type = obj.get("type")  # "payment"
        status = obj.get("status")  # "succeeded" / "canceled" / etc.

        if obj_type != "payment" or status != "succeeded":
            return None

        payment_id = obj.get("id", "")
        meta = obj.get("metadata") or {}
        telegram_id_str = meta.get("telegram_id", "")
        plan_id_str = meta.get("plan_id", "")

        if not telegram_id_str or not plan_id_str:
            logger.warning("YooKassa webhook: missing metadata telegram_id/plan_id")
            return None

        # Верифицируем через API: перечитываем платёж
        try:
            verified = await self._verify_payment(payment_id)
        except Exception:
            logger.exception("YooKassa: не удалось верифицировать платёж %s", payment_id)
            raise ValueError("Не удалось верифицировать платёж через ЮKassa API")

        if not verified:
            return None

        amount_obj = obj.get("amount", {})
        amount = Decimal(str(amount_obj.get("value", "0")))
        currency = (amount_obj.get("currency") or "RUB").upper()

        return WebhookResult(
            provider_payment_id=payment_id,
            telegram_id=int(telegram_id_str),
            plan_id=int(plan_id_str),
            amount=amount,
            currency=currency,
            succeeded=True,
        )

    async def _verify_payment(self, payment_id: str) -> bool:
        """Перечитывает платёж из API и проверяет статус."""
        def _sync() -> bool:
            self._configure()
            from yookassa import Payment  # type: ignore[import-untyped]
            payment = Payment.find_one(payment_id)
            return payment.status == "succeeded"

        return await asyncio.to_thread(_sync)
