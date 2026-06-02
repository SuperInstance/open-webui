"""
Budget Guardian core — tracks usage, enforces limits, computes phases, fires alerts.

This module wraps LLM API calls with budget enforcement. It intercepts
chat completion requests, tracks token usage, checks budgets, and applies
phase-based policies (warning banner, model downgrade, soft block).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from fastapi import Request

from .models import (
    AccumulatedUsage,
    AlertChannel,
    BudgetAlert,
    BudgetConfig,
    BudgetPhase,
    BudgetPeriod,
    ModelPricing,
    PerModelUsage,
    TeamBudget,
    TokenBudget,
    UsageRecord,
)
from .pricing import MODEL_PRICING_MAP, resolve_model_pricing
from .storage import BudgetStorage

log = logging.getLogger(__name__)

# Singleton instance
_guardian: Optional["BudgetGuardian"] = None


def get_guardian() -> "BudgetGuardian":
    if _guardian is None:
        raise RuntimeError("BudgetGuardian not initialized")
    return _guardian


def init_guardian(app_state: Any) -> "BudgetGuardian":
    global _guardian
    _guardian = BudgetGuardian(app_state)
    log.info("BudgetGuardian initialized")
    return _guardian


# ──────────────────────────────────────────────
# BudgetGuardian
# ──────────────────────────────────────────────


class BudgetGuardian:
    """
    Central budget enforcement engine.

    Tracks every LLM API call, computes per-user and per-team usage across
    daily/weekly/monthly windows, determines phases, and enforces limits.
    """

    def __init__(self, app_state: Any):
        self._app_state = app_state
        self._storage = BudgetStorage()
        self._config: BudgetConfig = BudgetConfig()
        self._user_budgets: dict[str, TokenBudget] = {}
        self._team_budgets: dict[str, TeamBudget] = {}
        self._lock = asyncio.Lock()

        # In-memory usage accumulator (synced to DB periodically)
        self._daily_usage: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    # ── Configuration ──────────────────────────

    async def load_config(self) -> BudgetConfig:
        """Load config from DB or return defaults."""
        cfg_data = await self._storage.load_config()
        if cfg_data:
            self._config = BudgetConfig(**cfg_data)
        return self._config

    async def save_config(self, config: BudgetConfig) -> None:
        self._config = config
        await self._storage.save_config(config.model_dump())

    async def get_config(self) -> BudgetConfig:
        return self._config

    async def set_user_budget(self, user_id: str, budget: TokenBudget) -> None:
        async with self._lock:
            self._user_budgets[user_id] = budget
            await self._storage.save_user_budget(user_id, budget.model_dump())

    async def get_user_budget(self, user_id: str) -> Optional[TokenBudget]:
        if user_id not in self._user_budgets:
            data = await self._storage.load_user_budget(user_id)
            if data:
                self._user_budgets[user_id] = TokenBudget(**data)
        return self._user_budgets.get(user_id)

    async def set_team_budget(self, team_id: str, budget: TeamBudget) -> None:
        async with self._lock:
            self._team_budgets[team_id] = budget
            await self._storage.save_team_budget(team_id, budget.model_dump())

    async def get_team_budget(self, team_id: str) -> Optional[TeamBudget]:
        if team_id not in self._team_budgets:
            data = await self._storage.load_team_budget(team_id)
            if data:
                self._team_budgets[team_id] = TeamBudget(**data)
        return self._team_budgets.get(team_id)

    async def get_all_user_budgets(self) -> list[TokenBudget]:
        """Return all configured user budgets."""
        return list(self._user_budgets.values()) or [
            TokenBudget(**d) for d in (await self._storage.load_all_user_budgets())
        ]

    async def get_all_team_budgets(self) -> list[TeamBudget]:
        return list(self._team_budgets.values()) or [
            TeamBudget(**d) for d in (await self._storage.load_all_team_budgets())
        ]

    # ── Usage recording ────────────────────────

    async def record_usage(
        self,
        user_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        team_id: Optional[str] = None,
        blocked: bool = False,
    ) -> UsageRecord:
        """Record a single LLM API call and enforce budget limits."""

        pricing = resolve_model_pricing(model_id)
        cost = Decimal("0")
        if pricing:
            cost = pricing.estimate_cost(
                input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
            )

        # Determine phase for this user
        phase = BudgetPhase.GREEN
        if self._config.enabled and not blocked:
            phase = await self._determine_phase(user_id, model_id, team_id)

        record = UsageRecord(
            user_id=user_id,
            team_id=team_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost,
            phase=phase,
            blocked=blocked,
        )

        await self._storage.save_usage(record.model_dump())
        return record

    async def _determine_phase(
        self, user_id: str, model_id: str, team_id: Optional[str] = None
    ) -> BudgetPhase:
        """Determine which phase the user is in based on current usage vs limits."""

        # Check team budget first (supersedes individual)
        if team_id:
            team_budget = await self.get_team_budget(team_id)
            if team_budget and team_budget.enabled:
                if team_budget.admin_override:
                    return BudgetPhase.GREEN
                pct = await self._usage_pct_team(team_budget)
                return self._pct_to_phase(pct)

        # User budget
        user_budget = await self.get_user_budget(user_id)
        if user_budget and user_budget.enabled:
            if user_budget.admin_override:
                return BudgetPhase.GREEN
            pct = await self._usage_pct_user(user_budget)
            return self._pct_to_phase(pct)

        # Default global config
        if self._config.enabled:
            pct = await self._usage_pct_global(user_id)
            return self._pct_to_phase(pct)

        return BudgetPhase.GREEN

    def _pct_to_phase(self, pct: float) -> BudgetPhase:
        if pct >= self._config.block_threshold:
            return BudgetPhase.BLOCKED
        if pct >= self._config.downgrade_threshold:
            return BudgetPhase.DOWNGRADE
        if pct >= self._config.warning_threshold:
            return BudgetPhase.WARNING
        return BudgetPhase.GREEN

    # ── Usage computation ──────────────────────

    async def _usage_pct_user(self, budget: TokenBudget) -> float:
        """Return max usage percentage across all limits for this user."""
        now = datetime.now(timezone.utc)
        pcts = []

        if budget.daily_token_limit > 0:
            daily = await self._storage.get_usage_tokens(
                budget.user_id, period=BudgetPeriod.DAILY, now=now
            )
            pcts.append(daily / budget.daily_token_limit)

        if budget.weekly_token_limit > 0:
            weekly = await self._storage.get_usage_tokens(
                budget.user_id, period=BudgetPeriod.WEEKLY, now=now
            )
            pcts.append(weekly / budget.weekly_token_limit)

        if budget.monthly_token_limit > 0:
            monthly = await self._storage.get_usage_tokens(
                budget.user_id, period=BudgetPeriod.MONTHLY, now=now
            )
            pcts.append(monthly / budget.monthly_token_limit)

        # Cost-based limits
        if budget.daily_cost_limit_cents > 0:
            daily_cost = await self._storage.get_usage_cost_cents(
                budget.user_id, period=BudgetPeriod.DAILY, now=now
            )
            pcts.append(daily_cost / budget.daily_cost_limit_cents)

        if budget.monthly_cost_limit_cents > 0:
            monthly_cost = await self._storage.get_usage_cost_cents(
                budget.user_id, period=BudgetPeriod.MONTHLY, now=now
            )
            pcts.append(monthly_cost / budget.monthly_cost_limit_cents)

        return max(pcts) if pcts else 0.0

    async def _usage_pct_team(self, budget: TeamBudget) -> float:
        """Return max usage percentage across all limits for this team."""
        now = datetime.now(timezone.utc)
        pcts = []

        if budget.daily_token_limit > 0:
            daily = await self._storage.get_team_usage_tokens(
                budget.team_id, period=BudgetPeriod.DAILY, now=now
            )
            pcts.append(daily / budget.daily_token_limit)

        if budget.monthly_cost_limit_cents > 0:
            monthly_cost = await self._storage.get_team_usage_cost_cents(
                budget.team_id, period=BudgetPeriod.MONTHLY, now=now
            )
            pcts.append(monthly_cost / budget.monthly_cost_limit_cents)

        return max(pcts) if pcts else 0.0

    async def _usage_pct_global(self, user_id: str) -> float:
        """Fallback: use global defaults to compute percentage."""
        user_budget = TokenBudget(
            user_id=user_id,
            daily_token_limit=self._config.default_daily_token_limit,
            weekly_token_limit=self._config.default_weekly_token_limit,
            monthly_token_limit=self._config.default_monthly_token_limit,
            daily_cost_limit_cents=self._config.default_daily_cost_limit_cents,
            monthly_cost_limit_cents=self._config.default_monthly_cost_limit_cents,
        )
        return await self._usage_pct_user(user_budget)

    # ── Accumulated usage (for admin dashboards) ──

    async def get_user_usage(
        self,
        user_id: str,
        period: BudgetPeriod = BudgetPeriod.MONTHLY,
    ) -> AccumulatedUsage:
        """Get accumulated usage for a user."""
        now = datetime.now(timezone.utc)
        totals = await self._storage.get_accumulated_usage(
            user_id=user_id, period=period, now=now
        )
        return totals

    async def get_team_usage(
        self,
        team_id: str,
        period: BudgetPeriod = BudgetPeriod.MONTHLY,
    ) -> AccumulatedUsage:
        """Get accumulated usage for a team."""
        now = datetime.now(timezone.utc)
        return await self._storage.get_team_accumulated_usage(team_id, period, now)

    async def get_all_users_usage(
        self, period: BudgetPeriod = BudgetPeriod.MONTHLY
    ) -> list[dict]:
        """Get usage summary for all users (admin dashboard data)."""
        now = datetime.now(timezone.utc)
        return await self._storage.get_all_users_usage_summary(period, now)

    async def get_total_spend(
        self, period: BudgetPeriod = BudgetPeriod.MONTHLY
    ) -> dict:
        """Get total spend across all users."""
        now = datetime.now(timezone.utc)
        return await self._storage.get_total_spend(period, now)

    # ── Budget enforcement ─────────────────────

    async def check_budget(
        self,
        user_id: str,
        model_id: str,
        team_id: Optional[str] = None,
        input_tokens_estimate: int = 0,
    ) -> tuple[bool, BudgetPhase, Optional[str]]:
        """
        Check whether a request should proceed.

        Returns:
            (allowed: bool, phase: BudgetPhase, downgrade_to: Optional[str])
            If phase is DOWNGRADE, downgrade_to contains the cheaper model.
        """
        if not self._config.enabled:
            return True, BudgetPhase.GREEN, None

        # Check per-model override first
        user_budget = await self.get_user_budget(user_id)
        if user_budget and model_id in user_budget.model_overrides:
            override = user_budget.model_overrides[model_id]
            if override.admin_override:
                return True, BudgetPhase.GREEN, None

        phase = await self._determine_phase(user_id, model_id, team_id)

        if phase == BudgetPhase.BLOCKED:
            return False, phase, None

        if phase == BudgetPhase.DOWNGRADE:
            # Find the downgrade model
            downgrade_to = None
            if user_budget and user_budget.downgrade_model:
                downgrade_to = user_budget.downgrade_model
            elif team_id:
                team_budget = await self.get_team_budget(team_id)
                if team_budget and team_budget.downgrade_model:
                    downgrade_to = team_budget.downgrade_model

            # If no explicit downgrade, try auto-downgrade to cheaper model
            if not downgrade_to:
                downgrade_to = self._auto_downgrade(model_id)

            return True, phase, downgrade_to

        return True, phase, None

    def _auto_downgrade(self, model_id: str) -> Optional[str]:
        """Find a cheaper version of the same model family."""
        pricing = resolve_model_pricing(model_id)
        if not pricing:
            return None

        # Known downgrade paths
        downgrade_map: dict[str, str] = {
            "gpt-4o": "gpt-4o-mini",
            "gpt-4": "gpt-4o-mini",
            "gpt-4-turbo": "gpt-4o-mini",
            "o1": "o1-mini",
            "o3-mini": "gpt-4o-mini",
            "claude-3-opus-20240229": "claude-3-5-sonnet-20241022",
            "claude-4-opus": "claude-4-sonnet",
            "claude-3-5-sonnet-20241022": "claude-3-5-haiku-20241022",
            "gemini-2.5-pro-exp-03-25": "gemini-2.5-flash-preview-04-17",
            "deepseek-chat": "deepseek-chat",
            "mistral-large-2411": "mistral-small-2501",
        }

        for expensive, cheap in downgrade_map.items():
            if model_id.startswith(expensive) or expensive.startswith(model_id):
                return cheap

        # Generic: find any model in the same "family" with lower price
        base_name = model_id.split("-")[0]
        candidates = [
            (mid, p)
            for mid, p in MODEL_PRICING_MAP.items()
            if mid.startswith(base_name)
            and p.input_price_per_1m < (pricing.input_price_per_1m or Decimal("999"))
        ]
        if candidates:
            candidates.sort(key=lambda x: x[1].input_price_per_1m)
            return candidates[0][0]

        return None

    # ── Alerts ─────────────────────────────────

    async def check_and_fire_alerts(self, user_id: str, team_id: Optional[str] = None) -> list[BudgetAlert]:
        """Check if alerts need to be fired for current usage levels."""
        alerts: list[BudgetAlert] = []
        now = datetime.now(timezone.utc)

        # User alerts
        user_budget = await self.get_user_budget(user_id)
        if user_budget and user_budget.enabled:
            pct = await self._usage_pct_user(user_budget)
            if pct >= user_budget.alert_threshold:
                alert = await self._fire_alert(
                    user_id=user_id,
                    alert_type="user_90",
                    phase=await self._determine_phase(user_id, "unknown"),
                    usage_pct=pct,
                    budget=user_budget,
                    now=now,
                )
                if alert:
                    alerts.append(alert)

        # Check global warning/downgrade/block thresholds
        if self._config.enabled:
            pct = await self._usage_pct_global(user_id)
            if pct >= self._config.warning_threshold and pct < self._config.downgrade_threshold:
                # Already covered by phase determination
                pass

        return alerts

    async def _fire_alert(
        self,
        user_id: str,
        alert_type: str,
        phase: BudgetPhase,
        usage_pct: float,
        budget: TokenBudget | TeamBudget,
        now: datetime,
        team_id: Optional[str] = None,
    ) -> Optional[BudgetAlert]:
        """Create and deliver a budget alert."""

        alert = BudgetAlert(
            user_id=user_id,
            team_id=team_id,
            alert_type=alert_type,
            message=f"{'Team' if team_id else 'User'} budget at {usage_pct:.1%}",
            phase=phase,
            usage_pct=usage_pct,
            current_cost_cents=0,
            limit_cents=budget.daily_cost_limit_cents or budget.monthly_cost_limit_cents or 0,
            current_tokens=0,
            limit_tokens=budget.daily_token_limit or budget.monthly_token_limit or 0,
            delivered_via="none",
        )

        await self._storage.save_alert(alert.model_dump())

        # Check if webhook delivery is configured
        team_config = None
        if team_id:
            team_config = await self.get_team_budget(team_id)

        webhook_url = (
            team_config.alert_webhook_url
            if team_config and team_config.alert_webhook_url
            else self._config.global_alert_webhook_url
        )

        if webhook_url:
            try:
                await self._deliver_webhook(webhook_url, alert)
                alert.delivered_via = "webhook"
            except Exception as e:
                log.warning(f"Failed to deliver budget alert webhook: {e}")

        return alert

    async def _deliver_webhook(self, url: str, alert: BudgetAlert) -> None:
        """Deliver an alert to a webhook URL."""
        import aiohttp

        payload = alert.model_dump()
        payload["_type"] = "budget_alert"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status >= 400:
                    log.warning(
                        f"Budget alert webhook returned {resp.status}: {await resp.text()}"
                    )

    async def get_alerts(
        self,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[BudgetAlert]:
        """Get recent alerts."""
        data = await self._storage.get_alerts(user_id=user_id, team_id=team_id, limit=limit)
        return [BudgetAlert(**d) for d in data]

    # ── Rollover ───────────────────────────────

    async def process_rollovers(self) -> None:
        """Process budget rollovers for teams with rollover enabled."""
        teams = await self.get_all_team_budgets()
        for team in teams:
            if not team.rollover_enabled:
                continue

            # Get previous period usage
            now = datetime.now(timezone.utc)
            usage = await self._storage.get_team_usage_tokens(
                team.team_id, BudgetPeriod.MONTHLY, now
            )

            if team.monthly_token_limit > 0 and usage < team.monthly_token_limit:
                unused = team.monthly_token_limit - usage
                rollover_amount = int(unused * team.rollover_fraction)
                log.info(
                    f"Team {team.team_id}: rolling over {rollover_amount} tokens "
                    f"({rollover_amount/team.monthly_token_limit:.1%} of limit)"
                )
                # Store rollover credit
                await self._storage.save_rollover(team.team_id, rollover_amount)
