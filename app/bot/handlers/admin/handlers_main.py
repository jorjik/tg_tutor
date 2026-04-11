from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.admin.callbacks import AdminMenuCD, BackCD
from app.bot.handlers.admin.keyboards import kb_main_menu
from app.db.session import AsyncSessionLocal
from app.services.admin_service import AdminStats, get_admin_stats

router = Router(name="admin_main")


def _stats_text(stats: AdminStats) -> str:
    return (
        "<b>📊 Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{stats.total_users}</b>\n"
        f"💳 Активных подписок: <b>{stats.active_subscriptions}</b>\n"
        f"💰 Выручка (успешные): <b>{stats.total_revenue:,.2f} RUB</b>"
    )


async def _send_menu(target: Message | CallbackQuery, stats: AdminStats) -> None:
    text = _stats_text(stats)
    kb = kb_main_menu()
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb)
    else:
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
        await target.answer()


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        stats = await get_admin_stats(session)
    await _send_menu(message, stats)


@router.callback_query(AdminMenuCD.filter(F.section == "stats"))
async def cq_stats(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        stats = await get_admin_stats(session)
    await _send_menu(query, stats)


@router.callback_query(BackCD.filter(F.target == "menu"))
async def cq_back_to_menu(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        stats = await get_admin_stats(session)
    await _send_menu(query, stats)
