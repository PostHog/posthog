from __future__ import annotations

from datetime import timedelta

import pytest
from unittest.mock import patch

from django.db import OperationalError, connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.util import delete_bulky_postgres_data

from products.stacks.backend import engine_adapter
from products.stacks.backend.engine_adapter import EngineCredentials, EngineFailure
from products.stacks.backend.logic import cleanup, crypto
from products.stacks.backend.models import Stack, StackDiff, StackRecordVersion
from products.stacks.backend.tests.base import StackAPITestBase, resource
from products.stacks.backend.tests.conftest import PRODUCT_DATABASES


def _nested(depth: int) -> list:
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


class TestAdmission(StackAPITestBase):
    def test_a_literal_credential_is_refused_and_nothing_is_stored(self) -> None:
        response = self.start_diff([resource("source", "billing", password="hunter2")])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "secret_literal"
        assert response.json()["detail"] == "source billing password: Name the password with secret()."
        assert not StackDiff.all_teams.exists()

    def test_the_order_a_definition_needs_reaches_the_engine(self) -> None:
        ordered = {**resource("insight", "by_plan"), "depends_on": [{"kind": "insight", "key": "mrr"}]}

        started = self.start_diff([resource("insight", "mrr"), ordered])
        assert started.status_code == status.HTTP_202_ACCEPTED, started.json()
        self.run_diff(started.json()["id"])

        by_key = {r["key"]: r for r in self.engine.inputs[-1].description["resources"]}
        assert by_key["by_plan"]["depends_on"] == [{"kind": "insight", "key": "mrr"}]
        assert "depends_on" not in by_key["mrr"]

    def test_the_description_is_stored_encrypted(self) -> None:
        diff = self.start_diff([resource("insight", "signups", description="a-recognizable-description")]).json()

        row = StackDiff.all_teams.get(id=diff["id"])
        with self.settings(STACKS_ENCRYPTION_KEYS=["bm90LXRoZS1zdGFja3Mta2V5LWZvci10aGlzLXRlc3Q="]):
            with pytest.raises(Exception):
                crypto.decrypt(row.encrypted_description)
        assert b"a-recognizable-description" in crypto.decrypt(row.encrypted_description)

    @parameterized.expand(
        [
            ("duplicate", [resource("insight", "a"), resource("insight", "a")], "duplicate_definition"),
            ("bad_key", [resource("insight", "Not A Key")], "invalid_key"),
            ("too_deep", [resource("insight", "a", deep=_nested(40))], "definition_too_deep"),
        ]
    )
    def test_limits_are_checked_before_anything_runs(self, _name: str, resources: list, code: str) -> None:
        response = self.start_diff(resources)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == code
        assert not StackDiff.all_teams.exists()

    def test_polling_a_diff_reads_none_of_its_encrypted_bytes(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])

        with CaptureQueriesContext(connections["stacks_db_writer"]) as queries:
            self.get_diff(diff["id"])

        assert queries.captured_queries
        assert not any("encrypted_" in query["sql"] for query in queries.captured_queries)

    @parameterized.expand(
        [
            ("no_keys", {"STACKS_ENCRYPTION_KEYS": []}),
            ("invalid_key", {"STACKS_ENCRYPTION_KEYS": ["not-a-fernet-key"]}),
            ("no_database", None),
        ]
    )
    def test_every_route_is_refused_before_a_stacks_query_when_stacks_are_not_set_up(
        self, _name: str, overrides: dict | None
    ) -> None:
        def requests() -> list:
            with CaptureQueriesContext(connections["stacks_db_writer"]) as queries:
                responses = [
                    self.start_diff([resource("insight", "signups")]),
                    self.client.get(self.url("web/bindings/")),
                    self.client.get(self.url("managed_kinds/")),
                ]
            assert queries.captured_queries == []
            return responses

        if overrides is None:
            with patch("products.stacks.backend.logic.stacks.database_ready", return_value=False):
                responses = requests()
        else:
            with self.settings(**overrides):
                responses = requests()

        assert [response.status_code for response in responses] == [status.HTTP_503_SERVICE_UNAVAILABLE] * 3
        assert {response.json()["code"] for response in responses} == {"stacks_unavailable"}


class TestCleanup(StackAPITestBase):
    databases = PRODUCT_DATABASES | {"ui_customization_db_writer", "ui_customization_db_reader"}

    def test_a_diff_past_its_deadline_is_closed(self) -> None:
        diff = self.start_diff([resource("insight", "signups")]).json()
        StackDiff.all_teams.update(deadline_at=timezone.now() - timedelta(seconds=1))

        self.sweep()

        assert self.get_diff(diff["id"])["diff"]["errors"][0]["code"] == "run_timed_out"

    def test_expired_saved_diffs_lose_their_bytes(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        StackDiff.all_teams.update(expires_at=timezone.now() - timedelta(seconds=1))

        self.sweep()

        assert StackDiff.all_teams.get(id=diff["id"]).encrypted_saved_diff is None

    def test_rotation_never_restores_bytes_a_push_cleared(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        rotate = crypto.rotate

        def cleared_meanwhile(token: bytes) -> bytes:
            StackDiff.all_teams.filter(id=diff["id"]).update(encrypted_saved_diff=None)
            return rotate(token)

        with patch("products.stacks.backend.logic.crypto.rotate", side_effect=cleared_meanwhile):
            crypto.reencrypt_all()

        assert StackDiff.all_teams.get(id=diff["id"]).encrypted_saved_diff is None

    def test_one_failing_cleanup_unit_never_starves_the_others(self) -> None:
        diff = self.start_diff([resource("insight", "signups")]).json()
        StackDiff.all_teams.update(deadline_at=timezone.now() - timedelta(seconds=1))

        with patch("products.stacks.backend.logic.lease.recover_expired_leases", side_effect=RuntimeError("stuck")):
            results = self.sweep()

        assert results["leases_recovered"] == -1
        assert results["diffs_timed_out"] == 1
        assert self.get_diff(diff["id"])["diff"]["errors"][0]["code"] == "run_timed_out"

    def test_a_project_deleted_while_the_stacks_database_is_down_is_cleaned_up_later(self) -> None:
        self.pushed([resource("insight", "signups")])
        with patch("products.stacks.backend.logic.cleanup.StackDiff.all_teams") as diffs:
            diffs.using.side_effect = OperationalError("stacks database unavailable")
            cleanup.delete_team_data([self.team.id])
        assert Stack.all_teams.exists()

        with patch("products.stacks.backend.logic.cleanup.Team.objects") as teams:
            teams.filter.return_value.values_list.return_value = []
            results = self.sweep()

        assert results["orphans_deleted"] == 1
        assert not Stack.all_teams.exists()

    def test_deleting_a_project_deletes_its_stack_data(self) -> None:
        self.pushed([resource("insight", "signups")])

        with self.captureOnCommitCallbacks(using="stacks_db_writer", execute=True):
            delete_bulky_postgres_data([self.team.id])
            delete_bulky_postgres_data([self.team.id])

        assert not Stack.all_teams.exists()
        assert not StackRecordVersion.all_teams.exists()
        assert not StackDiff.all_teams.exists()


class TestAdapter:
    def test_a_push_without_checkpoints_is_refused(self) -> None:
        def run_push_without_on_record(workdir, engine_input, saved, record, credentials):  # noqa: ANN001, ANN202
            raise AssertionError("must not run")

        credentials = EngineCredentials(host="http://localhost", project_id=1, api_key="x")
        with patch("products.stacks.backend.engine.run_push", run_push_without_on_record):
            with pytest.raises(EngineFailure) as refused:
                engine_adapter.push(object(), b"saved", None, credentials, lambda record: None)

        assert refused.value.errors[0]["code"] == "runner_unavailable"
