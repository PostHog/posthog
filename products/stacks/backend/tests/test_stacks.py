from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.oauth import OAuthAccessToken
from posthog.product_db_router import ProductDBRouter

from products.stacks.backend.logic import crypto
from products.stacks.backend.models import Stack, StackBinding, StackDiff, StackRecordVersion
from products.stacks.backend.tests.base import StackAPITestBase, resource
from products.stacks.backend.tests.conftest import RECORD_SECRET, SAVED_DIFF_SECRET, WorkerDied, already_started


class TestDiffs(StackAPITestBase):
    @parameterized.expand(
        [
            ("ready", [], "ready"),
            ("failed", [{"code": "reference_missing", "message": "Define the insight this alert reads."}], "failed"),
        ]
    )
    def test_diff_returns_running_then_settles_in_the_background(self, _name: str, errors: list, final: str) -> None:
        self.engine.diff_errors = errors

        response = self.start_diff([resource("insight", "signups")])

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["status"] == "running"
        assert self.dispatcher.diffs == [UUID(response.json()["id"])]
        assert self.get_diff(response.json()["id"])["status"] == "running"

        self.run_diff(response.json()["id"])

        diff = self.get_diff(response.json()["id"])
        assert diff["status"] == final
        assert diff["diff"]["errors"] == errors
        assert diff["diff"]["summary"]["create"] == 1
        assert self.engine.token_scopes == ["insight:read"]
        assert not OAuthAccessToken.objects.filter(token__in=[c.api_key for c in self.engine.credentials]).exists()

    def test_second_stack_claiming_a_natural_key_fails_and_names_the_first(self) -> None:
        self.pushed([resource("flag", "new-checkout", key="new-checkout")])

        diff = self.start_diff([resource("flag", "new-checkout", key="new-checkout")], stack="billing").json()

        assert diff["status"] == "failed"
        assert UUID(diff["id"]) not in self.dispatcher.diffs
        [error] = diff["diff"]["errors"]
        assert error["code"] == "claimed_by_other_stack"
        assert "web" in error["message"] and "org/web" in error["message"]

    def test_a_natural_key_detached_from_one_stack_can_be_pushed_by_another(self) -> None:
        self.pushed([resource("flag", "new-checkout", key="new-checkout")])
        [binding] = self.bindings()
        assert self.call("post", f"web/bindings/{binding['id']}/detach/").status_code == status.HTTP_200_OK

        diff = self.ready_diff([resource("flag", "new-checkout", key="new-checkout")], stack="billing")

        # The refusal tells the other stack to detach first, so the push the detach allows must go through.
        assert self.push(diff["id"], "billing").status_code == status.HTTP_202_ACCEPTED

    def test_two_stacks_adopting_one_entity_cannot_both_push(self) -> None:
        existing = self.engine.remote.add("flag", {"key": "beta", "name": "Beta"})
        first = self.ready_diff([resource("flag", "beta", key="beta")], stack="web")
        second = self.ready_diff([resource("flag", "beta", key="beta")], stack="billing")
        assert first["diff"]["summary"]["adopt"] == second["diff"]["summary"]["adopt"] == 1

        assert self.push(first["id"], "web").status_code == status.HTTP_202_ACCEPTED
        refused = self.push(second["id"], "billing")

        assert refused.status_code == status.HTTP_409_CONFLICT
        assert refused.json()["code"] == "claimed_by_other_stack"
        assert len(self.dispatcher.pushes) == 1
        self.run_push(first["id"])
        assert list(self.engine.remote.of("flag")) == [existing]
        assert StackBinding.all_teams.get(kind="flag").entity_id == existing


class TestLookup(StackAPITestBase):
    def test_a_natural_key_kind_is_found_by_its_id_or_its_name(self) -> None:
        self.pushed([resource("event", "checkout_completed")])
        [binding] = self.bindings()

        by_id = self.client.get(self.url("bindings/"), {"kind": "event", "entity_id": binding["entity_id"]})
        by_name = self.client.get(self.url("bindings/"), {"kind": "event", "entity_id": "checkout_completed"})

        assert by_id.json()["binding"]["id"] == by_name.json()["binding"]["id"] == binding["id"]


class TestPush(StackAPITestBase):
    def test_push_applies_the_saved_diff_once_and_a_second_push_creates_nothing(self) -> None:
        pushed = self.pushed([resource("insight", "signups")])

        assert (pushed["status"], pushed["push_status"]) == ("pushed", "succeeded")
        assert len(self.engine.remote.of("insight")) == 1
        assert self.engine.token_scopes[-1] == "insight:read insight:write"
        [binding] = self.bindings()
        assert (binding["kind"], binding["status"], binding["repository"]) == ("insight", "bound", "org/web")
        assert binding["source"] == {"file": ".ph/insights.ts", "export": "signups"}

        again = self.pushed([resource("insight", "signups")])

        assert again["diff"]["summary"]["create"] == 0
        assert len(self.engine.remote.of("insight")) == 1

    def test_push_refuses_a_diff_made_before_the_stack_moved(self) -> None:
        first = self.ready_diff([resource("insight", "signups")])
        second = self.ready_diff([resource("insight", "signups"), resource("insight", "churn")])
        self.push(first["id"])
        self.run_push(first["id"])

        response = self.push(second["id"])

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "stack_moved"
        assert self.get_diff(second["id"])["status"] == "stale"
        assert len(self.engine.remote.of("insight")) == 1

    def test_a_takeover_revokes_the_old_workers_token_and_the_next_push_waits_for_a_diff(self) -> None:
        diff = self.ready_diff([resource("insight", "a"), resource("insight", "b")])
        self.push(diff["id"])

        def take_over_after_first_change(index: int) -> None:
            if index == 1:
                Stack.all_teams.update(lease_expires_at=timezone.now() - timedelta(seconds=1))
                self.sweep()

        self.engine.on_each_record = take_over_after_first_change
        self.run_push(diff["id"])
        self.engine.on_each_record = None

        assert len(self.engine.remote.of("insight")) == 1
        assert self.get_diff(diff["id"])["push_status"] == "uncertain"
        assert [b["key"] for b in self.bindings()] == ["a"]
        reconciled = self.ready_diff([resource("insight", "a"), resource("insight", "b")])
        assert reconciled["diff"]["summary"]["create"] == 1
        assert self.push(reconciled["id"]).json()["code"] == "push_uncertain"
        assert self.reconcile(reconciled["id"]).status_code == status.HTTP_200_OK
        assert self.push(reconciled["id"]).status_code == status.HTTP_202_ACCEPTED
        self.run_push(reconciled["id"])
        assert len(self.engine.remote.of("insight")) == 2

    def test_a_worker_that_lost_its_lease_stops_at_its_next_saved_record(self) -> None:
        diff = self.ready_diff([resource("insight", "a"), resource("insight", "b"), resource("insight", "c")])
        self.push(diff["id"])

        def lose_lease_after_first_change(index: int) -> None:
            if index == 1:
                Stack.all_teams.update(lease_generation=99)

        self.engine.on_each_record = lose_lease_after_first_change
        self.run_push(diff["id"])

        # AbortRun from the second saved record stopped the engine before the third change.
        assert len(self.engine.remote.of("insight")) == 2
        assert StackRecordVersion.all_teams.get().serial == 1

    def test_an_uncertain_push_blocks_pushes_of_older_diffs(self) -> None:
        older = self.ready_diff([resource("insight", "a")])
        diff = self.ready_diff([resource("insight", "a")])
        self.push(diff["id"])
        Stack.all_teams.update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.sweep()

        response = self.push(older["id"])

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "push_uncertain"

    def test_a_worker_that_dies_after_a_change_loses_nothing(self) -> None:
        diff = self.ready_diff([resource("insight", "a"), resource("insight", "b")])
        self.push(diff["id"])
        self.engine.die_after = 1

        with pytest.raises(WorkerDied):
            self.run_push(diff["id"])
        Stack.all_teams.update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.sweep()

        assert [b["key"] for b in self.bindings()] == ["a"]
        self.engine.die_after = None
        retry = self.ready_diff([resource("insight", "a"), resource("insight", "b")])
        assert retry["diff"]["summary"]["create"] == 1
        assert retry["diff"]["warnings"] == []
        assert self.reconcile(retry["id"]).status_code == status.HTTP_200_OK
        self.push(retry["id"])
        self.run_push(retry["id"])
        assert len(self.engine.remote.of("insight")) == 2

    @parameterized.expand([("the_worker_died",), ("the_engine_was_killed",)])
    def test_a_create_the_worker_never_recorded_is_reconciled_before_the_next_push(self, how: str) -> None:
        diff = self.ready_diff([resource("insight", "a"), resource("insight", "b")])
        self.push(diff["id"])
        # The create of `a` reached PostHog, and the run stopped before its id was stored.
        if how == "the_worker_died":
            self.engine.die_before_record = 1
            with pytest.raises(WorkerDied):
                self.run_push(diff["id"])
            self.engine.die_before_record = None
            Stack.all_teams.update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            self.sweep()
        else:
            self.engine.interrupt_before_record = 1
            self.run_push(diff["id"])
            self.engine.interrupt_before_record = None
        assert self.get_diff(diff["id"])["push_status"] == "uncertain"
        [made] = self.engine.remote.of("insight")

        retry = self.ready_diff([resource("insight", "a"), resource("insight", "b")])

        # A ready diff alone never clears the uncertain push.
        assert self.push(retry["id"]).json()["code"] == "push_uncertain"
        assert retry["diff"]["warnings"] == [
            {
                "code": "possible_unrecorded_create",
                "kind": "insight",
                "key": "a",
                "message": retry["diff"]["warnings"][0]["message"],
                "entities": [{"entity_id": made, "name": "a"}],
            }
        ]
        adopted = self.call("post", "web/adopt/", {"resources": [{"kind": "insight", "key": "a", "entity_id": made}]})
        assert adopted.status_code == status.HTTP_200_OK, adopted.json()
        assert self.reconcile(retry["id"]).json()["code"] == "stack_moved"
        final = self.ready_diff([resource("insight", "a"), resource("insight", "b")])
        assert final["diff"]["warnings"] == []
        reconciled = self.reconcile(final["id"])
        assert reconciled.json() == {"stack_name": "web", "diff_id": final["id"], "acknowledged_warnings": 0}
        assert self.push(final["id"]).status_code == status.HTTP_202_ACCEPTED
        self.run_push(final["id"])
        assert len(self.engine.remote.of("insight")) == 2
        assert self.reconcile(final["id"]).json()["code"] == "nothing_to_reconcile"

    def test_a_failed_token_cleanup_still_records_the_push(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        self.push(diff["id"])

        tokens = patch("products.stacks.backend.logic.credentials.OAuthAccessToken")
        with tokens as token_model:
            token_model.objects.filter.return_value.delete.side_effect = RuntimeError("main database went away")
            self.run_push(diff["id"])

        assert self.get_diff(diff["id"])["status"] == "pushed"
        assert [b["status"] for b in self.bindings()] == ["bound"]

    def test_a_partial_failure_keeps_the_adopted_origin(self) -> None:
        existing = self.engine.remote.add("action", {"name": "Signup"})
        assert (
            self.call(
                "post", "web/adopt/", {"resources": [{"kind": "action", "key": "signup", "entity_id": existing}]}
            ).status_code
            == 200
        )
        diff = self.ready_diff([resource("action", "signup"), resource("insight", "a")])
        self.push(diff["id"])
        self.engine.fail_after = 1

        self.run_push(diff["id"])

        assert StackBinding.all_teams.get(kind="action").origin == "adopted"
        self.engine.fail_after = None
        removal = self.pushed([resource("insight", "a")])
        assert removal["diff"]["summary"]["release"] == 1
        assert (("action", existing)) in self.engine.remote.entities

    def test_a_record_that_is_missing_never_reads_as_an_empty_stack(self) -> None:
        self.pushed([resource("insight", "signups")])
        StackRecordVersion.all_teams.all().delete()

        diff = self.start_diff([resource("insight", "signups")]).json()
        self.run_diff(diff["id"])

        assert self.get_diff(diff["id"])["diff"]["errors"][0]["code"] == "record_missing"

    def test_a_duplicate_start_leaves_the_running_push_alone(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        self.dispatcher.push_error = already_started()

        assert self.push(diff["id"]).status_code == status.HTTP_202_ACCEPTED

        stack = Stack.all_teams.get()
        assert stack.lease_attempt_id == StackDiff.all_teams.get(id=diff["id"]).push_attempt_id
        assert self.get_diff(diff["id"])["push_status"] == "running"

    def test_an_ambiguous_dispatch_failure_releases_the_lease_as_uncertain(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        # Temporal may have started the workflow before the error came back.
        self.dispatcher.push_error = RuntimeError("deadline exceeded")

        self.push(diff["id"])

        assert Stack.all_teams.get().lease_attempt_id is None
        assert self.get_diff(diff["id"])["push_status"] == "uncertain"
        assert Stack.all_teams.get().needs_reconcile

    @parameterized.expand(
        [
            ("removals", 6, 0, {}, status.HTTP_400_BAD_REQUEST),
            ("recreates", 0, 6, {}, status.HTTP_400_BAD_REQUEST),
            ("both_under_their_own_cap", 3, 3, {}, status.HTTP_400_BAD_REQUEST),
            ("confirmed", 3, 3, {"max_removals": 6}, status.HTTP_202_ACCEPTED),
        ]
    )
    def test_push_over_the_removal_cap_needs_confirmation(
        self, _name: str, removals: int, recreates: int, body: dict, expected: int
    ) -> None:
        self.engine.extra_removals = removals
        self.engine.extra_recreates = recreates
        diff = self.ready_diff([resource("insight", "signups")])

        response = self.push(diff["id"], **body)

        assert response.status_code == expected
        if expected == status.HTTP_400_BAD_REQUEST:
            assert response.json()["code"] == "too_many_removals"

    def test_record_and_saved_diff_are_encrypted_and_never_returned(self) -> None:
        diff = self.pushed([resource("insight", "signups")])
        second = self.ready_diff([resource("insight", "signups")])

        responses = [
            self.client.get(self.url(f"web/diffs/{diff['id']}/")),
            self.client.get(self.url(f"web/diffs/{second['id']}/")),
            self.client.get(self.url("web/bindings/")),
            self.client.get(self.url("bindings/"), {"kind": "insight", "entity_id": self.bindings()[0]["entity_id"]}),
            self.push(second["id"]),
        ]

        for response in responses:
            assert RECORD_SECRET not in response.content.decode()
            assert SAVED_DIFF_SECRET not in response.content.decode()
        version = StackRecordVersion.all_teams.get()
        with self.settings(STACKS_ENCRYPTION_KEYS=["bm90LXRoZS1zdGFja3Mta2V5LWZvci10aGlzLXRlc3Q="]):
            with pytest.raises(Exception):
                crypto.decrypt(version.encrypted_record)
        assert RECORD_SECRET.encode() in crypto.decrypt(version.encrypted_record)

    def test_sensitive_values_are_stored_redacted_whatever_the_engine_returns(self) -> None:
        self.engine.leaked_sensitive = True

        diff = self.ready_diff([resource("insight", "signups")])

        [field] = [field for field in diff["diff"]["changes"][0]["fields"] if field["sensitive"]]
        assert (field["before"], field["after"]) == (None, None)
        assert "new-value" not in str(StackDiff.all_teams.get(id=diff["id"]).diff)


class TestBindings(StackAPITestBase):
    def test_adopt_records_a_pending_binding_that_a_push_binds(self) -> None:
        existing = self.engine.remote.add("action", {"name": "Signup"})

        response = self.call(
            "post", "web/adopt/", {"resources": [{"kind": "action", "key": "signup", "entity_id": f"0{existing}"}]}
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [(b["entity_id"], b["status"]) for b in response.json()["bindings"]] == [(existing, "pending")]
        diff = self.pushed([resource("action", "signup")])
        assert diff["diff"]["summary"]["adopt"] == 1
        assert [(b["entity_id"], b["status"]) for b in self.bindings()] == [(existing, "bound")]
        assert len(self.engine.remote.of("action")) == 1

    def test_adopt_refuses_an_entity_that_does_not_exist(self) -> None:
        response = self.call(
            "post", "web/adopt/", {"resources": [{"kind": "action", "key": "signup", "entity_id": "999"}]}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == "entity_not_found"
        assert not StackBinding.all_teams.exists()

    def test_detach_releases_the_entity_and_later_pushes_leave_it_in_posthog(self) -> None:
        self.pushed([resource("insight", "signups")])
        [binding] = self.bindings()
        lookup = {"kind": "insight", "entity_id": binding["entity_id"]}
        found = self.client.get(self.url("bindings/"), lookup).json()["binding"]
        assert (found["id"], found["owned_fields"]) == (binding["id"], ["name"])

        response = self.call("post", f"web/bindings/{binding['id']}/detach/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "detached"
        assert self.client.get(self.url("bindings/"), lookup).json()["binding"] is None
        for _ in range(2):
            self.pushed([resource("insight", "signups")])
            assert self.bindings() == []
        assert len(self.engine.remote.of("insight")) == 1

    def test_a_diff_computing_during_a_detach_never_becomes_pushable(self) -> None:
        self.pushed([resource("insight", "signups")])
        [binding] = self.bindings()
        running = self.start_diff([]).json()
        self.engine.during_diff = lambda: self.call("post", f"web/bindings/{binding['id']}/detach/")

        self.run_diff(running["id"])
        self.engine.during_diff = None

        assert self.get_diff(running["id"])["status"] == "stale"
        assert self.push(running["id"]).json()["code"] == "stack_moved"
        assert len(self.engine.remote.of("insight")) == 1


class TestWriterOnly(StackAPITestBase):
    def test_no_stacks_read_goes_to_the_replica(self) -> None:
        original = ProductDBRouter.db_for_read

        def refuse_replica_for_stacks(router, model, **hints):  # noqa: ANN001, ANN202
            instance = hints.get("instance")
            on_writer = instance is not None and instance._state.db == "stacks_db_writer"
            if model._meta.app_label == "stacks" and not on_writer:
                raise AssertionError(f"read of {model.__name__} without the writer")
            return original(router, model, **hints)

        with patch.object(ProductDBRouter, "db_for_read", refuse_replica_for_stacks):
            existing = self.engine.remote.add("action", {"name": "Signup"})
            self.call("post", "web/adopt/", {"resources": [{"kind": "action", "key": "signup", "entity_id": existing}]})
            self.pushed([resource("action", "signup"), resource("insight", "a")])
            [binding] = [b for b in self.bindings() if b["kind"] == "insight"]
            self.call("post", f"web/bindings/{binding['id']}/detach/")
            self.sweep()

        assert Stack.all_teams.using("stacks_db_writer").get().revision == 2
