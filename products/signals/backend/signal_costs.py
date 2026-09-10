from decimal import ROUND_HALF_UP, Decimal
from time import monotonic
from typing import Literal

from posthog.llm.gateway_client import build_async_openai_client

CostStage = Literal["research", "implementation"]
_COST_STAGES: tuple[CostStage, ...] = ("research", "implementation")
_model_pricings: dict[str, dict[str, str]] | None = None
_model_pricings_expires_at = 0.0


def _value(value: object, name: str, default: int | str | None = None) -> int | str | None:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


# The two gateways spell the cache rates differently: the Python gateway sends `input_cache_read`
# and `input_cache_write`, the Go gateway sends `cache_read` and `cache_write` for the same two
# rates. Read either spelling and keep the name `token_usage_to_spend` looks up, so a cached
# response prices instead of raising when the catalog comes from the Go gateway.
_PRICE_WIRE_NAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prompt", ("prompt",)),
    ("completion", ("completion",)),
    ("input_cache_read", ("input_cache_read", "cache_read")),
    ("input_cache_write", ("input_cache_write", "cache_write")),
)


def _price(pricing: object, wire_names: tuple[str, ...]) -> int | str | None:
    for wire_name in wire_names:
        value = _value(pricing, wire_name)
        if value is not None:
            return value
    return None


def _token_count(usage: object, name: str) -> int:
    value = _value(usage, name, 0)
    return int(value) if value is not None else 0


def token_usage_to_spend(usage: object, pricing: object) -> int:
    """Convert one provider response's token usage to rounded integer USD cents."""
    rates = (
        ("input_tokens", "prompt"),
        ("output_tokens", "completion"),
        ("cache_read_input_tokens", "input_cache_read"),
        ("cache_creation_input_tokens", "input_cache_write"),
    )
    spend = Decimal(0)
    for usage_name, price_name in rates:
        tokens = _token_count(usage, usage_name)
        if not tokens:
            continue
        price = _value(pricing, price_name)
        if price is None:
            raise ValueError(f"Model pricing is missing {price_name} for {tokens} {usage_name}")
        spend += Decimal(str(price)) * tokens
    return int((spend * 100).to_integral_value(rounding=ROUND_HALF_UP))


async def get_model_pricing(model: str) -> dict[str, str]:
    """Return the gateway catalog's per-token USD prices for a configured model."""
    global _model_pricings, _model_pricings_expires_at
    if _model_pricings is None or monotonic() >= _model_pricings_expires_at:
        async with build_async_openai_client("signals") as client:
            page = await client.models.list()
        pricings: dict[str, dict[str, str]] = {}
        for catalog_model in page.data:
            pricing = _value(catalog_model, "pricing")
            model_id = _value(catalog_model, "id")
            if model_id is None or pricing is None:
                continue
            if _value(pricing, "prompt") is None or _value(pricing, "completion") is None:
                continue
            pricings[str(model_id)] = {
                name: str(value)
                for name, wire_names in _PRICE_WIRE_NAMES
                if (value := _price(pricing, wire_names)) is not None
            }
        _model_pricings = pricings
        _model_pricings_expires_at = monotonic() + 3600
    try:
        return _model_pricings[model]
    except KeyError as error:
        raise LookupError(f"Model {model!r} is not priced by the gateway catalog") from error


def normalise_cost(model: str, spend: int) -> int:
    return spend


def _cost_values(metadata: dict, name: str) -> dict[CostStage, int]:
    values = metadata.setdefault(name, {})
    for stage in _COST_STAGES:
        values.setdefault(stage, 0)
    return values


def add_cost(
    metadata: dict,
    model: str,
    token_cost: int = 0,
    compute_cost: int = 0,
    stage: CostStage = "research",
) -> None:
    token_costs = _cost_values(metadata, "token_cost")
    compute_costs = _cost_values(metadata, "compute_cost")
    token_costs[stage] += normalise_cost(model, token_cost)
    compute_costs[stage] += normalise_cost(model, compute_cost)


def merge_costs(target: dict, source: dict) -> None:
    for name in ("token_cost", "compute_cost"):
        target_values = _cost_values(target, name)
        source_values = _cost_values(source, name)
        for stage in _COST_STAGES:
            target_values[stage] += source_values[stage]
