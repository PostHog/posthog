import json
from datetime import timedelta
from hashlib import sha256
from urllib.parse import urldefrag

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import Client
from django.utils import timezone

from parameterized import parameterized

from posthog.api.advanced_activity_logs import ActivityLogSerializer
from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.file_system.file_system import FileSystem
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget

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

    def test_admin_can_identify_live_audiences_without_exposing_signed_urls(self) -> None:
        self.issue("Coast")
        self.issue("Grove")
        audiences = NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release)
        coast = audiences.get(tenant_value="Coast")
        audiences.filter(tenant_value="Grove").update(expires_at=timezone.now() - timedelta(seconds=1))
        inventory = self.management + "active/"
        response = self.client.get(inventory)
        assert response.status_code == 200, response.content
        rows = response.json()
        assert len(rows) == 1
        assert rows[0] == {
            "embed_id": str(coast.pk),
            "origin": "https://portal.example.com",
            "tenant_column": "workspace_id",
            "tenant_value": "Coast",
            "revision": 1,
            "expires_at": rows[0]["expires_at"],
        }
        assert rows[0]["expires_at"]
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        assert self.client.get(inventory).status_code == 403

    def test_sharing_history_records_embed_changes_with_their_actor(self) -> None:
        self.issue("coast")
        embed = NotebookAppEmbed.objects.for_team(self.team.pk).get(release=self.release)
        expected_digest = sha256(b"coast").hexdigest()
        metadata = {
            "embed_id": str(embed.pk),
            "origin": "https://portal.example.com",
            "tenant_column": "workspace_id",
            "tenant_sha256": expected_digest,
            "revision": self.release.revision,
            "expires_at": embed.expires_at.isoformat(),
        }
        with patch("products.notebooks.backend.presentation.views.notebook.is_impersonated", return_value=True):
            self.issue("coast")
        embed.refresh_from_db()
        replaced = {**metadata, "expires_at": embed.expires_at.isoformat()}
        revoke = {**self.configuration("coast"), "revoke": True}
        assert self.client.post(self.management, revoke, format="json").status_code == 200
        assert self.client.post(self.management, revoke, format="json").status_code == 404
        records = ActivityLog.objects.filter(
            team_id=self.team.pk,
            scope="Notebook",
            item_id=self.notebook.short_id,
            detail__contains={"changes": [{"field": "app_embed"}]},
        ).order_by("created_at", "id")
        actual = [
            (row.user_id, row.was_impersonated, change["action"], change.get("before"), change.get("after"))
            for row in records
            if isinstance(row.detail, dict)
            for change in row.detail["changes"]
        ]
        assert actual == [
            (self.user.pk, False, "created", None, metadata),
            (self.user.pk, True, "changed", None, replaced),
            (self.user.pk, False, "deleted", replaced, None),
        ]
        for record, action in zip(records, ("created", "changed", "deleted"), strict=True):
            summary = ActivityLogSerializer.for_internal_event(record)
            assert summary is not None
            assert summary["id"] == str(record.pk)
            assert summary["detail"] == {"changes": [{"field": "app_embed", "action": action}]}
            assert "item_id" not in summary
        notebook_url = f"/api/projects/{self.team.pk}/notebooks/"
        notebook_detail = f"{notebook_url}{self.notebook.short_id}/"
        notebook_history = notebook_detail + "activity/"
        detail = self.client.get(notebook_history)
        self.assertContains(detail, str(embed.pk))
        self.assertContains(detail, expected_digest)
        team_feed = f"{notebook_url}activity/"
        self.assertContains(self.client.get(team_feed), expected_digest)

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        assert self.client.get(notebook_detail).status_code == 200
        for path in (team_feed, notebook_history):
            detail = self.client.get(path)
            self.assertNotContains(detail, "app_embed")
            self.assertNotContains(detail, expected_digest)
            self.assertNotContains(detail, embed.origin)

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

    def test_older_snapshot_reopens_from_its_pinned_release_for_the_signed_tenant(self) -> None:
        path, token = self.issue("coast")
        old_tabs = [{"title": "Old view", "blocks": [{"text": "Previous projection"}]}]
        for snapshot in [old_tabs, {"version": 1, "tabs": old_tabs}]:
            with self.subTest(snapshot=snapshot):
                NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release).update(snapshot=snapshot)
                output = self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe")
                self.assertContains(output, "Tide pools")
                self.assertNotContains(output, "Previous projection")
                self.assertNotContains(output, "Orchard")

    def test_wrapped_table_only_embeds_published_columns_for_the_selected_tenant(self) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        query = {
            "kind": "DataVisualizationNode",
            "source": {"kind": "HogQLQuery", "query": "SELECT private_source"},
            "display": "ActionsTable",
            "tableSettings": {"columns": [{"column": "Sessions"}]},
        }
        self.release.markdown = f'<SQLV2 nodeId="usage" runId="{run_id}" query={{{json.dumps(query)}}} />'
        self.release.save(update_fields=["markdown"])
        path, token = self.issue("grove")
        output = self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe")
        self.assertContains(output, "<td>93</td>", html=True)
        for hidden in ("workspace_id", "Orchard study", "Canopy watch", "<td>128</td>"):
            self.assertNotContains(output, hidden)

    def test_embed_requires_a_chart_with_shareable_output(self) -> None:
        self.release.markdown = self.release.markdown.replace(
            'outputTab="results"', 'vizQuery={{"display":"ActionsPie"}}'
        )
        self.release.save(update_fields=["markdown"])
        response = self.client.post(self.management, self.configuration("grove"), format="json")
        assert response.status_code == 400
        assert not NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release).exists()

    def test_issuing_an_oversized_audience_leaves_the_previous_code_active(self) -> None:
        path, token = self.issue("coast")
        with patch("products.notebooks.backend.app_embeds.MAX_EMBED_SNAPSHOT_BYTES", 15):
            response = self.client.post(self.management, self.configuration("coast"), format="json")
        assert response.status_code == 400
        self.assertContains(self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe"), "Tide pools")

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

    @parameterized.expand([("unpublish",), ("project_tree",)])
    def test_withdrawing_a_notebook_permanently_revokes_issued_embeds(self, surface: str) -> None:
        path, token = self.issue("coast")
        url = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/"
        if surface == "unpublish":
            response = self.client.patch(
                url, {"app_revision": self.notebook.app_revision, "app_published": None}, format="json"
            )
        else:
            file, _ = FileSystem.objects.get_or_create(
                team=self.team,
                type="notebook",
                ref=self.notebook.short_id,
                defaults={"path": "Weekly review", "depth": 1},
            )
            response = self.client.delete(f"/api/projects/{self.team.pk}/file_system/{file.pk}/")
        assert response.status_code == 200, response.content
        assert not NotebookAppEmbed.objects.for_team(self.team.pk).filter(release=self.release).exists()
        assert ActivityLog.objects.filter(
            team_id=self.team.pk,
            user=self.user,
            scope="Notebook",
            item_id=self.notebook.short_id,
            detail__contains={"changes": [{"field": "app_embed", "action": "deleted"}]},
        ).exists()
        self.notebook.refresh_from_db()
        new_layout = {
            "tabs": [{"id": "note", "title": "Notes"}],
            "blocks": [{"id": "text", "tab_id": "note", "kind": "text", "text": "Updated report"}],
        }
        data = (
            {"app_revision": self.notebook.app_revision, "app_published": new_layout}
            if surface == "unpublish"
            else {"deleted": False}
        )
        response = self.client.patch(url, data, format="json")
        assert response.status_code == 200, response.content
        assert self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe").status_code == 404

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
        with patch("products.notebooks.backend.app_embeds.VERIFIED_VIEW_BUDGET", Budget(burst=1, per_hour=1)):
            assert self.public.get(path).status_code == 200
            assert self.public.get(path).status_code == 200
            assert self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe").status_code == 200
            limited = self.public.post(path, {"token": token}, HTTP_SEC_FETCH_DEST="iframe")
            assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
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
