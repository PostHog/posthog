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
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode
from products.feature_flags.backend.flag_evaluations_mode import (
    OrganizationModeChange,
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
            ("flag_evaluations_only", "2", (), True, True),
            ("read_flag_evaluations", "1", (), True, False),
            ("skipped_count", "2", ("--skip-experiment-count",), False, False),
            ("events_writes_kept", "2", ("--keep-writing-flag-calls-to-events",), False, False),
        ]
    )
    def test_warns_only_when_the_mode_stops_events_writes_of_flag_calls_an_experiment_reads(
        self, _name: str, mode: str, extra_args: tuple[str, ...], expects_count: bool, expects_warning: bool
    ) -> None:
        create_experiment(
            team_id=self.team.id,
            feature_flag_id=FeatureFlag.objects.create(team=self.team, key="experiment-flag", created_by=self.user).id,
            name="Metric on flag calls",
            start_date=datetime(2026, 8, 1, tzinfo=UTC),
            metrics=[FLAG_CALL_METRIC],
        )

        output = self._run("--mode", mode, "--organization-id", str(self.organization.id), "--dry-run", *extra_args)

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
            "products.feature_flags.backend.flag_evaluations_mode.get_organization_flag_evaluations_modes",
            return_value={self.organization.id: FlagEvaluationsMode.EVENTS},
        ):
            [change] = set_organizations_flag_evaluations_mode(
                [self.organization], FlagEvaluationsMode.READ_FLAG_EVALUATIONS, allow_downgrade=False, dry_run=False
            )

        self.assertFalse(change.changed)
        self.assertEqual(self._stored_mode(self.organization), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

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
        self.assertEqual(
            Path(changed_ids_file).read_text().split(), [str(self.organization.id)] if first_chunk_commits else []
        )

        self._run(*args)

        self.assertEqual(get_organization_flag_evaluations_mode(second.id), FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        self.assertEqual(Path(changed_ids_file).read_text().split(), [str(self.organization.id), str(second.id)])

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
        self.assertEqual(
            Path(changed_ids_file).read_text().split(), [str(self.organization.id)] if expects_listed else []
        )

    def test_all_organizations_skips_the_excluded_ones(self) -> None:
        included, excluded = self._organizations_without_config(2)

        self._run("--mode", "2", "--all-organizations", "--exclude-organization-ids-file", self._ids_file(excluded.id))

        self.assertEqual(get_organization_flag_evaluations_mode(included.id), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        self.assertEqual(
            get_organization_flag_evaluations_mode(self.organization.id), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
        )
        self.assertEqual(get_organization_flag_evaluations_mode(excluded.id), FlagEvaluationsMode.EVENTS)

    def test_a_rollback_from_the_changed_ids_file_lowers_only_the_organizations_the_run_moved(self) -> None:
        already_on_two, moved, deleted_later = self._organizations_without_config(3)
        self._store_mode(already_on_two, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        changed_ids_file = self._ids_file()
        ids_file = self._ids_file(already_on_two.id, moved.id, moved.id, deleted_later.id)

        self._run("--mode", "2", "--organization-ids-file", ids_file, "--write-changed-ids", changed_ids_file)
        deleted_later.delete()
        output = self._run(
            "--mode",
            "0",
            "--allow-downgrade",
            "--organization-ids-file",
            changed_ids_file,
            "--skip-unknown-organization-ids",
        )

        self.assertIn(f"Skipping 1 unknown organization id(s) in {changed_ids_file}.", output)
        self.assertEqual(self._stored_mode(moved), FlagEvaluationsMode.EVENTS)
        self.assertEqual(self._stored_mode(already_on_two), FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

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
        Path(changed_ids_file).write_text(str(listed.id))

        self._run("--mode", "1", "--organization-id", str(moved.id), "--write-changed-ids", changed_ids_file)

        self.assertEqual(Path(changed_ids_file).read_text().split(), [str(listed.id), str(moved.id)])

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
