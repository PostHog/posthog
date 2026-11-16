from posthog.models.cohortmembership.query_rewrite import SavedQueryRewrite, rewrite_query_nodes, rewrite_saved_rows

from products.endpoints.backend.models import EndpointVersion


def rewrite_cohort_membership_queries(team_id: int, apply: bool) -> list[SavedQueryRewrite]:
    # Every version is rewritten in place, because a caller can still pin an older one.
    return rewrite_saved_rows(
        EndpointVersion._base_manager.filter(team_id=team_id), "query", "endpoint version", rewrite_query_nodes, apply
    )
