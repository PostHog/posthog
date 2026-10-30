import time
import datetime as dt
import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import jwt
import requests
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.settings import (
    API_VERSION_PATH,
    DEFAULT_LOOKBACK_DAYS,
    DOCUSIGN_ENDPOINTS,
    PAGE_SIZE,
    DocusignEndpointConfig,
    DocusignFanOutConfig,
)

# DocuSign runs completely separate demo and production stacks: an integration key only works
# against production once it has passed DocuSign's go-live review.
AUTH_HOSTS: dict[str, str] = {
    "production": "https://account.docusign.com",
    "demo": "https://account-d.docusign.com",
}

JWT_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
# `impersonation` is what lets the JWT grant mint a token for `sub` without a browser round trip.
JWT_SCOPES = "signature impersonation"
JWT_ASSERTION_LIFETIME_SECONDS = 3600

REQUEST_TIMEOUT_SECONDS = 120

# Hard stop so a misbehaving endpoint that keeps advertising `nextUri` can't page forever.
MAX_PAGES = 20_000

# Per-envelope tables cost one request per envelope against the account's hourly API quota, which
# the customer's other DocuSign integrations share. Pause once only this fraction of it is left.
QUOTA_RESERVE_FRACTION = 0.1
MAX_QUOTA_WAIT_SECONDS = 3600


class DocusignAuthError(Exception):
    """Raised when DocuSign refuses to issue an access token."""


@dataclasses.dataclass
class DocusignResumeConfig:
    """Resume cursor: the 0-based offset of the next page to request."""

    start_position: int


@dataclasses.dataclass(frozen=True)
class DocusignCredentials:
    environment: str
    selection: str
    integration_key: str
    user_id: Optional[str] = None
    private_key: Optional[str] = dataclasses.field(default=None, repr=False)
    secret_key: Optional[str] = dataclasses.field(default=None, repr=False)
    refresh_token: Optional[str] = dataclasses.field(default=None, repr=False)
    account_id: Optional[str] = None

    @property
    def auth_host(self) -> str:
        host = AUTH_HOSTS.get(self.environment)
        if host is None:
            raise ValueError(f"Invalid DocuSign environment: {self.environment}")
        return host

    @property
    def secret_values(self) -> tuple[str, ...]:
        return tuple(v for v in (self.private_key, self.secret_key, self.refresh_token) if v)


@dataclasses.dataclass(frozen=True)
class DocusignAccount:
    """The account-specific REST base URL DocuSign hands back from `/oauth/userinfo`."""

    account_id: str
    base_url: str


def _auth_session(credentials: DocusignCredentials) -> requests.Session:
    # Token exchanges carry the private key / refresh token in the request and the freshly
    # minted access token in the response, so they stay out of HTTP sample capture entirely.
    return make_tracked_session(redact_values=credentials.secret_values, capture=False)


def _api_session(credentials: DocusignCredentials) -> requests.Session:
    return make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=credentials.secret_values,
    )


def _build_jwt_assertion(credentials: DocusignCredentials) -> str:
    if not credentials.user_id or not credentials.private_key:
        raise DocusignAuthError("JWT grant requires both an impersonated user ID and an RSA private key.")

    issued_at = int(time.time())
    claims: dict[str, Any] = {
        "iss": credentials.integration_key,
        "sub": credentials.user_id,
        # DocuSign wants the bare auth host, without a scheme.
        "aud": urlparse(credentials.auth_host).netloc,
        "iat": issued_at,
        "exp": issued_at + JWT_ASSERTION_LIFETIME_SECONDS,
        "scope": JWT_SCOPES,
    }
    try:
        return jwt.encode(claims, credentials.private_key, algorithm="RS256")
    except Exception as e:
        raise DocusignAuthError(
            "Your DocuSign RSA private key could not be read. Paste the full PEM key including the "
            "-----BEGIN RSA PRIVATE KEY----- and -----END RSA PRIVATE KEY----- lines."
        ) from e


def mint_access_token(session: requests.Session, credentials: DocusignCredentials) -> str:
    """Exchange the stored credentials for a short-lived (~1h) DocuSign access token."""
    url = f"{credentials.auth_host}/oauth/token"

    if credentials.selection == "jwt":
        response = session.post(
            url,
            data={"grant_type": JWT_GRANT_TYPE, "assertion": _build_jwt_assertion(credentials)},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    else:
        if not credentials.secret_key or not credentials.refresh_token:
            raise DocusignAuthError("Refresh token auth requires both a secret key and a refresh token.")
        response = session.post(
            url,
            data={"grant_type": "refresh_token", "refresh_token": credentials.refresh_token},
            auth=HTTPBasicAuth(credentials.integration_key, credentials.secret_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    if not response.ok:
        raise DocusignAuthError(f"DocuSign token request failed: {_error_detail(response)}")

    token = response.json().get("access_token")
    if not token:
        raise DocusignAuthError("DocuSign token response did not contain an access token.")
    return str(token)


def _error_detail(response: requests.Response) -> str:
    """DocuSign reports permanent auth problems in the body (`consent_required`, `invalid_grant`)."""
    try:
        body = response.json()
    except ValueError:
        return f"status={response.status_code}"
    if isinstance(body, dict):
        error = body.get("error") or body.get("errorCode")
        description = body.get("error_description") or body.get("message")
        if error:
            return f"status={response.status_code} error={error} description={description}"
    return f"status={response.status_code}"


def resolve_account(session: requests.Session, credentials: DocusignCredentials, token: str) -> DocusignAccount:
    """Look up the account-specific REST base URL, which differs per account (na3, eu1, ...)."""
    response = session.get(
        f"{credentials.auth_host}/oauth/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise DocusignAuthError(f"DocuSign userinfo request failed: {_error_detail(response)}")

    accounts = response.json().get("accounts") or []
    if not accounts:
        raise DocusignAuthError("The DocuSign user has no accounts available to this integration key.")

    if credentials.account_id:
        matched = next((a for a in accounts if str(a.get("account_id")) == credentials.account_id), None)
        if matched is None:
            raise DocusignAuthError(f"DocuSign account {credentials.account_id} is not accessible to this user.")
    else:
        matched = next((a for a in accounts if a.get("is_default")), accounts[0])

    base_uri = str(matched["base_uri"]).rstrip("/")
    return DocusignAccount(
        account_id=str(matched["account_id"]),
        base_url=f"{base_uri}/restapi/{API_VERSION_PATH}/accounts/{matched['account_id']}",
    )


def _to_iso8601(value: Any) -> Optional[str]:
    """Coerce an incremental watermark to the UTC ISO-8601 string DocuSign's date filters take."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dt.datetime):
        moment = value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min, tzinfo=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    return text or None


def _default_from_date(start_date: Optional[str]) -> str:
    if start_date and start_date.strip():
        return start_date.strip()
    floor = dt.datetime.now(dt.UTC) - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS)
    return floor.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_params(
    endpoint: DocusignEndpointConfig,
    start_position: int,
    from_date: Optional[str],
) -> dict[str, str]:
    params: dict[str, str] = {**endpoint.params, "count": str(PAGE_SIZE), "start_position": str(start_position)}
    if endpoint.date_filter_param and from_date:
        params[endpoint.date_filter_param] = from_date
    return params


def _has_next_page(body: dict[str, Any], items: list[dict[str, Any]]) -> bool:
    """DocuSign advertises more rows via `nextUri`; fall back to a full page as the signal.

    We drive pagination off `start_position` arithmetic rather than following `nextUri`, because
    `nextUri` is a host-relative path and re-joining it against the account base URL is a
    needless place to get the account-specific host wrong.
    """
    if body.get("nextUri"):
        return True
    return len(items) >= PAGE_SIZE


def _flatten_recipients(envelope: dict[str, Any], parent: dict[str, Any]) -> list[dict[str, Any]]:
    """Split the per-role recipient buckets DocuSign nests under `recipients` into flat rows."""
    recipients = envelope.get("recipients")
    if not isinstance(recipients, dict):
        return []

    rows: list[dict[str, Any]] = []
    for recipient_type, bucket in recipients.items():
        if not isinstance(bucket, list):
            # `recipients` also carries scalars like `recipientCount` alongside the role buckets.
            continue
        for recipient in bucket:
            if isinstance(recipient, dict):
                rows.append({**recipient, **parent, "recipientType": recipient_type})
    return rows


def _flatten_custom_fields(envelope: dict[str, Any], parent: dict[str, Any]) -> list[dict[str, Any]]:
    custom_fields = envelope.get("customFields")
    if not isinstance(custom_fields, dict):
        return []

    rows: list[dict[str, Any]] = []
    for field_type, bucket_key in (("text", "textCustomFields"), ("list", "listCustomFields")):
        for custom_field in custom_fields.get(bucket_key) or []:
            if not isinstance(custom_field, dict):
                continue
            # The field id is part of the primary key, so fall back to the name when it is absent.
            field_id = custom_field.get("fieldId") or custom_field.get("name")
            if not field_id:
                continue
            rows.append({**custom_field, **parent, "customFieldType": field_type, "fieldId": str(field_id)})
    return rows


def _flatten_envelope_children(
    endpoint: DocusignEndpointConfig, envelopes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for envelope in envelopes:
        envelope_id = envelope.get("envelopeId")
        if not envelope_id:
            continue
        # Carry the parent's timestamps so the child table can be synced incrementally against
        # the same `from_date` window that produced its parent, and partitioned on a stable key.
        parent = _envelope_parent(envelope)

        if endpoint.derived_from_envelopes == "recipients":
            rows.extend(_flatten_recipients(envelope, parent))
            continue

        if endpoint.derived_from_envelopes == "custom_fields":
            rows.extend(_flatten_custom_fields(envelope, parent))
            continue

        for key in endpoint.envelope_child_keys:
            children = envelope.get(key)
            if isinstance(children, list):
                rows.extend({**child, **parent} for child in children if isinstance(child, dict))
                break
    return rows


def _quota_wait_seconds(headers: Mapping[str, str], now: float) -> float:
    """Seconds until DocuSign resets the hourly quota, when the last response left too little of it."""
    try:
        remaining = int(headers["X-RateLimit-Remaining"])
        limit = int(headers["X-RateLimit-Limit"])
        reset_at = float(headers["X-RateLimit-Reset"])
    except (KeyError, ValueError):
        return 0.0
    if remaining > limit * QUOTA_RESERVE_FRACTION:
        return 0.0
    return min(max(reset_at - now, 0.0), MAX_QUOTA_WAIT_SECONDS)


def _envelope_parent(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "envelopeId": str(envelope["envelopeId"]),
        "envelopeCreatedDateTime": envelope.get("createdDateTime"),
        "envelopeStatusChangedDateTime": envelope.get("statusChangedDateTime"),
    }


def _shape_envelope_sub_resource(
    endpoint: DocusignEndpointConfig, body: dict[str, Any], parent: dict[str, Any]
) -> list[dict[str, Any]]:
    if endpoint.envelope_sub_resource == "form_data":
        return [{**body, **parent}]

    if endpoint.envelope_sub_resource == "audit_events":
        rows: list[dict[str, Any]] = []
        for index, event in enumerate(body.get("auditEvents") or []):
            if not isinstance(event, dict):
                continue
            # Each event arrives as a list of name/value pairs (logTime, Action, UserName, ...).
            fields = {
                str(item["name"]): item.get("value")
                for item in event.get("eventFields") or []
                if isinstance(item, dict) and item.get("name")
            }
            rows.append({**fields, **parent, "eventIndex": index})
        return rows

    # DocuSign can list a template once per envelope document it supplied; keep one row per template.
    templates: dict[str, dict[str, Any]] = {}
    for template in body.get("templates") or []:
        if isinstance(template, dict) and template.get("templateId"):
            templates.setdefault(str(template["templateId"]), {**template, **parent})
    return list(templates.values())


def _shape_fan_out_rows(fan_out: DocusignFanOutConfig, body: dict[str, Any], parent_id: str) -> list[dict[str, Any]]:
    items = [item for item in (body.get(fan_out.data_key) or []) if isinstance(item, dict)]
    if not fan_out.flatten_envelope_recipients:
        return [{**item, fan_out.parent_id_column: parent_id} for item in items]

    rows: list[dict[str, Any]] = []
    for envelope in items:
        envelope_id = envelope.get("envelopeId")
        if not envelope_id:
            continue
        for recipient in envelope.get("recipients") or []:
            if isinstance(recipient, dict):
                rows.append({**recipient, "envelopeId": str(envelope_id), fan_out.parent_id_column: parent_id})
    return rows


def get_rows(
    credentials: DocusignCredentials,
    endpoint_name: str,
    start_date: Optional[str],
    resumable_source_manager: ResumableSourceManager[DocusignResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = DOCUSIGN_ENDPOINTS[endpoint_name]

    auth_session = _auth_session(credentials)
    api_session = _api_session(credentials)
    token = mint_access_token(auth_session, credentials)
    account = resolve_account(auth_session, credentials, token)

    from_date: Optional[str] = None
    if endpoint.date_filter_param:
        watermark = _to_iso8601(db_incremental_field_last_value) if should_use_incremental_field else None
        from_date = watermark or _default_from_date(start_date)

    start_position = 0
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            start_position = resume.start_position
            logger.debug(f"Resuming DocuSign {endpoint_name} from start_position={start_position}")

    last_headers: Mapping[str, str] = {}

    def request(path: str, params: dict[str, str]) -> dict[str, Any]:
        nonlocal token, last_headers
        url = f"{account.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        def _do() -> requests.Response:
            return api_session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        response = _do()
        # Access tokens last ~1h; re-mint once if a long sync outlives one.
        if response.status_code == 401:
            token = mint_access_token(auth_session, credentials)
            response = _do()

        last_headers = response.headers
        if not response.ok:
            logger.error(f"DocuSign API error: url={url}, {_error_detail(response)}")
            response.raise_for_status()

        body = response.json()
        return body if isinstance(body, dict) else {}

    def pause_if_quota_low() -> None:
        wait_seconds = _quota_wait_seconds(last_headers, time.time())
        if wait_seconds > 0:
            logger.info(f"DocuSign hourly API quota is low, pausing {wait_seconds:.0f}s until it resets")
            interruptible_wait(wait_seconds, safe_point=resumable_source_manager.safe_point)

    def fan_out_rows(fan_out: DocusignFanOutConfig, parent_id: str) -> Iterator[list[dict[str, Any]]]:
        path = fan_out.path.format(parent_id=quote(parent_id, safe=""))
        child_position = 0
        for _ in range(MAX_PAGES):
            params = dict(fan_out.params)
            if fan_out.paginated:
                params.update({"count": str(PAGE_SIZE), "start_position": str(child_position)})

            pause_if_quota_low()
            try:
                body = request(path, params)
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code not in fan_out.skip_statuses:
                    raise
                logger.warning(f"Skipping DocuSign {endpoint_name} for {parent_id}: status={e.response.status_code}")
                resumable_source_manager.safe_point()
                return

            rows = _shape_fan_out_rows(fan_out, body, parent_id)
            if rows:
                yield rows
            else:
                # The staged cursor is the start of the parent page, so resuming re-reads it whole.
                resumable_source_manager.safe_point()

            page = body.get(fan_out.data_key) or []
            if not fan_out.paginated or not page or not _has_next_page(body, page):
                return
            child_position += len(page)

    for _ in range(MAX_PAGES):
        body = request(endpoint.path, _build_params(endpoint, start_position, from_date))
        page = [item for item in (body.get(endpoint.data_key) or []) if isinstance(item, dict)]

        if endpoint.envelope_sub_resource:
            for envelope in page:
                if not envelope.get("envelopeId"):
                    continue
                pause_if_quota_low()

                parent = _envelope_parent(envelope)
                sub_resource_path = (
                    f"{endpoint.path}/{quote(parent['envelopeId'], safe='')}/{endpoint.envelope_sub_resource}"
                )
                sub_rows = _shape_envelope_sub_resource(
                    endpoint, request(sub_resource_path, endpoint.envelope_sub_resource_params), parent
                )
                if sub_rows:
                    yield sub_rows
                else:
                    # The staged cursor is the start of this page, so resuming re-reads it whole.
                    resumable_source_manager.safe_point()
        elif endpoint.fan_out:
            for parent_row in page:
                parent_id = parent_row.get(endpoint.fan_out.parent_id_key)
                if parent_id:
                    yield from fan_out_rows(endpoint.fan_out, str(parent_id))
        else:
            rows = _flatten_envelope_children(endpoint, page) if endpoint.derived_from_envelopes else page
            if rows:
                yield rows

        if not endpoint.supports_pagination or not page or not _has_next_page(body, page):
            break

        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary
        # key) rather than skipping it.
        start_position += len(page)
        resumable_source_manager.save_state(DocusignResumeConfig(start_position=start_position))

    resumable_source_manager.clear_state()


def validate_credentials(credentials: DocusignCredentials) -> tuple[bool, Optional[str]]:
    """Mint a token and resolve the account — the cheapest end-to-end proof the setup works."""
    try:
        session = _auth_session(credentials)
        token = mint_access_token(session, credentials)
        resolve_account(session, credentials, token)
    except DocusignAuthError as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach DocuSign with the provided credentials."
    return True, None


def docusign_source(
    credentials: DocusignCredentials,
    endpoint_name: str,
    start_date: Optional[str],
    resumable_source_manager: ResumableSourceManager[DocusignResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint = DOCUSIGN_ENDPOINTS[endpoint_name]

    return SourceResponse(
        name=endpoint_name,
        items=lambda: get_rows(
            credentials=credentials,
            endpoint_name=endpoint_name,
            start_date=start_date,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint.primary_key,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
    )
