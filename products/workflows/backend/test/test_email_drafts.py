import json
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import httpx
from anthropic import APITimeoutError
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.token_bucket import BucketDecision

from products.access_control.backend.models.access_control import AccessControl
from products.cohorts.backend.models.cohort import Cohort
from products.early_access_features.backend.models import EarlyAccessFeature
from products.error_tracking.backend.facade.testing import create_issue
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.surveys.backend.models import Survey

SERVICE = "products.workflows.backend.services.email_draft"


def _model_reply(payload: Any) -> MagicMock:
    client = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.with_options.return_value.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)]
    )
    return client


class TestEmailDrafts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.sources: dict[str, str] = {
            "error_tracking": str(create_issue(team_id=self.team.id, name="TypeError: cart is undefined")),
            "early_access": str(
                EarlyAccessFeature.objects.create(
                    team=self.team, name="Dark mode", description="Use the app in dark colors.", stage="beta"
                ).id
            ),
            "survey": str(
                Survey.objects.create(
                    team=self.team,
                    name="Checkout NPS",
                    type="popover",
                    questions=[{"type": "rating", "question": "How likely are you to recommend us?"}],
                ).id
            ),
            "feature_flag": str(FeatureFlag.objects.create(team=self.team, key="new-checkout").id),
            "cohort": str(Cohort.objects.create(team=self.team, name="Churned trial users").id),
        }

    def _draft(self, source: str, source_id: str | None = None) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/workflow_email_drafts/",
            {"source": source, "source_id": source_id or self.sources[source]},
        )

    @parameterized.expand(
        [
            ("error_tracking", "We fixed an issue you ran into"),
            ("early_access", "Dark mode is now available"),
            ("survey", "Thanks for your feedback"),
            ("feature_flag", "Something new for you"),
            ("cohort", ""),
        ]
    )
    @patch(f"{SERVICE}._draft_flag_enabled", return_value=False)
    def test_returns_the_source_template_when_ai_drafts_are_off(self, source: str, subject: str, _flag) -> None:
        response = self._draft(source)

        assert response.status_code == 200, response.json()
        body = response.json()
        assert (body["subject"], body["generated_by"], body["template_reason"]) == (subject, "template", "flag_off")
        assert (body["html"] == "") == (source == "cohort")

    @patch(f"{SERVICE}._draft_flag_enabled", return_value=True)
    @patch(f"{SERVICE}.build_ai_gateway_anthropic_client")
    def test_model_draft_is_escaped_and_carries_the_source_as_data(self, build_client, _flag) -> None:
        client = _model_reply(
            {
                "subject": "Dark mode is here",
                "preheader": "You asked for it early.",
                "paragraphs": ["Hi there,\n\nDark mode <script>alert(1)</script> is ready."],
            }
        )
        build_client.return_value = client

        body = self._draft("early_access").json()

        assert body["generated_by"] == "ai" and body["template_reason"] is None
        assert body["html"] == "<p>Hi there,</p>\n<p>Dark mode &lt;script&gt;alert(1)&lt;/script&gt; is ready.</p>"
        assert body["text"] == "Hi there,\n\nDark mode <script>alert(1)</script> is ready."
        prompt = client.with_options.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "<source_data>\nFeature name: Dark mode\nFeature description: Use the app in dark colors." in prompt
        assert build_client.call_args.kwargs["ai_product"] == "workflows"

    @parameterized.expand(
        [
            ("ai_not_approved", {"approved": False}),
            ("gateway_unconfigured", {"build_error": GatewayNotConfiguredError("unset")}),
            ("timeout", {"call_error": APITimeoutError(httpx.Request("POST", "http://gateway"))}),
            ("model_error", {"call_error": RuntimeError("gateway 502")}),
            ("invalid_output", {"reply": "Sure! Here is your email."}),
            ("invalid_output", {"reply": {"subject": "Hi {{ person.name }}", "paragraphs": ["Hi there,"]}}),
            ("invalid_output", {"reply": {"subject": "x" * 121, "paragraphs": ["Hi there,"]}}),
            ("rate_limited", {"denied": True}),
        ]
    )
    @patch(f"{SERVICE}._draft_flag_enabled", return_value=True)
    @patch(f"{SERVICE}.build_ai_gateway_anthropic_client")
    @patch(f"{SERVICE}.consume")
    def test_falls_back_to_the_template(self, reason: str, case: dict, consume, build_client, _flag) -> None:
        self.organization.is_ai_data_processing_approved = case.get("approved", True)
        self.organization.save()
        consume.return_value = BucketDecision(
            allowed=not case.get("denied", False), remaining=0, limit=20, retry_after=180, reset=3600
        )
        client = _model_reply(case.get("reply", {"subject": "ok", "paragraphs": ["Hi there,"]}))
        if "call_error" in case:
            client.with_options.return_value.messages.create.side_effect = case["call_error"]
        build_client.return_value = client
        if "build_error" in case:
            build_client.side_effect = case["build_error"]

        body = self._draft("error_tracking").json()

        assert (body["generated_by"], body["template_reason"], body["subject"]) == (
            "template",
            reason,
            "We fixed an issue you ran into",
        )
        if reason in ("ai_not_approved", "rate_limited"):
            client.with_options.return_value.messages.create.assert_not_called()

    @parameterized.expand([("error_tracking",), ("early_access",), ("survey",), ("feature_flag",), ("cohort",)])
    def test_another_teams_source_is_not_found(self, source: str) -> None:
        other_team = Team.objects.create(organization=self.organization)

        response = self.client.post(
            f"/api/projects/{other_team.id}/workflow_email_drafts/",
            {"source": source, "source_id": self.sources[source]},
        )

        assert response.status_code == 404, response.json()

    @parameterized.expand(
        [
            ("error_tracking", "not-a-uuid"),
            ("cohort", "abc"),
            ("feature_flag", "²"),
            ("survey", "00000000-0000-0000-0000-000000000000"),
        ]
    )
    def test_unknown_source_id_is_not_found(self, source: str, source_id: str) -> None:
        assert self._draft(source, source_id).status_code == 404

    @parameterized.expand(
        [
            ("early_access", "early_access_feature"),
            ("survey", "survey"),
            ("feature_flag", "feature_flag"),
            ("cohort", "cohort"),
        ]
    )
    @patch(f"{SERVICE}._draft_flag_enabled", return_value=False)
    def test_a_source_restricted_for_this_member_is_forbidden(self, source: str, resource: str, _flag) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=self.sources[source],
            access_level="none",
            organization_member=self.organization_membership,
        )

        response = self._draft(source)

        assert response.status_code == 403, response.json()
        assert "subject" not in response.json()

    @parameterized.expand(
        [
            (["hog_flow:write"], 403),
            (["hog_flow:write", "early_access_feature:read"], 200),
        ]
    )
    @patch(f"{SERVICE}._draft_flag_enabled", return_value=False)
    def test_a_scoped_key_needs_read_access_to_the_source(self, scopes: list[str], status: int, _flag) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_email_drafts/",
            {"source": "early_access", "source_id": self.sources["early_access"]},
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == status, response.json()
