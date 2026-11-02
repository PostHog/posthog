import os
import json
import asyncio
from functools import partial
from typing import Literal

import pytest
from unittest.mock import patch

import httpx
from parameterized import parameterized

from products.posthog_ai.eval_harness.test.offline_api import OfflineServer
from products.signals.eval.offline import EvalMetric, SignalsEvalRecorder
from products.signals.eval.offline_config import GROUPING_SUITE, SCOUT_SAFETY_SUITE


def test_grouping_publishes_stage_scores_and_aggregates_without_combining_recall() -> None:
    server = OfflineServer()
    with (
        patch.dict(os.environ, {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token"}),
        patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(server.respond))),
    ):
        recorder = SignalsEvalRecorder(GROUPING_SUITE, metadata={"git_sha": "test-revision", "limit": 3})
        for stage in ["signal-safety-filter", "github-actionability-check", "report-safety-check"]:
            recorder.record(
                eval_name=stage,
                item_name="case-0",
                input={"text": "An invented test finding"},
                output=False,
                expected=True,
                metrics=[EvalMetric(name="correct_classification", score=0.0, reasoning="Does not match fixture")],
            )
        recorder.record(
            eval_name="grouping-quality",
            item_name="report-0",
            metrics=[EvalMetric(name="group_recall", score=0.5)],
        )
        recorder.record(
            eval_name="grouping-aggregate",
            item_name="aggregate",
            metrics=[EvalMetric(name="group_recall", score=0.75), EvalMetric(name="ari", score=-0.25)],
        )
        recorder.record(
            eval_name="match-quality",
            item_name="case-0",
            metrics=[EvalMetric(name="query_diversity", score=1.5)],
        )
        url = asyncio.run(recorder.publish())

    bodies = [json.loads(request.content) for request in server.requests if request.url.path.endswith("/upload/")]
    results = [result for body in bodies for result in body["results"]]
    items = [item for body in bodies for item in body["items"]]
    assert server.status == "completed"
    assert server.experiment["suite_key"] == "signals/grouping-e2e"
    assert server.experiment["application_version"] == "test-revision"
    assert server.experiment["expected_item_count"] == 6
    assert server.experiment["expected_result_count"] == 96
    assert url is not None and recorder.experiment_id in url
    assert len({item["case_key"] for item in items}) == 6
    assert items[0]["payload"]["output"] is False
    assert items[0]["payload"]["input"]["input"] == {"text": "An invented test finding"}
    values = {r["scorer_version_id"]: r["value"] for r in results if r["status"] == "ok"}
    for metric in [
        "signal_safety_correct_classification",
        "actionability_correct_classification",
        "report_safety_correct_classification",
    ]:
        assert values[str(GROUPING_SUITE.scorer_versions[metric])] is False
    assert values[str(GROUPING_SUITE.scorer_versions["group_recall"])] == 0.5
    assert values[str(GROUPING_SUITE.scorer_versions["mean_group_recall"])] == 0.75
    assert values[str(GROUPING_SUITE.scorer_versions["ari"])] == -0.25
    assert values[str(GROUPING_SUITE.scorer_versions["query_diversity"])] == 1.5
    assert sum(r["status"] == "not_applicable" for r in results) == 89
    assert results[0]["payload"]["reasoning"] == "Does not match fixture"


@parameterized.expand([("skipped", None, "ok", "skipped"), ("error", None, "error", "error")])
def test_scout_outcomes_and_repeat_runs_keep_distinct_identities(
    _name: str, score: float | None, status: Literal["ok", "error"], expected_status: str
) -> None:
    servers = [OfflineServer(), OfflineServer()]
    for server in servers:
        with (
            patch.dict(os.environ, {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token"}),
            patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(server.respond))),
        ):
            recorder = SignalsEvalRecorder(SCOUT_SAFETY_SUITE)
            recorder.record(
                eval_name="scout-safety-filter",
                item_name="same-case",
                metrics=[
                    EvalMetric(
                        name="correct_classification",
                        score=score,
                        status=status,
                        error_code="judge_error" if status == "error" else None,
                    )
                ],
            )
            asyncio.run(recorder.publish())
        outcomes = next(json.loads(r.content)["results"] for r in server.requests if r.url.path.endswith("/upload/"))
        assert outcomes[0]["status"] == expected_status
        assert "value" not in outcomes[0]
        assert [outcome["status"] for outcome in outcomes[1:]] == ["not_applicable", "not_applicable"]
    assert servers[0].experiment["id"] != servers[1].experiment["id"]
    assert set(servers[0].items).isdisjoint(servers[1].items)


@parameterized.expand(
    [("opt_out", True, "test-only-token"), ("no_key", False, ""), ("bad_key", False, "invalid token")]
)
def test_disabled_reporting_never_attempts_network(_name: str, disabled: bool, api_key: str) -> None:
    def fail_network(request: httpx.Request) -> httpx.Response:
        pytest.fail("Disabled reporting attempted a network request")

    with (
        patch.dict(os.environ, {"POSTHOG_OFFLINE_EVAL_API_KEY": api_key}),
        patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(fail_network))),
    ):
        recorder = SignalsEvalRecorder(SCOUT_SAFETY_SUITE, disabled=disabled)
        recorder.record(
            eval_name="scout-safety-filter",
            item_name="case",
            metrics=[EvalMetric(name="correct_classification", score=1)],
        )
        assert asyncio.run(recorder.publish()) is None


@pytest.mark.parametrize("failed_action", ["upload", "tag"])
def test_upload_failure_is_reported_without_hiding_completed_scores(
    capsys: pytest.CaptureFixture[str], failed_action: str
) -> None:
    server = OfflineServer()

    def respond(request: httpx.Request) -> httpx.Response:
        if failed_action == "upload" or request.method == "PATCH":
            return httpx.Response(403)
        return server.respond(request)

    with (
        patch.dict(os.environ, {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token"}),
        patch(
            "httpx.AsyncClient",
            new=partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)),
        ),
    ):
        recorder = SignalsEvalRecorder(SCOUT_SAFETY_SUITE)
        recorder.record(
            eval_name="scout-safety-filter",
            item_name="case",
            metrics=[EvalMetric(name="correct_classification", score=0)],
        )
        url = asyncio.run(recorder.publish())
    output = capsys.readouterr().err
    if failed_action == "upload":
        assert url is None
        assert "upload failed" in output
    else:
        assert server.status == "completed"
        assert url is not None and recorder.experiment_id in url
        assert f"uploaded: {url}" in output
        assert "upload failed" not in output
    assert recorder.cases[0].scores["scout_safety_correct_classification"] == 0
