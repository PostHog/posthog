import json

import pytest

from products.signals.eval.self_driving.harness import grade
from products.signals.eval.self_driving.harness.grade import TASKS_DIR

TASK_IDS = sorted(path.name for path in TASKS_DIR.iterdir() if (path / "task.json").is_file())


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
