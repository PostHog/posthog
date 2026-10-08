import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.settings import (
    DRIVE_ID_COLUMN,
    GRAPH_BASE_URL,
    LIST_ID_COLUMN,
    LOGIN_BASE_URL,
    MAX_PAGES_PER_COLLECTION,
    SHAREPOINT_ENDPOINTS,
    SITE_ID_COLUMN,
    TOKEN_SCOPE,
    SharePointEndpoint,
)

REQUEST_TIMEOUT_SECONDS = 120
VALIDATE_TIMEOUT_SECONDS = 30

_module_logger: FilteringBoundLogger = structlog.get_logger(__name__)

SITES_DENIED_ERROR = (
    "Microsoft Graph denied access to SharePoint. Grant the app the Sites.Read.All application permission "
    "with admin consent, or list the site URLs it was granted through Sites.Selected."
)
INVALID_SITE_URL_ERROR = "Enter each SharePoint site as a full URL"


class SharePointSiteURLError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class SharePointResumeConfig:
    """Position of the walk: the site, the list or drive inside it, and the next page.

    `next_url` is None when the walk restarts at the start of `parent_id` (or of `site_id` for
    tables that have no parent below the site).
    """

    site_id: Optional[str] = None
    parent_id: Optional[str] = None
    next_url: Optional[str] = None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalize(row: dict[str, Any], endpoint: SharePointEndpoint, **parent_columns: str) -> dict[str, Any]:
    row.update(parent_columns)
    partition_key = SHAREPOINT_ENDPOINTS[endpoint].partition_key
    if partition_key is not None:
        # Type the partition column as a real datetime so it buckets by month.
        parsed = _parse_datetime(row.get(partition_key))
        if parsed is not None:
            row[partition_key] = parsed
    return row


def parse_site_urls(raw: Optional[str]) -> list[str]:
    """Turn the user's site URLs into Graph site paths, e.g. `/sites/contoso.sharepoint.com:/sites/hr:`.

    An empty value means every site the app can read.
    """
    if not raw:
        return []

    paths: list[str] = []
    for entry in raw.replace(",", "\n").splitlines():
        url = entry.strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SharePointSiteURLError(
                f"{INVALID_SITE_URL_ERROR}, for example https://contoso.sharepoint.com/sites/marketing. Got: {url}"
            )
        hostname = quote(parsed.hostname, safe=".-")
        relative_path = parsed.path.strip("/")
        if relative_path:
            paths.append(f"/sites/{hostname}:/{quote(relative_path, safe='/')}:")
        else:
            paths.append(f"/sites/{hostname}")
    return paths


def _is_personal_site(site: dict[str, Any]) -> bool:
    # `getAllSites` also returns every user's OneDrive. Those are personal files, not SharePoint.
    if site.get("isPersonalSite"):
        return True
    host = urlparse(site.get("webUrl") or "").hostname or ""
    return host.endswith("-my.sharepoint.com")


class SharePointClient:
    """Minimal Microsoft Graph client: mints an Entra ID app token and issues GETs.

    Access tokens last about an hour, so a long sync re-mints on the first 401 rather than
    failing the job.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._tenant_id = tenant_id.strip()
        self._client_id = client_id.strip()
        self._client_secret = client_secret
        self._logger = logger
        self._session = make_tracked_session(redact_values=(client_secret,))
        self._token: Optional[str] = None

    @property
    def token_url(self) -> str:
        return f"{LOGIN_BASE_URL}/{quote(self._tenant_id, safe='')}/oauth2/v2.0/token"

    def mint_token(self) -> str:
        response = self._session.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": TOKEN_SCOPE,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Entra ID did not return an access token for the app registration")
        self._token = token
        return token

    def get(
        self, path_or_url: str, params: Optional[dict[str, str]] = None, timeout: int = REQUEST_TIMEOUT_SECONDS
    ) -> Any:
        if path_or_url.startswith("/"):
            url = f"{GRAPH_BASE_URL}{path_or_url}"
        elif path_or_url.startswith(f"{GRAPH_BASE_URL}/"):
            url = path_or_url
        else:
            # `@odata.nextLink` comes from the response body. Never send the token anywhere but Graph.
            raise ValueError(f"Refusing to follow a non-Graph URL: {path_or_url}")

        if self._token is None:
            self.mint_token()

        def _do() -> requests.Response:
            return self._session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=timeout,
            )

        response = _do()
        if response.status_code == 401:
            self.mint_token()
            response = _do()

        if not response.ok:
            self._logger.error(
                f"Microsoft Graph error: status={response.status_code}, body={response.text[:500]}, url={url}"
            )
            response.raise_for_status()

        return response.json()


def _status(error: requests.HTTPError) -> Optional[int]:
    return error.response.status_code if error.response is not None else None


def _walk_collection(
    client: SharePointClient,
    path: str,
    params: Optional[dict[str, str]],
    start_url: Optional[str],
    stage_next: Callable[[str], None],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Follow `@odata.nextLink` through one Graph collection, staging each next page before its yield."""
    url = start_url or path
    # The next link already carries every query option, so params only go on the first request.
    request_params = None if start_url else params

    for _ in range(MAX_PAGES_PER_COLLECTION):
        body = client.get(url, params=request_params)
        rows = body.get("value") or []
        next_url = body.get("@odata.nextLink")
        if next_url:
            stage_next(next_url)
        if rows:
            yield rows
        if not next_url:
            return
        url = next_url
        request_params = None

    logger.warning(f"SharePoint: hit the {MAX_PAGES_PER_COLLECTION}-page cap for {path}, later rows are skipped")


def _walk_child_collection(
    client: SharePointClient,
    path: str,
    params: Optional[dict[str, str]],
    start_url: Optional[str],
    stage_next: Callable[[str], None],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Like `_walk_collection`, but a 404 skips the collection: sites and lists can go away mid-sync."""
    try:
        yield from _walk_collection(client, path, params, start_url, stage_next, logger)
    except requests.HTTPError as e:
        if _status(e) != 404:
            raise
        logger.warning(f"SharePoint: {path} no longer exists, skipping it")


def _list_sites(client: SharePointClient, site_paths: list[str], logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    if site_paths:
        return [site for path in site_paths if not _is_personal_site(site := client.get(path))]

    sites: list[dict[str, Any]] = []
    for page in _walk_collection(client, "/sites/getAllSites", None, None, lambda _: None, logger):
        sites.extend(site for site in page if not _is_personal_site(site))
    return sites


def _resume_index(ids: list[str], resume_id: Optional[str]) -> Optional[int]:
    if resume_id is None:
        return None
    try:
        return ids.index(resume_id)
    except ValueError:
        return None


def _iter_sites(
    client: SharePointClient,
    site_paths: list[str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[SharePointResumeConfig],
    resume: Optional[SharePointResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    if site_paths:
        sites = _list_sites(client, site_paths, logger)
        if sites:
            yield [_normalize(site, SharePointEndpoint.SITES) for site in sites]
        return

    def stage(next_url: str) -> None:
        manager.save_state(SharePointResumeConfig(next_url=next_url))

    start_url = resume.next_url if resume is not None else None
    for page in _walk_collection(client, "/sites/getAllSites", None, start_url, stage, logger):
        rows = [_normalize(site, SharePointEndpoint.SITES) for site in page if not _is_personal_site(site)]
        if rows:
            yield rows
        else:
            manager.safe_point()


def _iter_site_children(
    client: SharePointClient,
    endpoint: SharePointEndpoint,
    collection: str,
    sites: list[dict[str, Any]],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[SharePointResumeConfig],
    resume: Optional[SharePointResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Rows of `/sites/{id}/{collection}` for every site: the `lists` and `drives` tables."""
    site_ids = [site["id"] for site in sites]
    start = _resume_index(site_ids, resume.site_id if resume is not None else None)
    start_url = resume.next_url if resume is not None and start is not None else None

    for site_id in site_ids[start or 0 :]:
        manager.save_state(SharePointResumeConfig(site_id=site_id))
        yielded = False

        def stage(next_url: str, site_id: str = site_id) -> None:
            manager.save_state(SharePointResumeConfig(site_id=site_id, next_url=next_url))

        path = f"/sites/{quote(site_id, safe=',.-')}/{collection}"
        for page in _walk_child_collection(client, path, None, start_url, stage, logger):
            yielded = True
            yield [_normalize(row, endpoint, **{SITE_ID_COLUMN: site_id}) for row in page]
        start_url = None
        if not yielded:
            manager.safe_point()


def _iter_grandchildren(
    client: SharePointClient,
    endpoint: SharePointEndpoint,
    sites: list[dict[str, Any]],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[SharePointResumeConfig],
    resume: Optional[SharePointResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Rows inside every list (`list_items`) or every drive (`drive_items`) of every site."""
    site_ids = [site["id"] for site in sites]
    site_start = _resume_index(site_ids, resume.site_id if resume is not None else None)
    resume_parent_id = resume.parent_id if resume is not None and site_start is not None else None
    resume_next_url = resume.next_url if resume is not None and site_start is not None else None

    for site_id in site_ids[site_start or 0 :]:
        quoted_site = quote(site_id, safe=",.-")
        parents = _site_parents(client, endpoint, quoted_site, logger)
        parent_ids = [parent["id"] for parent in parents]
        parent_start = _resume_index(parent_ids, resume_parent_id)
        start_url = resume_next_url if parent_start is not None else None
        resume_parent_id = None
        resume_next_url = None

        if not parent_ids:
            manager.save_state(SharePointResumeConfig(site_id=site_id))
            manager.safe_point()
            continue

        for parent_id in parent_ids[parent_start or 0 :]:
            manager.save_state(SharePointResumeConfig(site_id=site_id, parent_id=parent_id))
            yielded = False

            def stage(next_url: str, site_id: str = site_id, parent_id: str = parent_id) -> None:
                manager.save_state(SharePointResumeConfig(site_id=site_id, parent_id=parent_id, next_url=next_url))

            for page in _iter_parent_rows(client, endpoint, quoted_site, site_id, parent_id, start_url, stage, logger):
                yielded = True
                yield page
            start_url = None
            if not yielded:
                manager.safe_point()


def _site_parents(
    client: SharePointClient, endpoint: SharePointEndpoint, quoted_site: str, logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    collection = "lists" if endpoint == SharePointEndpoint.LIST_ITEMS else "drives"
    parents: list[dict[str, Any]] = []
    path = f"/sites/{quoted_site}/{collection}"
    for page in _walk_child_collection(client, path, None, None, lambda _: None, logger):
        for parent in page:
            # Hidden lists are SharePoint's own plumbing (workflow history, user info, and so on).
            if endpoint == SharePointEndpoint.LIST_ITEMS and (parent.get("list") or {}).get("hidden"):
                continue
            parents.append(parent)
    return parents


def _iter_parent_rows(
    client: SharePointClient,
    endpoint: SharePointEndpoint,
    quoted_site: str,
    site_id: str,
    parent_id: str,
    start_url: Optional[str],
    stage: Callable[[str], None],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    quoted_parent = quote(parent_id, safe="!-_")

    if endpoint == SharePointEndpoint.LIST_ITEMS:
        path = f"/sites/{quoted_site}/lists/{quoted_parent}/items"
        for page in _walk_child_collection(client, path, {"expand": "fields"}, start_url, stage, logger):
            yield [_normalize(row, endpoint, **{SITE_ID_COLUMN: site_id, LIST_ID_COLUMN: parent_id}) for row in page]
        return

    # Delta is the only enumeration Graph guarantees returns every item in a drive, and it walks
    # every folder level in one flat feed. The same item can show up more than once, so keep the
    # first copy. The seen set is per drive and is lost on resume, so a resumed drive can repeat rows.
    seen: set[str] = set()
    path = f"/drives/{quoted_parent}/root/delta"
    for page in _walk_child_collection(client, path, None, start_url, stage, logger):
        rows = []
        for row in page:
            item_id = row.get("id")
            if row.get("deleted") is not None or item_id is None or item_id in seen:
                continue
            seen.add(item_id)
            # Graph's preauthenticated download URL grants temporary access to the document contents.
            # This metadata source must not persist it in the warehouse.
            row.pop("@microsoft.graph.downloadUrl", None)
            rows.append(_normalize(row, endpoint, **{SITE_ID_COLUMN: site_id, DRIVE_ID_COLUMN: parent_id}))
        if rows:
            yield rows


def _get_rows(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    site_urls: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SharePointResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    sharepoint_endpoint = SharePointEndpoint(endpoint)
    site_paths = parse_site_urls(site_urls)
    client = SharePointClient(tenant_id, client_id, client_secret, logger)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if sharepoint_endpoint == SharePointEndpoint.SITES:
        yield from _iter_sites(client, site_paths, logger, resumable_source_manager, resume)
        return

    sites = _list_sites(client, site_paths, logger)

    if sharepoint_endpoint in (SharePointEndpoint.LISTS, SharePointEndpoint.DRIVES):
        yield from _iter_site_children(
            client, sharepoint_endpoint, sharepoint_endpoint.value, sites, logger, resumable_source_manager, resume
        )
        return

    yield from _iter_grandchildren(client, sharepoint_endpoint, sites, logger, resumable_source_manager, resume)


def sharepoint_source(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    site_urls: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SharePointResumeConfig],
) -> SourceResponse:
    config = SHAREPOINT_ENDPOINTS[endpoint]
    has_datetime_partition = config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: _get_rows(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            site_urls=site_urls,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if has_datetime_partition else None,
        partition_format="month" if has_datetime_partition else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
        sort_mode="asc",
    )


def validate_credentials(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    site_urls: Optional[str],
) -> tuple[bool, Optional[str]]:
    if not tenant_id.strip():
        return False, "Enter the directory (tenant) ID of your Entra ID tenant."

    try:
        site_paths = parse_site_urls(site_urls)
    except SharePointSiteURLError as e:
        return False, str(e)

    client = SharePointClient(tenant_id, client_id, client_secret, _module_logger)

    try:
        client.mint_token()
    except requests.HTTPError as e:
        status = _status(e)
        if status in (400, 401):
            return (
                False,
                "Entra ID rejected the app registration. Check the tenant ID, application (client) ID, "
                "and client secret.",
            )
        return False, f"Could not get a token from Entra ID (status {status})."
    except Exception as e:
        return False, f"Could not reach Entra ID ({e}). Please retry."

    probes = site_paths or ["/sites/getAllSites"]
    for path in probes:
        try:
            client.get(path, timeout=VALIDATE_TIMEOUT_SECONDS)
        except requests.HTTPError as e:
            status = _status(e)
            if status in (401, 403):
                return False, SITES_DENIED_ERROR
            if status == 404:
                return False, f"SharePoint couldn't find the site {path}. Check the site URL."
            return False, f"Microsoft Graph returned an unexpected status ({status})."
        except Exception as e:
            return False, f"Could not reach Microsoft Graph ({e}). Please retry."

    return True, None
