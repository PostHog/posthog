from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models import Team

from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookNodeRun, NotebookRun
from products.notebooks.backend.presentation.views.notebook import NotebookSerializer

LAYOUT = {
    "tabs": [{"id": "overview", "title": "Overview"}],
    "blocks": [{"id": "intro", "kind": "text", "tab_id": "overview", "text": "## Results"}],
}


@pytest.mark.parametrize(
    "layout",
    [
        {"title": "Missing tabs and blocks"},
        {"tabs": [], "blocks": []},
        {"tabs": [{"id": "same", "title": "A"}, {"id": "same", "title": "B"}], "blocks": []},
        {**LAYOUT, "blocks": [{"id": "missing", "kind": "cell", "tab_id": "overview"}]},
        {**LAYOUT, "blocks": [{"id": "orphan", "kind": "text", "tab_id": "absent"}]},
        {**LAYOUT, "blocks": [{"id": "wide", "kind": "text", "tab_id": "overview", "width": 13}]},
        {
            **LAYOUT,
            "blocks": [
                {"id": "slider", "kind": "input", "tab_id": "overview", "variable": "limit", "min": 10, "max": 5}
            ],
        },
        {**LAYOUT, "blocks": LAYOUT["blocks"] * 2},
    ],
)
def test_partial_notebook_update_requires_a_complete_valid_app_layout(layout: dict[str, Any]) -> None:
    serializer = NotebookSerializer(data={"app_draft": layout}, partial=True)
    assert not serializer.is_valid()
    assert "app_draft" in serializer.errors


class TestNotebookAppLayout(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.app_flag = self.enterContext(
            patch(
                "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled",
                return_value=True,
            )
        )

    @parameterized.expand(
        [
            ("create_draft", "post", {"app_draft": LAYOUT}),
            ("create_published", "post", {"app_published": LAYOUT}),
            ("update_draft", "patch", {"app_draft": LAYOUT}),
            ("publish", "patch", {"app_published": LAYOUT}),
            ("unpublish", "patch", {"app_published": None}),
            ("revision", "patch", {"app_revision": 1}),
        ]
    )
    def test_disabled_flag_blocks_app_writes(self, _name: str, method: str, payload: dict[str, Any]) -> None:
        self.app_flag.return_value = False
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, app_draft=LAYOUT, app_published=LAYOUT)
        url = f"/api/projects/{self.team.id}/notebooks/"
        if method == "patch":
            url += f"{notebook.short_id}/"
        before = Notebook.objects.filter(team=self.team).count()
        response = getattr(self.client, method)(url, payload, format="json")
        assert response.status_code == 403, response.json()
        assert Notebook.objects.filter(team=self.team).count() == before
        notebook.refresh_from_db()
        assert notebook.app_draft == LAYOUT
        assert notebook.app_published == LAYOUT
        assert notebook.app_revision == 0

    @parameterized.expand([(False,), (None,)])
    def test_disabled_or_unknown_flag_hides_layouts_but_allows_notebook_edits(self, enabled: bool | None) -> None:
        self.app_flag.return_value = enabled
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, app_draft=LAYOUT, app_published=LAYOUT)
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        response = self.client.get(url)
        assert response.status_code == 200
        assert not {"app_draft", "app_published", "app_revision"}.intersection(response.json())
        response = self.client.patch(url, {"title": "Updated notebook"}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["title"] == "Updated notebook"
        assert not {"app_draft", "app_published", "app_revision"}.intersection(response.json())
        response = self.client.patch(url, {"app_revision": 0, "app_draft": LAYOUT}, format="json")
        assert response.status_code == 403

    def test_app_reads_and_writes_resolve_a_remotely_targeted_project(self) -> None:
        remote_checks: list[tuple[str, str]] = []

        def evaluate_flag(
            key: str,
            distinct_id: str,
            *,
            groups: dict[str, str] | None = None,
            only_evaluate_locally: bool = False,
            **kwargs: Any,
        ) -> bool | None:
            if key != "notebook-app-builder":
                return True
            if only_evaluate_locally:
                return None
            assert groups is not None
            remote_checks.append((distinct_id, groups["project"]))
            return distinct_id == self.user.distinct_id and groups["project"] == str(self.team.uuid)

        self.app_flag.side_effect = evaluate_flag
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()["app_revision"] == 0
        response = self.client.patch(url, {"app_revision": 0, "app_draft": LAYOUT}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["app_revision"] == 1

        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_notebook = Notebook.objects.create(team=other_team, created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{other_team.id}/notebooks/{other_notebook.short_id}/",
            {"app_revision": 0, "app_draft": LAYOUT},
            format="json",
        )
        assert response.status_code == 403, response.json()

        other_user = self.create_user_with_organization(self.organization)
        self.client.force_login(other_user)
        response = self.client.get(url)
        assert response.status_code == 200, response.json()
        assert "app_draft" not in response.json()
        assert remote_checks == [
            (self.user.distinct_id, str(self.team.uuid)),
            (self.user.distinct_id, str(other_team.uuid)),
            (other_user.distinct_id, str(self.team.uuid)),
        ]

    def test_draft_and_published_layouts_are_separate_and_reject_stale_writes(self) -> None:
        notebook = Notebook.objects.create(team=self.team, title="App notebook", created_by=self.user)
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        response = self.client.patch(
            url, {"app_revision": 0, "app_draft": LAYOUT, "app_published": LAYOUT}, format="json"
        )
        assert response.status_code == 200, response.json()
        assert response.json()["app_revision"] == 1
        assert response.json()["version"] == 0

        response = self.client.patch(
            url, {"app_revision": 1, "app_draft": {**LAYOUT, "title": "Draft title"}}, format="json"
        )
        assert response.status_code == 200, response.json()
        assert response.json()["app_draft"]["title"] == "Draft title"
        assert response.json()["app_published"]["title"] == ""

        response = self.client.patch(url, {"app_revision": 1, "app_published": None}, format="json")
        assert response.status_code == 409
        notebook.refresh_from_db()
        assert notebook.app_published is not None
        assert notebook.app_revision == 2

        response = self.client.patch(url, {"app_revision": 2, "app_published": None}, format="json")
        assert response.status_code == 200, response.json()
        notebook.refresh_from_db()
        assert notebook.app_published is None
        assert notebook.app_draft["title"] == "Draft title"

    def test_release_pins_defaults_and_restores_without_overwriting_the_draft(self) -> None:
        variables = [{"name": "region", "type": "string", "value": "Europe"}]
        notebook = Notebook.objects.create(
            team=self.team, created_by=self.user, title="First title", variables=variables
        )
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        release_url = url + "app_release/"
        first = self.client.patch(url, {"app_revision": 0, "app_published": LAYOUT}, format="json")
        assert first.status_code == 200, first.json()
        changes = {
            "title": "Second title",
            "variables": [],
            "app_revision": 1,
            "app_draft": {**LAYOUT, "title": "Draft"},
        }
        assert self.client.patch(url, changes, format="json").status_code == 200
        release = self.client.get(release_url).json()
        assert release["title"] == "First title"
        assert release["variables"] == variables
        assert not release["has_previous"]

        invalid = {**LAYOUT, "blocks": [{"id": "gone", "kind": "cell", "tab_id": "overview", "node_id": "absent"}]}
        assert self.client.patch(url, {"app_revision": 2, "app_published": invalid}, format="json").status_code == 400
        assert self.client.get(release_url).json() == release
        assert self.client.patch(url, {"app_revision": 2, "app_published": LAYOUT}, format="json").status_code == 200
        assert self.client.get(release_url).json()["has_previous"]
        other = Notebook.objects.create(team=self.team, title="Another app")
        other_release = NotebookAppRelease.objects.for_team(self.team.id).create(
            team_id=self.team.id, notebook=other, revision=1, layout=LAYOUT
        )
        restore = {"app_revision": 2, "restore_previous_app_release": True}
        assert self.client.patch(url, restore, format="json").status_code == 409
        response = self.client.patch(url, {**restore, "app_revision": 3}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["app_draft"]["title"] == "Draft"
        assert self.client.get(release_url).json()["variables"] == variables
        releases = NotebookAppRelease.objects.for_team(self.team.id)
        assert list(releases.filter(notebook=notebook).order_by("revision").values_list("revision", flat=True)) == [
            3,
            4,
        ]
        assert releases.filter(pk=other_release.pk).exists()
        assert self.client.patch(url, {"app_revision": 4, "app_published": None}, format="json").status_code == 200
        assert self.client.get(release_url).status_code == 404

    def test_preview_and_publish_require_the_saved_run_and_its_bound_defaults(self) -> None:
        defaults = [{"name": "region", "type": "string", "value": "Europe"}]
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, variables=defaults)
        run = NotebookRun.objects.for_team(self.team.id).create(
            team=self.team, notebook=notebook, trigger="ui", variables=defaults, status="done"
        )
        cell = NotebookNodeRun.objects.for_team(self.team.id).create(
            team=self.team,
            notebook=notebook,
            notebook_run=run,
            node_id="proof",
            node_type="python",
            code="print(region)",
            status="done",
            envelope={"stdout": "Europe"},
        )
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        layout = {
            **LAYOUT,
            "blocks": [{"id": "output", "kind": "cell", "tab_id": "overview", "title": "Region", "node_id": "proof"}],
        }
        source = '<PythonV2 nodeId="proof" code="print(region)" />'
        notebook.content = build_markdown_notebook_content(source)
        notebook.save(update_fields=["content"])
        preview = self.client.post(url + "app_preview/", layout, format="json")
        assert preview.status_code == 200, preview.json()
        assert "wait for the result to save" in preview.json()["problems"][0]
        assert self.client.patch(url, {"app_revision": 0, "app_published": layout}, format="json").status_code == 400
        source = source.replace(" />", f' runId="{cell.pk}" result={{{{"stdout":"Europe"}}}} />')
        notebook.content = build_markdown_notebook_content(source)
        notebook.save(update_fields=["content"])
        preview = self.client.post(url + "app_preview/", layout, format="json").json()
        assert preview["problems"] == [] and preview["results_as_of"]
        assert self.client.patch(url, {"app_revision": 0, "app_published": layout}, format="json").status_code == 200
        release = self.client.get(url + "app_release/").json()
        assert release["results_as_of"] == preview["results_as_of"]
        assert release["markdown"] == source
        notebook.variables = [{**defaults[0], "value": "Asia"}]
        notebook.save(update_fields=["variables"])
        preview = self.client.post(url + "app_preview/", layout, format="json").json()
        assert "stale" in preview["problems"][0]
        assert self.client.patch(url, {"app_revision": 1, "app_published": layout}, format="json").status_code == 400
        assert self.client.get(url + "app_release/").json() == release

    @parameterized.expand(
        [
            ("python_single", "PythonV2", "print(amount)", "number", 4, "number", 5),
            ("builtin", "PythonV2", "print(max)", "number", 4, "number", 5),
            ("dynamic_lookup", "PythonV2", "print(globals()['amount'])", "number", 4, "number", 5),
            ("type_change", "PythonV2", "print(amount)", "boolean", True, "number", 1),
            ("deletion", "PythonV2", "print(amount)", "number", 4, None, None),
            ("duckdb_single", "SQLV2", "select {amount}", "number", 4, "number", 5),
        ]
    )
    def test_release_checks_the_inputs_bound_by_a_single_cell(
        self,
        case: str,
        tag: str,
        code: str,
        kind: str,
        value: Any,
        new_kind: str | None,
        new_value: Any,
    ) -> None:
        name = "max" if case == "builtin" else "amount"
        notebook = Notebook.objects.create(team=self.team, variables=[{"name": name, "type": kind, "value": value}])
        cell = NotebookNodeRun.objects.for_team(self.team.id).create(
            team=self.team,
            notebook=notebook,
            node_id="output",
            node_type="python" if tag == "PythonV2" else "duckdb",
            code=code.replace("{amount}", "$amount"),
            status="done",
            bound_variables={name: value},
        )
        notebook.content = build_markdown_notebook_content(
            f'<{tag} nodeId="output" code="{code}" runId="{cell.pk}" result={{{{}}}} />'
        )
        notebook.save(update_fields=["content"])
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/"
        layout = {**LAYOUT, "blocks": [{"id": "result", "kind": "cell", "tab_id": "overview", "node_id": "output"}]}
        assert self.client.post(url + "app_preview/", layout, format="json").json()["problems"] == []
        notebook.variables = [{"name": name, "type": new_kind, "value": new_value}] if new_kind else []
        notebook.save(update_fields=["variables"])
        assert "stale" in self.client.post(url + "app_preview/", layout, format="json").json()["problems"][0]
        assert self.client.patch(url, {"app_revision": 0, "app_published": layout}, format="json").status_code == 400

    def test_release_reads_only_run_metadata_for_visible_results_and_their_dependencies(self) -> None:
        notebook = Notebook.objects.create(team=self.team)
        runs = NotebookNodeRun.objects.for_team(self.team.id)
        nodes = {
            node_id: runs.create(
                team=self.team,
                notebook=notebook,
                node_id=node_id,
                node_type="python",
                code=code,
                status="done",
                bound_variables={},
                envelope={"stdout": "output"},
            )
            for node_id, code in [("upstream", "frame = 1"), ("visible", "print(frame)"), ("excluded-cell", "print(0)")]
        }
        visible_id = nodes["visible"].id
        notebook.content = build_markdown_notebook_content(
            '<PythonV2 nodeId="upstream" code="frame = 1" returnVariable="frame" />\n\n'
            f'<PythonV2 nodeId="visible" code="print(frame)" returnVariable="shown" runId="{visible_id}" result={{{{}}}} />\n\n'
            '<PythonV2 nodeId="excluded-cell" code="print(0)" />'
        )
        notebook.save(update_fields=["content"])
        url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/app_preview/"
        layout = {**LAYOUT, "blocks": [{"id": "result", "kind": "cell", "tab_id": "overview", "node_id": "visible"}]}
        with CaptureQueriesContext(connection) as captured:
            preview = self.client.post(url, layout, format="json").json()
        assert preview["problems"] == []
        reads = [query["sql"] for query in captured.captured_queries if "posthog_notebooknoderun" in query["sql"]]
        assert reads
        for sql in reads:
            assert '"envelope"' not in sql and "excluded-cell" not in sql, sql
            assert "upstream" in sql and "visible" in sql, sql
        runs.filter(notebook=notebook, node_id="upstream").update(bound_variables=None)
        assert "stale" in self.client.post(url, layout, format="json").json()["problems"][0]

    def test_layout_patch_cannot_address_a_notebook_in_another_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        notebook = Notebook.objects.create(team=other_team, title="Other notebook", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/",
            {"app_revision": 0, "app_draft": LAYOUT},
            format="json",
        )
        assert response.status_code == 404
        notebook.refresh_from_db()
        assert notebook.app_draft is None

    @parameterized.expand(
        [
            ("incomplete_layout", {"app_revision": 0, "app_draft": {"title": "Incomplete"}}),
            ("revision_only", {"app_revision": 0}),
        ]
    )
    def test_invalid_layout_is_rejected_by_the_endpoint(self, _name: str, payload: dict[str, Any]) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/",
            payload,
            format="json",
        )
        assert response.status_code == 400
        notebook.refresh_from_db()
        assert notebook.app_draft is None
