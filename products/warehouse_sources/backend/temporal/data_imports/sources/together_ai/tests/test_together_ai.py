from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai import together_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import TOGETHER_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.together_ai import (
    TOGETHER_AI_BASE_URL,
    _extract_rows,
    get_rows,
    get_status_code,
    together_ai_source,
)


def _collect(monkeypatch: Any, endpoint: str, payload: Any) -> tuple[list[dict], list[dict[str, Any]]]:
    """Feed `payload` from _fetch and return (flattened rows, recorded fetch calls)."""
    calls: list[dict[str, Any]] = []

    def fake_fetch(session: Any, url: str, params: Any, headers: dict[str, str], logger: Any) -> Any:
        calls.append({"url": url, "params": params, "headers": headers})
        return payload

    monkeypatch.setattr(together_ai, "_fetch", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(api_key="together_test", endpoint=endpoint, logger=MagicMock()):
        # get_rows yields the collection as a list[dict]; the pipeline batches internally.
        rows.extend(batch)
    return rows, calls


class TestExtractRows:
    @parameterized.expand(
        [
            ("wrapped_envelope", {"data": [{"id": "ft-1"}, {"id": "ft-2"}]}, [{"id": "ft-1"}, {"id": "ft-2"}]),
            ("bare_array", [{"id": "batch-1"}], [{"id": "batch-1"}]),
            ("empty_envelope", {"data": []}, []),
            ("empty_array", [], []),
            ("non_dict_rows_dropped", ["not-a-row", {"id": "ft-1"}], [{"id": "ft-1"}]),
        ]
    )
    def test_unwraps_both_response_shapes(self, _name: str, payload: Any, expected: list[dict]) -> None:
        assert _extract_rows(payload, "fine_tunes") == expected

    @parameterized.expand(
        [
            ("string_body", "error"),
            ("null_body", None),
            ("dict_without_data_list", {"data": "oops"}),
            ("plain_object", {"id": "ft-1"}),
        ]
    )
    def test_unexpected_shape_raises(self, _name: str, payload: Any) -> None:
        # A silently-swallowed shape change would sync an empty table and look like data loss.
        with pytest.raises(ValueError):
            _extract_rows(payload, "fine_tunes")


class TestGetRows:
    def test_yields_rows_from_wrapped_endpoint(self, monkeypatch: Any) -> None:
        rows, calls = _collect(monkeypatch, "fine_tunes", {"data": [{"id": "ft-1"}]})
        assert rows == [{"id": "ft-1"}]
        assert calls[0]["url"] == f"{TOGETHER_AI_BASE_URL}/fine-tunes"
        assert calls[0]["headers"]["Authorization"] == "Bearer together_test"

    def test_yields_rows_from_bare_array_endpoint(self, monkeypatch: Any) -> None:
        rows, calls = _collect(monkeypatch, "batches", [{"id": "batch-1"}, {"id": "batch-2"}])
        assert rows == [{"id": "batch-1"}, {"id": "batch-2"}]
        assert calls[0]["url"] == f"{TOGETHER_AI_BASE_URL}/batches"

    def test_endpoints_table_only_requests_dedicated_deployments(self, monkeypatch: Any) -> None:
        # Without the filter the response also contains every public serverless model,
        # flooding the table with rows that duplicate the models catalog.
        _rows, calls = _collect(monkeypatch, "endpoints", {"data": []})
        assert calls[0]["params"] == {"type": "dedicated"}

    def test_top_level_endpoints_send_no_params(self, monkeypatch: Any) -> None:
        _rows, calls = _collect(monkeypatch, "models", [])
        assert calls[0]["params"] is None

    def test_empty_collection_yields_no_batches(self, monkeypatch: Any) -> None:
        rows, _calls = _collect(monkeypatch, "files", {"data": []})
        assert rows == []


class TestFetchRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 500),
            ("bad_gateway", 502),
        ]
    )
    def test_retryable_status_codes_are_retried(self, _name: str, status_code: int) -> None:
        retryable = MagicMock()
        retryable.status_code = status_code
        retryable.ok = False

        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}

        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(together_ai._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = together_ai._fetch(session, f"{TOGETHER_AI_BASE_URL}/x", None, {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_transport_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = []

        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(together_ai._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = together_ai._fetch(session, f"{TOGETHER_AI_BASE_URL}/x", None, {}, MagicMock())

        assert result == []
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        unauthorized = MagicMock()
        unauthorized.status_code = 401
        unauthorized.ok = False
        unauthorized.reason = "Unauthorized"
        unauthorized.url = f"{TOGETHER_AI_BASE_URL}/x?type=dedicated"

        session = MagicMock()
        session.get.return_value = unauthorized

        with pytest.raises(requests.HTTPError) as exc_info:
            together_ai._fetch(session, f"{TOGETHER_AI_BASE_URL}/x", None, {}, MagicMock())

        # The rebuilt error must not leak the query string or response body into stored error state.
        message = str(exc_info.value)
        assert "401 Client Error: Unauthorized" in message
        assert "?type=dedicated" not in message
        assert session.get.call_count == 1


class TestGetStatusCode:
    def test_default_probe_hits_files_with_bearer_auth(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(together_ai, "make_tracked_session", return_value=session):
            status = get_status_code("together_test")

        assert status == 200
        args, kwargs = session.get.call_args
        assert args[0] == f"{TOGETHER_AI_BASE_URL}/files"
        assert kwargs["headers"]["Authorization"] == "Bearer together_test"

    def test_schema_probe_hits_that_endpoint_with_its_params(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(together_ai, "make_tracked_session", return_value=session):
            get_status_code("together_test", "endpoints")

        args, kwargs = session.get.call_args
        assert args[0] == f"{TOGETHER_AI_BASE_URL}/endpoints"
        assert kwargs["params"] == {"type": "dedicated"}

    def test_unknown_schema_falls_back_to_files_probe(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(together_ai, "make_tracked_session", return_value=session):
            get_status_code("together_test", "not_a_table")

        args, _kwargs = session.get.call_args
        assert args[0] == f"{TOGETHER_AI_BASE_URL}/files"


class TestTogetherAISourceResponse:
    @parameterized.expand(list(TOGETHER_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        response = together_ai_source(api_key="together_test", endpoint=endpoint, logger=MagicMock())
        cfg = TOGETHER_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # Partition on the stable creation timestamp — never updated_at — so partitions
        # don't rewrite on every sync.
        assert response.partition_keys == [cfg.partition_key]
        assert response.partition_mode == "datetime"
