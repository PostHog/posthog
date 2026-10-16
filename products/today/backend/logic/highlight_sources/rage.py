import hashlib

from products.error_tracking.backend.facade.api import get_issue_basics
from products.web_analytics.backend.facade.rage_pages import (
    ErrorsBeforeRage,
    RagePage,
    find_errors_before_rage,
    find_top_rage_element,
    find_top_rage_page,
)

from ...facade.enums import HighlightLabel
from ..highlight_rules import human, short, users, uses_product
from ..highlight_types import Candidate, Context, Found, Source

RAGE_PAGE = "{people} rage-clicked on {page} in the last 7 days"
RAGE_PAGE_DETAIL = "{clicks} rage clicks · Top element: ‘{element}’"
RAGE_PAGE_NO_ELEMENT_DETAIL = "{clicks} rage clicks"
RAGE_PAGE_ERROR_DETAIL = "{pct}% of sessions saw the error ‘{issue}’ in the 30 seconds before"

RAGE_PRODUCTS = ("Session replay", "Web analytics", "Heatmaps")
MIN_ERROR_SESSIONS = 3
MIN_ERROR_SHARE = 0.3
NO_ERRORS = ErrorsBeforeRage(sessions=0, issue_id=None, issue_sessions=0)


def find(context: Context) -> Found:
    if not uses_product(context, *RAGE_PRODUCTS):
        return Found()
    page = context.daily("rage_page", lambda: find_top_rage_page(context.team, context.user))
    if page is None:
        return Found()
    path_key = hashlib.sha256(page.path.encode()).hexdigest()[:16]
    title = RAGE_PAGE.format(people=users(page.people), page=(page.path or "/")[:40])
    if context.allows("error_tracking:read"):
        errors = context.guard(
            "rage_errors",
            lambda: context.daily(
                f"rage_errors:{path_key}", lambda: find_errors_before_rage(context.team, context.user, page.path)
            ),
            NO_ERRORS,
        )
        error = _error_item(context, page, errors, title)
        if error is not None:
            return Found(items=(error,))
    top_element = context.guard(
        "rage_element",
        lambda: context.daily(
            f"rage_element:{path_key}", lambda: find_top_rage_element(context.team, context.user, page.path)
        ),
        None,
    )
    element = short(top_element or "", 30)
    clicks = human(page.clicks)
    return Found(
        items=(
            Candidate(
                key=f"rage:{page.path}",
                label=HighlightLabel.RISK,
                family="replay",
                importance=0.35,
                relevance=1.0,
                title=title,
                detail=RAGE_PAGE_DETAIL.format(clicks=clicks, element=element)
                if element
                else RAGE_PAGE_NO_ELEMENT_DETAIL.format(clicks=clicks),
                url="/replay/home",
            ),
        )
    )


def _error_item(context: Context, page: RagePage, errors: ErrorsBeforeRage, title: str) -> Candidate | None:
    issue_id = errors.issue_id
    share = errors.issue_sessions / errors.sessions if errors.sessions else 0
    if issue_id is None or errors.issue_sessions < MIN_ERROR_SESSIONS or share < MIN_ERROR_SHARE:
        return None
    issue = context.guard("rage_issue", lambda: get_issue_basics(context.team.id, issue_id), None)
    if issue is None:
        return None
    name = f"{issue.name or 'Issue'}: {issue.description}" if issue.description else issue.name or "Issue"
    return Candidate(
        key=f"rage:{page.path}",
        label=HighlightLabel.RISK,
        family="replay",
        importance=0.6,
        relevance=1.0,
        title=title,
        detail=RAGE_PAGE_ERROR_DETAIL.format(pct=f"{share * 100:.0f}", issue=short(name, 50)),
        url=f"/error_tracking/{issue_id}",
        ref=issue_id,
    )


SOURCE = Source(name="rage", find=find)
