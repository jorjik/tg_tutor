from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db.session import AsyncSessionLocal
from app.services.admin_service import (
    create_plan,
    delete_plan,
    get_all_plans,
    get_plan_by_id,
    toggle_plan_active,
)
from app.web.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Annotated[str, Depends(require_admin)]

# ── Шаблонизатор (inline HTML, без Jinja2) ────────────────────────────────────

_CSS = """
<meta charset="UTF-8">
<style>
  body{font-family:sans-serif;max-width:960px;margin:40px auto;padding:0 20px;color:#111}
  h1{margin-bottom:4px}nav{margin-bottom:16px}a{color:#0070f3;text-decoration:none}
  a:hover{text-decoration:underline}
  table{border-collapse:collapse;width:100%}
  td,th{border:1px solid #ddd;padding:8px 12px;text-align:left}
  th{background:#f5f5f5}tr:hover{background:#fafafa}
  .btn{display:inline-block;padding:6px 14px;border:none;border-radius:4px;
       cursor:pointer;font-size:14px;text-decoration:none}
  .btn-primary{background:#0070f3;color:#fff}.btn-primary:hover{background:#005fd6}
  .btn-danger{background:#e11d48;color:#fff}.btn-danger:hover{background:#c0153a}
  .btn-sm{padding:4px 10px;font-size:13px}
  .form-group{margin-bottom:14px}
  label{display:block;margin-bottom:4px;font-weight:600}
  input,select{padding:7px 10px;width:100%;box-sizing:border-box;border:1px solid #ccc;
               border-radius:4px;font-size:14px}
  .badge-active{color:#16a34a;font-weight:600}
  .badge-inactive{color:#dc2626;font-weight:600}
  .alert{padding:10px 16px;border-radius:4px;margin-bottom:16px}
  .alert-error{background:#fef2f2;border:1px solid #fca5a5;color:#991b1b}
</style>
"""


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!DOCTYPE html><html lang="ru"><head>{_CSS}<title>{title} — Админ</title></head>
<body>
<h1>{title}</h1>
<nav><a href="/admin/">← Все тарифы</a></nav><hr>
{body}
</body></html>"""
    return HTMLResponse(html)


def _plan_row(plan) -> str:  # type: ignore[type-arg]
    active = '<span class="badge-active">✅ Да</span>' if plan.is_active else '<span class="badge-inactive">❌ Нет</span>'
    day = plan.max_requests_per_day or "—"
    period = plan.max_requests_per_period or "—"
    return (
        f"<tr>"
        f"<td>{plan.id}</td>"
        f"<td>{plan.name}</td>"
        f"<td>{plan.price:,.2f} {plan.currency}</td>"
        f"<td>{plan.duration_days} дн.</td>"
        f"<td>{plan.openai_model}</td>"
        f"<td>{day}</td><td>{period}</td>"
        f"<td>{active}</td>"
        f"<td>"
        f'<a class="btn btn-primary btn-sm" href="/admin/plans/{plan.id}/edit">Ред.</a> '
        f'<a class="btn btn-sm" style="background:#6b7280;color:#fff" '
        f'   href="/admin/plans/{plan.id}/toggle">Вкл/Выкл</a> '
        f'<form style="display:inline" method="post" action="/admin/plans/{plan.id}/delete"'
        f'      onsubmit="return confirm(\'Удалить тариф?\');">'
        f'  <button class="btn btn-danger btn-sm" type="submit">Удалить</button>'
        f'</form>'
        f"</td>"
        f"</tr>"
    )


# ── GET /admin/ ───────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_index(_: AdminDep) -> HTMLResponse:
    async with AsyncSessionLocal() as session:
        plans = await get_all_plans(session)

    rows = "\n".join(_plan_row(p) for p in plans) if plans else (
        '<tr><td colspan="9" style="text-align:center;color:#888">Нет тарифов</td></tr>'
    )
    body = f"""
<p><a class="btn btn-primary" href="/admin/plans/create">➕ Создать тариф</a></p>
<table>
  <thead><tr>
    <th>ID</th><th>Название</th><th>Цена</th><th>Срок</th>
    <th>Модель ИИ</th><th>Лимит/день</th><th>Лимит/период</th>
    <th>Активен</th><th>Действия</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    return _page("Тарифы", body)


# ── GET /admin/plans/create ───────────────────────────────────────────────────

@router.get("/plans/create", response_class=HTMLResponse)
async def admin_plan_create_form(_: AdminDep, error: str = "") -> HTMLResponse:
    err_block = f'<div class="alert alert-error">{error}</div>' if error else ""
    body = f"""
{err_block}
<form method="post" action="/admin/plans/create">
  <div class="form-group"><label>Название</label><input name="name" required></div>
  <div class="form-group"><label>Цена</label><input name="price" type="number" step="0.01" min="0.01" required></div>
  <div class="form-group"><label>Валюта</label>
    <select name="currency"><option value="RUB">RUB</option><option value="USD">USD</option><option value="EUR">EUR</option></select>
  </div>
  <div class="form-group"><label>Длительность (дней)</label><input name="duration_days" type="number" min="1" required></div>
  <div class="form-group"><label>Модель OpenAI</label><input name="openai_model" value="gpt-4.1-mini" required></div>
  <div class="form-group"><label>Лимит запросов/день (пусто = без лимита)</label><input name="max_day" type="number" min="1"></div>
  <div class="form-group"><label>Лимит запросов/период (пусто = без лимита)</label><input name="max_period" type="number" min="1"></div>
  <div class="form-group"><label>Порядок сортировки</label><input name="sort_order" type="number" min="0" value="0" required></div>
  <button class="btn btn-primary" type="submit">Создать</button>
</form>"""
    return _page("Создать тариф", body)


@router.post("/plans/create")
async def admin_plan_create(
    _: AdminDep,
    name: Annotated[str, Form()],
    price: Annotated[str, Form()],
    currency: Annotated[str, Form()] = "RUB",
    duration_days: Annotated[int, Form()] = 30,
    openai_model: Annotated[str, Form()] = "gpt-4.1-mini",
    max_day: Annotated[str | None, Form()] = None,
    max_period: Annotated[str | None, Form()] = None,
    sort_order: Annotated[int, Form()] = 0,
) -> RedirectResponse:
    try:
        price_dec = Decimal(price)
        if price_dec <= 0:
            raise ValueError("Цена должна быть > 0")
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    max_day_int: int | None = int(max_day) if max_day and max_day.strip() else None
    max_period_int: int | None = int(max_period) if max_period and max_period.strip() else None

    async with AsyncSessionLocal() as session:
        await create_plan(
            session,
            name=name.strip(),
            price=price_dec,
            currency=currency.upper()[:3],
            duration_days=duration_days,
            openai_model=openai_model.strip(),
            max_requests_per_day=max_day_int,
            max_requests_per_period=max_period_int,
            sort_order=sort_order,
        )
    return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


# ── GET/POST /admin/plans/{id}/edit ──────────────────────────────────────────

@router.get("/plans/{plan_id}/edit", response_class=HTMLResponse)
async def admin_plan_edit_form(_: AdminDep, plan_id: int, error: str = "") -> HTMLResponse:
    async with AsyncSessionLocal() as session:
        plan = await get_plan_by_id(session, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    err_block = f'<div class="alert alert-error">{error}</div>' if error else ""
    md = plan.max_requests_per_day or ""
    mp = plan.max_requests_per_period or ""
    body = f"""
{err_block}
<form method="post" action="/admin/plans/{plan.id}/edit">
  <div class="form-group"><label>Название</label><input name="name" value="{plan.name}" required></div>
  <div class="form-group"><label>Цена</label><input name="price" type="number" step="0.01" min="0.01" value="{plan.price}" required></div>
  <div class="form-group"><label>Валюта</label>
    <select name="currency">
      <option {'selected' if plan.currency=='RUB' else ''} value="RUB">RUB</option>
      <option {'selected' if plan.currency=='USD' else ''} value="USD">USD</option>
      <option {'selected' if plan.currency=='EUR' else ''} value="EUR">EUR</option>
    </select>
  </div>
  <div class="form-group"><label>Длительность (дней)</label><input name="duration_days" type="number" min="1" value="{plan.duration_days}" required></div>
  <div class="form-group"><label>Модель OpenAI</label><input name="openai_model" value="{plan.openai_model}" required></div>
  <div class="form-group"><label>Лимит запросов/день (пусто = без лимита)</label><input name="max_day" type="number" min="1" value="{md}"></div>
  <div class="form-group"><label>Лимит запросов/период (пусто = без лимита)</label><input name="max_period" type="number" min="1" value="{mp}"></div>
  <div class="form-group"><label>Порядок сортировки</label><input name="sort_order" type="number" min="0" value="{plan.sort_order}" required></div>
  <button class="btn btn-primary" type="submit">Сохранить</button>
  <a class="btn" style="background:#6b7280;color:#fff;margin-left:8px" href="/admin/">Отмена</a>
</form>"""
    return _page(f"Редактировать: {plan.name}", body)


@router.post("/plans/{plan_id}/edit")
async def admin_plan_edit(
    _: AdminDep,
    plan_id: int,
    name: Annotated[str, Form()],
    price: Annotated[str, Form()],
    currency: Annotated[str, Form()] = "RUB",
    duration_days: Annotated[int, Form()] = 30,
    openai_model: Annotated[str, Form()] = "gpt-4.1-mini",
    max_day: Annotated[str | None, Form()] = None,
    max_period: Annotated[str | None, Form()] = None,
    sort_order: Annotated[int, Form()] = 0,
) -> RedirectResponse:
    try:
        price_dec = Decimal(price)
        if price_dec <= 0:
            raise ValueError("Цена должна быть > 0")
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    max_day_int: int | None = int(max_day) if max_day and max_day.strip() else None
    max_period_int: int | None = int(max_period) if max_period and max_period.strip() else None

    async with AsyncSessionLocal() as session:
        plan = await get_plan_by_id(session, plan_id)
        if plan is None:
            raise HTTPException(status_code=404)
        plan.name = name.strip()
        plan.price = price_dec
        plan.currency = currency.upper()[:3]
        plan.duration_days = duration_days
        plan.openai_model = openai_model.strip()
        plan.max_requests_per_day = max_day_int
        plan.max_requests_per_period = max_period_int
        plan.sort_order = sort_order
        await session.commit()

    return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


# ── POST /admin/plans/{id}/toggle ─────────────────────────────────────────────

@router.get("/plans/{plan_id}/toggle")
async def admin_plan_toggle(_: AdminDep, plan_id: int) -> RedirectResponse:
    async with AsyncSessionLocal() as session:
        try:
            await toggle_plan_active(session, plan_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="Тариф не найден")
    return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


# ── POST /admin/plans/{id}/delete ─────────────────────────────────────────────

@router.post("/plans/{plan_id}/delete")
async def admin_plan_delete(_: AdminDep, plan_id: int) -> RedirectResponse:
    async with AsyncSessionLocal() as session:
        try:
            await delete_plan(session, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
