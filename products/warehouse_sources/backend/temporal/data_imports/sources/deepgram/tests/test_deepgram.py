from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import deepgram as deepgram_mod
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import (
    DEEPGRAM_BASE_URL,
    DeepgramResumeConfig,
    _format_start_date,
    _format_start_value,
    _normalize_row,
    _redact_url_userinfo,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import DEEPGRAM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.source import DeepgramSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deepgram import (
    DeepgramSourceConfig,
)

# The framework injects the parent project id under this key before the child data_map lifts it out.
PARENT_KEY = "_projects_project_id"


def _driver() -> SourceDriver:
    return SourceDriver(DeepgramSource(), DeepgramSourceConfig(api_key="token"))


def _response(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestFormatStartValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            # Deepgram rejects fractional seconds, so a cursor with microseconds is floored to the second.
            ("subsecond_datetime", datetime(2026, 3, 4, 2, 58, 14, 987654, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_start_value(value) == expected


class TestNormalizeRow:
    def test_injects_project_id(self) -> None:
        row = _normalize_row(DEEPGRAM_ENDPOINTS["members"], {PARENT_KEY: "proj-1", "member_id": "m1"})
        assert row["project_id"] == "proj-1"
        assert row["member_id"] == "m1"
        assert PARENT_KEY not in row

    @parameterized.expand(
        [
            ("basic_auth", "https://user:pass@hooks.example.com/cb", "https://hooks.example.com/cb"),
            ("no_creds", "https://hooks.example.com/cb", "https://hooks.example.com/cb"),
            ("not_a_url", "not-a-url", "not-a-url"),
        ]
    )
    def test_redacts_callback_userinfo(self, _name: str, callback: str, expected: str) -> None:
        # A callback URL can embed Basic Auth creds; they must not reach the warehouse.
        row = _normalize_row(
            DEEPGRAM_ENDPOINTS["requests"], {PARENT_KEY: "proj-1", "request_id": "r1", "callback": callback}
        )
        assert row["callback"] == expected

    def test_missing_primary_key_raises(self) -> None:
        # A row missing request_id would let the merge overwrite unrelated rows; fail instead of emit.
        with pytest.raises(ValueError, match="request_id"):
            _normalize_row(DEEPGRAM_ENDPOINTS["requests"], {PARENT_KEY: "proj-1", "created": "2026-01-01"})


class TestRedactUrlUserinfo:
    def test_malformed_url_passthrough(self) -> None:
        assert _redact_url_userinfo("http://[") == "http://["


class TestFanOut:
    def test_fans_out_over_projects_and_injects_project_id(self) -> None:
        result = _driver().run(
            "members",
            [
                _response({"projects": [{"project_id": "p1"}, {"project_id": "p2"}]}),
                _response({"members": [{"member_id": "m1"}]}),
                _response({"members": [{"member_id": "m2"}]}),
            ],
        )

        assert result.raised is None
        assert [(r["member_id"], r["project_id"]) for r in result.rows] == [("m1", "p1"), ("m2", "p2")]
        assert result.urls == [
            f"{DEEPGRAM_BASE_URL}/projects",
            f"{DEEPGRAM_BASE_URL}/projects/p1/members",
            f"{DEEPGRAM_BASE_URL}/projects/p2/members",
        ]


class TestRequestsPagination:
    def test_checkpoint_advances_page_after_yield(self) -> None:
        with patch.object(deepgram_mod, "REQUESTS_PAGE_SIZE", 2):
            result = _driver().run(
                "requests",
                [
                    _response({"projects": [{"project_id": "p1"}]}),
                    _response({"requests": [{"request_id": "r1"}, {"request_id": "r2"}]}),
                    _response({"requests": [{"request_id": "r3"}]}),
                ],
                should_use_incremental_field=True,
            )

        assert result.raised is None
        assert result.params("page") == [None, "0", "1"]
        assert result.params("limit") == [None, "2", "2"]
        assert [row["request_id"] for row in result.rows] == ["r1", "r2", "r3"]
        # After yielding the first full page we persist the next page so a crash re-fetches page 1.
        child_pages = [
            state.fanout_state.get("child_state", {}).get("page")
            for state in result.saved_states
            if state.fanout_state and state.fanout_state.get("child_state")
        ]
        assert 1 in child_pages


class TestRequestsIncremental:
    def test_start_filter_only_on_requests(self) -> None:
        result = _driver().run(
            "requests",
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response({"requests": []}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[-1].param("start") == "2026-03-04T02:58:14+00:00"
        assert result.requests[-1].param("limit") == str(deepgram_mod.REQUESTS_PAGE_SIZE)
        # The parent project enumeration carries no incremental filter.
        assert result.requests[0].param("start") is None


class TestResume:
    def test_skips_completed_project(self) -> None:
        # p1 already fully synced last run — only projects (re-enumerated) and p2 are fetched.
        resume = DeepgramResumeConfig(
            fanout_state={"completed": ["/projects/p1/members"], "current": None, "child_state": None}
        )
        result = _driver().run(
            "members",
            [
                _response({"projects": [{"project_id": "p1"}, {"project_id": "p2"}]}),
                _response({"members": [{"member_id": "m2"}]}),
            ],
            resume_state=resume,
        )

        assert result.raised is None
        assert [r["member_id"] for r in result.rows] == ["m2"]
        assert result.urls == [
            f"{DEEPGRAM_BASE_URL}/projects",
            f"{DEEPGRAM_BASE_URL}/projects/p2/members",
        ]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("requests_is_incremental", "requests", "desc", ["project_id", "request_id"]),
            ("members_full_refresh", "members", "asc", ["project_id", "member_id"]),
            ("projects_top_level", "projects", "asc", ["project_id"]),
        ]
    )
    def test_shape(self, _name: str, endpoint: str, sort_mode: str, primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [])
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("token") is expected
        assert network.requests_log[0].path == "/v1/projects"
        assert network.requests_log[0].headers["authorization"] == "Token token"


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("iso_string", "2026-03-04T02:58:14+00:00", "2026-03-04"),
        ]
    )
    def test_truncates_to_whole_days(self, _name: str, value: Any, expected: str) -> None:
        # The usage and billing endpoints reject anything but YYYY-MM-DD with a 400.
        assert _format_start_date(value) == expected


class TestModelsEndpoint:
    @parameterized.expand(
        [
            (
                "both_catalogues",
                {"stt": [{"uuid": "u1", "name": "nova-3"}], "tts": [{"uuid": "u2", "name": "zeus"}]},
                [("u1", "stt"), ("u2", "tts")],
            ),
            # A project with no text-to-speech access omits the key entirely rather than sending [].
            ("missing_catalogue", {"stt": [{"uuid": "u1"}]}, [("u1", "stt")]),
            ("empty_catalogues", {"stt": [], "tts": []}, []),
        ]
    )
    def test_splits_parallel_catalogues_into_rows(
        self, _name: str, body: dict[str, Any], expected: list[tuple[str, str]]
    ) -> None:
        # The body is two parallel arrays, not one list of rows, and only the array a model came from
        # records whether it is speech-to-text or text-to-speech.
        result = _driver().run("models", [_response({"projects": [{"project_id": "p1"}]}), _response(body)])

        assert result.raised is None
        assert [(r["uuid"], r["model_type"]) for r in result.rows] == expected
        assert all(r["project_id"] == "p1" for r in result.rows)


class TestBreakdownEndpoints:
    @parameterized.expand(
        [
            (
                "usage",
                "usage_breakdown",
                "/usage/breakdown",
                {"hours": 1619.7, "requests": 373381},
                {"start": "2025-01-16", "end": "2025-01-16", "endpoint": "listen", "models": ["nova-3"]},
                "|listen||nova-3|||",
            ),
            (
                "billing",
                "billing_breakdown",
                "/billing/breakdown",
                {"dollars": "0.25"},
                {"start": "2025-01-16", "end": "2025-01-16", "line_item": "streaming::nova-3"},
                "||streaming::nova-3|",
            ),
            # Every dimension is null when the response is grouped by period only. The derived key
            # stays non-null so the merge predicate is still exact.
            (
                "ungrouped",
                "billing_breakdown",
                "/billing/breakdown",
                {"dollars": "1.00"},
                {"start": "2025-01-16", "end": "2025-01-16"},
                "|||",
            ),
        ]
    )
    def test_flattens_grouping_and_derives_grouping_key(
        self,
        _name: str,
        endpoint: str,
        path: str,
        measures: dict[str, Any],
        grouping: dict[str, Any],
        expected_key: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response({"results": [{**measures, "grouping": grouping}]}),
            ],
        )

        assert result.raised is None
        assert result.requests[-1].url == f"{DEEPGRAM_BASE_URL}/projects/p1{path}"
        assert len(result.rows) == 1
        # The period bounds live under "grouping"; they have to reach the row root or the primary key
        # can't be built.
        assert result.rows[0]["start"] == "2025-01-16"
        assert result.rows[0]["project_id"] == "p1"
        assert result.rows[0]["grouping_key"] == expected_key
        assert "grouping" not in result.rows[0]
        for measure, value in measures.items():
            assert result.rows[0][measure] == value


class TestFieldsEndpoints:
    def test_usage_fields_emits_one_row_per_value(self) -> None:
        result = _driver().run(
            "usage_fields",
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response(
                    {
                        "tags": ["tag=dev"],
                        "models": [{"name": "2-medical-nova", "language": "en-MY", "version": "1", "model_id": "m1"}],
                        "processing_methods": ["sync"],
                        "features": ["punctuate"],
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [(r["field"], r["value"]) for r in result.rows] == [
            ("models", "m1"),
            ("tags", "tag=dev"),
            ("processing_methods", "sync"),
            ("features", "punctuate"),
        ]
        assert result.rows[0]["name"] == "2-medical-nova"
        assert result.rows[0]["language"] == "en-MY"
        assert all(r["project_id"] == "p1" for r in result.rows)

    def test_billing_fields_unpacks_the_line_item_map(self) -> None:
        result = _driver().run(
            "billing_fields",
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response(
                    {
                        "accessors": ["a1"],
                        "deployments": ["hosted"],
                        "tags": [],
                        "line_items": {"streaming::nova-3": "Streaming Nova 3"},
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [(r["field"], r["value"]) for r in result.rows] == [
            ("accessors", "a1"),
            ("deployments", "hosted"),
            ("line_items", "streaming::nova-3"),
        ]
        # Line items arrive as a name -> description map, so the description has to survive the unpack.
        assert result.rows[-1]["description"] == "Streaming Nova 3"
