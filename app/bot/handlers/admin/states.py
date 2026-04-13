from aiogram.fsm.state import State, StatesGroup


class PlanEditFSM(StatesGroup):
    """Editing a single field of an existing plan.

    State data keys: plan_id (int), field (str), field_label (str).
    """

    waiting_for_value = State()


class PlanCreateFSM(StatesGroup):
    """Sequential wizard for creating a new plan."""

    name = State()
    price = State()
    currency = State()
    duration_days = State()
    openai_model = State()
    sort_order = State()
    stars_price = State()  # Stars-цена — целое число > 0 или "-"


class UserAddFreeFSM(StatesGroup):
    """Wizard for granting a free subscription to a user."""

    waiting_for_telegram_id = State()
    waiting_for_plan = State()
