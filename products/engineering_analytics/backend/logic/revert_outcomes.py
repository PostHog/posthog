from products.engineering_analytics.backend.facade.contracts import RevertOutcomes
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.revert_outcomes import query_revert_outcomes


def build_revert_outcomes(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
) -> RevertOutcomes:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_revert_outcomes(curated=curated, date_from=parsed_from, date_to=parsed_to)
