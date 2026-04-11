from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery
from aiogram.types import CallbackQuery

from app.db.session import AsyncSessionLocal
from app.services.admin_service import get_plan_by_id
from app.services.subscription_service import activate_subscription

logger = logging.getLogger(__name__)

router = Router(name="stars")


class PayStarsCD(CallbackData, prefix="pay_stars"):
    plan_id: int


@router.callback_query(PayStarsCD.filter())
async def cq_pay_stars(
    query: CallbackQuery, callback_data: PayStarsCD, bot: Bot
) -> None:
    async with AsyncSessionLocal() as session:
        plan = await get_plan_by_id(session, callback_data.plan_id)

    if plan is None or not plan.is_active or plan.stars_price is None:
        await query.answer("Тариф недоступен.", show_alert=True)
        return

    await bot.send_invoice(
        chat_id=query.from_user.id,
        title=plan.name,
        description=f"Подписка «{plan.name}» на {plan.duration_days} дней",
        payload=f"plan:{plan.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=plan.name, amount=plan.stars_price)],
    )
    await query.answer()


@router.pre_checkout_query()
async def on_pre_checkout_query(query: PreCheckoutQuery) -> None:
    try:
        plan_id = int(query.invoice_payload.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer(ok=False, error_message="Неверный платёж.")
        return

    async with AsyncSessionLocal() as session:
        plan = await get_plan_by_id(session, plan_id)

    if plan is None or not plan.is_active or plan.stars_price is None:
        await query.answer(ok=False, error_message="Тариф недоступен.")
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    try:
        plan_id = int(sp.invoice_payload.split(":", 1)[1])
    except (ValueError, IndexError):
        logger.error("Stars: невозможно разобрать payload: %s", sp.invoice_payload)
        return

    await activate_subscription(
        telegram_id=message.from_user.id,
        plan_id=plan_id,
        provider="stars",
        provider_payment_id=sp.telegram_payment_charge_id,
        amount=Decimal(sp.total_amount),
        currency="XTR",
        raw_payload=sp.model_dump(),
    )

    await message.answer(
        "⭐ Оплата звёздами прошла успешно!\n"
        "Подписка активирована. Используйте /status для проверки."
    )
