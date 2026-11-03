from typing import Any, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.chameleon import (
    ChameleonResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import CHAMELEON_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.source import ChameleonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chameleon import (
    ChameleonSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ChameleonSource(), ChameleonSourceConfig(account_secret="secret"))


def _response(endpoint: str, rows: list[dict[str, Any]], before: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={endpoint: rows, "cursor": {"before": before} if before else {}})


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("rate_limited", 429, False, "status 429"),
        ]
    )
    def test_status_maps_to_result(
        self, _name: str, status_code: int, expected_ok: bool, expected_fragment: str | None
    ) -> None:
        answer = ScriptedResponse(status=status_code)
        script = always(answer) if status_code in (429, 500) else [answer]
        with scripted_network(script) as network:
            ok, error = validate_credentials("secret")

        assert {request.path for request in network.requests_log} == {"/"}
        assert ok is expected_ok
        if expected_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_fragment in error

    def test_network_error_is_inconclusive(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            ok, error = validate_credentials("secret")

        assert {request.path for request in network.requests_log} == {"/"}
        assert ok is False
        assert error is not None and "Could not reach Chameleon" in error

    def test_probe_sends_the_account_secret_header(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("secret")

        assert network.requests_log[0].headers["x-account-secret"] == "secret"
        assert network.requests_log[0].headers["accept"] == "application/json"
        assert network.session_options[0]["redact_values"] == ("secret",)


class TestStandardEndpointPagination:
    def test_follows_before_cursor_until_exhausted(self) -> None:
        result = _driver().run(
            "segments",
            [
                _response("segments", [{"id": "S1"}, {"id": "S2"}], "S2"),
                _response("segments", [{"id": "S3"}], "S3"),
                _response("segments", []),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["S1", "S2", "S3"]
        assert result.paths == ["/v3/edit/segments"] * 3
        assert result.params("before") == [None, "S2", "S3"]
        assert result.params("limit") == ["500"] * 3

    @parameterized.expand(
        [
            # /analyze/profiles answers 422 to the `limit=500` the other list endpoints accept, so
            # it must go out with no `limit` and let Chameleon pick the page size.
            ("profiles_sends_no_limit", "profiles", "/v3/analyze/profiles", None),
            ("other_endpoints_keep_the_page_size", "segments", "/v3/edit/segments", "500"),
            ("deliveries_keep_the_page_size", "deliveries", "/v3/edit/deliveries", "500"),
        ]
    )
    def test_page_size_is_only_sent_where_the_endpoint_accepts_it(
        self, _name: str, endpoint: str, expected_path: str, expected_limit: str | None
    ) -> None:
        result = _driver().run(endpoint, [_response(endpoint, [{"id": "X1"}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["X1"]
        assert result.paths == [expected_path]
        assert result.params("limit") == [expected_limit]

    def test_stops_when_cursor_missing(self) -> None:
        result = _driver().run("tours", [_response("tours", [{"id": "T1"}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["T1"]
        assert len(result.requests) == 1

    def test_stops_when_cursor_fails_to_advance(self) -> None:
        # A repeated cursor must terminate the sync instead of wedging it in an infinite loop.
        result = _driver().run(
            "tours",
            [_response("tours", [{"id": "T1"}], "T1"), _response("tours", [{"id": "T1"}], "T1")],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["T1", "T1"]
        assert len(result.requests) == 2

    def test_missing_data_key_is_an_empty_page(self) -> None:
        # Chameleon envelopes are tolerated when the data key is absent — zero rows, no crash.
        result = _driver().run("tours", [ScriptedResponse(json={"cursor": {}})])

        assert result.raised is None
        assert result.rows == []

    def test_saves_resume_state_after_each_page_with_more_to_come(self) -> None:
        result = _driver().run(
            "segments",
            [
                _response("segments", [{"id": "S1"}, {"id": "S2"}], "S2"),
                _response("segments", [{"id": "S3"}]),
            ],
        )

        # Only the first page has a next cursor, so exactly one checkpoint is saved, pointing at it.
        assert result.raised is None
        assert result.saved_states == [ChameleonResumeConfig(before="S2")]

    def test_resumes_from_saved_before(self) -> None:
        # When state exists, the first request must start from the saved cursor, not page one.
        result = _driver().run(
            "segments",
            [_response("segments", [{"id": "S3"}])],
            resume_state=ChameleonResumeConfig(before="S2"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["S3"]
        assert result.params("before") == ["S2"]

    def test_secret_travels_via_framework_auth(self) -> None:
        # Framework api_key auth (not a hand-built header) so the secret is value-redacted from logs.
        result = _driver().run("tours", [_response("tours", [{"id": "T1"}])])

        assert result.raised is None
        assert result.requests[0].headers["x-account-secret"] == "secret"
        assert result.requests[0].headers["accept"] == "application/json"
        assert result.session_options[0]["redact_values"] == ("secret",)


class TestFanOut:
    @parameterized.expand(
        [
            ("responses", "responses", "surveys", "survey_id", "/edit/surveys", "/analyze/responses"),
            ("interactions", "interactions", "tours", "tour_id", "/edit/tours", "/analyze/interactions"),
        ]
    )
    def test_fans_out_over_parents_and_stamps_the_parent_id(
        self,
        _name: str,
        endpoint: str,
        parent_key: str,
        stamped_column: str,
        parent_path: str,
        child_path: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response(parent_key, [{"id": "P1"}, {"id": "P2"}]),
                _response(endpoint, [{"id": "C1"}, {"id": "C2"}]),
                _response(endpoint, [{"id": "C3"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "C1", stamped_column: "P1"},
            {"id": "C2", stamped_column: "P1"},
            {"id": "C3", stamped_column: "P2"},
        ]
        assert result.paths == [f"/v3{parent_path}", f"/v3{child_path}", f"/v3{child_path}"]
        assert result.params("id") == [None, "P1", "P2"]

    def test_parent_id_overwrites_the_one_the_api_returned(self) -> None:
        # Interactions already carry `tour_id`; stamping must leave one column holding the parent
        # actually queried, not two conflicting ones.
        result = _driver().run(
            "interactions",
            [
                _response("tours", [{"id": "T1"}]),
                _response("interactions", [{"id": "I1", "tour_id": "T1", "state": "completed"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "I1", "tour_id": "T1", "state": "completed"}]

    def test_paginates_within_a_survey(self) -> None:
        result = _driver().run(
            "responses",
            [
                _response("surveys", [{"id": "SV1"}]),
                _response("responses", [{"id": "R1"}], "R1"),
                _response("responses", [{"id": "R2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["R1", "R2"]
        assert result.params("before") == [None, None, "R1"]

    def test_survey_deleted_mid_fan_out_is_skipped(self) -> None:
        result = _driver().run(
            "responses",
            [
                _response("surveys", [{"id": "SV1"}, {"id": "GONE"}, {"id": "SV2"}]),
                _response("responses", [{"id": "R1"}]),
                ScriptedResponse(status=404, json={"error": "not found"}),
                _response("responses", [{"id": "R2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["R1", "R2"]

    def test_non_404_http_error_propagates(self) -> None:
        result = _driver().run(
            "responses",
            [_response("surveys", [{"id": "SV1"}]), ScriptedResponse(status=403, json={"error": "forbidden"})],
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_checkpoints_fan_out_progress(self) -> None:
        result = _driver().run(
            "responses",
            [
                _response("surveys", [{"id": "SV1"}]),
                _response("responses", [{"id": "R1"}], "R1"),
                _response("responses", [{"id": "R2"}]),
            ],
        )

        assert result.raised is None
        # Mid-survey: the in-progress survey path and its cursor are checkpointed so a crash
        # resumes into the same survey at the saved page.
        assert result.saved_states[0] == ChameleonResumeConfig(
            fanout_state={"completed": [], "current": "/analyze/responses?id=SV1", "child_state": {"cursor": "R1"}}
        )
        # Survey finished: it lands in `completed` so a restart skips it.
        assert result.saved_states[-1] == ChameleonResumeConfig(
            fanout_state={"completed": ["/analyze/responses?id=SV1"], "current": None, "child_state": None}
        )

    def test_resumes_by_skipping_completed_surveys(self) -> None:
        result = _driver().run(
            "responses",
            [_response("surveys", [{"id": "SV1"}, {"id": "SV2"}]), _response("responses", [{"id": "R2"}])],
            resume_state=ChameleonResumeConfig(
                fanout_state={"completed": ["/analyze/responses?id=SV1"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "R2", "survey_id": "SV2"}]
        assert result.paths == ["/v3/edit/surveys", "/v3/analyze/responses"]
        assert result.params("id") == [None, "SV2"]

    def test_pre_migration_bookmark_restarts_fan_out_fresh(self) -> None:
        # An old-shape bookmark (survey_id + before) can't seed the framework fan-out state — the
        # sync restarts from the first survey and the merge dedupes re-pulled rows.
        result = _driver().run(
            "responses",
            [_response("surveys", [{"id": "SV1"}]), _response("responses", [{"id": "R1"}])],
            resume_state=ChameleonResumeConfig(before="R9", survey_id="DELETED"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["R1"]
        assert result.params("id") == [None, "SV1"]
        assert result.params("before") == [None, None]


class TestPropertiesKinds:
    def test_requests_each_kind_and_stamps_it(self) -> None:
        # /edit/properties requires `kind`, so a complete table is the union of one request per kind,
        # and the payload doesn't echo the kind back — without stamping the two are indistinguishable.
        result = _driver().run(
            "properties",
            [
                ScriptedResponse(json={"properties": [{"id": "P1", "prop": "plan_cost"}]}),
                ScriptedResponse(json={"properties": [{"id": "P2", "prop": "arr"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "P1", "prop": "plan_cost", "kind": "profile"},
            {"id": "P2", "prop": "arr", "kind": "company"},
        ]
        assert result.paths == ["/v3/edit/properties"] * 2
        assert result.params("kind") == ["profile", "company"]

    def test_does_not_paginate_a_kind(self) -> None:
        # The endpoint returns the whole set at once. Paginating it on a stray cursor would re-request
        # the same complete set until the guard trips, once per kind.
        result = _driver().run(
            "properties",
            [_response("properties", [{"id": "P1"}], "P1"), _response("properties", [{"id": "P2"}], "P2")],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["P1", "P2"]
        assert len(result.requests) == 2


class TestResumeStateCompatibility:
    def test_pre_migration_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does `dataclass(**saved)` — state saved before the
        # framework migration must still construct.
        assert ChameleonResumeConfig(**cast("dict[str, Any]", {"before": "S2", "survey_id": "SV1"})) == (
            ChameleonResumeConfig(before="S2", survey_id="SV1")
        )


class TestChameleonSourceResponse:
    @parameterized.expand(list(CHAMELEON_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        if endpoint == "properties":
            script = [ScriptedResponse(json={"properties": []}), ScriptedResponse(json={"properties": []})]
        elif endpoint in ("responses", "interactions"):
            parent = CHAMELEON_ENDPOINTS[endpoint].fan_out_parent
            assert parent is not None
            script = [_response(parent, [])]
        else:
            script = [_response(endpoint, [])]

        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Chameleon returns newest-first; the watermark/ordering contract must reflect that.
        assert result.response.sort_mode == "desc"
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created_at"]
