import copy
import json
import hashlib
import graphlib
from collections.abc import Callable
from datetime import date
from typing import Any, Literal, NamedTuple, Optional, cast
from urllib.parse import quote, quote_plus, urlparse

from django.db import IntegrityError

import structlog
from jsonpath_ng.exceptions import JSONPathError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from requests import PreparedRequest, Response, Timeout
from urllib3.util.retry import Retry

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.models.custom_oauth2_integration import (
    CustomOAuth2Integration,
    get_custom_oauth2_integration,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SortMode,
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_adapter,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import _NoRedirectSession
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    OAuth2Auth,
    OAuth2AuthRequestError,
    auth_secret_values,
    strip_oauth2_permanent_marker,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    build_resource_dependency_graph,
    create_auth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    EndpointResource,
    EndpointResourceBase,
    ResolvedParam,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.utils import (
    exclude_keys,
    resolve_request_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

# Credential keys that must NOT appear inline in the manifest — they belong in
# the dedicated secret `auth_*` config fields so the API layer can redact them.
INLINE_SECRET_KEYS = ("token", "api_key", "password", "client_secret", "refresh_token", "access_token")

logger = structlog.get_logger(__name__)

# Outbound create-time probe tunables. The probe runs inline on the API request
# thread, the same as business_knowledge's URL fetch, so it borrows that feature's
# limits (products/business_knowledge/backend/constants.py): short connect/read
# timeouts and a hard upper bound on declared resources. Defined locally rather
# than imported so data_imports doesn't couple to an unrelated product.
PROBE_CONNECT_TIMEOUT = 5
PROBE_READ_TIMEOUT = 10
# Auth/header config is shared across resources and the probe only acts on 401/403,
# so one reachable resource validates the credential. Probe a small prefix instead
# of one request per declared resource — otherwise the endpoint is an on-demand
# outbound-request amplifier (one API call -> N outbound requests).
PROBE_MAX_RESOURCES = 5
# Bytes read from a 401/403 body for the error snippet. The probe opens responses
# with stream=True and never ingests the body, so a bounded slice keeps a large or
# hostile response from being buffered into worker memory (cf. URL_MAX_BYTES, sized
# down here because the probe only needs a short diagnostic snippet).
PROBE_ERROR_SNIPPET_BYTES = 2048
# Upper bound on the number of resources (tables/endpoints) a single custom
# source may declare. Also bounds the create-time outbound-request amplifier.
MAX_MANIFEST_RESOURCES = 50

# Upper bound on the number of custom sources a single team/project may create.
# Enforced in the external_data_source create endpoint.
MAX_CUSTOM_SOURCES_PER_TEAM = 5

# Bounds on the create-time preview / test-read. Like the probe, preview runs
# inline on the API request thread, so the row count is hard-capped: the default
# is enough to eyeball data_selector / primary_key / cursor_path, and the max
# stops a preview from buffering a large page into worker memory.
PREVIEW_DEFAULT_ROWS = 10
PREVIEW_MAX_ROWS = 50
# Cap the parent rows a fan-out preview walks: the engine fires one child request
# per parent, and empty child pages slip past the row cap (see `preview_resource`).
PREVIEW_MAX_FANOUT_PARENTS = 10
# Total decoded response bytes one preview may parse, across all its requests — a
# per-response cap wouldn't bound a fan-out's many pages (see `_PreviewSession`).
PREVIEW_MAX_TOTAL_BODY_BYTES = 20 * 1024 * 1024
# Compressed bytes pulled per streamed read while enforcing that budget; small so a
# bomb can inflate at most one chunk's worth past the budget before we abort.
PREVIEW_READ_CHUNK_BYTES = 64 * 1024


class ManifestValidationError(ValueError):
    """Raised when the user-provided manifest doesn't conform to RESTAPIConfig."""


class _ManifestAuth(BaseModel):
    # Only the non-secret auth fields are modelled, and extras are forbidden:
    # a misspelled key (e.g. `header` instead of `name`) fails manifest
    # validation here with a clear message instead of crashing the REST
    # engine's `create_auth` with an unexpected-kwarg TypeError at sync time.
    model_config = ConfigDict(extra="forbid")

    type: Literal["bearer", "api_key", "http_basic", "oauth2"]
    name: str | None = None
    location: Literal["header", "query", "param", "cookie"] | None = None
    username: str | None = None
    # OAuth2 (non-secret) fields. The customer brings their own client: client_id /
    # token_url and the extensibility knobs live in the manifest, while client_secret /
    # refresh_token are injected from the secret auth_oauth2_* config fields at sync time.
    # `authorization_code` is out of scope (needs an interactive consent flow), so the
    # grant Literal admits only the two non-interactive grants — a manifest declaring any
    # other grant fails validation here. Every field is optional so the non-oauth2 types
    # are unaffected; the after-validator enforces what oauth2 actually requires.
    client_id: str | None = None
    token_url: str | None = None
    grant_type: Literal["client_credentials", "refresh_token"] | None = None
    scopes: str | None = None
    access_token_name: str | None = None
    expires_in_name: str | None = None
    expiry_date_format: str | None = None
    extra_token_request_params: dict[str, str] | None = None
    token_request_headers: dict[str, str] | None = None
    client_auth_method: Literal["body", "basic"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_inline_credentials(cls, data: Any) -> Any:
        # Credentials belong in the secret auth_* config fields, never inline in
        # the manifest — the manifest field is non-secret and round-trips to the client.
        if isinstance(data, dict):
            inline = [key for key in INLINE_SECRET_KEYS if data.get(key)]
            # `extra_token_request_params` / `token_request_headers` are forwarded verbatim to the token
            # endpoint but live in the non-secret manifest, so a secret stashed in them would round-trip
            # to anyone who can read the source. Scan their keys too — case-insensitively, since header
            # names like `Authorization` are arbitrarily cased.
            for nested_key in ("extra_token_request_params", "token_request_headers"):
                nested = data.get(nested_key)
                if isinstance(nested, dict):
                    lowered = {str(key).lower(): value for key, value in nested.items()}
                    inline += [
                        f"{nested_key}.{key}" for key in (*INLINE_SECRET_KEYS, "authorization") if lowered.get(key)
                    ]
            if inline:
                raise ValueError(
                    f"Credentials ({', '.join(inline)}) must not be embedded — use the dedicated auth fields"
                )
        return data

    @model_validator(mode="after")
    def _require_oauth2_fields(self) -> "_ManifestAuth":
        # client_id + token_url are the minimum a customer-owned OAuth2 client needs;
        # without them the token exchange can't run. (client_secret is a separate
        # secret field, so it isn't required here.)
        if self.type == "oauth2":
            missing = [field for field in ("client_id", "token_url") if not getattr(self, field)]
            if missing:
                raise ValueError(f"OAuth2 auth requires {' and '.join(missing)} in the manifest")
        return self


class _ManifestClient(BaseModel):
    base_url: str = Field(min_length=1)
    auth: _ManifestAuth | None = None


class _ManifestEndpoint(BaseModel):
    path: str = Field(min_length=1)
    # GET and POST only. Data-warehouse syncs only ever read upstream data;
    # POST is permitted because some read/query-style endpoints require it, but
    # PUT/PATCH/DELETE are excluded so a misconfigured manifest can't mutate or
    # delete upstream data.
    method: Literal["GET", "POST", "get", "post"] | None = None
    # Query params and request body. Modelled only so a malformed `params`/`json`
    # (e.g. a JSON array where an object is expected) is caught at manifest time;
    # both still pass through untouched to the REST engine. `params` values may be
    # plain scalars or the engine's incremental/resolver specs, so the type stays
    # permissive. `json` is aliased because `json` shadows a `BaseModel` attribute.
    params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = Field(default=None, alias="json")


class _ManifestResource(BaseModel):
    name: str = Field(min_length=1)
    endpoint: _ManifestEndpoint
    # How the upstream API orders this resource's rows. Incremental syncs commit
    # the high-watermark per batch for "asc"; for a source whose order is
    # unknown or descending, declaring "desc" here avoids skipping rows on a
    # resumed sync. Defaults to "asc" when omitted.
    sort_mode: Literal["asc", "desc"] | None = None


class _Manifest(BaseModel):
    """Structural schema for a user-provided REST API manifest. Only the fields
    this source reads are modelled; every other RESTAPIConfig field (paginator,
    data_selector, incremental, …) passes through untouched to the REST engine."""

    client: _ManifestClient
    resources: list[_ManifestResource] = Field(min_length=1, max_length=MAX_MANIFEST_RESOURCES)

    @model_validator(mode="after")
    def _resource_names_unique(self) -> "_Manifest":
        seen: set[str] = set()
        for resource in self.resources:
            if resource.name in seen:
                raise ValueError(f"Duplicate resource name: {resource.name!r}")
            seen.add(resource.name)
        return self


def validate_manifest_structure(manifest: Any) -> None:
    """Validate only the structural shape of a manifest, via the
    :class:`_Manifest` schema.

    This is the validation level used on sync and schema-listing reads of
    already-stored manifests: it must stay permissive enough that tightening
    the rules can never brick a deployed source's syncs. Graph-level fan-out
    errors are checked separately by :func:`_validate_resource_graph` on the
    API validation paths (`validate_credentials`), and per-schema at sync time
    by :func:`_fanout_chain`.
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest must be a JSON object")
    try:
        _Manifest.model_validate(manifest)
    except ValidationError as exc:
        raise ManifestValidationError(_format_validation_errors(exc)) from exc


def _validate_resource_graph(manifest: dict[str, Any]) -> dict[str, Optional[ResolvedParam]]:
    """Surface parent/child fan-out errors at create-time instead of first sync.

    Reuses the REST engine's own :func:`build_resource_dependency_graph` so the
    rules can't drift from what the engine enforces at runtime: a child's
    ``type: "resolve"`` param must reference a resource that exists, must be
    bound in the path (``/forms/{form_id}/responses`` — query-param resolve is
    not supported by the engine), at most one resolve param per resource, and no
    dependency cycles (forced by ``static_order``). The graph builder mutates the
    resources it inspects (binds path params), so it runs on a deep copy and
    never touches the stored manifest.

    On top of the engine's rules, nesting is capped at one level: a parent must
    itself be top-level. The engine supports deeper chains, but each extra level
    multiplies the per-sync request volume by the parent's row count and every
    ancestor full-scans on every run — and no shipped fan-out source (PostHog
    built-ins, or any of Airbyte's declarative connectors) uses more than one
    level. Starting strict is deliberately cheap to relax later; loosening the
    cap is backwards-compatible, tightening it would break stored manifests.

    Returns the engine's parent-resolution map (resource name -> resolve param,
    ``None`` for top-level resources) so callers that need it — the probe's
    child filter — don't rebuild the graph.
    """
    try:
        graph, resource_map, resolved = _build_resource_graph(manifest)
        list(graph.static_order())
    except KeyError as exc:
        # A resolve param missing "resource"/"field" raises KeyError from deep
        # inside the engine — surface it as a validation error, not a 500.
        raise ManifestValidationError(f"A resolve param is missing the required key {exc}") from exc
    except JSONPathError as exc:
        # The resolve param's "field" is a JSONPath, compiled inside the engine;
        # a malformed expression raises a bare-Exception subclass.
        raise ManifestValidationError(f"A resolve param's field is not a valid JSONPath: {exc}") from exc
    except graphlib.CycleError as exc:
        # str(CycleError) is the raw args tuple — render the cycle readably.
        cycle = exc.args[1] if len(exc.args) > 1 else []
        rendered = " -> ".join(str(name) for name in cycle)
        raise ManifestValidationError(f"Resources form a dependency cycle: {rendered}") from exc
    except (ValueError, NotImplementedError) as exc:
        raise ManifestValidationError(str(exc)) from exc

    client = manifest.get("client")
    base_url = client.get("base_url") if isinstance(client, dict) else None
    for name, resolved_param in resolved.items():
        if resolved_param is None:
            continue
        parent = resolved_param.resolve_config["resource"]
        if resolved.get(parent) is not None:
            raise ManifestValidationError(
                f"Resource {name!r} depends on {parent!r}, which itself depends on another resource — "
                "a resource can only depend on a top-level resource (one level of nesting)"
            )
        # The parent placeholder is filled with uncontrolled upstream data at
        # sync time, then the engine resolves the path against base_url. A
        # placeholder positioned where it can supply the URL's authority lets that
        # parent value redirect the authenticated request — and its credential —
        # off base_url: a leading placeholder (`{form_id}/...`) can be a full
        # `https://attacker/...`, and a literal scheme prefix (`https:{form_id}`)
        # lets `//attacker/...` take over the authority. Neither the create-time
        # host validator nor the update retarget guard can see this — they only
        # ever inspect the literal placeholder. The path comes from `resource_map`
        # (defaults merged, scalar params already bound), so only the resolve
        # placeholder survives in the same string the request is built from.
        endpoint = resource_map[name].get("endpoint")
        path = endpoint.get("path", "") if isinstance(endpoint, dict) else ""
        if (
            isinstance(path, str)
            and isinstance(base_url, str)
            and _placeholder_escapes_base(path, resolved_param.param_name, base_url)
        ):
            raise ManifestValidationError(
                f"Resource {name!r}: the parent placeholder {{{resolved_param.param_name}}} must sit within the path "
                "of the base URL (e.g. /forms/{form_id}/responses) — it must not start the path or follow a scheme "
                "like 'https:', so the bound parent value can't redirect the request off the manifest's base URL"
            )
    return resolved


def _validate_incremental_configs(manifest: dict[str, Any]) -> None:
    """Reject incremental config values that would deterministically crash at sync time.

    The structural schema doesn't model ``endpoint.incremental``, so a hand-authored
    non-string ``datetime_format`` would otherwise only surface mid-sync, and only
    from the second sync onward (formatting needs a stored watermark).
    """
    for resource in manifest.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        endpoint = resource.get("endpoint")
        incremental = endpoint.get("incremental") if isinstance(endpoint, dict) else None
        if not isinstance(incremental, dict):
            continue
        datetime_format = incremental.get("datetime_format")
        if datetime_format is not None and not isinstance(datetime_format, str):
            raise ManifestValidationError(
                f"Resource {resource.get('name')!r}: endpoint.incremental.datetime_format must be a string "
                'strftime pattern (e.g. "%Y-%m-%dT%H:%M:%SZ")'
            )


# Plain-English replacements for the pydantic constraint messages users hit most
# when hand-authoring a manifest; an unmapped error keeps pydantic's own wording.
_VALIDATION_MESSAGE_OVERRIDES = {
    "string_too_short": "must not be empty",
}


def _render_error_location(loc: tuple[Any, ...]) -> str:
    """Render a pydantic ``loc`` tuple as a path that mirrors the manifest JSON,
    e.g. ``("resources", 0, "endpoint", "path")`` -> ``resources[0].endpoint.path``."""
    rendered = ""
    for part in loc:
        if isinstance(part, int):
            rendered += f"[{part}]"
        elif rendered:
            rendered += f".{part}"
        else:
            rendered = str(part)
    return rendered


def _format_validation_errors(exc: ValidationError) -> str:
    """Render Pydantic's validation errors as a single user-facing string.

    Pydantic's positional loc tuples and raw constraint wording ("String should
    have at least 1 character") read like internals to someone editing manifest
    JSON, so mirror the JSON path and swap the common messages for plainer English.
    """
    messages: list[str] = []
    for error in exc.errors():
        location = _render_error_location(error["loc"])
        message = _VALIDATION_MESSAGE_OVERRIDES.get(error["type"], error["msg"].removeprefix("Value error, "))
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages)


def validate_manifest_urls(manifest: dict[str, Any], team_id: int) -> tuple[bool, str | None]:
    """Walk every URL field in the manifest and reject internal/private hosts.

    Also enforces ``https://`` on PostHog Cloud. Self-hosted instances skip
    the host check via :func:`_is_host_safe` (which is itself a no-op
    outside of cloud).
    """
    base_url = manifest["client"]["base_url"]
    ok, err = _check_url(base_url, team_id)
    if not ok:
        return False, f"Invalid base_url: {err}"

    # The OAuth2 token endpoint is a second customer-controlled host that receives the
    # client_secret. Vet it like base_url: https-on-Cloud + internal-host rejection.
    # Defense-in-depth (Smokescreen already guards egress); the load-bearing control
    # against repointing token_url to exfiltrate the secret is the re-entry gate, which
    # sees token_url via manifest_request_hosts (same extraction, shared helper).
    token_url = _manifest_oauth2_token_url(manifest.get("client"))
    if token_url is not None:
        ok, err = _check_url(token_url, team_id)
        if not ok:
            return False, f"Invalid token_url: {err}"

    base_host = _url_hostname(base_url)
    for resource in manifest["resources"]:
        # Resolve exactly as the engine will (so a whitespace/case-disguised absolute path
        # is caught), then only re-vet resources that resolve to a *different* host than
        # base_url — `_is_host_safe` does a DNS lookup, so don't re-resolve base per resource.
        resolved = _endpoint_request_url(base_url, resource.get("endpoint"))
        if resolved is None or _url_hostname(resolved) == base_host:
            continue
        ok, err = _check_url(resolved, team_id)
        if not ok:
            return False, f"Resource {resource['name']!r}: {err}"

    return True, None


def _check_url(url: str, team_id: int) -> tuple[bool, str | None]:
    # `_url_hostname` mirrors the real connect host (backslash/whitespace-normalized) so the
    # validator can't be fooled into vetting a different host than the request reaches.
    hostname = _url_hostname(url)
    if not hostname:
        return False, f"URL {url!r} is missing a hostname"
    if is_cloud() and urlparse(url).scheme != "https":
        return False, f"URL {url!r} must use https:// on PostHog Cloud"
    return _is_host_safe(hostname, team_id)


class _LeaveMissing(dict):
    """Format mapping that leaves unknown ``{name}`` placeholders untouched."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _endpoint_request_url(base_url: str, endpoint: Any) -> str | None:
    """The URL an endpoint will send a request — and the credential — to.

    The REST engine binds scalar ``params`` into the path (``_bind_path_params`` runs
    ``path.format(**params)``) and then resolves it against ``base_url`` via
    ``resolve_request_url``. We do exactly the same here, so a template like ``"{target}"``
    (``params={"target": "https://attacker/"}``) or ``"{scheme}://attacker/"``
    (``params={"scheme": "https"}``) — and any whitespace/case/encoding-disguised absolute
    URL — resolves to the same destination the runtime would request. Returns ``None`` for a
    non-dict endpoint or a missing/non-string path. (SSRF to internal hosts is separately
    caught at request time by the transport-layer guard; this is about detecting a *new
    destination* for the credential re-entry check.)
    """
    if not isinstance(endpoint, dict):
        return None
    path = endpoint.get("path")
    if not isinstance(path, str):
        return None

    params = endpoint.get("params")
    bindable = (
        _LeaveMissing({name: value for name, value in params.items() if isinstance(value, str)})
        if isinstance(params, dict)
        else _LeaveMissing()
    )
    try:
        resolved = path.format_map(bindable)
    except (ValueError, IndexError, KeyError):
        # Malformed / positional format string — it's re-vetted at request time anyway.
        resolved = path

    return resolve_request_url(base_url, resolved)


def _manifest_oauth2_token_url(client: Any) -> str | None:
    """The oauth2 ``token_url`` for a parsed manifest's ``client``, or ``None`` if absent /
    non-oauth2 / non-string.

    Single source for the two places that must agree on it — :func:`validate_manifest_urls`
    (vets the host) and :func:`manifest_request_hosts` (feeds the credential re-entry gate).
    Keeping them in lockstep matters for security: if the re-entry gate ever stopped tracking
    ``token_url`` while the URL vetting still did, an editor could repoint it past the gate.
    """
    auth = client.get("auth") if isinstance(client, dict) else None
    if isinstance(auth, dict) and auth.get("type") == "oauth2":
        token_url = auth.get("token_url")
        if isinstance(token_url, str):
            return token_url
    return None


def manifest_request_hosts(manifest_json: Any) -> frozenset[str]:
    """Hostnames a stored manifest will send requests — and the credential — to.

    Lets the API layer detect when an update retargets the source at a new host
    so it can require the credential to be re-entered: an editor who can't read
    the stored secret must not be able to redirect it to a server they control.
    Returns an empty set for anything unparseable — the caller treats "no hosts"
    as "nothing new", and a malformed manifest is rejected elsewhere.
    """
    if not isinstance(manifest_json, str):
        return frozenset()
    try:
        manifest = json.loads(manifest_json)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(manifest, dict):
        return frozenset()

    client = manifest.get("client")
    base_url = client.get("base_url") if isinstance(client, dict) else None
    # Resolve resource paths against base_url the same way the engine does. With no usable
    # base_url an absolute resource path still has a host; a relative one is left hostless
    # (its destination is unknown) — the manifest is rejected elsewhere for the missing base.
    base_for_resolve = base_url if isinstance(base_url, str) else ""

    urls: list[str] = [base_url] if isinstance(base_url, str) else []
    resources = manifest.get("resources")
    if isinstance(resources, list):
        for resource in resources:
            endpoint = resource.get("endpoint") if isinstance(resource, dict) else None
            resolved = _endpoint_request_url(base_for_resolve, endpoint)
            if resolved is not None:
                urls.append(resolved)

    # The OAuth2 token endpoint receives the stored client_secret, so it's a request
    # destination the re-entry gate must track: an editor who can't read the secret
    # must not be able to repoint token_url at a host they control while keeping the
    # secret. It's a literal URL (not a path template), so add its host directly —
    # don't run the path-resolution logic on it.
    token_url = _manifest_oauth2_token_url(client)
    if token_url is not None:
        urls.append(token_url)

    # `_url_hostname` returns an already-lowercased host.
    hosts = {host for url in urls if (host := _url_hostname(url))}
    return frozenset(hosts)


def _url_hostname(url: str) -> str | None:
    """The host the HTTP client will actually connect to.

    `urlparse` treats a backslash — and its ``%5c`` encoding — as ordinary
    userinfo, so ``https://evil.example\\@trusted.example/`` parses as host
    ``trusted.example`` here, while requests/urllib3 (per the WHATWG URL rules)
    treat ``\\`` as a path separator and connect to ``evil.example``. Normalizing
    those to ``/`` before parsing keeps the retarget guard aligned with the real
    destination, so an ambiguous-authority URL can't smuggle the credential to a
    new host while appearing unchanged.
    """
    normalized = url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return urlparse(normalized).hostname


# Probe values substituted for a fan-out child's resolve placeholder to test
# whether uncontrolled parent data bound there could move the request — and the
# credential — off base_url's host. Each models a different escape technique: a
# full absolute URL (placeholder is the first/only path segment), an
# authority-only value (a literal ``scheme:`` prefix lets ``//host`` take over),
# and a bare host (placeholder sits in the authority of a ``scheme://`` prefix).
# The ``.invalid`` TLD never resolves and this is a pure string check — no I/O.
_PLACEHOLDER_ESCAPE_SENTINELS = ("https://sentinel.invalid/x", "//sentinel.invalid/x", "sentinel.invalid")


def _placeholder_escapes_base(path: str, param_name: str, base_url: str) -> bool:
    """True if binding the resolve placeholder ``{param_name}`` in ``path`` could
    move the request to a host other than ``base_url``'s.

    The placeholder is filled with uncontrolled upstream data at sync time, then
    the engine resolves the path against ``base_url`` exactly as
    :func:`resolve_request_url` does. We substitute attacker-shaped sentinels for
    the placeholder and check whether any resolves to a different host — catching
    not just a leading placeholder (``{form_id}/responses``) but a literal
    ``scheme:`` prefix that lets the bound value supply the authority
    (``https:{form_id}/responses`` with ``form_id="//attacker/x"`` resolves to the
    attacker host). A position that keeps the placeholder strictly inside the path
    (``/forms/{form_id}/responses``) leaves the host unchanged and passes.
    """
    base_host = _url_hostname(base_url)
    if not base_host:
        # A base_url with no host is rejected separately by validate_manifest_urls;
        # don't raise a confusing placeholder error for it here.
        return False
    placeholder = "{" + param_name + "}"
    for sentinel in _PLACEHOLDER_ESCAPE_SENTINELS:
        probed = path.replace(placeholder, sentinel)
        if _url_hostname(resolve_request_url(base_url, probed)) != base_host:
            return True
    return False


@SourceRegistry.register
class CustomSource(SimpleSource[CustomSourceConfig]):
    """User-defined REST API source.

    The manifest is a JSON ``RESTAPIConfig`` (same shape as the dict-based
    configs that power Intercom, Attio, Chargebee, etc.) so the existing REST
    engine in ``common/rest_source`` handles pagination, auth, JSONPath
    extraction, and incremental params with no per-source code.

    Auth credentials are stored in separate ``auth_*`` fields, not inline in
    the manifest. ``manifest_json`` holds only the non-secret structure, so the
    generic API machinery redacts the credentials from responses and carries
    them across updates with no source-specific serializer code. The full
    config is rejoined in :meth:`_assemble_manifest` before it reaches the
    REST engine.
    """

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUSTOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CUSTOM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Custom REST source",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Set up a source using custom configured mappings. "
                "Define a REST API source by providing a manifest that follows the same shape "
                "as PostHog's built-in REST sources — see the docs for the field reference."
            ),
            iconPath="/static/posthog-icon.svg",
            docsUrl=None,
            featureFlag="dwh_custom_source",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="manifest_json",
                        label="Manifest (JSON)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    # One credential is used per sync, selected by the manifest's
                    # client.auth.type. All secret so the generic API layer redacts them.
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Bearer token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="auth_api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="auth_password",
                        label="Auth password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    # OAuth2 (auth.type == "oauth2"): the customer's own client secret and,
                    # for the refresh_token grant, their pre-obtained refresh token. Both
                    # secret so the generic API layer redacts them and the re-entry gate
                    # covers them. The non-secret oauth fields (client_id / token_url / …)
                    # live in manifest_json.
                    SourceFieldInputConfig(
                        name="auth_oauth2_client_secret",
                        label="OAuth2 client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="auth_oauth2_refresh_token",
                        label="OAuth2 refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    # Non-secret pointer to a CustomOAuth2Integration row (a UUID). Server-managed: the
                    # validation seams write it when adopting the static auth_oauth2_* secrets above into
                    # a row, and the API layer drops/pins any client-supplied value. When set, the live
                    # client_secret / refresh_token / minted access token come from that row at sync time
                    # (so a rotated single-use refresh token gets persisted), and the static secrets are
                    # ignored. Declared here (despite never rendering — the Custom source UI is the
                    # manifest builder) so the config codegen keeps it on CustomSourceConfig.
                    SourceFieldInputConfig(
                        name="auth_oauth2_integration_id",
                        label="OAuth2 integration",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "The upstream API rejected the request with HTTP 401. Check that the configured auth credentials are correct.",
            "403 Client Error": "The upstream API rejected the request with HTTP 403. The configured credentials may lack the required permissions.",
            # A schema points to a resource the manifest no longer defines (renamed or removed
            # in an edit while the table's sync stayed scheduled). Permanent until the config is
            # fixed — match the stable suffix, not the variable resource name in the message.
            "not found in config": "A table in this sync points to a resource that no longer exists in the source's manifest. Re-add the resource to the manifest, or remove the table from the sync, then try again.",
            # The OAuth2 token endpoint rejected the client credentials or the grant. Both are
            # permanent until the config changes — retrying the sync can't fix them. The two
            # codes below get pointed, code-specific copy; every other permanent token failure
            # (unauthorized_client / invalid_scope / a bare 3xx redirect / a malformed token
            # response / a missing token_url) is caught by the stable marker OAuth2AuthRequestError
            # embeds whenever is_permanent is set — so no permanent token error retries until the
            # activity budget is exhausted. Transient (429 / 5xx) token errors carry no marker.
            "invalid_client": "The OAuth2 token endpoint rejected the client credentials (invalid_client). Check the configured client_id, client secret, and token URL.",
            "invalid_grant": "The OAuth2 token endpoint rejected the grant (invalid_grant) — a refresh token may have expired or been revoked. Re-enter the OAuth2 credentials.",
            OAUTH2_PERMANENT_ERROR_MARKER: "The OAuth2 token endpoint rejected the request and the configuration must change before the sync can succeed. Check the configured OAuth2 credentials, token URL, grant type, and scopes.",
        }

    def _assemble_manifest(self, config: CustomSourceConfig) -> dict[str, Any]:
        """Parse the stored manifest and rejoin it with the auth credentials.

        ``manifest_json`` holds the RESTAPIConfig structure with no credential
        values; the secrets live in separate ``auth_*`` fields so the generic
        API layer can redact them. This rebuilds the full config the REST
        engine consumes.
        """
        try:
            manifest = json.loads(config.manifest_json)
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(f"Manifest is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})")
        # Structural validation only — no resource-graph checks. This runs on
        # every sync and schema listing of already-stored manifests, so a
        # graph problem on one resource must not take down the source's other
        # schemas (graph rules are enforced on the API validation paths in
        # `validate_credentials`, and per-schema at sync time in `_fanout_chain`).
        validate_manifest_structure(manifest)
        _inject_auth_secrets(manifest, config)
        return manifest

    def validate_credentials(
        self,
        config: CustomSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        *,
        source_id: Optional[str] = None,
        owner_user_id: Optional[int] = None,
    ) -> tuple[bool, str | None]:
        try:
            manifest = self._assemble_manifest(config)
            # Graph-level fan-out rules apply on every validation path —
            # including updates that don't touch the manifest and schema-scoped
            # read checks. Builder-authored manifests are always graph-valid,
            # so a stored manifest tripping this means hand-authored JSON that
            # never synced; failing the API call with a pointed message is
            # preferable to carrying a permanent leniency mode. The returned
            # map feeds the probe's child filter below.
            resolved = _validate_resource_graph(manifest)
            _validate_incremental_configs(manifest)
        except ManifestValidationError as exc:
            return False, str(exc)

        ok, err = validate_manifest_urls(manifest, team_id)
        if not ok:
            return False, err

        # Statically-entered OAuth2 secrets are adopted into a server-managed CustomOAuth2Integration
        # row on every interactive validation, so the durable row — not job_inputs — becomes the home
        # for the client secret and the (possibly rotating) refresh token. The config is rewritten to
        # point at the row with its static secrets cleared; callers that persist the validated config
        # afterwards store the pointer instead of the raw secrets.
        try:
            _adopt_static_oauth2_secrets(manifest, config, team_id, source_id=source_id, owner_user_id=owner_user_id)
        except CustomOAuth2Integration.DoesNotExist:
            return False, OAUTH2_CREDENTIALS_GONE_MESSAGE

        # A row-backed OAuth2 source keeps its secrets in the CustomOAuth2Integration row, not in
        # job_inputs — `_assemble_manifest` deliberately skipped the static secrets for it. Mint
        # (or reuse a cached token) through the row here, exactly as sync time does, so validation has a
        # live token to probe with. `get_access_token()` persists a rotated single-use refresh token, so
        # this is the only seam that re-mints; the data probe below reuses the seeded token via
        # `OAuth2Auth.__call__` and must NOT re-mint (that would rotate without writeback — see the guard
        # on the pre-mint block). Errors mirror the pre-mint handling: a permanent token rejection blocks
        # with a pointed message; a transient one doesn't block (the first real sync retries).
        if config.auth_oauth2_integration_id:
            try:
                # Bind the integration to the source being validated, mirroring sync/preview: on update
                # (source_id given) the row must belong to that source; on create/setup (no source yet) it
                # must be unbound. Without this, the probe below could mint and send another source's token
                # to an attacker-supplied base_url.
                _inject_oauth2_integration_secrets(
                    manifest,
                    config.auth_oauth2_integration_id,
                    team_id,
                    source_id=source_id,
                    forbid_bound=source_id is None,
                    owner_user_id=owner_user_id,
                )
            except CustomOAuth2Integration.DoesNotExist:
                return False, OAUTH2_CREDENTIALS_GONE_MESSAGE
            except OAuth2AuthRequestError as exc:
                auth_config = manifest.get("client", {}).get("auth", {})
                injected_secrets = tuple(
                    str(auth_config[key])
                    for key in ("client_secret", "refresh_token", "access_token")
                    if auth_config.get(key)
                )
                if exc.is_permanent:
                    return False, _redact_secrets(
                        f"The OAuth2 token endpoint rejected the request: {strip_oauth2_permanent_marker(str(exc))}",
                        injected_secrets,
                    )
                # Transient (429 / 5xx): don't block creation — the first real sync retries the mint.
                return True, None

        # Probe a small prefix of resources so we surface auth/connection errors
        # at create-time rather than waiting for the first sync. The auth/header
        # setup comes from the shared client config, so it is built once and
        # reused across the per-resource requests.
        client = manifest["client"]
        base_url = client["base_url"]

        headers: dict[str, str] = dict(client.get("headers") or {})
        # Build the probe's auth exactly the way the REST engine will at sync
        # time (`create_auth`) instead of reconstructing it by hand — so the
        # probe and the sync agree on which credential is sent and where
        # (header / query / cookie), and a malformed auth config surfaces here
        # as a clear error rather than crashing the first sync.
        try:
            probe_auth = create_auth(client.get("auth"))
        except (ValueError, TypeError) as exc:
            return False, f"Invalid auth configuration: {exc}"

        # OAuth2 mints its access token lazily on the first request, so pre-mint it now —
        # a bad client_secret / token_url then fails with a pointed "the OAuth2 token
        # endpoint rejected the request: …" instead of a misleading "resource unreachable"
        # on the first data probe. Minting before the probe session is built also lets the
        # freshly-minted access token join that session's redaction set. A transient
        # (429 / 5xx) token error must not block creation — the first real sync retries —
        # so only a permanent error (invalid_client / invalid_grant / other 4xx) is surfaced.
        #
        # Skip this for an integration-backed source: its token was already minted+persisted above
        # (via the row's writeback-safe path) and seeded into the manifest. Re-minting on this
        # throwaway `probe_auth` would rotate the single-use refresh token WITHOUT persisting it,
        # orphaning the row on a consumed token. The seeded token reaches the probe through
        # `OAuth2Auth.__call__`, which doesn't re-mint a still-valid token.
        if isinstance(probe_auth, OAuth2Auth) and not config.auth_oauth2_integration_id:
            try:
                # Bound the inline token exchange to the same budget as the data probe — this runs
                # on the API request thread, so a stalled token endpoint must fail fast (well within
                # the request's idle timeout) rather than block for the generous sync-time read.
                probe_auth._obtain_token(timeout=(PROBE_CONNECT_TIMEOUT, PROBE_READ_TIMEOUT))
            except OAuth2AuthRequestError as exc:
                if exc.is_permanent:
                    # Strip the internal sync-time classifier marker — it's not user-facing copy.
                    return False, _redact_secrets(
                        f"The OAuth2 token endpoint rejected the request: {strip_oauth2_permanent_marker(str(exc))}",
                        auth_secret_values(probe_auth),
                    )
                # Transient (429 / 5xx): don't block creation — the first real sync retries the
                # token exchange. Skip the data probe too: it has no minted token to authenticate
                # with, so requests would re-invoke the auth (re-running the failing mint) and turn
                # this into a misleading "could not reach <data resource>" failure.
                return True, None
            except Exception as exc:
                # Redact the credential defensively — a transport-layer exception shouldn't carry
                # the secret, but the redaction discipline is cheap and uniform here.
                return False, _redact_secrets(
                    f"Could not reach the OAuth2 token endpoint: {exc}", auth_secret_values(probe_auth)
                )

        # The probe runs inline on the request thread, so keep it cheap and
        # bounded: no retries (don't multiply outbound volume at create time),
        # no redirects (Smokescreen re-resolves each hop; keep the credential
        # pinned to the validated host), and credential values registered for
        # redaction even when injected under a manifest-chosen param/header name
        # the denylist scrubber can't anticipate.
        session = make_tracked_session(
            headers=headers,
            redact_values=auth_secret_values(probe_auth),
            retry=Retry(total=0),
            allow_redirects=False,
        )

        # Fan-out child resources bind a parent row's field into their path
        # (`/forms/{form_id}/responses`), so they can't be reached without first
        # fetching a parent — skip them. Auth is shared across resources, so the
        # top-level resources still validate the credential. The engine's own
        # dependency map (not a local copy of its resolve-param detection) tells
        # us which resources are children.
        probeable = [resource for resource in manifest["resources"] if resolved.get(resource.get("name")) is None]
        for resource in probeable[:PROBE_MAX_RESOURCES]:
            endpoint = resource.get("endpoint", {})
            method = (endpoint.get("method") or "GET").upper()
            path = endpoint.get("path", "")
            # Resolve via the shared helper so the probe hits the same host the sync will.
            url = resolve_request_url(base_url, path)
            # Replay the configured query params and request body so the probe
            # matches what the sync sends — an endpoint that needs them shouldn't
            # answer differently at probe vs sync time.
            probe_params = _static_probe_params(endpoint.get("params"))
            probe_json = endpoint.get("json")
            try:
                # stream=True so the body isn't buffered into memory; only a 401/403
                # snippet is read below, and the response is always closed.
                response = session.request(
                    method,
                    url,
                    params=probe_params or None,
                    json=probe_json,
                    auth=probe_auth,
                    timeout=(PROBE_CONNECT_TIMEOUT, PROBE_READ_TIMEOUT),
                    stream=True,
                )
            except Timeout:
                # str(exc) here is the raw urllib3 "HTTPSConnectionPool(...): Read timed out" dump,
                # which isn't actionable — surface the configured timeouts instead.
                return False, (
                    f"Resource {resource['name']!r}: timed out reaching {url} "
                    f"(connect timeout {PROBE_CONNECT_TIMEOUT}s, read timeout {PROBE_READ_TIMEOUT}s). "
                    "The endpoint may be slow or temporarily unreachable — check the URL and try again."
                )
            except Exception:
                return False, (
                    f"Resource {resource['name']!r}: could not reach {url}. "
                    "Check that the URL is correct and the endpoint is reachable."
                )

            # Only an auth rejection (401/403) is a credential problem. Other
            # statuses — 404 (resource not yet provisioned), 405, 429 (rate
            # limited during the probe burst), 5xx — are not credential errors
            # and must not block source creation; a real, persistent failure
            # surfaces on the first sync instead.
            try:
                if response.status_code in (401, 403):
                    message = (
                        f"Resource {resource['name']!r}: the upstream API rejected the request with "
                        f"HTTP {response.status_code} from {url} — check the configured auth credentials."
                    )
                    # Redact the credential from the echoed body before surfacing it: an upstream
                    # could reflect the sent credential (e.g. an OAuth2 bearer token minted above) in
                    # its 401/403 error, and the snippet would otherwise leak it into a user message.
                    snippet = _redact_secrets(_read_capped_text(response), auth_secret_values(probe_auth))
                    if snippet:
                        message += f" The upstream responded: {snippet}"
                    return False, message
            finally:
                response.close()

        return True, None

    def get_schemas(
        self,
        config: CustomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        manifest = self._assemble_manifest(config)

        ok, err = validate_manifest_urls(manifest, team_id)
        if not ok:
            raise ManifestValidationError(err or "Manifest URL validation failed")

        schemas: list[SourceSchema] = []
        for resource in manifest["resources"]:
            assert isinstance(resource, dict)
            schemas.append(_schema_from_resource(resource))

        if names is not None:
            wanted = set(names)
            schemas = [schema for schema in schemas if schema.name in wanted]
        return schemas

    def source_for_pipeline(self, config: CustomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        try:
            manifest = self._assemble_manifest(config)
            # A model-backed OAuth2 source loads its live secrets + minted token from the
            # CustomOAuth2Integration row here (sync time, DB-capable), which also writes back a rotated
            # refresh token. _assemble_manifest already skipped the static job_inputs secrets for it.
            if config.auth_oauth2_integration_id:
                # Bind the integration to the syncing source so it can't inject another source's tokens.
                _inject_oauth2_integration_secrets(
                    manifest, config.auth_oauth2_integration_id, inputs.team_id, source_id=inputs.source_id
                )
            ok, err = validate_manifest_urls(manifest, inputs.team_id)
            if not ok:
                raise ManifestValidationError(err or "Manifest URL validation failed")

            # The resources to run for this schema: the chosen resource plus,
            # when it's a fan-out child, its ancestor chain (root first) — see
            # `_fanout_chain` for the full rationale. Ancestors are stripped of
            # incremental config so the run's high-watermark — which belongs to
            # the chosen resource — can't be misapplied to a parent and silently
            # drop parent rows (and with them their children); they full-scan
            # every run, matching the built-in fan-out sources (Typeform/Sentry).
            chain = _fanout_chain(manifest, inputs.schema_name)
            chosen = chain.child
            engine_resources = [
                *(_without_incremental_config(r) for r in chain.ancestors),
                _strip_engine_unsupported_incremental_keys(chain.child),
            ]
            engine_manifest = cast(RESTAPIConfig, {**manifest, "resources": engine_resources})

            # The engine serializes a datetime watermark via str() (space-separated),
            # which strict APIs reject — format it to the declared wire format first.
            last_value = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            last_value = _format_incremental_cursor(last_value, chosen)

            # Inside the try block: the engine raises deterministic ValueErrors at
            # build time for config problems the create-time checks can't see
            # (e.g. `include_from_parent` on a resource with no resolve param).
            resources = rest_api_resources(
                engine_manifest,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                db_incremental_field_last_value=last_value,
            )
        except CustomOAuth2Integration.DoesNotExist as exc:
            # The manifest points at an OAuth2 integration row that no longer resolves for this
            # team (deleted, wrong team, or a dangling auth_oauth2_integration_id). It's a permanent
            # config error — the row won't reappear on a retry — but it's neither a ValueError nor a
            # message the substring classifier recognises, so without this it would retry until the
            # activity budget is exhausted. Fail fast like the other deterministic config errors.
            raise NonRetryableException(
                "The stored OAuth2 credentials this source points to no longer exist. "
                "Re-enter the client secret and refresh token in the source settings, then try again."
            ) from exc
        except ValueError as exc:
            # A malformed manifest, a missing resource, or a broken parent
            # reference is a permanent, deterministic failure — retrying the sync
            # cannot fix it. Raise NonRetryableException (the only type Temporal
            # treats as non-retryable for this activity) so the job fails fast
            # instead of burning the whole retry budget on an error that will
            # always recur.
            raise NonRetryableException(str(exc)) from exc

        resource = next((r for r in resources if getattr(r, "name", None) == inputs.schema_name), None)
        if resource is None:
            raise NonRetryableException(f"Resource {inputs.schema_name!r} was not produced by the REST engine")

        primary_key = chosen.get("primary_key")
        primary_keys: list[str] | None
        if isinstance(primary_key, list):
            primary_keys = [str(key) for key in primary_key]
        elif isinstance(primary_key, str):
            primary_keys = [primary_key]
        else:
            primary_keys = None

        # The manifest declares the upstream's row ordering; default "asc" to
        # match PostHog's other REST sources. An incorrect "asc" assumption on a
        # non-ascending API can skip rows on a resumed incremental sync.
        #
        # "desc" only defers committing the high-watermark until the run finishes
        # (so a partial run can't advance the cursor past rows it never reached on
        # the next scheduled sync). It does NOT make a single run resumable: the
        # generic REST engine has no earliest-value sweep, so an interrupted "desc"
        # run restarts from the newest page rather than continuing older rows. This
        # is deliberately non-resumable — duplicate work is collapsed by
        # primary_keys, and the only failure mode is an endpoint too large to
        # finish within one worker window. A proper fix would slice the cursor into
        # windows with per-window state (cf. Airbyte's DatetimeBasedCursor), which
        # the generic engine doesn't support today.
        #
        # Fan-out children always get the deferred-commit ("desc") behavior: their
        # rows arrive grouped per parent, never globally cursor-ascending, so an
        # "asc" per-batch commit after an interruption would set the watermark past
        # later parents' older rows and permanently skip them.
        sort_mode: SortMode = "desc" if (chain.is_fanout_child or chosen.get("sort_mode") == "desc") else "asc"

        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: resource,
            primary_keys=primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="md5",
            sort_mode=sort_mode,
        )

    def preview_resource(
        self,
        config: CustomSourceConfig,
        team_id: int,
        resource_name: str,
        max_rows: int = PREVIEW_DEFAULT_ROWS,
        *,
        owner_user_id: Optional[int] = None,
    ) -> "PreviewResult":
        """Fetch a bounded first page of rows for one manifest resource.

        Lets a manifest author verify ``data_selector`` / ``primary_key`` /
        ``cursor_path`` against live rows before creating a source. Reuses the
        sync path's manifest assembly, SSRF host validation, fan-out chain, and
        REST engine, but: pins every resource to a single page, strips all
        incremental config (preview is an unconditional first read, so the
        returned rows still carry the cursor field for inspection), and injects
        a no-redirect, timeout-bounded session so the inline read can't hang.
        Iterating the lazy engine resource and stopping at ``max_rows`` bounds a
        fan-out child's per-parent request volume.

        Structural / graph / URL problems raise ``ManifestValidationError`` or
        ``ValueError`` (the API turns these into 400s); a live fetch failure is
        returned in ``error`` so the caller can iterate. The assembled manifest
        carries the injected credential and is never returned — only rows.
        """
        max_rows = max(1, min(max_rows, PREVIEW_MAX_ROWS))

        manifest = self._assemble_manifest(config)
        _validate_resource_graph(manifest)
        _validate_incremental_configs(manifest)

        ok, err = validate_manifest_urls(manifest, team_id)
        if not ok:
            raise ManifestValidationError(err or "Manifest URL validation failed")

        # Preview is often the first server-side touch of freshly-typed OAuth2 secrets — adopt them
        # into a (still unbound) integration row before minting, so a provider that rotates single-use
        # refresh tokens rotates against a persisted row rather than a throwaway in-memory auth. The
        # source-create that follows reuses the same row via _reusable_unbound_integration.
        try:
            _adopt_static_oauth2_secrets(manifest, config, team_id, source_id=None, owner_user_id=owner_user_id)
        except CustomOAuth2Integration.DoesNotExist as exc:
            raise ManifestValidationError(OAUTH2_CREDENTIALS_GONE_MESSAGE) from exc

        # Row-backed OAuth2 source: seed the manifest with the row's live secrets + minted token
        # (mint-or-reuse, persisting any rotation) so the preview's lazy first-request mint reuses the
        # seeded token instead of re-minting on the throwaway preview auth — which would rotate the
        # single-use refresh token without writing it back. Same seam as sync time / validate_credentials.
        if config.auth_oauth2_integration_id:
            try:
                # Preview runs before the source exists, so the integration must not already back another
                # source — otherwise a preview could read another source's data with its tokens.
                _inject_oauth2_integration_secrets(
                    manifest, config.auth_oauth2_integration_id, team_id, forbid_bound=True, owner_user_id=owner_user_id
                )
            except CustomOAuth2Integration.DoesNotExist as exc:
                raise ManifestValidationError(OAUTH2_CREDENTIALS_GONE_MESSAGE) from exc
            except OAuth2AuthRequestError as exc:
                # The mint is a live network call, so a token-endpoint failure here is a fetch-style
                # error, not a config error — surface it the same way a row-read failure would be, with
                # the injected secrets redacted out of the message.
                auth_config = manifest.get("client", {}).get("auth", {})
                injected_secrets = tuple(
                    str(auth_config[key])
                    for key in ("client_secret", "refresh_token", "access_token")
                    if auth_config.get(key)
                )
                return PreviewResult(
                    rows=[],
                    row_count=0,
                    columns=[],
                    error=_redact_secrets(strip_oauth2_permanent_marker(str(exc)), injected_secrets),
                )

        chain = _fanout_chain(manifest, resource_name)

        client = manifest["client"]
        try:
            preview_auth = create_auth(client.get("auth"))
        except (ValueError, TypeError) as exc:
            raise ManifestValidationError(f"Invalid auth configuration: {exc}") from exc
        secret_values = auth_secret_values(preview_auth)

        engine_resources = [
            _with_single_page_paginator(_without_incremental_config(resource))
            for resource in (*chain.ancestors, chain.child)
        ]
        engine_manifest = cast(
            RESTAPIConfig,
            {
                **manifest,
                "resources": engine_resources,
                "client": {
                    **client,
                    "session": _build_preview_session(secret_values),
                    # One attempt only — a rate-limited endpoint must surface an error
                    # inline, not sleep on `Retry-After` and tie up the request thread.
                    "max_retries": 1,
                },
            },
        )

        try:
            resources = rest_api_resources(
                engine_manifest,
                team_id=team_id,
                job_id="custom-source-preview",
                db_incremental_field_last_value=None,
            )
        except ValueError as exc:
            # Deterministic build-time config errors the create-time checks can't
            # see (e.g. include_from_parent on a resource with no resolve param).
            raise ManifestValidationError(str(exc)) from exc

        # Cap how many parent rows each fan-out ancestor emits. The engine issues one
        # child request per parent row, and empty child pages are dropped before the
        # row reader sees them — so the request bound has to live on the parent, not on
        # pages collected downstream.
        ancestor_names = {ancestor["name"] for ancestor in chain.ancestors}
        for engine_resource in resources:
            if getattr(engine_resource, "name", None) in ancestor_names:
                engine_resource.add_filter(_keep_first_n(PREVIEW_MAX_FANOUT_PARENTS))

        resource = next((r for r in resources if getattr(r, "name", None) == resource_name), None)
        if resource is None:
            raise ManifestValidationError(f"Resource {resource_name!r} was not produced by the REST engine")

        try:
            rows = _collect_preview_rows(resource, max_rows)
        except Exception as exc:
            return PreviewResult(
                rows=[],
                row_count=0,
                columns=[],
                error=_redact_secrets(strip_oauth2_permanent_marker(str(exc)), secret_values),
            )

        return PreviewResult(rows=rows, row_count=len(rows), columns=_infer_columns(rows), error=None)


class PreviewResult(NamedTuple):
    """Outcome of a single-resource preview read. ``error`` is set only for a
    live fetch failure — structural problems raise instead."""

    rows: list[dict[str, Any]]
    row_count: int
    columns: list[dict[str, str]]
    error: str | None


class PreviewResponseTooLargeError(Exception):
    """A preview's cumulative response bytes exceeded ``PREVIEW_MAX_TOTAL_BODY_BYTES``."""


class _PreviewSession(_NoRedirectSession):
    """No-redirect session for the inline preview read, bounded on time and size.

    Pins a session-level timeout (``RESTClient.send()`` passes none, so a stalled
    upstream can't hang the request thread) and caps the response bytes parsed via a
    budget shared across the preview — one session serves one preview. See
    ``_read_within_budget`` for the size enforcement.
    """

    def __init__(self) -> None:
        super().__init__()
        self._body_budget = PREVIEW_MAX_TOTAL_BODY_BYTES

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", (PROBE_CONNECT_TIMEOUT, PROBE_READ_TIMEOUT))
        kwargs["stream"] = True
        response = super().send(request, **kwargs)
        try:
            body = self._read_within_budget(response)
        finally:
            response.close()
        response._content = body
        response._content_consumed = True  # type: ignore[attr-defined]
        return response

    def _read_within_budget(self, response: Response) -> bytes:
        # Stream *decoded* chunks and stop the instant the running total crosses the
        # budget. A single read(decode_content=True) would inflate the whole compressed
        # body at once — a gzipped page decompresses fully before any size check — so a
        # bomb is bounded only by decoding incrementally and aborting early.
        chunks: list[bytes] = []
        decoded = 0
        for chunk in response.raw.stream(PREVIEW_READ_CHUNK_BYTES, decode_content=True):
            decoded += len(chunk)
            if decoded > self._body_budget:
                raise PreviewResponseTooLargeError(
                    f"Preview response bodies exceeded the {PREVIEW_MAX_TOTAL_BODY_BYTES}-byte budget"
                )
            chunks.append(chunk)
        self._body_budget -= decoded
        return b"".join(chunks)


def _build_preview_session(redact_values: tuple[str, ...]) -> _PreviewSession:
    """A tracked preview session: no transport retries, credentials registered
    for value-based redaction (auth may be injected under a manifest-chosen
    param/header the denylist can't anticipate)."""
    session = _PreviewSession()
    adapter = make_tracked_adapter(retry=Retry(total=0), redact_values=redact_values)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _with_single_page_paginator(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``resource`` pinned to a single page, so a preview reads
    exactly one page per resource regardless of the manifest's paginator."""
    endpoint = resource.get("endpoint")
    if isinstance(endpoint, str):
        endpoint = {"path": endpoint}
    elif not isinstance(endpoint, dict):
        endpoint = {}
    return {**resource, "endpoint": {**endpoint, "paginator": {"type": "single_page"}}}


def _keep_first_n(n: int) -> Callable[[dict[str, Any]], bool]:
    """A stateful filter that keeps the first ``n`` rows and drops the rest.

    Applied to a fan-out ancestor so the child fans out over at most ``n`` parent
    rows — the request bound the row reader can't enforce, since empty child pages
    never reach it.
    """
    seen = 0

    def keep(_row: dict[str, Any]) -> bool:
        nonlocal seen
        if seen >= n:
            return False
        seen += 1
        return True

    return keep


def _collect_preview_rows(resource: Any, max_rows: int) -> list[dict[str, Any]]:
    """Flatten the engine resource's pages into at most ``max_rows`` records.

    Iterating a :class:`Resource` yields pages (``list[dict]``) lazily, so
    returning early abandons the generator and stops it issuing further requests.
    A fan-out child's request volume is bounded upstream by capping its parent
    rows (see ``preview_resource``); a single-page top-level resource issues one
    request regardless.
    """
    rows: list[dict[str, Any]] = []
    for page in resource:
        for item in page:
            if isinstance(item, dict):
                rows.append(item)
                if len(rows) >= max_rows:
                    return rows
    return rows


def _json_type_label(value: Any) -> str:
    # bool is a subclass of int, so it must be checked first.
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _infer_columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Advisory column list for the previewed rows — each key seen (first-seen
    order), typed from the first non-null value. Helps the caller sanity-check
    data_selector / primary_key / cursor_path against real data."""
    columns: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            if key not in columns or columns[key] == "null":
                columns[key] = _json_type_label(value)
    return [{"name": name, "type": type_label} for name, type_label in columns.items()]


def _redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    # Redact the raw secret and its URL-encoded forms: a key in a query param is
    # percent-encoded in `response.url`, which an HTTPError carries verbatim.
    for secret in secrets:
        if not secret:
            continue
        for variant in dict.fromkeys((secret, quote(secret, safe=""), quote_plus(secret))):
            text = text.replace(variant, "***")
    return text


def _read_capped_text(response: Response) -> str:
    """Read at most ``PROBE_ERROR_SNIPPET_BYTES`` of a streamed body for an error snippet.

    The probe opens responses with ``stream=True`` and never ingests the body, so a
    bounded slice keeps a large or hostile upstream response from being materialized
    into worker memory. Reads the raw stream directly (rather than ``response.text``,
    which buffers and decompresses the whole body).

    ``decode_content=False`` is deliberate: it reads exactly ``PROBE_ERROR_SNIPPET_BYTES``
    raw bytes and never inflates a ``Content-Encoding: gzip`` body, so a decompression
    bomb can't expand a tiny read into megabytes. The flip side is that a compressed or
    otherwise non-text body would decode to binary garbage, so it is omitted from the
    snippet rather than echoed into a user-facing error.
    """
    # ``identity`` means "no transformation", so its body is plain bytes worth surfacing;
    # any other encoding (gzip, br, …) would decode to garbage, so omit the snippet.
    if response.headers.get("Content-Encoding", "").lower() not in ("", "identity"):
        return ""
    try:
        raw = response.raw.read(PROBE_ERROR_SNIPPET_BYTES, decode_content=False)
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="replace")
    # A replacement char means the bytes weren't valid UTF-8 — a binary or still-encoded
    # body — so drop it rather than surface garbage to the user.
    if "�" in text:
        return ""
    return text.strip()


def _static_probe_params(params: Any) -> dict[str, Any]:
    """The literal query params safe to replay in the create-time probe.

    A RESTAPIConfig ``params`` map can hold the engine's incremental / parent-
    resolver specs (dict values) that are only resolved against cursor or parent
    state at sync time — the probe has neither, so it forwards just the plain
    (non-dict) values and lets the engine handle the rest on the first sync.
    """
    if not isinstance(params, dict):
        return {}
    return {key: value for key, value in params.items() if not isinstance(value, dict)}


def _inject_auth_secrets(manifest: dict[str, Any], config: CustomSourceConfig) -> None:
    """Inject credential values from the secret config fields into ``client.auth``.

    Mutates ``manifest`` in place. Which field is used is selected by the
    manifest's declared ``client.auth.type``; an absent/empty value is left
    alone so the upstream probe surfaces the missing-credential error.
    """
    client = manifest.get("client")
    if not isinstance(client, dict):
        return
    auth = client.get("auth")
    if not isinstance(auth, dict):
        return

    auth_type = auth.get("type")
    if auth_type == "bearer" and config.auth_token:
        auth["token"] = config.auth_token
    elif auth_type == "api_key" and config.auth_api_key:
        auth["api_key"] = config.auth_api_key
    elif auth_type == "http_basic" and config.auth_password:
        auth["password"] = config.auth_password
    elif auth_type == "oauth2":
        # A model-backed source (auth_oauth2_integration_id set) gets its live secrets + minted token
        # from the CustomOAuth2Integration row at sync time (see _inject_oauth2_integration_secrets),
        # so skip the static job_inputs secrets entirely — they aren't the source of truth here.
        if config.auth_oauth2_integration_id:
            return
        # The non-secret oauth fields (client_id / token_url / grant_type / knobs) are
        # already in the manifest; inject only the secrets. client_credentials needs just
        # the client_secret; the refresh_token grant also needs the refresh token.
        if config.auth_oauth2_client_secret:
            auth["client_secret"] = config.auth_oauth2_client_secret
        if config.auth_oauth2_refresh_token:
            auth["refresh_token"] = config.auth_oauth2_refresh_token


# The exact non-secret OAuth2Auth knobs a manifest's `client.auth` may declare — the schema of a
# CustomOAuth2Integration row's `config` (plus the worker-written `refreshed_at`).
_OAUTH2_ROW_CONFIG_KEYS = (
    "client_id",
    "token_url",
    "grant_type",
    "scopes",
    "access_token_name",
    "expires_in_name",
    "expiry_date_format",
    "extra_token_request_params",
    "token_request_headers",
    "client_auth_method",
)

# User-facing copy for a row-backed source whose integration row no longer resolves. Recovery is
# always the same: re-enter the client secret / refresh token in the source's settings, which adopts
# them into a fresh row.
OAUTH2_CREDENTIALS_GONE_MESSAGE = (
    "This source's stored OAuth2 credentials are no longer available. "
    "Re-enter the client secret and refresh token in the source settings to reconnect."
)


def _oauth2_row_config(auth: dict[str, Any]) -> dict[str, Any]:
    """The non-secret OAuth2 client config a manifest declares, in row-`config` shape.

    The grant is normalized to its default so row matching doesn't split on an
    implied-vs-explicit ``client_credentials``.
    """
    row_config = {key: auth[key] for key in _OAUTH2_ROW_CONFIG_KEYS if auth.get(key) not in (None, "")}
    row_config["grant_type"] = auth.get("grant_type") or "client_credentials"
    return row_config


def _reusable_unbound_integration(
    team_id: int, owner_user_id: int, row_config: dict[str, Any]
) -> Optional[CustomOAuth2Integration]:
    """The caller's own unbound integration row for the same OAuth2 client, if one exists.

    An unbound row is left behind by a preview or a failed create attempt — and may hold a rotated
    refresh token the user never saw, which is exactly why it must be reused rather than recreated:
    for providers that rotate single-use refresh tokens, the row's token is the only live descendant
    of the one the user typed. Newest first so retries converge on the most recently touched row.
    """
    candidates = (
        CustomOAuth2Integration.objects.for_team(team_id)
        .filter(external_data_source__isnull=True, created_by_id=owner_user_id)
        .order_by("-created_at")
    )
    for candidate in candidates:
        if all(candidate.config.get(key) == row_config.get(key) for key in ("client_id", "token_url", "grant_type")):
            return candidate
    return None


def _apply_oauth2_material(
    integration: CustomOAuth2Integration, row_config: dict[str, Any], config: CustomSourceConfig
) -> None:
    """Sync the manifest's non-secret OAuth2 config and any re-entered secrets onto the row.

    A re-entered refresh token only replaces the stored one when it differs from the last token the
    user submitted (tracked by fingerprint) *and* the non-secret client config is unchanged:
    re-typing the original token — already consumed by a rotating provider — must not clobber the
    rotated descendant the row persisted across a retry or preview→create. But once the config
    changes (a repointed token_url above all), the keep-rule must not apply: it would mint the live
    rotated token — a credential the editor never possessed — against the new destination. Replacing
    with the typed token means a config change only ever sends material the editor provably knows.
    A replacement (or a config change) drops the cached access token so the next mint uses the new
    material instead of riding a token minted under the old one.
    """
    sensitive = dict(integration.sensitive_config)
    new_config = dict(row_config)
    if "refreshed_at" in integration.config:
        new_config["refreshed_at"] = integration.config["refreshed_at"]
    config_changed = new_config != integration.config
    if config_changed:
        sensitive.pop("access_token", None)
        sensitive.pop("token_expiry", None)
    if config.auth_oauth2_client_secret:
        sensitive["client_secret"] = config.auth_oauth2_client_secret
    if config.auth_oauth2_refresh_token:
        fingerprint = hashlib.sha256(config.auth_oauth2_refresh_token.encode()).hexdigest()
        if config_changed or fingerprint != sensitive.get("refresh_token_fingerprint"):
            sensitive["refresh_token"] = config.auth_oauth2_refresh_token
            sensitive["refresh_token_fingerprint"] = fingerprint
            sensitive.pop("access_token", None)
            sensitive.pop("token_expiry", None)
    if config_changed or sensitive != integration.sensitive_config:
        integration.config = new_config
        integration.sensitive_config = sensitive
        integration.save(update_fields=["config", "sensitive_config"])


def _adopt_static_oauth2_secrets(
    manifest: dict[str, Any],
    config: CustomSourceConfig,
    team_id: int,
    *,
    source_id: Optional[str],
    owner_user_id: Optional[int],
) -> None:
    """Move statically-entered OAuth2 secrets into a server-managed CustomOAuth2Integration row.

    The custom source config screen only ever collects the non-secret client config (in the manifest)
    plus the client secret / refresh token as static secret fields; the durable integration row is an
    implementation detail created here, with no user-facing API. Runs only on interactive request
    seams (``owner_user_id`` set): create/update validation, schema discovery, and preview. Mutates
    ``config`` — pointing it at the row and clearing the static secrets — and scrubs the secrets from
    the assembled ``manifest``, so a caller that persists the config afterwards stores a secret-free
    ``job_inputs``.

    * No row linked yet: reuse the caller's unbound row for the same client (see
      :func:`_reusable_unbound_integration`), else create one.
    * Row already linked (``config.auth_oauth2_integration_id``): authorize it for this source first —
      an unauthorized caller must not be able to rewrite another source's row config — then refresh
      its non-secret config from the manifest and rotate in any re-entered secrets (the reconnect
      path).

    Raises ``CustomOAuth2Integration.DoesNotExist`` when the linked row is not usable by this
    source/owner, or when it is gone and no re-entered secrets are available to rebuild it from.
    """
    if owner_user_id is None:
        return
    client = manifest.get("client")
    if not isinstance(client, dict):
        return
    auth = client.get("auth")
    if not isinstance(auth, dict) or auth.get("type") != "oauth2":
        return
    has_static_secrets = bool(config.auth_oauth2_client_secret or config.auth_oauth2_refresh_token)
    if not config.auth_oauth2_integration_id and not has_static_secrets:
        return

    row_config = _oauth2_row_config(auth)
    integration: Optional[CustomOAuth2Integration] = None
    if config.auth_oauth2_integration_id:
        try:
            integration = get_custom_oauth2_integration(config.auth_oauth2_integration_id, team_id)
        except CustomOAuth2Integration.DoesNotExist:
            # Dangling pointer (row deleted). Re-entered secrets are the recovery path: fall through
            # and adopt them into a fresh row instead of leaving the source stuck on a dead pointer.
            if not has_static_secrets:
                raise
        if integration is not None:
            _authorize_integration_for_source(
                integration, team_id, source_id=source_id, forbid_bound=source_id is None, owner_user_id=owner_user_id
            )
    if integration is None:
        integration = _reusable_unbound_integration(team_id, owner_user_id, row_config) or (
            CustomOAuth2Integration.objects.for_team(team_id).create(
                team_id=team_id, created_by_id=owner_user_id, config=row_config
            )
        )
    _apply_oauth2_material(integration, row_config, config)

    config.auth_oauth2_integration_id = str(integration.id)
    config.auth_oauth2_client_secret = None
    config.auth_oauth2_refresh_token = None
    # The static secrets were already copied into the manifest by _inject_auth_secrets — scrub them so
    # only the row-minted token (seeded by _inject_oauth2_integration_secrets) ever reaches the engine.
    auth.pop("client_secret", None)
    auth.pop("refresh_token", None)


def _authorize_integration_for_source(
    integration: CustomOAuth2Integration,
    team_id: int,
    *,
    source_id: Optional[str],
    forbid_bound: bool,
    owner_user_id: Optional[int] = None,
) -> None:
    """Fail closed unless ``integration`` belongs to — or is owned by the user setting up — the source
    about to use its secrets.

    Scoping the lookup by ``team_id`` alone lets any source in a team adopt another source's integration
    UUID and exfiltrate its OAuth client secret + tokens. Binding the row to its source closes that:

    * sync (``source_id`` set): the row must already belong to this source. An unbound row is claimed for
      it on first use (trust-on-first-use), so no second source can adopt it afterwards; a row bound to a
      different source is rejected.
    * preview/create (``forbid_bound``): there's no source yet, so the row must be unbound — it can't
      already be backing another source.

    An unbound row is a floating credential, so a request-context caller (``owner_user_id`` set) may only
    consume one it created — otherwise a teammate could adopt someone else's not-yet-bound integration.
    At sync there's no acting user; the source already passed this same owner check at create/update, so
    the first-use claim is safe.

    Rejection raises ``CustomOAuth2Integration.DoesNotExist`` so each caller's existing "integration no
    longer exists" handling turns it into the right non-retryable / 400 response.
    """
    foreign_unbound = owner_user_id is not None and integration.created_by_id != owner_user_id
    bound_source_id = integration.external_data_source_id
    if source_id is not None:
        if bound_source_id is None:
            if foreign_unbound:
                raise CustomOAuth2Integration.DoesNotExist("OAuth2 integration is not available for this source.")
            # Atomically claim the unbound row for this source. A guarded UPDATE (not a save) loses the
            # race cleanly if another source's first sync claims it first, and an IntegrityError means the
            # source already has a different integration bound — both fall through to the match check below,
            # which fails closed.
            try:
                claimed = (
                    CustomOAuth2Integration.objects.for_team(team_id)
                    .filter(pk=integration.pk, external_data_source__isnull=True)
                    .update(external_data_source_id=source_id)
                )
            except IntegrityError:
                claimed = 0
            if claimed:
                integration.external_data_source_id = source_id  # keep the in-memory row consistent
                return
            bound_source_id = (
                CustomOAuth2Integration.objects.for_team(team_id)
                .values_list("external_data_source_id", flat=True)
                .get(pk=integration.pk)
            )
        if str(bound_source_id) != str(source_id):
            raise CustomOAuth2Integration.DoesNotExist("OAuth2 integration is not bound to this source.")
    elif forbid_bound:
        if bound_source_id is not None:
            raise CustomOAuth2Integration.DoesNotExist("OAuth2 integration is already bound to another source.")
        if foreign_unbound:
            raise CustomOAuth2Integration.DoesNotExist("OAuth2 integration is not available for this source.")


def _inject_oauth2_integration_secrets(
    manifest: dict[str, Any],
    integration_id: str,
    team_id: int,
    *,
    source_id: Optional[str] = None,
    forbid_bound: bool = False,
    owner_user_id: Optional[int] = None,
) -> None:
    """Inject a model-backed OAuth2 source's minted access token into ``client.auth`` as a static bearer.

    Mutates ``manifest`` in place. Runs at sync, create-time validation, and preview — all DB-capable
    seams where ``team_id`` is known — never on the schema-listing manifest assembly. ``get_access_token()``
    mints + persists up front (under a row lock), so this is the seam where a rotating provider's new
    single-use refresh token gets written back before the next sync would reuse the consumed one.

    Only the minted access token is seeded — never the refresh_token/client_secret — and
    ``manages_own_token=False`` tells the REST engine to send it without ever minting. A mid-sync re-mint
    would consume a single-use refresh token whose rotation the engine can't persist; instead an expired
    token surfaces as a retryable 401 and the retry re-mints up front through the row.

    ``source_id`` / ``forbid_bound`` bind the integration to the source using it; see
    ``_authorize_integration_for_source``.
    """
    client = manifest.get("client")
    if not isinstance(client, dict):
        return
    auth = client.get("auth")
    if not isinstance(auth, dict) or auth.get("type") != "oauth2":
        return
    integration = get_custom_oauth2_integration(integration_id, team_id)
    _authorize_integration_for_source(
        integration, team_id, source_id=source_id, forbid_bound=forbid_bound, owner_user_id=owner_user_id
    )
    integration.get_access_token()
    auth["access_token"] = integration.sensitive_config.get("access_token")
    auth["manages_own_token"] = False
    # Strip any minting material so the engine structurally cannot re-mint mid-sync (belt-and-suspenders
    # to manages_own_token=False): the row is the only place a single-use refresh token may be rotated +
    # persisted.
    auth.pop("client_secret", None)
    auth.pop("refresh_token", None)


def _incremental_field_type(raw: Any) -> IncrementalFieldType:
    """Map a manifest-declared cursor type to an :class:`IncrementalFieldType`.

    Defaults to ``DateTime`` — the common case for REST cursors — but a manifest
    can declare ``cursor_type`` (``integer``, ``date``, ``timestamp``, …) so an
    integer or string cursor is stored and compared with the right type rather
    than being misinterpreted as a timestamp.
    """
    if isinstance(raw, str):
        try:
            return IncrementalFieldType(raw.strip().lower())
        except ValueError:
            pass
    return IncrementalFieldType.DateTime


# Keys the Custom source understands on ``endpoint.incremental`` that the generic
# REST engine's ``Incremental(**config)`` constructor does NOT accept. They must be
# removed before the engine builds its incremental tracker, or it raises an
# unexpected keyword-argument error at sync setup.
_ENGINE_UNSUPPORTED_INCREMENTAL_KEYS = frozenset({"cursor_type", "datetime_format"})


def _format_incremental_cursor(value: Any, chosen: dict[str, Any]) -> Any:
    """Render a datetime/date high-watermark as a string for the REST engine.

    The engine binds the watermark via ``str()``, whose space-separated datetime
    rendering strict APIs (e.g. Typeform) reject. The resource's
    ``endpoint.incremental.datetime_format`` strftime pattern controls the wire
    format, defaulting to ISO-8601; non-datetime cursors pass through untouched.

    A non-string ``datetime_format`` raises ``ManifestValidationError`` (non-retryable)
    instead of strftime's ``TypeError``, which Temporal would retry — a backstop for
    manifests stored before ``_validate_incremental_configs`` existed.
    """
    # `datetime` is a subclass of `date`, so this matches both.
    if not isinstance(value, date):
        return value
    endpoint = chosen.get("endpoint")
    incremental = endpoint.get("incremental") if isinstance(endpoint, dict) else None
    datetime_format = incremental.get("datetime_format") if isinstance(incremental, dict) else None
    if datetime_format is not None and not isinstance(datetime_format, str):
        raise ManifestValidationError(
            f"Resource {chosen.get('name')!r}: endpoint.incremental.datetime_format must be a string "
            'strftime pattern (e.g. "%Y-%m-%dT%H:%M:%SZ")'
        )
    return value.strftime(datetime_format) if datetime_format else value.isoformat()


def _strip_engine_unsupported_incremental_keys(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``resource`` with REST-engine-incompatible keys removed
    from ``endpoint.incremental``. The input is left untouched so schema typing
    can still read the full incremental config."""
    endpoint = resource.get("endpoint")
    if not isinstance(endpoint, dict):
        return resource
    incremental = endpoint.get("incremental")
    if not isinstance(incremental, dict) or not _ENGINE_UNSUPPORTED_INCREMENTAL_KEYS.intersection(incremental):
        return resource
    cleaned = exclude_keys(incremental, _ENGINE_UNSUPPORTED_INCREMENTAL_KEYS)
    return {**resource, "endpoint": {**endpoint, "incremental": cleaned}}


def _build_resource_graph(
    manifest: dict[str, Any],
) -> tuple[Any, dict[str, EndpointResource], dict[str, Optional[ResolvedParam]]]:
    """Run the REST engine's dependency-graph builder on a deep copy of the
    manifest. The builder binds path params in place, so it must never see the
    stored manifest's resources — hence the copy.
    """
    return build_resource_dependency_graph(
        cast(EndpointResourceBase, copy.deepcopy(manifest.get("resource_defaults") or {})),
        cast("list[str | EndpointResource]", copy.deepcopy(manifest["resources"])),
    )


class FanoutChain(NamedTuple):
    """The resources a schema's sync hands the engine: the chosen resource plus
    its fan-out ancestors (root first). The single source of truth for whether
    the chosen resource is a fan-out child — callers must not re-derive that
    from names or chain length."""

    ancestors: list[dict[str, Any]]
    child: dict[str, Any]

    @property
    def is_fanout_child(self) -> bool:
        return bool(self.ancestors)


def _fanout_chain(manifest: dict[str, Any], chosen_name: str) -> FanoutChain:
    """The :class:`FanoutChain` for ``chosen_name``: its fan-out ancestors
    (root first) plus ``chosen`` itself; a top-level resource has no ancestors.

    We pass this subset, not the whole manifest, on purpose. The engine is lazy —
    resources it builds but we never iterate issue no requests — but it still
    runs ``setup_incremental_object`` for every resource it's given at build time,
    so an unrelated resource's config error would otherwise sink this schema's
    sync. Subsetting also lets the caller full-scan the ancestors (via
    ``_without_incremental_config``) so the child's high-watermark isn't
    misapplied to a parent. The parent graph comes from the engine's own
    ``build_resource_dependency_graph``, so resolve-param detection isn't
    re-implemented here.

    Raises ``ValueError`` when ``chosen_name`` isn't in the manifest.
    """
    by_name: dict[str, dict[str, Any]] = {
        r["name"]: r for r in manifest["resources"] if isinstance(r, dict) and isinstance(r.get("name"), str)
    }
    chosen = by_name.get(chosen_name)
    if chosen is None:
        raise ValueError(f"Resource {chosen_name!r} not found in config")
    try:
        _, _, resolved = _build_resource_graph(manifest)
    except (ValueError, NotImplementedError, KeyError, JSONPathError) as exc:
        # Graph rules are enforced at create/update time, but a stored manifest
        # can predate them. A graph error on an UNRELATED resource must not sink
        # this schema's sync — fall back to handing the engine just the chosen
        # resource (the pre-fan-out behavior). If the chosen resource itself is
        # the broken one, the engine rejects it at build time with the
        # underlying error, which the caller converts to a non-retryable failure.
        # Logged so the size of the predates-the-rules population is measurable;
        # once this stops firing in production the fallback can be deleted.
        logger.warning(
            "custom_source_fanout_graph_fallback",
            schema_name=chosen_name,
            error=str(exc),
        )
        return FanoutChain(ancestors=[], child=chosen)
    ancestor_names: list[str] = []
    seen: set[str] = {chosen_name}
    current = chosen_name
    while (resolved_param := resolved.get(current)) is not None:
        parent_name = resolved_param.resolve_config["resource"]
        if parent_name in seen:
            # The graph builder itself doesn't reject cycles (only the
            # create-time `static_order` check does), so a stored manifest can
            # still carry one — fail loudly rather than loop or truncate.
            raise ValueError(f"Resource {chosen_name!r} is part of a dependency cycle")
        ancestor_names.append(parent_name)
        seen.add(parent_name)
        current = parent_name
    return FanoutChain(ancestors=[by_name[name] for name in reversed(ancestor_names)], child=chosen)


def _without_incremental_config(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``resource`` with every incremental form removed.

    The engine builds an incremental tracker from EITHER ``endpoint.incremental``
    OR a params-style ``{"type": "incremental", ...}`` spec (see the engine's
    ``setup_incremental_object``) — both must go, or the run's high-watermark
    would still be injected into this resource's start param.
    """
    endpoint = resource.get("endpoint")
    if not isinstance(endpoint, dict):
        return resource
    cleaned = exclude_keys(endpoint, {"incremental"})
    params = cleaned.get("params")
    if isinstance(params, dict):
        cleaned["params"] = {
            key: value
            for key, value in params.items()
            if not (isinstance(value, dict) and value.get("type") == "incremental")
        }
    return {**resource, "endpoint": cleaned}


def _schema_from_resource(resource: dict[str, Any]) -> SourceSchema:
    name = resource["name"]
    endpoint = resource.get("endpoint", {})
    incremental_cfg = endpoint.get("incremental") if isinstance(endpoint, dict) else None

    incremental_fields: list[IncrementalField] = []
    if isinstance(incremental_cfg, dict):
        cursor_path = incremental_cfg.get("cursor_path")
        if isinstance(cursor_path, str) and cursor_path:
            cursor_type = _incremental_field_type(incremental_cfg.get("cursor_type"))
            incremental_fields = [
                IncrementalField(
                    label=cursor_path,
                    field=cursor_path,
                    type=cursor_type,
                    field_type=cursor_type,
                )
            ]

    primary_key = resource.get("primary_key")
    detected_primary_keys: list[str] | None
    if isinstance(primary_key, list):
        detected_primary_keys = [str(key) for key in primary_key]
    elif isinstance(primary_key, str):
        detected_primary_keys = [primary_key]
    else:
        detected_primary_keys = None

    return SourceSchema(
        name=name,
        supports_incremental=bool(incremental_fields),
        supports_append=False,
        incremental_fields=incremental_fields,
        detected_primary_keys=detected_primary_keys,
    )
