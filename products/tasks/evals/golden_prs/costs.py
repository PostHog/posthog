import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRICE_TABLE = Path(__file__).resolve().parents[4] / "nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json"


@dataclass(frozen=True, kw_only=True, slots=True)
class TokenPrices:
    """US dollars per token."""

    input: float
    cached_input: float
    output: float


def load_token_prices(path: Path = PRICE_TABLE) -> dict[str, TokenPrices]:
    prices = {}
    for entry in json.loads(path.read_text()):
        default = entry["cost"].get("default", {})
        if "prompt_token" in default and "completion_token" in default:
            prices[entry["model"]] = TokenPrices(
                input=default["prompt_token"],
                cached_input=default.get("cache_read_token", default["prompt_token"]),
                output=default["completion_token"],
            )
    return prices


def case_cost_usd(result: Mapping[str, Any], prices: Mapping[str, TokenPrices]) -> float | None:
    """The cost the agent reported. Codex reports only tokens, so its cost is those tokens at API prices."""
    usage = result["usage"]
    if "total_cost_usd" in usage:
        return usage["total_cost_usd"]
    price = prices.get(f"openai/{result['model']}") if result["runtime"] == "codex" else None
    if price is None or "input_tokens" not in usage:
        return None
    # OpenAI counts cached tokens inside input_tokens.
    cached = usage.get("cached_input_tokens", 0)
    return (
        (usage["input_tokens"] - cached) * price.input
        + cached * price.cached_input
        + usage.get("output_tokens", 0) * price.output
    )
