from aiogram.filters.callback_data import CallbackData


class AdminMenuCD(CallbackData, prefix="adm"):
    section: str  # "stats" | "plans" | "users"


class PlanListCD(CallbackData, prefix="adm_pl"):
    pass


class PlanDetailCD(CallbackData, prefix="adm_pd"):
    plan_id: int


class PlanEditFieldCD(CallbackData, prefix="adm_pef"):
    plan_id: int
    field: str  # "name"|"price"|"currency"|"duration_days"|"max_day"|"max_period"|"model"|"sort_order"


class PlanToggleActiveCD(CallbackData, prefix="adm_pta"):
    plan_id: int


class PlanCreateCD(CallbackData, prefix="adm_pc"):
    pass


class PlanDeleteCD(CallbackData, prefix="adm_pdel"):
    plan_id: int


class UserListCD(CallbackData, prefix="adm_ul"):
    page: int  # 0-based


class UserDetailCD(CallbackData, prefix="adm_ud"):
    user_id: int  # internal DB id


class BackCD(CallbackData, prefix="adm_bk"):
    target: str  # "menu" | "plan_list" | "plan_detail" | "user_list"
    ref_id: int = 0  # plan_id or page number when relevant


class PlanCreateDefaultModelCD(CallbackData, prefix="adm_pcdm"):
    pass


class PlanCreateNoLimitCD(CallbackData, prefix="adm_pcnl"):
    field: str  # "max_day" | "max_period"
