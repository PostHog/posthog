from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jotform import (
    JotformSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform import (
    JotformResumeConfig,
    _format_filter_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.settings import (
    ENDPOINTS,
    JOTFORM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source import JotformSource

US_BASE = "https://api.jotform.com"


def _driver() -> SourceDriver:
    return SourceDriver(JotformSource(), JotformSourceConfig(api_key="key", region="us"))


def _response(content: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json={"content": content, "responseCode": status_code})


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC), "2024-01-15 10:30:45"),
            (datetime(2024, 1, 15, 10, 30, 45), "2024-01-15 10:30:45"),
            (date(2024, 1, 15), "2024-01-15 00:00:00"),
            ("2024-01-15 10:30:45", "2024-01-15 10:30:45"),
            ("2024-01-15T10:30:45", "2024-01-15 10:30:45"),
            (None, None),
            (True, None),
            ("not-a-date", None),
        ],
    )
    def test_format(self, value, expected):
        assert _format_filter_value(value) == expected


class TestListEndpoints:
    def test_paginates_until_partial_page_and_checkpoints_next_offset(self) -> None:
        with mock.patch.object(JOTFORM_ENDPOINTS["submissions"], "page_size", 2):
            result = _driver().run("submissions", [_response([{"id": "1"}, {"id": "2"}]), _response([{"id": "3"}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.params("offset") == ["0", "2"]
        assert result.params("limit") == ["2", "2"]
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [JotformResumeConfig(offset=2)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("submissions", [_response([{"id": "9"}])], resume_state=JotformResumeConfig(offset=200))

        assert result.raised is None
        assert result.params("offset") == ["200"]

    def test_incremental_run_sends_gt_filter_on_chosen_field(self) -> None:
        result = _driver().run(
            "submissions",
            [_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert result.params("orderby") == ["updated_at"]
        assert result.params("filter") == ['{"updated_at:gt":"2024-01-15 10:30:45"}']


class TestLabelResourcesFanOut:
    def test_fans_out_over_nested_labels_and_injects_label_id(self) -> None:
        tree = {"id": "root", "sublabels": [{"id": "child", "parent_label_id": "root", "sublabels": []}]}
        root_assets = [{"id": "251453058472053", "assetType": "form"}]
        child_assets = [
            {"id": "251453058472053", "assetType": "form"},
            {"id": "251453701279861", "assetType": "workflow"},
        ]
        result = _driver().run("label_resources", [_response(tree), _response(root_assets), _response(child_assets)])

        assert result.raised is None
        assert [(row["label_id"], row["assetType"], row["id"]) for row in result.rows] == [
            ("root", "form", "251453058472053"),
            ("child", "form", "251453058472053"),
            ("child", "workflow", "251453701279861"),
        ]
        assert all("_labels_id" not in row for row in result.rows)
        assert result.paths == ["/user/labels", "/label/root/resources", "/label/child/resources"]
        assert all(request.origin == US_BASE for request in result.requests)
        assert result.requests[1].param("orderby") == "created_at"
        assert result.requests[1].param("offset") == "0"
        saved_states = [state.fanout_state for state in result.saved_states]
        assert set(saved_states[-1]["completed"]) == {"/label/root/resources", "/label/child/resources"}
        assert saved_states[-1]["current"] is None
        assert saved_states[-1]["child_state"] is None

    def test_resumes_and_skips_completed_labels(self) -> None:
        tree = {"id": "root", "sublabels": [{"id": "child", "sublabels": []}]}
        resume = JotformResumeConfig(
            fanout_state={"completed": ["/label/root/resources"], "current": None, "child_state": None}
        )
        result = _driver().run(
            "label_resources",
            [_response(tree), _response([{"id": "1", "assetType": "form"}])],
            resume_state=resume,
        )

        assert result.raised is None
        assert [row["label_id"] for row in result.rows] == ["child"]
        assert result.paths == ["/user/labels", "/label/child/resources"]
        assert all(request.origin == US_BASE for request in result.requests)


class TestRetries:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_statuses_eventually_raise(self, status_code: int) -> None:
        # The client re-issues on 429/5xx; exhaust the attempts with the same status.
        result = _driver().run("forms", always(_response([], status_code)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_client_errors_raise_immediately(self, status_code: int) -> None:
        result = _driver().run("forms", [_response([], status_code)])

        assert isinstance(result.raised, HTTPError)
        # No retry on a 4xx: exactly one request was sent.
        assert len(result.requests) == 1


class TestValidateCredentials:
    def test_pins_redirects_off_and_redacts_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key-123", "us", "forms.acme.com")

        # User-controlled host: no redirects off the validated host, and the key is value-redacted.
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("key-123",)
        assert network.requests_log[0].url == "https://forms.acme.com/API/user"


class TestQuestionsFanOut:
    def test_fans_out_over_forms_and_injects_form_id(self) -> None:
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        f1_questions = {"1": {"qid": "1", "text": "Name"}, "2": {"qid": "2", "text": "Email"}}
        f2_questions = {"1": {"qid": "1", "text": "Age"}}
        result = _driver().run("questions", [_response(forms_page), _response(f1_questions), _response(f2_questions)])

        assert result.raised is None
        assert [(row["form_id"], row["qid"]) for row in result.rows] == [("f1", "1"), ("f1", "2"), ("f2", "1")]
        # Forms are listed once, then each form's questions endpoint is hit in turn.
        assert result.paths == ["/user/forms", "/form/f1/questions", "/form/f2/questions"]
        assert all(request.origin == US_BASE for request in result.requests)
        assert result.requests[0].param("orderby") == "created_at"

    def test_checkpoints_completed_forms(self) -> None:
        result = _driver().run("questions", [_response([{"id": "f1"}]), _response({"1": {"qid": "1"}})])

        assert result.raised is None
        # The final checkpoint records f1's questions path as completed.
        saved_states = [state.fanout_state for state in result.saved_states]
        assert any(state and "/form/f1/questions" in (state.get("completed") or []) for state in saved_states)


class TestJotformSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = JOTFORM_ENDPOINTS[endpoint]
        script: Script
        if endpoint == "label_resources":
            script = route(
                {
                    "/user/labels": [_response({"id": "root", "sublabels": []})],
                    "/label/root/resources": [_response([])],
                }
            )
        elif endpoint == "labels":
            script = [_response({"id": "root", "sublabels": []})]
        else:
            script = [_response([])]
        result = _driver().run(endpoint, script)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_format == config.partition_format
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
