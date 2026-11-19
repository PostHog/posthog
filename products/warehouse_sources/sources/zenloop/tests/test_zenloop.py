from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.sources.sdk.testing import DriveResult, ScriptedResponse, SourceDriver, always, route
from products.warehouse_sources.sources.zenloop import zenloop
from products.warehouse_sources.sources.zenloop._config import ZenloopSourceConfig
from products.warehouse_sources.sources.zenloop.settings import ZENLOOP_ENDPOINTS
from products.warehouse_sources.sources.zenloop.source import ZenloopSource
from products.warehouse_sources.sources.zenloop.zenloop import ZenloopResumeConfig


def _response(
    items: list[dict[str, Any]] | None,
    *,
    response_key: str = "surveys",
    status: int = 200,
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {"meta": {"per_page": zenloop.PER_PAGE}}
    if not drop_key:
        body[response_key] = items or []
    return ScriptedResponse(status=status, json=body)


def _run(script: Any, endpoint: str = "surveys", resume_state: ZenloopResumeConfig | None = None) -> DriveResult:
    driver = SourceDriver(ZenloopSource(), ZenloopSourceConfig(api_token="token"))
    return driver.run(endpoint, script, resume_state=resume_state)


class TestPagination:
    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        # Page 1 must never be fetched on resume.
        result = _run(
            [_response([{"id": 3}, {"id": 4}]), _response([{"id": 5}])],
            resume_state=ZenloopResumeConfig(next_page=2),
        )

        assert [r["id"] for r in result.rows] == [3, 4, 5]
        assert result.params("page")[0] == "2"

    def test_missing_data_key_raises_loudly(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        result = _run([_response(None, drop_key=True)])

        # A 200 body without the endpoint's named key means the response shape changed — fail loud
        # rather than silently syncing 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _run([_response([{"id": 1}], status=status), _response([{"id": 1}])])

        # The transient error is retried and the reissued request succeeds.
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _run(always(_response([{"id": 1}], status=status)))

        assert isinstance(result.raised, HTTPError)


class TestZenloopSourceResponse:
    @parameterized.expand([("surveys",), ("survey_groups",), ("properties",)])
    def test_response_shape_matches_endpoint_config(self, endpoint: str) -> None:
        result = _run(
            always(_response([], response_key=ZENLOOP_ENDPOINTS[endpoint].response_key)),
            endpoint=endpoint,
        )

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a creation-timestamp partition key, so partitioning stays off.
        assert response.partition_mode is None
        assert response.partition_keys is None


def _answers_page(answers: list[dict[str, Any]], page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        status=200,
        json={"meta": {"page": page, "per_page": 20, "total_pages": total_pages}, "properties": [], "answers": answers},
    )


class TestFanoutEndpoints:
    @parameterized.expand(
        [
            ("survey_answers", "surveys", "survey_public_hash_id"),
            ("survey_group_answers", "survey_groups", "survey_group_public_hash_id"),
        ]
    )
    def test_answers_walk_every_parent_to_its_last_page(self, endpoint: str, parent: str, parent_key: str) -> None:
        script = route(
            {
                f"/{parent}/AAA=/answers": [
                    _answers_page([{"id": "a1", "inserted_at": "2024-01-01T00:00:00Z"}], page=1, total_pages=2),
                    _answers_page([{"id": "a2", "inserted_at": "2024-01-02T00:00:00Z"}], page=2, total_pages=2),
                ],
                f"/{parent}/BBB=/answers": [_answers_page([{"id": "a1"}], page=1, total_pages=1)],
                f"/{parent}": [
                    _response([{"public_hash_id": "AAA="}, {"public_hash_id": "BBB="}], response_key=parent),
                ],
            }
        )
        result = _run(script, endpoint=endpoint)

        assert result.raised is None
        assert [(r[parent_key], r["id"]) for r in result.rows] == [("AAA=", "a1"), ("AAA=", "a2"), ("BBB=", "a1")]
        # The same answer id under two parents stays two rows, so the key must carry the parent.
        assert result.response is not None
        assert result.response.primary_keys == [parent_key, "id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["inserted_at"]
        assert all(f"_{parent}_public_hash_id" not in r for r in result.rows)
        assert result.paths == [
            f"/v1/{parent}",
            f"/v1/{parent}/AAA=/answers",
            f"/v1/{parent}/AAA=/answers",
            f"/v1/{parent}/BBB=/answers",
        ]
        answer_requests = result.requests[1:]
        assert [r.param("page") for r in answer_requests] == ["1", "2", "1"]
        assert {(r.param("order_by"), r.param("order_type")) for r in answer_requests} == {("inserted_at", "asc")}
        assert all(r.param("per_page") is None for r in answer_requests)

    @parameterized.expand(
        [
            ("survey_summaries", "surveys", "survey"),
            ("survey_group_summaries", "survey_groups", "survey_group"),
        ]
    )
    def test_summary_object_becomes_one_row_per_parent(self, endpoint: str, parent: str, key: str) -> None:
        script = route(
            {
                f"/{parent}/AAA=": [
                    ScriptedResponse(status=200, json={key: {"public_hash_id": "AAA=", "nps": {"percentage": 40}}})
                ],
                f"/{parent}/BBB=": [
                    ScriptedResponse(status=200, json={key: {"public_hash_id": "BBB=", "nps": {"percentage": -5}}})
                ],
                f"/{parent}": [
                    _response([{"public_hash_id": "AAA="}, {"public_hash_id": "BBB="}], response_key=parent),
                ],
            }
        )
        result = _run(script, endpoint=endpoint)

        assert result.raised is None
        assert [(r["public_hash_id"], r["nps"]["percentage"]) for r in result.rows] == [("AAA=", 40), ("BBB=", -5)]

    @parameterized.expand(
        [
            ("survey_answers", "surveys", "/answers", {"answers": [{"id": "c1"}], "meta": {"total_pages": 1}}),
            (
                "survey_group_answers",
                "survey_groups",
                "/answers",
                {"answers": [{"id": "c1"}], "meta": {"total_pages": 1}},
            ),
            ("survey_summaries", "surveys", "", {"survey": {"public_hash_id": "CCC="}}),
            ("survey_group_summaries", "survey_groups", "", {"survey_group": {"public_hash_id": "CCC="}}),
        ]
    )
    def test_parent_deleted_mid_sync_is_skipped_and_later_parents_still_sync(
        self, endpoint: str, parent: str, child_suffix: str, child_body: dict[str, Any]
    ) -> None:
        not_found = ScriptedResponse(status=404, json={"error": {"status": 404, "code": "NOT_FOUND"}})
        script = route(
            {
                f"/{parent}/BBB={child_suffix}": [not_found],
                f"/{parent}/CCC={child_suffix}": [ScriptedResponse(status=200, json=child_body)],
                f"/{parent}": [
                    _response([{"public_hash_id": "BBB="}, {"public_hash_id": "CCC="}], response_key=parent)
                ],
            }
        )
        result = _run(script, endpoint=endpoint)

        assert result.raised is None
        assert len(result.rows) == 1
        assert result.paths[-1] == f"/v1/{parent}/CCC={child_suffix}"

    def test_summary_without_its_object_key_raises_loudly(self) -> None:
        script = route(
            {
                "/surveys/AAA=": [ScriptedResponse(status=200, json={"error": {"status": 200}})],
                "/surveys": [_response([{"public_hash_id": "AAA="}])],
            }
        )
        result = _run(script, endpoint="survey_summaries")

        assert isinstance(result.raised, ValueError)
        assert result.rows == []

    def test_answers_resume_skips_finished_parents_and_continues_the_current_one(self) -> None:
        script = route(
            {
                "/surveys/BBB=/answers": [_answers_page([{"id": "b2"}], page=2, total_pages=2)],
                "/surveys/CCC=/answers": [_answers_page([{"id": "c1"}], page=1, total_pages=1)],
                "/surveys": [
                    _response(
                        [{"public_hash_id": "AAA="}, {"public_hash_id": "BBB="}, {"public_hash_id": "CCC="}],
                    ),
                ],
            }
        )
        result = _run(
            script,
            endpoint="survey_answers",
            resume_state=ZenloopResumeConfig(
                completed=["/surveys/AAA=/answers"],
                current="/surveys/BBB=/answers",
                child_state={"page": 2},
            ),
        )

        assert result.raised is None
        assert [(r["survey_public_hash_id"], r["id"]) for r in result.rows] == [("BBB=", "b2"), ("CCC=", "c1")]
        assert result.paths == ["/v1/surveys", "/v1/surveys/BBB=/answers", "/v1/surveys/CCC=/answers"]
        assert result.params("page")[1] == "2"
