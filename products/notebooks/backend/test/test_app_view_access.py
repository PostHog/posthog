import json
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import Throttled

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.file_system.file_system import FileSystem
from posthog.token_bucket import BucketDecision, Budget

from products.access_control.backend.facade.testing import create_access_control
from products.notebooks.backend import app_delivery
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

    @parameterized.expand([("notebook",), ("project_tree",)])
    def test_trash_and_restore_require_a_new_grant(self, surface: str) -> None:
        old_url = self.grant()
        self.client.force_login(self.recipient)
        source_url = self.management.removesuffix("app_view_grants/")
        tree_url = f"/api/projects/{self.team.pk}/file_system/"
        if surface == "notebook":
            response = self.client.patch(source_url, {"deleted": False}, format="json")
            assert response.status_code == 200, response.content
            self.assertContains(self.client.get(old_url), "222")
            response = self.client.patch(source_url, {"deleted": True}, format="json")
        else:
            folder = FileSystem.objects.create(team=self.team, path="Quarterly", depth=1, type="folder")
            FileSystem.objects.update_or_create(
                team=self.team,
                type="notebook",
                ref=self.notebook.short_id,
                defaults={"path": "Quarterly/Activation", "depth": 2},
            )
            response = self.client.delete(f"{tree_url}{folder.pk}/")
        assert response.status_code == 200, response.content
        self.notebook.refresh_from_db()
        self.assertTrue(self.notebook.deleted)
        grants = NotebookAppViewGrant.objects.for_team(self.team.pk).filter(release=self.release)
        assert not grants.exists()

        # Notebooks already in the trash can still have grants issued before deletion revoked them.
        grants.create(
            team=self.team,
            release=self.release,
            recipient=self.recipient,
            expires_at=timezone.now() + timedelta(days=1),
        )
        if surface == "notebook":
            response = self.client.patch(source_url, {"deleted": False}, format="json")
        else:
            response = self.client.post(
                tree_url + "undo_delete/",
                {"items": [{"type": "notebook", "ref": self.notebook.short_id}]},
                format="json",
            )
        assert response.status_code == 200, response.content
        self.notebook.refresh_from_db()
        self.assertFalse(self.notebook.deleted)
        assert not grants.exists()
        assert self.client.get(old_url).status_code == 404
        self.client.force_login(self.user)
        new_url = self.grant()
        self.client.force_login(self.recipient)
        assert self.client.get(old_url).status_code == 404
        self.assertContains(self.client.get(new_url), "222")

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

    def test_recipient_lookup_budget_applies_before_resolving_a_second_project(self) -> None:
        url = self.grant()
        another_team = Team.objects.create(organization=self.organization, name="Second project")
        other_url = reverse("notebook_app_view_grant", args=[another_team.pk, self.release.pk])
        self.client.force_login(self.recipient)
        with patch.object(app_delivery, "APP_VIEW_RECIPIENT_BUDGET", Budget(burst=1, per_hour=1)):
            self.assertContains(self.client.get(url), "222")
            with patch(
                "products.notebooks.backend.presentation.app_view_access.get_object_or_404",
                side_effect=AssertionError("an exhausted recipient must not query the project"),
            ):
                response = self.client.get(other_url)
            assert response.status_code == 429
            assert int(response.headers["Retry-After"]) > 0

    def test_a_missing_grant_consumes_only_its_project_recipient_budget(self) -> None:
        url = self.grant()
        another_team = Team.objects.create(organization=self.organization, name="Second project")
        self.client.force_login(self.recipient)
        other_url = reverse("notebook_app_view_grant", args=[another_team.pk, self.release.pk])
        with patch.object(app_delivery, "APP_VIEW_PROJECT_RECIPIENT_BUDGET", Budget(burst=1, per_hour=1)):
            assert self.client.get(other_url).status_code == 404
            with self.assertNumQueries(0), self.assertRaises(Throttled):
                app_delivery.read_granted_output(another_team.pk, self.recipient.pk, self.release.pk)
            self.assertContains(self.client.get(url), "222")
            assert app_delivery.read_granted_output(another_team.pk, self.user.pk, self.release.pk) is None

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

    @parameterized.expand([("object",), ("serialized",)])
    def test_query_wrapped_table_shares_only_its_selected_column(self, encoding: str) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        query = {
            "kind": "DataVisualizationNode",
            "display": "ActionsTable",
            "source": {"kind": "HogQLQuery", "query": "SELECT 1"},
            "tableSettings": {"columns": [{"column": "Signups"}]},
        }
        attribute = json.dumps(query if encoding == "object" else json.dumps(query))
        self.release.markdown = f'<SQLV2 nodeId="totals" runId="{run_id}" query={{{attribute}}} />'
        self.release.save(update_fields=["markdown"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertContains(output, "<td>222</td>", html=True)
        self.assertNotContains(output, "Oct 12")
        self.assertNotContains(output, "<th>Week</th>", html=True)

    def test_chart_fallback_uses_pinned_rows_and_marks_an_incomplete_preview(self) -> None:
        self.release.markdown = '<SQLV2 nodeId="totals" code="SELECT 1" runId="published" vizQuery={{"display":"ActionsBar","chartSettings":{"xAxis":{"column":"period"},"yAxis":[{"column":"count"}]}}} result={{"columns":["period","count","private_note"],"first_page":[["Nov",1,"hidden"]],"row_count":2,"previewOnly":true}} />'
        self.release.sql_rows = {
            "published": [["Nov", 1, "hidden"], ["Dec", 2, "hidden"]],
            "schema:published": {
                "node_id": "totals",
                "columns": ["period", "count", "private_note"],
                "types": [["period", "String"], ["count", "Int64"], ["private_note", "String"]],
                "row_count": 2,
            },
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

    @parameterized.expand(
        [
            ("ActionsPie", {"xAxis": {"column": "Week"}, "yAxis": [{"column": "Signups"}, {"column": "Visits"}]}),
            ("Auto", {}),
            ("ScatterPlot", {"xAxis": {"column": "Visits"}, "yAxis": [{"column": "Signups"}]}),
            ("Metric", {"yAxis": [{"column": "Signups"}, {"column": "Visits"}]}),
        ]
    )
    def test_transformed_charts_omit_undisplayed_input_values(self, display: str, settings: dict) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        chart = {"display": display, "chartSettings": settings}
        self.release.markdown = (
            f'<SQLV2 nodeId="totals" code="SELECT 1" runId="{run_id}" vizQuery={{{json.dumps(chart)}}} />'
        )
        self.release.sql_rows[f"schema:{run_id}"]["columns"] = ["Week", "Region", "Signups", "Visits"]
        self.release.sql_rows[run_id] = [["Oct 12", "North", 222, 450], ["Oct 19", "South", 91, None]]
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertContains(output, "Publish this chart as a table or single number")
        for private_value in ("Oct 12", "North", "<td>222</td>", "<td>450</td>", "<td>91</td>"):
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

    def test_automatic_single_column_and_malformed_visualization(self) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        self.release.sql_rows[f"schema:{run_id}"]["columns"] = ["Value"]
        self.release.sql_rows[run_id] = [[17], [29]]
        self.release.markdown = (
            f'<SQLV2 nodeId="totals" code="SELECT 1" runId="{run_id}" vizQuery={{{{"display":"Auto"}}}} />'
        )
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        with patch("products.notebooks.backend.app_delivery.app_output_tabs", side_effect=RuntimeError("unavailable")):
            assert self.client.get(url).status_code == 500
        output = self.client.get(url)
        self.assertContains(output, "<td>17</td>", html=True)
        self.assertNotContains(output, "<td>29</td>", html=True)
        self.release = NotebookAppRelease.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            revision=2,
            title=self.release.title,
            layout=self.release.layout,
            markdown=f'<SQLV2 nodeId="totals" code="SELECT 1" runId="{run_id}" vizQuery />',
            sql_rows=self.release.sql_rows,
        )
        self.client.force_login(self.user)
        url = self.grant()
        self.client.force_login(self.recipient)
        self.assertContains(self.client.get(url), "Publish this chart as a table or single number")

    @parameterized.expand(["ActionsBar", "ActionsLineGraph", "Auto"])
    def test_grouped_chart_values_only_share_distinct_displayed_categories(self, display: str) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        chart = json.dumps({"display": display})
        self.release.markdown = f'<SQLV2 nodeId="totals" runId="{run_id}" code="SELECT 1" vizQuery={{{chart}}} />'
        self.release.sql_rows[f"schema:{run_id}"]["row_count"] = 2
        self.release.sql_rows[f"schema:{run_id}"]["types"] = [["Week", "String"], ["Signups", "Int64"]]
        self.release.sql_rows[run_id] = [["Spring", 6], ["Spring", 9]]
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertContains(output, "Publish this chart as a table or single number")
        self.assertNotContains(output, "<td>6</td>", html=True)
        self.assertNotContains(output, "<td>9</td>", html=True)

    @parameterized.expand(["stale", "over_limit", "inferred", "valid"])
    def test_chart_series_must_be_verified_against_the_displayed_schema(self, scenario: str) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        measures = [f"Measure {i}" for i in range(201 if scenario == "over_limit" else 2)]
        columns = ["Category", *measures, "Note"]
        selected = ["Note"] if scenario == "stale" else measures
        chart = {
            "display": "ActionsLineGraph",
            "chartSettings": {"xAxis": {"column": "Category"}, "yAxis": [{"column": name} for name in selected]},
        }
        if scenario == "inferred":
            chart.pop("chartSettings")
        self.release.markdown = (
            f'<SQLV2 nodeId="totals" runId="{run_id}" code="SELECT 1" vizQuery={{{json.dumps(chart)}}} />'
        )
        self.release.sql_rows[f"schema:{run_id}"].update(
            columns=columns,
            types=[["Category", "String"], *[[name, "Int64"] for name in measures], ["Note", "String"]],
            row_count=1,
        )
        self.release.sql_rows[run_id] = [["Winter", *range(len(measures)), "Internal note"]]
        self.release.save(update_fields=["markdown", "sql_rows"])
        url = self.grant()
        self.client.force_login(self.recipient)
        output = self.client.get(url)
        self.assertNotContains(output, "Internal note")
        if scenario == "valid":
            self.assertContains(output, "<td>Winter</td>", html=True)
            self.assertContains(output, '<th scope="col">Measure 1</th>', html=True)
            self.assertContains(output, "<td>1</td>", html=True)
        else:
            self.assertContains(output, "Publish this chart as a table or single number")
            self.assertNotContains(output, "<td>Winter</td>", html=True)

    def test_shared_budget_counts_a_saved_table_again_when_the_layout_repeats_it(self) -> None:
        run_id = next(key for key in self.release.sql_rows if not key.startswith("schema:"))
        value = "North team " * 12
        self.release.sql_rows[run_id] = [[value, 42]]
        self.release.save(update_fields=["sql_rows"])
        with patch("products.notebooks.backend.app_delivery.MAX_RELEASE_RESULT_BYTES", 320):
            url = self.grant()
            self.client.force_login(self.recipient)
            self.assertContains(self.client.get(url), value.strip())

            repeated = {**self.release.layout["blocks"][0], "id": "comparison", "tab_id": "notes"}
            self.release = NotebookAppRelease.objects.for_team(self.team.pk).create(
                team=self.team,
                notebook=self.notebook,
                revision=2,
                title=self.release.title,
                layout={**self.release.layout, "blocks": [*self.release.layout["blocks"], repeated]},
                markdown=self.release.markdown,
                sql_rows=self.release.sql_rows,
            )
            self.client.force_login(self.user)
            url = self.grant()
            self.client.force_login(self.recipient)
            output = self.client.get(url)
            self.assertContains(output, "This app exceeds the shared output limit")
            self.assertNotContains(output, value.strip())
            self.assertContains(self.client.get(url), "This app exceeds the shared output limit")

    def test_notebook_readers_can_see_normal_edits_without_sharing_recipient_details(self) -> None:
        self.grant()
        ordinary = ActivityLog.objects.create(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            user=self.user,
            item_id=self.notebook.short_id,
            scope="Notebook",
            activity="updated",
            detail={"name": "Weekly summary"},
        )
        notebook = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/"
        self.assertContains(self.client.get(notebook + "activity/"), self.recipient.email)

        self.client.force_login(self.recipient)
        assert self.client.get(notebook).status_code == 200
        history = self.client.get(notebook + "activity/")
        self.assertContains(history, str(ordinary.pk))
        self.assertNotContains(history, "app_view_grant")
        self.assertNotContains(history, self.recipient.email)

    def test_grant_audits_are_scoped_to_the_notebook(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.AUDIT_LOGS, "name": "Audit logs"},
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save(update_fields=["available_product_features"])
        create_access_control(
            team_id=self.team.pk, resource="notebook", resource_id=str(self.notebook.pk), access_level="none"
        )
        self.grant()
        ordinary = ActivityLog.objects.create(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            scope="Notebook",
            activity="updated",
            detail={"name": "Example notebook title change"},
        )
        self.assertContains(
            self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/activity/"),
            self.recipient.email,
        )
        OrganizationMembership.objects.create(
            organization=Organization.objects.create(name="Another organization"),
            user=self.recipient,
            level=OrganizationMembership.Level.OWNER,
        )
        self.client.force_login(self.recipient)
        for route in (
            "notebooks/activity/",
            "activity_log/",
            "advanced_activity_logs/",
            "advanced_activity_logs/?is_csv_export=1",
        ):
            with self.subTest(route=route):
                response = self.client.get(f"/api/projects/{self.team.pk}/{route}")
                self.assertNotContains(response, "app_view_grant")
                self.assertContains(response, str(ordinary.pk))

    @parameterized.expand(
        [
            ("admin", OrganizationMembership.Level.ADMIN, False),
            ("owner", OrganizationMembership.Level.OWNER, False),
            ("staff_member", OrganizationMembership.Level.MEMBER, True),
        ]
    )
    def test_privileged_auditors_see_grants_and_revocations_after_deletion(
        self, _name: str, level: OrganizationMembership.Level, is_staff: bool
    ) -> None:
        self.grant()
        revoke = self.client.post(
            self.management, {"recipient_uuid": str(self.recipient.uuid), "revoke": True}, format="json"
        )
        assert revoke.status_code == 200
        self.notebook.deleted = True
        self.notebook.save(update_fields=["deleted"])
        audit_ids = ActivityLog.objects.filter(
            organization_id=self.organization.pk,
            team_id=self.team.pk,
            item_id=self.notebook.short_id,
            detail__contains={"changes": [{"field": "app_view_grant"}]},
        ).values_list("pk", flat=True)
        assert len(audit_ids) == 2
        outside = Organization.objects.create(name="Separate organization")
        outside_team = Team.objects.create(organization=outside, name="Separate project")
        outside_record = ActivityLog.objects.create(
            organization_id=outside.pk,
            team_id=outside_team.pk,
            scope="Notebook",
            activity="updated",
            item_id=self.notebook.short_id,
            detail={"changes": [{"field": "app_view_grant", "after": {"recipient": "outside@example.com"}}]},
        )
        self.organization.available_product_features = [{"key": AvailableFeature.AUDIT_LOGS, "name": "Audit logs"}]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = level
        self.organization_membership.save(update_fields=["level"])
        self.user.is_staff = is_staff
        self.user.save(update_fields=["is_staff"])
        project = f"/api/projects/{self.team.pk}"
        routes = [
            f"{project}/activity_log/",
            f"{project}/advanced_activity_logs/",
            f"{project}/advanced_activity_logs/?is_csv_export=1",
        ]
        org_audit = f"/api/organizations/{self.organization.pk}/advanced_activity_logs/"
        if level >= OrganizationMembership.Level.ADMIN:
            routes.append(org_audit)
        else:
            assert self.client.get(org_audit).status_code == 403
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertContains(response, self.recipient.email)
                self.assertNotContains(response, str(outside_record.pk))
                for row_id in audit_ids:
                    self.assertContains(response, str(row_id))
