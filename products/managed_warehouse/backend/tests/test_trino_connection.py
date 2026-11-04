import os
import uuid
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from urllib.parse import urlsplit

import pytest
from unittest import mock

from django.test import override_settings

import requests
from rest_framework.response import Response

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, tags_context

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTrinoConnectionUnavailable
from products.managed_warehouse.backend.trino_connection import (
    connect_managed_warehouse_trino,
    resolve_managed_warehouse_trino_connection,
    use_trino_canary,
)

CREDENTIAL_ID = "svc_0123456789abcdef01234567"
CANARY_DOMAIN = "canary.dw.us.postwh.com"


def _mint_response(**target_overrides: object) -> Response:
    return Response(
        {
            "credential_id": CREDENTIAL_ID,
            "credential_secret": "example-secret",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "connect": {"host": "warehouse.example.com", "port": 5432, "database": "ducklake", "sslmode": "require"},
            "trino_connect": {
                "host": "tenant.dw.us.postwh.com",
                "port": 443,
                "catalog": "org_example",
                "username": CREDENTIAL_ID,
                "http_scheme": "https",
                **target_overrides,
            },
        }
    )


def _http_response(request: requests.PreparedRequest, **payload: object) -> requests.Response:
    import json

    response = requests.Response()
    response.status_code = 200
    response.request = request
    response._content = json.dumps(payload).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def test_resolves_a_minted_credential_without_reading_stored_passwords() -> None:
    with mock.patch(
        "products.managed_warehouse.backend.presentation.views._request", return_value=_mint_response()
    ) as cp:
        connection = resolve_managed_warehouse_trino_connection("org-1")
    assert connection.username == CREDENTIAL_ID
    assert connection.password == "example-secret"
    assert connection.catalog == "org_example"
    assert "example-secret" not in repr(connection)
    assert cp.call_args.args == ("POST", "org-1", "/service-credentials")


@pytest.mark.parametrize(
    "change",
    [
        {"trino_connect": None},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"expires_at": "2000-01-01T00:00:00"},
        {"credential_id": "root"},
        {"credential_secret": ""},
    ],
)
def test_rejects_unusable_service_credentials(change: dict[str, object]) -> None:
    response = _mint_response()
    response.data.update(change)
    with mock.patch("products.managed_warehouse.backend.presentation.views._request", return_value=response):
        with pytest.raises(ManagedWarehouseTrinoConnectionUnavailable):
            resolve_managed_warehouse_trino_connection("org-1")


@pytest.mark.parametrize(
    "target",
    [
        {"host": ""},
        {"port": 0},
        {"port": True},
        {"port": 65536},
        {"catalog": ""},
        {"username": "root"},
        {"http_scheme": "http"},
    ],
)
def test_rejects_invalid_trino_targets(target: dict[str, object]) -> None:
    with mock.patch(
        "products.managed_warehouse.backend.presentation.views._request", return_value=_mint_response(**target)
    ):
        with pytest.raises(ManagedWarehouseTrinoConnectionUnavailable):
            resolve_managed_warehouse_trino_connection("org-1")


@pytest.mark.parametrize(
    "canary,canary_domain,host",
    [
        (False, "", "tenant.dw.us.postwh.com"),
        (False, CANARY_DOMAIN, "tenant.dw.us.postwh.com"),
        (True, CANARY_DOMAIN, "tenant.canary.dw.us.postwh.com"),
    ],
)
@pytest.mark.parametrize("renewal_target", ["included", "omitted", "null"])
def test_polling_renews_the_grant_and_preserves_cancellation_ownership(
    renewal_target: str, canary: bool, canary_domain: str, host: str
) -> None:
    minted = _mint_response()
    refreshed = _mint_response()
    refreshed.data.pop("credential_secret")
    refreshed.data["secret_rotated"] = False
    if renewal_target == "omitted":
        refreshed.data.pop("trino_connect")
    elif renewal_target == "null":
        refreshed.data["trino_connect"] = None
    refreshed.data["expires_at"] = (datetime.now(UTC) + timedelta(minutes=29)).isoformat()
    issued_at = datetime.now(UTC)
    sent: list[requests.PreparedRequest] = []

    def send(request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        sent.append(request)
        if request.method == "POST":
            return _http_response(
                request,
                id="query-1",
                infoUri=f"https://{host}/query-1",
                nextUri=f"https://{host}/v1/statement/query-1",
                stats={},
            )
        if request.method == "GET":
            return _http_response(
                request,
                id="query-1",
                infoUri=f"https://{host}/query-1",
                nextUri=f"https://{host}/v1/statement/query-1",
                columns=[{"name": "value", "type": "bigint", "typeSignature": {"rawType": "bigint", "arguments": []}}],
                data=[[1]],
                stats={},
            )
        response = _http_response(request)
        response.status_code = 204
        return response

    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=canary_domain),
        mock.patch(
            "products.managed_warehouse.backend.presentation.views._request", side_effect=[minted, refreshed]
        ) as cp,
        mock.patch("products.managed_warehouse.backend.trino_connection._utcnow", return_value=issued_at) as now,
        mock.patch("requests.adapters.HTTPAdapter.send", side_effect=send),
    ):
        with connect_managed_warehouse_trino("org-1", canary=canary) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            now.return_value = issued_at + timedelta(minutes=14)
            cursor.cancel()
    assert cp.call_count == 2
    assert {urlsplit(r.url).hostname for r in sent} == {host}
    assert cp.call_args.args == ("POST", "org-1", "/service-credentials/refresh")
    assert cp.call_args.kwargs["json_body"]["credential_id"] == CREDENTIAL_ID
    assert cp.call_args.kwargs["json_body"]["rotate_secret"] is False
    assert [r.method for r in sent] == ["POST", "GET", "DELETE"]
    assert (
        sent[-1].headers["Authorization"]
        == "Basic " + base64.b64encode(f"{CREDENTIAL_ID}:example-secret".encode()).decode()
    )
    assert all(r.headers["X-Trino-User"] == CREDENTIAL_ID for r in sent)


@pytest.mark.parametrize(
    "refresh_response",
    ["unavailable", "target_changed", "identity_changed", "old_control_plane", "rotated", "expired", "naive_expiry"],
)
def test_failed_refresh_does_not_send_a_request(refresh_response: str) -> None:
    minted = _mint_response()
    issued_at = datetime.now(UTC)
    response = _mint_response()
    response.data.pop("credential_secret")
    response.data["secret_rotated"] = False
    response.data["expires_at"] = (datetime.now(UTC) + timedelta(minutes=29)).isoformat()
    if refresh_response == "unavailable":
        response = Response({"error": "unavailable"}, status=503)
    elif refresh_response == "target_changed":
        response.data["trino_connect"]["host"] = "other.example.com"
    elif refresh_response == "old_control_plane":
        response.data.pop("secret_rotated")
        response.data["credential_secret"] = "unexpected-rotated-secret"
    elif refresh_response == "rotated":
        response.data["credential_secret"] = "unexpected-rotated-secret"
    elif refresh_response in {"expired", "naive_expiry"}:
        response.data.pop("trino_connect")
        response.data["expires_at"] = "2000-01-01T00:00:00Z" if refresh_response == "expired" else "2099-01-01T00:00:00"
    else:
        response.data["credential_id"] = "svc_111111111111111111111111"
        response.data["trino_connect"]["username"] = response.data["credential_id"]
    with (
        mock.patch("products.managed_warehouse.backend.presentation.views._request", side_effect=[minted, response]),
        mock.patch("products.managed_warehouse.backend.trino_connection._utcnow", return_value=issued_at) as now,
        mock.patch("requests.adapters.HTTPAdapter.send") as send,
    ):
        with connect_managed_warehouse_trino("org-1") as connection:
            now.return_value = issued_at + timedelta(minutes=14)
            with pytest.raises(ManagedWarehouseTrinoConnectionUnavailable):
                connection.cursor().execute("SELECT 1")
        send.assert_not_called()


def test_canary_without_a_configured_domain_is_refused_before_a_credential_is_minted() -> None:
    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=""),
        mock.patch("products.managed_warehouse.backend.presentation.views._request") as cp,
        pytest.raises(ManagedWarehouseTrinoConnectionUnavailable, match="canary domain is not configured"),
    ):
        with connect_managed_warehouse_trino("org-1", canary=True):
            pass
    cp.assert_not_called()


@pytest.mark.parametrize(
    "host",
    [
        "trino.example.com",
        "tenant",
        "nested.tenant.dw.us.postwh.com",
        "tenant.dw.us.postwh.com.example.com",
        "tenant.canary.dw.us.postwh.com",
    ],
)
def test_canary_route_needs_a_host_that_the_control_plane_issued_under_a_normal_domain(host: str) -> None:
    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=CANARY_DOMAIN),
        mock.patch(
            "products.managed_warehouse.backend.presentation.views._request", return_value=_mint_response(host=host)
        ),
        mock.patch("requests.adapters.HTTPAdapter.send") as send,
        pytest.raises(ManagedWarehouseTrinoConnectionUnavailable, match="hosted warehouse host"),
    ):
        with connect_managed_warehouse_trino("org-1", canary=True):
            pass
    send.assert_not_called()


@pytest.mark.parametrize(
    "host,port,bypass_proxy,canary_domain",
    [
        ("tenant.dw.us.postwh.com", 443, True, ""),
        ("tenant.dw.eu.postwh.com", 443, True, ""),
        ("TENANT.DW.DEV.POSTWH.COM.", 443, True, ""),
        ("tenant.dw.us.postwh.com", 8443, False, ""),
        ("trino.example.com", 443, False, ""),
        ("nested.tenant.dw.us.postwh.com", 443, False, ""),
        ("dw.us.postwh.com", 443, False, ""),
        ("tenant.dw.us.postwh.com.example.com", 443, False, ""),
        ("tenant", 443, False, ""),
        ("tenant.canary.dw.us.postwh.com", 443, False, ""),
        ("tenant.canary.dw.us.postwh.com", 443, True, CANARY_DOMAIN),
        ("tenant.canary.dw.us.postwh.com", 8443, False, CANARY_DOMAIN),
        ("nested.tenant.canary.dw.us.postwh.com", 443, False, CANARY_DOMAIN),
        ("tenant.canary.dw.eu.postwh.com", 443, False, CANARY_DOMAIN),
        ("tenant.canary.dw.us.postwh.com.example.com", 443, False, CANARY_DOMAIN),
    ],
)
def test_connection_keeps_verified_tls_and_scoped_proxy_bypass(
    host: str, port: int, bypass_proxy: bool, canary_domain: str
) -> None:
    proxy = "http://proxy.example.com:4750"
    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=canary_domain),
        mock.patch.dict(os.environ, {"HTTPS_PROXY": proxy, "NO_PROXY": ""}, clear=True),
        mock.patch(
            "products.managed_warehouse.backend.presentation.views._request",
            return_value=_mint_response(host=host, port=port),
        ),
        mock.patch("requests.adapters.HTTPAdapter.send", side_effect=RuntimeError("network boundary")) as send,
    ):
        with pytest.raises(RuntimeError, match="network boundary"):
            with connect_managed_warehouse_trino("org-1") as connection:
                connection.cursor().execute("SELECT 1")
    assert send.call_args.kwargs["verify"] is True
    assert send.call_args.kwargs["timeout"] == 60
    assert send.call_args.kwargs["proxies"].get("https") == (None if bypass_proxy else proxy)


@pytest.mark.parametrize("response_kind", ["foreign_next_uri", "redirect"])
def test_service_secret_is_never_sent_to_a_redirect_or_foreign_poll_target(response_kind: str) -> None:
    sent: list[requests.PreparedRequest] = []

    def send(request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        sent.append(request)
        response = _http_response(
            request,
            id="query-1",
            infoUri="https://tenant.dw.us.postwh.com/query-1",
            nextUri="https://other.example.com/v1/statement/query-1",
            stats={},
        )
        if response_kind == "redirect":
            response.status_code = 307
            response.headers["Location"] = "https://other.example.com/v1/statement"
        return response

    with (
        mock.patch("products.managed_warehouse.backend.presentation.views._request", return_value=_mint_response()),
        mock.patch("requests.adapters.HTTPAdapter.send", side_effect=send),
    ):
        with connect_managed_warehouse_trino("org-1") as connection:
            with pytest.raises(ManagedWarehouseTrinoConnectionUnavailable):
                connection.cursor().execute("SELECT 1")
    assert len(sent) == 1
    assert sent[0].url == "https://tenant.dw.us.postwh.com:443/v1/statement"


@pytest.mark.parametrize("verify", [True, "example-ca.pem"])
def test_a_prepared_request_renews_expiry_at_send_time(verify: bool | str) -> None:
    from products.managed_warehouse.backend.trino_connection import _TrinoServiceSession

    minted = _mint_response()
    refreshed = _mint_response()
    issued_at = datetime.now(UTC)
    refreshed.data.pop("credential_secret")
    refreshed.data["secret_rotated"] = False
    refreshed.data["expires_at"] = (issued_at + timedelta(minutes=29)).isoformat()
    with (
        mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.example.com:4750", "NO_PROXY": ""}, clear=True),
        mock.patch(
            "products.managed_warehouse.backend.presentation.views._request", side_effect=[minted, refreshed]
        ) as cp,
        mock.patch("products.managed_warehouse.backend.trino_connection._utcnow", return_value=issued_at) as now,
        mock.patch(
            "requests.adapters.HTTPAdapter.send", side_effect=lambda request, **kwargs: _http_response(request)
        ) as send,
    ):
        config = resolve_managed_warehouse_trino_connection("org-1")
        with _TrinoServiceSession("org-1", config) as session:
            session.verify = verify
            session.cert = ("client.crt", "client.key")
            session.stream = True
            prepared = session.prepare_request(
                requests.Request("GET", "https://tenant.dw.us.postwh.com/v1/statement/query-1")
            )
            now.return_value = issued_at + timedelta(minutes=14)
            session.send(prepared)
            session.send(prepared)
    assert send.call_args.kwargs["verify"] == verify
    assert send.call_args.kwargs["cert"] == ("client.crt", "client.key")
    assert send.call_args.kwargs["stream"] is True
    assert send.call_args.kwargs["proxies"]["https"] == "http://proxy.example.com:4750"
    assert cp.call_count == 2
    assert (
        prepared.headers["Authorization"]
        == "Basic " + base64.b64encode(f"{CREDENTIAL_ID}:example-secret".encode()).decode()
    )


def test_cancellation_does_not_wait_for_a_blocked_poll() -> None:
    from products.managed_warehouse.backend.trino_connection import _TrinoServiceSession

    poll_started, release_poll = Event(), Event()
    minted, refreshed = _mint_response(), _mint_response()
    issued_at = datetime.now(UTC)
    refreshed.data.pop("credential_secret")
    refreshed.data["secret_rotated"] = False
    refreshed.data["expires_at"] = (issued_at + timedelta(minutes=29)).isoformat()

    def send(request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        if request.method == "GET":
            poll_started.set()
            assert release_poll.wait(10)
        return _http_response(request)

    with (
        mock.patch(
            "products.managed_warehouse.backend.presentation.views._request", side_effect=[minted, refreshed]
        ) as cp,
        mock.patch("products.managed_warehouse.backend.trino_connection._utcnow", return_value=issued_at) as now,
        mock.patch("requests.adapters.HTTPAdapter.send", side_effect=send),
    ):
        config = resolve_managed_warehouse_trino_connection("org-1")
        with _TrinoServiceSession("org-1", config) as session, ThreadPoolExecutor(max_workers=2) as executor:
            now.return_value = issued_at + timedelta(minutes=14)
            poll = executor.submit(session.get, "https://tenant.dw.us.postwh.com/v1/statement/query-1")
            try:
                assert poll_started.wait(5)
                cancel = executor.submit(session.delete, "https://tenant.dw.us.postwh.com/v1/statement/query-1")
                assert cancel.result(timeout=5).status_code == 200
                assert not poll.done()
            finally:
                release_poll.set()
            assert poll.result(timeout=5).status_code == 200
    assert cp.call_count == 2


@pytest.mark.parametrize(
    "canary_domain,distinct_id,tags,limit_context,flag_result,evaluates_flag,expected",
    [
        (CANARY_DOMAIN, "user-1", {}, None, True, True, True),
        (CANARY_DOMAIN, "user-1", {}, LimitContext.QUERY, True, True, True),
        (CANARY_DOMAIN, "user-1", {}, LimitContext.QUERY_ASYNC, True, True, True),
        (CANARY_DOMAIN, "user-1", {}, None, False, True, False),
        (CANARY_DOMAIN, "user-1", {}, None, None, True, False),
        (CANARY_DOMAIN, "user-1", {}, None, RuntimeError("flags unavailable"), True, False),
        ("", "user-1", {}, None, True, False, False),
        (CANARY_DOMAIN, None, {}, None, True, False, False),
        (CANARY_DOMAIN, "", {}, None, True, False, False),
        (CANARY_DOMAIN, "user-1", {"trigger": "warmingV2"}, None, True, False, False),
        (CANARY_DOMAIN, "user-1", {"feature": Feature.CACHE_WARMUP}, None, True, False, False),
        (CANARY_DOMAIN, "user-1", {"alert_config_id": uuid.uuid4()}, None, True, False, False),
        (CANARY_DOMAIN, "user-1", {"feature": Feature.ALERTING}, None, True, False, False),
        (CANARY_DOMAIN, "user-1", {}, LimitContext.EXPORT, True, False, False),
        (CANARY_DOMAIN, "user-1", {}, LimitContext.SQL_ALERT, True, False, False),
        (CANARY_DOMAIN, "user-1", {}, LimitContext.POSTHOG_AI, True, False, False),
    ],
)
def test_use_trino_canary_needs_a_flagged_user_on_an_interactive_run(
    canary_domain: str,
    distinct_id: str | None,
    tags: dict[str, object],
    limit_context: LimitContext | None,
    flag_result: object,
    evaluates_flag: bool,
    expected: bool,
) -> None:
    clean_tags = {"trigger": None, "feature": None, "alert_config_id": None}
    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=canary_domain),
        tags_context(**{**clean_tags, **tags}),
        mock.patch(
            "posthoganalytics.feature_enabled",
            side_effect=flag_result if isinstance(flag_result, Exception) else None,
            return_value=flag_result,
        ) as flag,
    ):
        assert use_trino_canary(distinct_id, "org-1", limit_context=limit_context) is expected
    assert flag.called is evaluates_flag
    if evaluates_flag:
        assert flag.call_args.args == ("managed-warehouse-trino-canary", distinct_id)
        assert flag.call_args.kwargs["groups"] == {"organization": "org-1"}
        assert flag.call_args.kwargs["only_evaluate_locally"] is False
        assert flag.call_args.kwargs["send_feature_flag_events"] is False
