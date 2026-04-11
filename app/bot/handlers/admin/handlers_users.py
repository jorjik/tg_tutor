from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.handlers.admin.callbacks import AdminMenuCD, BackCD, UserDetailCD, UserListCD
from app.bot.handlers.admin.keyboards import kb_user_detail, kb_user_list
from app.db.session import AsyncSessionLocal
from app.services.admin_service import UserDetail, get_user_detail, get_users_page

router = Router(name="admin_users")

_PAGE_SIZE = 8


def _user_list_text(total: int, page: int, page_size: int) -> str:
    total_pages = max(1, ceil(total / page_size))
    return (
        f"<b>👥 Пользователи</b>\n"
        f"Страница {page + 1}/{total_pages} · всего: {total}"
    )


def _user_detail_text(detail: UserDetail) -> str:
    username_str = f"@{detail.username}" if detail.username else "—"
    locale_str = detail.locale or "—"
    reg_date = detail.created_at.strftime("%d.%m.%Y")

    sub_block = "<i>Нет подписки</i>"
    if detail.sub_plan_name:
        ends = detail.sub_ends_at.strftime("%d.%m.%Y") if detail.sub_ends_at else "—"
        sub_block = (
            f"Тариф: <b>{detail.sub_plan_name}</b>\n"
            f"  Статус: <b>{detail.sub_status}</b>\n"
            f"  До: <b>{ends}</b>"
        )

    return (
        "<b>👤 Пользователь</b>\n\n"
        f"Telegram ID: <code>{detail.telegram_id}</code>\n"
        f"Username: <b>{username_str}</b>\n"
        f"Локаль: {locale_str}\n"
        f"Зарегистрирован: {reg_date}\n\n"
        f"<b>Подписка:</b>\n{sub_block}\n\n"
        "<b>Активность:</b>\n"
        f"  Сообщений в истории: <b>{detail.message_count}</b>\n"
        f"  Запросов всего: <b>{detail.total_requests}</b>"
    )


async def show_user_page(query: CallbackQuery, page: int) -> None:
    async with AsyncSessionLocal() as session:
        rows, total = await get_users_page(session, page, _PAGE_SIZE)

    total_pages = max(1, ceil(total / _PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))

    text = _user_list_text(total, page, _PAGE_SIZE)
    kb = kb_user_list(rows, page=page, total=total, page_size=_PAGE_SIZE)
    try:
        await query.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await query.answer()


@router.callback_query(AdminMenuCD.filter(F.section == "users"))
async def cq_users_entry(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_user_page(query, page=0)


@router.callback_query(UserListCD.filter())
async def cq_user_list(query: CallbackQuery, callback_data: UserListCD) -> None:
    await show_user_page(query, page=callback_data.page)


@router.callback_query(UserDetailCD.filter())
async def cq_user_detail(
    query: CallbackQuery, callback_data: UserDetailCD, state: FSMContext
) -> None:
    async with AsyncSessionLocal() as session:
        detail = await get_user_detail(session, callback_data.user_id)
    if detail is None:
        await query.answer("Пользователь не найден.", show_alert=True)
        return

    # Remember which page to go back to (stored in FSM data, default 0)
    data = await state.get_data()
    page = data.get("user_list_page", 0)
    await state.update_data(user_list_page=page)

    try:
        await query.message.edit_text(
            _user_detail_text(detail),
            reply_markup=kb_user_detail(page=page),
        )
    except TelegramBadRequest:
        pass
    await query.answer()


@router.callback_query(BackCD.filter(F.target == "user_list"))
async def cq_back_to_user_list(
    query: CallbackQuery, callback_data: BackCD, state: FSMContext
) -> None:
    await show_user_page(query, page=callback_data.ref_id)
