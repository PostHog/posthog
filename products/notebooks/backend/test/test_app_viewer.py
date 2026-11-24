from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client.execute_async import QueryNotFoundError
from posthog.constants import AvailableFeature

from products.access_control.backend.models.access_control import AccessControl
from products.notebooks.backend.app_viewer import resolve_viewer_queries
from products.notebooks.backend.facade.contracts import AppRelease
from products.notebooks.backend.markdown_conversion import (
    build_markdown_notebook_content,
    get_markdown_notebook_markdown,
)
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookNodeRun


class TestNotebookAppViewer(ClickhouseTestMixin, APIBaseTest):
    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_viewer_inputs_bind_published_sources_without_writing_shared_state(self, _app_builder_enabled) -> None:
        defaults = [{"name": "region", "type": "string", "value": "All"}]
        content = build_markdown_notebook_content(
            '<SQLV2 nodeId="base" code="select {region} AS region" returnVariable="regions" />\n\n'
            '<SQLV2 nodeId="output" code="select * from regions" returnVariable="answer" />'
        )
        layout = {
            "tabs": [{"id": "overview", "title": "Overview"}],
            "blocks": [
                {"id": "region", "kind": "input", "variable": "region", "tab_id": "overview"},
                {"id": "answer", "kind": "cell", "node_id": "output", "tab_id": "overview"},
            ],
        }
        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            variables=defaults,
            content=content,
            app_published=layout,
            app_revision=1,
        )
        NotebookAppRelease.objects.for_team(self.team.id).create(
            team=self.team,
            notebook=notebook,
            revision=1,
            layout=layout,
            variables=defaults,
            markdown=get_markdown_notebook_markdown(content),
            title="Release",
        )
        notebook.content = build_markdown_notebook_content("Unpublished draft")
        notebook.save(update_fields=["content"])
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="notebook", resource_id=str(notebook.pk), access_level="viewer"
        )
        notebook_url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        url = notebook_url + "app_queries/"
        for name, region in [("alice", "Europe"), ("bob", "Asia")]:
            user = self._create_user(f"{name}@example.com")
            self.organization.members.add(user)
            self.client.force_login(user)
            assert self.client.get(notebook_url).json()["user_access_level"] == "viewer"
            assert self.client.patch(notebook_url, {"title": "Unauthorized"}, format="json").status_code == 403
            payload = {"revision": 1, "variables": [{**defaults[0], "value": region}]}
            response = self.client.post(url, payload, format="json")
            assert response.status_code == 200, response.json()
            [plan] = response.json()
            assert plan["node_id"] == "output" and region in plan["query"]
            assert not plan["matches_defaults"]
            result = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {"query": {"kind": "HogQLQuery", "query": plan["query"]}, "refresh": "blocking"},
                format="json",
            )
            assert result.status_code == 200, result.json()
            assert result.json()["results"] == [[region]]
        assert self.client.post(url, {"variables": defaults, "revision": 1}, format="json").json()[0][
            "matches_defaults"
        ]
        assert self.client.post(url, {**payload, "revision": 2}, format="json").status_code == 409
        assert (
            self.client.post(
                url, {**payload, "variables": [{**defaults[0], "name": "private"}]}, format="json"
            ).status_code
            == 400
        )
        with patch(
            "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._has_query_access",
            return_value=False,
        ):
            assert self.client.post(url, payload, format="json").status_code == 403
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch(
                "products.notebooks.backend.presentation.notebook_throttles.NotebookAppQueryBurstThrottle.rate",
                "1/minute",
            ),
        ):
            assert self.client.post(url, payload, format="json").status_code == 200
            assert self.client.post(url, payload, format="json").status_code == 429
            self.client.force_login(self.user)
            assert self.client.post(url, payload, format="json").status_code == 200
        notebook.refresh_from_db()
        assert notebook.variables == defaults
        assert get_markdown_notebook_markdown(notebook.content) == "Unpublished draft"
        assert notebook.app_revision == 1


def test_date_filter_only_recomputes_native_outputs_with_changed_bindings() -> None:
    release = AppRelease(
        revision=1,
        published_at=None,
        results_as_of=None,
        title="Regions",
        has_previous=False,
        markdown="\n\n".join(
            [
                '<PythonV2 nodeId="python" code="x = 1" returnVariable="frame" />',
                '<SQLV2 nodeId="external" code="select * from frame" returnVariable="external_rows" />',
                '<SQLV2 nodeId="dependent" code="select * from external_rows" />',
                '<SQLV2 nodeId="date" code="select toDate({day}) AS day" />',
                '<SQLV2 nodeId="constant" code="select 1" />',
            ]
        ),
        variables=[{"name": "day", "type": "date", "value": "2026-10-12"}],
        layout={
            "blocks": [
                {"kind": "input", "variable": "day"},
                *[{"kind": "cell", "node_id": node} for node in ["python", "dependent", "date", "constant"]],
            ]
        },
    )
    plans = {plan.node_id: plan for plan in resolve_viewer_queries(release, {"day": "2026-10-19"})}
    assert plans.keys() == {"date", "constant"}
    assert "2026-10-19" in plans["date"].query
    assert not plans["date"].matches_defaults
    assert plans["constant"].matches_defaults


class TestPublishedAppResults(APIBaseTest):
    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_published_run_restores_rows_after_cache_expiry(self, _flag) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        rows = [[number] for number in range(74)] + [["published last row"]]
        run = NotebookNodeRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=notebook,
            node_type="hogql",
            node_id="orders",
            code="SELECT 1",
            status="done",
            envelope={"first_page": rows[:50], "has_more": True, "columns": ["value"]},
        )
        source = f'<SQLV2 nodeId="orders" code="SELECT 1" runId="{run.id}" result={{{{"first_page":[[0]]}}}} />'
        notebook.content = build_markdown_notebook_content(source)
        notebook.save(update_fields=["content"])
        layout = {
            "tabs": [{"id": "summary", "title": "Summary"}],
            "blocks": [{"id": "output", "kind": "cell", "tab_id": "summary", "node_id": "orders"}],
        }
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        with patch("products.notebooks.backend.app_release_results.sync_direct_run", return_value=rows):
            published = self.client.patch(url, {"app_revision": 0, "app_published": layout}, format="json")
        assert published.status_code == 200, published.json()
        release = self.client.get(url + "app_release/")
        assert release.status_code == 200
        assert b"published last row" not in release.content
        result_url = url + f"sql_v2/runs/{run.id}/"
        with patch("products.notebooks.backend.sql_v2_direct.get_query_status", side_effect=QueryNotFoundError):
            republished = self.client.patch(url, {"app_revision": 1, "app_published": layout}, format="json")
            assert republished.status_code == 200, republished.json()
            current = NotebookAppRelease.objects.for_team(self.team.id).get(notebook=notebook, revision=2)
            assert current.sql_rows == {str(run.id): rows}
            with patch("products.notebooks.backend.app_release_results.MAX_RELEASE_RESULT_BYTES", 64):
                oversized = self.client.patch(url, {"app_revision": 2, "app_published": layout}, format="json")
                assert oversized.status_code == 200, oversized.json()
                current = NotebookAppRelease.objects.for_team(self.team.id).get(notebook=notebook, revision=3)
                assert current.sql_rows == {}
            restored = self.client.get(result_url, {"node_id": "orders"})
            assert restored.status_code == 200, restored.json()
            assert restored.json()["rows"] == rows
            assert self.client.get(result_url, {"node_id": "other"}).status_code == 404
            run.connection_id = run.id
            run.save(update_fields=["connection_id"])
            assert self.client.get(result_url, {"node_id": "orders"}).status_code == 403
