import json
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.token_bucket import BucketDecision

from products.access_control.backend.facade.testing import create_access_control
from products.notebooks.backend.app_release_results import capture_published_sql_rows
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookAppViewGrant, NotebookNodeRun


class TestNotebookAppViewAccess(APIBaseTest):
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
        self.recipient = User.objects.create_and_join(self.organization, "viewer@example.com", None)
        layout = {
            "tabs": [{"id": "overview", "title": "Overview"}, {"id": "notes", "title": "Methodology"}],
            "blocks": [
                {"id": "summary", "kind": "cell", "tab_id": "overview", "node_id": "totals", "title": "Weekly signups"},
                {"id": "instructions", "kind": "text", "tab_id": "notes", "text": "Counts include completed signups."},
            ],
        }
        self.notebook = Notebook.objects.create(team=self.team, title="Weekly activation", app_published=layout)
        run = NotebookNodeRun.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            node_id="totals",
            node_type="hogql",
            status="done",
            code="SELECT private_source",
            envelope={"columns": ["Week", "Signups"], "first_page": [["Oct 12", 222]]},
        )
        markdown = f'Private notes\n\n<SQLV2 nodeId="totals" code="SELECT private_source" runId="{run.pk}" outputTab="results" />'
        self.release = NotebookAppRelease.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            revision=1,
            title="Weekly activation",
            layout=layout,
            markdown=markdown,
            sql_rows=capture_published_sql_rows(self.notebook, markdown, layout),
            variables=[{"name": "hidden", "type": "string", "value": "private default"}],
        )
        self.management = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/app_view_grants/"

    def grant(self) -> str:
        response = self.client.post(
            self.management, {"email": self.recipient.email.upper(), "revision": self.release.revision}, format="json"
        )
        assert response.status_code == 200, response.content
        return response.json()["url"]

    def test_only_the_current_project_member_receives_the_pinned_output(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        create_access_control(
            team_id=self.team.pk, resource="notebook", resource_id=str(self.notebook.pk), access_level="none"
        )
        url = self.grant()
        assert self.client.get(url).status_code == 404
        self.client.force_login(self.recipient)
        source_url = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/"
        assert self.client.get(source_url).status_code in (403, 404)
        output = self.client.get(url)
        self.assertContains(output, "222")
        for private in ("private_source", "Private notes", "private default", "Open notebook"):
            self.assertNotContains(output, private)
        self.assertContains(self.client.get(url + "?tab=1"), "Counts include completed signups.")
        assert self.client.get(url.replace(f"/apps/{self.team.pk}/", f"/apps/{self.team.pk + 1}/")).status_code == 404
        assert self.client.post(self.management, {"email": self.user.email}, format="json").status_code == 403
        self.recipient.organization_memberships.all().delete()
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])
        assert self.client.get(url).status_code == 404

    def test_expiry_revoke_and_unpublish_stop_existing_links(self) -> None:
        url = self.grant()
        NotebookAppViewGrant.objects.for_team(self.team.pk).filter(release=self.release).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.recipient)
        assert self.client.get(url).status_code == 404
        self.client.force_login(self.user)
        assert self.grant() == url
        self.notebook.app_published = None
        self.notebook.save()
        self.client.force_login(self.recipient)
        assert self.client.get(url).status_code == 404
        self.client.force_login(self.user)
        response = self.client.post(self.management, {"email": self.recipient.email, "revoke": True}, format="json")
        assert response.status_code == 200
        assert not NotebookAppViewGrant.objects.for_team(self.team.pk).filter(release=self.release).exists()
        events = ActivityLog.objects.filter(team_id=self.team.pk, scope="Notebook", item_id=self.notebook.short_id)
        details = [
            change
            for detail in events.values_list("detail", flat=True)
            if isinstance(detail, dict)
            for change in detail.get("changes", [])
            if change["field"] == "app_view_grant"
        ]
        assert any(change.get("after") == {"recipient": self.recipient.email, "revision": 1} for change in details)
        assert any(change.get("before") == {"recipient": self.recipient.email, "revision": 1} for change in details)

    def test_admin_can_find_and_revoke_a_member_after_their_email_changes(self) -> None:
        url = self.grant()
        self.recipient.email = "renamed@example.com"
        self.recipient.save(update_fields=["email"])
        response = self.client.get(self.management + "active/")
        assert response.status_code == 200, response.content
        grants = response.json()["results"]
        assert len(grants) == 1
        assert grants[0]["email"] == self.recipient.email
        request = {"recipient_uuid": grants[0]["recipient_uuid"], "revoke": True}
        assert self.client.post(self.management, request, format="json").status_code == 200
        assert self.client.post(self.management, request, format="json").status_code == 404
        self.client.force_login(self.recipient)
        assert self.client.get(url).status_code == 404
        assert self.client.get(self.management + "active/").status_code == 403

    def test_authorized_repeat_reads_reuse_the_pinned_projection(self) -> None:
        url = self.grant()
        self.client.force_login(self.recipient)
        self.assertContains(self.client.get(url), "222")
        with patch(
            "products.notebooks.backend.app_delivery.app_output_tabs", side_effect=AssertionError("unexpected reparse")
        ):
            self.assertContains(self.client.get(url), "222")
        denied = BucketDecision(allowed=False, remaining=0, limit=1, retry_after=4, reset=4)
        with patch("products.notebooks.backend.app_delivery.consume", return_value=denied):
            response = self.client.get(url)
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "4"

    def test_grant_matches_the_release_the_admin_reviewed(self) -> None:
        self.release.revision = 2
        self.release.save(update_fields=["revision"])
        request = {"email": self.recipient.email, "revision": 1}
        assert self.client.post(self.management, request, format="json").status_code == 400
        assert not NotebookAppViewGrant.objects.for_team(self.team.pk).exists()

    def test_org_security_policies_also_apply_to_app_only_output(self) -> None:
        url = self.grant()
        self.client.force_login(self.recipient)
        for field in ("is_active", "is_pending_deletion", "enforce_2fa", "enforce_verified_domains"):
            with self.subTest(field=field):
                old = getattr(self.organization, field)
                setattr(self.organization, field, field != "is_active")
                self.organization.save(update_fields=[field])
                assert self.client.get(url).status_code == 403
                setattr(self.organization, field, old)
                self.organization.save(update_fields=[field])

    def test_chart_fallback_uses_pinned_rows_and_marks_an_incomplete_preview(self) -> None:
        self.release.markdown = '<SQLV2 nodeId="totals" code="SELECT 1" runId="published" result={{"columns":["period","count","private_note"],"first_page":[["Nov",1,"hidden"]],"row_count":2,"previewOnly":true}} />'
        self.release.sql_rows = {
            "published": [["Nov", 1, "hidden"], ["Dec", 2, "hidden"]],
            "schema:published": {"node_id": "totals", "columns": ["period", "count", "private_note"], "row_count": 2},
        }
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertContains(output, "Dec")
        self.assertNotContains(output, "private_note")
        self.assertNotContains(output, "Only part")
        self.release = NotebookAppRelease.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            revision=2,
            title=self.release.title,
            layout=self.release.layout,
            markdown=self.release.markdown,
        )
        self.client.force_login(self.user)
        partial_url = self.grant()
        self.client.force_login(self.recipient)
        self.assertContains(self.client.get(partial_url), "Republish this app")

    def test_shared_pie_omits_the_undisplayed_axis_and_raw_values(self) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        chart = {
            "display": "ActionsPie",
            "chartSettings": {"xAxis": {"column": "Week"}, "yAxis": [{"column": "Signups"}, {"column": "Visits"}]},
        }
        self.release.markdown = (
            f'<SQLV2 nodeId="totals" code="SELECT 1" runId="{run_id}" vizQuery={{{json.dumps(chart)}}} />'
        )
        self.release.sql_rows[f"schema:{run_id}"]["columns"] = ["Week", "Signups", "Visits"]
        self.release.sql_rows[run_id] = [["Oct 12", 222, 450], ["Oct 19", 91, 350]]
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertContains(output, "Publish this chart as a table or single number")
        for private_value in ("Oct 12", "Oct 19", "<td>222</td>", "<td>450</td>"):
            self.assertNotContains(output, private_value)

    @parameterized.expand(
        [
            ([], "Oct 12", "222"),
            ([{"column": "Signups"}], "222", "Oct 12"),
        ]
    )
    def test_single_number_exposes_one_displayed_value(
        self, columns: list[dict[str, str]], visible: str, hidden: str
    ) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        chart = json.dumps({"display": "BoldNumber", "tableSettings": {"columns": columns}})
        self.release.markdown = f'<SQLV2 nodeId="totals" code="SELECT 1" runId="{run_id}" vizQuery={{{chart}}} />'
        self.release.sql_rows[run_id].append(["Oct 19", 91])
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertContains(output, f"<td>{visible}</td>", html=True)
        for other in (hidden, "Oct 19", "91"):
            self.assertNotContains(output, f"<td>{other}</td>", html=True)

    def test_grant_audits_are_scoped_to_the_notebook(self) -> None:
        self.grant()
        self.assertNotContains(
            self.client.get(f"/api/projects/{self.team.pk}/notebooks/activity/"), self.recipient.email
        )
        self.assertContains(
            self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/activity/"),
            self.recipient.email,
        )
