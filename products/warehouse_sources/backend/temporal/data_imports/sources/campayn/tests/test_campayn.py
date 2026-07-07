from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.campayn import (
    CampaynRetryableError,
    _as_rows,
    _fetch,
    base_url,
    campayn_source,
    get_rows,
    is_subdomain_valid,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import (
    CAMPAYN_ENDPOINTS,
    ENDPOINTS,
)

SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.campayn.campayn.make_tracked_session"


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else []
        self.text = str(self._json)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} Client Error", response=mock.MagicMock(status_code=self.status_code)
            )


class FakeSession:
    def __init__(self, responses_by_url: dict[str, FakeResponse]) -> None:
        self._responses_by_url = responses_by_url
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers})
        # Match by suffix so tests don't have to spell out the full subdomain host every time.
        for suffix, response in self._responses_by_url.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected URL: {url}")


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme"),
            ("  acme  ", "acme"),
            ("acme.campayn.com", "acme"),
            ("https://acme.campayn.com/", "acme"),
            ("http://acme.campayn.com/api/v1/lists.json", "acme"),
            ("ACME.CAMPAYN.COM", "ACME"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestIsSubdomainValid:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", True),
            ("acme-corp", True),
            ("acme.campayn.com", True),
            ("https://acme.campayn.com", True),
            # Pasted paths/URLs collapse to the bare label, so these end up safe.
            ("acme/../evil", True),
            ("acme@evil.com", False),
            ("acme.evil.com", False),
            ("acme corp", False),
            ("", False),
        ],
    )
    def test_validity(self, raw: str, expected: bool) -> None:
        assert is_subdomain_valid(raw) is expected


class TestAsRows:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            ([{"id": "1"}, {"id": "2"}], [{"id": "1"}, {"id": "2"}]),
            ([{"id": "1"}, "junk"], [{"id": "1"}]),
            ({"data": [{"id": "1"}]}, [{"id": "1"}]),
            ({"id": "1"}, [{"id": "1"}]),
            ("nope", []),
            ([], []),
        ],
    )
    def test_coercion(self, payload: Any, expected: list[dict[str, Any]]) -> None:
        assert _as_rows(payload) == expected


class TestGetRowsTopLevel:
    def test_lists_yields_single_batch(self) -> None:
        session = FakeSession({"/lists.json": FakeResponse(json_data=[{"id": "1"}, {"id": "2"}])})
        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("acme", "k", "lists", mock.MagicMock()))
        assert batches == [[{"id": "1"}, {"id": "2"}]]
        assert session.calls[0]["url"] == f"{base_url('acme')}/lists.json"
        assert session.calls[0]["headers"]["Authorization"] == "TRUEREST apikey=k"

    def test_empty_response_yields_nothing(self) -> None:
        session = FakeSession({"/emails.json": FakeResponse(json_data=[])})
        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("acme", "k", "emails", mock.MagicMock()))
        assert batches == []


class TestGetRowsFanOut:
    def test_contacts_fan_out_injects_list_id(self) -> None:
        session = FakeSession(
            {
                "/lists.json": FakeResponse(json_data=[{"id": "10"}, {"id": "20"}]),
                "/lists/10/contacts.json": FakeResponse(json_data=[{"id": "1", "email": "a@x.com"}]),
                "/lists/20/contacts.json": FakeResponse(json_data=[{"id": "2", "email": "b@x.com"}]),
            }
        )
        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("acme", "k", "contacts", mock.MagicMock()))

        assert batches == [
            [{"id": "1", "email": "a@x.com", "list_id": "10"}],
            [{"id": "2", "email": "b@x.com", "list_id": "20"}],
        ]

    def test_fan_out_skips_list_deleted_mid_sync(self) -> None:
        session = FakeSession(
            {
                "/lists.json": FakeResponse(json_data=[{"id": "10"}, {"id": "20"}]),
                "/lists/10/contacts.json": FakeResponse(status_code=404),
                "/lists/20/contacts.json": FakeResponse(json_data=[{"id": "2"}]),
            }
        )
        logger = mock.MagicMock()
        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("acme", "k", "contacts", logger))

        assert batches == [[{"id": "2", "list_id": "20"}]]
        logger.warning.assert_called_once()

    def test_fan_out_reraises_non_404_http_error(self) -> None:
        session = FakeSession(
            {
                "/lists.json": FakeResponse(json_data=[{"id": "10"}]),
                "/lists/10/forms.json": FakeResponse(status_code=403),
            }
        )
        with mock.patch(SESSION_PATH, return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("acme", "k", "forms", mock.MagicMock()))


class TestFetchRetry:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        # Override tenacity's backoff sleep so the 5 retries don't actually wait; the decorator
        # reraises the last CampaynRetryableError once attempts are exhausted.
        session = FakeSession({"/lists.json": FakeResponse(status_code=status)})
        with mock.patch(SESSION_PATH, return_value=session), mock.patch.object(_fetch.retry, "sleep"):  # type: ignore[attr-defined]
            with pytest.raises(CampaynRetryableError):
                list(get_rows("acme", "k", "lists", mock.MagicMock()))

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_client_errors_raise_http_error(self, status: int) -> None:
        session = FakeSession({"/lists.json": FakeResponse(status_code=status)})
        with mock.patch(SESSION_PATH, return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("acme", "k", "lists", mock.MagicMock()))


class TestCampaynSource:
    def test_all_endpoints_buildable_with_correct_primary_keys(self) -> None:
        for endpoint in ENDPOINTS:
            response = campayn_source("acme", "k", endpoint, mock.MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == CAMPAYN_ENDPOINTS[endpoint].primary_keys
            # No stable creation-time field exists, so nothing is partitioned.
            assert response.partition_mode is None

    def test_fan_out_endpoints_key_includes_parent_list_id(self) -> None:
        assert campayn_source("acme", "k", "contacts", mock.MagicMock()).primary_keys == ["list_id", "id"]
        assert campayn_source("acme", "k", "forms", mock.MagicMock()).primary_keys == ["list_id", "id"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_mapping(self, status: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=status)
        with mock.patch(SESSION_PATH, return_value=session):
            assert validate_credentials("acme", "k") is expected

    def test_connection_error_returns_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(SESSION_PATH, return_value=session):
            assert validate_credentials("acme", "k") is False

    def test_probes_lists_endpoint(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=200)
        with mock.patch(SESSION_PATH, return_value=session):
            validate_credentials("acme", "k")
        called_url = (
            session.get.call_args.args[0] if session.get.call_args.args else session.get.call_args.kwargs["url"]
        )
        assert called_url == f"{base_url('acme')}/lists.json"
