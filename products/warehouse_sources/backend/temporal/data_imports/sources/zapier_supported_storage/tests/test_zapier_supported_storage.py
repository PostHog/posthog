from typing import Any

import pytest
from unittest.mock import MagicMock

import pyarrow as pa
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zapiersupportedstorage import (
    ZapierSupportedStorageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.source import (
    ZapierSupportedStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.zapier_supported_storage import (
    ZapierSupportedStorageRetryableError,
    validate_credentials,
    zapier_supported_storage_source,
)


def _driver() -> SourceDriver:
    return SourceDriver(ZapierSupportedStorageSource(), ZapierSupportedStorageSourceConfig(secret="s"))


def _sync(script: Any) -> DriveResult:
    return _driver().run("records", script)


def _rows_from_store(store: Any) -> list[dict[str, Any]]:
    result = _sync([ScriptedResponse(json=store)])
    out: list[dict[str, Any]] = []
    for table in result.items:
        assert isinstance(table, pa.Table)
        out.extend(table.to_pylist())
    return out


class TestGetRows:
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
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        result = _sync(always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, ZapierSupportedStorageRetryableError)

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_raise_scrubbed_http_error(self, status: int) -> None:
        # 4xx can't be fixed by retrying, so an HTTPError must surface immediately. The message must
        # keep the "<status> Client Error ... for url: https://store.zapier.com/api/records" prefix
        # (get_non_retryable_errors matches on it) but never echo the response body, which can hold
        # arbitrary store secrets and would otherwise leak into logs and latest_error.
        secret_body = {"leaked": "super-secret-store-value"}
        result = _sync([ScriptedResponse(status=status, json=secret_body)])

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
        assert "https://store.zapier.com/api/records" in message
        assert "super-secret-store-value" not in message
        assert len(result.requests) == 1

    def test_non_dict_payload_raises_retryable(self) -> None:
        # A non-object payload (transient API/proxy response) must not complete a "successful" full
        # refresh with zero rows and wipe previously synced records; it must raise so the sync retries.
        result = _sync(always(ScriptedResponse(json=[1, 2, 3])))

        assert isinstance(result.raised, ZapierSupportedStorageRetryableError)
        assert result.rows == []


class TestValidateCredentials:
    def test_valid_secret(self) -> None:
        with scripted_network([ScriptedResponse(json={})]):
            assert validate_credentials("some-secret") == (True, None)

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            (400, "valid UUID4"),
        ],
    )
    def test_error_statuses_map_to_messages(self, status: int, fragment: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            valid, error = validate_credentials("some-secret")
        assert valid is False
        assert error is not None and fragment in error


class TestSessionIsHardened:
    # Both entry points send the store `secret` as the `X-Secret` header, and every response body is
    # the store's arbitrary customer key/value contents. So both must (a) exclude their requests from
    # HTTP sample capture - a regression to capture=True would persist customer store values to object
    # storage where the name-based scrubbers can't redact unknown keys - and (b) disable redirects,
    # since requests forwards custom headers across cross-host redirects and a regression to
    # allow_redirects=True would let the secret leak to a redirect target.
    def test_get_rows_disables_capture_and_redirects(self) -> None:
        result = _sync([ScriptedResponse(json={"a": "1"})])

        assert result.session_options[0]["capture"] is False
        assert result.session_options[0]["allow_redirects"] is False

    def test_validate_credentials_disables_capture_and_redirects(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("s")

        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["allow_redirects"] is False


class TestSourceResponse:
    def test_items_is_lazy(self) -> None:
        # Building the SourceResponse must not issue any request; only iterating items should.
        with scripted_network([]) as network:
            zapier_supported_storage_source(secret="s", endpoint="records", logger=MagicMock())

        assert network.requests_log == []
        assert network.session_options == []
