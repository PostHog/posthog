from datetime import date
from functools import partial

from pydantic import TypeAdapter

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User

from products.customer_analytics.backend.facade.api import get_key_metrics
from products.product_analytics.backend.facade.contracts import InsightSeriesPending

from ..facade import contracts
from ..temporal.inputs import PinnedNumber, ResolvePinsInputs, ResolvePinsResult
from .highlight_sources.key_metrics import tile
from .highlight_sources.routine import dashboard_tile_metric, insight_metric
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
    metrics: list[contracts.HighlightMetric] = []
    pending: list[str] = []
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=context.team.id):
        insights = [pin for pin in inputs.pins if pin.key.startswith(INSIGHT_PREFIX)]
        if insights and context.allows("insight:read"):
            for pin in insights:
                metric = context.guard(f"pinned {pin.key}", partial(_insight, context, pin, pending), None)
                if metric is not None:
                    metrics.append(metric)
        key_metrics = [pin.key for pin in inputs.pins if not pin.key.startswith(INSIGHT_PREFIX)]
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
        keys=[pin.key for pin in inputs.pins],
        found=PINNED_METRICS.dump_json(metrics).decode(),
        pending=pending,
        failed=bool(context.failures),
    )


def _insight(context: Context, pin: PinnedNumber, pending: list[str]) -> contracts.HighlightMetric | None:
    short_id = pin.key.removeprefix(INSIGHT_PREFIX)
    try:
        on_dashboard = (
            dashboard_tile_metric(context, pin.dashboard_id, short_id, raise_if_pending=True)
            if pin.dashboard_id is not None
            else None
        )
        return on_dashboard or insight_metric(context, short_id, raise_if_pending=True)
    except InsightSeriesPending:
        pending.append(pin.key)
        return None
