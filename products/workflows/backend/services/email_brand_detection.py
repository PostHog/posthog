import math
import time
from urllib.parse import quote

from django.core.cache import cache

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration

from products.workflows.backend.services.brand_detection.detector import BrandDetection, TreeEntry, detect_brand

GITHUB_SOURCE = "workflows_brand"
REQUEST_TIMEOUT_SECONDS = 5
DETECTION_BUDGET_SECONDS = 15
CACHE_TTL_SECONDS = 10 * 60
CACHE_VERSION = 1
UNREADABLE_STATUS_CODES = (403, 404)
TOKEN_REJECTED_STATUS_CODE = 401
EMPTY_REPOSITORY_STATUS_CODE = 409


class GitHubBusy(Exception):
    pass


class GitHubDisconnected(Exception):
    pass


class RepositoryUnreadable(Exception):
    pass


def detect_repository_brand(
    *, team_id: int, integration: Integration, repository: str, app_root: str | None, refresh: bool
) -> BrandDetection:
    """Propose an Email brand from a GitHub repository, reusing a detection made in the last ten minutes.

    Raises ``GitHubBusy`` when the egress limiter or GitHub refuses a call for now, ``GitHubDisconnected``
    when the installation is gone or its token is rejected, ``RepositoryUnreadable`` when the integration
    cannot read the repository, and ``UnknownAppRoot`` for an app root outside it.
    """
    key = _cache_key(team_id=team_id, integration_id=integration.id, repository=repository, app_root=app_root)
    if not refresh and (cached := cache.get(key)) is not None:
        return cached
    reader = _RepositoryReader(integration, repository)
    detection = _detect(reader, repository, app_root)
    if not reader.ran_out_of_time:
        cache.set(key, detection, CACHE_TTL_SECONDS)
    return detection


def _detect(reader: "_RepositoryReader", repository: str, app_root: str | None) -> BrandDetection:
    try:
        tree = reader.tree()
        return detect_brand(repository_name=repository, tree=tree, read_text=reader.read_text, app_root=app_root)
    except GitHubIntegrationError as error:
        if reader.installation_unavailable():
            raise GitHubDisconnected() from error
        raise GitHubBusy() from error
    except (GitHubEgressBudgetExhausted, GitHubRateLimitError) as error:
        raise GitHubBusy() from error


class _RepositoryReader:
    """Reads one repository on the interactive lane, within the per-call timeout and the overall budget."""

    def __init__(self, integration: Integration, repository: str) -> None:
        self._github = GitHubIntegration(integration, source=GITHUB_SOURCE, priority=Priority.NORMAL)
        self._repository = repository
        self._deadline = time.monotonic() + DETECTION_BUDGET_SECONDS
        self._blob_shas: dict[str, str] = {}
        self.ran_out_of_time = False

    def tree(self) -> list[TreeEntry]:
        default_branch = self._get_json(f"/repos/{self._repository}", endpoint="/repos/{owner}/{repo}")[
            "default_branch"
        ]
        tree = self._get_json(
            f"/repos/{self._repository}/git/trees/{quote(default_branch, safe='/')}",
            endpoint="/repos/{owner}/{repo}/git/trees/{tree_sha}",
            params={"recursive": 1},
            empty_on_status=EMPTY_REPOSITORY_STATUS_CODE,
        )
        blobs = [entry for entry in tree.get("tree", []) if isinstance(entry, dict) and entry.get("type") == "blob"]
        self._blob_shas = {entry["path"]: entry["sha"] for entry in blobs}
        return [TreeEntry(path=entry["path"], size=int(entry.get("size") or 0)) for entry in blobs]

    def installation_unavailable(self) -> bool:
        return self._github.installation_unavailable()

    def read_text(self, path: str) -> str | None:
        if time.monotonic() > self._deadline:
            self.ran_out_of_time = True
            return None
        response = self._github.api_request(
            "GET",
            f"/repos/{self._repository}/git/blobs/{self._blob_shas[path]}",
            endpoint="/repos/{owner}/{repo}/git/blobs/{file_sha}",
            headers={"Accept": "application/vnd.github.raw+json"},
            timeout=self._call_timeout(),
            retry_transient=False,
        )
        self._raise_for_status(response.status_code)
        return response.content.decode("utf-8", errors="replace")

    def _get_json(
        self,
        path: str,
        *,
        endpoint: str,
        params: dict[str, str | int] | None = None,
        empty_on_status: int | None = None,
    ) -> dict:
        response = self._github.api_request(
            "GET", path, endpoint=endpoint, params=params, timeout=self._call_timeout(), retry_transient=False
        )
        if response.status_code == empty_on_status:
            return {}
        self._raise_for_status(response.status_code)
        return response.json()

    def _call_timeout(self) -> int:
        remaining = math.ceil(self._deadline - time.monotonic())
        return max(1, min(REQUEST_TIMEOUT_SECONDS, remaining))

    def _raise_for_status(self, status_code: int) -> None:
        if status_code == TOKEN_REJECTED_STATUS_CODE:
            raise GitHubDisconnected()
        if status_code in UNREADABLE_STATUS_CODES:
            raise RepositoryUnreadable()
        if status_code != 200:
            raise GitHubBusy()


def _cache_key(*, team_id: int, integration_id: int, repository: str, app_root: str | None) -> str:
    root = "auto" if app_root is None else f"path:{app_root.strip().strip('/')}"
    return (
        f"workflows_email_brand_detection:v{CACHE_VERSION}:team:{team_id}:integration:{integration_id}"
        f":repo:{repository.lower()}:root:{root}"
    )
