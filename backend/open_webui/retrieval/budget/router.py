"""
Budget Guardian API router.

Endpoints:
  GET    /api/budget/status       — user-facing: current usage and phase
  GET    /api/budget/admin        — admin dashboard: per-user spend, totals
  POST   /api/budget/admin/config — admin: update global config
  POST   /api/budget/admin/user   — admin: set user budget
  POST   /api/budget/admin/team   — admin: set team budget
  GET    /api/budget/alerts       — get budget alerts
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from open_webui.models.users import UserModel
from open_webui.utils.auth import get_admin_user, get_verified_user

from .core import get_guardian, init_guardian
from .models import (
    AlertChannel,
    BudgetConfig,
    BudgetPeriod,
    BudgetPhase,
    TeamBudget,
    TokenBudget,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/budget", tags=["budget"])


async def _guardian(request: Request):
    """Get or initialize the BudgetGuardian singleton."""
    try:
        return get_guardian()
    except RuntimeError:
        guardian = init_guardian(request.app.state)
        await guardian.load_config()
        return guardian


# ──────────────────────────────────────────────
# User-facing status endpoint
# ──────────────────────────────────────────────


@router.get("/status")
async def get_status(
    request: Request,
    user=Depends(get_verified_user),
):
    """
    Get current budget status for the authenticated user.

    Returns usage percentages, current phase, and whether there's
    an active downgrade or block.
    """
    guardian = await _guardian(request)
    config = await guardian.get_config()

    if not config.enabled:
        return {"enabled": False, "phase": "green", "message": "Budget tracking is disabled"}

    user_budget = await guardian.get_user_budget(user.id)

    # Per-period usage
    now = datetime.now(timezone.utc)
    periods = {}
    for period in BudgetPeriod:
        usage = await guardian.get_user_usage(user.id, period)
        tokens_used = usage.total_tokens
        cost_used = usage.total_cost_cents

        # Find limit
        token_limit = 0
        cost_limit_cents = 0
        if user_budget:
            if period == BudgetPeriod.DAILY:
                token_limit = user_budget.daily_token_limit
                cost_limit_cents = user_budget.daily_cost_limit_cents
            elif period == BudgetPeriod.WEEKLY:
                token_limit = user_budget.weekly_token_limit
                cost_limit_cents = user_budget.weekly_cost_limit_cents
            elif period == BudgetPeriod.MONTHLY:
                token_limit = user_budget.monthly_token_limit
                cost_limit_cents = user_budget.monthly_cost_limit_cents
        else:
            if period == BudgetPeriod.DAILY:
                token_limit = config.default_daily_token_limit
                cost_limit_cents = config.default_daily_cost_limit_cents
            elif period == BudgetPeriod.MONTHLY:
                token_limit = config.default_monthly_token_limit
                cost_limit_cents = config.default_monthly_cost_limit_cents

        periods[period.value] = {
            "tokens_used": tokens_used,
            "token_limit": token_limit,
            "token_pct": round(tokens_used / token_limit * 100, 1) if token_limit > 0 else 0,
            "cost_cents_used": cost_used,
            "cost_limit_cents": cost_limit_cents,
            "cost_pct": round(cost_used / cost_limit_cents * 100, 1) if cost_limit_cents > 0 else 0,
        }

    # Current phase
    phase = await guardian._determine_phase(user.id, "status_check")
    _, _, downgrade_to = await guardian.check_budget(user.id, "status_check")

    return {
        "enabled": True,
        "user_id": user.id,
        "phase": phase.value,
        "downgrade_to": downgrade_to,
        "periods": periods,
        "model_pricing_available": config.tracking_enabled,
    }


# ──────────────────────────────────────────────
# Admin dashboard
# ──────────────────────────────────────────────


@router.get("/admin")
async def get_admin_dashboard(
    request: Request,
    period: str = "monthly",
    user=Depends(get_admin_user),
):
    """
    Get the admin budget dashboard.

    Returns total spend, per-user spend, model cost breakdown, and
    budget utilization heatmap data.
    """
    guardian = await _guardian(request)
    config = await guardian.get_config()

    try:
        p = BudgetPeriod(period)
    except ValueError:
        p = BudgetPeriod.MONTHLY

    now = datetime.now(timezone.utc)

    # Total spend
    total_spend = await guardian.get_total_spend(p)

    # Per-user usage
    users_usage = await guardian.get_all_users_usage(p)

    # Config
    config_dict = config.model_dump()

    # User budgets
    user_budgets = [b.model_dump() for b in await guardian.get_all_user_budgets()]
    team_budgets = [b.model_dump() for b in await guardian.get_all_team_budgets()]

    # Recent alerts
    alerts = await guardian.get_alerts(limit=20)
    alerts_data = [a.model_dump() for a in alerts] if alerts else []

    # Build utilization heatmap (per-user token pct)
    heatmap = {}
    for ub in user_budgets:
        uid = ub.get("user_id", "")
        ml = ub.get("monthly_token_limit", 0)
        if ml > 0:
            usage = await guardian.get_user_usage(uid, BudgetPeriod.MONTHLY)
            pct = round(usage.total_tokens / ml * 100, 1)
            heatmap[uid] = {
                "usage_tokens": usage.total_tokens,
                "limit_tokens": ml,
                "usage_pct": pct,
                "phase": guardian._pct_to_phase(pct / 100.0).value,
            }

    return {
        "enabled": config.enabled,
        "config": config_dict,
        "total_spend": total_spend,
        "users_usage": users_usage,
        "user_budgets": user_budgets,
        "team_budgets": team_budgets,
        "heatmap": heatmap,
        "alerts": alerts_data,
    }


# ──────────────────────────────────────────────
# Admin config
# ──────────────────────────────────────────────


@router.post("/admin/config")
async def update_admin_config(
    request: Request,
    config_data: BudgetConfig,
    user=Depends(get_admin_user),
):
    """Update the global budget configuration."""
    guardian = await _guardian(request)
    await guardian.save_config(config_data)
    return {"status": "ok", "config": config_data.model_dump()}


@router.post("/admin/user")
async def set_user_budget(
    request: Request,
    budget: TokenBudget,
    user=Depends(get_admin_user),
):
    """Set or update a per-user budget."""
    guardian = await _guardian(request)
    await guardian.set_user_budget(budget.user_id, budget)
    return {"status": "ok", "budget": budget.model_dump()}


@router.post("/admin/team")
async def set_team_budget(
    request: Request,
    budget: TeamBudget,
    user=Depends(get_admin_user),
):
    """Set or update a team budget."""
    guardian = await _guardian(request)
    await guardian.set_team_budget(budget.team_id, budget)
    return {"status": "ok", "budget": budget.model_dump()}


@router.delete("/admin/user/{user_id}")
async def delete_user_budget(
    request: Request,
    user_id: str,
    admin_user=Depends(get_admin_user),
):
    """Remove a user's budget configuration."""
    guardian = await _guardian(request)
    # Reset to empty (will fall back to global defaults)
    default_budget = TokenBudget(
        user_id=user_id,
        enabled=False,
    )
    await guardian.set_user_budget(user_id, default_budget)
    return {"status": "ok"}


@router.delete("/admin/team/{team_id}")
async def delete_team_budget(
    request: Request,
    team_id: str,
    admin_user=Depends(get_admin_user),
):
    """Remove a team budget."""
    guardian = await _guardian(request)
    default_budget = TeamBudget(
        team_id=team_id,
        name="",
        enabled=False,
    )
    await guardian.set_team_budget(team_id, default_budget)
    return {"status": "ok"}


# ──────────────────────────────────────────────
# Alerts
# ──────────────────────────────────────────────


@router.get("/alerts")
async def get_budget_alerts(
    request: Request,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    limit: int = 50,
    user=Depends(get_admin_user),
):
    """Get budget alerts, optionally filtered."""
    guardian = await _guardian(request)
    alerts = await guardian.get_alerts(
        user_id=user_id,
        team_id=team_id,
        limit=limit,
    )
    return {"alerts": [a.model_dump() for a in alerts]}


# ──────────────────────────────────────────────
# Middleware integration helper
# ──────────────────────────────────────────────


async def budget_middleware(request: Request, user: UserModel):
    """
    Middleware hook for the async LLM call path.

    Call this before making an LLM API request to check budget limits.
    Returns (allowed, phase, downgrade_to) or raises HTTPException.
    """
    guardian = await _guardian(request)

    # Extract model from request body
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    model_id = body.get("model", "unknown")
    team_id = body.get("metadata", {}).get("team_id") if body.get("metadata") else None

    allowed, phase, downgrade_to = await guardian.check_budget(
        user_id=user.id,
        model_id=model_id,
        team_id=team_id,
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Budget limit reached",
                "phase": phase.value,
                "message": "Your API budget has been exhausted. Contact your admin to increase limits or wait for the next period.",
            },
        )

    return allowed, phase, downgrade_to
