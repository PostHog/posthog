from decimal import Decimal


def cost_to_spend(token_cost_microusd: int, *, task_count: int = 0) -> Decimal:
    """Customer spend in USD cents: token cost plus four cents per task run."""
    if token_cost_microusd < 0 or task_count < 0:
        raise ValueError("Cost and task count must be nonnegative")
    return Decimal(token_cost_microusd) / 10_000 + Decimal(4) * task_count
