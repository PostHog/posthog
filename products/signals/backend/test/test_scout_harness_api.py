from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScratchpad
from products.tasks.backend.models import Task, TaskRun


def _make_task_run(team: Team, *, status: str | None = None) -> TaskRun:
    task = Task.objects.create(
        team=team,
        title="scout run",
        description="scout run",
        origin_product=Task.OriginProduct.SIGNALS_SCOUT,
    )
    task_run = TaskRun.objects.create(task=task, team=team)
    if status is not None:
        TaskRun.objects.filter(id=task_run.id).update(status=status)
        task_run.refresh_from_db()
    return task_run


def _make_run(team: Team, *, task_run_status: str = TaskRun.Status.IN_PROGRESS, **overrides) -> SignalScoutRun:
    """Build a SignalScoutRun bridge row whose TaskRun is in the given status."""
    config, _ = SignalScoutConfig.objects.get_or_create(team=team)
    task_run = _make_task_run(team, status=task_run_status)
    defaults: dict = {
        "task_run": task_run,
        "scout_config": config,
        "skill_name": "signals-scout-general",
        "skill_version": 1,
    }
    defaults.update(overrides)
    return SignalScoutRun.objects.create(team=team, **defaults)


class TestScoutHarnessRunsAPI(APIBaseTest):
    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/"

    def _detail_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/"

    def test_list_returns_runs_for_team_newest_first(self) -> None:
        older = _make_run(self.team)
        newer = _make_run(self.team)
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        ids = [row["run_id"] for row in response.json()]
        # newer first (created_at desc).
        assert ids == [str(newer.id), str(older.id)]

    def test_list_does_not_leak_runs_from_another_team(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        _make_run(other)
        own = _make_run(self.team)
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        ids = [row["run_id"] for row in response.json()]
        assert ids == [str(own.id)]

    def test_list_limit_clamped_to_max(self) -> None:
        for _ in range(3):
            _make_run(self.team)
        response = self.client.get(f"{self._list_url()}?limit=2")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

    def test_list_text_filter_matches_summary_ilike(self) -> None:
        keep = _make_run(self.team, summary="emit-free /checkout pass")
        _make_run(self.team, summary="LLM cost scan, all normal")
        response = self.client.get(f"{self._list_url()}?text=checkout")
        assert response.status_code == status.HTTP_200_OK
        ids = [row["run_id"] for row in response.json()]
        assert ids == [str(keep.id)]

    def test_retrieve_returns_bridge_projection(self) -> None:
        run = _make_run(self.team, summary="looked at /checkout, nothing actionable")
        response = self.client.get(self._detail_url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["run_id"] == str(run.id)
        assert body["skill_name"] == "signals-scout-general"
        assert body["task_run_id"] == str(run.task_run_id)
        # Status flows from the linked TaskRun (default fixture sets IN_PROGRESS).
        assert body["status"] == TaskRun.Status.IN_PROGRESS
        assert body["summary"] == "looked at /checkout, nothing actionable"

    def test_retrieve_unknown_id_returns_404(self) -> None:
        response = self.client.get(self._detail_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        response = self.client.get(self._detail_url(str(run.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_malformed_run_id_returns_404(self) -> None:
        # Anything URL-safe that isn't a UUID must 404 cleanly — not 500 from
        # Django's UUIDField conversion blowing up on `.filter(id=...)`.
        for bad in ("not-a-uuid", "abc-def-ghi", "123", "deadbeef"):
            response = self.client.get(self._detail_url(bad))
            assert response.status_code == status.HTTP_404_NOT_FOUND, (
                f"expected 404 for {bad!r}, got {response.status_code}"
            )


class TestScoutHarnessEmitFindingAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The harness preflight mirrors `emit_signal()`'s downstream gates: the org
        # must have AI processing approved and the team must have an enabled
        # SignalSourceConfig for the signals_scout source. Without this setup, the
        # preflight short-circuits before `emit_signal` runs.
        from products.signals.backend.models import SignalSourceConfig

        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        SignalSourceConfig.objects.get_or_create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            defaults={"enabled": True},
        )

    def _findings_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/findings/"

    def _payload(self, **overrides) -> dict:
        body: dict = {
            "description": "Checkout 500s spike correlates with payment-flag rollout",
            "weight": 0.6,
            "confidence": 0.7,
            "evidence": [
                {
                    "source_product": "error_tracking",
                    "summary": "issue id <abc> increased 4x after 14:00",
                    "entity_id": "abc",
                },
            ],
            "finding_id": "f-1",
        }
        body.update(overrides)
        return body

    def test_emit_finding_calls_emit_signal_with_deterministic_source_id(self) -> None:
        run = _make_run(self.team)
        with patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            response = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["emitted"] is True
        assert body["finding_id"] == "f-1"
        assert body["skipped_reason"] is None
        mock_emit.assert_awaited_once()
        # Idempotency is via the deterministic `source_id` keyed on (run, finding).
        assert mock_emit.await_args.kwargs["source_id"] == f"run:{run.id}:finding:f-1"

    def test_emit_finding_rejects_non_in_progress_run(self) -> None:
        run = _make_run(self.team, task_run_status=TaskRun.Status.COMPLETED)
        response = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_emit_finding_validates_weight_range(self) -> None:
        run = _make_run(self.team)
        response = self.client.post(self._findings_url(str(run.id)), data=self._payload(weight=2.0), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_emit_finding_unknown_run_returns_404(self) -> None:
        response = self.client.post(
            self._findings_url("00000000-0000-0000-0000-000000000000"), data=self._payload(), format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_emit_finding_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        response = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_emit_finding_malformed_run_id_returns_404(self) -> None:
        # Same guard as `retrieve`: a URL-safe non-UUID must 404 before any DB
        # call, not 500 from `.filter(id=...)` on a non-UUID string.
        for bad in ("not-a-uuid", "abc-def-ghi", "123", "deadbeef"):
            response = self.client.post(self._findings_url(bad), data=self._payload(), format="json")
            assert response.status_code == status.HTTP_404_NOT_FOUND, (
                f"expected 404 for {bad!r}, got {response.status_code}"
            )


class TestScoutHarnessScratchpadAPI(APIBaseTest):
    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/scratchpad/"

    def _delete_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/scratchpad/delete/"

    def test_remember_creates_entry(self) -> None:
        body = {"key": "k1", "content": "checkout regression noise — already tracked"}
        response = self.client.post(self._list_url(), data=body, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "k1"
        assert data["content"] == "checkout regression noise — already tracked"

    def test_remember_idempotent_upsert_on_team_key(self) -> None:
        first = self.client.post(self._list_url(), data={"key": "k1", "content": "v1"}, format="json")
        second = self.client.post(self._list_url(), data={"key": "k1", "content": "v2"}, format="json")
        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert SignalScratchpad.objects.filter(team=self.team, key="k1").count() == 1
        assert SignalScratchpad.objects.get(team=self.team, key="k1").content == "v2"

    def test_search_returns_team_entries(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="active", content="still relevant")
        SignalScratchpad.objects.create(team=self.team, key="another", content="more memory")
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        keys = {row["key"] for row in response.json()}
        assert keys == {"active", "another"}

    def test_search_text_filter_uses_ilike(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="match", content="The CHECKOUT funnel is broken")
        SignalScratchpad.objects.create(team=self.team, key="miss", content="image loading is slow")
        response = self.client.get(f"{self._list_url()}?text=checkout")
        assert response.status_code == status.HTTP_200_OK
        keys = [row["key"] for row in response.json()]
        assert keys == ["match"]

    def test_search_does_not_leak_other_teams_memory(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        SignalScratchpad.objects.create(team=other, key="theirs", content="leaked?")
        SignalScratchpad.objects.create(team=self.team, key="ours", content="visible")
        response = self.client.get(self._list_url())
        keys = [row["key"] for row in response.json()]
        assert keys == ["ours"]

    def test_forget_removes_entry(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="k1", content="v")
        response = self.client.post(self._delete_url(), data={"key": "k1"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"deleted": True}
        assert not SignalScratchpad.objects.filter(team=self.team, key="k1").exists()

    def test_forget_returns_false_when_key_missing(self) -> None:
        response = self.client.post(self._delete_url(), data={"key": "ghost"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"deleted": False}

    def test_remember_accepts_run_id_belonging_to_same_team(self) -> None:
        run = _make_run(self.team)
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": str(run.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        row = SignalScratchpad.objects.get(team=self.team, key="k1")
        assert str(row.created_by_run_id) == str(run.id)

    def test_remember_rejects_run_id_from_another_team(self) -> None:
        # A run UUID from another team must not create cross-team lineage on this
        # team's memory row — the agent's MCP token is team-scoped, but `run_id`
        # is a free body field and previously had no validation.
        other = Team.objects.create(organization=self.organization, name="Other")
        other_run = _make_run(other)
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": str(other_run.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "run_id"
        assert not SignalScratchpad.objects.filter(team=self.team, key="k1").exists()

    def test_remember_rejects_unknown_run_id(self) -> None:
        # A well-formed UUID that doesn't reference any run row should also bounce —
        # don't let a typo silently produce orphan lineage on the memory table.
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "run_id"

    def test_remember_rejects_malformed_run_id(self) -> None:
        # UUIDField in the serializer rejects non-UUID strings before the view runs.
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": "not-a-uuid"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
