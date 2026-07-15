"""PostHog Code billing — seat roster for the usage-report query split.

Code usage bills through the org's `posthog_code_usage` subscription, but only for users on
a usage-based plan: generations from seat-covered users (free/pro/alpha PostHog Code seats)
are excluded from the billed `posthog_code_credits` counter at the query layer. The
authoritative source for who held which seat on a given day is the billing service's
ProductSeat table, exposed via its cross-org active-roster endpoint.

Coverage is org-scoped: a seat covers a user's usage only in the organization that granted
it, so the roster is grouped by organization rather than flattened into one distinct_id set —
a covered seat in one org must not exempt the same user's usage in an org that pays per-usage.
"""

from datetime import date
from typing import Any, TypedDict

from django.conf import settings

import requests
from rest_framework.exceptions import NotAuthenticated
from retry import retry

from ee.billing.billing_manager import handle_billing_service_error
from ee.settings import BILLING_SERVICE_URL

POSTHOG_CODE_PRODUCT_KEY = "posthog_code"
# $0 usage-entitlement seat plans; every other plan key (free/pro/alpha) is seat-covered.
POSTHOG_CODE_USAGE_PLAN_KEY_PREFIX = "posthog-code-usage"


class ActiveRosterSeat(TypedDict):
    user_distinct_id: str
    plan_key: str
    status: str
    organization_id: str


@retry(tries=3, delay=1, backoff=2)
def _fetch_active_roster_page(product_key: str, on_date: date, cursor: str | None) -> dict[str, Any]:
    # Cross-org read, so billing's PublicAPIKey auth instead of the usual per-org JWT.
    api_key = settings.BILLING_SERVICE_API_KEY
    if not api_key:
        raise NotAuthenticated("BILLING_SERVICE_API_KEY is not configured for billing service authentication")
    params: dict[str, str] = {"product_key": product_key, "on_date": on_date.isoformat()}
    if cursor:
        params["cursor"] = cursor
    res = requests.get(
        f"{BILLING_SERVICE_URL}/api/public/seats/active-roster/",
        params=params,
        headers={"X-API-Key": api_key},
        timeout=30,
    )
    handle_billing_service_error(res, valid_codes=(200,))
    return res.json()


def get_seat_covered_distinct_ids_by_org(product_key: str, on_date: date) -> dict[str, set[str]]:
    """Distinct_ids whose usage on `on_date` is covered by a non-usage-plan seat, grouped by the
    id (as a string) of the organization that granted the seat.

    Raises on fetch failure or a malformed roster payload — callers must not swallow this: an
    empty-roster default would bill every seat holder, a full-roster default would bill no one.
    """
    covered: dict[str, set[str]] = {}
    cursor: str | None = None
    while True:
        page = _fetch_active_roster_page(product_key, on_date, cursor)
        seats: list[ActiveRosterSeat] | None = page.get("results")
        if not isinstance(seats, list):
            raise ValueError(
                f"Billing active-roster response for {product_key} on {on_date} has no 'results' list — "
                "refusing to treat it as an empty roster"
            )
        for seat in seats:
            # Direct indexing on purpose: a seat missing a required field raises instead of being
            # silently misclassified as billable.
            if seat["status"] != "active" or seat["plan_key"].startswith(POSTHOG_CODE_USAGE_PLAN_KEY_PREFIX):
                continue
            covered.setdefault(str(seat["organization_id"]), set()).add(seat["user_distinct_id"])
        cursor = page.get("next")
        if not cursor:
            break
    return covered
