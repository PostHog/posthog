import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import (
    CONFIGCAT_ENDPOINTS,
    ConfigCatEndpointConfig,
)

CONFIGCAT_BASE_URL = "https://api.configcat.com"
# Cheap org-level list used to confirm the Public API credential is genuine. The credential is
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/v1/organizations"
REQUEST_TIMEOUT_SECONDS = 60
# The v2 values response is an envelope describing one config/environment pair; the per-flag rows
# sit under this key.
SETTING_FORMULAS_SELECTOR = "settingFormulas"
# The audit log is the one paged endpoint; 100 is the maximum page size it accepts.
AUDIT_LOG_PAGE_SIZE = 100
# Each list in the organization members envelope, and the role it records. A user appears in more
# than one when they hold more than one role.
ORGANIZATION_MEMBER_GROUPS = (("admins", "admin"), ("billingManagers", "billingManager"), ("members", "member"))


def _headers(username: str, password: str) -> dict[str, str]:
    # ConfigCat's Public Management API authenticates with HTTP Basic credentials (a username and
    # password pair generated on the Public API credentials page — not the SDK keys).
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _get(session: requests.Session, path: str) -> Any:
    response = session.get(f"{CONFIGCAT_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _get_list(session: requests.Session, path: str) -> list[dict[str, Any]]:
    body = _get(session, path)
    if not isinstance(body, list):
        raise ValueError(f"ConfigCat returned a non-list response body for {path}")
    if any(not isinstance(row, dict) for row in body):
        raise ValueError(f"ConfigCat returned a non-object row for {path}")
    return body


def _identifier(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value):
        raise ValueError(f"ConfigCat row has an invalid {field}")
    return str(value)


def _ids(rows: list[dict[str, Any]], field: str) -> list[str]:
    return [_identifier(row, field) for row in rows]


def _product_ids(session: requests.Session) -> list[str]:
    return _ids(_get_list(session, CONFIGCAT_ENDPOINTS["products"].path), "productId")


def _organization_ids(session: requests.Session) -> list[str]:
    return _ids(_get_list(session, CONFIGCAT_ENDPOINTS["organizations"].path), "organizationId")


def _configs(session: requests.Session, product_id: str) -> list[dict[str, Any]]:
    path = CONFIGCAT_ENDPOINTS["configs"].path.format(productId=product_id)
    rows = _get_list(session, path)
    _ids(rows, "configId")
    return rows


def _environment_ids(session: requests.Session, product_id: str) -> list[str]:
    path = CONFIGCAT_ENDPOINTS["environments"].path.format(productId=product_id)
    return _ids(_get_list(session, path), "environmentId")


def _setting_value_rows(body: Any, config_id: str, environment_id: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError(f"ConfigCat returned a non-object values body for config {config_id}")
    formulas = body.get(SETTING_FORMULAS_SELECTOR)
    if not isinstance(formulas, list):
        raise ValueError(f"ConfigCat returned invalid settingFormulas for config {config_id}")

    rows: list[dict[str, Any]] = []
    for formula in formulas:
        if not isinstance(formula, dict):
            raise ValueError(f"ConfigCat returned a non-object setting formula for config {config_id}")
        setting = formula.get("setting")
        if not isinstance(setting, dict):
            raise ValueError(f"ConfigCat returned an invalid setting for config {config_id}")
        _identifier(setting, "settingId")
        rows.append(
            {
                **formula,
                "configId": config_id,
                "environmentId": environment_id,
                "settingId": setting["settingId"],
            }
        )
    return rows


def _v1_setting_value_rows(body: Any, config_id: str, environment_id: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError(f"ConfigCat returned a non-object values body for config {config_id}")
    values = body.get("settingValues")
    if not isinstance(values, list):
        raise ValueError(f"ConfigCat returned invalid settingValues for config {config_id}")

    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"ConfigCat returned a non-object setting value for config {config_id}")
        setting = value.get("setting")
        if not isinstance(setting, dict):
            raise ValueError(f"ConfigCat returned an invalid setting for config {config_id}")
        _identifier(setting, "settingId")
        rows.append(
            {
                **value,
                "configId": config_id,
                "environmentId": environment_id,
                "settingId": setting["settingId"],
            }
        )
    return rows


def _stale_flag_rows(body: Any, product_id: str) -> list[dict[str, Any]]:
    """Flatten the stale-flag report into one row per flag, keeping its per-environment detail."""
    if not isinstance(body, dict):
        raise ValueError(f"ConfigCat returned a non-object staleflags body for product {product_id}")
    configs = body.get("configs")
    if not isinstance(configs, list):
        raise ValueError(f"ConfigCat returned invalid staleflags configs for product {product_id}")

    rows: list[dict[str, Any]] = []
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError(f"ConfigCat returned a non-object staleflags config for product {product_id}")
        config_id = _identifier(config, "configId")
        settings = config.get("settings")
        if not isinstance(settings, list):
            raise ValueError(f"ConfigCat returned invalid staleflags settings for config {config_id}")
        for setting in settings:
            if not isinstance(setting, dict):
                raise ValueError(f"ConfigCat returned a non-object stale flag for config {config_id}")
            rows.append(
                {
                    **setting,
                    "productId": product_id,
                    "configId": config_id,
                    "configName": config.get("name"),
                }
            )
    return rows


def _organization_member_rows(body: Any, organization_id: str) -> list[dict[str, Any]]:
    """Flatten the members envelope into one row per user per role."""
    if not isinstance(body, dict):
        raise ValueError(f"ConfigCat returned a non-object members body for organization {organization_id}")

    rows: list[dict[str, Any]] = []
    for key, member_type in ORGANIZATION_MEMBER_GROUPS:
        members = body.get(key)
        if not isinstance(members, list):
            raise ValueError(f"ConfigCat returned invalid {key} for organization {organization_id}")
        for member in members:
            if not isinstance(member, dict):
                raise ValueError(f"ConfigCat returned a non-object {key} entry for organization {organization_id}")
            rows.append({**member, "organizationId": organization_id, "memberType": member_type})
    return rows


# Endpoints whose body is an envelope rather than a bare array, keyed by schema name. Each builder
# reshapes one response into rows, given the parent id the envelope does not repeat on every item.
ENVELOPE_ROW_BUILDERS: dict[str, Callable[[Any, str], list[dict[str, Any]]]] = {
    "stale_flags": _stale_flag_rows,
    "organization_members": _organization_member_rows,
}


def _to_configcat_datetime(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value into the UTC ISO 8601 shape `fromUtcDateTime` takes."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat()


def _audit_log_pages(
    session: requests.Session, organization_id: str, since: Optional[str]
) -> Iterator[list[dict[str, Any]]]:
    base_path = CONFIGCAT_ENDPOINTS["audit_logs"].path.format(organizationId=organization_id)
    page_number = 1
    while True:
        params: dict[str, Any] = {"pageNumber": page_number, "pageSize": AUDIT_LOG_PAGE_SIZE}
        if since is not None:
            params["fromUtcDateTime"] = since
        body = _get(session, f"{base_path}?{urlencode(params)}")
        if not isinstance(body, dict):
            raise ValueError(f"ConfigCat returned a non-object auditlogs body for organization {organization_id}")
        data = body.get("data")
        if not isinstance(data, list):
            raise ValueError(f"ConfigCat returned invalid auditlogs data for organization {organization_id}")
        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"ConfigCat returned a non-object audit log for organization {organization_id}")
            rows.append({**item, "organizationId": organization_id})
        paging = body.get("paging")
        # Losing `hasNext` would end the walk silently, and a run that stops early still commits
        # its watermark — so the rows behind the truncation would never be fetched again.
        if not isinstance(paging, dict) or not isinstance(paging.get("hasNext"), bool):
            raise ValueError(f"ConfigCat returned invalid auditlogs paging for organization {organization_id}")

        if rows:
            yield rows

        # An empty page also terminates: it is what a page past the end returns, so the walk stops
        # even if `hasNext` ever disagrees with the data.
        if not rows or not paging["hasNext"]:
            return
        page_number += 1


def _validate_primary_keys(rows: list[dict[str, Any]], primary_keys: list[str]) -> None:
    for row in rows:
        for field in primary_keys:
            _identifier(row, field)


def _parent_scoped_rows(
    session: requests.Session, config: ConfigCatEndpointConfig, parent_id: str, path: str
) -> list[dict[str, Any]]:
    builder = ENVELOPE_ROW_BUILDERS.get(config.name)
    rows = builder(_get(session, path), parent_id) if builder is not None else _get_list(session, path)
    _validate_primary_keys(rows, config.primary_keys)
    return rows


def _organization_rows(
    session: requests.Session, config: ConfigCatEndpointConfig, since: Optional[str]
) -> Iterator[list[dict[str, Any]]]:
    for organization_id in _organization_ids(session):
        if config.name == "audit_logs":
            for page in _audit_log_pages(session, organization_id, since):
                _validate_primary_keys(page, config.primary_keys)
                yield page
            continue

        rows = _parent_scoped_rows(session, config, organization_id, config.path.format(organizationId=organization_id))
        if rows:
            yield rows


def _tag_setting_rows(
    session: requests.Session, config: ConfigCatEndpointConfig, product_id: str
) -> Iterator[list[dict[str, Any]]]:
    tags_path = CONFIGCAT_ENDPOINTS["tags"].path.format(productId=product_id)
    for tag in _get_list(session, tags_path):
        tag_id = _identifier(tag, "tagId")
        # Carry the tag's own value rather than the stringified id, so the junction column keeps the
        # integer type the `tags` table stores it under.
        rows = [{**row, "tagId": tag["tagId"]} for row in _get_list(session, config.path.format(tagId=tag_id))]
        _validate_primary_keys(rows, config.primary_keys)
        if rows:
            yield rows


def _config_child_rows(
    session: requests.Session, config: ConfigCatEndpointConfig, configs: list[dict[str, Any]]
) -> Iterator[list[dict[str, Any]]]:
    for config_row in configs:
        config_id = _identifier(config_row, "configId")
        rows = _get_list(session, config.path.format(configId=config_id))
        _validate_primary_keys(rows, config.primary_keys)
        if rows:
            yield rows


def _config_environment_rows(
    session: requests.Session,
    config: ConfigCatEndpointConfig,
    configs: list[dict[str, Any]],
    environment_ids: list[str],
) -> Iterator[list[dict[str, Any]]]:
    for config_row in configs:
        config_id = _identifier(config_row, "configId")
        evaluation_version = config_row.get("evaluationVersion")
        if evaluation_version not in ("v1", "v2"):
            raise ValueError(f"ConfigCat config {config_id} has an invalid evaluationVersion")
        for environment_id in environment_ids:
            if evaluation_version == "v1":
                path = f"/v1/configs/{config_id}/environments/{environment_id}/values"
                rows = _v1_setting_value_rows(_get(session, path), config_id, environment_id)
            else:
                path = config.path.format(configId=config_id, environmentId=environment_id)
                rows = _setting_value_rows(_get(session, path), config_id, environment_id)
            if rows:
                yield rows


def _product_child_rows(
    session: requests.Session, config: ConfigCatEndpointConfig, product_id: str
) -> Iterator[list[dict[str, Any]]]:
    if config.parent == "product":
        rows = _parent_scoped_rows(session, config, product_id, config.path.format(productId=product_id))
        if rows:
            yield rows
        return

    if config.parent == "tag":
        yield from _tag_setting_rows(session, config, product_id)
        return

    configs = _configs(session, product_id)

    if config.parent == "config":
        yield from _config_child_rows(session, config, configs)
        return

    yield from _config_environment_rows(session, config, configs, _environment_ids(session, product_id))


def _fan_out_rows(
    session: requests.Session, config: ConfigCatEndpointConfig, since: Optional[str]
) -> Iterator[list[dict[str, Any]]]:
    if config.parent == "organization":
        yield from _organization_rows(session, config, since)
        return

    for product_id in _product_ids(session):
        yield from _product_child_rows(session, config, product_id)


def _partition_kwargs(config: ConfigCatEndpointConfig) -> dict[str, Any]:
    if config.partition_key is None:
        return {}
    return {
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": [config.partition_key],
    }


def _fan_out_source(
    username: str, password: str, config: ConfigCatEndpointConfig, since: Optional[str]
) -> SourceResponse:
    def items() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(headers=_headers(username, password), redact_values=(username, password))
        yield from _fan_out_rows(session, config, since)

    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode=config.sort_mode,
        **_partition_kwargs(config),
    )


def configcat_source(
    username: str,
    password: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CONFIGCAT_ENDPOINTS[endpoint]

    if config.parent is not None:
        return _fan_out_source(username, password, config, _to_configcat_datetime(db_incremental_field_last_value))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CONFIGCAT_BASE_URL,
            # Basic auth via the framework so the credential is redacted from logs; the client
            # retries 429/5xx (documented ~20 req/sec, ~500 req/min per endpoint) on its own.
            "auth": {"type": "http_basic", "username": username, "password": password},
            "headers": {"Accept": "application/json"},
            # The Public Management API list endpoints return the full collection in one response.
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # The body is a bare JSON array; require it to be a list so an unexpected object
                    # payload fails loud instead of syncing the object as a single row.
                    "data_selector_required": True,
                },
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
        sort_mode=config.sort_mode,
        **_partition_kwargs(config),
    )


def check_access(username: str, password: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the Public API credential.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(username, password), redact_values=(username, password))
    try:
        response = session.get(f"{CONFIGCAT_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to ConfigCat: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"ConfigCat returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(username: str, password: str) -> tuple[bool, str | None]:
    status, message = check_access(username, password)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid ConfigCat Public API credentials"
    return False, message or "Could not validate ConfigCat Public API credentials"
