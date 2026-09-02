import re
import json
import datetime as dt
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.settings import (
    AWS_ORGANIZATIONS_ENDPOINTS,
    CONTENT_TYPE,
    CREDENTIAL_ERROR_CODES,
    MAX_RESULTS,
    MAX_RETRY_ATTEMPTS,
    ORGANIZATIONS_API_VERSION,
    ORGANIZATIONS_ENDPOINT_URL,
    POLICY_FILTERS,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_INITIAL_WAIT_SECONDS,
    RETRY_MAX_WAIT_SECONDS,
    RETRYABLE_ERROR_CODES,
    SIGNING_NAME,
    SIGNING_REGION,
    TARGET_PREFIXES,
    AwsOrganizationsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Organizations is a POST-only JSON RPC and the tracked session's default policy only retries
# idempotent verbs, so POST is opted in explicitly for the transport-level statuses.
TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_IAM_ACTION_PATTERN = re.compile(r"organizations:[A-Za-z0-9]+")


class AwsOrganizationsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"AWS Organizations request failed: {code} - {message}")
        self.code = code
        self.message = message


class AwsOrganizationsRetryableError(AwsOrganizationsError):
    pass


@dataclasses.dataclass(frozen=True)
class AwsOrganizationsResumeConfig:
    """Where a previous attempt stopped: the page token, and which sub-walk it belonged to.

    `work_key` is the `ListPolicies` filter for the policies table and `None` everywhere else.
    """

    next_token: Optional[str] = None
    work_key: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next_token: Optional[str]


def target_prefix(api_version: Optional[str]) -> str:
    version = api_version or ORGANIZATIONS_API_VERSION
    prefix = TARGET_PREFIXES.get(version)
    if prefix is None:
        raise ValueError(f"Unsupported AWS Organizations API version: {version!r}")
    return prefix


def result_key(endpoint_config: AwsOrganizationsEndpointConfig) -> str:
    if endpoint_config.result_key is None:
        raise ValueError(f"{endpoint_config.name} is not a paginated list endpoint")
    return endpoint_config.result_key


def _snake(name: str) -> str:
    """`MasterAccountId` -> `master_account_id`, `FeatureSet` -> `feature_set`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _parse_timestamp(value: Any) -> Any:
    """Organizations serializes timestamps as epoch seconds; leave anything else untouched."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(value, tz=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)
    return value


def _flatten(prefix: str, obj: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in obj.items():
        column = f"{prefix}_{_snake(key)}" if prefix else _snake(key)
        if isinstance(value, dict):
            flattened.update(_flatten(column, value))
        else:
            flattened[column] = value
    return flattened


def normalize_row(endpoint_config: AwsOrganizationsEndpointConfig, obj: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested structures into snake_case columns and parse epoch timestamps."""
    kept = {key: value for key, value in obj.items() if key not in endpoint_config.drop_keys}
    row = _flatten("", kept)
    for column in endpoint_config.timestamp_columns:
        if column in row:
            row[column] = _parse_timestamp(row[column])
    return row


def _error_code(response: requests.Response, body: dict[str, Any]) -> str:
    header = response.headers.get("x-amzn-ErrorType") or ""
    if header:
        return header.split(":")[0].split("#")[-1]
    # AWS returns `{"__type": "com.amazonaws.organizations#AccessDeniedException"}`; some
    # fronting errors use a bare `code` instead.
    raw = body.get("__type") or body.get("code") or f"HTTP {response.status_code}"
    return str(raw).rsplit("#", 1)[-1]


def _error_message(response: requests.Response, body: dict[str, Any]) -> str:
    for key in ("message", "Message", "errorMessage", "Reason"):
        value = body.get(key)
        if value:
            return str(value)[:500]
    return response.text[:500]


def error_for_response(response: requests.Response) -> AwsOrganizationsError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    code = _error_code(response, body)
    message = _error_message(response, body)
    if code in RETRYABLE_ERROR_CODES or response.status_code >= 500:
        return AwsOrganizationsRetryableError(code, message)
    return AwsOrganizationsError(code, message)


class AwsOrganizationsClient:
    """SigV4-signed JSON client for the AWS Organizations API.

    Every operation is a POST to the single global endpoint, discriminated by `X-Amz-Target`,
    so there is no REST surface the declarative framework could drive. Signing rides botocore
    (already a repo dependency) but the request goes out over the tracked session so it stays
    in our HTTP logs and metrics.
    """

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        session_token: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self.target_prefix = target_prefix(api_version)
        self._credentials = Credentials(access_key_id, secret_access_key, session_token or None)
        self._signer = SigV4Auth(self._credentials, SIGNING_NAME, SIGNING_REGION)
        self._session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(value for value in (secret_access_key, session_token) if value),
        )

    def _signed_headers(self, operation: str, body: bytes) -> dict[str, str]:
        request = AWSRequest(
            method="POST",
            url=ORGANIZATIONS_ENDPOINT_URL,
            data=body,
            headers={
                "Content-Type": CONTENT_TYPE,
                "X-Amz-Target": f"{self.target_prefix}.{operation}",
            },
        )
        self._signer.add_auth(request)
        return dict(request.headers)

    def send(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        response = self._session.post(
            ORGANIZATIONS_ENDPOINT_URL,
            data=body,
            headers=self._signed_headers(operation, body),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise error_for_response(response)
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {}

    # Throttling arrives as HTTP 400 with the code in the body, which the tracked transport's
    # status-code retries can't see, so there is no compounding here.
    @retry(
        retry=retry_if_exception_type((AwsOrganizationsRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=RETRY_INITIAL_WAIT_SECONDS, max=RETRY_MAX_WAIT_SECONDS),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.send(operation, payload)


def _is_invalid_token(error: AwsOrganizationsError) -> bool:
    return "INVALID_PAGINATION_TOKEN" in error.message.upper() or error.code == "InvalidPaginationTokenException"


def is_policy_type_unavailable(error: AwsOrganizationsError) -> bool:
    """True when a policy type simply isn't offered here, rather than being denied to us."""
    if error.code == "UnsupportedAPIEndpointException":
        return True
    # Partitions that don't offer a policy type reject its enum value outright instead of
    # returning an empty list.
    return error.code == "InvalidInputException" and "INVALID_ENUM" in error.message.upper()


def iter_pages(
    client: AwsOrganizationsClient,
    operation: str,
    payload: dict[str, Any],
    items_key: str,
    logger: FilteringBoundLogger,
    start_token: Optional[str] = None,
) -> Iterator[Page]:
    next_token = start_token
    resumed = start_token is not None

    while True:
        request_payload = dict(payload)
        if next_token:
            request_payload["NextToken"] = next_token

        try:
            body = client.request(operation, request_payload)
        except AwsOrganizationsError as error:
            # A token saved by a previous attempt can expire; restart the walk instead of
            # failing the job. Merge on the primary key absorbs the re-read rows.
            if resumed and _is_invalid_token(error):
                logger.debug(f"Saved page token no longer valid; restarting. operation={operation}")
                next_token = None
                resumed = False
                continue
            raise
        resumed = False

        items = [item for item in body.get(items_key) or [] if isinstance(item, dict)]
        next_token = body.get("NextToken") or None
        yield Page(items=items, next_token=next_token)
        # AWS documents that these operations can return an empty page while more results are
        # still available, so only a null token ends the walk.
        if not next_token:
            return


def iter_items(
    client: AwsOrganizationsClient,
    operation: str,
    payload: dict[str, Any],
    items_key: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    for page in iter_pages(client, operation, payload, items_key, logger):
        yield from page.items


def _checkpointed_rows(
    pages: Iterator[Page],
    rows_for_items: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    resumable_source_manager: ResumableSourceManager[AwsOrganizationsResumeConfig],
    work_key: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    for page in pages:
        rows = rows_for_items(page.items)
        if rows:
            yield rows
        # Saved after yielding: a crash re-yields the last page, which merges away on the
        # primary key, rather than skipping it.
        resumable_source_manager.save_state(AwsOrganizationsResumeConfig(next_token=page.next_token, work_key=work_key))


def _single_object_rows(
    client: AwsOrganizationsClient, endpoint_config: AwsOrganizationsEndpointConfig
) -> Iterator[list[dict[str, Any]]]:
    body = client.request(endpoint_config.operation, {})
    obj = body.get(endpoint_config.object_key or "") or {}
    if isinstance(obj, dict) and obj:
        yield [normalize_row(endpoint_config, obj)]


def _list_rows(
    client: AwsOrganizationsClient,
    endpoint_config: AwsOrganizationsEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AwsOrganizationsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_token = resume.next_token if resume is not None else None
    if start_token:
        logger.debug(f"Resuming from a saved page token. endpoint={endpoint_config.name}")

    payload: dict[str, Any] = {}
    if endpoint_config.page_size is not None:
        payload["MaxResults"] = endpoint_config.page_size

    pages = iter_pages(
        client,
        endpoint_config.operation,
        payload,
        result_key(endpoint_config),
        logger,
        start_token=start_token,
    )
    yield from _checkpointed_rows(
        pages,
        lambda items: [normalize_row(endpoint_config, item) for item in items],
        resumable_source_manager,
    )


def _policy_rows(
    client: AwsOrganizationsClient,
    endpoint_config: AwsOrganizationsEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AwsOrganizationsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """One walk per policy type, since `Filter` is required and takes a single type."""
    filters = list(POLICY_FILTERS)
    start_token: Optional[str] = None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resumed_filter = resume.work_key if resume is not None else None
    if resumed_filter is not None and resumed_filter in filters:
        index = filters.index(resumed_filter)
        if resume is not None and resume.next_token:
            filters = filters[index:]
            start_token = resume.next_token
        else:
            # The saved walk finished, so pick up at the next policy type.
            filters = filters[index + 1 :]
        logger.debug(f"Resuming policies from a saved policy type. policy_type={resumed_filter}")

    for policy_filter in filters:
        pages = iter_pages(
            client,
            endpoint_config.operation,
            {"Filter": policy_filter, "MaxResults": endpoint_config.page_size},
            result_key(endpoint_config),
            logger,
            start_token=start_token,
        )
        try:
            yield from _checkpointed_rows(
                pages,
                lambda items: [normalize_row(endpoint_config, item) for item in items],
                resumable_source_manager,
                work_key=policy_filter,
            )
        except AwsOrganizationsError as error:
            if is_policy_type_unavailable(error):
                logger.debug(f"Skipping unavailable policy type. policy_type={policy_filter}")
                start_token = None
                continue
            raise
        start_token = None


# Named fields instead of a 2/3-tuple return: semgrep's tuple-return-prefer-dataclass
# devex rule flags tuple[$T, $T] and tuple[$A, $B, $C, ...] return annotations because
# same-typed or 3+ positional elements are easy to swap or misread at the call site.
@dataclasses.dataclass(frozen=True)
class OrganizationalUnitEntry:
    """An OU paired with the parent it was found under."""

    item: dict[str, Any]
    parent_id: str
    parent_type: str


@dataclasses.dataclass(frozen=True)
class TaggableResource:
    """A resource that can carry tags, identified by id and resource type."""

    resource_id: str
    resource_type: str


def _iter_organizational_units(
    client: AwsOrganizationsClient, logger: FilteringBoundLogger
) -> Iterator[OrganizationalUnitEntry]:
    """Every OU in the organization, paired with the parent it was found under.

    Organizations only lists OUs one parent at a time, so the hierarchy is walked breadth-first
    from the roots.
    """
    pending: list[tuple[str, str]] = []
    for root in iter_items(client, "ListRoots", {"MaxResults": MAX_RESULTS}, "Roots", logger):
        root_id = root.get("Id")
        if isinstance(root_id, str) and root_id:
            pending.append((root_id, "ROOT"))

    seen: set[str] = set()
    while pending:
        parent_id, parent_type = pending.pop(0)
        for item in iter_items(
            client,
            "ListOrganizationalUnitsForParent",
            {"ParentId": parent_id, "MaxResults": MAX_RESULTS},
            "OrganizationalUnits",
            logger,
        ):
            yield OrganizationalUnitEntry(item=item, parent_id=parent_id, parent_type=parent_type)
            unit_id = item.get("Id")
            # `seen` guards against an id coming back twice, which would otherwise walk the
            # same subtree forever.
            if isinstance(unit_id, str) and unit_id and unit_id not in seen:
                seen.add(unit_id)
                pending.append((unit_id, "ORGANIZATIONAL_UNIT"))


def _organizational_unit_rows(
    client: AwsOrganizationsClient,
    endpoint_config: AwsOrganizationsEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for entry in _iter_organizational_units(client, logger):
        row = normalize_row(endpoint_config, entry.item)
        row["parent_id"] = entry.parent_id
        row["parent_type"] = entry.parent_type
        rows.append(row)
        if len(rows) >= MAX_RESULTS:
            yield rows
            rows = []
    if rows:
        yield rows


def _iter_taggable_resources(
    client: AwsOrganizationsClient, logger: FilteringBoundLogger
) -> Iterator[TaggableResource]:
    """Every resource in the organization that can carry tags."""

    def candidates() -> Iterator[tuple[Any, str]]:
        for account in iter_items(client, "ListAccounts", {"MaxResults": MAX_RESULTS}, "Accounts", logger):
            yield account.get("Id"), "ACCOUNT"

        for root in iter_items(client, "ListRoots", {"MaxResults": MAX_RESULTS}, "Roots", logger):
            yield root.get("Id"), "ROOT"

        for entry in _iter_organizational_units(client, logger):
            yield entry.item.get("Id"), "ORGANIZATIONAL_UNIT"

        for policy_filter in POLICY_FILTERS:
            try:
                for policy in iter_items(
                    client, "ListPolicies", {"Filter": policy_filter, "MaxResults": MAX_RESULTS}, "Policies", logger
                ):
                    yield policy.get("Id"), "POLICY"
            except AwsOrganizationsError as error:
                if is_policy_type_unavailable(error):
                    logger.debug(f"Skipping unavailable policy type. policy_type={policy_filter}")
                    continue
                raise

    seen: set[str] = set()
    for resource_id, resource_type in candidates():
        if isinstance(resource_id, str) and resource_id and resource_id not in seen:
            seen.add(resource_id)
            yield TaggableResource(resource_id=resource_id, resource_type=resource_type)


def _resource_tag_rows(
    client: AwsOrganizationsClient,
    endpoint_config: AwsOrganizationsEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    for resource in _iter_taggable_resources(client, logger):
        resource_id, resource_type = resource.resource_id, resource.resource_type
        rows: list[dict[str, Any]] = []
        try:
            for tag in iter_items(
                client, endpoint_config.operation, {"ResourceId": resource_id}, result_key(endpoint_config), logger
            ):
                row = normalize_row(endpoint_config, tag)
                row["resource_id"] = resource_id
                row["resource_type"] = resource_type
                rows.append(row)
        except AwsOrganizationsError as error:
            if error.code == "TargetNotFoundException":
                logger.debug(f"Skipping resource deleted mid-sync. resource_id={resource_id}")
                continue
            raise
        if rows:
            yield rows


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoint: str,
    api_version: Optional[str],
    resumable_source_manager: ResumableSourceManager[AwsOrganizationsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_ORGANIZATIONS_ENDPOINTS[endpoint]
    client = AwsOrganizationsClient(
        aws_access_key_id, aws_secret_access_key, aws_session_token, api_version=api_version
    )

    if endpoint_config.object_key is not None:
        yield from _single_object_rows(client, endpoint_config)
        return

    if endpoint == "organizational_units":
        # The parents are discovered as the walk runs and AWS documents no ordering, so a
        # partial walk can't be skipped past safely. These restart instead of resuming.
        yield from _organizational_unit_rows(client, endpoint_config, logger)
        return

    if endpoint == "resource_tags":
        yield from _resource_tag_rows(client, endpoint_config, logger)
        return

    if endpoint == "policies":
        yield from _policy_rows(client, endpoint_config, resumable_source_manager, logger)
    else:
        yield from _list_rows(client, endpoint_config, resumable_source_manager, logger)

    resumable_source_manager.clear_state()


def _permission_reason(error: AwsOrganizationsError) -> Optional[str]:
    if error.code == "AccessDeniedException":
        match = _IAM_ACTION_PATTERN.search(error.message)
        missing = f"Missing IAM permission {match.group(0)}." if match else "These credentials can't read this table."
        return f"{missing} Organizations list operations only work from the management account or a delegated administrator."
    if error.code == "AWSOrganizationsNotInUseException":
        return "This AWS account isn't a member of an organization."
    if error.code in CREDENTIAL_ERROR_CODES:
        return "AWS rejected the access key. Please check the access key ID and secret access key."
    return None


def endpoint_permission_reason(client: AwsOrganizationsClient, endpoint: str) -> Optional[str]:
    """Probe the calls a sync of this endpoint issues. `None` when reachable.

    Only a real denial counts as unreachable: throttles, 5xx and network errors leave the
    endpoint reported as reachable, so a blip can't hide tables from the schema picker.
    """
    endpoint_config = AWS_ORGANIZATIONS_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        return None

    try:
        if endpoint_config.object_key is not None:
            client.request(endpoint_config.operation, {})
        elif endpoint == "organizational_units":
            roots = client.request("ListRoots", {"MaxResults": 1})
            for root in roots.get("Roots") or []:
                root_id = root.get("Id") if isinstance(root, dict) else None
                if isinstance(root_id, str):
                    client.request("ListOrganizationalUnitsForParent", {"ParentId": root_id, "MaxResults": 1})
                break
        elif endpoint == "policies":
            client.request("ListPolicies", {"Filter": POLICY_FILTERS[0], "MaxResults": 1})
        elif endpoint == "resource_tags":
            accounts = client.request("ListAccounts", {"MaxResults": 1})
            for account in accounts.get("Accounts") or []:
                account_id = account.get("Id") if isinstance(account, dict) else None
                if isinstance(account_id, str):
                    client.request("ListTagsForResource", {"ResourceId": account_id})
                break
        else:
            client.request(endpoint_config.operation, {"MaxResults": 1})
    except AwsOrganizationsError as error:
        return _permission_reason(error)
    except Exception:
        return None
    return None


def probe_endpoint_permissions(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoints: list[str],
    api_version: Optional[str] = None,
) -> dict[str, str | None]:
    client = AwsOrganizationsClient(
        aws_access_key_id, aws_secret_access_key, aws_session_token, api_version=api_version
    )
    return {endpoint: endpoint_permission_reason(client, endpoint) for endpoint in endpoints}


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    schema_name: Optional[str] = None,
    api_version: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"

    client = AwsOrganizationsClient(
        aws_access_key_id, aws_secret_access_key, aws_session_token, api_version=api_version
    )

    if schema_name is not None and schema_name in AWS_ORGANIZATIONS_ENDPOINTS:
        reason = endpoint_permission_reason(client, schema_name)
        return reason is None, reason

    try:
        # DescribeOrganization is the one operation any account in the organization can call, so
        # it proves the key is genuine without requiring management-account access.
        client.request("DescribeOrganization", {})
    except AwsOrganizationsError as error:
        if error.code == "AccessDeniedException":
            # A denied DescribeOrganization still proves the key is genuine; per-table access is
            # reported in the schema picker instead of blocking source creation.
            return True, None
        if error.code == "AWSOrganizationsNotInUseException":
            return (
                False,
                "This AWS account isn't a member of an organization. Connect a key from an account in an AWS organization.",
            )
        return False, str(error)
    except Exception:
        return False, "Could not reach the AWS Organizations API. Please try again."

    return True, None


def aws_organizations_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoint: str,
    api_version: Optional[str],
    resumable_source_manager: ResumableSourceManager[AwsOrganizationsResumeConfig],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AWS_ORGANIZATIONS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            endpoint=endpoint,
            api_version=api_version,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        # AWS documents no ordering for these list APIs, and none of them takes a time filter,
        # so every table is a full refresh with nothing for a watermark to track.
        sort_mode="desc",
    )
