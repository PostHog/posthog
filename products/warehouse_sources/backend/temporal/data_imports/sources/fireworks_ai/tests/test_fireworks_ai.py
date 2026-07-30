from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai import fireworks_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FIREWORKS_AI_BASE_URL,
    FireworksAIResumeConfig,
    _extract_rows,
    fireworks_ai_source,
    get_rows,
    get_status_code,
    normalize_account_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
)


def _manager(resume_token: str | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_token is not None
    manager.load_state.return_value = FireworksAIResumeConfig(page_token=resume_token) if resume_token else None
    return manager


def _collect(
    monkeypatch: Any, endpoint: str, payloads: list[Any], manager: MagicMock | None = None
) -> tuple[list[dict], list[dict[str, Any]], MagicMock]:
    """Feed successive `payloads` from _fetch and return (rows, recorded fetch calls, manager)."""
    calls: list[dict[str, Any]] = []
    remaining = list(payloads)

    def fake_fetch(session: Any, url: str, params: Any, headers: dict[str, str], logger: Any) -> Any:
        calls.append({"url": url, "params": params, "headers": headers})
        return remaining.pop(0)

    monkeypatch.setattr(fireworks_ai, "_fetch", fake_fetch)
    manager = manager if manager is not None else _manager()

    rows: list[dict] = []
    for batch in get_rows(
        api_key="fw_test",
        account_id="my-account",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,
    ):
        rows.extend(batch)
    return rows, calls, manager


class TestNormalizeAccountId:
    @parameterized.expand(
        [
            ("bare_id", "my-account", "my-account"),
            ("resource_prefix", "accounts/my-account", "my-account"),
            ("whitespace_and_slashes", "  accounts/my-account/ ", "my-account"),
        ]
    )
    def test_reduces_input_to_bare_account_id(self, _name: str, entered: str, expected: str) -> None:
        assert normalize_account_id(entered) == expected


class TestExtractRows:
    @parameterized.expand(
        [
            ("rows_present", {"models": [{"name": "m-1"}, {"name": "m-2"}]}, [{"name": "m-1"}, {"name": "m-2"}]),
            # Proto3 JSON omits empty repeated fields — a missing collection key is an empty page.
            ("collection_key_omitted", {"totalSize": 0}, []),
            ("empty_collection", {"models": []}, []),
            ("non_dict_rows_dropped", {"models": ["not-a-row", {"name": "m-1"}]}, [{"name": "m-1"}]),
        ]
    )
    def test_unwraps_aip_list_envelope(self, _name: str, payload: Any, expected: list[dict]) -> None:
        assert _extract_rows(payload, "models", "models") == expected

    @parameterized.expand(
        [
            ("string_body", "error"),
            ("null_body", None),
            ("bare_array", [{"name": "m-1"}]),
            ("collection_not_a_list", {"models": "oops"}),
        ]
    )
    def test_unexpected_shape_raises(self, _name: str, payload: Any) -> None:
        # A silently-swallowed shape change would sync an empty table and look like data loss.
        with pytest.raises(ValueError):
            _extract_rows(payload, "models", "models")


class TestGetRowsPagination:
    def test_single_page_yields_rows_and_saves_no_state(self, monkeypatch: Any) -> None:
        rows, calls, manager = _collect(monkeypatch, "models", [{"models": [{"name": "m-1"}]}])
        assert rows == [{"name": "m-1"}]
        assert len(calls) == 1
        assert calls[0]["url"] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"
        assert calls[0]["params"] == {"pageSize": PAGE_SIZE}
        assert calls[0]["headers"]["Authorization"] == "Bearer fw_test"
        manager.save_state.assert_not_called()

    def test_follows_next_page_token_and_saves_state_after_each_page(self, monkeypatch: Any) -> None:
        rows, calls, manager = _collect(
            monkeypatch,
            "models",
            [
                {"models": [{"name": "m-1"}], "nextPageToken": "tok-2"},
                {"models": [{"name": "m-2"}], "nextPageToken": "tok-3"},
                {"models": [{"name": "m-3"}]},
            ],
        )
        assert rows == [{"name": "m-1"}, {"name": "m-2"}, {"name": "m-3"}]
        assert [c["params"].get("pageToken") for c in calls] == [None, "tok-2", "tok-3"]
        # State is saved after yielding each page, so a crash re-yields the last page rather
        # than skipping it.
        saved = [call.args[0].page_token for call in manager.save_state.call_args_list]
        assert saved == ["tok-2", "tok-3"]

    def test_empty_next_page_token_terminates(self, monkeypatch: Any) -> None:
        _rows, calls, manager = _collect(monkeypatch, "models", [{"models": [{"name": "m-1"}], "nextPageToken": ""}])
        assert len(calls) == 1
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_page_token(self, monkeypatch: Any) -> None:
        rows, calls, _manager_ = _collect(
            monkeypatch, "models", [{"models": [{"name": "m-9"}]}], manager=_manager(resume_token="tok-9")
        )
        assert rows == [{"name": "m-9"}]
        assert calls[0]["params"] == {"pageSize": PAGE_SIZE, "pageToken": "tok-9"}

    def test_camel_case_collections_resolve_path_and_data_key(self, monkeypatch: Any) -> None:
        rows, calls, _manager_ = _collect(
            monkeypatch,
            "supervised_fine_tuning_jobs",
            [{"supervisedFineTuningJobs": [{"name": "sft-1"}]}],
        )
        assert rows == [{"name": "sft-1"}]
        assert calls[0]["url"] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/supervisedFineTuningJobs"

    def test_pasted_resource_prefix_does_not_double_the_path(self, monkeypatch: Any) -> None:
        calls: list[str] = []

        def fake_fetch(session: Any, url: str, params: Any, headers: Any, logger: Any) -> Any:
            calls.append(url)
            return {"models": []}

        monkeypatch.setattr(fireworks_ai, "_fetch", fake_fetch)
        list(
            get_rows(
                api_key="fw_test",
                account_id="accounts/my-account",
                endpoint="models",
                logger=MagicMock(),
                resumable_source_manager=_manager(),
            )
        )
        assert calls[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"


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
        good.json.return_value = {"models": []}

        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(fireworks_ai._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = fireworks_ai._fetch(session, f"{FIREWORKS_AI_BASE_URL}/x", None, {}, MagicMock())

        assert result == {"models": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately_without_query_string(self) -> None:
        unauthorized = MagicMock()
        unauthorized.status_code = 401
        unauthorized.ok = False
        unauthorized.reason = "Unauthorized"
        unauthorized.url = f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models?pageToken=tok-secret"

        session = MagicMock()
        session.get.return_value = unauthorized

        with pytest.raises(requests.HTTPError) as exc_info:
            fireworks_ai._fetch(session, f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models", None, {}, MagicMock())

        # The rebuilt error must not leak the pagination token, and its prefix must stay stable
        # for get_non_retryable_errors() matching.
        message = str(exc_info.value)
        assert "401 Client Error: Unauthorized for url: https://api.fireworks.ai" in message
        assert "pageToken" not in message
        assert session.get.call_count == 1


class TestGetStatusCode:
    def test_default_probe_hits_models_with_bearer_auth(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            status = get_status_code("fw_test", "my-account")

        assert status == 200
        args, kwargs = session.get.call_args
        assert args[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"
        assert kwargs["params"] == {"pageSize": 1}
        assert kwargs["headers"]["Authorization"] == "Bearer fw_test"

    def test_schema_probe_hits_that_endpoints_path(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            get_status_code("fw_test", "my-account", "evaluation_jobs")

        args, _kwargs = session.get.call_args
        assert args[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/evaluationJobs"


class TestFireworksAISourceResponse:
    @parameterized.expand(list(FIREWORKS_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        response = fireworks_ai_source(
            api_key="fw_test",
            account_id="my-account",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
        cfg = FIREWORKS_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # Partition on the stable creation timestamp — never updateTime — so partitions
        # don't rewrite on every sync.
        assert response.partition_keys == [cfg.partition_key]
        assert response.partition_mode == "datetime"
