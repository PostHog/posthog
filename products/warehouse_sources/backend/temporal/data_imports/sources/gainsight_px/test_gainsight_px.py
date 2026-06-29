from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px import gainsight_px as gpx
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    GAINSIGHT_PX_ENDPOINTS,
)

LOGGER = structlog.get_logger()


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


def _session_returning(response: FakeResponse) -> MagicMock:
    session = MagicMock()
    session.get.return_value = response
    return session


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "https://api.aptrinsic.com/v1"),
            ("eu", "https://api-eu.aptrinsic.com/v1"),
            ("us2", "https://api-us2.aptrinsic.com/v1"),
            ("unknown", "https://api.aptrinsic.com/v1"),
        ]
    )
    def test_region_resolution(self, region: str, expected: str) -> None:
        assert gpx._base_url(region) == expected


class TestHeaders:
    def test_uses_aptrinsic_api_key_header(self) -> None:
        # The PX auth header is a verified, non-obvious detail — a regression to `Authorization: Bearer`
        # would silently break every request.
        assert gpx.API_KEY_HEADER == "X-APTRINSIC-API-KEY"
        assert gpx._headers("secret")["X-APTRINSIC-API-KEY"] == "secret"


class TestExtractRecords:
    @parameterized.expand(
        [
            ("keyed_list", {"accounts": [{"id": 1}]}, "accounts", [{"id": 1}]),
            ("empty_list", {"accounts": []}, "accounts", []),
            ("missing_key", {"other": 1}, "accounts", []),
            ("key_not_a_list", {"accounts": {"id": 1}}, "accounts", []),
            ("non_dict_payload", [1, 2], "accounts", []),
            (
                "different_key_per_endpoint",
                {"articleExternalViewList": [{"id": 9}]},
                "articleExternalViewList",
                [{"id": 9}],
            ),
            # Safety net: a renamed record key self-heals to the sole list-of-objects field...
            ("renamed_key_self_heals", {"renamed": [{"id": 1}], "scrollId": "s"}, "accounts", [{"id": 1}]),
            # ...but only when it's unambiguous — two object-lists, or a scalar list, fall through to [].
            ("two_object_lists_no_heal", {"a": [{"id": 1}], "b": [{"id": 2}]}, "accounts", []),
            ("scalar_list_no_heal", {"foo": [1, 2]}, "accounts", []),
            # A list that only starts with a dict must not qualify — every item has to be an object.
            ("heterogeneous_list_no_heal", {"renamed": [{"id": 1}, "nope"]}, "accounts", []),
        ]
    )
    def test_extract(self, _name: str, payload: Any, data_key: str, expected: list) -> None:
        assert gpx._extract_records(payload, data_key) == expected

    def test_self_heal_warns_so_a_key_change_is_diagnosable(self) -> None:
        logger = MagicMock()
        assert gpx._extract_records({"renamed": [{"id": 1}]}, "accounts", logger) == [{"id": 1}]
        logger.warning.assert_called_once()


class TestCheckResponse:
    # Status classification is split out of `_fetch_page` (which is wrapped in tenacity's @retry) so it
    # can be asserted directly without incurring real retry backoff waits.
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        with pytest.raises(gpx.GainsightPxRetryableError):
            gpx._check_response(FakeResponse(status_code=status, text="boom"), "http://x", LOGGER)  # type: ignore[arg-type]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        with pytest.raises(requests.HTTPError):
            gpx._check_response(FakeResponse(status_code=status, text="nope"), "http://x", LOGGER)  # type: ignore[arg-type]

    def test_ok_passes_response_through(self) -> None:
        response = FakeResponse(status_code=200, json_data={"accounts": []})
        assert gpx._check_response(response, "http://x", LOGGER) is response  # type: ignore[arg-type, comparison-overlap]


class TestPagination:
    def _run(self, pages: list[dict[str, Any]], endpoint: str = "accounts") -> tuple[list[dict[str, Any]], MagicMock]:
        with (
            patch.object(gpx, "make_tracked_session", return_value=MagicMock()),
            patch.object(gpx, "_fetch_page", side_effect=pages) as mock_fetch,
        ):
            batches = list(gpx.get_rows("us", "key", endpoint, LOGGER))
        return [row for batch in batches for row in batch], mock_fetch

    def test_full_page_then_short_page_stops_even_when_scroll_id_persists(self) -> None:
        # PX does not reliably null `scrollId` on the final page, so a short page (fewer rows than
        # requested) is the real terminator. A `while scroll_id:` loop here would never stop.
        pages: list[dict[str, Any]] = [
            {"accounts": [{"id": i} for i in range(gpx.PAGE_SIZE)], "scrollId": "s1"},
            {"accounts": [{"id": i} for i in range(gpx.PAGE_SIZE, gpx.PAGE_SIZE + 100)], "scrollId": "s1"},
        ]
        rows, mock_fetch = self._run(pages)
        assert len(rows) == gpx.PAGE_SIZE + 100
        assert mock_fetch.call_count == 2
        # First request hits region+path with no cursor; the second carries the scrollId.
        assert mock_fetch.call_args_list[0].args[1] == "https://api.aptrinsic.com/v1/accounts"
        assert mock_fetch.call_args_list[0].args[3] == {"pageSize": gpx.PAGE_SIZE}
        assert mock_fetch.call_args_list[1].args[3] == {"pageSize": gpx.PAGE_SIZE, "scrollId": "s1"}

    def test_empty_first_page_yields_nothing(self) -> None:
        rows, mock_fetch = self._run([{"accounts": [], "scrollId": "s9"}])
        assert rows == []
        assert mock_fetch.call_count == 1

    def test_exact_page_multiple_fetches_once_more_then_stops(self) -> None:
        # A full final page can't be distinguished from a non-final one, so we fetch once more and stop
        # on the trailing empty page rather than dropping rows or looping.
        pages: list[dict[str, Any]] = [
            {"accounts": [{"id": i} for i in range(gpx.PAGE_SIZE)], "scrollId": "s1"},
            {"accounts": [], "scrollId": "s1"},
        ]
        rows, mock_fetch = self._run(pages)
        assert len(rows) == gpx.PAGE_SIZE
        assert mock_fetch.call_count == 2

    def test_missing_scroll_id_stops_after_first_page(self) -> None:
        rows, mock_fetch = self._run([{"accounts": [{"id": 1}]}])
        assert rows == [{"id": 1}]
        assert mock_fetch.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        session = _session_returning(FakeResponse(status_code=status))
        with patch.object(gpx, "make_tracked_session", return_value=session):
            assert gpx.validate_credentials("us", "key") is expected

    def test_network_error_returns_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(gpx, "make_tracked_session", return_value=session):
            assert gpx.validate_credentials("eu", "key") is False


class TestSecretRedaction:
    # The API key rides in a custom header the tracked transport won't redact by name, so every session
    # must be built with value-based redaction — guards against the key leaking into captured HTTP samples.
    def test_validate_credentials_redacts_key(self) -> None:
        session = _session_returning(FakeResponse(status_code=200))
        with patch.object(gpx, "make_tracked_session", return_value=session) as mock_factory:
            gpx.validate_credentials("us", "secret-key")
        assert mock_factory.call_args.kwargs.get("redact_values") == ("secret-key",)

    def test_sync_session_redacts_key(self) -> None:
        with (
            patch.object(gpx, "make_tracked_session", return_value=MagicMock()) as mock_factory,
            patch.object(gpx, "_fetch_page", side_effect=[{"accounts": []}]),
        ):
            list(gpx.get_rows("us", "secret-key", "accounts", LOGGER))
        assert mock_factory.call_args.kwargs.get("redact_values") == ("secret-key",)


class TestSourceResponse:
    @parameterized.expand([(name,) for name in GAINSIGHT_PX_ENDPOINTS])
    def test_response_shape_for_every_endpoint(self, endpoint: str) -> None:
        # Guards against a settings/transport routing mismatch and locks the `id` primary key.
        response = gpx.gainsight_px_source("us", "key", endpoint, LOGGER)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]

    def test_items_is_lazy(self) -> None:
        # Building the response must not fire any request; iteration is what pulls pages.
        with patch.object(gpx, "_fetch_page") as mock_fetch:
            gpx.gainsight_px_source("us", "key", "accounts", LOGGER)
        mock_fetch.assert_not_called()
