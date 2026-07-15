from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    PosthogMcpScopes,
    create_oauth_access_token_for_user,
)

from products.signals.backend.models import (
    SignalProjectProfile,
    SignalReport,
    SignalScoutConfig,
    SignalScoutEmission,
    SignalScoutRun,
    SignalScratchpad,
)
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY, discover_canonical_skills
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.team_limits import MAX_RUNS_PER_TEAM_PER_TICK
from products.signals.backend.scout_harness.tools.profile import compute_project_profile
from products.signals.backend.temporal.signal_queries import fetch_report_ids_for_source_ids
from products.skills.backend.models.skills import LLMSkill

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


def _authenticate_as_scout(test: APIBaseTest, *, scopes: PosthogMcpScopes = "signals_scout") -> None:
    """Auth the test client with a scout-internal token, mirroring how the harness sandbox
    reaches these endpoints in production. The emit / scratchpad write actions require
    `signal_scout_internal:write`, which is server-mint-only and rejects session auth, so the
    default `APIBaseTest` force-login isn't enough for the write surface — only reads pass on
    a session. `logout()` first so the token is the sole credential on every request.

    `scopes` selects the posture: the default `signals_scout` covers emit-signal / scratchpad;
    pass `signals_scout_reports` (the report-channel posture, which adds `signal_scout_report:write`)
    to exercise the emit-report / edit-report surface.
    """
    # `create_oauth_access_token_for_user` resolves the Array app by `get_instance_region()`,
    # which isn't deterministic across test contexts — create the app for every region client
    # id so the lookup always resolves.
    for client_id in (ARRAY_APP_CLIENT_ID_DEV, ARRAY_APP_CLIENT_ID_US, ARRAY_APP_CLIENT_ID_EU):
        OAuthApplication.objects.get_or_create(
            client_id=client_id,
            defaults={
                "name": "Array Test App",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://app.posthog.com/callback",
                # RS256 is enforced by the `enforce_rs256_algorithm` DB constraint.
                "algorithm": "RS256",
            },
        )
    token = create_oauth_access_token_for_user(test.user, test.team.id, scopes=scopes, include_internal_scopes=True)
    test.client.logout()
    test.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


def _make_task_run(team: Team, *, status: str | None = None) -> TaskRun:
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
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


def _make_run(team: Team, *, task_run_status: str | None = None, **overrides) -> SignalScoutRun:
    """Build a SignalScoutRun bridge row whose TaskRun is in the given status."""
    TaskRun = apps.get_model("tasks", "TaskRun")
    if task_run_status is None:
        task_run_status = TaskRun.Status.IN_PROGRESS
    config, _ = SignalScoutConfig.objects.get_or_create(
        team=team, skill_name="signals-scout-general", defaults={"emit": True}
    )
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

    def test_list_surfaces_emit_tally(self) -> None:
        _make_run(
            self.team,
            emitted_count=2,
            emitted_finding_ids=["f-a", "f-b"],
            emitted_report_ids=["r-1"],
            edited_report_ids=["r-2"],
        )
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = response.json()[0]
        assert row["emitted_count"] == 2
        assert row["emitted_finding_ids"] == ["f-a", "f-b"]
        # Both report-id channels must surface through the serializer. Guards a real gap: these are
        # carried on the run DTO but were not declared on the serializer, so they were silently dropped
        # from the API/MCP response.
        assert row["emitted_report_ids"] == ["r-1"]
        assert row["edited_report_ids"] == ["r-2"]

    @parameterized.expand([("emitted_true", "true"), ("emitted_false", "false")])
    def test_list_emitted_filter_keeps_only_the_matching_runs(self, _name: str, emitted_param: str) -> None:
        emitting = _make_run(self.team, emitted_count=1, emitted_finding_ids=["f-x"])
        quiet = _make_run(self.team)  # emitted_count defaults to 0
        response = self.client.get(f"{self._list_url()}?emitted={emitted_param}")
        assert response.status_code == status.HTTP_200_OK
        ids = [row["run_id"] for row in response.json()]
        expected = emitting if emitted_param == "true" else quiet
        assert ids == [str(expected.id)]

    def test_list_skill_name_filter_scopes_to_one_scout(self) -> None:
        errors = _make_run(self.team, skill_name="signals-scout-errors")
        _make_run(self.team, skill_name="signals-scout-llm")
        response = self.client.get(f"{self._list_url()}?skill_name=signals-scout-errors")
        assert response.status_code == status.HTTP_200_OK
        ids = [row["run_id"] for row in response.json()]
        assert ids == [str(errors.id)]

    def test_list_surfaces_error_and_failure_reason_for_failed_run(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = _make_run(self.team, task_run_status=TaskRun.Status.FAILED)
        TaskRun.objects.filter(id=run.task_run_id).update(error_message="boom: sandbox died\nstack line 2")
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = response.json()[0]
        assert row["error"] == "boom: sandbox died\nstack line 2"
        assert row["failure_reason"] == "boom: sandbox died"

    def test_retrieve_returns_bridge_projection(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
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
        # Emit tally defaults surface even on a run that emitted nothing.
        assert body["emitted_count"] == 0
        assert body["emitted_finding_ids"] == []

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


def _make_emission(team: Team, run: SignalScoutRun, *, finding_id: str, **overrides) -> SignalScoutEmission:
    defaults: dict = {
        "description": "Checkout 500s post-deploy",
        "weight": 0.7,
        "confidence": 0.85,
        "severity": "P1",
        "source_id": f"run:{run.id}:finding:{finding_id}",
    }
    defaults.update(overrides)
    return SignalScoutEmission.objects.create(team=team, scout_run=run, finding_id=finding_id, **defaults)


class TestScoutHarnessRunEmissionsAPI(APIBaseTest):
    def _emissions_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emissions/"

    def test_returns_emissions_for_run_newest_first(self) -> None:
        run = _make_run(self.team, emitted_count=2, emitted_finding_ids=["f-a", "f-b"])
        _make_emission(self.team, run, finding_id="f-a")
        newer = _make_emission(self.team, run, finding_id="f-b", tags=["cost-spike"])
        response = self.client.get(self._emissions_url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [row["finding_id"] for row in body] == ["f-b", "f-a"]
        first = body[0]
        assert first["run_id"] == str(run.id)
        assert first["description"] == "Checkout 500s post-deploy"
        assert first["weight"] == 0.7
        assert first["confidence"] == 0.85
        assert first["severity"] == "P1"
        assert first["tags"] == ["cost-spike"]
        assert first["source_id"] == f"run:{run.id}:finding:{newer.finding_id}"
        # Untagged emissions surface an empty list, not null.
        assert body[1]["tags"] == []

    def test_emissions_scoped_to_the_requested_run(self) -> None:
        run_a = _make_run(self.team)
        run_b = _make_run(self.team)
        _make_emission(self.team, run_a, finding_id="f-a")
        _make_emission(self.team, run_b, finding_id="f-b")
        response = self.client.get(self._emissions_url(str(run_a.id)))
        assert response.status_code == status.HTTP_200_OK
        assert [row["finding_id"] for row in response.json()] == ["f-a"]

    def test_emissions_empty_for_run_that_emitted_nothing(self) -> None:
        run = _make_run(self.team)
        response = self.client.get(self._emissions_url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_emissions_unknown_run_returns_404(self) -> None:
        response = self.client.get(self._emissions_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_emissions_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        _make_emission(other, run, finding_id="f-a")
        response = self.client.get(self._emissions_url(str(run.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND


# Patch target: the helper is hot-imported into the view module, so patch it there, not at source.
_FETCH_REPORT_IDS = "products.signals.backend.temporal.signal_queries.fetch_report_ids_for_source_ids"


class TestScoutHarnessEmissionReportsAPI(APIBaseTest):
    def _url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emissions/reports/"

    def test_pairs_each_finding_with_its_linked_report(self) -> None:
        run = _make_run(self.team, emitted_finding_ids=["f-a", "f-b"])
        linked = _make_emission(self.team, run, finding_id="f-a")
        _make_emission(self.team, run, finding_id="f-b")  # unmatched — no report
        report = SignalReport.objects.create(team=self.team, title="Checkout 500s", status=SignalReport.Status.READY)
        with patch(_FETCH_REPORT_IDS, return_value={linked.source_id: str(report.id)}) as mock_fetch:
            response = self.client.get(self._url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        # The helper is called once for the whole run with every finding's source_id.
        assert sorted(mock_fetch.call_args.args[1]) == sorted(
            [f"run:{run.id}:finding:f-a", f"run:{run.id}:finding:f-b"]
        )
        body = {row["finding_id"]: row for row in response.json()}
        assert body["f-a"]["report"] == {
            "id": str(report.id),
            "title": "Checkout 500s",
            "status": "ready",
        }
        assert body["f-a"]["source_id"] == linked.source_id
        # A finding whose signal never grouped into a report links to null, not an error.
        assert body["f-b"]["report"] is None

    def test_deleted_report_is_treated_as_no_link(self) -> None:
        # ClickHouse soft-delete and Postgres status can drift, so the reverse lookup can resolve a
        # report id that's since been deleted — surface that as "no link", not a dangling chip.
        run = _make_run(self.team)
        emission = _make_emission(self.team, run, finding_id="f-a")
        deleted = SignalReport.objects.create(team=self.team, status=SignalReport.Status.DELETED)
        with patch(_FETCH_REPORT_IDS, return_value={emission.source_id: str(deleted.id)}):
            response = self.client.get(self._url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["report"] is None

    def test_suppressed_report_is_treated_as_no_link(self) -> None:
        # The inbox hides suppressed reports from its default flow, so a chip to one would deep-link
        # to a page that can't load it — surface suppressed reports as "no link" here too.
        run = _make_run(self.team)
        emission = _make_emission(self.team, run, finding_id="f-a")
        suppressed = SignalReport.objects.create(team=self.team, status=SignalReport.Status.SUPPRESSED)
        with patch(_FETCH_REPORT_IDS, return_value={emission.source_id: str(suppressed.id)}):
            response = self.client.get(self._url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["report"] is None

    def test_clickhouse_failure_degrades_to_null_links(self) -> None:
        # A transient CH/HogQL failure shouldn't 500 the whole page — each finding still
        # comes back, just with `report: null` instead of a resolved link.
        run = _make_run(self.team, emitted_finding_ids=["f-a"])
        _make_emission(self.team, run, finding_id="f-a")
        with patch(_FETCH_REPORT_IDS, side_effect=Exception("ClickHouse timeout")):
            response = self.client.get(self._url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["report"] is None

    def test_report_lookup_query_compiles_without_alias_collision(self) -> None:
        # Regression: the lookup pushes the `source_id` filter into the shared dedup subquery,
        # which exposes `metadata` as an `argMax(...)` alias. HogQL resolved the `metadata`
        # reference in that pushed-down WHERE to the aggregate alias and rejected the whole
        # query ("aggregate function ... found in WHERE"), so `fetch_report_ids_for_source_ids`
        # raised on every call. The view swallowed it, degrading *every* finding to
        # `report: null` — the chip never rendered for anyone. The other tests in this class
        # mock the helper, so they never exercised the query and the break shipped silently.
        # Run the real query (no mock) against an empty ClickHouse: it must compile and return
        # an empty map rather than raise.
        result = fetch_report_ids_for_source_ids(self.team, ["run:00000000-0000-0000-0000-000000000000:finding:f-a"])
        assert result == {}

    def test_empty_run_returns_empty_and_skips_clickhouse(self) -> None:
        run = _make_run(self.team)
        with patch(_FETCH_REPORT_IDS) as mock_fetch:
            response = self.client.get(self._url(str(run.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        mock_fetch.assert_not_called()

    def test_unknown_run_returns_404(self) -> None:
        response = self.client.get(self._url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        _make_emission(other, run, finding_id="f-a")
        response = self.client.get(self._url(str(run.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestScoutHarnessEmissionsBatchAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/emissions/batch/"

    def test_batches_emissions_across_runs_newest_first(self) -> None:
        # The findings page opens one batched request instead of one per run; the response flattens
        # every run's findings newest-first, each row tagged with its own run_id so the UI can regroup.
        run_a = _make_run(self.team)
        run_b = _make_run(self.team)
        _make_emission(self.team, run_a, finding_id="a-old")
        _make_emission(self.team, run_b, finding_id="b-mid")
        _make_emission(self.team, run_a, finding_id="a-new")
        response = self.client.post(self._url(), data={"run_ids": [str(run_a.id), str(run_b.id)]}, format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [row["finding_id"] for row in body] == ["a-new", "b-mid", "a-old"]
        run_by_finding = {row["finding_id"]: row["run_id"] for row in body}
        assert run_by_finding["a-new"] == str(run_a.id)
        assert run_by_finding["b-mid"] == str(run_b.id)

    def test_foreign_team_run_ids_contribute_no_rows(self) -> None:
        # A stale or cross-team run id must not 404 the whole batch (one bad id would blank the page) —
        # team scoping just drops its rows.
        run = _make_run(self.team)
        _make_emission(self.team, run, finding_id="mine")
        other = Team.objects.create(organization=self.organization, name="Other")
        other_run = _make_run(other)
        _make_emission(other, other_run, finding_id="theirs")
        response = self.client.post(self._url(), data={"run_ids": [str(run.id), str(other_run.id)]}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert [row["finding_id"] for row in response.json()] == ["mine"]

    def test_empty_run_ids_rejected(self) -> None:
        response = self.client.post(self._url(), data={"run_ids": []}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestScoutHarnessEmissionReportsBatchAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/emissions/reports/batch/"

    def test_resolves_every_runs_links_in_one_clickhouse_call(self) -> None:
        # The whole point of the batch endpoint: the per-run page fired one ClickHouse query per run,
        # which made Findings slow to open. The batched form resolves every run's findings in a single
        # `fetch_report_ids_for_source_ids` round-trip — assert it's called exactly once with the source
        # ids from both runs, and that links map back correctly across runs.
        run_a = _make_run(self.team)
        run_b = _make_run(self.team)
        linked_a = _make_emission(self.team, run_a, finding_id="f-a")
        linked_b = _make_emission(self.team, run_b, finding_id="f-b")
        report = SignalReport.objects.create(team=self.team, title="Checkout 500s", status=SignalReport.Status.READY)
        with patch(
            _FETCH_REPORT_IDS,
            return_value={linked_a.source_id: str(report.id), linked_b.source_id: str(report.id)},
        ) as mock_fetch:
            response = self.client.post(self._url(), data={"run_ids": [str(run_a.id), str(run_b.id)]}, format="json")
        assert response.status_code == status.HTTP_200_OK
        mock_fetch.assert_called_once()
        assert sorted(mock_fetch.call_args.args[1]) == sorted([linked_a.source_id, linked_b.source_id])
        body = {row["finding_id"]: row for row in response.json()}
        assert body["f-a"]["report"]["id"] == str(report.id)
        assert body["f-b"]["report"]["id"] == str(report.id)

    def test_foreign_team_run_ids_contribute_no_rows(self) -> None:
        run = _make_run(self.team)
        _make_emission(self.team, run, finding_id="mine")
        other = Team.objects.create(organization=self.organization, name="Other")
        other_run = _make_run(other)
        _make_emission(other, other_run, finding_id="theirs")
        with patch(_FETCH_REPORT_IDS, return_value={}):
            response = self.client.post(self._url(), data={"run_ids": [str(run.id), str(other_run.id)]}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert [row["finding_id"] for row in response.json()] == ["mine"]


class TestScoutHarnessRecentEmissionsAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/emissions/recent/"

    def test_flattens_emissions_across_runs_newest_first_without_run_ids(self) -> None:
        # The cross-run reader: unlike the per-run `emissions` action (one run) and the batch action
        # (caller supplies run_ids), this returns the team's recent findings across every run in one
        # call, each row tagged with its own run_id. Guards that an agent can ask "what has the fleet
        # surfaced lately?" without first listing runs and fanning out.
        run_a = _make_run(self.team)
        run_b = _make_run(self.team)
        _make_emission(self.team, run_a, finding_id="a-old")
        _make_emission(self.team, run_b, finding_id="b-mid")
        _make_emission(self.team, run_a, finding_id="a-new")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [row["finding_id"] for row in body] == ["a-new", "b-mid", "a-old"]
        run_by_finding = {row["finding_id"]: row["run_id"] for row in body}
        assert run_by_finding["a-new"] == str(run_a.id)
        assert run_by_finding["b-mid"] == str(run_b.id)

    def test_does_not_leak_emissions_from_another_team(self) -> None:
        own_run = _make_run(self.team)
        _make_emission(self.team, own_run, finding_id="mine")
        other = Team.objects.create(organization=self.organization, name="Other")
        other_run = _make_run(other)
        _make_emission(other, other_run, finding_id="theirs")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert [row["finding_id"] for row in response.json()] == ["mine"]

    def test_skill_name_filter_scopes_to_the_emitting_scout(self) -> None:
        # The filter walks the FK to the emitting run's skill (`scout_run__skill_name`) — a distinct
        # join path from the run-list's own-column filter, easy to break independently.
        errors_run = _make_run(self.team, skill_name="signals-scout-errors")
        llm_run = _make_run(self.team, skill_name="signals-scout-llm")
        _make_emission(self.team, errors_run, finding_id="err")
        _make_emission(self.team, llm_run, finding_id="llm")
        response = self.client.get(self._url(), data={"skill_name": "signals-scout-errors"})
        assert response.status_code == status.HTTP_200_OK
        assert [row["finding_id"] for row in response.json()] == ["err"]

    def test_limit_caps_the_page(self) -> None:
        run = _make_run(self.team)
        for i in range(3):
            _make_emission(self.team, run, finding_id=f"f-{i}")
        response = self.client.get(self._url(), data={"limit": 2})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

    def test_date_to_excludes_emissions_at_or_after_the_bound(self) -> None:
        # `date_to` is the exclusive upper bound that backs cursor pagination; guard the half-open
        # window so a caller can walk back without re-seeing the boundary row.
        run = _make_run(self.team)
        older = _make_emission(self.team, run, finding_id="older")
        newer = _make_emission(self.team, run, finding_id="newer")
        # emitted_at is auto_now_add, so pin distinct timestamps after the fact.
        SignalScoutEmission.objects.filter(id=older.id).update(emitted_at="2026-01-01T00:00:00Z")
        SignalScoutEmission.objects.filter(id=newer.id).update(emitted_at="2026-01-02T00:00:00Z")
        response = self.client.get(self._url(), data={"date_to": "2026-01-02T00:00:00Z"})
        assert response.status_code == status.HTTP_200_OK
        assert [row["finding_id"] for row in response.json()] == ["older"]


class TestScoutHarnessFindingsSummaryAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/findings/summary/"

    def test_summary_tallies_emitted_findings_across_scouts(self) -> None:
        # The cheap callout tally that replaced the client walking the whole paginated runs window:
        # sums each emitted run's emitted_count, counts distinct scouts, and ignores both quiet runs
        # and other teams. Drop any of those and the callout count drifts.
        _make_run(self.team, skill_name="signals-scout-errors", emitted_count=2, emitted_finding_ids=["a", "b"])
        _make_run(self.team, skill_name="signals-scout-llm", emitted_count=1, emitted_finding_ids=["c"])
        _make_run(self.team, skill_name="signals-scout-errors")  # quiet — emitted_count defaults to 0
        other = Team.objects.create(organization=self.organization, name="Other")
        _make_run(other, emitted_count=5, emitted_finding_ids=["x", "y", "z", "w", "v"])
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["count"] == 3
        assert body["scout_count"] == 2
        assert body["latest_at"] is not None

    def test_summary_excludes_runs_outside_the_window(self) -> None:
        # Guards the `created_at` window filter: a finding emitted before the lookback must not count,
        # else the callout would advertise stale findings the findings page won't show.
        _make_run(self.team, emitted_count=1, emitted_finding_ids=["recent"])
        stale = _make_run(self.team, emitted_count=4, emitted_finding_ids=["a", "b", "c", "d"])
        SignalScoutRun.objects.filter(id=stale.id).update(created_at=timezone.now() - timedelta(hours=80))
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["count"] == 1
        assert body["scout_count"] == 1


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
        # emit-signal requires `signal_scout_internal:write` — session auth is rejected.
        _authenticate_as_scout(self)

    def _emit_signal_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emit-signal/"

    def _payload(self, **overrides) -> dict:
        body: dict = {
            "description": "Checkout 500s spike correlates with payment-flag rollout",
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
        with patch("products.signals.backend.facade.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            response = self.client.post(self._emit_signal_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["emitted"] is True
        assert body["finding_id"] == "f-1"
        assert body["skipped_reason"] is None
        mock_emit.assert_awaited_once()
        assert mock_emit.await_args is not None
        # Idempotency is via the deterministic `source_id` keyed on (run, finding).
        assert mock_emit.await_args.kwargs["source_id"] == f"run:{run.id}:finding:f-1"

    def test_emit_finding_normalizes_tags_into_extra(self) -> None:
        run = _make_run(self.team)
        with patch("products.signals.backend.facade.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            response = self.client.post(
                self._emit_signal_url(str(run.id)),
                data=self._payload(tags=["Cost Spike", "cost_spike", "silent-failure"]),
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.kwargs["extra"]["tags"] == ["cost-spike", "silent-failure"]
        emission = SignalScoutEmission.objects.get(scout_run=run)
        assert emission.tags == ["cost-spike", "silent-failure"]

    def test_emit_finding_rejects_too_many_tags(self) -> None:
        run = _make_run(self.team)
        with patch("products.signals.backend.facade.api.emit_signal", new_callable=AsyncMock) as mock_emit:
            response = self.client.post(
                self._emit_signal_url(str(run.id)),
                data=self._payload(tags=[f"tag-{i}" for i in range(11)]),
                format="json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_emit.assert_not_called()

    def test_emit_finding_rejects_non_in_progress_run(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = _make_run(self.team, task_run_status=TaskRun.Status.COMPLETED)
        response = self.client.post(self._emit_signal_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_emit_finding_unknown_run_returns_404(self) -> None:
        response = self.client.post(
            self._emit_signal_url("00000000-0000-0000-0000-000000000000"), data=self._payload(), format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_emit_finding_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        response = self.client.post(self._emit_signal_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_emit_finding_malformed_run_id_returns_404(self) -> None:
        # Same guard as `retrieve`: a URL-safe non-UUID must 404 before any DB
        # call, not 500 from `.filter(id=...)` on a non-UUID string.
        for bad in ("not-a-uuid", "abc-def-ghi", "123", "deadbeef"):
            response = self.client.post(self._emit_signal_url(bad), data=self._payload(), format="json")
            assert response.status_code == status.HTTP_404_NOT_FOUND, (
                f"expected 404 for {bad!r}, got {response.status_code}"
            )


class TestScoutHarnessScratchpadAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # remember (create) and forget require `signal_scout_internal:write` — session auth
        # is rejected, so authenticate with the scout-internal token like the harness does.
        _authenticate_as_scout(self)

    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/scratchpad/"

    def _forget_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/scratchpad/forget/"

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

    def test_search_keys_only_blanks_content(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="k1", content="a long body")
        response = self.client.get(f"{self._list_url()}?keys_only=true")
        assert response.status_code == status.HTTP_200_OK
        row = response.json()[0]
        assert row["key"] == "k1"
        assert row["content"] == ""

    def test_search_content_max_chars_truncates_preview(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="k1", content="abcdefghij")
        response = self.client.get(f"{self._list_url()}?content_max_chars=4")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["content"] == "abcd"

    def test_search_does_not_leak_other_teams_memory(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        SignalScratchpad.objects.create(team=other, key="theirs", content="leaked?")
        SignalScratchpad.objects.create(team=self.team, key="ours", content="visible")
        response = self.client.get(self._list_url())
        keys = [row["key"] for row in response.json()]
        assert keys == ["ours"]

    def test_forget_removes_entry(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="k1", content="v")
        response = self.client.post(self._forget_url(), data={"key": "k1"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"deleted": True}
        assert not SignalScratchpad.objects.filter(team=self.team, key="k1").exists()

    def test_forget_returns_false_when_key_missing(self) -> None:
        response = self.client.post(self._forget_url(), data={"key": "ghost"}, format="json")
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

    def test_remember_drops_run_id_from_another_team(self) -> None:
        # A run UUID from another team must not create cross-team lineage on this
        # team's memory row — but lineage is best-effort, so the write still lands
        # with `created_by_run_id` left null rather than being rejected.
        other = Team.objects.create(organization=self.organization, name="Other")
        other_run = _make_run(other)
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": str(other_run.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        row = SignalScratchpad.objects.get(team=self.team, key="k1")
        assert row.created_by_run_id is None

    def test_remember_drops_unknown_run_id(self) -> None:
        # A well-formed UUID that doesn't reference any run row is dropped (no orphan
        # lineage), but the memory write itself must never be lost over it.
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        row = SignalScratchpad.objects.get(team=self.team, key="k1")
        assert row.created_by_run_id is None

    def test_remember_rejects_malformed_run_id(self) -> None:
        # UUIDField in the serializer rejects non-UUID strings before the view runs.
        response = self.client.post(
            self._list_url(),
            data={"key": "k1", "content": "v", "run_id": "not-a-uuid"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAgentHarnessProjectProfileAPI(APIBaseTest):
    """The project profile is the scout's orientation surface — read once at run start.

    The build path (per-section table scans + a ClickHouse aggregation, plus a row write)
    is gated to the internal scout token: a session GET bypasses CSRF, so letting it build
    on cache miss would make the rebuild CSRF-triggerable. These tests cover the read-only
    contract for untrusted callers (cached-or-404, never a build) and the scout's lazy build.
    """

    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/project_profile/current/"

    def _seed_profile(self, *, team: Team | None = None) -> str:
        """Persist a real, schema-valid profile via the build path so a later read hits the
        cache, and return its profile_id. Building here is fine — the behavior under test is
        that the *read* doesn't build, not that nothing ever builds.
        """
        return compute_project_profile(team=team or self.team).profile_id

    # --- untrusted (session) callers: read-only, never build ---

    def test_session_read_returns_404_when_no_profile_exists(self) -> None:
        # A session GET bypasses CSRF, so it must not trigger an inline build. With no
        # cached row the read-only caller gets a 404 rather than a freshly-built profile.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 0
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_404_NOT_FOUND
        # No row written as a side effect of the GET.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 0

    def test_session_read_returns_cached_profile(self) -> None:
        seeded_id = self._seed_profile()
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["profile_id"] == seeded_id
        assert {"profile_id", "computed_at", "expires_at", "source_version"} <= set(body.keys())
        assert "inventory" in body["payload"]
        # Read-only: no new row written.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_session_read_ignores_force_refresh(self) -> None:
        # `force_refresh` is honored only for the internal scout token. A session caller
        # passing it still gets the cached row — no rebuild, no second row.
        seeded_id = self._seed_profile()
        response = self.client.get(self._list_url(), {"force_refresh": "true"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["profile_id"] == seeded_id
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_session_read_does_not_leak_other_teams_profile(self) -> None:
        # Another team in the same org has a profile; ours does not. A session GET must
        # neither build ours nor surface theirs — it 404s.
        other = Team.objects.create(organization=self.organization, name="Other")
        self._seed_profile(team=other)
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- internal scout token: lazy-builds on miss ---

    def test_scout_read_lazy_computes_a_profile_when_none_exists(self) -> None:
        _authenticate_as_scout(self)
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 0
        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        # Response shape carries the cache metadata + the inventory payload.
        assert {"profile_id", "computed_at", "expires_at", "source_version"} <= set(body.keys())
        assert "inventory" in body["payload"]
        # And a row was persisted as a side effect of the scout's build.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_scout_read_returns_cached_profile_on_repeat_call(self) -> None:
        _authenticate_as_scout(self)
        first = self.client.get(self._list_url()).json()
        second = self.client.get(self._list_url()).json()
        assert first["profile_id"] == second["profile_id"]
        # No second row written.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_scout_read_inventory_payload_carries_expected_keys(self) -> None:
        _authenticate_as_scout(self)
        response = self.client.get(self._list_url())
        inventory = response.json()["payload"]["inventory"]
        assert set(inventory.keys()) == {
            "project_context",
            "products_in_use",
            "product_intents",
            "integrations",
            "external_data_sources",
            "signal_source_configs",
            "emit_eligibility",
            "existing_inbox_reports",
            "recent_activity",
            "recent_dashboards",
            "recent_surveys",
            "recent_feature_flags",
            "recent_experiments",
            "recent_alerts",
            "recent_hog_functions",
            "recent_hog_flows",
            "recent_notebooks",
            "recent_cohorts",
            "recent_actions",
            "recent_reviewer_corrections",
            "top_events",
        }

    # --- per-scout dry-run overlay (run_id) ---

    def _emit_eligibility(self, response) -> dict:
        return response.json()["payload"]["inventory"]["emit_eligibility"]

    def test_scout_read_with_run_id_flags_own_dry_run(self) -> None:
        # The reported defect: a dry-run scout (its config has emit disabled) must read
        # can_emit=false during Orient. The team-wide gates alone report can_emit=true, so without
        # the run_id overlay it would author a report and only learn at emit time that it's dropped.
        _authenticate_as_scout(self)
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-dry", emit=False)
        run = _make_run(self.team, scout_config=config, skill_name="signals-scout-dry")
        body = self._emit_eligibility(self.client.get(self._list_url(), {"run_id": str(run.id)}))
        assert body["scout_dry_run"] is True
        assert body["can_emit"] is False
        assert body["remediation"] and "dry-run" in body["remediation"]

    def test_scout_read_reports_can_emit_when_not_own_dry_run(self) -> None:
        # The overlay must only fire for a scout that is itself in dry-run: an emitting scout, a
        # caller that omits run_id, and an unresolvable run_id all fall back to the team-wide
        # baseline (can_emit true here), so the fix can't over-block emitting scouts.
        _authenticate_as_scout(self)
        emitting_config = SignalScoutConfig.objects.create(
            team=self.team, skill_name="signals-scout-emitting", emit=True
        )
        emitting_run = _make_run(self.team, scout_config=emitting_config, skill_name="signals-scout-emitting")
        for label, params in [
            ("emitting scout's run_id", {"run_id": str(emitting_run.id)}),
            ("no run_id (team baseline)", {}),
            ("unknown run_id", {"run_id": str(uuid.uuid4())}),
        ]:
            with self.subTest(label):
                body = self._emit_eligibility(self.client.get(self._list_url(), params))
                assert body["scout_dry_run"] is False, label
                assert body["can_emit"] is True, label


class TestScoutHarnessConfigAPI(APIBaseTest):
    def _list_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/configs/"

    def _detail_url(self, config_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/configs/{config_id}/"

    def _make_skill(self, name: str, team: Team | None = None) -> LLMSkill:
        return LLMSkill.objects.create(
            team=team or self.team,
            name=name,
            description="test scout",
            body="# test scout",
        )

    def test_list_returns_team_configs_ordered_by_skill(self) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-beta")
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-alpha")

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [c["skill_name"] for c in body] == ["signals-scout-alpha", "signals-scout-beta"]
        assert body[0]["enabled"] is True
        assert body[0]["emit"] is True
        assert body[0]["run_interval_minutes"] == 1440

    def test_list_excludes_withheld_config(self) -> None:
        # A held-back scout that still has a row (previously seeded, then withheld) is not surfaced
        # in the config list — the read surface stays consistent with the seeding + dispatch gates.
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-alpha")
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-error-tracking")
        payload_path = "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload"
        with patch(
            payload_path,
            return_value={"default_team_config": {"withheld_skills": ["signals-scout-error-tracking"]}},
        ):
            response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        assert [c["skill_name"] for c in response.json()] == ["signals-scout-alpha"]

    @parameterized.expand(
        [
            ("skill_present", "Watches error tracking for new and spiking issues."),
            ("skill_absent", None),
        ]
    )
    def test_list_surfaces_skill_description(self, _name: str, skill_description: str | None) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-errors")
        if skill_description is not None:
            LLMSkill.objects.create(
                team=self.team, name="signals-scout-errors", description=skill_description, body="..."
            )

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        # Absent skill (or no description) falls back to "".
        assert response.json()[0]["description"] == (skill_description or "")

    def test_list_description_ignores_non_latest_and_other_team_skills(self) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-errors")
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="stale",
            body="...",
            version=1,
            is_latest=False,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="current",
            body="...",
            version=2,
            is_latest=True,
        )
        other_team = Team.objects.create(organization=self.organization, name="other")
        LLMSkill.objects.create(team=other_team, name="signals-scout-errors", description="other team", body="...")

        response = self.client.get(self._list_url())

        assert response.json()[0]["description"] == "current"

    def test_partial_update_surfaces_skill_description(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=False)
        LLMSkill.objects.create(team=self.team, name="signals-scout-foo", description="Foo scout.", body="...")

        response = self.client.patch(self._detail_url(str(config.id)), data={"enabled": True}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["description"] == "Foo scout."
        # The partial_update path resolves skill_info independently of list — assert origin too.
        assert response.json()["scout_origin"] == "custom"

    @parameterized.expand(
        [
            # (label, skill_name, metadata, expected). `signals-scout-general` is a real on-disk
            # canonical scout; `signals-scout-my-fork` is a name the harness never ships.
            (
                "harness_seeded_canonical_name",
                "signals-scout-general",
                {"seeded_by": HARNESS_SEEDED_BY, "source": "products/signals/skills"},
                "canonical",
            ),
            ("hand_authored_no_metadata", "signals-scout-general", {}, "custom"),
            ("hand_authored_other_seed", "signals-scout-general", {"seeded_by": "some_other_thing"}, "custom"),
            # A fork via duplicate_skill() inherits the source row's seeded_by tag, but a fork can
            # never take a canonical name — so the name guard reclassifies it as custom.
            ("seeded_tag_but_non_canonical_name", "signals-scout-my-fork", {"seeded_by": HARNESS_SEEDED_BY}, "custom"),
        ]
    )
    def test_list_classifies_origin_from_skill_metadata(
        self, _name: str, skill_name: str, metadata: dict, expected_origin: str
    ) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name=skill_name)
        LLMSkill.objects.create(team=self.team, name=skill_name, description="d", body="...", metadata=metadata)

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["scout_origin"] == expected_origin

    def test_list_origin_defaults_to_custom_when_skill_absent(self) -> None:
        # A config with no live skill row isn't a canonical scout.
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-errors")

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["scout_origin"] == "custom"

    def test_partial_update_changes_schedule_emit_and_records_enabled_by(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=False)

        response = self.client.patch(
            self._detail_url(str(config.id)),
            data={"enabled": True, "emit": True, "run_interval_minutes": 60},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        config.refresh_from_db()
        assert config.enabled is True
        assert config.emit is True
        assert config.run_interval_minutes == 60
        assert config.enabled_by_id == self.user.id

    def test_partial_update_rejects_interval_below_min(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        # 20 is below the 30-minute floor (the tightest cadence the UI offers) but above the old
        # 10-minute floor, so this also guards against the floor being reverted.
        response = self.client.patch(self._detail_url(str(config.id)), data={"run_interval_minutes": 20}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_partial_update_cannot_change_skill_name(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        self.client.patch(self._detail_url(str(config.id)), data={"skill_name": "signals-scout-bar"}, format="json")
        config.refresh_from_db()
        assert config.skill_name == "signals-scout-foo"

    def test_partial_update_unknown_id_returns_404(self) -> None:
        response = self.client.patch(
            self._detail_url("00000000-0000-0000-0000-000000000000"), data={"enabled": False}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update_other_teams_config_returns_404(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        config = SignalScoutConfig.all_teams.create(team=other_team, skill_name="signals-scout-foo")
        response = self.client.patch(self._detail_url(str(config.id)), data={"enabled": False}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_destroy_removes_config(self) -> None:
        # The orphan-cleanup path: a config whose skill is gone can't be made to disappear via
        # partial_update (only inert), so destroy must actually remove the row.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")

        response = self.client.delete(self._detail_url(str(config.id)))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SignalScoutConfig.all_teams.filter(id=config.id).exists()

    def test_destroy_unknown_id_returns_404(self) -> None:
        response = self.client.delete(self._detail_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_destroy_other_teams_config_returns_404_and_preserves_row(self) -> None:
        # Tenant isolation: deleting must be scoped by team — another team's config is neither
        # removed nor acknowledged.
        other_team = Team.objects.create(organization=self.organization, name="other")
        config = SignalScoutConfig.all_teams.create(team=other_team, skill_name="signals-scout-foo")

        response = self.client.delete(self._detail_url(str(config.id)))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SignalScoutConfig.all_teams.filter(id=config.id).exists()

    def _sync_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/configs/sync/"

    def test_sync_materializes_fleet_for_fresh_team(self) -> None:
        canonical_names = {c.name for c in discover_canonical_skills()}
        scout_names = {n for n in canonical_names if n.startswith("signals-scout-")}
        companion_names = canonical_names - scout_names
        assert scout_names, "expected canonical signals-scout-* skills on disk"
        assert "authoring-scouts" in companion_names
        assert SignalScoutConfig.objects.filter(team=self.team).count() == 0

        response = self.client.post(self._sync_url())

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        # Only scouts get configs — companion skills (authoring-scouts) are seeded
        # into the team's LLMSkill namespace below but never materialize a scout config.
        assert {c["skill_name"] for c in body} == scout_names
        assert [c["skill_name"] for c in body] == sorted(scout_names)
        assert all(c["enabled"] is True for c in body)
        assert all(c["emit"] is True for c in body)
        assert all(c["run_interval_minutes"] == 1440 for c in body)
        assert SignalScoutConfig.objects.filter(team=self.team).count() == len(scout_names)
        # Every canonical skill — fleet and companions — was seeded into the team's
        # LLMSkill namespace.
        assert (
            set(LLMSkill.objects.filter(team=self.team, deleted=False).values_list("name", flat=True))
            == canonical_names
        )

    def test_sync_respects_withheld_skills_holdback(self) -> None:
        # A scout held back via the `signals-scout` flag denylist must not be seeded or
        # config-materialized by the on-demand sync endpoint, the same as the scheduled path. The
        # holdback resolves through `team_limits.withheld_skills_for_team`, so patch the flag read
        # there (same module `_METADATA_PAYLOAD_PATH` points at).
        payload_path = "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload"
        with patch(
            payload_path,
            return_value={"default_team_config": {"withheld_skills": ["signals-scout-error-tracking"]}},
        ):
            response = self.client.post(self._sync_url())

        assert response.status_code == status.HTTP_200_OK
        skill_names = {c["skill_name"] for c in response.json()}
        assert "signals-scout-error-tracking" not in skill_names
        assert "signals-scout-general" in skill_names
        assert not SignalScoutConfig.objects.filter(team=self.team, skill_name="signals-scout-error-tracking").exists()
        assert not LLMSkill.objects.filter(team=self.team, name="signals-scout-error-tracking", deleted=False).exists()

    def test_sync_excludes_previously_seeded_withheld_config(self) -> None:
        # A config seeded before the scout was withheld still exists in storage; the sync response
        # must not surface it (visibility boundary), even though we don't tombstone the row.
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-error-tracking")
        payload_path = "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload"
        with patch(
            payload_path,
            return_value={"default_team_config": {"withheld_skills": ["signals-scout-error-tracking"]}},
        ):
            response = self.client.post(self._sync_url())

        assert response.status_code == status.HTTP_200_OK
        assert "signals-scout-error-tracking" not in {c["skill_name"] for c in response.json()}
        # Storage is untouched — the row is hidden from the response, not deleted.
        assert SignalScoutConfig.objects.filter(team=self.team, skill_name="signals-scout-error-tracking").exists()

    def test_sync_rejects_read_only_scope(self) -> None:
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.utils import generate_random_token_personal, hash_key_value

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read only",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scoped_teams=[self.team.id],
            scopes=["signal_scout:read"],
        )
        self.client.logout()

        response = self.client.post(self._sync_url(), HTTP_AUTHORIZATION=f"Bearer {key_value}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert SignalScoutConfig.objects.filter(team=self.team).count() == 0

    def test_sync_is_idempotent_and_preserves_tuned_configs(self) -> None:
        first = self.client.post(self._sync_url())
        assert first.status_code == status.HTTP_200_OK
        fleet_size = len(first.json())

        # Tune one config the way a user would, then sync again.
        tuned = SignalScoutConfig.objects.filter(team=self.team).order_by("skill_name").first()
        assert tuned is not None
        tuned.enabled = False
        tuned.save(update_fields=["enabled"])

        second = self.client.post(self._sync_url())

        assert second.status_code == status.HTTP_200_OK
        assert len(second.json()) == fleet_size
        assert SignalScoutConfig.objects.filter(team=self.team).count() == fleet_size
        tuned.refresh_from_db()
        assert tuned.enabled is False, "sync must not reset existing configs"

    def test_list_is_side_effect_free_for_unregistered_scout_skills(self) -> None:
        # The list MCP tool is annotated readOnly — a scout skill without a config must not
        # get one minted by a GET; registration is the coordinator's or `create`'s job.
        self._make_skill("signals-scout-fresh")

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        assert not SignalScoutConfig.objects.filter(team=self.team, skill_name="signals-scout-fresh").exists()

    def test_create_registers_config_with_provided_fields(self) -> None:
        self._make_skill("signals-scout-fresh")

        response = self.client.post(
            self._list_url(),
            data={"skill_name": "signals-scout-fresh", "run_interval_minutes": 120, "emit": False},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["skill_name"] == "signals-scout-fresh"
        assert body["run_interval_minutes"] == 120
        assert body["emit"] is False
        assert body["enabled"] is True
        config = SignalScoutConfig.objects.get(team=self.team, skill_name="signals-scout-fresh")
        assert config.created_by_id == self.user.id
        assert config.enabled_by_id == self.user.id

    def test_create_stamps_scout_category_on_skill(self) -> None:
        skill = self._make_skill("signals-scout-fresh")
        assert skill.category == ""

        response = self.client.post(self._list_url(), data={"skill_name": "signals-scout-fresh"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        skill.refresh_from_db()
        assert skill.category == "scout"

    def test_create_disabled_config_does_not_stamp_enabled_by(self) -> None:
        self._make_skill("signals-scout-fresh")

        response = self.client.post(
            self._list_url(), data={"skill_name": "signals-scout-fresh", "enabled": False}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        config = SignalScoutConfig.objects.get(team=self.team, skill_name="signals-scout-fresh")
        assert config.enabled is False
        assert config.enabled_by_id is None

    def test_create_upserts_existing_config(self) -> None:
        self._make_skill("signals-scout-fresh")
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-fresh", enabled=False)

        response = self.client.post(
            self._list_url(),
            data={"skill_name": "signals-scout-fresh", "enabled": True, "run_interval_minutes": 120},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        config = SignalScoutConfig.objects.get(team=self.team, skill_name="signals-scout-fresh")
        assert config.enabled is True
        assert config.run_interval_minutes == 120
        assert config.enabled_by_id == self.user.id

    def test_create_upsert_leaves_omitted_fields_untouched(self) -> None:
        self._make_skill("signals-scout-fresh")
        SignalScoutConfig.objects.create(
            team=self.team, skill_name="signals-scout-fresh", emit=False, run_interval_minutes=120
        )

        # Set only `emit` — the schedule must stay where it was.
        response = self.client.post(
            self._list_url(), data={"skill_name": "signals-scout-fresh", "emit": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        config = SignalScoutConfig.objects.get(team=self.team, skill_name="signals-scout-fresh")
        assert config.emit is True
        assert config.run_interval_minutes == 120

    _CAP_PATCH = "products.signals.backend.scout_harness.views.MAX_ENABLED_SCOUTS_PER_TEAM"

    def test_create_disabled_config_is_allowed_at_team_cap(self) -> None:
        self._make_skill("signals-scout-first")
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-first", enabled=True)
        self._make_skill("signals-scout-second")

        with patch(self._CAP_PATCH, 1):
            response = self.client.post(
                self._list_url(), data={"skill_name": "signals-scout-second", "enabled": False}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED
        config = SignalScoutConfig.objects.get(team=self.team, skill_name="signals-scout-second")
        assert config.enabled is False

    @parameterized.expand(["create", "partial_update"])
    def test_enable_past_team_cap_is_rejected(self, surface: str) -> None:
        # Both write surfaces enforce the same cap: with one enabled scout filling the
        # (patched) cap, flipping a second scout on must 400 and leave it disabled.
        self._make_skill("signals-scout-first")
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-first", enabled=True)
        self._make_skill("signals-scout-second")
        second = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-second", enabled=False)

        with patch(self._CAP_PATCH, 1):
            if surface == "create":
                response = self.client.post(
                    self._list_url(), data={"skill_name": "signals-scout-second", "enabled": True}, format="json"
                )
            else:
                response = self.client.patch(self._detail_url(str(second.id)), data={"enabled": True}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "enabled scouts" in response.json()["detail"]
        second.refresh_from_db()
        assert second.enabled is False

    @parameterized.expand(
        [
            # Re-asserting `enabled=True` on the already-enabled scout: it's excluded from
            # its own cap count, so the upsert must not read as exceeding the cap.
            ("create_reassert_enabled", "create", {"skill_name": "signals-scout-first", "enabled": True}),
            # Tuning a field on an already-enabled scout isn't a net-new enable, so the cap
            # check is skipped entirely.
            ("partial_update_tune", "partial_update", {"run_interval_minutes": 120}),
        ]
    )
    def test_tuning_enabled_scout_is_allowed_at_team_cap(self, _name: str, surface: str, data: dict) -> None:
        self._make_skill("signals-scout-first")
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-first", enabled=True)

        with patch(self._CAP_PATCH, 1):
            if surface == "create":
                response = self.client.post(self._list_url(), data=data, format="json")
            else:
                response = self.client.patch(self._detail_url(str(config.id)), data=data, format="json")

        assert response.status_code == status.HTTP_200_OK

    @parameterized.expand(
        [
            ("unknown_skill", "signals-scout-nonexistent"),
            ("non_scout_prefix", "my-ordinary-skill"),
        ]
    )
    def test_create_rejects_invalid_skill_name(self, _name: str, skill_name: str) -> None:
        if not skill_name.startswith("signals-scout-"):
            self._make_skill(skill_name)
        response = self.client.post(self._list_url(), data={"skill_name": skill_name}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalScoutConfig.objects.filter(team=self.team, skill_name=skill_name).exists()

    def test_create_rejects_skill_belonging_to_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._make_skill("signals-scout-fresh", team=other_team)

        response = self.client.post(self._list_url(), data={"skill_name": "signals-scout-fresh"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            not SignalScoutConfig.all_teams.filter(skill_name="signals-scout-fresh").exclude(team=other_team).exists()
        )

    def test_create_rejects_interval_below_min(self) -> None:
        self._make_skill("signals-scout-fresh")
        response = self.client.post(
            self._list_url(), data={"skill_name": "signals-scout-fresh", "run_interval_minutes": 20}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


_METADATA_PAYLOAD_PATH = "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload"


class TestScoutHarnessMetadataAPI(APIBaseTest):
    """Scout metadata endpoint: enrollment, the alpha banner, and the enforced run limits, all
    resolved from the `signals-scout` flag payload so the UI shows the throttle dispatch applies."""

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/metadata/current/"

    def _get(self, payload: dict | None):
        # The endpoint reads the flag payload via team_limits; stub it so enrollment + caps are
        # deterministic without depending on the live flag.
        with patch(_METADATA_PAYLOAD_PATH, return_value=payload):
            return self.client.get(self._url())

    def test_returns_metadata_shape(self) -> None:
        response = self._get({"guaranteed_team_ids": [self.team.id]})
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert set(body.keys()) == {"enrolled", "banner_message", "limits"}
        assert set(body["limits"].keys()) == {
            "max_runs_per_tick",
            "max_runs_per_day",
            "runs_today",
            "runs_remaining_today",
        }

    @parameterized.expand([("listed", True), ("not_listed", False)])
    def test_enrolled_reflects_guaranteed_team_ids(self, _name: str, listed: bool) -> None:
        team_id = self.team.id if listed else self.team.id + 1
        assert self._get({"guaranteed_team_ids": [team_id]}).json()["enrolled"] is listed

    def test_falls_back_to_suppressed_metadata_when_flag_unavailable(self) -> None:
        # Flag service down → `_read_flag_payload` returns None: enrollment falls back to the
        # gated allowlist (which this fresh team isn't on), the banner is suppressed, and the caps
        # default to the code constants. The endpoint must stay up and fail closed, not error.
        body = self._get(None).json()
        assert body["enrolled"] is False
        assert body["banner_message"] is None
        assert body["limits"]["max_runs_per_tick"] == MAX_RUNS_PER_TEAM_PER_TICK
        assert body["limits"]["max_runs_per_day"] is None

    def test_banner_message_surfaced_from_payload(self) -> None:
        body = self._get(
            {"guaranteed_team_ids": [self.team.id], "scouts_banner_message": "Alpha: daily runs limited"}
        ).json()
        assert body["banner_message"] == "Alpha: daily runs limited"

    @parameterized.expand(
        [("unset", {}), ("blank", {"scouts_banner_message": "   "}), ("non_string", {"scouts_banner_message": 123})]
    )
    def test_banner_message_null_when_unset_blank_or_non_string(self, _name: str, extra: dict) -> None:
        body = self._get({"guaranteed_team_ids": [self.team.id], **extra}).json()
        assert body["banner_message"] is None

    def test_limits_unbounded_by_default(self) -> None:
        # No caps configured anywhere → day is uncapped and the per-tick cap falls back to the
        # code default; the UI should show "no daily limit" rather than a fabricated number.
        body = self._get({"guaranteed_team_ids": [self.team.id]}).json()
        assert body["limits"]["max_runs_per_day"] is None
        assert body["limits"]["runs_remaining_today"] is None
        assert body["limits"]["max_runs_per_tick"] == MAX_RUNS_PER_TEAM_PER_TICK

    def test_limits_resolved_from_default_team_config(self) -> None:
        body = self._get(
            {
                "guaranteed_team_ids": [self.team.id],
                "default_team_config": {"max_runs_per_day": 3, "max_runs_per_tick": 1},
            }
        ).json()
        assert body["limits"]["max_runs_per_day"] == 3
        assert body["limits"]["max_runs_per_tick"] == 1

    def test_per_team_config_overrides_default(self) -> None:
        body = self._get(
            {
                "guaranteed_team_ids": [self.team.id],
                "default_team_config": {"max_runs_per_day": 3},
                "team_configs": {str(self.team.id): {"max_runs_per_day": 50}},
            }
        ).json()
        assert body["limits"]["max_runs_per_day"] == 50

    def test_runs_today_and_remaining_count_recent_runs(self) -> None:
        _make_run(self.team)
        _make_run(self.team)
        body = self._get({"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 5}}).json()
        assert body["limits"]["runs_today"] == 2
        assert body["limits"]["runs_remaining_today"] == 3

    def test_remaining_floors_at_zero_when_budget_spent(self) -> None:
        for _ in range(3):
            _make_run(self.team)
        body = self._get({"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 1}}).json()
        assert body["limits"]["runs_today"] == 3
        assert body["limits"]["runs_remaining_today"] == 0

    def test_runs_today_does_not_count_other_teams(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        _make_run(other)
        _make_run(self.team)
        body = self._get({"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 5}}).json()
        assert body["limits"]["runs_today"] == 1


_QUOTA = "products.signals.backend.scout_harness.views.is_team_signals_quota_limited"
_START = "products.signals.backend.temporal.agentic.scout_scheduler.start_manual_signals_scout_run"
_CONNECT = "products.signals.backend.scout_harness.views.sync_connect"
_WITHHELD = "products.signals.backend.scout_harness.views.withheld_skills_for_team"
_FLAG = "products.signals.backend.scout_harness.views._read_flag_payload"


class TestScoutHarnessConfigRunAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The run action requires a live backing skill; every dispatch case needs one present.
        LLMSkill.objects.create(team=self.team, name="signals-scout-foo", description="Foo scout.", body="...")
        # The manual run honors the same enrollment + daily-budget gates as the coordinator. Enroll
        # this team by default (no daily cap) so the dispatch cases reach the run path; the
        # enrollment/budget regression cases override this payload.
        flag = patch(_FLAG, return_value={"guaranteed_team_ids": [self.team.id]})
        flag.start()
        self.addCleanup(flag.stop)

    def _run_url(self, config_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/configs/{config_id}/run/"

    @parameterized.expand([("enabled", True), ("disabled", False)])
    def test_run_dispatches_and_returns_workflow_id(self, _name: str, enabled: bool) -> None:
        # Disabled scouts are dispatchable too (run-to-test before enabling) — that's the regression
        # guard for the "allow disabled" decision; a stray `enabled` gate would fail the disabled case.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=enabled)
        with (
            patch(_QUOTA, return_value=False),
            patch(_CONNECT) as connect,
            patch(_START, return_value="wf-123") as start,
        ):
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"skill_name": "signals-scout-foo", "workflow_id": "wf-123", "started": True}
        start.assert_called_once_with(connect.return_value, team_id=self.team.id, skill_name="signals-scout-foo")

    def test_run_over_quota_returns_429_without_dispatching(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with patch(_QUOTA, return_value=True), patch(_START) as start:
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        start.assert_not_called()

    def test_run_with_in_flight_run_returns_409_without_dispatching(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        _make_run(self.team, skill_name="signals-scout-foo")  # TaskRun IN_PROGRESS by default
        with patch(_QUOTA, return_value=False), patch(_START) as start:
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_409_CONFLICT
        start.assert_not_called()

    def test_run_maps_workflow_already_started_race_to_409(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        race = WorkflowAlreadyStartedError("wf", "RunSignalsScoutWorkflow")
        with patch(_QUOTA, return_value=False), patch(_CONNECT), patch(_START, side_effect=race):
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_run_unknown_config_returns_404_without_dispatching(self) -> None:
        with patch(_QUOTA, return_value=False), patch(_START) as start:
            response = self.client.post(self._run_url("00000000-0000-0000-0000-000000000000"))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        start.assert_not_called()

    def test_run_withheld_scout_returns_404_without_dispatching(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with (
            patch(_WITHHELD, return_value={"signals-scout-foo"}),
            patch(_QUOTA, return_value=False),
            patch(_START) as start,
        ):
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        start.assert_not_called()

    def test_run_config_without_backing_skill_returns_404_without_dispatching(self) -> None:
        # A config can outlive its skill; dispatching would 202 then fail in the runner with no run
        # row to poll. Reject up front — guards the latest-non-deleted-skill check in `run`.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-orphan")
        with patch(_QUOTA, return_value=False), patch(_START) as start:
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        start.assert_not_called()

    def test_run_dispatches_when_only_in_flight_run_is_stale(self) -> None:
        # An orphan past the stale cutoff (crashed worker, never wrote a terminal status) must not
        # wedge the 409 fail-fast — otherwise a disabled scout, whose only run path is this endpoint,
        # could never recover. The dispatched run's own self-heal reaps it; the view must let it through.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        stale = _make_run(self.team, skill_name="signals-scout-foo")  # TaskRun IN_PROGRESS by default
        old = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S + 60)
        TaskRun = apps.get_model("tasks", "TaskRun")
        TaskRun.objects.filter(id=stale.task_run_id).update(created_at=old)
        with (
            patch(_QUOTA, return_value=False),
            patch(_CONNECT),
            patch(_START, return_value="wf-123") as start,
        ):
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_202_ACCEPTED
        start.assert_called_once()

    def test_run_on_skipped_team_returns_403_without_dispatching(self) -> None:
        # `skip_team_ids` is the operator kill switch: the coordinator never schedules a skipped
        # team, so the manual trigger must refuse it too — otherwise any `signal_scout:write` caller
        # could run a scout an operator deliberately suppressed. Guards the enrollment check in `run`.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with (
            patch(_FLAG, return_value={"guaranteed_team_ids": [self.team.id], "skip_team_ids": [self.team.id]}),
            patch(_QUOTA, return_value=False),
            patch(_START) as start,
        ):
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        start.assert_not_called()

    def test_run_over_daily_budget_returns_429_without_dispatching(self) -> None:
        # Manual runs count against the same per-team daily budget the coordinator enforces, so once
        # `max_runs_per_day` is spent the trigger is throttled instead of letting repeated manual runs
        # blow past the cap. One run already landed today and the cap is 1 → the next is refused.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        TaskRun = apps.get_model("tasks", "TaskRun")
        _make_run(self.team, skill_name="signals-scout-foo", task_run_status=TaskRun.Status.COMPLETED)
        with (
            patch(
                _FLAG,
                return_value={"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 1}},
            ),
            patch(_QUOTA, return_value=False),
            patch(_START) as start,
        ):
            response = self.client.post(self._run_url(str(config.id)))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        start.assert_not_called()


class TestScoutHarnessMembersAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _authenticate_as_scout(self)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/members/"

    def test_lists_project_members_with_resolved_github_login(self) -> None:
        # self.user has a GitHub identity (login lowercased on resolution); a second member has
        # none, so their `github_login` is null rather than dropping out of the roster.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-self", extra_data={"login": "OctoCat"})
        User.objects.create_and_join(self.organization, "second@posthog.com", None, first_name="Sec")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        by_email = {row["email"]: row for row in response.json()}
        assert by_email[self.user.email]["github_login"] == "octocat"
        assert by_email[self.user.email]["user_uuid"] == str(self.user.uuid)
        assert by_email["second@posthog.com"]["github_login"] is None

    @parameterized.expand(
        [
            # a single token matches an email / one name part …
            ("single_token", "alice", {"alice@posthog.com"}),
            # … and a full display name matches the concatenated first+last, not just one field —
            # the case a naive per-field filter misses (regression guard for the search predicate).
            ("full_display_name", "jane doe", {"jane@posthog.com"}),
        ]
    )
    def test_search_narrows_the_roster(self, _name: str, query: str, expected_emails: set[str]) -> None:
        # `search` is the bound on a large roster — it must filter to matching email/name so a scout
        # can pull just the owner instead of the whole directory. Case-insensitive substring.
        User.objects.create_and_join(self.organization, "alice@posthog.com", None, first_name="Alice")
        User.objects.create_and_join(self.organization, "jane@posthog.com", None, first_name="Jane", last_name="Doe")
        response = self.client.get(self._url(), data={"search": query})
        assert response.status_code == status.HTTP_200_OK
        emails = {row["email"] for row in response.json()}
        assert emails == expected_emails

    def test_does_not_leak_members_from_another_org(self) -> None:
        other_org = Organization.objects.create(name="Other Org")
        User.objects.create_and_join(other_org, "outsider@example.com", None)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        emails = {row["email"] for row in response.json()}
        assert self.user.email in emails
        assert "outsider@example.com" not in emails

    @parameterized.expand([("session", None), ("public_read_token", "read_only")])
    def test_non_scout_auth_cannot_list_members(self, _name: str, scopes: PosthogMcpScopes | None) -> None:
        # The roster (member PII) is gated on the internal `signal_scout_internal` scope object, so neither
        # a logged-in session (the CSRF / PAK class) nor a public `read_only` MCP token — which carries no
        # internal scope — can reach it; only a sandbox scout token can. Guards the internal-vs-external
        # boundary: keeps member emails / logins off every user-grantable credential and the public catalog.
        if scopes is None:
            self.client.credentials()
            self.client.force_login(self.user)
        else:
            _authenticate_as_scout(self, scopes=scopes)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_403_FORBIDDEN
