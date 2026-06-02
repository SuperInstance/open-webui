# 🏆 Budget Guardian Integration

**Open WebUI + API Spending Limits**

Budget Guardian is a first-class integration that adds budget enforcement, usage tracking, phase-based auto-downgrades, and team billing to Open WebUI — the 100K+ star open-source ChatGPT UI.

---

## Quick Start

```bash
# Enable Budget Guardian
export BUDGET_GUARDIAN_ENABLED=true

# Start Open WebUI as usual
# The budget endpoints are automatically registered
```

That's it. All `/api/chat/completions` and `/api/v1/chat/completions` calls will be tracked.

---

## Architecture

```
User → Open WebUI → Budget Guardian middleware → LLM API
                         │
                    ┌────┴────┐
                    │  Usage  │
                    │  Store  │
                    │ (JSONL) │
                    └─────────┘
                         │
                    ┌────┴────┐
                    │ Budgets │
                    │ Alerts  │
                    │ Config  │
                    └─────────┘
```

Budget Guardian sits between the user and the LLM provider. Every API call is:
1. Intercepted and checked against the user's budget
2. Recorded (tokens + cost) for the usage ledger
3. Evaluated for phase (green → warning → downgrade → blocked)
4. Forwarded to the LLM (or blocked/downgraded)

---

## API Endpoints

### `GET /api/budget/status`
User-facing: returns current usage, phase, and limits.

```json
{
  "enabled": true,
  "user_id": "abc123",
  "phase": "warning",
  "downgrade_to": "gpt-4o-mini",
  "periods": {
    "daily": {
      "tokens_used": 450000,
      "token_limit": 1000000,
      "token_pct": 45.0,
      "cost_cents_used": 112,
      "cost_limit_cents": 500,
      "cost_pct": 22.4
    },
    "monthly": {
      "tokens_used": 18500000,
      "token_limit": 20000000,
      "token_pct": 92.5,
      "cost_cents_used": 4625,
      "cost_limit_cents": 10000,
      "cost_pct": 46.25
    }
  }
}
```

### `GET /api/budget/admin`
Admin dashboard: total spend, per-user breakdown, model costs, alerts, heatmap.

### `POST /api/budget/admin/config`
Update global budget configuration:

```json
{
  "enabled": true,
  "default_daily_token_limit": 1000000,
  "default_monthly_token_limit": 20000000,
  "default_daily_cost_limit_cents": 500,
  "global_alert_webhook_url": "https://hooks.example.com/budget-alerts"
}
```

### `POST /api/budget/admin/user`
Set per-user budget:

```json
{
  "user_id": "abc123",
  "daily_token_limit": 500000,
  "monthly_cost_limit_cents": 5000,
  "downgrade_model": "gpt-4o-mini"
}
```

### `POST /api/budget/admin/team`
Set team budget with rollover:

```json
{
  "team_id": "team-eng",
  "name": "Engineering",
  "member_user_ids": ["abc123", "def456"],
  "monthly_token_limit": 50000000,
  "rollover_enabled": true,
  "alert_threshold": 0.9,
  "alert_webhook_url": "https://hooks.example.com/team-alerts"
}
```

### `GET /api/budget/alerts`
Get budget alert history (admin only).

---

## Phase System

| Phase | Threshold | Behavior |
|-------|-----------|----------|
| 🟢 **Green** | < 60% | Normal operation |
| 🟡 **Warning** | 60-85% | Warning banner, full access |
| 🟠 **Downgrade** | 85-100% | Auto-switch to cheaper model |
| 🔴 **Blocked** | 100%+ | Requests blocked (admin override available) |

---

## Model Pricing

40+ LLM models have real pricing built in:

| Model | Input ($/1M tok) | Output ($/1M tok) |
|-------|-------------------|--------------------|
| GPT-4o | $2.50 | $10.00 |
| GPT-4o Mini | $0.15 | $0.60 |
| o1 | $15.00 | $60.00 |
| Claude 3.5 Sonnet | $3.00 | $15.00 |
| Claude Opus | $15.00 | $75.00 |
| Gemini 2.5 Pro | $1.25 | $10.00 |
| DeepSeek V3 | $0.27 | $1.10 |
| Mistral Large | $2.00 | $6.00 |

Custom pricing can be added via the codebase or the admin API.

---

## Team Budgets with Rollover

Teams share a budget pool across all members. With rollover enabled, unused tokens from one period carry over to the next:

```
Month 1: 50M limit, 30M used → 20M unused
  Rollover (100%): +20M to next period
Month 2: 50M limit + 20M rollover = 70M available
```

---

## Alert System

Alerts fire at configurable thresholds (default: 90%):
- **Webhook delivery**: POST to any URL with JSON payload
- **Per-team channels**: independent webhooks per team
- **Global fallback**: single webhook for all alerts
- **Alert payload** includes user/team, usage %, phase, and limits

---

## Configuration Reference

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `BUDGET_GUARDIAN_ENABLED` | `false` | Enable budget tracking |
| `BUDGET_GUARDIAN_DATA_DIR` | `/tmp/open-webui/budget-guardian` | Storage location |

All other configuration is done through the admin API at `/api/budget/admin/config`.

---

## Extending

### Custom Pricing
Add models to `backend/open_webui/retrieval/budget/pricing.py`:

```python
ModelPricing(
    model_id="my-custom-model",
    display_name="My Custom Model",
    input_price_per_1m=Decimal("0.50"),
    output_price_per_1m=Decimal("2.00"),
)
```

### Database Backend
The default storage uses JSONL files. For production deployments, swap `BudgetStorage` with a SQLAlchemy-backed implementation using the app's existing database connection.

---

## License

Budget Guardian is provided as part of SuperInstance's enhancements to Open WebUI.
Same license as the parent project.
