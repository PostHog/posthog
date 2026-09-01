from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.api.hog_flow import DRAFT_CONTENT_FIELDS
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_proposal import WorkflowProposal

webhook_template = MOCK_NODE_TEMPLATES[0]


def _trigger_action() -> dict:
    return {
        "id": "trigger_node",
        "name": "trigger_1",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
        },
    }


def _webhook_action(action_id: str = "action_1", url: str = "https://example.com") -> dict:
    return {
        "id": action_id,
        "name": action_id,
        "type": "function",
        "config": {"template_id": "template-webhook", "inputs": {"url": {"value": url}}},
    }


@patch("products.workflows.backend.api.hog_flow.posthoganalytics.feature_enabled", return_value=True)
class TestWorkflowProposals(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)

    def _create_active_flow(self) -> str:
        create = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Proposal Flow", "actions": [_trigger_action(), _webhook_action()]},
        )
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        activate = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert activate.status_code == 200, activate.json()
        return flow_id

    def _propose(self, flow_id: str, **overrides) -> dict:
        payload = {
            "title": "Point the webhook somewhere that answers",
            "rationale": "Every call to the current URL failed over the last week.",
            "content": {"actions": [_trigger_action(), _webhook_action(url="https://proposed.example.com")]},
            "evidence": {
                "metric": "failure rate",
                "current_value": 1.0,
                "target_value": 0.0,
                "window": "-7d",
                "n": 240,
                "guardrails": [{"metric": "complaint rate", "value": 0.0, "n": 240}],
            },
            "source_type": "scout",
            **overrides,
        }
        if "base_version" not in payload:
            live = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}")
            payload["base_version"] = live.json()["version"]
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/", payload, format="json"
        )
        assert response.status_code == 201, response.json()
        return response.json()

    def _publish(self, flow_id: str):
        with patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count") as mock_count:
            mock_count.return_value = MagicMock(
                status_code=200, json=lambda: {"count": 0, "by_action": {}, "position_unknown": 0}
            )
            preview = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert preview.status_code == 200, preview.json()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
        )
        assert response.status_code == 200, response.json()
        return response

    def test_approve_stages_a_full_draft_and_leaves_live_alone(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "approved"

        flow = HogFlow.objects.get(id=flow_id)
        # The live config is untouched: an approval can only ever stage.
        assert flow.actions[1]["config"]["inputs"]["url"]["value"] == "https://example.com"
        assert flow.version == 1
        # The staged draft is a whole-content snapshot (live as the base, the proposal on top), which
        # is what publish's plain copy needs — a partial draft would drop the rest of the workflow.
        draft = flow.draft
        assert draft is not None
        assert set(draft.keys()) == set(DRAFT_CONTENT_FIELDS)
        assert draft["actions"][1]["config"]["inputs"]["url"]["value"] == "https://proposed.example.com"

    def test_publish_marks_the_approved_proposal_applied(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {})

        self._publish(flow_id)

        stored = WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"])
        assert stored.status == "applied"
        assert stored.applied_version == HogFlow.objects.get(id=flow_id).version == 2

    def test_only_the_suggestion_still_staged_is_recorded_as_applied(self, _mock_flag):
        flow_id = self._create_active_flow()
        first = self._propose(flow_id, source_id="stub:first")
        second = self._propose(
            flow_id,
            source_id="stub:second",
            content={"actions": [_trigger_action(), _webhook_action(url="https://second.example.com")]},
        )

        self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{first['id']}/approve/", {})
        approve_second = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{second['id']}/approve/", {"overwrite": True}
        )
        assert approve_second.status_code == 200, approve_second.json()

        self._publish(flow_id)

        # The second approval replaced the first one's content in the draft, so only the second went
        # live. Recording both as applied would give the first a measured outcome it never earned.
        assert WorkflowProposal.objects.for_team(self.team.id).get(id=second["id"]).status == "applied"
        replaced = WorkflowProposal.objects.for_team(self.team.id).get(id=first["id"])
        assert replaced.status == "suggested"
        assert replaced.applied_version is None
        assert HogFlow.objects.get(id=flow_id).actions[1]["config"]["inputs"]["url"]["value"] == (
            "https://second.example.com"
        )

    def test_discarding_the_draft_returns_the_suggestion_to_the_queue(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {})

        discard = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/discard_draft", {})
        assert discard.status_code == 200, discard.json()

        stored = WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"])
        assert stored.status == "suggested"
        assert stored.resolved_at is None

        # An unrelated later publish must not adopt it: its change was never in that draft.
        self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed"}}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        self._publish(flow_id)
        assert WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"]).status == "suggested"

    @parameterized.expand([("actions",), ("variables",)])
    def test_a_suggestion_older_than_the_live_workflow_is_refused_for_whole_list_fields(self, _mock_flag, field: str):
        # Both fields are whole lists, so a stale copy of either drops whatever was added since —
        # `variables` reads like a single setting but behaves like `actions`.
        flow_id = self._create_active_flow()
        content = (
            {"actions": [_trigger_action(), _webhook_action(url="https://proposed.example.com")]}
            if field == "actions"
            else {"variables": [{"key": "greeting", "type": "string", "default": "hi"}]}
        )
        proposal = self._propose(flow_id, content=content, source_id=f"stale:{field}")
        self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed"}}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        self._publish(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {"overwrite": True}
        )

        assert response.status_code == 409, response.json()
        assert response.json()["code"] == "proposal_out_of_date"
        assert HogFlow.objects.get(id=flow_id).draft is None

    def test_a_suggestion_older_than_the_live_workflow_is_refused(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        # Someone publishes a step change after the suggestion was written. Its action list is now the
        # older shape, so staging it would drop that edit.
        self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed"}}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        self._publish(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {"overwrite": True}
        )
        assert response.status_code == 409, response.json()
        assert response.json()["code"] == "proposal_out_of_date"
        assert WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"]).status == "suggested"
        assert HogFlow.objects.get(id=flow_id).draft is None

    def test_provenance_comes_from_the_transport_not_the_payload(self, _mock_flag):
        flow_id = self._create_active_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {
                "title": "Self-labelled as a human edit",
                "rationale": "A caller must not be able to pass its own work off as someone else's.",
                "content": {"actions": [_trigger_action(), _webhook_action()]},
                "base_version": 1,
                "source_type": "scout",
                "created_via": "web",
            },
            format="json",
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["created_via"] == "mcp"

    def test_repeat_source_id_returns_the_same_proposal(self, _mock_flag):
        flow_id = self._create_active_flow()
        first = self._propose(flow_id, source_id="run:1:finding:webhook-url")

        again = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {
                "title": "Retry of the same finding",
                "rationale": "A retried agent run must not queue a second copy for the human.",
                "content": {"actions": [_trigger_action(), _webhook_action()]},
                "base_version": 1,
                "source_type": "scout",
                "source_id": "run:1:finding:webhook-url",
            },
            format="json",
        )
        assert again.status_code == 200, again.json()
        assert again.json()["id"] == first["id"]
        assert WorkflowProposal.objects.for_team(self.team.id).filter(hog_flow_id=flow_id).count() == 1

    @parameterized.expand(
        [
            ("no sample size", {"metric": "email open rate", "current_value": 0.07, "guardrails": []}, "`n`"),
            (
                "no counter-metrics",
                {"metric": "email open rate", "current_value": 0.07, "n": 120},
                "guardrails",
            ),
            (
                "rate under the producer's own key",
                {"metric": "email open rate", "current_open_rate": "8.65%", "n": 208, "guardrails": []},
                "current_value",
            ),
        ]
    )
    def test_a_rate_the_panel_cannot_read_back_is_refused(self, _mock_flag, _name: str, evidence: dict, expected: str):
        # The loop's two worst failures are declaring a win off twenty sends and lifting one metric
        # while harming another. Both are refused at the seam rather than left to a producer's prompt.
        flow_id = self._create_active_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {
                "title": "Shorten the subject",
                "rationale": "Testing the evidence contract.",
                "content": {"actions": [_trigger_action(), _webhook_action()]},
                "evidence": evidence,
                "source_type": "scout",
            },
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert expected in str(response.json())

    def test_evidence_with_a_denominator_and_guardrails_is_accepted(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(
            flow_id,
            evidence={
                "metric": "email open rate",
                "current_value": 0.07,
                "n": 120,
                "guardrails": [{"metric": "complaint rate", "value": 0.001, "n": 120}],
            },
        )
        assert proposal["evidence"]["guardrails"][0]["metric"] == "complaint rate"

    def test_the_outcome_reads_the_step_the_suggestion_named(self, _mock_flag):
        # A workflow with several email steps would otherwise measure a change to one of them against
        # the sends of all of them, diluting a real move and attributing an unrelated one.
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id, step_id="action_1")
        self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {})
        self._publish(flow_id)

        with patch("products.workflows.backend.api.hog_flow.fetch_app_metric_totals") as mock_totals:
            mock_totals.return_value = SimpleNamespace(totals={})
            response = self.client.get(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/outcome"
            )

        assert response.status_code == 200, response.json()
        assert {call.kwargs["instance_id"] for call in mock_totals.call_args_list} == {"action_1"}

    def test_outcome_reports_both_versions_with_their_sample_sizes(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {})
        self._publish(flow_id)

        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/outcome"
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        # Before is the version proposed against, after is the version it went live as, so a reader
        # cannot accidentally compare a version against itself.
        assert body["before"]["version"] == 1
        assert body["after"]["version"] == 2
        assert body["after"]["target"]["n"] == 0
        assert body["after"]["target"]["below_minimum_sample"] is True
        # Opens and clicks move for different reasons — a subject line gets a message opened, the body
        # gets it clicked — so a suggestion that lifts one and flattens the other has to be visible.
        assert body["after"]["click_through"]["metric"] == "click rate"
        assert body["after"]["click_through"]["n"] == body["after"]["target"]["n"]
        assert [guardrail["metric"] for guardrail in body["after"]["guardrails"]] == [
            "complaint rate",
            "bounce rate",
        ]
        assert body["unavailable_guardrails"] == ["unsubscribe rate"]

    def test_an_api_key_can_read_the_outcome_of_what_it_proposed(self, _mock_flag):
        # The producer is an agent authenticating with a personal API key, so every endpoint it needs
        # has to declare a scope. An action missing from the scope lists is rejected before it runs,
        # whatever scopes the key holds.
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {})
        self._publish(flow_id)

        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="scout", user=self.user, secure_value=hash_key_value(value), scopes=["hog_flow:read"]
        )
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/outcome",
            headers={"authorization": f"Bearer {value}"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["after"]["version"] == 2

    def test_a_partial_action_list_is_refused(self, _mock_flag):
        flow_id = self._create_active_flow()
        # `actions` replaces the live list, so a caller that sends only the step it edited would stage a
        # draft with the trigger deleted — and the human reviewing the suggestion cannot see what is gone.
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {
                "title": "Only the step I touched",
                "rationale": "A truncated action list must not reach a draft.",
                "content": {"actions": [_webhook_action(url="https://proposed.example.com")]},
                "base_version": 1,
                "source_type": "scout",
            },
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert "replace the whole list" in str(response.json())
        assert WorkflowProposal.objects.for_team(self.team.id).filter(hog_flow_id=flow_id).count() == 0

    @parameterized.expand([("approve",), ("reject",)])
    def test_resolving_twice_is_refused(self, _mock_flag, action: str):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        url = f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/{action}/"

        assert self.client.post(url, {}).status_code == 200
        second = self.client.post(url, {})
        assert second.status_code == 409, second.json()
        assert second.json()["code"] == "proposal_already_resolved"

    def test_approving_over_a_staged_draft_needs_the_draft_stamp_it_saw(self, _mock_flag):
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        # A draft staged after the confirmation dialog opened must not be silently overwritten.
        staged = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed"}}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert staged.status_code == 200, staged.json()

        url = f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/"
        assert self.client.post(url, {}).json()["code"] == "draft_exists"
        stale = self.client.post(url, {"overwrite": True, "expected_draft_updated_at": "2020-01-01T00:00:00Z"})
        assert stale.status_code == 409, stale.json()
        assert WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"]).status == "suggested"

    def test_a_whole_list_proposal_must_say_which_version_it_read(self, _mock_flag):
        # Without it the row records the version at create time, so a producer that took its time
        # looks current and the approve-time staleness guard never fires.
        flow_id = self._create_active_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {
                "title": "Point the webhook somewhere else",
                "rationale": "Testing the version contract.",
                "content": {"actions": [_trigger_action(), _webhook_action()]},
                "source_type": "scout",
            },
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert "base_version" in str(response.json())

    @parameterized.expand(
        [
            ("read-only trigger", {"trigger": {"type": "event"}}, "Unknown content field"),
            ("read-only abort action", {"abort_action": "action_1"}, "Unknown content field"),
            ("actions holding a string", {"actions": ["oops"]}, "list of objects"),
            ("actions that are not a list", {"actions": "oops"}, "list of objects"),
            ("edges holding a string", {"edges": ["oops"]}, "list of objects"),
        ]
    )
    def test_content_the_publish_path_cannot_carry_is_refused(
        self, _mock_flag, _name: str, content: dict, expected: str
    ):
        # Each of these used to reach the graph validator or the secret stripper, which read every
        # item as a mapping and answered a bad request with a 500.
        flow_id = self._create_active_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {
                "title": "Change something publish would drop",
                "rationale": "Testing the content contract.",
                "content": content,
                "base_version": 1,
                "source_type": "scout",
            },
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert expected in str(response.json())

    def test_editing_the_draft_returns_the_approved_suggestion_to_the_queue(self, _mock_flag):
        # Approved means "this suggestion is what sits in the draft". An edit over that draft can
        # undo the change, and publish reads approved as shipped, so the edit hands the decision back.
        flow_id = self._create_active_flow()
        proposal = self._propose(flow_id)
        approve = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/{proposal['id']}/approve/", {}
        )
        assert approve.status_code == 200, approve.json()

        edit = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": [_trigger_action(), _webhook_action(url="https://edited.example.com")],
                "stage_draft": True,
            },
            format="json",
        )
        assert edit.status_code == 200, edit.json()

        assert (
            WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"]).status
            == WorkflowProposal.Status.SUGGESTED
        )

        self._publish(flow_id)
        applied = WorkflowProposal.objects.for_team(self.team.id).get(id=proposal["id"])
        assert applied.status == WorkflowProposal.Status.SUGGESTED
        assert applied.applied_version is None

    def test_applied_suggestions_are_listed_by_the_version_that_carried_them(self, _mock_flag):
        # Apply order follows the version that shipped a suggestion, not when it was written: a
        # suggestion approved after later-written ones ships last. The panel reads only the newest
        # few applied, so creation order would hide the change that shipped most recently.
        flow_id = self._create_active_flow()
        flow = HogFlow.objects.get(id=flow_id)
        written_first = WorkflowProposal(
            hog_flow=flow,
            team=self.team,
            title="Written first, shipped last",
            rationale="Approved after the other one had already shipped.",
            content={"exit_condition": "exit_on_conversion"},
            base_version=1,
            status=WorkflowProposal.Status.APPLIED,
            applied_version=3,
            source_type=WorkflowProposal.SourceType.SCOUT,
            created_via=WorkflowProposal.CreatedVia.MCP,
        )
        written_first.save()
        written_last = WorkflowProposal(
            hog_flow=flow,
            team=self.team,
            title="Written last, shipped first",
            rationale="Approved and published before the other one.",
            content={"exit_condition": "exit_on_conversion"},
            base_version=1,
            status=WorkflowProposal.Status.APPLIED,
            applied_version=2,
            source_type=WorkflowProposal.SourceType.SCOUT,
            created_via=WorkflowProposal.CreatedVia.MCP,
        )
        written_last.save()

        listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/?status=applied&limit=1")
        assert listed.status_code == 200, listed.json()
        assert [row["id"] for row in listed.json()["results"]] == [str(written_first.id)]


@patch("products.workflows.backend.api.hog_flow.posthoganalytics.feature_enabled", return_value=False)
class TestWorkflowProposalsFlagOff(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)

    def test_the_surface_does_not_exist_without_the_flag(self, _mock_flag):
        create = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Proposal Flow", "actions": [_trigger_action(), _webhook_action()]},
        )
        flow_id = create.json()["id"]

        listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/")
        assert listed.status_code == 404, listed.json()
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/proposals/",
            {"title": "x", "rationale": "y", "content": {"actions": []}, "source_type": "scout"},
            format="json",
        )
        assert created.status_code == 404, created.json()


class TestWorkflowProposalModel(APIBaseTest):
    def test_team_is_mirrored_from_the_workflow(self):
        flow = HogFlow.objects.create(team=self.team, name="Scoped flow")
        other_team = self.organization.teams.create(name="Other team")

        proposal = WorkflowProposal(
            hog_flow=flow,
            team=other_team,
            title="Wrong team on the way in",
            rationale="Fail-closed reads filter on this row's team, so it has to match the workflow's.",
            content={"actions": []},
            base_version=1,
            source_type=WorkflowProposal.SourceType.SCOUT,
            created_via=WorkflowProposal.CreatedVia.MCP,
        )
        proposal.save()

        assert proposal.team_id == self.team.id
        assert WorkflowProposal.objects.for_team(other_team.id).filter(id=proposal.id).count() == 0
