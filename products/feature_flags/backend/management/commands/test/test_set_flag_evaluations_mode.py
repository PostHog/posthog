import re
import fcntl
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.experiments.backend.facade.testing import create_experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import FlagEvaluationsConfig, get_organization_flag_evaluations_mode
from products.feature_flags.backend.flag_evaluations_mode import (
    OrganizationModeChange,
    RecordedHistory,
    RestoreOutcome,
    restore_organizations_flag_evaluations_configs,
    set_organizations_flag_evaluations_mode,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

FLAG_CALL_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "source": {"kind": "EventsNode", "event": "$feature_flag_called"},
}


class TestSetFlagEvaluationsMode(BaseTest):
    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("set_flag_evaluations_mode", *args, stdout=out)
        return out.getvalue()

    def _stored_mode(self, organization: Organization) -> int | None:
        return (
            OrganizationFeatureFlagsConfig.objects.filter(organization=organization)
            .values_list("flag_evaluations_mode", flat=True)
            .first()
        )

    def _keeps_events_writes(self, organization: Organization) -> bool:
        return OrganizationFeatureFlagsConfig.objects.get(organization=organization).keep_writing_flag_calls_to_events

    def _store_mode(self, organization: Organization, mode: FlagEvaluationsMode) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=organization, defaults={"flag_evaluations_mode": mode}
        )

    def _store_config(self, organization: Organization, mode: FlagEvaluationsMode, keeps_events_writes: bool) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=organization,
            defaults={"flag_evaluations_mode": mode, "keep_writing_flag_calls_to_events": keeps_events_writes},
        )

    def _stored_config(self, organization: Organization) -> tuple[int, bool]:
        config = OrganizationFeatureFlagsConfig.objects.get(organization=organization)
        return config.flag_evaluations_mode, config.keep_writing_flag_calls_to_events

    def _listed_ids(self, path: str) -> list[str]:
        return [line.split()[0] for line in Path(path).read_text().splitlines() if line.strip()]

    def _ids_file(self, *lines: object) -> str:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "ids.txt"
        path.write_text("".join(f"{line}\n" for line in lines))
        return str(path)

    def _file_locked_by_another_run(self) -> str:
        path = self._ids_file()
        file = open(path, "a")
        self.addCleanup(file.close)
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        return path

    def _organizations_without_config(self, count: int) -> list[Organization]:
        # bulk_create skips the post_save handler, so these organizations have no config row, like
        # the organizations created before the row existed.
        return Organization.objects.bulk_create(
            [Organization(name=f"Organization {i}", slug=uuid4().hex) for i in range(count)]
        )

    def test_an_organization_without_a_row_gets_one_at_the_target(self) -> None:
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).delete()

        self._run("--mode", "1", "--organization-id", str(self.organization.id))

        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.READ_FLAG_EVALUATIONS)

    def test_dry_run_reports_and_writes_nothing(self) -> None:
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).delete()

        output = self._run("--mode", "1", "--organization-id", str(self.organization.id), "--dry-run")

        self.assertIn(f"organization {self.organization.id}", output)
        self.assertIn("mode 0 -> 1", output)
        self.assertIn("Would set mode 1 on 1 organization(s).", output)
        self.assertIsNone(self._stored_mode(self.organization))

    @parameterized.expand(
        [
            ("flag_evaluations_only", lambda self: ("--mode", "2", *self._selects_organization), True, True),
            ("read_flag_evaluations", lambda self: ("--mode", "1", *self._selects_organization), True, False),
            (
                "skipped_count",
                lambda self: ("--mode", "2", *self._selects_organization, "--skip-experiment-count"),
                False,
                False,
            ),
            (
                "events_writes_kept",
                lambda self: ("--mode", "2", *self._selects_organization, "--keep-writing-flag-calls-to-events"),
                True,
                True,
            ),
            (
                "restore_to_flag_evaluations_only",
                lambda self: ("--restore-from-changed-ids-file", self._ids_file(f"{self.organization.id} 2 0 0 0")),
                True,
                True,
            ),
        ]
    )
    def test_warns_only_when_the_mode_stops_events_writes_of_flag_calls_an_experiment_reads(
        self, _name: str, build_args: Any, expects_count: bool, expects_warning: bool
    ) -> None:
        self._selects_organization = ("--organization-id", str(self.organization.id))
        create_experiment(
            team_id=self.team.id,
            feature_flag_id=FeatureFlag.objects.create(team=self.team, key="experiment-flag", created_by=self.user).id,
            name="Metric on flag calls",
            start_date=datetime(2026, 8, 1, tzinfo=UTC),
            metrics=[FLAG_CALL_METRIC],
        )

        output = self._run(*build_args(self), "--dry-run")

        self.assertEqual("1 experiment(s) reading $feature_flag_called from events" in output, expects_count)
        self.assertEqual("1 running experiment(s) read $feature_flag_called from events" in output, expects_warning)

    def test_keep_writing_flag_calls_to_events_applies_to_mode_2_and_clears_when_the_mode_moves(self) -> None:
        organization_id = str(self.organization.id)
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        self._run("--mode", "2", "--keep-writing-flag-calls-to-events", "--organization-id", organization_id)
        self.assertTrue(self._keeps_events_writes(self.organization))

        self._run("--mode", "2", "--organization-id", organization_id)
        self.assertFalse(self._keeps_events_writes(self.organization))

        self._run("--mode", "2", "--keep-writing-flag-calls-to-events", "--organization-id", organization_id)
        self._run("--mode", "1", "--allow-downgrade", "--organization-id", organization_id)
        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        self.assertFalse(self._keeps_events_writes(self.organization))

    @time_machine.travel("2026-09-01T12:00:00Z", tick=False)
    def test_created_after_selects_only_newer_organizations(self) -> None:
        cutoff = timezone.now() - timedelta(minutes=5)
        Organization.objects.filter(id=self.organization.id).update(created_at=cutoff - timedelta(days=1))
        new_organization = Organization.objects.create(name="New organization")

        self._run("--mode", "1", "--organizations-created-after", cutoff.isoformat())

        self.assertEqual(
            get_organization_flag_evaluations_mode(new_organization.id), FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )
        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.EVENTS)

    @parameterized.expand(
        [
            (
                "keeps_a_higher_mode_by_default",
                (),
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "Left 1 organization(s) above mode 1.",
            ),
            (
                "lowers_it_with_allow_downgrade",
                ("--allow-downgrade",),
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                "Set mode 1 on 1 organization(s).",
            ),
        ]
    )
    def test_downgrade_guard(
        self, _name: str, extra_args: tuple[str, ...], expected_mode: int, expected_output: str
    ) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        output = self._run("--mode", "1", "--organization-id", str(self.organization.id), *extra_args)

        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), expected_mode)
        self.assertIn(expected_output, output)

    def test_allow_downgrade_lowers_the_stored_mode_while_reads_are_forced_to_events(self) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.READ_FLAG_EVALUATIONS)

        with override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", True):
            self._run("--mode", "0", "--organization-id", str(self.organization.id), "--allow-downgrade")

        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.EVENTS)

    def test_a_raise_after_the_read_is_not_overwritten(self) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        # The stale read stands in for a staff write that raises the organization between the
        # helper's read and its write.
        with patch(
            "products.feature_flags.backend.flag_evaluations_mode.get_organization_flag_evaluations_configs",
            return_value={
                self.organization.id: FlagEvaluationsConfig(mode=FlagEvaluationsMode.EVENTS, keeps_events_writes=False)
            },
        ):
            [change] = set_organizations_flag_evaluations_mode(
                [self.organization], FlagEvaluationsMode.READ_FLAG_EVALUATIONS, allow_downgrade=False, dry_run=False
            )

        self.assertFalse(change.changed)
        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

    def test_a_restore_does_not_overwrite_a_change_after_its_read(self) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        after_the_run = FlagEvaluationsConfig(mode=FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, keeps_events_writes=False)

        # The stale read stands in for a write that the row lock does not stop, such as an insert of a row that the
        # read found missing.
        with patch(
            "products.feature_flags.backend.flag_evaluations_mode.get_organization_flag_evaluations_configs",
            return_value={self.organization.id: after_the_run},
        ):
            [restore] = restore_organizations_flag_evaluations_configs(
                {
                    self.organization.id: RecordedHistory(
                        before=FlagEvaluationsConfig(mode=FlagEvaluationsMode.EVENTS, keeps_events_writes=False),
                        after=after_the_run,
                        unbroken=True,
                    )
                },
                dry_run=False,
            )

        self.assertEqual(restore.outcome, RestoreOutcome.CHANGED_OUTSIDE_THE_RUNS)
        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.READ_FLAG_EVALUATIONS)

    @parameterized.expand(
        [
            (
                "unknown_organization_id",
                lambda self, missing: ("--organization-id", str(self.organization.id), "--organization-id", missing),
                "Unknown organization",
            ),
            (
                "unknown_id_in_ids_file",
                lambda self, missing: ("--organization-ids-file", self._ids_file(self.organization.id, missing)),
                "Unknown organization",
            ),
            (
                "unknown_id_in_exclude_file",
                lambda self, missing: (
                    "--organization-id",
                    str(self.organization.id),
                    "--exclude-organization-ids-file",
                    self._ids_file(missing),
                ),
                "Unknown organization",
            ),
            (
                "line_that_is_not_an_id",
                lambda self, missing: (
                    "--organization-ids-file",
                    self._ids_file("organization_id", self.organization.id),
                ),
                "'organization_id' is not an organization id",
            ),
            (
                "line_that_is_not_an_id_in_exclude_file",
                lambda self, missing: ("--all-organizations", "--exclude-organization-ids-file", self._ids_file("2")),
                "'2' is not an organization id",
            ),
            (
                "changed_ids_file_on_a_dry_run",
                lambda self, missing: (
                    "--organization-id",
                    str(self.organization.id),
                    "--dry-run",
                    "--write-changed-ids",
                    self._ids_file(),
                ),
                "a dry run changes none",
            ),
            (
                "changed_ids_file_in_the_older_format_of_bare_ids",
                lambda self, missing: (
                    "--organization-id",
                    str(self.organization.id),
                    "--write-changed-ids",
                    self._ids_file(self.organization.id),
                ),
                "Write the changed ids to a new file",
            ),
            (
                "changed_ids_file_as_the_ids_file",
                lambda self, missing: (
                    "--organization-ids-file",
                    self._ids_file(f"{self.organization.id} 0 0 2 0"),
                ),
                "--restore-from-changed-ids-file",
            ),
            (
                "changed_ids_file_another_run_writes",
                lambda self, missing: (
                    "--organization-id",
                    str(self.organization.id),
                    "--write-changed-ids",
                    self._file_locked_by_another_run(),
                ),
                "Another run is writing to",
            ),
        ]
    )
    def test_refuses_the_run_before_writing(self, _name: str, build_args: Any, message: str) -> None:
        missing_id = "00000000-0000-0000-0000-000000000000"

        with self.assertRaisesMessage(CommandError, message):
            self._run("--mode", "1", *build_args(self, missing_id))

        self.assertEqual(get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.EVENTS)

    @parameterized.expand(
        [
            ("a_later_chunk_fails", "set_organizations_flag_evaluations_mode", True),
            ("the_ids_file_sync_fails", "os.fsync", False),
        ]
    )
    def test_a_failure_partway_keeps_the_ids_file_in_step_with_the_writes_and_a_rerun_finishes(
        self, _name: str, failing_call: str, first_chunk_commits: bool
    ) -> None:
        second = Organization.objects.create(name="Second organization")
        changed_ids_file = self._ids_file()
        args = (
            "--mode",
            "1",
            "--organization-id",
            str(self.organization.id),
            "--organization-id",
            str(second.id),
            "--chunk-size",
            "1",
            "--write-changed-ids",
            changed_ids_file,
        )

        def fail_on_second(
            organizations: Sequence[Organization], *args: Any, **kwargs: Any
        ) -> list[OrganizationModeChange]:
            if organizations[0].id == second.id:
                raise RuntimeError("write failed")
            return set_organizations_flag_evaluations_mode(organizations, *args, **kwargs)

        side_effect = (
            fail_on_second
            if failing_call == "set_organizations_flag_evaluations_mode"
            else [RuntimeError("sync failed"), None]
        )
        with (
            patch(
                f"products.feature_flags.backend.management.commands.set_flag_evaluations_mode.{failing_call}",
                side_effect=side_effect,
            ),
            self.assertRaises(RuntimeError),
        ):
            self._run(*args)

        self.assertEqual(
            get_organization_flag_evaluations_mode(self.organization.id),
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS if first_chunk_commits else FlagEvaluationsMode.EVENTS,
        )
        self.assertEqual(get_organization_flag_evaluations_mode(second.id), FlagEvaluationsMode.EVENTS)
        self.assertEqual(self._listed_ids(changed_ids_file), [str(self.organization.id)] if first_chunk_commits else [])

        self._run(*args)

        self.assertEqual(get_organization_flag_evaluations_mode(second.id), FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        self.assertEqual(self._listed_ids(changed_ids_file), [str(self.organization.id), str(second.id)])

    @parameterized.expand(
        [
            ("commit_applies", True, None, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
            ("commit_is_lost", False, None, FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False),
            (
                "commit_applies_then_another_writer_lowers_it",
                True,
                FlagEvaluationsMode.EVENTS,
                FlagEvaluationsMode.EVENTS,
                True,
            ),
        ]
    )
    def test_a_commit_that_raises_keeps_the_ids_of_a_chunk_that_may_have_committed(
        self,
        _name: str,
        commit_applies: bool,
        mode_another_writer_stores: FlagEvaluationsMode | None,
        expected_mode: int,
        expects_listed: bool,
    ) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        changed_ids_file = self._ids_file()
        real_atomic = transaction.atomic

        @contextmanager
        def atomic_whose_commit_raises() -> Iterator[None]:
            with real_atomic():
                yield
                if not commit_applies:
                    raise DatabaseError("connection lost before the commit")
            if mode_another_writer_stores is not None:
                self._store_mode(self.organization, mode_another_writer_stores)
            raise DatabaseError("connection lost after the commit")

        with (
            patch(
                "products.feature_flags.backend.management.commands.set_flag_evaluations_mode.transaction",
                SimpleNamespace(atomic=atomic_whose_commit_raises),
            ),
            self.assertRaises(DatabaseError),
        ):
            self._run(
                "--mode", "2", "--organization-id", str(self.organization.id), "--write-changed-ids", changed_ids_file
            )

        self.assertEqual(self._stored_mode(self.organization), expected_mode)
        self.assertEqual(self._listed_ids(changed_ids_file), [str(self.organization.id)] if expects_listed else [])

    def test_all_organizations_skips_the_excluded_ones(self) -> None:
        included, excluded = self._organizations_without_config(2)

        self._run("--mode", "2", "--all-organizations", "--exclude-organization-ids-file", self._ids_file(excluded.id))

        self.assertEqual(get_organization_flag_evaluations_mode(included.id), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        self.assertEqual(
            get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
        )
        self.assertEqual(get_organization_flag_evaluations_mode(excluded.id), FlagEvaluationsMode.EVENTS)

    def test_a_restore_puts_each_organization_the_run_changed_back_to_its_own_settings(self) -> None:
        moved_up, only_turned_on, already_kept, deleted_later = self._organizations_without_config(4)
        self._store_config(only_turned_on, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False)
        self._store_config(already_kept, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True)
        changed_ids_file = self._ids_file()
        ids_file = self._ids_file(moved_up.id, only_turned_on.id, already_kept.id, deleted_later.id)

        run_output = self._run(
            "--mode",
            "2",
            "--keep-writing-flag-calls-to-events",
            "--organization-ids-file",
            ids_file,
            "--write-changed-ids",
            changed_ids_file,
        )
        deleted_later.delete()
        output = self._run(
            "--restore-from-changed-ids-file", changed_ids_file, "--skip-unknown-organization-ids", "--chunk-size", "1"
        )

        self.assertIn(f"Appended 3 changed organization(s) to {changed_ids_file}.", run_output)
        self.assertIn(f"Skipping 1 unknown organization id(s) in {changed_ids_file}.", output)
        self.assertEqual(
            {
                organization: self._stored_config(organization)
                for organization in (moved_up, only_turned_on, already_kept)
            },
            {
                moved_up: (FlagEvaluationsMode.EVENTS, False),
                only_turned_on: (FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False),
                already_kept: (FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
            },
        )

    @parameterized.expand(
        [
            (
                "restores_the_first_record_of_an_organization_two_runs_changed",
                ["0 0 1 0", "1 0 2 0"],
                (FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False),
                (FlagEvaluationsMode.EVENTS, False),
                "Restored 1 organization(s).",
            ),
            (
                "leaves_an_organization_already_back_at_its_first_record",
                ["0 0 2 0"],
                (FlagEvaluationsMode.EVENTS, False),
                (FlagEvaluationsMode.EVENTS, False),
                "1 organization(s) already had the settings the file records from before the run.",
            ),
            (
                "keeps_an_organization_changed_since_the_run",
                ["0 0 2 0"],
                (FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False),
                (FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False),
                "Kept the settings of 1 organization(s)",
            ),
            (
                "keeps_an_organization_changed_between_two_runs",
                ["0 0 1 0", "2 0 2 1"],
                (FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
                (FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
                "Kept the settings of 1 organization(s)",
            ),
        ]
    )
    def test_a_restore_writes_only_an_organization_that_still_has_the_settings_the_runs_left(
        self,
        _name: str,
        records: list[str],
        current: tuple[FlagEvaluationsMode, bool],
        expected: tuple[FlagEvaluationsMode, bool],
        expected_output: str,
    ) -> None:
        self._store_config(self.organization, *current)
        changed_ids_file = self._ids_file(*(f"{self.organization.id} {record}" for record in records))

        output = self._run("--restore-from-changed-ids-file", changed_ids_file)

        self.assertEqual(self._stored_config(self.organization), expected)
        self.assertIn(expected_output, output)

    @parameterized.expand(
        [
            ("a_mode", ("--mode", "0"), "--mode"),
            ("an_exclude_file", ("--exclude-organization-ids-file", "ids"), "--exclude-organization-ids-file"),
            ("kept_writes", ("--keep-writing-flag-calls-to-events",), "--keep-writing-flag-calls-to-events"),
            ("a_changed_ids_file", ("--write-changed-ids", "ids"), "--write-changed-ids"),
            ("allow_downgrade", ("--allow-downgrade",), "--allow-downgrade"),
        ]
    )
    def test_a_restore_refuses_an_option_it_would_ignore(
        self, _name: str, extra_args: tuple[str, ...], message: str
    ) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        changed_ids_file = self._ids_file(f"{self.organization.id} 0 0 2 0")
        args = [self._ids_file() if arg == "ids" else arg for arg in extra_args]

        with self.assertRaisesMessage(CommandError, message):
            self._run("--restore-from-changed-ids-file", changed_ids_file, *args)

        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

    def test_a_restore_refuses_a_file_without_the_settings_from_before_the_run(self) -> None:
        self._store_mode(self.organization, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        changed_ids_file = self._ids_file(f"{self.organization.id} 0 0 2 0", self.organization.id)

        with self.assertRaisesMessage(CommandError, f"{changed_ids_file}:2:"):
            self._run("--restore-from-changed-ids-file", changed_ids_file)

        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

    def test_a_restore_locks_every_listed_row_in_id_order_before_it_writes(self) -> None:
        # Other writers lock rows in id order. The restore's UPDATE joins an unnest, whose plan sets the order it
        # locks rows in, so without an up-front lock in id order a concurrent writer can deadlock with it.
        first, second = self._organizations_without_config(2)
        self._store_config(first, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False)
        self._store_config(second, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False)
        changed_ids_file = self._ids_file(f"{second.id} 1 0 2 0", f"{first.id} 0 0 2 0")

        with CaptureQueriesContext(connection) as queries:
            self._run("--restore-from-changed-ids-file", changed_ids_file)

        statements = [query["sql"] for query in queries]
        lock = next(i for i, sql in enumerate(statements) if "FOR UPDATE" in sql)
        first_write = next(i for i, sql in enumerate(statements) if sql.lstrip().startswith("UPDATE"))
        self.assertLess(lock, first_write)
        self.assertRegex(statements[lock], r"^SELECT \S+\.\"organization_id\" .* ORDER BY 1 ASC FOR UPDATE$")
        self.assertEqual(self._stored_config(first), (FlagEvaluationsMode.EVENTS, False))
        self.assertEqual(self._stored_config(second), (FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False))

    def test_a_restore_that_fails_partway_finishes_when_it_runs_again(self) -> None:
        first, second = self._organizations_without_config(2)
        self._store_config(first, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False)
        self._store_config(second, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False)
        args = (
            "--restore-from-changed-ids-file",
            self._ids_file(f"{first.id} 0 0 2 0", f"{second.id} 0 0 2 0"),
            "--chunk-size",
            "1",
        )

        def fail_on_second(histories: Any, *args: Any, **kwargs: Any) -> Any:
            if second.id in histories:
                raise RuntimeError("write failed")
            return restore_organizations_flag_evaluations_configs(histories, *args, **kwargs)

        with (
            patch(
                "products.feature_flags.backend.management.commands.set_flag_evaluations_mode."
                "restore_organizations_flag_evaluations_configs",
                side_effect=fail_on_second,
            ),
            self.assertRaises(RuntimeError),
        ):
            self._run(*args)
        self.assertEqual(self._stored_mode(first), FlagEvaluationsMode.EVENTS)
        self.assertEqual(self._stored_mode(second), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        output = self._run(*args)

        self.assertEqual(self._stored_mode(second), FlagEvaluationsMode.EVENTS)
        self.assertIn("Restored 1 organization(s).", output)
        self.assertIn("1 organization(s) already had the settings the file records from before the run.", output)

    @parameterized.expand(
        [
            ("one_chunk_prints_a_line_per_organization", "1000", "2 team(s)): mode 1, unchanged", "chunk 1/"),
            (
                "several_chunks_print_a_line_per_chunk",
                "1",
                "chunk 3/3: 3/3 organization(s) done, 1 changed",
                "team(s)",
            ),
        ]
    )
    def test_a_dry_run_reports_what_the_run_does(
        self, _name: str, chunk_size: str, expected_line: str, unexpected_text: str
    ) -> None:
        Team.objects.create(organization=self.organization, name="Second team")
        on_two, without_row = self._organizations_without_config(2)
        self._store_mode(on_two, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        self._store_mode(self.organization, FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        args = ["--mode", "1", "--chunk-size", chunk_size, "--skip-experiment-count"]
        for organization in (self.organization, on_two, without_row):
            args += ["--organization-id", str(organization.id)]

        dry_run_output = self._run(*args, "--dry-run")
        output = self._run(*args)

        def without_timing(text: str) -> str:
            return re.sub(r", \d+s elapsed", "", text)

        self.assertEqual(without_timing(dry_run_output.replace("Would set", "Set")), without_timing(output))
        self.assertIn("Set mode 1 on 1 organization(s).", output)
        self.assertIn("Left 1 organization(s) above mode 1.", output)
        self.assertIn(expected_line, output)
        self.assertNotIn(unexpected_text, output)

    def test_a_run_appends_to_an_ids_file_that_lacks_a_final_newline(self) -> None:
        listed, moved = self._organizations_without_config(2)
        changed_ids_file = self._ids_file()
        Path(changed_ids_file).write_text(f"{listed.id} 0 0 1 0")

        self._run("--mode", "1", "--organization-id", str(moved.id), "--write-changed-ids", changed_ids_file)

        self.assertEqual(self._listed_ids(changed_ids_file), [str(listed.id), str(moved.id)])

    def test_the_upsert_sends_ids_in_sorted_order(self) -> None:
        organizations = self._organizations_without_config(5)

        with CaptureQueriesContext(connection) as queries:
            set_organizations_flag_evaluations_mode(
                list(reversed(organizations)),
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                allow_downgrade=False,
                dry_run=False,
            )

        [upsert] = [query["sql"] for query in queries if "unnest" in query["sql"]]
        sent_ids = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", upsert)
        self.assertEqual(sent_ids, sorted(str(organization.id) for organization in organizations))

    def test_a_chunk_takes_the_same_number_of_queries_for_any_number_of_organizations(self) -> None:
        def count_queries(organizations: list[Organization]) -> int:
            with CaptureQueriesContext(connection) as queries:
                self._run(
                    "--mode",
                    "1",
                    "--skip-experiment-count",
                    "--organization-ids-file",
                    self._ids_file(*(organization.id for organization in organizations)),
                )
            return len(queries)

        # The first run fills caches, such as the content type cache, that would add queries to only one of the
        # measured runs.
        count_queries(self._organizations_without_config(1))
        self.assertEqual(
            count_queries(self._organizations_without_config(3)), count_queries(self._organizations_without_config(30))
        )
