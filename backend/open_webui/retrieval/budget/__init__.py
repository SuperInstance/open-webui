"""
Budget Guardian — API spending limits for Open WebUI.

Provides per-user, per-model, and team-based token/cost budgets
with phase detection (warning → downgrade → block), admin dashboards,
and alerting.
"""

import importlib

from .core import BudgetGuardian
from .models import (
    BudgetAlert,
    BudgetConfig,
    BudgetPhase,
    ModelPricing,
    TeamBudget,
    TokenBudget,
    UsageRecord,
)
from .pricing import MODEL_PRICING_MAP, resolve_model_pricing


def __getattr__(name):
    if name == "budget_router":
        from .router import router
        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BudgetGuardian",
    "BudgetAlert",
    "BudgetConfig",
    "BudgetPhase",
    "ModelPricing",
    "TeamBudget",
    "TokenBudget",
    "UsageRecord",
    "MODEL_PRICING_MAP",
    "resolve_model_pricing",
    "budget_router",
]
