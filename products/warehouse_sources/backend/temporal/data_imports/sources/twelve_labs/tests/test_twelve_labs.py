from datetime import UTC, date, datetime
from typing import Any, cast

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twelvelabs import (
    TwelveLabsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.source import TwelveLabsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.twelve_labs import (
    TwelveLabsResumeConfig,
    _format_incremental_value,
    validate_credentials,
)


def _page(rows: list[dict[str, Any]], page: int, total_page: int, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={"data": rows, "page_info": {"page": page, "total_page": total_page, "limit_per_page": 50}},
    )


def _run(
    endpoint: str,
    script: Script,
    resume_state: TwelveLabsResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    driver = SourceDriver(TwelveLabsSource(), TwelveLabsSourceConfig(api_key="tlk"))
    return driver.run(endpoint, script, resume_state=resume_state, **kwargs)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        # A wrong RFC 3339 shape (e.g. a +00:00 offset) breaks the server-side created_at/updated_at
        # filter, so the exact string matters.
        assert _format_incremental_value(value) == expected


class TestValidateCredentials:
    def test_credentialed_session_redacts_key_and_refuses_redirects(self) -> None:
        # The x-api-key value must never reach tracked telemetry, and a 30x must not replay it to
        # another host, so validation builds the session with both guards on.
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("tlk_key")
        assert network.session_options == [{"redact_values": ("tlk_key",), "allow_redirects": False}]


class TestTopLevelPagination:
    def test_saves_resume_state_after_each_page_but_not_on_last(self) -> None:
        # State is saved after yielding a page (so a crash re-yields, not skips) and only while more
        # pages remain, so we never bookmark past the end of the list.
        result = _run(
            "indexes",
            [_page([{"_id": "a"}], page=1, total_page=2), _page([{"_id": "b"}], page=2, total_page=2)],
        )

        assert [s.next_page for s in result.saved_states] == [2]

    def test_resumes_from_saved_page(self) -> None:
        result = _run(
            "indexes",
            [_page([{"_id": "b"}], page=2, total_page=2)],
            resume_state=TwelveLabsResumeConfig(next_page=2),
        )

        # Only page 2 is fetched — the resume skips page 1.
        assert [r["_id"] for r in result.rows] == ["b"]
        assert len(result.requests) == 1
        assert result.requests[0].param("page") == "2"

    def test_incremental_applies_server_side_filter(self) -> None:
        result = _run(
            "indexes",
            [_page([{"_id": "a"}], page=1, total_page=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )

        request = result.requests[0]
        assert request.param("sort_by") == "updated_at"
        assert request.param("sort_option") == "asc"
        assert request.param("updated_at") == "2026-03-04T02:58:14.000Z"


class TestFanOut:
    def test_injects_parent_index_id_into_every_video_row(self) -> None:
        # /indexes returns two indexes, each with one video page. The parent index_id must land on
        # every row so the [index_id, _id] primary key stays unique table-wide.
        result = _run(
            "videos",
            [
                _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),
                _page([{"_id": "v1"}], page=1, total_page=1),
                _page([{"_id": "v2"}], page=1, total_page=1),
            ],
        )

        assert result.rows == [{"_id": "v1", "index_id": "idx1"}, {"_id": "v2", "index_id": "idx2"}]
        assert result.paths == [
            "/v1.3/indexes",
            "/v1.3/indexes/idx1/videos",
            "/v1.3/indexes/idx2/videos",
        ]
        # Child pages carry the videos sort params, and the resolve param never leaks into the query.
        assert result.requests[1].param("sort_by") == "created_at"
        assert result.requests[1].param("page_limit") == "50"
        assert result.requests[1].param("index_id") is None

    def test_resume_skips_completed_index(self) -> None:
        # Bookmarked with idx1 already completed: idx1's videos must not be re-fetched.
        result = _run(
            "videos",
            [
                _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),
                _page([{"_id": "v2"}], page=1, total_page=1),
            ],
            resume_state=TwelveLabsResumeConfig(
                fanout_state={"completed": ["/indexes/idx1/videos"], "current": None, "child_state": None}
            ),
        )

        assert result.rows == [{"_id": "v2", "index_id": "idx2"}]
        assert result.paths == ["/v1.3/indexes", "/v1.3/indexes/idx2/videos"]

    def test_asset_transcriptions_skip_assets_without_a_transcription(self) -> None:
        # An asset with no transcription 404s. That must skip the asset, not fail the sync, and each
        # transcription row must carry its asset's id and creation time.
        result = _run(
            "asset_transcriptions",
            [
                _page(
                    [
                        {"_id": "a1", "created_at": "2026-08-01T00:00:00Z"},
                        {"_id": "a2", "created_at": "2026-08-02T00:00:00Z"},
                    ],
                    page=1,
                    total_page=1,
                ),
                ScriptedResponse(status=404, json={"code": "resource_not_found"}),
                ScriptedResponse(
                    json={"status": "ready", "sentences": [{"start": 0.0, "end": 1.5, "value": "Hello."}]}
                ),
            ],
        )

        assert result.rows == [
            {
                "status": "ready",
                "sentences": [{"start": 0.0, "end": 1.5, "value": "Hello."}],
                "asset_id": "a2",
                "asset_created_at": "2026-08-02T00:00:00Z",
            }
        ]
        assert result.paths == [
            "/v1.3/assets",
            "/v1.3/assets/a1/transcription",
            "/v1.3/assets/a2/transcription",
        ]
        assert result.requests[0].query["asset_types"] == ("video", "audio")
        assert dict(result.requests[1].query) == {"include": ("sentences,utterances",)}

    def test_item_tags_fan_out_over_each_store_and_its_video_items(self) -> None:
        # The tags path needs the store id from two levels up, so it must be carried through the
        # items level. Image items hold no tags and must not cost a request.
        tag = {"_id": "t1", "knowledge_store_id": "ks2", "item_id": "i2", "start_sec": 1.5, "end_sec": None}
        result = _run(
            "knowledge_store_item_tags",
            [
                _page([{"_id": "ks1"}, {"_id": "ks2"}], page=1, total_page=1),
                _page([{"_id": "i1", "asset_type": "image"}], page=1, total_page=1),
                _page([{"_id": "i2", "asset_type": "video"}], page=1, total_page=1),
                _page([tag], page=1, total_page=1),
            ],
        )

        assert result.rows == [tag]
        assert result.paths == [
            "/v1.3/knowledge-stores",
            "/v1.3/knowledge-stores/ks1/items",
            "/v1.3/knowledge-stores/ks2/items",
            "/v1.3/knowledge-stores/ks2/items/i2/tags",
        ]
        assert result.requests[1].param("sort_option") == "asc"
        assert result.requests[3].param("knowledge_store_id") is None
        assert result.response is not None
        assert result.response.supports_resume is False

    def test_old_shape_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved before the
        # migration must still construct.
        state = TwelveLabsResumeConfig(**cast("dict[str, Any]", {"next_page": 2, "index_id": "idx2"}))
        assert state.next_page == 2
        assert state.index_id == "idx2"
        assert state.fanout_state is None


class TestTwelveLabsSourceResponse:
    @parameterized.expand([("indexes", ["_id"]), ("tasks", ["_id"]), ("videos", ["index_id", "_id"])])
    def test_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _run(endpoint, []).response
        assert response is not None
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]


class TestNonRetryableCredentialErrors:
    def test_unauthorized_raises_matchable_httperror(self) -> None:
        # get_non_retryable_errors matches the base-host 401 text, so the raised HTTPError message
        # must carry that stable prefix (not just the per-request path).
        result = _run("indexes", [ScriptedResponse(status=401, json={})])

        assert result.raised is not None
        assert "401 Client Error: Unauthorized for url: https://api.twelvelabs.io" in str(result.raised)
