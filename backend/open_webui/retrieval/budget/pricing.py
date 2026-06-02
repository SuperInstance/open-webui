"""
Real-world model pricing map for major LLM providers.
Prices are in USD per 1M tokens (input / output) as of mid-2025.
"""

from decimal import Decimal

from .models import ModelPricing

# ──────────────────────────────────────────────
# Major model pricing
# Price units: USD per 1 million tokens
# ──────────────────────────────────────────────

MODEL_PRICING_MAP: dict[str, ModelPricing] = {}

# ── OpenAI ────────────────────────────────────

_openai_models: list[ModelPricing] = [
    # GPT-4o family
    ModelPricing(
        model_id="gpt-4o",
        display_name="GPT-4o",
        input_price_per_1m=Decimal("2.50"),
        output_price_per_1m=Decimal("10.00"),
        cache_read_price_per_1m=Decimal("1.25"),
    ),
    ModelPricing(
        model_id="gpt-4o-2024-08-06",
        display_name="GPT-4o (Aug 2024)",
        input_price_per_1m=Decimal("2.50"),
        output_price_per_1m=Decimal("10.00"),
        cache_read_price_per_1m=Decimal("1.25"),
    ),
    ModelPricing(
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        input_price_per_1m=Decimal("0.15"),
        output_price_per_1m=Decimal("0.60"),
        cache_read_price_per_1m=Decimal("0.075"),
    ),
    ModelPricing(
        model_id="gpt-4o-mini-2024-07-18",
        display_name="GPT-4o Mini (Jul 2024)",
        input_price_per_1m=Decimal("0.15"),
        output_price_per_1m=Decimal("0.60"),
        cache_read_price_per_1m=Decimal("0.075"),
    ),
    # GPT-4 Turbo
    ModelPricing(
        model_id="gpt-4-turbo",
        display_name="GPT-4 Turbo",
        input_price_per_1m=Decimal("10.00"),
        output_price_per_1m=Decimal("30.00"),
    ),
    ModelPricing(
        model_id="gpt-4",
        display_name="GPT-4",
        input_price_per_1m=Decimal("30.00"),
        output_price_per_1m=Decimal("60.00"),
    ),
    # o1 / o3
    ModelPricing(
        model_id="o1",
        display_name="o1",
        input_price_per_1m=Decimal("15.00"),
        output_price_per_1m=Decimal("60.00"),
        cache_read_price_per_1m=Decimal("7.50"),
    ),
    ModelPricing(
        model_id="o1-mini",
        display_name="o1 Mini",
        input_price_per_1m=Decimal("1.10"),
        output_price_per_1m=Decimal("4.40"),
        cache_read_price_per_1m=Decimal("0.55"),
    ),
    ModelPricing(
        model_id="o3-mini",
        display_name="o3 Mini",
        input_price_per_1m=Decimal("1.10"),
        output_price_per_1m=Decimal("4.40"),
        cache_read_price_per_1m=Decimal("0.55"),
    ),
    # GPT-4.1
    ModelPricing(
        model_id="gpt-4.1",
        display_name="GPT-4.1",
        input_price_per_1m=Decimal("2.00"),
        output_price_per_1m=Decimal("8.00"),
        cache_read_price_per_1m=Decimal("0.50"),
    ),
    ModelPricing(
        model_id="gpt-4.1-mini",
        display_name="GPT-4.1 Mini",
        input_price_per_1m=Decimal("0.40"),
        output_price_per_1m=Decimal("1.60"),
        cache_read_price_per_1m=Decimal("0.10"),
    ),
    ModelPricing(
        model_id="gpt-4.1-nano",
        display_name="GPT-4.1 Nano",
        input_price_per_1m=Decimal("0.10"),
        output_price_per_1m=Decimal("0.40"),
        cache_read_price_per_1m=Decimal("0.025"),
    ),
    # Embeddings
    ModelPricing(
        model_id="text-embedding-3-large",
        display_name="text-embedding-3-large",
        input_price_per_1m=Decimal("0.13"),
    ),
    ModelPricing(
        model_id="text-embedding-3-small",
        display_name="text-embedding-3-small",
        input_price_per_1m=Decimal("0.02"),
    ),
    ModelPricing(
        model_id="text-embedding-ada-002",
        display_name="text-embedding-ada-002",
        input_price_per_1m=Decimal("0.10"),
    ),
]

for _m in _openai_models:
    MODEL_PRICING_MAP[_m.model_id] = _m

# ── Anthropic ─────────────────────────────────

_anthropic_models: list[ModelPricing] = [
    ModelPricing(
        model_id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
        cache_write_price_per_1m=Decimal("3.75"),
        cache_read_price_per_1m=Decimal("0.30"),
    ),
    ModelPricing(
        model_id="claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku",
        input_price_per_1m=Decimal("0.80"),
        output_price_per_1m=Decimal("4.00"),
        cache_write_price_per_1m=Decimal("1.00"),
        cache_read_price_per_1m=Decimal("0.08"),
    ),
    ModelPricing(
        model_id="claude-3-opus-20240229",
        display_name="Claude 3 Opus",
        input_price_per_1m=Decimal("15.00"),
        output_price_per_1m=Decimal("75.00"),
        cache_write_price_per_1m=Decimal("18.75"),
        cache_read_price_per_1m=Decimal("1.50"),
    ),
    ModelPricing(
        model_id="claude-3-sonnet-20240229",
        display_name="Claude 3 Sonnet",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
        cache_write_price_per_1m=Decimal("3.75"),
        cache_read_price_per_1m=Decimal("0.30"),
    ),
    ModelPricing(
        model_id="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        input_price_per_1m=Decimal("0.25"),
        output_price_per_1m=Decimal("1.25"),
        cache_write_price_per_1m=Decimal("0.30"),
        cache_read_price_per_1m=Decimal("0.03"),
    ),
    ModelPricing(
        model_id="claude-4-sonnet",
        display_name="Claude 4 Sonnet",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
        cache_write_price_per_1m=Decimal("3.75"),
        cache_read_price_per_1m=Decimal("0.30"),
    ),
    ModelPricing(
        model_id="claude-4-opus",
        display_name="Claude 4 Opus",
        input_price_per_1m=Decimal("15.00"),
        output_price_per_1m=Decimal("75.00"),
        cache_write_price_per_1m=Decimal("18.75"),
        cache_read_price_per_1m=Decimal("1.50"),
    ),
]

for _m in _anthropic_models:
    MODEL_PRICING_MAP[_m.model_id] = _m

# ── Google (Gemini) ───────────────────────────

_gemini_models: list[ModelPricing] = [
    ModelPricing(
        model_id="gemini-2.5-pro-exp-03-25",
        display_name="Gemini 2.5 Pro",
        input_price_per_1m=Decimal("1.25"),
        output_price_per_1m=Decimal("10.00"),
        cache_read_price_per_1m=Decimal("0.03125"),
    ),
    ModelPricing(
        model_id="gemini-2.5-flash-preview-04-17",
        display_name="Gemini 2.5 Flash",
        input_price_per_1m=Decimal("0.15"),
        output_price_per_1m=Decimal("0.60"),
        cache_read_price_per_1m=Decimal("0.0075"),
    ),
    ModelPricing(
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        input_price_per_1m=Decimal("0.10"),
        output_price_per_1m=Decimal("0.40"),
        cache_read_price_per_1m=Decimal("0.025"),
    ),
    ModelPricing(
        model_id="gemini-2.0-flash-lite",
        display_name="Gemini 2.0 Flash Lite",
        input_price_per_1m=Decimal("0.075"),
        output_price_per_1m=Decimal("0.30"),
        cache_read_price_per_1m=Decimal("0.01875"),
    ),
    ModelPricing(
        model_id="gemini-1.5-pro",
        display_name="Gemini 1.5 Pro",
        input_price_per_1m=Decimal("1.25"),
        output_price_per_1m=Decimal("5.00"),
        cache_read_price_per_1m=Decimal("0.03125"),
    ),
    ModelPricing(
        model_id="gemini-1.5-flash",
        display_name="Gemini 1.5 Flash",
        input_price_per_1m=Decimal("0.075"),
        output_price_per_1m=Decimal("0.30"),
        cache_read_price_per_1m=Decimal("0.01875"),
    ),
    # Embeddings
    ModelPricing(
        model_id="text-embedding-004",
        display_name="text-embedding-004",
        input_price_per_1m=Decimal("0.0001"),
    ),
]

for _m in _gemini_models:
    MODEL_PRICING_MAP[_m.model_id] = _m

# ── Meta (Llama), Mistral, DeepSeek, etc. ─────

_other_models: list[ModelPricing] = [
    # DeepSeek
    ModelPricing(
        model_id="deepseek-chat",
        display_name="DeepSeek V3",
        input_price_per_1m=Decimal("0.27"),
        output_price_per_1m=Decimal("1.10"),
        cache_read_price_per_1m=Decimal("0.07"),
    ),
    ModelPricing(
        model_id="deepseek-reasoner",
        display_name="DeepSeek R1",
        input_price_per_1m=Decimal("0.55"),
        output_price_per_1m=Decimal("2.19"),
        cache_read_price_per_1m=Decimal("0.14"),
    ),
    # Mistral
    ModelPricing(
        model_id="mistral-large-2411",
        display_name="Mistral Large",
        input_price_per_1m=Decimal("2.00"),
        output_price_per_1m=Decimal("6.00"),
    ),
    ModelPricing(
        model_id="mistral-small-2501",
        display_name="Mistral Small",
        input_price_per_1m=Decimal("0.20"),
        output_price_per_1m=Decimal("0.60"),
    ),
    ModelPricing(
        model_id="mistral-embed",
        display_name="Mistral Embed",
        input_price_per_1m=Decimal("0.10"),
    ),
    # Groq / open models (free tier)
    ModelPricing(
        model_id="llama-3.3-70b-versatile",
        display_name="Llama 3.3 70B (Groq)",
        input_price_per_1m=Decimal("0.59"),
        output_price_per_1m=Decimal("0.79"),
    ),
    ModelPricing(
        model_id="llama-3.1-8b-instant",
        display_name="Llama 3.1 8B (Groq)",
        input_price_per_1m=Decimal("0.05"),
        output_price_per_1m=Decimal("0.08"),
    ),
    ModelPricing(
        model_id="mixtral-8x7b-32768",
        display_name="Mixtral 8x7B (Groq)",
        input_price_per_1m=Decimal("0.24"),
        output_price_per_1m=Decimal("0.24"),
    ),
    # Cohere
    ModelPricing(
        model_id="command-r-plus",
        display_name="Command R+",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
    ),
    ModelPricing(
        model_id="command-r",
        display_name="Command R",
        input_price_per_1m=Decimal("0.50"),
        output_price_per_1m=Decimal("1.50"),
    ),
    # Perplexity
    ModelPricing(
        model_id="sonar-pro",
        display_name="Sonar Pro",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
    ),
    ModelPricing(
        model_id="sonar",
        display_name="Sonar",
        input_price_per_1m=Decimal("1.00"),
        output_price_per_1m=Decimal("1.00"),
    ),
]

for _m in _other_models:
    MODEL_PRICING_MAP[_m.model_id] = _m


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def resolve_model_pricing(model_id: str) -> ModelPricing | None:
    """
    Look up a model's pricing. Handles version suffixes and partial matches
    (e.g. 'gpt-4o-2024-08-06' matches pricing for 'gpt-4o').

    Priority:
      1. Exact match in MODEL_PRICING_MAP
      2. Suffix-stripped match (dash-separated, right to left)
      3. Prefix match (model_id starts with a known key)
    """
    # Exact match
    if model_id in MODEL_PRICING_MAP:
        return MODEL_PRICING_MAP[model_id]

    # Suffix-stripped: remove trailing date/version parts
    parts = model_id.split("-")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:i])
        if candidate in MODEL_PRICING_MAP:
            return MODEL_PRICING_MAP[candidate]

    # Prefix match: known key is a prefix of model_id
    for key in sorted(MODEL_PRICING_MAP, key=len, reverse=True):
        if model_id.startswith(key):
            return MODEL_PRICING_MAP[key]

    # Check for common prefix patterns
    base_lookups = [
        "gpt-4o",
        "gpt-4",
        "gpt-3.5",
        "claude-3",
        "claude-4",
        "gemini-2",
        "gemini-1.5",
        "deepseek",
        "mistral",
        "llama",
        "command",
    ]
    for base in base_lookups:
        if model_id.startswith(base):
            for key, pricing in MODEL_PRICING_MAP.items():
                if key.startswith(base):
                    return pricing

    return None
