from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.notebooks.backend.models import Notebook
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
