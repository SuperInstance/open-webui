"""
Tests for Budget Guardian — the LLM budget enforcement system.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_webui.retrieval.budget.core import BudgetGuardian, init_guardian
from open_webui.retrieval.budget.models import (
    BudgetConfig,
    BudgetPhase,
    BudgetPeriod,
    TeamBudget,
    TokenBudget,
    UsageRecord,
)
from open_webui.retrieval.budget.pricing import (
    MODEL_PRICING_MAP,
    resolve_model_pricing,
)
from open_webui.retrieval.budget.storage import BudgetStorage


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def app_state():
    """Mock FastAPI app state."""
    state = MagicMock()
    state.config = MagicMock()
    return state


@pytest.fixture
def guardian(app_state):
    """Create a fresh BudgetGuardian with a temp storage directory."""
    with patch.dict(os.environ, {"BUDGET_GUARDIAN_DATA_DIR": tempfile.mkdtemp()}):
        g = BudgetGuardian(app_state)
        g._config.enabled = True
        return g


@pytest.fixture
def storage():
    """Create a fresh storage with temp dir."""
    with patch.dict(os.environ, {"BUDGET_GUARDIAN_DATA_DIR": tempfile.mkdtemp()}):
        s = BudgetStorage()
        return s


# ──────────────────────────────────────────────
# Pricing tests
# ──────────────────────────────────────────────


class TestPricing:
    def test_exact_match(self):
        pricing = resolve_model_pricing("gpt-4o")
        assert pricing is not None
        assert pricing.input_price_per_1m == Decimal("2.50")
        assert pricing.output_price_per_1m == Decimal("10.00")

    def test_suffix_match(self):
        pricing = resolve_model_pricing("gpt-4o-2024-08-06")
        assert pricing is not None
        assert pricing.input_price_per_1m == Decimal("2.50")

    def test_unknown_model(self):
        pricing = resolve_model_pricing("completely-fake-model-v99")
        assert pricing is None

    def test_claude_opus(self):
        pricing = resolve_model_pricing("claude-3-opus-20240229")
        assert pricing is not None
        assert pricing.input_price_per_1m == Decimal("15.00")
        assert pricing.output_price_per_1m == Decimal("75.00")

    def test_cost_estimate(self):
        pricing = resolve_model_pricing("gpt-4o")
        cost = pricing.estimate_cost(input_tokens=1000, output_tokens=500)
        assert cost == Decimal("0.00750")

    def test_all_models_have_pricing(self):
        assert len(MODEL_PRICING_MAP) > 40


# ──────────────────────────────────────────────
# Storage tests
# ──────────────────────────────────────────────


class TestStorage:
    async def test_save_load_config(self, storage):
        config = {"enabled": True, "default_daily_token_limit": 500000}
        await storage.save_config(config)
        loaded = await storage.load_config()
        assert loaded["enabled"] is True
        assert loaded["default_daily_token_limit"] == 500000

    async def test_save_load_user_budget(self, storage):
        budget = {"user_id": "user1", "daily_token_limit": 100000, "enabled": True}
        await storage.save_user_budget("user1", budget)
        loaded = await storage.load_user_budget("user1")
        assert loaded["user_id"] == "user1"
        assert loaded["daily_token_limit"] == 100000

    async def test_usage_recording_and_query(self, storage):
        now = datetime.now(timezone.utc)
        record = {
            "user_id": "user1", "model_id": "gpt-4o",
            "input_tokens": 1000, "output_tokens": 500,
            "cost_usd": "0.00750", "timestamp": now.isoformat(), "blocked": False,
        }
        await storage.save_usage(record)
        tokens = await storage.get_usage_tokens("user1", BudgetPeriod.DAILY, now)
        assert tokens == 1500
        other = await storage.get_usage_tokens("user2", BudgetPeriod.DAILY, now)
        assert other == 0

    async def test_usage_cost_query(self, storage):
        now = datetime.now(timezone.utc)
        record = {
            "user_id": "user1", "model_id": "gpt-4o",
            "input_tokens": 100000, "output_tokens": 50000,
            "cost_usd": "0.75", "timestamp": now.isoformat(), "blocked": False,
        }
        await storage.save_usage(record)
        cost_cents = await storage.get_usage_cost_cents("user1", BudgetPeriod.DAILY, now)
        assert cost_cents == 75

    async def test_accumulated_usage(self, storage):
        now = datetime.now(timezone.utc)
        records = [
            {"user_id": "u1", "model_id": "gpt-4o", "input_tokens": 1000, "output_tokens": 500, "cost_usd": "0.01", "timestamp": now.isoformat(), "blocked": False},
            {"user_id": "u1", "model_id": "claude-3-5-sonnet", "input_tokens": 2000, "output_tokens": 1000, "cost_usd": "0.02", "timestamp": now.isoformat(), "blocked": False},
            {"user_id": "u1", "model_id": "gpt-4o", "input_tokens": 500, "output_tokens": 200, "cost_usd": "0.005", "timestamp": now.isoformat(), "blocked": False},
        ]
        for r in records:
            await storage.save_usage(r)
        usage = await storage.get_accumulated_usage("u1", BudgetPeriod.DAILY, now)
        assert usage.total_tokens == 5200
        assert "gpt-4o" in usage.per_model
        assert usage.per_model["gpt-4o"].tokens == 2200

    async def test_alerts(self, storage):
        alert = {"user_id": "u1", "alert_type": "warning_60", "phase": "warning"}
        await storage.save_alert(alert)
        alerts = await storage.get_alerts(user_id="u1")
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "warning_60"

    async def test_total_spend(self, storage):
        now = datetime.now(timezone.utc)
        records = [
            {"user_id": "u1", "model_id": "gpt-4o", "input_tokens": 1000, "output_tokens": 500, "cost_usd": "0.01", "timestamp": now.isoformat(), "blocked": False},
            {"user_id": "u2", "model_id": "claude", "input_tokens": 2000, "output_tokens": 1000, "cost_usd": "0.02", "timestamp": now.isoformat(), "blocked": False},
        ]
        for r in records:
            await storage.save_usage(r)
        total = await storage.get_total_spend(BudgetPeriod.DAILY, now)
        assert total["total_calls"] == 2
        assert total["total_cost_usd"] == 0.03
        assert total["total_tokens"] == 4500


# ──────────────────────────────────────────────
# Core Guardian tests
# ──────────────────────────────────────────────


class TestBudgetGuardian:
    async def test_init(self, guardian):
        assert guardian._config.enabled is True

    async def test_determine_phase_green(self, guardian):
        phase = await guardian._determine_phase("user1", "gpt-4o")
        assert phase == BudgetPhase.GREEN

    async def test_determine_phase_blocked(self, guardian):
        budget = TokenBudget(user_id="user_blocked", daily_token_limit=100, daily_cost_limit_cents=1)
        await guardian.set_user_budget("user_blocked", budget)
        await guardian.record_usage(user_id="user_blocked", model_id="gpt-4o", input_tokens=10000, output_tokens=5000)
        phase = await guardian._determine_phase("user_blocked", "gpt-4o")
        assert phase == BudgetPhase.BLOCKED

    async def test_determine_phase_warning(self, guardian):
        budget = TokenBudget(user_id="user_warn", daily_token_limit=1000)
        await guardian.set_user_budget("user_warn", budget)
        await guardian.record_usage(user_id="user_warn", model_id="gpt-4o", input_tokens=700, output_tokens=0)
        phase = await guardian._determine_phase("user_warn", "gpt-4o")
        assert phase == BudgetPhase.WARNING

    async def test_check_budget_allowed(self, guardian):
        allowed, phase, downgrade = await guardian.check_budget("user1", "gpt-4o")
        assert allowed is True
        assert phase == BudgetPhase.GREEN

    async def test_check_budget_blocked(self, guardian):
        budget = TokenBudget(user_id="blocked", daily_token_limit=10)
        await guardian.set_user_budget("blocked", budget)
        await guardian.record_usage(user_id="blocked", model_id="gpt-4o", input_tokens=5000, output_tokens=0)
        allowed, phase, downgrade = await guardian.check_budget("blocked", "gpt-4o")
        assert allowed is False
        assert phase == BudgetPhase.BLOCKED

    async def test_downgrade_model(self, guardian):
        downgrade = guardian._auto_downgrade("gpt-4o")
        assert downgrade == "gpt-4o-mini"

    async def test_admin_override(self, guardian):
        budget = TokenBudget(user_id="admin_user", daily_token_limit=1, admin_override=True)
        await guardian.set_user_budget("admin_user", budget)
        allowed, phase, _ = await guardian.check_budget("admin_user", "gpt-4o")
        assert allowed is True
        assert phase == BudgetPhase.GREEN

    async def test_disabled_config(self, guardian):
        guardian._config.enabled = False
        allowed, phase, _ = await guardian.check_budget("any_user", "gpt-4o")
        assert allowed is True
        assert phase == BudgetPhase.GREEN

    async def test_record_usage(self, guardian):
        record = await guardian.record_usage(user_id="recorder", model_id="gpt-4o", input_tokens=500, output_tokens=200)
        assert record.user_id == "recorder"
        assert record.model_id == "gpt-4o"
        assert record.input_tokens == 500
        assert record.output_tokens == 200
        assert record.cost_usd > 0

    async def test_team_budget(self, guardian):
        team = TeamBudget(
            team_id="team-rnd", name="R&D", member_user_ids=["dev1", "dev2"],
            monthly_token_limit=100000, rollover_enabled=True, rollover_fraction=1.0,
        )
        await guardian.set_team_budget("team-rnd", team)
        await guardian.record_usage(user_id="dev1", model_id="gpt-4o", input_tokens=30000, output_tokens=10000, team_id="team-rnd")
        phase = await guardian._determine_phase("dev1", "gpt-4o", team_id="team-rnd")
        assert phase == BudgetPhase.GREEN  # 40% used

    async def test_alert_creation(self, guardian):
        alert = await guardian._fire_alert(
            user_id="alert_user", alert_type="warning_60", phase=BudgetPhase.WARNING,
            usage_pct=0.65,
            budget=TokenBudget(user_id="alert_user", daily_token_limit=1000),
            now=datetime.now(timezone.utc),
        )
        assert alert is not None
        assert alert.alert_type == "warning_60"
        assert alert.usage_pct == 0.65

    async def test_get_user_usage(self, guardian):
        await guardian.record_usage(user_id="usage_user", model_id="gpt-4o", input_tokens=1000, output_tokens=500)
        usage = await guardian.get_user_usage("usage_user", BudgetPeriod.MONTHLY)
        assert usage.total_tokens == 1500
        assert "gpt-4o" in usage.per_model

    async def test_all_users_usage_summary(self, guardian):
        await guardian.record_usage("u1", "gpt-4o", 1000, 500)
        await guardian.record_usage("u2", "claude-sonnet", 2000, 1000)
        summary = await guardian.get_all_users_usage(BudgetPeriod.MONTHLY)
        assert len(summary) == 2


# ──────────────────────────────────────────────
# Config tests
# ──────────────────────────────────────────────


class TestBudgetConfig:
    async def test_defaults(self, guardian):
        config = await guardian.get_config()
        assert config.default_daily_token_limit == 1_000_000
        assert config.default_monthly_cost_limit_cents == 10000
        assert config.warning_threshold == 0.60
        assert config.downgrade_threshold == 0.85
        assert config.block_threshold == 1.00

    async def test_save_and_reload(self, guardian):
        new = BudgetConfig(enabled=True, default_daily_token_limit=500000, default_monthly_cost_limit_cents=5000)
        await guardian.save_config(new)
        loaded = await guardian.get_config()
        assert loaded.default_daily_token_limit == 500000
        assert loaded.default_monthly_cost_limit_cents == 5000

    async def test_phase_thresholds(self, guardian):
        assert guardian._pct_to_phase(0.5) == BudgetPhase.GREEN
        assert guardian._pct_to_phase(0.6) == BudgetPhase.WARNING
        assert guardian._pct_to_phase(0.85) == BudgetPhase.DOWNGRADE
        assert guardian._pct_to_phase(1.0) == BudgetPhase.BLOCKED
        assert guardian._pct_to_phase(1.5) == BudgetPhase.BLOCKED
