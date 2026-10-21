from datetime import UTC, datetime, timedelta
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FIREWORKS_AI_BASE_URL,
    FireworksAIResumeConfig,
    UsageWindow,
    _usage_row_id,
    _usage_rows,
    _usage_windows,
    get_status_code,
    normalize_account_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    ACCOUNT_USAGE,
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.source import FireworksAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fireworksai import (
    FireworksAISourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FireworksAISource(), FireworksAISourceConfig(api_key="fw_test", account_id="my-account"))


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
        result = _driver().run(
            "models",
            [
                ScriptedResponse(json={"models": [{"name": "m-1"}], "nextPageToken": "tok-2"}),
                ScriptedResponse(json={"models": [{"name": "m-2"}], "nextPageToken": "tok-3"}),
                ScriptedResponse(json={"models": [{"name": "m-3"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"name": "m-1"}, {"name": "m-2"}, {"name": "m-3"}]
        assert result.params("pageToken") == [None, "tok-2", "tok-3"]
        # State is saved after yielding each page (points at the next page), so a crash re-yields
        # the last page rather than skipping it. No save on the final (tokenless) page.
        assert [state.page_token for state in result.saved_states] == ["tok-2", "tok-3"]

    def test_resumes_from_saved_page_token(self) -> None:
        result = _driver().run(
            "models",
            [ScriptedResponse(json={"models": [{"name": "m-9"}]})],
            resume_state=FireworksAIResumeConfig(page_token="tok-9"),
        )

        assert result.raised is None
        assert result.rows == [{"name": "m-9"}]
        assert result.queries[0] == {"pageSize": (str(PAGE_SIZE),), "pageToken": ("tok-9",)}

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
        result = _driver().run(endpoint, [ScriptedResponse(json={collection: [{"name": "row-1"}]})])

        assert result.raised is None
        assert result.rows == [{"name": "row-1"}]
        assert result.requests[0].url.split("?", 1)[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/{collection}"


class TestEmptyPages:
    @parameterized.expand(
        [
            # Proto3 JSON omits empty repeated fields — a missing collection key is an empty page.
            ("collection_key_omitted", {"totalSize": 0}),
            ("empty_collection", {"models": []}),
        ]
    )
    def test_empty_page_yields_no_rows(self, _name: str, body: dict[str, Any]) -> None:
        result = _driver().run("models", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestGetStatusCode:
    def test_default_probe_hits_models_with_bearer_auth(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            status = get_status_code("fw_test", "my-account")

        assert status == 200
        assert network.requests_log[0].url == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models?pageSize=1"
        assert network.requests_log[0].param("pageSize") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer fw_test"


class TestFireworksAISourceResponse:
    @parameterized.expand(list(FIREWORKS_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json={})))
        assert result.raised is None
        response = result.response
        assert response is not None
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


class TestAccountUsageTransport:
    def test_checkpoint_saved_after_each_window_names_the_next_one(self) -> None:
        watermark = datetime.now(UTC) - timedelta(days=40)
        result = _driver().run(
            ACCOUNT_USAGE,
            [ScriptedResponse(json={}), ScriptedResponse(json={})],
            incremental_field="startTime",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        # One save only: the final window has nothing after it to resume into.
        saved = [state.usage_window_start for state in result.saved_states]
        assert len(saved) == 1
        # The checkpoint names the first window not yet yielded, so a restart replays at most the
        # window that was in progress.
        # The request param is RFC 3339 to the second, so compare at that resolution.
        next_start = result.requests[1].param("startTime")
        assert next_start is not None
        assert datetime.fromisoformat(saved[0]).replace(microsecond=0) == datetime.strptime(
            next_start, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)

    def test_resumes_from_the_saved_window(self) -> None:
        result = _driver().run(
            ACCOUNT_USAGE,
            [ScriptedResponse(json={})],
            resume_state=FireworksAIResumeConfig(
                usage_window_start=(datetime.now(UTC) - timedelta(days=5)).isoformat()
            ),
            incremental_field="startTime",
            db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=90),
        )

        # Without honouring the checkpoint this would re-walk all 90 days as three windows.
        assert result.raised is None
        assert len(result.requests) == 1

    def test_http_error_propagates_so_the_job_can_classify_it(self) -> None:
        result = _driver().run(ACCOUNT_USAGE, [ScriptedResponse(status=401)])
        assert isinstance(result.raised, HTTPError)
        assert "401 Client Error" in str(result.raised)


class TestAccountUsageStatusProbe:
    def test_probe_sends_a_window_because_billing_usage_rejects_a_bare_call(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert get_status_code("fw_test", "my-account", ACCOUNT_USAGE) == 200

        request = network.requests_log[0]
        assert request.url.split("?", 1)[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/billingUsage"
        # A pageSize-only probe would 400 here and read back as a bad API key.
        assert set(request.query) == {"startTime", "endTime"}
