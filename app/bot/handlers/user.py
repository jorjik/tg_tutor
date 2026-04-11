from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.admin_service import get_all_plans
from app.services.chat_service import get_or_create_user
from app.services.subscription_service import (
    ActiveSubscription,
    check_limits,
    get_active_subscription,
    get_usage_since,
    get_usage_today,
)

logger = logging.getLogger(__name__)

router = Router(name="user")


# ── Callback data ─────────────────────────────────────────────────────────────

class SelectPlanCD(CallbackData, prefix="sub_sel"):
    plan_id: int


# ── /status ───────────────────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not message.from_user:
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            locale=message.from_user.language_code,
        )
        await session.commit()

        active_sub: ActiveSubscription | None = await get_active_subscription(session, user.id)

        if active_sub is None:
            await message.answer(
                "📋 <b>Ваша подписка</b>\n\n"
                "У вас нет активной подписки.\n"
                "Используйте /subscribe, чтобы оформить подписку."
            )
            return

        sub = active_sub.subscription
        plan = active_sub.plan
        ends = sub.ends_at.strftime("%d.%m.%Y")

        # Счётчики использования
        today_count = await get_usage_today(session, user.id)
        period_count = await get_usage_since(session, user.id, sub.starts_at)

        day_limit_str = str(plan.max_requests_per_day) if plan.max_requests_per_day else "∞"
        period_limit_str = str(plan.max_requests_per_period) if plan.max_requests_per_period else "∞"

    text = (
        "📋 <b>Ваша подписка</b>\n\n"
        f"Тариф: <b>{plan.name}</b>\n"
        f"Действует до: <b>{ends}</b>\n"
        f"Модель ИИ: <b>{plan.openai_model}</b>\n\n"
        f"Запросов сегодня: <b>{today_count} / {day_limit_str}</b>\n"
        f"Запросов за период: <b>{period_count} / {period_limit_str}</b>"
    )
    await message.answer(text)


# ── /subscribe ────────────────────────────────────────────────────────────────

def _plan_kb(plans: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in plans:
        b.button(
            text=f"{plan.name} — {plan.price:,.0f} {plan.currency} / {plan.duration_days} дн.",
            callback_data=SelectPlanCD(plan_id=plan.id),
        )
    b.adjust(1)
    return b.as_markup()


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    async with AsyncSessionLocal() as session:
        plans = await get_all_plans(session)

    active_plans = [p for p in plans if p.is_active]

    if not active_plans:
        await message.answer("Сейчас нет доступных тарифов. Попробуйте позже.")
        return

    await message.answer(
        "💳 <b>Выберите тариф:</b>",
        reply_markup=_plan_kb(active_plans),
    )


@router.callback_query(SelectPlanCD.filter())
async def cq_select_plan(query: CallbackQuery, callback_data: SelectPlanCD) -> None:
    if not query.from_user:
        await query.answer()
        return

    settings = get_settings()

    async with AsyncSessionLocal() as session:
        from app.services.admin_service import get_plan_by_id
        plan = await get_plan_by_id(session, callback_data.plan_id)

    if plan is None or not plan.is_active:
        await query.answer("Тариф недоступен.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()

    if settings.payments_configured:
        from app.services.payments import get_provider
        try:
            provider = get_provider(settings)
            payment_url = await provider.create_payment(
                telegram_id=query.from_user.id,
                plan_id=plan.id,
                amount=plan.price,
                currency=plan.currency,
                description=f"Подписка «{plan.name}» на {plan.duration_days} дней",
                return_url=settings.payment_return_url,
            )
            provider_name = "Stripe" if settings.payment_provider == "stripe" else "ЮKassa"
            kb.button(text=f"💳 Оплатить картой ({provider_name})", url=payment_url)
        except Exception:
            logger.exception("Ошибка создания платежа")

    if plan.stars_price is not None:
        from app.bot.handlers.stars import PayStarsCD
        kb.button(
            text=f"⭐ Оплатить {plan.stars_price} Stars",
            callback_data=PayStarsCD(plan_id=plan.id),
        )

    kb.adjust(1)

    if not kb.buttons:
        await query.answer("Оплата временно недоступна. Обратитесь к администратору.", show_alert=True)
        return

    stars_str = f" или {plan.stars_price} ⭐" if plan.stars_price else ""
    await query.message.edit_text(
        f"💳 <b>Тариф «{plan.name}»</b>\n\n"
        f"Стоимость: <b>{plan.price:,.2f} {plan.currency}{stars_str}</b>\n"
        f"Срок: <b>{plan.duration_days} дней</b>\n\n"
        "Выберите способ оплаты. После успешной оплаты подписка активируется автоматически.",
        reply_markup=kb.as_markup(),
    )
    await query.answer()
