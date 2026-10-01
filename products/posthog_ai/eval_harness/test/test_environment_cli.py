from __future__ import annotations

import io
import os
import json
import hashlib
import tarfile
import argparse
import tempfile
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from unittest import TestCase
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.posthog_ai.eval_harness.environment import cli
from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.schema import (
    EVENT_TABLE,
    METRIC_TABLE,
    EnvironmentEvent,
    EnvironmentMetric,
)

SOURCE = datetime(2030, 6, 4, 12, tzinfo=UTC)


def write_inputs(root: Path) -> tuple[Path, Path]:
    events = root / "source-events.parquet"
    metrics = root / "source-metrics.parquet"
    EVENT_TABLE.write(
        events,
        [
            EnvironmentEvent(
                uuid=UUID("00000000-0000-4000-8000-000000000001"),
                event="example_action",
                distinct_id="example-user",
                timestamp=SOURCE - timedelta(hours=1),
                created_at=SOURCE - timedelta(minutes=59),
                properties={"duration": 3, "enabled": True, "example": None},
            )
        ],
    )
    METRIC_TABLE.write(
        metrics,
        [
            EnvironmentMetric(
                id=UUID("00000000-0000-4000-8000-000000000002"),
                created_at=SOURCE - timedelta(days=1),
                name="example_actions",
                description="Count example actions.",
                status="approved",
            )
        ],
    )
    return events, metrics


def checksum_manifest(folder: Path) -> None:
    rows = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(folder).as_posix()}\n"
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (folder / "SHA256SUMS").write_text("".join(rows))


def bundle(root: Path) -> Path:
    folder = root / "fixtures"
    events, metrics = write_inputs(root)
    EnvironmentDataset.build(
        folder,
        environment_id="example-environment",
        event_paths=[events],
        metrics_path=metrics,
        source_cutoff=SOURCE,
    )
    checksum_manifest(folder)
    archive = root / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(folder, arcname="fixtures")
    return archive


class TestEnvironmentInput(TestCase):
    def test_archive_and_folder_load_identical_data_and_reuse_private_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = bundle(root)
            workspace = root / "state"
            workspace.mkdir()
            source_bytes = archive.read_bytes()
            folder = cli.EnvironmentInput.unpack(archive, workspace)
            original = EnvironmentDataset.load(root / "fixtures/environment.json")
            extracted = EnvironmentDataset.load(folder / "environment.json")
            self.assertEqual(extracted.manifest, original.manifest)
            self.assertEqual(list(extracted.events()), list(original.events()))
            self.assertEqual(extracted.metrics, original.metrics)
            self.assertEqual(cli.EnvironmentInput.unpack(archive, workspace), folder)
            self.assertEqual(archive.read_bytes(), source_bytes)
            self.assertEqual(len(list(workspace.glob("bundle-*"))), 1)
            for path in folder.rglob("*"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    @parameterized.expand(["traversal", "absolute", "symlink", "hardlink", "special", "duplicate", "oversized"])
    def test_unsafe_archives_are_rejected_without_publishing_extracted_bundle(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "state"
            workspace.mkdir()
            archive = root / "unsafe.tar.gz"
            member = tarfile.TarInfo("fixtures/item")
            if failure == "traversal":
                member.name = "../outside"
            elif failure == "absolute":
                member.name = str(root / "outside")
            elif failure in {"symlink", "hardlink"}:
                member.type = tarfile.SYMTYPE if failure == "symlink" else tarfile.LNKTYPE
                member.linkname = "../../outside"
            elif failure == "special":
                member.type = tarfile.FIFOTYPE
            with tarfile.open(archive, "w:gz") as output:
                output.addfile(member)
                if failure == "duplicate":
                    output.addfile(member)
            with patch.object(cli, "MAX_ARCHIVE_MEMBERS", 0 if failure == "oversized" else 10_000):
                with self.assertRaises(ValueError):
                    cli.EnvironmentInput.unpack(archive, workspace)
            self.assertFalse((root / "outside").exists())
            self.assertEqual(list(workspace.iterdir()), [])

    @parameterized.expand(["changed", "extra", "missing", "symlink", "unsafe_checksum", "duplicate_checksum"])
    def test_checksum_manifest_cannot_hide_changed_or_unlisted_files(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle(root)
            folder = root / "fixtures"
            if failure == "changed":
                (folder / "environment.json").write_text("{}")
            elif failure == "extra":
                (folder / "unlisted.txt").write_text("Unexpected file.")
            elif failure == "missing":
                (folder / "environment.json").unlink()
            elif failure == "symlink":
                (folder / "link").symlink_to(root)
            elif failure == "unsafe_checksum":
                (folder / "SHA256SUMS").write_text(f"{'0' * 64}  ../outside\n")
            elif failure == "duplicate_checksum":
                content = (folder / "SHA256SUMS").read_text()
                (folder / "SHA256SUMS").write_text(content + content.splitlines()[0] + "\n")
            with self.assertRaises(ValueError):
                cli.EnvironmentInput.unpack(folder, root / "state")

    def test_workspace_lock_refuses_overlapping_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with cli.workspace_lock(Path(temporary)):
                with self.assertRaisesRegex(ValueError, "Another fixture preparation"):
                    with cli.workspace_lock(Path(temporary)):
                        self.fail("The second preparation acquired the lock")


class TestEnvironmentApp(TestCase):
    @parameterized.expand(
        [((200, 302, 401), True), ((200, 200, 401), True), ((200, 302, 500), False), ((200, 404), False)]
    )
    def test_readiness_requires_health_page_and_unauthenticated_api(
        self, statuses: tuple[int, ...], expected: bool
    ) -> None:
        with patch.object(cli.LocalApp, "status", side_effect=statuses):
            self.assertEqual(cli.LocalApp.healthy(), expected)

    def test_healthy_foreign_checkout_is_reused_without_start_or_port_changes(self) -> None:
        with (
            patch.object(cli.LocalApp, "healthy", return_value=True),
            patch.object(cli.LocalApp, "checkout", return_value="/invented/another-checkout"),
            patch.object(cli.LocalApp, "process_status", return_value={"status": "done", "exit_code": 0}),
            patch.object(cli.LocalApp, "occupied_ports") as ports,
            patch.object(cli.subprocess, "run") as command,
        ):
            self.assertEqual(cli.LocalApp.ensure(timeout=60, workspace=Path("/unused")), "/invented/another-checkout")
        ports.assert_not_called()
        command.assert_not_called()

    def test_partial_stack_is_not_stopped_or_replaced(self) -> None:
        with (
            patch.object(cli.LocalApp, "healthy", return_value=False),
            patch.object(cli.LocalApp, "occupied_ports", return_value=[8000]),
            patch.object(cli.subprocess, "run") as command,
        ):
            with self.assertRaisesRegex(ValueError, "will not stop or replace"):
                cli.LocalApp.ensure(timeout=60, workspace=Path("/unused"))
        command.assert_not_called()

    def test_stopped_app_uses_own_checkout_and_skips_zombie_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with (
                patch.object(cli.LocalApp, "healthy", side_effect=[False, True]),
                patch.object(cli.LocalApp, "occupied_ports", return_value=[]),
                patch.object(cli.LocalApp, "checkout", return_value=None),
                patch.object(cli.LocalApp, "process_status", return_value={"status": "done", "exit_code": 0}),
                patch.object(cli.subprocess, "run") as command,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(cli.LocalApp.ensure(timeout=60, workspace=workspace), str(cli.REPO_ROOT))
            self.assertEqual(
                command.call_args.args[0],
                [
                    str(cli.REPO_ROOT / ".codex/with-flox"),
                    "env",
                    "HOGLI_SKIP_ZOMBIE_CHECK=1",
                    "HOGLI_SKIP_GIT_CHECK=1",
                    "hogli",
                    "up",
                    "-d",
                    "-y",
                ],
            )
            self.assertEqual(command.call_args.kwargs["cwd"], cli.REPO_ROOT)
            self.assertEqual((workspace / "app-start.log").stat().st_mode & 0o777, 0o600)

    @parameterized.expand(["crashed", "stopped", "done"])
    def test_healthy_http_does_not_override_failed_clickhouse_migrations(self, status: str) -> None:
        with (
            patch.object(cli.LocalApp, "healthy", return_value=True),
            patch.object(cli.LocalApp, "checkout", return_value="/invented/app"),
            patch.object(
                cli.LocalApp,
                "process_status",
                side_effect=[{"status": "done", "exit_code": 0}, {"status": status, "exit_code": 1}],
            ),
            patch.object(cli.subprocess, "run") as command,
        ):
            with self.assertRaisesRegex(ValueError, "inspect migrate-clickhouse"):
                cli.LocalApp.ensure(timeout=60, workspace=Path("/unused"))
        command.assert_not_called()

    def test_migrations_are_allowed_to_finish_without_restarting_workers(self) -> None:
        with (
            patch.object(
                cli.LocalApp,
                "process_status",
                side_effect=[
                    {"status": "running"},
                    {"status": "done", "exit_code": 0},
                    {"status": "done", "exit_code": 0},
                    {"status": "done", "exit_code": 0},
                ],
            ) as status,
            patch.object(cli.time, "sleep"),
        ):
            cli.LocalApp.wait_for_migrations("/invented/app", timeout=60)
        self.assertEqual(status.call_count, 4)
        status.assert_called_with("/invented/app", "migrate-clickhouse")

    @parameterized.expand([None, "/invented/other-checkout"])
    def test_pending_migrations_never_change_a_foreign_or_unknown_app(self, checkout: str | None) -> None:
        backend = Mock(spec=["assert_migrations_current", "restore"])
        backend.assert_migrations_current.side_effect = cli.EnvironmentMigrationsPending("Pending")
        with patch.object(cli.subprocess, "run") as command:
            with self.assertRaisesRegex(ValueError, "Start the normal app from this checkout"):
                cli.LocalApp.ensure_postgres_migrations(
                    backend, checkout=checkout, workspace=Path("/unused"), timeout=60
                )
        command.assert_not_called()

    @parameterized.expand(["current", "forward", "command_failed", "still_pending", "unexpected_failure"])
    def test_own_checkout_migrations_are_forward_only_and_rechecked(self, outcome: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            backend = Mock(spec=["assert_migrations_current", "restore"])
            pending = cli.EnvironmentMigrationsPending("Pending")
            backend.assert_migrations_current.side_effect = (
                [None]
                if outcome == "current"
                else [RuntimeError("Unexpected preflight failure")]
                if outcome == "unexpected_failure"
                else [pending, pending if outcome == "still_pending" else None]
            )
            with patch.object(cli.subprocess, "run") as command, redirect_stdout(io.StringIO()):
                if outcome == "command_failed":
                    command.side_effect = subprocess.CalledProcessError(1, ["invented-command"])
                if outcome in {"command_failed", "still_pending", "unexpected_failure"}:
                    with self.assertRaises((ValueError, RuntimeError)):
                        cli.LocalApp.ensure_postgres_migrations(
                            backend, checkout=str(cli.REPO_ROOT), workspace=workspace, timeout=60
                        )
                else:
                    cli.LocalApp.ensure_postgres_migrations(
                        backend, checkout=str(cli.REPO_ROOT), workspace=workspace, timeout=60
                    )
            expected_commands = (
                []
                if outcome in {"current", "unexpected_failure"}
                else [
                    [str(cli.REPO_ROOT / ".codex/with-flox"), "python", "manage.py", "migrate", "--noinput"],
                    [str(cli.REPO_ROOT / ".codex/with-flox"), "python", "manage.py", "migrate_product_databases"],
                ][: 1 if outcome == "command_failed" else 2]
            )
            self.assertEqual([call.args[0] for call in command.call_args_list], expected_commands)
            for call in command.call_args_list:
                self.assertEqual(call.kwargs["cwd"], cli.REPO_ROOT)
                self.assertEqual(call.kwargs["timeout"], 60)
                self.assertTrue(call.kwargs["check"])
            if expected_commands:
                self.assertEqual((workspace / "migrations.log").stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                backend.assert_migrations_current.call_count, 2 if outcome in {"forward", "still_pending"} else 1
            )
            self.assertFalse((workspace / "receipt.json").exists())


class TestEnvironmentCLI(TestCase):
    def test_database_errors_do_not_print_sql_or_credentials(self) -> None:
        output = io.StringIO()
        with (
            patch.object(cli, "prepare", side_effect=cli.DatabaseError("SELECT private_payload: invented-secret")),
            redirect_stderr(output),
        ):
            self.assertEqual(cli.main(["prepare", "/invented/fixtures"]), 1)
        self.assertIn("local database operation failed (DatabaseError)", output.getvalue())
        self.assertNotIn("SELECT", output.getvalue())
        self.assertNotIn("invented-secret", output.getvalue())

    def test_foreign_pending_migrations_stop_before_restore_or_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = bundle(root)
            workspace = root / "state"
            backend = Mock(spec=["assert_migrations_current", "restore"])
            backend.assert_migrations_current.side_effect = cli.EnvironmentMigrationsPending("Pending")
            with (
                patch.object(cli, "load_backend", return_value=backend),
                patch.object(cli, "assert_local_databases", return_value={}),
                patch.object(cli.LocalApp, "ensure", return_value="/invented/another-checkout"),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(ValueError, "No migrations or project import were started"):
                    cli.prepare(
                        argparse.Namespace(
                            environment=archive, state_dir=workspace, target_cutoff=None, user_id=None, timeout=60
                        )
                    )
            backend.restore.assert_not_called()
            self.assertFalse((workspace / "receipt.json").exists())
            self.assertFalse((workspace / "migrations.log").exists())

    def test_failed_app_start_keeps_validated_dataset_reusable_without_initializing_django(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = bundle(root)
            workspace = root / "state"
            args = argparse.Namespace(
                environment=archive, state_dir=workspace, target_cutoff=None, user_id=None, timeout=60
            )
            with (
                patch.object(cli, "load_backend") as backend,
                patch.object(cli, "assert_local_databases", return_value={}),
                patch.object(cli.LocalApp, "ensure", side_effect=ValueError("Startup unavailable")),
            ):
                with self.assertRaisesRegex(ValueError, "Startup unavailable"):
                    cli.prepare(args)
                backend.assert_not_called()
            folder = cli.EnvironmentInput.unpack(archive, workspace)
            manifest_bytes = (folder / "environment.json").read_bytes()
            prepared = EnvironmentDataset.load(folder / "environment.json")
            with patch.object(cli, "assert_local_databases", return_value={}):
                cli.validate_receipt(prepared, workspace, None, None)
            self.assertEqual(prepared.path.read_bytes(), manifest_bytes)
            self.assertFalse((workspace / "receipt.json").exists())

    @parameterized.expand(["pending", "failed", "wrong_source", "changed_database", "changed_user", "changed_cutoff"])
    def test_incompatible_receipt_is_rejected_before_app_start(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = bundle(root)
            workspace = root / "state"
            workspace.mkdir()
            folder = cli.EnvironmentInput.unpack(archive, workspace)
            prepared = EnvironmentDataset.load(folder / "environment.json")
            receipt = {
                "phase": failure if failure in {"pending", "failed"} else "complete",
                "databases": {},
                "manifest_sha256": prepared.manifest_sha256,
                "user_id": 10,
                "target_cutoff": SOURCE.isoformat(),
            }
            if failure == "wrong_source":
                receipt["manifest_sha256"] = "0" * 64
            elif failure == "changed_database":
                receipt["databases"] = {"host": "other-local-database"}
            (workspace / "receipt.json").write_text(json.dumps(receipt))
            with (
                patch.object(cli, "assert_local_databases", return_value={}),
                patch.object(cli.LocalApp, "ensure") as start,
                patch.object(cli, "load_backend") as backend,
            ):
                with self.assertRaises(ValueError):
                    cli.prepare(
                        argparse.Namespace(
                            environment=archive,
                            state_dir=workspace,
                            target_cutoff=SOURCE + timedelta(days=1) if failure == "changed_cutoff" else None,
                            user_id=11 if failure == "changed_user" else None,
                            timeout=60,
                        )
                    )
            start.assert_not_called()
            backend.assert_not_called()

    @parameterized.expand(["input", "local_guard", "dataset"])
    def test_invalid_input_or_local_guard_never_starts_services_or_imports(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle(root)
            source = root / "fixtures"
            if failure == "input":
                (source / "environment.json").write_text("Unexpected manifest replacement.")
            backend = Mock(spec=["assert_migrations_current", "restore"])
            with (
                patch.object(cli, "load_backend", return_value=backend),
                patch.object(cli.LocalApp, "ensure") as start,
                patch.object(cli, "assert_local_databases", return_value={}) as guard,
                patch.object(EnvironmentDataset, "load", wraps=EnvironmentDataset.load) as validate,
            ):
                if failure == "local_guard":
                    guard.side_effect = RuntimeError("Only normal local databases")
                elif failure == "dataset":
                    validate.side_effect = ValueError("Conflicting event IDs")
                with self.assertRaises((ValueError, RuntimeError)):
                    cli.prepare(
                        argparse.Namespace(
                            environment=source, state_dir=root / "state", target_cutoff=None, user_id=None, timeout=60
                        )
                    )
            start.assert_not_called()
            backend.restore.assert_not_called()

    def test_cli_passes_optional_cutoff_to_receipt_owner_and_never_prints_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = bundle(root)
            workspace = root / "state"
            backend = Mock(spec=["assert_migrations_current", "restore"])
            backend.restore.return_value = SimpleNamespace(
                reused=True,
                event_count=20,
                team_id=456,
                target_cutoff=SOURCE,
                receipt_path=workspace / "receipt.json",
                credentials_path=workspace / "login-credentials.json",
            )
            output = io.StringIO()
            with (
                patch.object(cli, "load_backend", return_value=backend),
                patch.object(cli.LocalApp, "ensure", return_value="/invented/app-checkout"),
                patch.object(cli, "assert_local_databases", return_value={}),
                patch.dict(os.environ, {"SITE_URL": "https://cli.example.com"}),
                redirect_stdout(output),
            ):
                cli.prepare(
                    argparse.Namespace(
                        environment=archive, state_dir=workspace, target_cutoff=None, user_id=42, timeout=60
                    )
                )
            self.assertIsNone(backend.restore.call_args.kwargs["target_cutoff"])
            self.assertEqual(backend.restore.call_args.kwargs["user_id"], 42)
            self.assertEqual(backend.restore.call_args.kwargs["provenance"]["app_checkout"], "/invented/app-checkout")
            self.assertIn("https://cli.example.com/project/456/", output.getvalue())
            self.assertIn(str(workspace / "login-credentials.json"), output.getvalue())
            self.assertNotIn("password", output.getvalue())

    @parameterized.expand(
        ["https://user:password@example.com", "https://example.com/?token=secret", "file:///tmp/page"]
    )
    def test_project_link_does_not_print_credentials_or_non_http_urls(self, site: str) -> None:
        with patch.dict(os.environ, {"SITE_URL": site}):
            self.assertEqual(cli.project_link(456), "http://localhost:8010/project/456/activity/explore")

    def test_cutoff_requires_timezone_and_normalizes_utc(self) -> None:
        self.assertEqual(cli.parse_cutoff("2030-06-04T14:00:00+02:00"), SOURCE)
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.parse_cutoff("2030-06-04T12:00:00")


class TestEnvironmentPack(TestCase):
    def test_pack_round_trip_contains_only_manifest_data_and_checksums_without_loading_django(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events, metrics = write_inputs(root)
            originals = {path: path.read_bytes() for path in (events, metrics)}
            (root / "unrelated-secret.txt").write_text("invented secret excluded from bundle")
            archive = root / "environment.tar.gz"
            with (
                patch.object(cli.django, "setup") as django_setup,
                patch.object(cli, "load_backend") as backend,
                patch.object(cli.LocalApp, "ensure") as start,
                patch.dict(os.environ, {"EVAL_ENVIRONMENT_INVOCATION_DIR": str(root)}),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    cli.main(
                        [
                            "pack",
                            "--events",
                            events.name,
                            "--metrics",
                            metrics.name,
                            "--source-cutoff",
                            SOURCE.isoformat(),
                            "--name",
                            "example-environment",
                            "--output",
                            archive.name,
                        ]
                    ),
                    0,
                )
            django_setup.assert_not_called()
            backend.assert_not_called()
            start.assert_not_called()
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            with tarfile.open(archive) as packed:
                for member in packed:
                    self.assertTrue(member.isfile() or member.isdir())
                    self.assertEqual(member.mode, 0o700 if member.isdir() else 0o600)
                    self.assertEqual((member.uid, member.gid, member.uname, member.gname), (0, 0, "", ""))
            workspace = root / "state"
            workspace.mkdir()
            folder = cli.EnvironmentInput.unpack(archive, workspace)
            dataset = EnvironmentDataset.load(folder / "environment.json")
            self.assertEqual(list(dataset.events()), list(EVENT_TABLE.read(events)))
            self.assertEqual(dataset.metrics, list(METRIC_TABLE.read(metrics)))
            allowed = {dataset.path, folder / "SHA256SUMS"}
            allowed.update(reference.resolve(folder) for reference in dataset.manifest.events)
            self.assertIsNotNone(dataset.manifest.metrics)
            if dataset.manifest.metrics:
                allowed.add(dataset.manifest.metrics.resolve(folder))
            self.assertEqual(cli.regular_files(folder), allowed)
            self.assertEqual(dataset.manifest.environment_id, "example-environment")
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    @parameterized.expand(["existing_output", "invalid_policy", "archive_limit"])
    def test_pack_failure_does_not_publish_or_replace_bundle(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events, _ = write_inputs(root)
            output = root / "environment.tar.gz"
            policy = root / "policy.json"
            policy.write_text(json.dumps({"unsupported": "invented-private-value"}))
            if failure == "existing_output":
                output.write_bytes(b"existing bundle")
            errors = io.StringIO()
            with (
                patch.object(cli, "MAX_ARCHIVE_BYTES", 1 if failure == "archive_limit" else 2 * 1024**3),
                redirect_stderr(errors),
                redirect_stdout(io.StringIO()),
            ):
                arguments = [
                    "pack",
                    "--events",
                    str(events),
                    "--source-cutoff",
                    SOURCE.isoformat(),
                    "--name",
                    "example-environment",
                    "--output",
                    str(output),
                ]
                if failure == "invalid_policy":
                    arguments += ["--text-policy", str(policy)]
                self.assertEqual(cli.main(arguments), 1)
            if failure == "existing_output":
                self.assertEqual(output.read_bytes(), b"existing bundle")
            else:
                self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".environment-pack-*")), [])
            self.assertNotIn("invented-private-value", errors.getvalue())

    def test_pack_embeds_only_explicit_text_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events, _ = write_inputs(root)
            policy = root / "policy.json"
            expected = {"time_strings": [], "string_replacements": {"example-user": "local-user"}}
            policy.write_text(json.dumps(expected))
            archive = root / "environment.tar.gz"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli.main(
                        [
                            "pack",
                            "--events",
                            str(events),
                            "--source-cutoff",
                            SOURCE.isoformat(),
                            "--source-id",
                            "example-environment",
                            "--text-policy",
                            str(policy),
                            "--output",
                            str(archive),
                        ]
                    ),
                    0,
                )
            workspace = root / "state"
            workspace.mkdir()
            folder = cli.EnvironmentInput.unpack(archive, workspace)
            manifest = EnvironmentDataset.load(folder / "environment.json").manifest
            self.assertEqual(manifest.string_replacements, expected["string_replacements"])
            self.assertIsNone(manifest.metrics)
            self.assertEqual(manifest.metric_count, 0)

    @parameterized.expand([([],), (["prepare"],), (["pack"],)])
    def test_help_never_initializes_django_or_starts_the_app(self, arguments: list[str]) -> None:
        with (
            patch.object(cli.django, "setup") as django_setup,
            patch.object(cli, "load_backend") as backend,
            patch.object(cli.LocalApp, "ensure") as start,
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as exit_status:
                cli.main([*arguments, "--help"])
            self.assertEqual(exit_status.exception.code, 0)
        django_setup.assert_not_called()
        backend.assert_not_called()
        start.assert_not_called()
