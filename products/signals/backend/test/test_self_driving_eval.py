import json
from pathlib import Path
from typing import Any

import pytest

from braintrust.framework import EvalResultWithSummary
from braintrust.logger import ExperimentSummary, ScoreSummary

from products.signals.eval.self_driving import eval_selfdriving
from products.signals.eval.self_driving.harness import (
    drive as drive_module,
    grade,
)
from products.signals.eval.self_driving.harness.grade import TASKS_DIR

TASK_IDS = sorted(path.name for path in TASKS_DIR.iterdir() if (path / "task.json").is_file())


def _braintrust_result(
    experiment_url: str | None,
    scores: dict[str, float] | None = None,
) -> EvalResultWithSummary[dict[str, Any], dict[str, Any]]:
    summary = ExperimentSummary(
        project_name="signals-self-driving",
        project_id=None,
        experiment_id=None,
        experiment_name="shareable-run",
        project_url=None,
        experiment_url=experiment_url,
        comparison_experiment_name=None,
        scores={name: ScoreSummary(name, 1, score, None, None) for name, score in (scores or {}).items()},
        metrics={},
    )
    return EvalResultWithSummary(summary=summary, results=[])


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_pristine_task_exposes_the_planted_regression(task_id: str) -> None:
    result = grade.run_verify_suite(task_id, TASKS_DIR / task_id / "repo", patched=False)

    assert result["fix"]["pass"] == 0, result["raw"]
    assert result["fix"]["fail"] > 0, result["raw"]
    assert result["regression"]["pass"] > 0, result["raw"]
    assert result["regression"]["fail"] == 0, result["raw"]


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_task_fixture_matches_the_task_contract(task_id: str) -> None:
    task_dir = TASKS_DIR / task_id
    task_spec = json.loads((task_dir / "task.json").read_text())
    signals = json.loads((task_dir / "signals.json").read_text())

    assert task_spec["task_id"] == task_id
    assert task_spec["repo_full_name"] == f"acme/{task_id}"
    assert task_spec["signal_type"] in {"conversations", "github", "linear", "pganalyze", "zendesk"}
    assert task_spec["difficulty"] in {"T1", "T2", "T3"}
    assert task_spec["ground_truth"]["root_cause"]
    assert task_spec["ground_truth"]["fix_contract"]
    assert task_spec["seed"]["streams"]
    assert signals
    assert (task_dir / "repo").is_dir()
    assert (task_dir / "verify").is_dir()


def test_llm_judge_uses_the_signals_gateway(mocker) -> None:
    gateway = mocker.MagicMock()
    client = gateway.__enter__.return_value
    client.chat.completions.create.return_value.choices = [
        mocker.Mock(message=mocker.Mock(content='{"score": 0.75, "reasoning": "Mostly correct"}'))
    ]
    get_llm_client = mocker.patch.object(grade, "get_llm_client", return_value=gateway)

    result = grade.llm_judge("Grade this", team_id=42)

    assert result == {"score": 0.75, "reasoning": "Mostly correct"}
    get_llm_client.assert_called_once_with(product="signals", team_id=42)
    client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_run_eval_requires_braintrust_before_starting_a_case(
    monkeypatch: pytest.MonkeyPatch, mocker, tmp_path: Path
) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    eval_async = mocker.patch.object(eval_selfdriving, "EvalAsync")

    async def run_fn(task_id: str, trial: int) -> dict[str, Any]:
        raise AssertionError("the pipeline must not start without Braintrust configured")

    with pytest.raises(eval_selfdriving.MissingBraintrustApiKey, match="BRAINTRUST_API_KEY"):
        await eval_selfdriving.run_eval(
            task_ids=[TASK_IDS[0]],
            trials=1,
            workspace=tmp_path,
            experiment_name="missing-key",
            run_fn=run_fn,
        )

    eval_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_eval_configures_a_private_uploaded_braintrust_experiment(
    monkeypatch: pytest.MonkeyPatch, mocker, tmp_path: Path
) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-key")
    braintrust_result = _braintrust_result("https://braintrust.example/eval")
    eval_async = mocker.patch.object(eval_selfdriving, "EvalAsync", return_value=braintrust_result)

    async def run_fn(task_id: str, trial: int) -> dict[str, Any]:
        return {}

    result = await eval_selfdriving.run_eval(
        task_ids=TASK_IDS[:2],
        trials=1,
        workspace=tmp_path,
        experiment_name="shareable-run",
        run_fn=run_fn,
        max_concurrency=1,
    )

    assert result is braintrust_result
    _, kwargs = eval_async.call_args
    assert kwargs["experiment_name"] == "shareable-run"
    assert kwargs["is_public"] is False
    assert kwargs["no_send_logs"] is False
    assert kwargs["update"] is True
    assert kwargs["timeout"] is None
    assert kwargs["max_concurrency"] == 2
    assert kwargs["metadata"] == {
        "suite": "signals-self-driving",
        "task_ids": TASK_IDS[:2],
        "task_count": 2,
        "trials": 1,
        "pipeline_concurrency": 1,
    }


@pytest.mark.asyncio
async def test_run_eval_fails_when_braintrust_does_not_return_a_shareable_url(
    monkeypatch: pytest.MonkeyPatch, mocker, tmp_path: Path
) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-key")
    mocker.patch.object(
        eval_selfdriving,
        "EvalAsync",
        return_value=_braintrust_result(None),
    )

    async def run_fn(task_id: str, trial: int) -> dict[str, Any]:
        return {}

    with pytest.raises(eval_selfdriving.BraintrustUploadError, match="did not return an experiment URL"):
        await eval_selfdriving.run_eval(
            task_ids=[TASK_IDS[0]],
            trials=1,
            workspace=tmp_path,
            experiment_name="missing-url",
            run_fn=run_fn,
        )


def test_format_eval_summary_includes_shareable_url_scores_and_local_results(tmp_path: Path) -> None:
    result = _braintrust_result(
        "https://braintrust.example/eval",
        scores={"root_cause_identified": 0.75, "behavioral_correctness": 0.5},
    )

    output = drive_module.format_eval_summary(result, tmp_path / "results")

    assert output.splitlines() == [
        "Braintrust: https://braintrust.example/eval",
        "Scores:",
        "  behavioral_correctness: 50.0%",
        "  root_cause_identified: 75.0%",
        f"Local results: {tmp_path / 'results'}",
    ]
