"""Pydantic models and SQLAlchemy tables for budget tracking."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────


class BudgetPhase(str, enum.Enum):
    """Usage phases a user/team can be in."""

    GREEN = "green"  # < 60%
    WARNING = "warning"  # 60% - 85%
    DOWNGRADE = "downgrade"  # 85% - 100%
    BLOCKED = "blocked"  # 100%+


class BudgetPeriod(str, enum.Enum):
    """Rolling time window for a budget."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AlertChannel(str, enum.Enum):
    """Where budget alerts are delivered."""

    EMAIL = "email"
    WEBHOOK = "webhook"
    BOTH = "both"
    NONE = "none"


# ──────────────────────────────────────────────
# Model pricing lookup
# ──────────────────────────────────────────────


class ModelPricing(BaseModel):
    """Per-model cost configuration."""

    model_id: str
    display_name: str = ""
    input_price_per_1m: Decimal = Decimal("0")  # USD per 1M input tokens
    output_price_per_1m: Decimal = Decimal("0")  # USD per 1M output tokens
    cache_read_price_per_1m: Decimal = Decimal("0")
    cache_write_price_per_1m: Decimal = Decimal("0")
    per_request_fee: Decimal = Decimal("0")  # fixed fee per API call

    @property
    def cost_per_input_token(self) -> Decimal:
        return self.input_price_per_1m / Decimal("1_000_000")

    @property
    def cost_per_output_token(self) -> Decimal:
        return self.output_price_per_1m / Decimal("1_000_000")

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> Decimal:
        return (
            Decimal(str(input_tokens)) * self.cost_per_input_token
            + Decimal(str(output_tokens)) * self.cost_per_output_token
            + Decimal(str(cache_read_tokens)) * (self.cache_read_price_per_1m / Decimal("1_000_000"))
            + Decimal(str(cache_write_tokens)) * (self.cache_write_price_per_1m / Decimal("1_000_000"))
            + self.per_request_fee
        )


# ──────────────────────────────────────────────
# Token budget (per-user)
# ──────────────────────────────────────────────


class TokenBudget(BaseModel):
    """Per-user budget configuration."""

    user_id: str
    enabled: bool = True

    # Token caps across all models (0 = unlimited)
    daily_token_limit: int = 0
    weekly_token_limit: int = 0
    monthly_token_limit: int = 0

    # Cost caps in USD cents (0 = unlimited)
    daily_cost_limit_cents: int = 0
    weekly_cost_limit_cents: int = 0
    monthly_cost_limit_cents: int = 0

    # Per-model overrides (model_id → TokenBudget override)
    model_overrides: dict[str, "TokenBudget"] = {}

    # Alert threshold (0.0-1.0, e.g. 0.9 = alert at 90%)
    alert_threshold: float = 0.9

    # Downgrade model (used at 85% phase)
    downgrade_model: Optional[str] = None

    # Admin override — if True, budget checks are skipped
    admin_override: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────
# Team budget
# ──────────────────────────────────────────────


class TeamBudget(BaseModel):
    """Shared budget for a team of users."""

    team_id: str
    name: str
    member_user_ids: list[str] = []

    enabled: bool = True

    # Shared caps
    daily_token_limit: int = 0
    weekly_token_limit: int = 0
    monthly_token_limit: int = 0
    daily_cost_limit_cents: int = 0
    weekly_cost_limit_cents: int = 0
    monthly_cost_limit_cents: int = 0

    # Whether unused budget rolls over to next period
    rollover_enabled: bool = False
    rollover_fraction: float = 1.0  # what fraction of unused rolls over

    # Alert
    alert_threshold: float = 0.9
    alert_channel: AlertChannel = AlertChannel.WEBHOOK
    alert_webhook_url: Optional[str] = None
    alert_emails: list[str] = []

    # Downgrade config
    downgrade_model: Optional[str] = None
    admin_override: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────
# Usage record (single API call)
# ──────────────────────────────────────────────


class UsageRecord(BaseModel):
    """One row per tracked LLM API call."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    team_id: Optional[str] = None

    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    cost_usd: Decimal = Decimal("0")
    currency: str = "USD"

    # Phase at time of call
    phase: BudgetPhase = BudgetPhase.GREEN

    # Whether this call was blocked by budget
    blocked: bool = False

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="allow")


# ──────────────────────────────────────────────
# Budget alert
# ──────────────────────────────────────────────


class BudgetAlert(BaseModel):
    """Record of a triggered budget alert."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    team_id: Optional[str] = None

    alert_type: str  # "warning_60", "downgrade_85", "block_100", "team_90"
    message: str
    phase: BudgetPhase

    # Usage snapshot at alert time
    usage_pct: float
    current_cost_cents: int
    limit_cents: int
    current_tokens: int
    limit_tokens: int

    delivered_via: str = "none"  # email, webhook, both
    delivered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────
# Accumulated usage (materialized / cached)
# ──────────────────────────────────────────────


class AccumulatedUsage(BaseModel):
    """Pre-computed usage totals for a user/team over a window."""

    user_id: Optional[str] = None
    team_id: Optional[str] = None

    period: BudgetPeriod

    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cents: int = 0

    # Per-model breakdown
    per_model: dict[str, "PerModelUsage"] = {}

    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PerModelUsage(BaseModel):
    """Usage breakdown for a single model."""

    model_id: str
    tokens: int = 0
    cost_cents: int = 0
    call_count: int = 0


# ──────────────────────────────────────────────
# Budget config (admin settings, stored as JSON)
# ──────────────────────────────────────────────


class BudgetConfig(BaseModel):
    """Global budget configuration, stored in config table."""

    enabled: bool = False
    default_daily_token_limit: int = 1_000_000
    default_weekly_token_limit: int = 5_000_000
    default_monthly_token_limit: int = 20_000_000

    default_daily_cost_limit_cents: int = 500  # $5
    default_weekly_cost_limit_cents: int = 2500  # $25
    default_monthly_cost_limit_cents: int = 10000  # $100

    # Phase thresholds (fraction of limit)
    warning_threshold: float = 0.60
    downgrade_threshold: float = 0.85
    block_threshold: float = 1.00

    # Alert webhook URL (global)
    global_alert_webhook_url: Optional[str] = None

    # Whether to track usage at all
    tracking_enabled: bool = True

    # Whitelist of models to track (empty = all)
    tracked_models: list[str] = []

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
