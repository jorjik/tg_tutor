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
    max_day = State()     # max_requests_per_day  — "-" or int
    max_period = State()  # max_requests_per_period — "-" or int
    sort_order = State()
    stars_price = State()  # Stars-цена — целое число > 0 или "-"
