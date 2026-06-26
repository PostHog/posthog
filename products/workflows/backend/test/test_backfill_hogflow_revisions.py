from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from posthog.models.team.team import Team
from posthog.models.user import User

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_revision import HogFlowRevision, sync_mirror_revision


@patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
class TestBackfillHogFlowRevisions(TestCase):
    def setUp(self):
        super().setUp()
        self.organization, self.team, _user = User.objects.bootstrap("Test org", "backfill@posthog.com", None)
        self.team2 = Team.objects.create(organization=self.organization, name="Team 2")

    def _create_flow(self, team, name="Flow", **kwargs):
        defaults = {
            "name": name,
            "status": HogFlow.State.ACTIVE,
            "trigger": {"type": "event", "filters": {"events": [{"id": "$pageview"}]}},
            "edges": [{"from": "a", "to": "b"}],
            "actions": [{"id": "a", "type": "trigger"}],
        }
        defaults.update(kwargs)
        return HogFlow.objects.create(team=team, **defaults)

    def test_backfill_creates_one_active_revision_per_flow_and_sets_pointer(self, _mock):
        flow = self._create_flow(self.team, name="Flow 1")

        call_command("backfill_hogflow_revisions", stdout=StringIO())

        flow.refresh_from_db()
        assert flow.active_revision is not None
        revision = flow.active_revision
        assert revision.status == HogFlowRevision.State.ACTIVE
        assert revision.team_id == self.team.id
        assert revision.version == flow.version

    def test_backfill_copies_all_content_fields(self, _mock):
        flow = self._create_flow(
            self.team,
            name="Full Flow",
            description="A description",
            trigger_masking={"ttl": 3600},
            conversion={"goal": "purchase"},
            exit_condition="exit_on_trigger_not_matched",
            abort_action="abort_node",
            variables=[{"name": "x"}],
            billable_action_types=["function"],
        )

        call_command("backfill_hogflow_revisions", stdout=StringIO())

        flow.refresh_from_db()
        rev = flow.active_revision
        assert rev.name == "Full Flow"
        assert rev.description == "A description"
        assert rev.trigger == flow.trigger
        assert rev.edges == flow.edges
        assert rev.actions == flow.actions
        assert rev.trigger_masking == {"ttl": 3600}
        assert rev.conversion == {"goal": "purchase"}
        assert rev.exit_condition == "exit_on_trigger_not_matched"
        assert rev.abort_action == "abort_node"
        assert rev.variables == [{"name": "x"}]
        assert rev.billable_action_types == ["function"]

    def test_backfill_is_idempotent(self, _mock):
        self._create_flow(self.team)

        call_command("backfill_hogflow_revisions", stdout=StringIO())
        assert HogFlowRevision.objects.count() == 1

        out = StringIO()
        call_command("backfill_hogflow_revisions", stdout=out)
        assert HogFlowRevision.objects.count() == 1
        assert "Nothing to backfill" in out.getvalue()

    def test_backfill_filters_by_team(self, _mock):
        self._create_flow(self.team, name="Team 1 Flow")
        self._create_flow(self.team2, name="Team 2 Flow")

        call_command("backfill_hogflow_revisions", team_id=self.team.id, stdout=StringIO())

        assert HogFlowRevision.objects.filter(team=self.team).count() == 1
        assert HogFlowRevision.objects.filter(team=self.team2).count() == 0

    def test_backfill_draft_workflow_gets_draft_revision_without_pointer(self, _mock):
        flow = self._create_flow(self.team, status=HogFlow.State.DRAFT)

        call_command("backfill_hogflow_revisions", stdout=StringIO())

        flow.refresh_from_db()
        assert flow.active_revision_id is None
        assert flow.revisions.get().status == HogFlowRevision.State.DRAFT

    def test_backfill_skips_draft_already_double_written(self, _mock):
        # A draft created after double-write went live has a null pointer but an existing mirror revision.
        # Selecting on active_revision instead of revisions would re-pick it and collide on the unique
        # (team, hog_flow, version) constraint.
        flow = self._create_flow(self.team, status=HogFlow.State.DRAFT)
        sync_mirror_revision(flow)
        assert flow.active_revision_id is None
        assert HogFlowRevision.objects.filter(hog_flow=flow).count() == 1

        out = StringIO()
        call_command("backfill_hogflow_revisions", stdout=out)

        assert HogFlowRevision.objects.filter(hog_flow=flow).count() == 1
        assert "Nothing to backfill" in out.getvalue()

    def test_dry_run_writes_nothing(self, _mock):
        self._create_flow(self.team)

        out = StringIO()
        call_command("backfill_hogflow_revisions", dry_run=True, stdout=out)

        assert HogFlowRevision.objects.count() == 0
        assert "DRY RUN" in out.getvalue()
