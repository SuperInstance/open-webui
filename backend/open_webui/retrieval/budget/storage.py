"""
Budget Guardian storage — persists usage records, budgets, config, and alerts.

Uses the existing open-webui DB infrastructure (SQLAlchemy + JSON columns)
and flat-file storage for runtime simplicity. Data is stored under a
configurable directory and in the app's existing config table.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from .models import (
    AccumulatedUsage,
    BudgetPeriod,
    PerModelUsage,
)

log = logging.getLogger(__name__)

# Where budget data lives
BUDGET_DIR = os.environ.get(
    "BUDGET_GUARDIAN_DATA_DIR",
    "/tmp/open-webui/budget-guardian",
)

# ──────────────────────────────────────────────
# In-memory storage (production would use DB)
# ──────────────────────────────────────────────


class BudgetStorage:
    """
    Storage layer for Budget Guardian.

    In this initial implementation, data is stored in-memory and synced to
    JSON files. A production deployment would use the app's SQL database.
    """

    def __init__(self):
        os.makedirs(BUDGET_DIR, exist_ok=True)
        os.makedirs(os.path.join(BUDGET_DIR, "usage"), exist_ok=True)
        os.makedirs(os.path.join(BUDGET_DIR, "alerts"), exist_ok=True)
        os.makedirs(os.path.join(BUDGET_DIR, "budgets"), exist_ok=True)
        os.makedirs(os.path.join(BUDGET_DIR, "rollovers"), exist_ok=True)

        # In-memory stores
        self._config: Optional[dict] = None
        self._usage: list[dict] = []
        self._user_budgets: dict[str, dict] = {}
        self._team_budgets: dict[str, dict] = {}
        self._alerts: list[dict] = []
        self._rollovers: dict[str, int] = {}

        self._load_all()

    # ── Persistence helpers ────────────────────

    def _usage_path(self) -> str:
        return os.path.join(BUDGET_DIR, "usage", "records.jsonl")

    def _alerts_path(self) -> str:
        return os.path.join(BUDGET_DIR, "alerts", "alerts.jsonl")

    def _config_path(self) -> str:
        return os.path.join(BUDGET_DIR, "config.json")

    def _user_budget_path(self, user_id: str) -> str:
        return os.path.join(BUDGET_DIR, "budgets", f"user_{user_id}.json")

    def _team_budget_path(self, team_id: str) -> str:
        return os.path.join(BUDGET_DIR, "budgets", f"team_{team_id}.json")

    def _rollovers_path(self) -> str:
        return os.path.join(BUDGET_DIR, "rollovers", "rollovers.json")

    def _load_all(self):
        """Load all persisted data into memory."""
        # Config
        if os.path.exists(self._config_path()):
            with open(self._config_path()) as f:
                self._config = json.load(f)

        # Usage records
        if os.path.exists(self._usage_path()):
            with open(self._usage_path()) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._usage.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        # Alerts
        if os.path.exists(self._alerts_path()):
            with open(self._alerts_path()) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._alerts.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        # Rollovers
        if os.path.exists(self._rollovers_path()):
            with open(self._rollovers_path()) as f:
                self._rollovers = json.load(f)

    # ── Config ─────────────────────────────────

    async def load_config(self) -> Optional[dict]:
        return self._config

    async def save_config(self, data: dict) -> None:
        self._config = data
        with open(self._config_path(), "w") as f:
            json.dump(data, f, default=str, indent=2)

    # ── User budgets ───────────────────────────

    async def save_user_budget(self, user_id: str, data: dict) -> None:
        self._user_budgets[user_id] = data
        with open(self._user_budget_path(user_id), "w") as f:
            json.dump(data, f, default=str, indent=2)

    async def load_user_budget(self, user_id: str) -> Optional[dict]:
        if user_id in self._user_budgets:
            return self._user_budgets[user_id]
        path = self._user_budget_path(user_id)
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                self._user_budgets[user_id] = data
                return data
        return None

    async def load_all_user_budgets(self) -> list[dict]:
        budgets = list(self._user_budgets.values())
        # Also scan disk
        budget_dir = os.path.join(BUDGET_DIR, "budgets")
        for fname in os.listdir(budget_dir):
            if fname.startswith("user_") and fname.endswith(".json"):
                user_id = fname[5:-5]
                if user_id not in self._user_budgets:
                    await self.load_user_budget(user_id)
                    if user_id in self._user_budgets:
                        budgets.append(self._user_budgets[user_id])
        return budgets

    # ── Team budgets ───────────────────────────

    async def save_team_budget(self, team_id: str, data: dict) -> None:
        self._team_budgets[team_id] = data
        with open(self._team_budget_path(team_id), "w") as f:
            json.dump(data, f, default=str, indent=2)

    async def load_team_budget(self, team_id: str) -> Optional[dict]:
        if team_id in self._team_budgets:
            return self._team_budgets[team_id]
        path = self._team_budget_path(team_id)
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                self._team_budgets[team_id] = data
                return data
        return None

    async def load_all_team_budgets(self) -> list[dict]:
        budgets = list(self._team_budgets.values())
        budget_dir = os.path.join(BUDGET_DIR, "budgets")
        for fname in os.listdir(budget_dir):
            if fname.startswith("team_") and fname.endswith(".json"):
                team_id = fname[5:-5]
                if team_id not in self._team_budgets:
                    await self.load_team_budget(team_id)
                    if team_id in self._team_budgets:
                        budgets.append(self._team_budgets[team_id])
        return budgets

    # ── Usage ──────────────────────────────────

    async def save_usage(self, record: dict) -> None:
        self._usage.append(record)
        # Append to JSONL
        with open(self._usage_path(), "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _window_start(self, period: BudgetPeriod, now: datetime) -> datetime:
        """Get the start of the rolling window."""
        if period == BudgetPeriod.DAILY:
            return now - timedelta(hours=24)
        elif period == BudgetPeriod.WEEKLY:
            return now - timedelta(days=7)
        else:
            return now - timedelta(days=30)

    async def get_usage_tokens(
        self, user_id: str, period: BudgetPeriod, now: datetime
    ) -> int:
        """Get total tokens for a user in a given period."""
        window = self._window_start(period, now)
        total = 0
        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if r.get("user_id") == user_id and ts >= window and not r.get("blocked", False):
                total += r.get("input_tokens", 0) + r.get("output_tokens", 0)
        return total

    async def get_usage_cost_cents(
        self, user_id: str, period: BudgetPeriod, now: datetime
    ) -> int:
        """Get total cost in cents for a user in a given period."""
        window = self._window_start(period, now)
        total = Decimal("0")
        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if r.get("user_id") == user_id and ts >= window and not r.get("blocked", False):
                cost_str = r.get("cost_usd", "0")
                try:
                    total += Decimal(str(cost_str))
                except Exception:
                    pass
        return int(total * 100)  # Convert USD to cents

    async def get_team_usage_tokens(
        self, team_id: str, period: BudgetPeriod, now: datetime
    ) -> int:
        """Get total tokens for a team in a given period."""
        window = self._window_start(period, now)
        total = 0
        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if r.get("team_id") == team_id and ts >= window and not r.get("blocked", False):
                total += r.get("input_tokens", 0) + r.get("output_tokens", 0)
        return total

    async def get_team_usage_cost_cents(
        self, team_id: str, period: BudgetPeriod, now: datetime
    ) -> int:
        window = self._window_start(period, now)
        total = Decimal("0")
        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if r.get("team_id") == team_id and ts >= window and not r.get("blocked", False):
                cost_str = r.get("cost_usd", "0")
                try:
                    total += Decimal(str(cost_str))
                except Exception:
                    pass
        return int(total * 100)

    def _parse_ts(self, ts_str: str) -> datetime:
        """Parse an ISO timestamp string safely."""
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    async def get_accumulated_usage(
        self, user_id: str, period: BudgetPeriod, now: datetime
    ) -> AccumulatedUsage:
        """Get pre-computed usage for a user."""
        window = self._window_start(period, now)
        total_tokens = 0
        total_input = 0
        total_output = 0
        total_cost = Decimal("0")
        per_model: dict[str, dict] = {}

        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if r.get("user_id") == user_id and ts >= window and not r.get("blocked", False):
                inp = r.get("input_tokens", 0)
                out = r.get("output_tokens", 0)
                total_tokens += inp + out
                total_input += inp
                total_output += out
                cost_str = r.get("cost_usd", "0")
                try:
                    total_cost += Decimal(str(cost_str))
                except Exception:
                    pass

                mid = r.get("model_id", "unknown")
                if mid not in per_model:
                    per_model[mid] = {"tokens": 0, "cost_cents": 0, "count": 0}
                per_model[mid]["tokens"] += inp + out
                per_model[mid]["count"] += 1
                try:
                    per_model[mid]["cost_cents"] += int(Decimal(str(cost_str)) * 100)
                except Exception:
                    pass

        return AccumulatedUsage(
            user_id=user_id,
            period=period,
            total_tokens=total_tokens,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_cents=int(total_cost * 100),
            per_model={
                mid: PerModelUsage(
                    model_id=mid,
                    tokens=v["tokens"],
                    cost_cents=v["cost_cents"],
                    call_count=v["count"],
                )
                for mid, v in per_model.items()
            },
        )

    async def get_team_accumulated_usage(
        self, team_id: str, period: BudgetPeriod, now: datetime
    ) -> AccumulatedUsage:
        """Get pre-computed usage for a team."""
        window = self._window_start(period, now)
        total_tokens = 0
        total_input = 0
        total_output = 0
        total_cost = Decimal("0")
        per_model: dict[str, dict] = {}

        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if r.get("team_id") == team_id and ts >= window and not r.get("blocked", False):
                inp = r.get("input_tokens", 0)
                out = r.get("output_tokens", 0)
                total_tokens += inp + out
                total_input += inp
                total_output += out
                cost_str = r.get("cost_usd", "0")
                try:
                    total_cost += Decimal(str(cost_str))
                except Exception:
                    pass

                mid = r.get("model_id", "unknown")
                if mid not in per_model:
                    per_model[mid] = {"tokens": 0, "cost_cents": 0, "count": 0}
                per_model[mid]["tokens"] += inp + out
                per_model[mid]["count"] += 1
                try:
                    per_model[mid]["cost_cents"] += int(Decimal(str(cost_str)) * 100)
                except Exception:
                    pass

        return AccumulatedUsage(
            team_id=team_id,
            period=period,
            total_tokens=total_tokens,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_cents=int(total_cost * 100),
            per_model={
                mid: PerModelUsage(
                    model_id=mid,
                    tokens=v["tokens"],
                    cost_cents=v["cost_cents"],
                    call_count=v["count"],
                )
                for mid, v in per_model.items()
            },
        )

    async def get_all_users_usage_summary(
        self, period: BudgetPeriod, now: datetime
    ) -> list[dict]:
        """Get usage summary for all users (for admin dashboard)."""
        user_data: dict[str, dict] = {}
        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if ts >= self._window_start(period, now) and not r.get("blocked", False):
                uid = r.get("user_id", "unknown")
                if uid not in user_data:
                    user_data[uid] = {
                        "user_id": uid,
                        "total_tokens": 0,
                        "total_cost_cents": 0,
                        "call_count": 0,
                        "models": set(),
                    }
                user_data[uid]["total_tokens"] += r.get("input_tokens", 0) + r.get(
                    "output_tokens", 0
                )
                cost_str = r.get("cost_usd", "0")
                try:
                    user_data[uid]["total_cost_cents"] += int(
                        Decimal(str(cost_str)) * 100
                    )
                except Exception:
                    pass
                user_data[uid]["call_count"] += 1
                user_data[uid]["models"].add(r.get("model_id", "unknown"))

        result = []
        for uid, data in user_data.items():
            data["models"] = list(data["models"])
            result.append(data)

        result.sort(key=lambda x: x["total_cost_cents"], reverse=True)
        return result

    async def get_total_spend(
        self, period: BudgetPeriod, now: datetime
    ) -> dict:
        """Get aggregate spend info."""
        window = self._window_start(period, now)
        total_cost = Decimal("0")
        total_tokens = 0
        model_breakdown: dict[str, dict] = {}
        call_count = 0

        for r in self._usage:
            ts = self._parse_ts(r.get("timestamp", ""))
            if ts >= window and not r.get("blocked", False):
                call_count += 1
                total_tokens += r.get("input_tokens", 0) + r.get("output_tokens", 0)
                cost_str = r.get("cost_usd", "0")
                try:
                    total_cost += Decimal(str(cost_str))
                except Exception:
                    pass

                mid = r.get("model_id", "unknown")
                if mid not in model_breakdown:
                    model_breakdown[mid] = {
                        "tokens": 0,
                        "cost_cents": 0,
                        "calls": 0,
                    }
                model_breakdown[mid]["tokens"] += r.get("input_tokens", 0) + r.get(
                    "output_tokens", 0
                )
                model_breakdown[mid]["calls"] += 1
                try:
                    model_breakdown[mid]["cost_cents"] += int(
                        Decimal(str(cost_str)) * 100
                    )
                except Exception:
                    pass

        return {
            "period": period.value,
            "total_cost_usd": float(total_cost),
            "total_cost_cents": int(total_cost * 100),
            "total_tokens": total_tokens,
            "total_calls": call_count,
            "model_breakdown": model_breakdown,
        }

    # ── Alerts ─────────────────────────────────

    async def save_alert(self, alert: dict) -> None:
        self._alerts.append(alert)
        with open(self._alerts_path(), "a") as f:
            f.write(json.dumps(alert, default=str) + "\n")

    async def get_alerts(
        self,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        results = []
        for a in reversed(self._alerts):
            if user_id and a.get("user_id") != user_id:
                continue
            if team_id and a.get("team_id") != team_id:
                continue
            results.append(a)
            if len(results) >= limit:
                break
        return results

    # ── Rollovers ──────────────────────────────

    async def save_rollover(self, team_id: str, amount: int) -> None:
        self._rollovers[team_id] = self._rollovers.get(team_id, 0) + amount
        with open(self._rollovers_path(), "w") as f:
            json.dump(self._rollovers, f)

    async def get_rollover(self, team_id: str) -> int:
        return self._rollovers.get(team_id, 0)
