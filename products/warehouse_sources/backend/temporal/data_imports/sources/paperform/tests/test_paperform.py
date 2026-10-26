from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paperform import (
    PaperformSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.paperform import (
    PAGE_SIZE,
    PaperformResumeConfig,
    _format_after_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import (
    ENDPOINTS,
    PAPERFORM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source import PaperformSource


def _driver() -> SourceDriver:
    return SourceDriver(PaperformSource(), PaperformSourceConfig(api_key="pf-key"))


def _resp(
    results_key: str, items: list[dict[str, Any]], *, has_more: bool = False, status: int = 200
) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={"status": "ok", "results": {results_key: items}, "has_more": has_more, "total": len(items)},
    )


class TestTopLevel:
    def test_follows_after_id_cursor_until_has_more_false(self) -> None:
        result = _driver().run(
            "forms",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}], has_more=True),
                _resp("forms", [{"id": "f3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["f1", "f2", "f3"]
        # Page one carries no cursor; page two advances on the last id of page one.
        assert result.params("after_id") == [None, "f2"]
        # Every page requests the largest page size in stable ascending creation order.
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        assert result.params("sort") == ["ASC"] * 2
        # Checkpoint saved after the first page (points at the next page), then pagination ends.
        assert result.saved_states == [PaperformResumeConfig(cursor="f2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "forms", [_resp("forms", [{"id": "f3"}])], resume_state=PaperformResumeConfig(cursor="f2")
        )

        assert result.raised is None
        assert result.rows == [{"id": "f3"}]
        # The resumed run starts at the saved cursor rather than re-fetching page one.
        assert result.params("after_id") == ["f2"]

    def test_missing_results_key_fails_loud(self) -> None:
        # A 200 body without the expected results key means the response shape changed.
        result = _driver().run("forms", [ScriptedResponse(json={"status": "ok", "results": {}})])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestFanOut:
    def test_injects_form_id_and_paginates_each_form(self) -> None:
        result = _driver().run(
            "submissions",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("submissions", [{"id": "s1"}, {"id": "s2"}], has_more=True),
                _resp("submissions", [{"id": "s3"}]),
                _resp("submissions", [{"id": "s4"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"form_id": "f1", "id": "s1"},
            {"form_id": "f1", "id": "s2"},
            {"form_id": "f1", "id": "s3"},
            {"form_id": "f2", "id": "s4"},
        ]
        assert result.paths == [
            "/v1/forms",
            "/v1/forms/f1/submissions",
            "/v1/forms/f1/submissions",
            "/v1/forms/f2/submissions",
        ]
        # Fan-out progress is checkpointed so a crash resumes mid-stream.
        assert result.saved_states
        assert result.saved_states[-1].fanout_state is not None

    def test_resume_skips_completed_forms(self) -> None:
        result = _driver().run(
            "submissions",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("submissions", [{"id": "s10"}]),
            ],
            resume_state=PaperformResumeConfig(
                fanout_state={
                    "completed": ["/forms/f1/submissions"],
                    "current": "/forms/f2/submissions",
                    "child_state": {"cursor": "s9"},
                }
            ),
        )

        # f1 was fully synced before the crash and must not be re-fetched; f2 resumes at its cursor.
        assert result.raised is None
        assert result.rows == [{"form_id": "f2", "id": "s10"}]
        assert result.paths == ["/v1/forms", "/v1/forms/f2/submissions"]
        assert result.requests[1].param("after_id") == "s9"

    def test_incremental_watermark_first_page_of_each_form_only(self) -> None:
        result = _driver().run(
            "submissions",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("submissions", [{"id": "s1"}], has_more=True),
                _resp("submissions", [{"id": "s2"}]),
                _resp("submissions", []),
            ],
            incremental_field="created_at_utc",
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, 999999, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/forms",
            "/v1/forms/f1/submissions",
            "/v1/forms/f1/submissions",
            "/v1/forms/f2/submissions",
        ]
        # The forms listing that drives the fan-out is never date-filtered.
        assert result.requests[0].param("after_date") is None
        # Each form's first page carries the watermark (truncated down to whole seconds)...
        assert result.requests[1].param("after_date") == "2024-01-02T03:04:05Z"
        assert result.requests[3].param("after_date") == "2024-01-02T03:04:05Z"
        # ...and later pages advance purely on after_id (after_id supersedes after_date server-side).
        assert result.requests[2].param("after_id") == "s1"
        assert result.requests[2].param("after_date") is None


class TestRetryAndErrors:
    def test_client_error_raises(self) -> None:
        result = _driver().run("forms", [_resp("forms", [], status=401)])

        assert isinstance(result.raised, HTTPError)


class TestFormatAfterDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 5, 6, 7, 8, 9, 123456, tzinfo=UTC), "2024-05-06T07:08:09Z"),
            ("naive_datetime_assumed_utc", datetime(2024, 5, 6, 7, 8, 9), "2024-05-06T07:08:09Z"),
            ("string_passthrough", "2024-05-06T07:08:09Z", "2024-05-06T07:08:09Z"),
        ]
    )
    def test_formats_watermark(self, _name: str, value: Any, expected: str) -> None:
        assert _format_after_date(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_maps_status_to_message(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("pf-key") == (expected_valid, expected_message)

        assert {request.path for request in network.requests_log} == {"/v1/forms"}
        assert network.requests_log[0].path == "/v1/forms"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer pf-key"

    def test_connection_error_is_not_validated(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            valid, message = validate_credentials("pf-key")

        assert valid is False
        assert message == "Could not connect to Paperform to validate the API key"
        assert {request.path for request in network.requests_log} == {"/v1/forms"}


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_shape(self, endpoint: str) -> None:
        config = PAPERFORM_ENDPOINTS[endpoint]
        results_key = "forms" if config.form_scoped else config.results_key
        result = _driver().run(endpoint, [_resp(results_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        assert result.response.sort_mode == "asc"
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None

    def test_form_scoped_endpoints_include_form_id_in_primary_key(self) -> None:
        # These tables aggregate rows across every form, so per-form identifiers (submission id,
        # field key, SKU, coupon code) are only unique with the parent form id in the key.
        for config in PAPERFORM_ENDPOINTS.values():
            if config.form_scoped:
                assert config.primary_keys[0] == "form_id"
