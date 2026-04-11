from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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
)
from app.bot.handlers.admin.keyboards import (
    FIELD_LABELS,
    kb_plan_create_cancel,
    kb_plan_create_model,
    kb_plan_detail,
    kb_plan_edit_cancel,
    kb_plan_edit_no_limit,
    kb_plan_list,
)
from app.bot.handlers.admin.states import PlanCreateFSM, PlanEditFSM
from app.db.models import Plan
from app.db.session import AsyncSessionLocal
from app.services.admin_service import (
    create_plan,
    delete_plan,
    get_all_plans,
    get_plan_by_id,
    toggle_plan_active,
    update_plan_field,
)

router = Router(name="admin_plans")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _plan_text(plan: Plan) -> str:
    day_limit = str(plan.max_requests_per_day) if plan.max_requests_per_day else "—"
    period_limit = str(plan.max_requests_per_period) if plan.max_requests_per_period else "—"
    active = "Да ✅" if plan.is_active else "Нет ❌"
    stars_str = f"{plan.stars_price} ⭐" if plan.stars_price else "—"
    return (
        f"<b>💼 Тариф: {plan.name}</b>\n\n"
        f"💵 Цена: <b>{plan.price:,.2f} {plan.currency}</b>\n"
        f"⭐ Stars-цена: <b>{stars_str}</b>\n"
        f"📅 Длительность: <b>{plan.duration_days} дн.</b>\n"
        f"🤖 Модель: <b>{plan.openai_model}</b>\n"
        f"📊 Лимит/день: <b>{day_limit}</b>\n"
        f"📊 Лимит/период: <b>{period_limit}</b>\n"
        f"🔢 Сортировка: <b>{plan.sort_order}</b>\n"
        f"✅ Активен: <b>{active}</b>"
    )


async def show_plan_list(query: CallbackQuery) -> None:
    async with AsyncSessionLocal() as session:
        plans = await get_all_plans(session)
    text = "<b>💼 Тарифы</b>" if plans else "<b>💼 Тарифы</b>\n\nПока нет ни одного тарифа."
    try:
        await query.message.edit_text(text, reply_markup=kb_plan_list(plans))
    except TelegramBadRequest:
        pass
    await query.answer()


# ── List ──────────────────────────────────────────────────────────────────────

@router.callback_query(AdminMenuCD.filter(F.section == "plans"))
@router.callback_query(PlanListCD.filter())
async def cq_plan_list(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_plan_list(query)


# ── Detail ────────────────────────────────────────────────────────────────────

@router.callback_query(PlanDetailCD.filter())
async def cq_plan_detail(
    query: CallbackQuery, callback_data: PlanDetailCD, state: FSMContext
) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        plan = await get_plan_by_id(session, callback_data.plan_id)
    if plan is None:
        await query.answer("Тариф не найден.", show_alert=True)
        return
    try:
        await query.message.edit_text(_plan_text(plan), reply_markup=kb_plan_detail(plan))
    except TelegramBadRequest:
        pass
    await query.answer()


# ── Toggle active ─────────────────────────────────────────────────────────────

@router.callback_query(PlanToggleActiveCD.filter())
async def cq_plan_toggle(
    query: CallbackQuery, callback_data: PlanToggleActiveCD
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            plan = await toggle_plan_active(session, callback_data.plan_id)
        except LookupError:
            await query.answer("Тариф не найден.", show_alert=True)
            return
    try:
        await query.message.edit_text(_plan_text(plan), reply_markup=kb_plan_detail(plan))
    except TelegramBadRequest:
        pass
    await query.answer("Статус изменён.")


# ── Delete ────────────────────────────────────────────────────────────────────

@router.callback_query(PlanDeleteCD.filter())
async def cq_plan_delete(
    query: CallbackQuery, callback_data: PlanDeleteCD
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await delete_plan(session, callback_data.plan_id)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
    async with AsyncSessionLocal() as session:
        plans = await get_all_plans(session)
    try:
        await query.message.edit_text(
            "<b>💼 Тарифы</b>\n\n✅ Тариф удалён.",
            reply_markup=kb_plan_list(plans),
        )
    except TelegramBadRequest:
        pass
    await query.answer()


# ── Edit field (FSM) ──────────────────────────────────────────────────────────

@router.callback_query(PlanEditFieldCD.filter())
async def cq_plan_edit_field(
    query: CallbackQuery, callback_data: PlanEditFieldCD, state: FSMContext
) -> None:
    field = callback_data.field
    label = FIELD_LABELS.get(field, field)
    await state.set_state(PlanEditFSM.waiting_for_value)
    await state.update_data(plan_id=callback_data.plan_id, field=field, field_label=label)

    hint = ""
    if field in ("max_day", "max_period"):
        hint = "\nВведите число или нажмите кнопку чтобы убрать ограничение."
        reply_markup = kb_plan_edit_no_limit(callback_data.plan_id, field)
    elif field == "stars_price":
        hint = "\nВведите число Stars > 0 или <code>-</code> чтобы отключить."
        reply_markup = kb_plan_edit_cancel(callback_data.plan_id)
    else:
        reply_markup = kb_plan_edit_cancel(callback_data.plan_id)

    try:
        await query.message.edit_text(
            f"Введите новое значение для <b>{label}</b>.{hint}",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        pass
    await query.answer()


@router.message(PlanEditFSM.waiting_for_value, F.text)
async def fsm_plan_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plan_id: int = data["plan_id"]
    field: str = data["field"]
    raw = (message.text or "").strip()

    async with AsyncSessionLocal() as session:
        try:
            plan = await update_plan_field(session, plan_id, field, raw)
        except (ValueError, LookupError) as exc:
            await message.answer(
                f"⚠️ {exc}\n\nПопробуйте снова или нажмите Отмена.",
                reply_markup=kb_plan_edit_cancel(plan_id),
            )
            return  # stay in FSM state

    await state.clear()
    await message.answer(_plan_text(plan), reply_markup=kb_plan_detail(plan))


@router.callback_query(PlanEditNoLimitCD.filter())
async def cq_plan_edit_no_limit(
    query: CallbackQuery, callback_data: PlanEditNoLimitCD, state: FSMContext
) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        try:
            plan = await update_plan_field(session, callback_data.plan_id, callback_data.field, "-")
        except LookupError:
            await query.answer("Тариф не найден.", show_alert=True)
            return
    try:
        await query.message.edit_text(_plan_text(plan), reply_markup=kb_plan_detail(plan))
    except TelegramBadRequest:
        pass
    await query.answer("Лимит убран.")


@router.callback_query(BackCD.filter(F.target == "plan_detail"))
async def cq_back_to_plan_detail(
    query: CallbackQuery, callback_data: BackCD, state: FSMContext
) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        plan = await get_plan_by_id(session, callback_data.ref_id)
    if plan is None:
        await query.answer("Тариф не найден.", show_alert=True)
        return
    try:
        await query.message.edit_text(_plan_text(plan), reply_markup=kb_plan_detail(plan))
    except TelegramBadRequest:
        pass
    await query.answer()


@router.callback_query(BackCD.filter(F.target == "plan_list"))
async def cq_back_to_plan_list(
    query: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    await show_plan_list(query)


# ── Create wizard (FSM) ───────────────────────────────────────────────────────

_CREATE_STEPS: list[tuple[str, str, str]] = [
    # (fsm_state_name, field_key, prompt)
    ("name", "name", "Введите <b>название</b> тарифа:"),
    ("price", "price", "Введите <b>цену</b> (например 299.00):"),
    ("currency", "currency", "Введите <b>валюту</b> (3 буквы, например RUB):"),
    ("duration_days", "duration_days", "Введите <b>длительность</b> в днях (например 30):"),
    ("openai_model", "openai_model", "Введите <b>модель OpenAI</b> (например gpt-4.1-mini)\nили нажмите кнопку чтобы использовать модель по умолчанию:"),
    ("sort_order", "sort_order", "Введите <b>порядок сортировки</b> (целое число ≥ 0, например 0):"),
    ("stars_price", "stars_price", "Введите <b>Stars-цену</b> (целое число > 0) или <code>-</code> чтобы не принимать Stars:"),
]

_STEP_STATES = [
    PlanCreateFSM.name,
    PlanCreateFSM.price,
    PlanCreateFSM.currency,
    PlanCreateFSM.duration_days,
    PlanCreateFSM.openai_model,
    PlanCreateFSM.sort_order,
    PlanCreateFSM.stars_price,
]

_VALIDATORS: dict[str, type] = {
    "price": Decimal,
}


def _step_header(step_idx: int) -> str:
    total = len(_CREATE_STEPS)
    return f"<b>Создание тарифа — шаг {step_idx + 1}/{total}</b>\n\n"


@router.callback_query(PlanCreateCD.filter())
async def cq_plan_create_start(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PlanCreateFSM.name)
    await state.update_data(_step=0)
    _, _, prompt = _CREATE_STEPS[0]
    try:
        await query.message.edit_text(
            _step_header(0) + prompt,
            reply_markup=kb_plan_create_cancel(),
        )
    except TelegramBadRequest:
        pass
    await query.answer()


@router.callback_query(PlanCreateDefaultModelCD.filter())
async def cq_plan_create_default_model(query: CallbackQuery, state: FSMContext) -> None:
    from app.config import get_settings  # noqa: PLC0415
    default_model = get_settings().openai_model
    step_idx = next(i for i, (_, k, _) in enumerate(_CREATE_STEPS) if k == "openai_model")
    await state.update_data(openai_model=default_model)
    next_idx = step_idx + 1
    _, _, prompt = _CREATE_STEPS[next_idx]
    await state.set_state(_STEP_STATES[next_idx])
    try:
        await query.message.edit_text(
            _step_header(next_idx) + prompt,
            reply_markup=_kb_for_step(next_idx),
        )
    except TelegramBadRequest:
        pass
    await query.answer()


def _kb_for_step(step_idx: int) -> object:
    """Return the appropriate keyboard for showing step `step_idx`."""
    _, field_key, _ = _CREATE_STEPS[step_idx]
    if field_key == "openai_model":
        from app.config import get_settings  # noqa: PLC0415
        return kb_plan_create_model(get_settings().openai_model)
    return kb_plan_create_cancel()


async def _handle_create_step(message: Message, state: FSMContext, step_idx: int) -> None:
    raw = (message.text or "").strip()
    _, field_key, _ = _CREATE_STEPS[step_idx]

    # Validate via admin_service cast logic (reuse update_plan_field logic indirectly)
    from app.services.admin_service import _cast_field  # noqa: PLC0415

    try:
        value = _cast_field(field_key, raw)
    except ValueError as exc:
        await message.answer(
            f"⚠️ {exc}\n\nПопробуйте снова или нажмите Отмена.",
            reply_markup=_kb_for_step(step_idx),
        )
        return

    await state.update_data(**{field_key: value})
    next_idx = step_idx + 1

    if next_idx < len(_CREATE_STEPS):
        _, _, prompt = _CREATE_STEPS[next_idx]
        await state.set_state(_STEP_STATES[next_idx])
        await message.answer(
            _step_header(next_idx) + prompt,
            reply_markup=_kb_for_step(next_idx),
        )
    else:
        # All steps done — create the plan
        data = await state.get_data()
        kwargs = {k: data[k] for _, k, _ in _CREATE_STEPS if k in data}
        # Map wizard keys to model attrs
        if "max_day" in kwargs:
            kwargs["max_requests_per_day"] = kwargs.pop("max_day")
        if "max_period" in kwargs:
            kwargs["max_requests_per_period"] = kwargs.pop("max_period")
        if "openai_model" not in kwargs and "model" in kwargs:
            kwargs["openai_model"] = kwargs.pop("model")

        async with AsyncSessionLocal() as session:
            plan = await create_plan(session, **kwargs)

        await state.clear()
        await message.answer(
            f"✅ Тариф <b>{plan.name}</b> создан!\n\n" + _plan_text(plan),
            reply_markup=kb_plan_detail(plan),
        )


# ── Cancel wizard via command ─────────────────────────────────────────────────

@router.message(StateFilter(PlanCreateFSM, PlanEditFSM), Command("stop", "cancel", "отмена"))
async def cmd_cancel_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Действие отменено.")


# Generate one handler per create FSM state
for _idx, (_state_name, _field, _prompt) in enumerate(_CREATE_STEPS):
    _state = _STEP_STATES[_idx]
    _captured_idx = _idx

    @router.message(StateFilter(_state), F.text)
    async def _create_step_handler(
        message: Message,
        state: FSMContext,
        _step_idx: int = _captured_idx,
    ) -> None:
        await _handle_create_step(message, state, _step_idx)
