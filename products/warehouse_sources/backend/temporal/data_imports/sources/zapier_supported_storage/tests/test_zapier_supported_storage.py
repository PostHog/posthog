from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import requests
from tenacity import stop_after_attempt, wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.zapier_supported_storage import (
    ZapierSupportedStorageRetryableError,
    _fetch_store,
    get_rows,
    validate_credentials,
    zapier_supported_storage_source,
)

MODULE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.zapier_supported_storage"
)


def _response(body: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = body
    resp.text = str(body)
    resp.reason = "Bad Request"
    resp.url = "https://store.zapier.com/api/records"
    return resp


def _rows_from_store(store: Any) -> list[dict[str, Any]]:
    with patch(f"{MODULE}.make_tracked_session") as factory:
        factory.return_value.get.return_value = _response(store)
        tables = list(get_rows(secret="s", logger=MagicMock()))
    out: list[dict[str, Any]] = []
    for table in tables:
        assert isinstance(table, pa.Table)
        out.extend(table.to_pylist())
    return out


class TestGetRows:
    def test_one_row_per_store_key(self) -> None:
        rows = _rows_from_store({"a": "1", "b": "2"})
        assert {r["key"] for r in rows} == {"a", "b"}
        assert {(r["key"], r["value"]) for r in rows} == {("a", "1"), ("b", "2")}

    def test_empty_store_yields_no_rows(self) -> None:
        assert _rows_from_store({}) == []

    @pytest.mark.parametrize(
        ("stored_value", "expected"),
        [
            ("plain string", "plain string"),
            (42, "42"),
            (3.5, "3.5"),
            (True, "true"),
            ({"nested": 1}, '{"nested": 1}'),
            ([1, 2, 3], "[1, 2, 3]"),
            (None, None),
        ],
    )
    def test_value_coerced_to_stable_string_type(self, stored_value: Any, expected: str | None) -> None:
        # Storage by Zapier holds arbitrary JSON per key; the value column must be a single stable
        # type so the Delta table doesn't get conflicting per-row schemas. Strings pass through,
        # everything else is JSON-encoded, and a genuine null stays null.
        rows = _rows_from_store({"k": stored_value})
        assert rows == [{"key": "k", "value": expected}]


class TestFetchStore:
    def _fetch_once(self, response: MagicMock) -> Any:
        # Collapse the retry to a single attempt with no backoff so retryable-status tests don't sleep.
        session = MagicMock()
        session.get.return_value = response
        fetch = _fetch_store.retry_with(stop=stop_after_attempt(1), wait=wait_none())  # type: ignore[attr-defined]
        return fetch(session, "secret", MagicMock())

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(ZapierSupportedStorageRetryableError):
            self._fetch_once(_response({}, status_code=status))

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_raise_scrubbed_http_error(self, status: int) -> None:
        # 4xx can't be fixed by retrying, so an HTTPError must surface immediately. The message must
        # keep the "<status> Client Error ... for url: https://store.zapier.com/api/records" prefix
        # (get_non_retryable_errors matches on it) but never echo the response body, which can hold
        # arbitrary store secrets and would otherwise leak into logs and latest_error.
        secret_body = {"leaked": "super-secret-store-value"}
        with pytest.raises(requests.HTTPError) as exc:
            self._fetch_once(_response(secret_body, status_code=status))
        message = str(exc.value)
        assert "https://store.zapier.com/api/records" in message
        assert "super-secret-store-value" not in message

    def test_non_dict_payload_raises_retryable(self) -> None:
        # A non-object payload (transient API/proxy response) must not complete a "successful" full
        # refresh with zero rows and wipe previously synced records; it must raise so the sync retries.
        with pytest.raises(ZapierSupportedStorageRetryableError):
            self._fetch_once(_response([1, 2, 3]))


class TestValidateCredentials:
    def _run(self, response: MagicMock | None = None, side_effect: Exception | None = None) -> tuple[bool, str | None]:
        with patch(f"{MODULE}.make_tracked_session") as factory:
            if side_effect is not None:
                factory.return_value.get.side_effect = side_effect
            else:
                factory.return_value.get.return_value = response
            return validate_credentials("some-secret")

    def test_valid_secret(self) -> None:
        assert self._run(_response({}, status_code=200)) == (True, None)

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            (400, "valid UUID4"),
            (401, "invalid"),
            (500, "500"),
        ],
    )
    def test_error_statuses_map_to_messages(self, status: int, fragment: str) -> None:
        valid, error = self._run(_response({}, status_code=status))
        assert valid is False
        assert error is not None and fragment in error

    def test_network_error_returns_message(self) -> None:
        valid, error = self._run(side_effect=requests.ConnectionError("boom"))
        assert valid is False
        assert error is not None and "boom" in error


class TestSessionIsHardened:
    # Both entry points send the store `secret` as the `X-Secret` header, and every response body is
    # the store's arbitrary customer key/value contents. So both must (a) exclude their requests from
    # HTTP sample capture - a regression to capture=True would persist customer store values to object
    # storage where the name-based scrubbers can't redact unknown keys - and (b) disable redirects,
    # since requests forwards custom headers across cross-host redirects and a regression to
    # allow_redirects=True would let the secret leak to a redirect target.
    def test_get_rows_disables_capture_and_redirects(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as factory:
            factory.return_value.get.return_value = _response({"a": "1"})
            list(get_rows(secret="s", logger=MagicMock()))
        assert factory.call_args.kwargs["capture"] is False
        assert factory.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_disables_capture_and_redirects(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as factory:
            factory.return_value.get.return_value = _response({}, status_code=200)
            validate_credentials("s")
        assert factory.call_args.kwargs["capture"] is False
        assert factory.call_args.kwargs["allow_redirects"] is False


class TestSourceResponse:
    def test_shape_is_full_refresh_keyed_by_store_key(self) -> None:
        response = zapier_supported_storage_source(secret="s", endpoint="records", logger=MagicMock())
        assert response.name == "records"
        assert response.primary_keys == ["key"]
        # No timestamps to partition on - one full-refresh partition.
        assert response.partition_count == 1
        assert response.partition_keys is None

    def test_items_is_lazy(self) -> None:
        # Building the SourceResponse must not issue any request; only iterating items should.
        with patch(f"{MODULE}.make_tracked_session") as factory:
            zapier_supported_storage_source(secret="s", endpoint="records", logger=MagicMock())
            factory.assert_not_called()
