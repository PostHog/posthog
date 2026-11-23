import hashlib
from dataclasses import field
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.core import signing
from django.core.cache import cache

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models import Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from products.signals.backend.github_actor import GITHUB_LOGIN_PATTERN
from products.signals.backend.models import SignalReport
from products.signals.backend.monitor_pr import InvalidPullRequest, monitor_key, pr_identity
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_content_gates import team_pr_monitoring_enabled, team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import effective_report_status

PAGE_SIZE = 25
SCAN_LIMIT = 250
CURSOR_SALT = "signals.pr-browser"


@frozen
class PRReport:
    id: str
    status: str


@frozen
class BrowserPR:
    url: str
    repository: str
    number: int
    title: str
    state: str
    draft: bool
    author: str
    created_at: str
    updated_at: str
    report: PRReport | None


@frozen
class PRPage:
    results: list[BrowserPR]
    next_cursor: str | None
    github_login: str | None
    has_integration: bool
    incomplete: bool


@frozen
class PRCheck:
    name: str
    status: str
    conclusion: str | None
    url: str | None


@frozen
class PROverview:
    pull_request: BrowserPR
    body: str
    head_branch: str
    base_branch: str
    additions: int
    deletions: int
    changed_files: int
    checks: list[PRCheck]
    checks_available: bool
    has_conflicts: bool


@frozen
class _RegisteredGitHubIntegration:
    id: int
    github: GitHubIntegration
    owner: str | None
    repositories: set[str]


def _authorize(team: Team, user: User) -> None:
    if not team_pr_monitoring_enabled(team.id):
        raise PermissionError("PR monitoring is not enabled for this project.")
    if not may_read_reports(team=team, user=user):
        raise PermissionError("You need permission to view tasks in this project.")


def _integration_owner(github: GitHubIntegration) -> str | None:
    account = github.integration.config.get("account")
    name = account.get("name") if isinstance(account, dict) else github.integration.config.get("organization")
    return name if isinstance(name, str) and GITHUB_LOGIN_PATTERN.fullmatch(name) else None


def _integrations(team_id: int) -> list[_RegisteredGitHubIntegration]:
    result = []
    seen: set[str] = set()
    for integration in sorted(IntegrationManager.github.oauth.list(team_id), key=lambda row: row.id):
        github = GitHubIntegration(integration, source="signals_pr_browser", priority=Priority.NORMAL)
        repositories = {
            str(repo["full_name"]).lower()
            for repo in github.list_all_cached_repositories()
            if isinstance(repo, dict) and repo.get("full_name")
        }
        result.append(
            _RegisteredGitHubIntegration(
                id=integration.id,
                github=github,
                owner=_integration_owner(github),
                repositories=repositories - seen,
            )
        )
        seen.update(repositories)
    return result


def _reports(team_id: int, user_id: int) -> dict[str, PRReport]:
    monitoring_enabled = team_report_monitoring_enabled(team_id)
    return {
        key: PRReport(
            id=str(report_id),
            status=effective_report_status(status, team_id=team_id, monitoring_enabled=monitoring_enabled),
        )
        for key, report_id, status in SignalReport.objects.filter(
            team_id=team_id, created_by_id=user_id, scout_idempotency_key__startswith=f"monitor-pr:{user_id}:"
        )
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("scout_idempotency_key", "id", "status")
        if key is not None
    }


def _fetch_search_page(
    *, team_id: int, integration: _RegisteredGitHubIntegration, login: str, cutoff: str, page: int
) -> dict[str, Any]:
    assert integration.owner is not None
    query = f"is:pr author:{login} user:{integration.owner} created:<={cutoff}"
    key = f"signals:pr-browser:{team_id}:{integration.id}:{hashlib.sha256(query.encode()).hexdigest()}:{page}"
    data = cache.get(key)
    if data is not None:
        return data
    response = integration.github.api_request(
        "GET",
        "/search/issues",
        params={"q": query, "sort": "created", "order": "desc", "per_page": 100, "page": page},
    )
    if not response.ok:
        raise GitHubIntegrationError("Could not list pull requests from GitHub.")
    try:
        data = response.json()
    except ValueError as error:
        raise GitHubIntegrationError("Could not list pull requests from GitHub.") from error
    cache.set(key, data, timeout=60)
    return data


def _browser_pr_from_search_item(
    *,
    item: dict[str, Any],
    integration: _RegisteredGitHubIntegration,
    user_id: int,
    monitoring: str,
    reports: dict[str, PRReport],
) -> BrowserPR | None:
    try:
        repository, number = pr_identity(item["html_url"])
    except (KeyError, TypeError, InvalidPullRequest):
        return None
    if repository not in integration.repositories:
        return None
    report = reports.get(monitor_key(user_id, item["html_url"]))
    if (monitoring == "monitored" and report is None) or (monitoring == "unmonitored" and report is not None):
        return None
    return BrowserPR(
        url=f"https://github.com/{repository}/pull/{number}",
        repository=repository,
        number=number,
        title=item["title"],
        state="merged" if item.get("pull_request", {}).get("merged_at") else item["state"],
        draft=bool(item.get("draft")),
        author=item["user"]["login"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        report=report,
    )


@frozen
class _CursorState:
    signer: signing.TimestampSigner = field(repr=False)
    offsets: dict[str, int]
    cutoff: str


def _load_cursor_state(*, cursor: str, binding: list[Any]) -> _CursorState:
    keys = settings.SIGNALS_PR_BROWSER_CURSOR_SIGNING_KEYS
    if not keys:
        raise InvalidPullRequest("Pull request pagination is not configured. Contact support.")
    signer = signing.TimestampSigner(key=keys[0], fallback_keys=list(keys[1:]), salt=CURSOR_SALT)
    if not cursor:
        return _CursorState(signer=signer, offsets={}, cutoff=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        saved = signer.unsign_object(cursor, max_age=86400)
        if saved["binding"] != binding:
            raise ValueError
        return _CursorState(signer=signer, offsets=dict(saved["offsets"]), cutoff=saved["cutoff"])
    except (signing.BadSignature, KeyError, TypeError, ValueError) as error:
        raise InvalidPullRequest("This PR list has expired. Refresh to load it again.") from error


def list_authored_prs(*, team: Team, user: User, monitoring: str, cursor: str = "") -> PRPage:
    team = team.parent_team or team
    _authorize(team, user)
    if not settings.SIGNALS_PR_BROWSER_CURSOR_SIGNING_KEYS:
        raise InvalidPullRequest("Pull request pagination is not configured. Contact support.")
    login = user.get_github_login(include_team_fallback=False)
    integrations = _integrations(team.id)
    if not login or not GITHUB_LOGIN_PATTERN.fullmatch(login):
        return PRPage(
            results=[], next_cursor=None, github_login=None, has_integration=bool(integrations), incomplete=False
        )
    searchable = [item for item in integrations if item.repositories and item.owner]
    binding = [team.id, user.id, login, monitoring, [item.id for item in searchable]]
    cursor_state = _load_cursor_state(cursor=cursor, binding=binding)
    offsets = cursor_state.offsets

    pages: dict[tuple[int, int], dict[str, Any]] = {}
    incomplete = False

    def peek(integration: _RegisteredGitHubIntegration) -> dict[str, Any] | None:
        nonlocal incomplete
        offset = offsets.get(str(integration.id), 0)
        if offset >= 1000:
            incomplete = True
            return None
        page = offset // 100 + 1
        page_key = (integration.id, page)
        if page_key not in pages:
            pages[page_key] = _fetch_search_page(
                team_id=team.id, integration=integration, login=login, cutoff=cursor_state.cutoff, page=page
            )
        data = pages[page_key]
        incomplete |= bool(data.get("incomplete_results")) or data.get("total_count", 0) > 1000
        items = data.get("items", [])
        return items[offset % 100] if offset % 100 < len(items) else None

    reports = _reports(team.id, user.id)
    results: list[BrowserPR] = []
    heads = {integration.id: peek(integration) for integration in searchable}
    by_id = {integration.id: integration for integration in searchable}
    scanned = 0
    while any(heads.values()) and len(results) < PAGE_SIZE and scanned < SCAN_LIMIT:
        integration_id = max(heads, key=lambda key: (heads[key] or {}).get("created_at", ""))
        item = heads[integration_id]
        assert item is not None
        integration = by_id[integration_id]
        offsets[str(integration_id)] = offsets.get(str(integration_id), 0) + 1
        scanned += 1
        heads[integration_id] = peek(integration)
        if pr := _browser_pr_from_search_item(
            item=item, integration=integration, user_id=user.id, monitoring=monitoring, reports=reports
        ):
            results.append(pr)
    next_cursor = (
        cursor_state.signer.sign_object(
            {"binding": binding, "offsets": offsets, "cutoff": cursor_state.cutoff}, compress=True
        )
        if any(heads.values())
        else None
    )
    return PRPage(
        results=results,
        next_cursor=next_cursor,
        github_login=login,
        has_integration=bool(integrations),
        incomplete=incomplete,
    )


def get_pr_overview(*, team: Team, user: User, pr_url: str) -> PROverview:
    team = team.parent_team or team
    _authorize(team, user)
    repository, number = pr_identity(pr_url)
    github = next(
        (integration.github for integration in _integrations(team.id) if repository in integration.repositories), None
    )
    if github is None:
        raise InvalidPullRequest("Connect this repository through the project's GitHub integration.")
    data = github.get_pull_request(repository, number)
    if not data.get("success"):
        status_code = data.get("status_code")
        if status_code is None or status_code >= 500:
            raise GitHubIntegrationError(
                "GitHub is temporarily unavailable. Try again shortly.", status_code=status_code
            )
        raise InvalidPullRequest("Could not read this pull request through the project's GitHub integration.")
    try:
        checks = github.get_pull_request_checks(repository, number)
    except GitHubIntegrationError:
        checks = {"success": False}
    return PROverview(
        pull_request=BrowserPR(
            url=f"https://github.com/{repository}/pull/{number}",
            repository=repository,
            number=number,
            title=data["title"],
            state="merged" if data["merged"] else data["state"],
            draft=bool(data.get("draft")),
            author=data.get("author") or "",
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            report=_reports(team.id, user.id).get(monitor_key(user.id, pr_url)),
        ),
        body=data.get("body") or "",
        head_branch=data.get("head_branch") or "",
        base_branch=data.get("base_branch") or "",
        additions=data.get("additions", 0),
        deletions=data.get("deletions", 0),
        changed_files=data.get("changed_files", 0),
        checks=[
            PRCheck(
                name=check["name"], status=check["status"], conclusion=check.get("conclusion"), url=check.get("url")
            )
            for check in checks.get("checks", [])
        ],
        checks_available=bool(checks.get("success")),
        has_conflicts=bool(checks.get("has_conflict")),
    )
