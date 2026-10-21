from datetime import date
from functools import partial

from pydantic import TypeAdapter

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User

from products.customer_analytics.backend.facade.api import get_key_metrics
from products.product_analytics.backend.facade.contracts import InsightSeriesPending

from ..facade import contracts
from ..temporal.inputs import ResolvePinsInputs, ResolvePinsResult
from . import pulse_pins
from .highlight_sources.key_metrics import tile
from .highlight_sources.routine import insight_metric
from .highlight_types import Context

INSIGHT_PREFIX = "insight:"

PINNED_METRICS = TypeAdapter(list[contracts.HighlightMetric])


def resolve_pins(inputs: ResolvePinsInputs) -> ResolvePinsResult:
    context = Context(
        Team.objects.get(id=inputs.team_id),
        User.objects.get(id=inputs.user_id),
        date.fromisoformat(inputs.local_day),
        None if inputs.scopes is None else frozenset(inputs.scopes),
    )
    keys = (
        inputs.keys
        if inputs.keys is not None
        else [pin.key for pin in pulse_pins.get_pins(team_id=inputs.team_id, user_id=inputs.user_id)]
    )
    metrics: list[contracts.HighlightMetric] = []
    pending: list[str] = []
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=context.team.id):
        insights = [key for key in keys if key.startswith(INSIGHT_PREFIX)]
        if insights and context.allows("insight:read"):
            for key in insights:
                metric = context.guard(f"pinned {key}", partial(_insight, context, key, pending), None)
                if metric is not None:
                    metrics.append(metric)
        key_metrics = [key for key in keys if not key.startswith(INSIGHT_PREFIX)]
        if key_metrics and context.allows("customer_analytics:read"):
            found = context.guard(
                "pinned key metrics", partial(get_key_metrics, team=context.team, user=context.user), []
            )
            if found is None:
                pending.extend(key_metrics)
            else:
                by_key = {metric.key: metric for metric in found}
                metrics.extend(tile(by_key[key]) for key in key_metrics if key in by_key)
    return ResolvePinsResult(
        keys=keys,
        found=PINNED_METRICS.dump_json(metrics).decode(),
        pending=pending,
        failed=bool(context.failures),
    )


def _insight(context: Context, key: str, pending: list[str]) -> contracts.HighlightMetric | None:
    try:
        return insight_metric(context, key.removeprefix(INSIGHT_PREFIX), raise_if_pending=True)
    except InsightSeriesPending:
        pending.append(key)
        return None
