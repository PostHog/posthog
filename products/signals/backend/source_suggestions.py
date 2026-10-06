"""Which products a report may suggest the team turn on, and the suggestion a report shows.

A report suggests a product only while the team does not use it. A product is in use when the team
opted in to it, or when the shared data freshness registry saw its data recently. That registry is
where each product declares what counts as its data, and it caches its answer per project.
"""

from __future__ import annotations

import structlog
from pydantic import ValidationError

from posthog.data_freshness import get_organization_data_freshness
from posthog.models import Team
from posthog.schema_enums import ProductKey

from products.signals.backend.artefact_schemas import SourceSuggestion
from products.signals.backend.enums import SuggestedSourceProduct
from products.signals.backend.models import SignalReportArtefact

logger = structlog.get_logger(__name__)


def _opted_in(team: Team, product: SuggestedSourceProduct) -> bool:
    # An opt-in counts before any data arrives, so a suggestion stops showing as soon as the team
    # turns the product on.
    if product == SuggestedSourceProduct.SESSION_REPLAY:
        return bool(team.session_recording_opt_in)
    if product == SuggestedSourceProduct.ERROR_TRACKING:
        return bool(team.autocapture_exceptions_opt_in)
    return False


def _products_with_recent_data(team: Team) -> set[str] | None:
    """Products the team received data for recently, or None when a failed probe left it unknown."""
    results = get_organization_data_freshness(str(team.organization_id), [team])
    if not results:
        return None
    return {source.data_source for source in results[0].sources}


def unused_suggestable_products(team: Team) -> list[SuggestedSourceProduct]:
    candidates = [product for product in SuggestedSourceProduct if not _opted_in(team, product)]
    if not candidates:
        return []
    with_data = _products_with_recent_data(team)
    if with_data is None:
        return []
    return [product for product in candidates if ProductKey(product.value) not in with_data]


def current_source_suggestion(team: Team, report_id: str) -> SourceSuggestion | None:
    """The report's latest suggestion, or None when it has none or the team now uses the product."""
    artefact = (
        SignalReportArtefact.objects.filter(
            team_id=team.id, report_id=report_id, type=SignalReportArtefact.ArtefactType.SOURCE_SUGGESTION
        )
        .order_by("-created_at")
        .only("id", "content")
        .first()
    )
    if artefact is None:
        return None
    try:
        suggestion = SourceSuggestion.model_validate_json(artefact.content)
    except ValidationError:
        logger.warning("signals.source_suggestion.invalid_content", report_id=report_id, artefact_id=str(artefact.id))
        return None
    if suggestion.product not in unused_suggestable_products(team):
        return None
    return suggestion
