from __future__ import annotations

from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalAgentConfig, SignalAgentRun, SignalMemory, SignalProjectProfile


def _make_run(team, **overrides) -> SignalAgentRun:
    config, _ = SignalAgentConfig.objects.get_or_create(team=team)
    defaults: dict = {
        "agent_config": config,
        "skill_name": "signals-agent-scout",
        "skill_version": 1,
        "status": SignalAgentRun.Status.RUNNING,
        "summary": "investigating checkout 500s",
    }
    defaults.update(overrides)
    return SignalAgentRun.objects.create(team=team, **defaults)


class TestAgentHarnessRunsAPI(APIBaseTest):
    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/agent_harness/runs/"

    def _detail_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/agent_harness/runs/{run_id}/"

    def test_list_returns_runs_for_team_newest_first(self) -> None:
        older = _make_run(self.team, summary="old work")
        SignalAgentRun.objects.filter(id=older.id).update(started_at=timezone.now() - timedelta(hours=2))
        newer = _make_run(self.team, summary="new work")
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        ids = [row["run_id"] for row in response.json()]
        assert ids == [str(newer.id), str(older.id)]

    def test_list_text_filter_uses_ilike(self) -> None:
        match = _make_run(self.team, summary="checkout flow regressing")
        _make_run(self.team, summary="unrelated topic")
        response = self.client.get(f"{self._list_url()}?text=checkout")
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["run_id"] == str(match.id)

    def test_list_does_not_leak_runs_from_another_team(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        _make_run(other, summary="other-team work")
        own = _make_run(self.team, summary="own work")
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

    def test_retrieve_returns_full_payload(self) -> None:
        run = _make_run(
            self.team,
            findings=[{"finding_id": "f1", "emitted": True}],
            tool_call_log=[{"tool": "search_recent_runs"}],
        )
        response = self.client.get(self._detail_url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["run_id"] == str(run.id)
        assert body["findings"] == [{"finding_id": "f1", "emitted": True}]
        assert body["tool_call_log"] == [{"tool": "search_recent_runs"}]

    def test_retrieve_unknown_id_returns_404(self) -> None:
        response = self.client.get(self._detail_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        response = self.client.get(self._detail_url(str(run.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAgentHarnessEmitFindingAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The harness preflight mirrors `emit_signal()`'s downstream gates: the org
        # must have AI processing approved and the team must have an enabled
        # SignalSourceConfig for the signals_agent source. Without this setup, the
        # preflight short-circuits before `emit_signal` runs and the non-shadow
        # tests assert against the wrong state.
        from products.signals.backend.models import SignalSourceConfig

        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        SignalSourceConfig.objects.get_or_create(
            team=self.team,
            source_product="signals_agent",
            source_type="cross_source_issue",
            defaults={"enabled": True},
        )

    def _findings_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/agent_harness/runs/{run_id}/findings/"

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

    def test_emit_finding_in_shadow_mode_persists_without_firing_pipeline(self) -> None:
        run = _make_run(self.team)
        # Default config rows are shadow_mode=True per model default.
        with patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            response = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {"finding_id": "f-1", "emitted": False, "skipped_reason": "shadow_mode"}
        mock_emit.assert_not_called()
        run.refresh_from_db()
        assert len(run.findings) == 1
        assert run.findings[0]["finding_id"] == "f-1"
        assert run.findings[0]["emitted"] is False

    def test_emit_finding_outside_shadow_mode_calls_emit_signal(self) -> None:
        run = _make_run(self.team)
        SignalAgentConfig.objects.filter(team=self.team).update(shadow_mode=False)
        with patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            response = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["emitted"] is True
        assert body["skipped_reason"] is None
        mock_emit.assert_awaited_once()
        run.refresh_from_db()
        assert run.findings[0]["emitted"] is True

    def test_emit_finding_idempotent_on_finding_id(self) -> None:
        run = _make_run(self.team)
        SignalAgentConfig.objects.filter(team=self.team).update(shadow_mode=False)
        with patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            first = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
            second = self.client.post(self._findings_url(str(run.id)), data=self._payload(), format="json")
        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["skipped_reason"] == "already_emitted"
        # Pipeline only ever fires once for the same finding_id.
        mock_emit.assert_awaited_once()

    def test_emit_finding_rejects_non_running_run(self) -> None:
        run = _make_run(self.team, status=SignalAgentRun.Status.COMPLETED)
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


class TestAgentHarnessMemoryAPI(APIBaseTest):
    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/agent_harness/memory/"

    def _forget_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/agent_harness/memory/forget/"

    def test_remember_creates_agent_inference_entry(self) -> None:
        body = {"key": "k1", "content": "checkout regression noise — already tracked", "tags": ["checkout"]}
        response = self.client.post(self._list_url(), data=body, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "k1"
        assert data["authority"] == SignalMemory.Authority.AGENT_INFERENCE
        assert data["tags"] == ["checkout"]
        # Default 7-day TTL applied — exact value not asserted, but expires_at must be set.
        assert data["expires_at"] is not None

    def test_remember_idempotent_upsert_on_team_key(self) -> None:
        first = self.client.post(self._list_url(), data={"key": "k1", "content": "v1"}, format="json")
        second = self.client.post(self._list_url(), data={"key": "k1", "content": "v2"}, format="json")
        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert SignalMemory.objects.filter(team=self.team, key="k1").count() == 1
        assert SignalMemory.objects.get(team=self.team, key="k1").content == "v2"

    def test_remember_rejects_overwrite_of_human_confirmed(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="locked",
            content="human-curated",
            authority=SignalMemory.Authority.HUMAN_CONFIRMED,
        )
        response = self.client.post(
            self._list_url(), data={"key": "locked", "content": "agent override"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_search_returns_unexpired_only_by_default(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="active",
            content="still relevant",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            expires_at=timezone.now() + timedelta(days=1),
        )
        SignalMemory.objects.create(
            team=self.team,
            key="stale",
            content="aged out",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            expires_at=timezone.now() - timedelta(days=1),
        )
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        keys = [row["key"] for row in response.json()]
        assert keys == ["active"]

    def test_search_include_expired_surfaces_them(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="stale",
            content="aged out",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            expires_at=timezone.now() - timedelta(days=1),
        )
        response = self.client.get(f"{self._list_url()}?include_expired=true")
        assert response.status_code == status.HTTP_200_OK
        keys = [row["key"] for row in response.json()]
        assert "stale" in keys

    def test_search_does_not_leak_other_teams_memory(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        SignalMemory.objects.create(team=other, key="theirs", content="leaked?")
        SignalMemory.objects.create(team=self.team, key="ours", content="visible")
        response = self.client.get(self._list_url())
        keys = [row["key"] for row in response.json()]
        assert keys == ["ours"]

    def test_forget_removes_agent_entry(self) -> None:
        SignalMemory.objects.create(team=self.team, key="k1", content="v")
        response = self.client.post(self._forget_url(), data={"key": "k1"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"deleted": True}
        assert not SignalMemory.objects.filter(team=self.team, key="k1").exists()

    def test_forget_returns_false_when_key_missing(self) -> None:
        response = self.client.post(self._forget_url(), data={"key": "ghost"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"deleted": False}

    def test_forget_refuses_human_confirmed(self) -> None:
        SignalMemory.objects.create(
            team=self.team,
            key="locked",
            content="curated",
            authority=SignalMemory.Authority.HUMAN_CONFIRMED,
        )
        response = self.client.post(self._forget_url(), data={"key": "locked"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_remember_accepts_run_id_belonging_to_same_team(self) -> None:
        run = _make_run(self.team)
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": str(run.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        row = SignalMemory.objects.get(team=self.team, key="k1")
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
        assert not SignalMemory.objects.filter(team=self.team, key="k1").exists()

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


class TestAgentHarnessProjectProfileAPI(APIBaseTest):
    """The project profile is the agent's orientation surface — read once at run start.

    There's only one operation (`list` returns the singleton current profile), so the
    surface is small. These tests cover lazy compute on first call, cache-hit reuse,
    and team isolation.
    """

    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/agent_harness/project_profile/"

    def test_lazy_computes_a_profile_when_none_exists(self) -> None:
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 0
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        # Response shape carries the cache metadata + the inventory payload.
        assert "profile_id" in body
        assert "computed_at" in body
        assert "expires_at" in body
        assert "source_version" in body
        assert "inventory" in body["payload"]
        # And a row was persisted as a side effect.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_returns_cached_profile_on_repeat_call(self) -> None:
        first = self.client.get(self._list_url()).json()
        second = self.client.get(self._list_url()).json()
        assert first["profile_id"] == second["profile_id"]
        # No second row written.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_does_not_leak_other_teams_profile(self) -> None:
        # Build a profile for another team in the same org and confirm we don't see it.
        other = Team.objects.create(organization=self.organization, name="Other")
        SignalProjectProfile.objects.create(
            team=other,
            expires_at=timezone.now() + timedelta(hours=24),
            source_version="v1",
            payload={"inventory": {}},
        )
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        # Our team had no profile — the lazy compute path must have built a fresh one
        # on this team, not surfaced the other team's row.
        row = SignalProjectProfile.objects.get(id=body["profile_id"])
        assert row.team_id == self.team.id

    def test_inventory_payload_carries_expected_keys(self) -> None:
        response = self.client.get(self._list_url())
        inventory = response.json()["payload"]["inventory"]
        assert set(inventory.keys()) == {
            "products_in_use",
            "product_intents",
            "integrations",
            "external_data_sources",
            "signal_source_configs",
            "existing_inbox_reports",
        }
