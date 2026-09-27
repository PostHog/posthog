from __future__ import annotations

import json
import importlib
import multiprocessing
from io import BytesIO, StringIO
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from urllib.request import Request

cli = importlib.import_module(
    "products.signals.eval.experiments.2026-09-long-running-agent-evals.scripts.run_live_trials"
)

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]


class FakeTrialClient:
    def __init__(self, stranded_status: str | None = None, interrupt_first_poll: bool = False) -> None:
        self.stranded_status = stranded_status
        self.interrupt_first_poll = interrupt_first_poll
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
        if self.interrupt_first_poll:
            self.interrupt_first_poll = False
            raise KeyboardInterrupt
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


def run_paused_controller(arguments: list[str], variants: Path, connection: Connection, after_launch: bool) -> None:
    original_read = Path.read_text

    def pause(launches: list[dict[str, Json]]) -> None:
        connection.send([launch["launch_id"] for launch in launches])
        connection.recv()

    def read_text(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == variants and not after_launch:
            pause([])
        return original_read(path, encoding=encoding, errors=errors)

    class PausedTrialClient(FakeTrialClient):
        def request(self, path: str, body: dict[str, Json] | None = None) -> dict[str, Json]:
            if body is None and after_launch:
                pause(self.launches)
            return super().request(path, body)

    client = PausedTrialClient(interrupt_first_poll=True)
    with (
        patch.object(Path, "read_text", read_text),
        patch.object(cli, "TrialClient", return_value=client),
        patch.object(cli.sys, "argv", arguments),
    ):
        try:
            cli.main()
        except SystemExit as stopped:
            connection.send(
                {"exit_code": stopped.code, "launch_ids": [launch["launch_id"] for launch in client.launches]}
            )


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

    @parameterized.expand([(1, None, 1), (3, None, 3), (1, 2, 2)])
    def test_interrupted_cli_resumes_with_saved_or_explicit_concurrency(
        self, initial: int, override: int | None, expected: int
    ) -> None:
        client = FakeTrialClient(interrupt_first_poll=True)
        variants = self.output / "variants.json"
        variants.write_text(json.dumps([{"label": "baseline"}]))
        self.enterContext(patch.dict(cli.os.environ, {"POSTHOG_API_KEY": "synthetic-test-key"}))
        self.enterContext(patch.object(cli, "TrialClient", return_value=client))
        arguments = ["run_live_trials", "--output", str(self.output)]
        with patch.object(
            cli.sys,
            "argv",
            [
                *arguments,
                "--project-id",
                "2",
                "--config-id",
                "source-scout",
                "--variants",
                str(variants),
                "--repeats",
                "4",
                "--concurrency",
                str(initial),
            ],
        ):
            with self.assertRaises(SystemExit) as stopped:
                cli.main()
        assert stopped.exception.code == 1
        saved = json.loads((self.output / "manifest.json").read_text())
        assert saved["concurrency"] == initial
        launch_ids = [row["request"]["launch_id"] for row in saved["runs"]]
        assert len(client.launches) == 1

        resume = [*arguments, "--resume"]
        if override is not None:
            resume.extend(["--concurrency", str(override)])
        with patch.object(cli.sys, "argv", resume):
            cli.main()

        assert client.peak_active == expected
        assert not client.active
        assert [launch["launch_id"] for launch in client.launches] == launch_ids
        saved = json.loads((self.output / "manifest.json").read_text())
        assert saved["concurrency"] == expected
        assert [row["status"] for row in saved["runs"]] == ["done"] * 4

    def test_legacy_manifest_resumes_one_run_at_a_time(self) -> None:
        manifest = {**self.manifest(4), "host": "http://localhost:8000"}
        cli.save_json(self.output / "manifest.json", manifest)
        client = FakeTrialClient()
        self.enterContext(patch.dict(cli.os.environ, {"POSTHOG_API_KEY": "synthetic-test-key"}))
        self.enterContext(patch.object(cli, "TrialClient", return_value=client))
        with patch.object(cli.sys, "argv", ["run_live_trials", "--output", str(self.output), "--resume"]):
            cli.main()

        assert client.peak_active == 1
        saved = json.loads((self.output / "manifest.json").read_text())
        assert saved["concurrency"] == 1
        assert [row["status"] for row in saved["runs"]] == ["done"] * 4

    @parameterized.expand([(1, True), (4, False)])
    def test_connection_resets_retry_the_same_launch_request_with_a_bounded_attempt_count(
        self, reset_count: int, succeeds: bool
    ) -> None:
        body = {"launch_id": "synthetic-launch", "variant": "baseline", "skill_body": "Review synthetic events."}
        started = {"launch_id": body["launch_id"], "context_id": "shared-context"}
        submitted: list[bytes] = []

        def open_request(request: Request, timeout: int) -> BytesIO:
            assert isinstance(request.data, bytes)
            submitted.append(request.data)
            if len(submitted) <= reset_count:
                raise ConnectionResetError("Connection reset by peer")
            return BytesIO(json.dumps(started).encode())

        with patch.object(cli, "build_opener") as opener:
            opener.return_value.open.side_effect = open_request
            client = cli.TrialClient("http://localhost:8000", "synthetic-test-key")
            if succeeds:
                assert client.request("/trial/", body) == started
            else:
                with self.assertRaisesRegex(RuntimeError, "retry this saved manifest"):
                    client.request("/trial/", body)

        assert len(submitted) == (reset_count + 1 if succeeds else 4)
        assert len(set(submitted)) == 1
        assert json.loads(submitted[0]) == body

    @parameterized.expand([False, True])
    def test_competing_controllers_cannot_replace_runs_and_can_resume_after_exit(self, crash: bool) -> None:
        variants = self.output / "variants.json"
        variants.write_text(json.dumps([{"label": "baseline"}]))
        arguments = [
            "run_live_trials",
            "--output",
            str(self.output),
            "--project-id",
            "2",
            "--config-id",
            "source-scout",
            "--variants",
            str(variants),
            "--repeats",
            "2",
        ]
        self.enterContext(patch.dict(cli.os.environ, {"POSTHOG_API_KEY": "synthetic-test-key"}))
        context = multiprocessing.get_context("spawn")
        connection, child_connection = context.Pipe()
        owner = context.Process(target=run_paused_controller, args=(arguments, variants, child_connection, crash))
        owner.start()
        try:
            assert connection.poll(10), "The owner did not reach the controlled pause."
            owner_launch_ids = connection.recv()
            manifest_path = self.output / "manifest.json"
            original_manifest = manifest_path.read_bytes() if crash else None
            client = FakeTrialClient()
            self.enterContext(patch.object(cli, "TrialClient", return_value=client))
            for competing in (arguments, [*arguments, "--resume"]):
                with patch.object(cli.sys, "argv", competing), patch.object(cli.sys, "stderr", StringIO()) as error:
                    with self.assertRaises(SystemExit) as refused:
                        cli.main()
                assert refused.exception.code == 2
                assert "Another controller" in error.getvalue()
                assert client.launches == []
                assert (manifest_path.read_bytes() if manifest_path.exists() else None) == original_manifest

            if crash:
                owner.kill()
            else:
                connection.send("continue")
                assert connection.poll(10), "The owner did not save its interrupted run."
                stopped = connection.recv()
                assert stopped["exit_code"] == 1
                owner_launch_ids = stopped["launch_ids"]
            owner.join(timeout=10)
            assert not owner.is_alive()
            assert owner.exitcode == (-9 if crash else 0)

            saved = json.loads(manifest_path.read_text())
            launch_ids = [row["request"]["launch_id"] for row in saved["runs"]]
            assert len(owner_launch_ids) == 1
            assert owner_launch_ids[0] == launch_ids[0]
            client.active.update(owner_launch_ids)
            with patch.object(cli.sys, "argv", [*arguments, "--resume"]):
                cli.main()

            assert [*owner_launch_ids, *[launch["launch_id"] for launch in client.launches]] == launch_ids
            assert not client.active
            assert all(row["status"] == "done" for row in json.loads(manifest_path.read_text())["runs"])
        finally:
            if owner.is_alive():
                owner.kill()
            owner.join(timeout=10)
            connection.close()
            child_connection.close()
