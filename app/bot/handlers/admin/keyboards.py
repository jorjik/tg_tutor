from __future__ import annotations

from math import ceil

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.handlers.admin.callbacks import (
    AdminMenuCD,
    BackCD,
    PlanCreateCD,
    PlanCreateDefaultModelCD,
    PlanDeleteCD,
    PlanDetailCD,
    PlanEditFieldCD,
    PlanEditNoLimitCD,
    PlanListCD,
    PlanToggleActiveCD,
    UserAddFreeCancelCD,
    UserAddFreePickPlanCD,
    UserAddFreeStartCD,
    UserDetailCD,
    UserListCD,
)
from app.db.models import Plan
from app.services.admin_service import UserRow

# Field label mapping for plan edit buttons
FIELD_LABELS: dict[str, str] = {
    "name": "Название",
    "price": "Цена",
    "currency": "Валюта",
    "duration_days": "Длительность (дней)",
    "max_day": "Лимит в день",
    "max_period": "Лимит за период",
    "openai_model": "Модель ИИ",
    "sort_order": "Порядок сортировки",
    "stars_price": "Stars-цена (⭐)",
}


# ── Main menu ─────────────────────────────────────────────────────────────────

def kb_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика", callback_data=AdminMenuCD(section="stats"))
    b.button(text="💼 Тарифы", callback_data=AdminMenuCD(section="plans"))
    b.button(text="👥 Пользователи", callback_data=AdminMenuCD(section="users"))
    b.adjust(3)
    return b.as_markup()


# ── Plans list ────────────────────────────────────────────────────────────────

def kb_plan_list(plans: list[Plan]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in plans:
        status = "✅" if plan.is_active else "❌"
        b.button(
            text=f"{status} {plan.name}",
            callback_data=PlanDetailCD(plan_id=plan.id),
        )
    b.adjust(1)
    b.button(text="➕ Создать тариф", callback_data=PlanCreateCD())
    b.button(text="🔙 Меню", callback_data=BackCD(target="menu"))
    b.adjust(1)
    return b.as_markup()


# ── Plan detail ───────────────────────────────────────────────────────────────

def kb_plan_detail(plan: Plan) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    fields = ["name", "price", "currency", "duration_days", "openai_model", "max_day", "max_period", "sort_order", "stars_price"]
    for field in fields:
        b.button(
            text=f"✏️ {FIELD_LABELS[field]}",
            callback_data=PlanEditFieldCD(plan_id=plan.id, field=field),
        )
    b.adjust(2)
    active_label = "🔴 Деактивировать" if plan.is_active else "🟢 Активировать"
    b.button(text=active_label, callback_data=PlanToggleActiveCD(plan_id=plan.id))
    b.button(text="🗑 Удалить", callback_data=PlanDeleteCD(plan_id=plan.id))
    b.button(text="🔙 К тарифам", callback_data=PlanListCD())
    b.adjust(1)
    return b.as_markup()


def kb_plan_edit_cancel(plan_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="❌ Отмена",
        callback_data=BackCD(target="plan_detail", ref_id=plan_id),
    )
    return b.as_markup()


def kb_plan_create_cancel() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Отменить создание", callback_data=PlanListCD())
    return b.as_markup()


def kb_plan_edit_no_limit(plan_id: int, field: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="♾ Без лимита", callback_data=PlanEditNoLimitCD(plan_id=plan_id, field=field))
    b.button(text="❌ Отмена", callback_data=BackCD(target="plan_detail", ref_id=plan_id))
    b.adjust(1)
    return b.as_markup()


def kb_plan_create_model(default_model: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"🤖 По умолчанию ({default_model})", callback_data=PlanCreateDefaultModelCD())
    b.button(text="❌ Отменить создание", callback_data=PlanListCD())
    b.adjust(1)
    return b.as_markup()


# ── Users ─────────────────────────────────────────────────────────────────────

def kb_user_list(
    rows: list[UserRow],
    page: int,
    total: int,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for row in rows:
        name = f"@{row.username}" if row.username else f"id:{row.telegram_id}"
        status = ""
        if row.sub_status == "active":
            status = " ✅"
        elif row.sub_status == "expired":
            status = " ⏱"
        b.button(
            text=f"👤 {name}{status}",
            callback_data=UserDetailCD(user_id=row.id),
        )
    b.adjust(1)

    total_pages = max(1, ceil(total / page_size))
    nav_row = []
    if page > 0:
        nav_row.append(("◀ Назад", UserListCD(page=page - 1)))
    nav_row.append((f"{page + 1}/{total_pages}", BackCD(target="menu")))  # non-action counter
    if page < total_pages - 1:
        nav_row.append(("Вперёд ▶", UserListCD(page=page + 1)))

    for label, cb in nav_row:
        b.button(text=label, callback_data=cb)
    b.adjust(len(nav_row))

    b.button(text="➕ Бесплатный доступ", callback_data=UserAddFreeStartCD())
    b.button(text="🔙 Меню", callback_data=BackCD(target="menu"))
    b.adjust(1)
    return b.as_markup()


def kb_user_add_free_cancel() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Отмена", callback_data=UserAddFreeCancelCD())
    return b.as_markup()


def kb_user_add_free_plans(plans: list[Plan]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in plans:
        b.button(
            text=f"💼 {plan.name} ({plan.duration_days} дн.)",
            callback_data=UserAddFreePickPlanCD(plan_id=plan.id),
        )
    b.adjust(1)
    b.button(text="❌ Отмена", callback_data=UserAddFreeCancelCD())
    b.adjust(1)
    return b.as_markup()


def kb_user_detail(page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="🔙 К списку",
        callback_data=BackCD(target="user_list", ref_id=page),
    )
    return b.as_markup()
