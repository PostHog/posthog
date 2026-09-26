from __future__ import annotations

import json
import importlib
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

cli = importlib.import_module(
    "products.signals.eval.experiments.2026-09-long-running-agent-evals.scripts.run_live_trials"
)

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]


class FakeTrialClient:
    def __init__(self, stranded_status: str | None = None) -> None:
        self.stranded_status = stranded_status
        self.launches: list[dict[str, Json]] = []
        self.active: set[str] = set()
        self.peak_active = 0
        self.polls: dict[str, int] = {}

    def request(self, path: str, body: dict[str, Json] | None = None) -> dict[str, Json]:
        if body is not None:
            self.launches.append(body.copy())
            launch_id = str(body["launch_id"])
            self.active.add(launch_id)
            self.peak_active = max(self.peak_active, len(self.active))
            return {"launch_id": launch_id, "context_id": "shared-context"}
        launch_id = parse_qs(urlparse(path).query)["launch_id"][0]
        self.polls[launch_id] = self.polls.get(launch_id, 0) + 1
        if self.stranded_status and launch_id == "launch-0":
            return {
                "status": "failed",
                "task_status": self.stranded_status,
                "task_id": "stranded-task",
                "task_run_id": "stranded-run",
                "invalid_reason": "The controlling workflow ended before its task.",
            }
        if self.polls[launch_id] == 1:
            return {"status": "in_progress", "task_status": "in_progress"}
        self.active.remove(launch_id)
        return {"status": "completed", "task_status": "completed"}

    def read_json(self, path: str) -> list[Json]:
        return []


class TestScoutLiveTrialsCLI(TestCase):
    def setUp(self) -> None:
        self.output = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.object(cli.time, "sleep"))
        self.enterContext(patch.object(cli.time, "monotonic", side_effect=count()))

    def manifest(self, count: int) -> dict[str, Json]:
        return {
            "project_id": 2,
            "config_id": "source-scout",
            "runs": [
                {"status": "pending", "request": {"launch_id": f"launch-{index}", "variant": f"variant-{index}"}}
                for index in range(count)
            ],
        }

    @parameterized.expand(["not_started", "queued", "in_progress"])
    def test_active_task_after_controller_failure_stops_launches_and_can_resume(self, task_status: str) -> None:
        client = FakeTrialClient(stranded_status=task_status)
        comparison = cli.Comparison(client, self.output, self.manifest(2))

        with self.assertRaisesRegex(RuntimeError, "stranded-task.*stranded-run.*--resume"):
            comparison.run(concurrency=1, timeout=60)

        assert [launch["launch_id"] for launch in client.launches] == ["launch-0"]
        result = json.loads((self.output / "launch-0.result.json").read_text())
        assert result["task_status"] == task_status
        saved = json.loads((self.output / "manifest.json").read_text())
        assert [run["status"] for run in saved["runs"]] == ["running", "pending"]
        assert saved["runs"][0]["result_file"] == "launch-0.result.json"

        client.stranded_status = None
        cli.Comparison(client, self.output, saved).run(concurrency=1, timeout=60)

        assert [launch["launch_id"] for launch in client.launches] == ["launch-0", "launch-1"]
        assert client.peak_active == 1
        assert not client.active
        saved = json.loads((self.output / "manifest.json").read_text())
        assert [run["status"] for run in saved["runs"]] == ["done", "done"]

    def test_parallel_batch_shares_context_and_respects_concurrency(self) -> None:
        client = FakeTrialClient()
        cli.Comparison(client, self.output, self.manifest(4)).run(concurrency=2, timeout=60)

        assert client.peak_active == 2
        assert not client.active
        assert [launch.get("context_id") for launch in client.launches] == [None, *["shared-context"] * 3]
        assert len(list(self.output.glob("*.result.json"))) == 4
        saved = json.loads((self.output / "manifest.json").read_text())
        assert [run["status"] for run in saved["runs"]] == ["done"] * 4
