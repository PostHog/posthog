import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai import fireworks_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FIREWORKS_AI_BASE_URL,
    FireworksAIResumeConfig,
    UsageWindow,
    _usage_row_id,
    _usage_rows,
    _usage_windows,
    fireworks_ai_source,
    get_status_code,
    normalize_account_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    ACCOUNT_USAGE,
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FireworksAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(
    endpoint: str, responses: list[Response], manager: mock.MagicMock, account_id: str = "my-account"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params, urls = _wire(session, responses)
        source_response = fireworks_ai_source(
            api_key="fw_test",
            account_id=account_id,
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        rows = [row for page in cast("Iterable[Any]", source_response.items()) for row in page]
    return rows, params, urls


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


class TestPagination:
    def test_follows_next_page_token_and_saves_state_after_each_page(self) -> None:
        manager = _make_manager()
        rows, params, _urls = _rows(
            "models",
            [
                _response({"models": [{"name": "m-1"}], "nextPageToken": "tok-2"}),
                _response({"models": [{"name": "m-2"}], "nextPageToken": "tok-3"}),
                _response({"models": [{"name": "m-3"}]}),
            ],
            manager,
        )

        assert rows == [{"name": "m-1"}, {"name": "m-2"}, {"name": "m-3"}]
        assert [p.get("pageToken") for p in params] == [None, "tok-2", "tok-3"]
        # State is saved after yielding each page (points at the next page), so a crash re-yields
        # the last page rather than skipping it. No save on the final (tokenless) page.
        saved = [call.args[0].page_token for call in manager.save_state.call_args_list]
        assert saved == ["tok-2", "tok-3"]

    def test_resumes_from_saved_page_token(self) -> None:
        manager = _make_manager(FireworksAIResumeConfig(page_token="tok-9"))
        rows, params, _urls = _rows("models", [_response({"models": [{"name": "m-9"}]})], manager)

        assert rows == [{"name": "m-9"}]
        assert params[0] == {"pageSize": PAGE_SIZE, "pageToken": "tok-9"}

    @parameterized.expand(
        [
            ("supervised_fine_tuning_jobs", "supervisedFineTuningJobs"),
            # The API calls this collection rlorTrainerJobs, so neither the path nor the data key
            # can be derived from the table name.
            ("reinforcement_fine_tuning_steps", "rlorTrainerJobs"),
            ("dpo_jobs", "dpoJobs"),
        ]
    )
    def test_camel_case_collections_resolve_path_and_data_key(self, endpoint: str, collection: str) -> None:
        manager = _make_manager()
        rows, _params, urls = _rows(endpoint, [_response({collection: [{"name": "row-1"}]})], manager)

        assert rows == [{"name": "row-1"}]
        assert urls[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/{collection}"


class TestEmptyPages:
    @parameterized.expand(
        [
            # Proto3 JSON omits empty repeated fields — a missing collection key is an empty page.
            ("collection_key_omitted", {"totalSize": 0}),
            ("empty_collection", {"models": []}),
        ]
    )
    def test_empty_page_yields_no_rows(self, _name: str, body: dict[str, Any]) -> None:
        manager = _make_manager()
        rows, params, _urls = _rows("models", [_response(body)], manager)
        assert rows == []
        assert len(params) == 1
        manager.save_state.assert_not_called()


class TestGetStatusCode:
    def test_default_probe_hits_models_with_bearer_auth(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            status = get_status_code("fw_test", "my-account")

        assert status == 200
        args, kwargs = session.get.call_args
        assert args[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"
        assert kwargs["params"] == {"pageSize": 1}
        assert kwargs["headers"]["Authorization"] == "Bearer fw_test"


class TestFireworksAISourceResponse:
    @parameterized.expand(list(FIREWORKS_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        response = fireworks_ai_source(
            api_key="fw_test",
            account_id="my-account",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )
        cfg = FIREWORKS_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # Partition on the stable creation timestamp — never updateTime — so partitions
        # don't rewrite on every sync.
        assert response.partition_keys == [cfg.partition_key]
        assert response.partition_mode == "datetime"


_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

_SERVERLESS_BUCKET = {
    "startTime": "2026-06-01T00:00:00Z",
    "endTime": "2026-06-02T00:00:00Z",
    "modelName": "accounts/my-account/models/llama",
    "usageType": "TEXT_INFERENCE",
    "apiKeyId": "key-1",
    "group": {"model_name": "accounts/my-account/models/llama"},
    "promptTokens": "100",
    "completionTokens": "20",
}


class TestUsageWindows:
    @parameterized.expand(
        [
            ("watermark_at_now", timedelta(0)),
            ("watermark_ahead_of_now", timedelta(days=3)),
        ]
    )
    def test_caught_up_watermark_still_re_reads_the_open_day(self, _name: str, offset: timedelta) -> None:
        # The newest bucket keeps accumulating until its day closes. Without the clamp this builds
        # an inverted window, which UsageWindow rejects and the API would 400 on.
        windows = _usage_windows(_NOW + offset, _NOW)

        assert len(windows) == 1
        assert windows[0] == UsageWindow(start=_NOW - timedelta(days=1), end=_NOW)


class TestUsageRows:
    def test_each_array_becomes_rows_tagged_with_its_category(self) -> None:
        rows = _usage_rows(
            {
                "serverlessCosts": [_SERVERLESS_BUCKET],
                "dedicatedCosts": [{"startTime": "2026-06-01T00:00:00Z", "deploymentId": "dep-1"}],
                "trainingCosts": [{"startTime": "2026-06-01T00:00:00Z", "jobId": "job-1"}],
            }
        )

        assert [row["usageCategory"] for row in rows] == ["serverless", "dedicated", "training"]
        # The API's own fields survive alongside the two synthesized ones.
        assert rows[0]["promptTokens"] == "100"
        assert rows[1]["deploymentId"] == "dep-1"

    @parameterized.expand(
        [
            ("collection_key_omitted", {}),
            ("empty_arrays", {"serverlessCosts": [], "dedicatedCosts": [], "trainingCosts": []}),
            ("null_array", {"serverlessCosts": None}),
        ]
    )
    def test_window_with_no_usage_yields_no_rows(self, _name: str, payload: dict[str, Any]) -> None:
        assert _usage_rows(payload) == []


class TestUsageRowId:
    @parameterized.expand(
        [
            ("start_time", {"startTime": "2026-06-02T00:00:00Z"}),
            ("model_name", {"modelName": "accounts/my-account/models/mixtral"}),
            ("usage_type", {"usageType": "IMAGE_INFERENCE"}),
            ("api_key_id", {"apiKeyId": "key-2"}),
            ("group_dimension", {"group": {"model_name": "accounts/my-account/models/llama", "user_id": "u-1"}}),
            # A dimension the API omits must not hash the same as one it returns empty, or two
            # distinct buckets collapse onto one row.
            ("absent_dimension", {"apiKeyId": None}),
            ("empty_dimension", {"apiKeyId": ""}),
        ]
    )
    def test_each_dimension_produces_a_distinct_id(self, _name: str, override: dict[str, Any]) -> None:
        assert _usage_row_id("serverless", {**_SERVERLESS_BUCKET, **override}) != _usage_row_id(
            "serverless", _SERVERLESS_BUCKET
        )


def _run_usage(
    manager: mock.MagicMock,
    payloads: list[dict[str, Any]],
    db_incremental_field_last_value: Any = None,
) -> tuple[list[dict[str, Any]], list[mock.MagicMock]]:
    session = mock.MagicMock()
    session.get.side_effect = [mock.MagicMock(**{"json.return_value": payload}) for payload in payloads]

    with mock.patch.object(fireworks_ai, "make_tracked_session", return_value=session):
        source_response = fireworks_ai_source(
            api_key="fw_test",
            account_id="my-account",
            endpoint=ACCOUNT_USAGE,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        rows = [row for batch in cast("Iterable[Any]", source_response.items()) for row in batch]
    return rows, session.get.call_args_list


class TestAccountUsageTransport:
    def test_checkpoint_saved_after_each_window_names_the_next_one(self) -> None:
        manager = _make_manager()
        watermark = datetime.now(UTC) - timedelta(days=40)
        _rows_out, calls = _run_usage(manager, [{}, {}], db_incremental_field_last_value=watermark)

        # One save only: the final window has nothing after it to resume into.
        saved = [call.args[0].usage_window_start for call in manager.save_state.call_args_list]
        assert len(saved) == 1
        # The checkpoint names the first window not yet yielded, so a restart replays at most the
        # window that was in progress.
        # The request param is RFC 3339 to the second, so compare at that resolution.
        assert datetime.fromisoformat(saved[0]).replace(microsecond=0) == datetime.strptime(
            calls[1].kwargs["params"]["startTime"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)

    def test_resumes_from_the_saved_window(self) -> None:
        manager = _make_manager(
            FireworksAIResumeConfig(usage_window_start=(datetime.now(UTC) - timedelta(days=5)).isoformat())
        )
        _rows_out, calls = _run_usage(
            manager, [{}], db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=90)
        )

        # Without honouring the checkpoint this would re-walk all 90 days as three windows.
        assert len(calls) == 1

    def test_http_error_propagates_so_the_job_can_classify_it(self) -> None:
        session = mock.MagicMock()
        session.get.return_value.raise_for_status.side_effect = Exception(
            "401 Client Error: Unauthorized for url: https://api.fireworks.ai/v1/accounts/my-account/billingUsage"
        )

        with mock.patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            source_response = fireworks_ai_source(
                api_key="fw_test",
                account_id="my-account",
                endpoint=ACCOUNT_USAGE,
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
            )
            with pytest.raises(Exception, match="401 Client Error"):
                list(cast("Iterable[Any]", source_response.items()))


class TestAccountUsageStatusProbe:
    def test_probe_sends_a_window_because_billing_usage_rejects_a_bare_call(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            assert get_status_code("fw_test", "my-account", ACCOUNT_USAGE) == 200

        args, kwargs = session.get.call_args
        assert args[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/billingUsage"
        # A pageSize-only probe would 400 here and read back as a bad API key.
        assert set(kwargs["params"]) == {"startTime", "endTime"}
