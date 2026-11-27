from datetime import timedelta
from urllib.parse import urldefrag

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import Client
from django.utils import timezone

from posthog.models import OrganizationMembership
from posthog.token_bucket import BucketDecision, BucketUnavailable

from products.notebooks.backend.app_release_results import capture_published_sql_rows
from products.notebooks.backend.models import Notebook, NotebookAppEmbed, NotebookAppRelease, NotebookNodeRun
from products.notebooks.backend.tasks.app_embeds import cleanup_expired_app_embeds


class TestNotebookAppEmbeds(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch(
                "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled",
                return_value=True,
            )
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        layout = {
            "tabs": [{"id": "activity", "title": "Weekly activity"}, {"id": "notes", "title": "Methodology"}],
            "blocks": [
                {"id": "report", "kind": "cell", "node_id": "usage", "tab_id": "activity", "title": "Project activity"},
                {"id": "note", "kind": "text", "tab_id": "notes", "text": "Counts include completed sessions."},
            ],
            "description": "Active projects and completed sessions in the last seven days.",
        }
        result = {
            "columns": ["workspace_id", "Project", "Sessions"],
            "first_page": [
                ["coast", "Tide pools", 128],
                ["grove", "Orchard study", 93],
                ["coast", "Harbor survey", 74],
                ["grove", "Canopy watch", 62],
            ],
        }
        self.notebook = Notebook.objects.create(team=self.team, title="Project activity report", app_published=layout)
        run = NotebookNodeRun.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            node_id="usage",
            node_type="hogql",
            status="done",
            code="SELECT private_source",
            envelope=result,
        )
        markdown = f'<SQLV2 nodeId="usage" code="SELECT private_source" runId="{run.pk}" outputTab="results" />'
        self.release = NotebookAppRelease.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            revision=1,
            title="Project activity report",
            layout=layout,
            markdown=markdown,
            sql_rows=capture_published_sql_rows(self.notebook, markdown, layout),
        )
        self.management = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/app_embeds/"
        self.public = Client(enforce_csrf_checks=True)

    def configuration(self, tenant: str) -> dict[str, str | int]:
        return {
            "origin": "https://portal.example.com",
            "tenant_column": "workspace_id",
            "tenant_value": tenant,
            "revision": self.release.revision,
        }

    def issue(self, tenant: str) -> tuple[str, str]:
        response = self.client.post(self.management, self.configuration(tenant), format="json")
        assert response.status_code == 200, response.content
        return urldefrag(response.json()["url"])

    def test_stale_release_cannot_be_shared_and_expired_audiences_release_capacity(self) -> None:
        stale = {**self.configuration("coast"), "revision": self.release.revision + 1}
        denied = self.client.post(self.management, stale, format="json")
        assert denied.status_code == 400 and denied.json()["attr"] == "revision"
        with patch("products.notebooks.backend.app_embeds.MAX_PROJECT_AUDIENCES", 1):
            self.issue("coast")
            NotebookAppEmbed.objects.for_team(self.team.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
            self.issue("grove")

    def test_tenant_outputs_stay_disjoint_at_one_site(self) -> None:
        coast, coast_token = self.issue("coast")
        grove, grove_token = self.issue("grove")
        shell = self.public.get(coast)
        self.assertNotContains(shell, "Tide pools")
        assert "frame-ancestors https://portal.example.com" in shell.headers["Content-Security-Policy"]
        assert "X-Frame-Options" not in shell.headers
        a = self.public.post(coast, {"token": coast_token, "tenant_value": "grove"}, HTTP_SEC_FETCH_DEST="iframe")
        b = self.public.post(grove, {"token": grove_token}, HTTP_SEC_FETCH_DEST="iframe")
        self.assertContains(a, "Tide pools")
        self.assertContains(b, "Orchard study")
        for value in ("Orchard study", "workspace_id", "private_source"):
            self.assertNotContains(a, value)
        self.assertNotContains(b, "Tide pools")
        assert self.public.post(grove, {"token": coast_token}, HTTP_SEC_FETCH_DEST="iframe").status_code == 404
        assert self.public.post(coast, {"token": coast_token}, HTTP_SEC_FETCH_DEST="document").status_code == 404
        assert self.public.get(coast.replace(f"/embed/{self.team.pk}/", "/embed/999999/")).status_code == 404

    def test_single_number_shares_only_the_first_matching_tenant_value(self) -> None:
        self.release.markdown = self.release.markdown.replace(
            'outputTab="results"',
            'vizQuery={{"display":"BoldNumber","tableSettings":{"columns":[{"column":"Sessions"}]}}}',
        )
        self.release.save(update_fields=["markdown"])
        path, token = self.issue("grove")
        result = self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe")
        self.assertContains(result, "<td>93</td>", html=True)
        for hidden in ("<td>128</td>", "<td>62</td>", "Orchard study", "workspace_id"):
            self.assertNotContains(result, hidden)

    def test_reissue_expiry_revocation_and_organization_policy(self) -> None:
        path, old = self.issue("coast")
        _, current = self.issue("coast")
        assert self.public.post(path, {"token": old}, HTTP_SEC_FETCH_DEST="iframe").status_code == 404
        assert self.public.post(path, {"token": current}, HTTP_SEC_FETCH_DEST="iframe").status_code == 200
        NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert self.public.get(path).status_code == 404
        self.issue("coast")
        self.organization.allow_publicly_shared_resources = False
        self.organization.save()
        assert self.public.get(path).status_code == 404
        assert self.client.post(self.management, self.configuration("grove"), format="json").status_code == 403
        assert (
            self.client.post(
                self.management, {**self.configuration("coast"), "revoke": True}, format="json"
            ).status_code
            == 200
        )
        assert not NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release).exists()

    def test_tenant_rows_after_the_preview_and_incomplete_releases(self) -> None:
        self.release.markdown = '<SQLV2 nodeId="usage" code="SELECT 1" runId="retained" outputTab="results" result={{"columns":["workspace_id","project"],"first_page":[["grove","Grove survey"]],"has_more":true,"row_count":2}} />'
        self.release.sql_rows = {
            "retained": [["grove", "Grove survey"], ["coast", "Tidal survey"]],
            "schema:retained": {"node_id": "usage", "columns": ["workspace_id", "project"], "row_count": 2},
        }
        self.release.save(update_fields=["markdown", "sql_rows"])
        path, token = self.issue("coast")
        output = self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe")
        self.assertContains(output, "Tidal survey")
        self.assertNotContains(output, "Grove survey")
        self.release.sql_rows = {}
        self.release.save(update_fields=["sql_rows"])
        response = self.client.post(self.management, self.configuration("coast"), format="json")
        assert response.status_code == 400
        self.assertContains(response, "complete SQL results", status_code=400)

    def test_unicode_tenant_redeems_within_the_size_limit(self) -> None:
        path, token = self.issue("🌲" * 256)
        assert len(token) <= 4096
        assert self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe").status_code == 200

    def test_audience_limit_allows_renewal_and_expired_rows_are_removed(self) -> None:
        self.issue("coast")
        with patch("products.notebooks.backend.app_embeds.MAX_PROJECT_AUDIENCES", 1):
            self.issue("coast")
            response = self.client.post(self.management, self.configuration("grove"), format="json")
            assert response.status_code == 400
        self.issue("grove")
        audiences = NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release)
        audiences.filter(tenant_value="grove").update(expires_at=timezone.now() - timedelta(seconds=1))
        cleanup_expired_app_embeds()
        assert list(audiences.values_list("tenant_value", flat=True)) == ["coast"]

    def test_restricted_requests_leave_existing_audiences_revocable(self) -> None:
        path, token = self.issue("coast")
        denied = BucketDecision(allowed=False, remaining=0, limit=1, retry_after=12, reset=12)
        with patch("products.notebooks.backend.presentation.app_embeds.consume", return_value=denied):
            assert self.public.get(path).status_code == 429
            response = self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe")
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "12"
        with patch(
            "products.notebooks.backend.presentation.app_embeds.consume",
            return_value=BucketUnavailable(error="unavailable"),
        ):
            assert self.public.get(path).status_code == 503
        with patch("products.notebooks.backend.app_embeds.consume", return_value=denied):
            assert self.client.post(self.management, self.configuration("grove"), format="json").status_code == 429
            revoked = self.client.post(self.management, {**self.configuration("coast"), "revoke": True}, format="json")
            assert revoked.status_code == 200

    def test_audience_budget_counts_authenticated_renders_and_issuance_requires_capacity(self) -> None:
        path, token = self.issue("coast")
        with patch("products.notebooks.backend.app_embeds.require_capacity") as capacity:
            self.public.get(path)
            capacity.assert_not_called()
            assert self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe").status_code == 200
            capacity.assert_called_once()
        with patch(
            "products.notebooks.backend.app_embeds.consume", return_value=BucketUnavailable(error="unavailable")
        ):
            response = self.client.post(self.management, self.configuration("grove"), format="json")
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "5"

    def test_risk_flagged_session_can_revoke_but_must_reauthenticate_to_issue(self) -> None:
        self.issue("coast")
        session = self.client.session
        session[settings.SESSION_STEP_UP_REQUIRED_KEY] = True
        session.save()
        response = self.client.post(self.management, self.configuration("grove"), format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "sensitive_action_required_reauth"
        response = self.client.post(self.management, {**self.configuration("coast"), "revoke": True}, format="json")
        assert response.status_code == 200

    def test_missing_tenant_column_and_invalid_audience_are_rejected(self) -> None:
        for override in (
            {"origin": "https://*.example.com"},
            {"origin": "https://[2001:db8::1]"},
            {"origin": "https://portal.example.com/a"},
            {"tenant_column": "missing"},
        ):
            response = self.client.post(self.management, {**self.configuration("coast"), **override}, format="json")
            assert response.status_code == 400
        assert not NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release).exists()
