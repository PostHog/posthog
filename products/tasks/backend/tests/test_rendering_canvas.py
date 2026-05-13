from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework import serializers, status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.models import RenderingCanvas, Task
from products.tasks.backend.rendering_canvas_validation import MAX_CONTENT_BYTES, validate_canvas_content

VALID_CONTENT = "export default function Page() {\n  return <div>{{ @api.projects.get(id) }}</div>;\n}\n"


class TestRenderingCanvasValidation(TestCase):
    @parameterized.expand(
        [
            ("fetch", "fetch('/x')"),
            ("xhr", "new XMLHttpRequest()"),
            ("eval", "eval('1+1')"),
            ("new_function", "new Function('return 1')"),
            ("dynamic_import", "import('./mod')"),
            ("script_tag", "<script>alert(1)</script>"),
            ("document_cookie", "document.cookie"),
            ("window_location", "window.location.href = '/x'"),
        ]
    )
    def test_forbidden_patterns_rejected(self, _name: str, snippet: str) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_canvas_content(f"function X(){{ {snippet} }}")

    def test_size_limit_rejected(self) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_canvas_content("a" * (MAX_CONTENT_BYTES + 1))

    @parameterized.expand(
        [
            ("simple", "{{ @api.projects.get(id) }}"),
            ("nested_path", "{{ @api.projects.events.list(team_id, 10) }}"),
            ("no_args", "{{ @api.health.ping() }}"),
        ]
    )
    def test_valid_template_accepted(self, _name: str, template: str) -> None:
        validate_canvas_content(f"export default () => <div>{template}</div>")

    @parameterized.expand(
        [
            ("unknown_prefix", "{{ user.name }}"),
            ("missing_call", "{{ @api.projects }}"),
            ("nested_braces", "{{ @api.foo({nested: 1}) }}"),
        ]
    )
    def test_invalid_template_rejected(self, _name: str, template: str) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_canvas_content(f"<div>{template}</div>")

    def test_unmatched_braces_rejected(self) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_canvas_content("<div>{{ @api.x.y() </div>")

    def test_plain_content_accepted(self) -> None:
        validate_canvas_content("export default () => <div>hello</div>;")


class TestRenderingCanvasAPI(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    other_team: ClassVar[Team]
    user: ClassVar[User]
    feature_flag_patcher: MagicMock

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization = Organization.objects.create(name="Canvas Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Team A")
        cls.other_team = Team.objects.create(organization=cls.organization, name="Team B")
        cls.user = User.objects.create_user(email="canvas@example.com", first_name="C", password="p")
        cls.organization.members.add(cls.user)
        OrganizationMembership.objects.filter(user=cls.user, organization=cls.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def setUp(self) -> None:
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        mock = self.feature_flag_patcher.start()
        mock.side_effect = lambda flag, *a, **kw: flag == "tasks"

    def tearDown(self) -> None:
        self.feature_flag_patcher.stop()
        super().tearDown()

    def _url(self, team: Team | None = None, canvas_id: str | None = None) -> str:
        team_id = (team or self.team).id
        base = f"/api/projects/{team_id}/rendering_canvases/"
        return f"{base}{canvas_id}/" if canvas_id else base

    def test_create_and_retrieve(self) -> None:
        response = self.client.post(
            self._url(),
            {"name": "My UI", "content": VALID_CONTENT},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        canvas_id = response.json()["id"]

        canvas = RenderingCanvas.objects.get(id=canvas_id)
        self.assertEqual(canvas.team_id, self.team.id)
        self.assertEqual(canvas.created_by_id, self.user.id)
        self.assertEqual(canvas.name, "My UI")

        get_response = self.client.get(self._url(canvas_id=canvas_id))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.json()["name"], "My UI")

    def test_create_rejects_forbidden_content(self) -> None:
        response = self.client.post(
            self._url(),
            {"name": "Bad", "content": "fetch('/x')"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "content")

    def test_list_scopes_to_team(self) -> None:
        RenderingCanvas.objects.create(team=self.team, name="Mine", content="x")
        RenderingCanvas.objects.create(team=self.other_team, name="Theirs", content="x")

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["Mine"])

    def test_other_team_canvas_not_retrievable(self) -> None:
        canvas = RenderingCanvas.objects.create(team=self.other_team, name="X", content="x")
        response = self.client.get(self._url(canvas_id=str(canvas.id)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_updates_content(self) -> None:
        canvas = RenderingCanvas.objects.create(team=self.team, name="N", content="old")
        response = self.client.patch(
            self._url(canvas_id=str(canvas.id)),
            {"content": VALID_CONTENT},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        canvas.refresh_from_db()
        self.assertEqual(canvas.content, VALID_CONTENT)

    def test_delete_soft_deletes(self) -> None:
        canvas = RenderingCanvas.objects.create(team=self.team, name="N", content="x")
        response = self.client.delete(self._url(canvas_id=str(canvas.id)))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        canvas.refresh_from_db()
        self.assertTrue(canvas.deleted)

        list_response = self.client.get(self._url())
        ids = [item["id"] for item in list_response.json()["results"]]
        self.assertNotIn(str(canvas.id), ids)

    def test_task_must_match_team(self) -> None:
        other_task = Task.objects.create(
            team=self.other_team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        response = self.client.post(
            self._url(),
            {"name": "X", "content": "x", "task": str(other_task.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestRenderingCanvasGenerate(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    other_team: ClassVar[Team]
    user: ClassVar[User]
    feature_flag_patcher: MagicMock

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization = Organization.objects.create(name="Canvas Gen Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Team A")
        cls.other_team = Team.objects.create(organization=cls.organization, name="Team B")
        cls.user = User.objects.create_user(email="gen@example.com", first_name="G", password="p")
        cls.organization.members.add(cls.user)
        OrganizationMembership.objects.filter(user=cls.user, organization=cls.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def setUp(self) -> None:
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        mock = self.feature_flag_patcher.start()
        mock.side_effect = lambda flag, *a, **kw: flag == "tasks"

    def tearDown(self) -> None:
        self.feature_flag_patcher.stop()
        super().tearDown()

    def _generate_url(self) -> str:
        return f"/api/projects/{self.team.id}/rendering_canvases/generate/"

    @patch("products.tasks.backend.api.generate_canvas_tsx")
    def test_generate_happy_path(self, mock_generate: MagicMock) -> None:
        mock_generate.return_value = (VALID_CONTENT, "Generated UI")

        response = self.client.post(
            self._generate_url(),
            {"prompt": "a card with the project name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        body = response.json()
        self.assertEqual(body["name"], "Generated UI")
        self.assertEqual(body["content"], VALID_CONTENT)

        canvas = RenderingCanvas.objects.get(id=body["id"])
        self.assertEqual(canvas.team_id, self.team.id)
        self.assertEqual(canvas.created_by_id, self.user.id)

        mock_generate.assert_called_once()
        kwargs = mock_generate.call_args.kwargs
        self.assertEqual(kwargs["team"].id, self.team.id)
        self.assertEqual(kwargs["user"].id, self.user.id)
        self.assertEqual(kwargs["prompt"], "a card with the project name")

    @patch("products.tasks.backend.api.generate_canvas_tsx")
    def test_generate_uses_name_hint_when_provided(self, mock_generate: MagicMock) -> None:
        mock_generate.return_value = (VALID_CONTENT, "Derived From Prompt")

        response = self.client.post(
            self._generate_url(),
            {"prompt": "anything", "name": "Explicit Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        # The action passes the hint through to generate_canvas_tsx; the function decides.
        # We assert the hint reached the function — derivation behavior is unit-tested separately.
        self.assertEqual(mock_generate.call_args.kwargs["name_hint"], "Explicit Name")

    @patch("products.tasks.backend.api.generate_canvas_tsx")
    def test_generate_rejects_unsafe_llm_output(self, mock_generate: MagicMock) -> None:
        mock_generate.return_value = ("export default () => fetch('/x')", "Bad Output")

        response = self.client.post(
            self._generate_url(),
            {"prompt": "something"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(RenderingCanvas.objects.count(), 0)

    @patch("products.tasks.backend.api.generate_canvas_tsx")
    def test_generate_rejects_cross_team_task(self, mock_generate: MagicMock) -> None:
        other_task = Task.objects.create(
            team=self.other_team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        response = self.client.post(
            self._generate_url(),
            {"prompt": "x", "task": str(other_task.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_generate.assert_not_called()
        self.assertEqual(RenderingCanvas.objects.count(), 0)

    def test_generate_requires_prompt(self) -> None:
        response = self.client.post(self._generate_url(), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
