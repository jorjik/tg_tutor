from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class WebhookResult:
    """Результат разбора входящего вебхука."""
    provider_payment_id: str  # уникальный ID платежа у провайдера
    telegram_id: int
    plan_id: int
    amount: Decimal
    currency: str
    succeeded: bool           # True = платёж прошёл, False = отклонён/ошибка


class PaymentProvider(ABC):

    @abstractmethod
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
        """Создаёт платёж и возвращает URL для оплаты."""

    @abstractmethod
    async def parse_webhook(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> WebhookResult | None:
        """Разбирает тело вебхука.

        Возвращает WebhookResult если платёж определён,
        None — если событие нерелевантно (например, не payment.succeeded).
        Выбрасывает ValueError при неверной подписи.
        """
