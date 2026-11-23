from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.models import Team

from products.stacks.backend.logic import cleanup, runs
from products.stacks.backend.models import StackDiff
from products.stacks.backend.tests.conftest import PRODUCT_DATABASES, faked_engine

SOURCE = {"repository": "org/web", "branch": "main", "commit": "abc123"}


def resource(kind: str, identity: str, **body: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "key": identity,
        "body": {"name": identity, **body},
        "source": {"file": f".ph/{kind}s.ts", "export": identity},
    }


# The helpers run on an API test case, which only the subclasses below name.
_TestCase: Any = APIBaseTest if TYPE_CHECKING else object


class StackCalls(_TestCase):
    """Requests and worker runs for a stacks test, with the engine faked."""

    def setUp(self) -> None:
        super().setUp()
        # As in production: a missing cached answer is read from the stacks database.
        reads = override_settings(STACKS_WRITE_LOCK_READS_DATABASE=True)
        reads.enable()
        self.addCleanup(reads.disable)
        fakes = faked_engine()
        self.engine, self.dispatcher = fakes.__enter__()
        self.addCleanup(fakes.__exit__, None, None, None)

    def url(self, path: str, team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/stacks/{path}"

    def call(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, team: Team | None = None, **extra: Any
    ):
        with self.captureOnCommitCallbacks(using="stacks_db_writer", execute=True):
            return getattr(self.client, method)(self.url(path, team), body or {}, format="json", **extra)

    def start_diff(self, resources: list[dict], stack: str = "web", *, team: Team | None = None, **extra: Any):
        return self.call(
            "post",
            f"{stack}/diffs/",
            {"description": {"version": 1, "resources": resources}, "source": SOURCE},
            team=team,
            **extra,
        )

    def get_diff(self, diff_id: str, stack: str = "web", **extra: Any) -> dict[str, Any]:
        response = self.client.get(self.url(f"{stack}/diffs/{diff_id}/"), **extra)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def run_diff(self, diff_id: str) -> None:
        runs.compute_diff(StackDiff.all_teams.using("stacks_db_writer").get(id=diff_id).team_id, UUID(diff_id))

    def ready_diff(self, resources: list[dict], stack: str = "web") -> dict[str, Any]:
        response = self.start_diff(resources, stack)
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        self.run_diff(response.json()["id"])
        return self.get_diff(response.json()["id"], stack)

    def push(self, diff_id: str, stack: str = "web", **body: Any):
        return self.call("post", f"{stack}/diffs/{diff_id}/push/", body)

    def run_push(self, diff_id: str) -> None:
        diff = StackDiff.all_teams.using("stacks_db_writer").get(id=diff_id)
        assert diff.push_attempt_id is not None
        runs.run_push(diff.team_id, diff.id, diff.push_attempt_id)

    def pushed(self, resources: list[dict], stack: str = "web") -> dict[str, Any]:
        diff = self.ready_diff(resources, stack)
        response = self.push(diff["id"], stack)
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        self.run_push(diff["id"])
        return self.get_diff(diff["id"], stack)

    def reconcile(self, diff_id: str, stack: str = "web"):
        return self.call("post", f"{stack}/reconcile/", {"diff_id": diff_id})

    def bindings(self, stack: str = "web") -> list[dict[str, Any]]:
        response = self.client.get(self.url(f"{stack}/bindings/"))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["results"]

    def sweep(self) -> dict[str, int]:
        with self.captureOnCommitCallbacks(using="stacks_db_writer", execute=True):
            return cleanup.sweep()


class StackAPITestBase(StackCalls, APIBaseTest):
    databases = PRODUCT_DATABASES
