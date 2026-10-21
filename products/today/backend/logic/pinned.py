from dataclasses import replace
from datetime import date
from functools import partial

from pydantic import TypeAdapter

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User

from products.customer_analytics.backend.facade.api import get_key_metrics

from ..facade import contracts
from ..temporal.inputs import PinnedNumber, ResolvePinsInputs, ResolvePinsResult
from .highlight_sources.key_metrics import tile
from .highlight_sources.routine import dashboard_tile_metric, insight_metric
from .highlight_types import Context
from .pulse_pins import INSIGHT_PREFIX, required_scopes

PINNED_METRICS = TypeAdapter(list[contracts.HighlightMetric])


def resolve_pins(inputs: ResolvePinsInputs) -> ResolvePinsResult:
    context = Context(
        Team.objects.get(id=inputs.team_id),
        User.objects.get(id=inputs.user_id),
        date.fromisoformat(inputs.local_day),
        None if inputs.scopes is None else frozenset(inputs.scopes),
    )
    metrics: list[contracts.HighlightMetric] = []
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=context.team.id):
        for pin in inputs.pins:
            if not pin.key.startswith(INSIGHT_PREFIX) or not context.allows(
                *required_scopes(pin.key, pin.dashboard_id)
            ):
                continue
            metric = context.guard(f"pinned {pin.key}", partial(_insight, context, pin), None)
            if metric is not None:
                metrics.append(replace(metric, reason=None))
        key_metrics = [pin.key for pin in inputs.pins if not pin.key.startswith(INSIGHT_PREFIX)]
        if key_metrics and context.allows("customer_analytics:read"):
            found = context.guard(
                "pinned key metrics", partial(get_key_metrics, team=context.team, user=context.user), None
            )
            by_key = {metric.key: metric for metric in found or []}
            metrics.extend(replace(tile(by_key[key]), reason=None) for key in key_metrics if key in by_key)
    return ResolvePinsResult(found=PINNED_METRICS.dump_json(metrics).decode())


def _insight(context: Context, pin: PinnedNumber) -> contracts.HighlightMetric | None:
    short_id = pin.key.removeprefix(INSIGHT_PREFIX)
    if pin.dashboard_id is not None:
        return dashboard_tile_metric(context, pin.dashboard_id, short_id, blocking=True)
    return insight_metric(context, short_id, blocking=True)
