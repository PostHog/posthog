from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from tenacity import stop_after_attempt, wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven import aiven
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.aiven import (
    _fetch,
    _get_headers,
    _iter_rows,
    _list,
    aiven_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import AIVEN_ENDPOINTS


def _response(status_code: int, body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = ""
    resp.json.return_value = body or {}

    def _raise() -> None:
        if not resp.ok:
            raise requests.HTTPError(
                f"{status_code} Client Error: for url: https://api.aiven.io/v1/x",
                response=cast(requests.Response, resp),
            )

    resp.raise_for_status.side_effect = _raise
    return resp


class TestGetHeaders:
    def test_uses_aivenv1_scheme_not_bearer(self) -> None:
        headers = _get_headers("tok-123")
        # Aiven requires the literal `aivenv1` prefix; a `Bearer` prefix is rejected by the API.
        assert headers["Authorization"] == "aivenv1 tok-123"
        assert "Bearer" not in headers["Authorization"]


class TestFetch:
    def test_success_returns_json(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, {"projects": [{"project_name": "p1"}]})
        result = _fetch("https://api.aiven.io/v1/project", {}, MagicMock(), session)
        assert result == {"projects": [{"project_name": "p1"}]}

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status)
        # tenacity attaches `retry_with` to the wrapped fn at runtime; the type stub omits it.
        fetch = _fetch.retry_with(stop=stop_after_attempt(3), wait=wait_none())  # type: ignore[attr-defined]
        with pytest.raises(aiven.AivenRetryableError):
            fetch("https://api.aiven.io/v1/project", {}, MagicMock(), session)
        assert session.get.call_count == 3

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately_without_retry(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status)
        with pytest.raises(requests.HTTPError):
            _fetch("https://api.aiven.io/v1/project", {}, MagicMock(), session)
        # Credential/permission failures must not burn retries.
        assert session.get.call_count == 1


class TestList:
    @parameterized.expand(
        [
            ("present", {"projects": [{"project_name": "p1"}]}, [{"project_name": "p1"}]),
            ("missing_key", {"other": []}, []),
            ("null_value", {"projects": None}, []),
            ("non_list", {"projects": {"nested": 1}}, []),
        ]
    )
    def test_extracts_rows_under_data_key(self, _name: str, body: dict[str, Any], expected: list) -> None:
        with patch.object(aiven, "_fetch", return_value=body):
            assert _list("/project", "projects", {}, MagicMock(), MagicMock()) == expected


class TestFanOut:
    def test_fan_out_none_yields_single_batch(self) -> None:
        with patch.object(aiven, "_fetch", return_value={"clouds": [{"cloud_name": "aws-x"}]}):
            batches = list(_iter_rows(AIVEN_ENDPOINTS["clouds"], {}, MagicMock(), MagicMock()))
        assert batches == [[{"cloud_name": "aws-x"}]]

    def test_fan_out_project_injects_parent_project_name(self) -> None:
        # `services` items carry no project field, so the parent's `project_name` must be injected
        # to keep the composite primary key unique across projects.
        responses = {
            "/project": {"projects": [{"project_name": "p1"}, {"project_name": "p2"}]},
            "/project/p1/service": {"services": [{"service_name": "s1"}]},
            "/project/p2/service": {"services": [{"service_name": "s2"}]},
        }

        def fake_fetch(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return responses[url.replace(aiven.AIVEN_BASE_URL, "")]

        with patch.object(aiven, "_fetch", side_effect=fake_fetch):
            batches = list(_iter_rows(AIVEN_ENDPOINTS["services"], {}, MagicMock(), MagicMock()))

        assert batches == [
            [{"service_name": "s1", "project_name": "p1"}],
            [{"service_name": "s2", "project_name": "p2"}],
        ]

    def test_fan_out_organization_injects_org_without_overwriting(self) -> None:
        responses = {
            "/organizations": {"organizations": [{"organization_id": "org1"}]},
            "/organization/org1/user": {"users": [{"user_id": "u1"}]},
        }

        def fake_fetch(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return responses[url.replace(aiven.AIVEN_BASE_URL, "")]

        with patch.object(aiven, "_fetch", side_effect=fake_fetch):
            batches = list(_iter_rows(AIVEN_ENDPOINTS["organization_users"], {}, MagicMock(), MagicMock()))

        assert batches == [[{"user_id": "u1", "organization_id": "org1"}]]

    def test_fan_out_organization_setdefault_keeps_existing_org_id(self) -> None:
        # billing_groups already carry organization_id; injection must not clobber it.
        responses = {
            "/organizations": {"organizations": [{"organization_id": "org1"}]},
            "/organization/org1/billing-groups": {
                "billing_groups": [{"billing_group_id": "bg1", "organization_id": "org-real"}]
            },
        }

        def fake_fetch(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return responses[url.replace(aiven.AIVEN_BASE_URL, "")]

        with patch.object(aiven, "_fetch", side_effect=fake_fetch):
            batches = list(_iter_rows(AIVEN_ENDPOINTS["billing_groups"], {}, MagicMock(), MagicMock()))

        assert batches[0][0]["organization_id"] == "org-real"

    def test_fan_out_invoice_two_levels_injects_org_and_invoice(self) -> None:
        responses = {
            "/organizations": {"organizations": [{"organization_id": "org1"}]},
            "/organization/org1/invoices": {"invoices": [{"invoice_number": "inv1"}, {"invoice_number": "inv2"}]},
            "/organization/org1/invoice/inv1/lines": {"lines": [{"line_type": "usage"}]},
            "/organization/org1/invoice/inv2/lines": {"lines": [{"line_type": "credit"}]},
        }

        def fake_fetch(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return responses[url.replace(aiven.AIVEN_BASE_URL, "")]

        with patch.object(aiven, "_fetch", side_effect=fake_fetch):
            batches = list(_iter_rows(AIVEN_ENDPOINTS["invoice_lines"], {}, MagicMock(), MagicMock()))

        assert batches == [
            [{"line_type": "usage", "organization_id": "org1", "invoice_number": "inv1"}],
            [{"line_type": "credit", "organization_id": "org1", "invoice_number": "inv2"}],
        ]

    def test_empty_batches_are_not_yielded(self) -> None:
        responses: dict[str, dict[str, Any]] = {
            "/project": {"projects": [{"project_name": "p1"}, {"project_name": "p2"}]},
            "/project/p1/service": {"services": []},
            "/project/p2/service": {"services": [{"service_name": "s2"}]},
        }

        def fake_fetch(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return responses[url.replace(aiven.AIVEN_BASE_URL, "")]

        with patch.object(aiven, "_fetch", side_effect=fake_fetch):
            batches = list(_iter_rows(AIVEN_ENDPOINTS["services"], {}, MagicMock(), MagicMock()))

        assert batches == [[{"service_name": "s2", "project_name": "p2"}]]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    def test_maps_status_to_bool(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(status)
        with patch.object(aiven, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(aiven, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is False


class TestAivenSource:
    def test_get_rows_uses_single_tracked_session(self) -> None:
        session = MagicMock()
        with (
            patch.object(aiven, "make_tracked_session", return_value=session) as make_session,
            patch.object(aiven, "_iter_rows", return_value=iter([])) as iter_rows,
        ):
            list(get_rows("tok", "projects", MagicMock()))
        make_session.assert_called_once()
        # The one session is threaded into the fan-out so requests reuse pooled connections.
        assert iter_rows.call_args.args[3] is session

    @parameterized.expand(list(AIVEN_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        config = AIVEN_ENDPOINTS[endpoint]
        response = aiven_source("tok", endpoint, MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
