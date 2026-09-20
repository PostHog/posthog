import base64
from collections.abc import Iterator
from typing import Any, Optional

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


def _validate_primary_keys(rows: list[dict[str, Any]], primary_keys: list[str]) -> None:
    for row in rows:
        for field in primary_keys:
            _identifier(row, field)


def _fan_out_rows(session: requests.Session, config: ConfigCatEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    for product_id in _product_ids(session):
        if config.parent == "product":
            rows = _get_list(session, config.path.format(productId=product_id))
            _validate_primary_keys(rows, config.primary_keys)
            if rows:
                yield rows
            continue

        configs = _configs(session, product_id)

        if config.parent == "config":
            for config_row in configs:
                config_id = _identifier(config_row, "configId")
                rows = _get_list(session, config.path.format(configId=config_id))
                _validate_primary_keys(rows, config.primary_keys)
                if rows:
                    yield rows
            continue

        environment_ids = _environment_ids(session, product_id)
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


def _fan_out_source(username: str, password: str, config: ConfigCatEndpointConfig) -> SourceResponse:
    def items() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(headers=_headers(username, password), redact_values=(username, password))
        yield from _fan_out_rows(session, config)

    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def configcat_source(
    username: str,
    password: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = CONFIGCAT_ENDPOINTS[endpoint]

    if config.parent is not None:
        return _fan_out_source(username, password, config)

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
