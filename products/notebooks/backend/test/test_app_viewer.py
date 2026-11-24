from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.constants import AvailableFeature

from products.access_control.backend.models.access_control import AccessControl
from products.notebooks.backend.app_viewer import resolve_viewer_queries
from products.notebooks.backend.facade.contracts import AppRelease
from products.notebooks.backend.markdown_conversion import (
    build_markdown_notebook_content,
    get_markdown_notebook_markdown,
)
from products.notebooks.backend.models import Notebook, NotebookAppRelease


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
