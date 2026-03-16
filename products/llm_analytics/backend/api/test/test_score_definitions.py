from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.llm_analytics.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion


class TestScoreDefinitionsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_patcher = patch(
            "products.llm_analytics.backend.api.score_definitions.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.addCleanup(self.feature_flag_patcher.stop)

    def _endpoint(self) -> str:
        return f"/api/environments/{self.team.id}/llm_analytics/score_definitions/"

    def _current_version(self, definition: ScoreDefinition) -> ScoreDefinitionVersion:
        current_version = definition.current_version
        assert current_version is not None
        return current_version

    def test_returns_403_when_feature_flag_disabled(self):
        self.mock_feature_enabled.return_value = False

        response = self.client.get(self._endpoint())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            (
                "categorical_single",
                {
                    "name": "Quality",
                    "kind": "categorical",
                    "config": {
                        "options": [
                            {"key": "good", "label": "Good"},
                            {"key": "bad", "label": "Bad"},
                        ]
                    },
                },
            ),
            (
                "categorical_multiple",
                {
                    "name": "Themes",
                    "kind": "categorical",
                    "config": {
                        "options": [
                            {"key": "helpful", "label": "Helpful"},
                            {"key": "accurate", "label": "Accurate"},
                            {"key": "complete", "label": "Complete"},
                        ],
                        "selection_mode": "multiple",
                        "min_selections": 1,
                        "max_selections": 2,
                    },
                },
            ),
            (
                "numeric",
                {
                    "name": "Score",
                    "kind": "numeric",
                    "config": {"min": 0, "max": 5, "step": 1},
                },
            ),
            (
                "boolean",
                {
                    "name": "Resolved",
                    "kind": "boolean",
                    "config": {"true_label": "Yes", "false_label": "No"},
                },
            ),
        ]
    )
    def test_can_create_score_definitions_for_all_supported_kinds(self, _name: str, payload: dict):
        response = self.client.post(self._endpoint(), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        current_version = self._current_version(definition)
        self.assertEqual(definition.created_by, self.user)
        self.assertEqual(definition.kind, payload["kind"])
        self.assertEqual(current_version.version, 1)
        self.assertEqual(current_version.config, payload["config"])

    def test_patch_updates_metadata_without_creating_a_new_version(self):
        definition = self._create_definition()

        response = self.client.patch(
            f"{self._endpoint()}{definition.id}/",
            {"name": "Updated quality", "description": "Updated description", "archived": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()
        current_version = self._current_version(definition)
        self.assertEqual(definition.name, "Updated quality")
        self.assertEqual(definition.description, "Updated description")
        self.assertTrue(definition.archived)
        self.assertEqual(current_version.version, 1)
        self.assertEqual(definition.versions.count(), 1)

    def test_create_starts_active(self):
        response = self.client.post(
            self._endpoint(),
            {
                "name": "Customer Satisfaction",
                "kind": "boolean",
                "config": {"true_label": "Good", "false_label": "Bad"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        self.assertFalse(definition.archived)

    def test_create_rejects_archived_scorers(self):
        response = self.client.post(
            self._endpoint(),
            {
                "name": "Customer Satisfaction",
                "kind": "boolean",
                "archived": True,
                "config": {"true_label": "Good", "false_label": "Bad"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "archived")
        self.assertEqual(response.data["detail"], "New scorers must be created as active.")

    def test_new_version_creates_immutable_snapshot_and_advances_current_version(self):
        definition = self._create_definition()
        original_config = self._current_version(definition).config

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {
                "config": {
                    "options": [
                        {"key": "pass", "label": "Pass"},
                        {"key": "needs_work", "label": "Needs work"},
                        {"key": "fail", "label": "Fail"},
                    ],
                    "selection_mode": "multiple",
                    "min_selections": 1,
                    "max_selections": 2,
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()
        current_version = self._current_version(definition)
        self.assertEqual(current_version.version, 2)
        self.assertEqual(definition.versions.count(), 2)
        self.assertEqual(definition.versions.get(version=1).config, original_config)
        self.assertEqual(
            definition.versions.get(version=2).config,
            {
                "options": [
                    {"key": "pass", "label": "Pass"},
                    {"key": "needs_work", "label": "Needs work"},
                    {"key": "fail", "label": "Fail"},
                ],
                "selection_mode": "multiple",
                "min_selections": 1,
                "max_selections": 2,
            },
        )

    def test_list_supports_search_kind_archived_and_ordering(self):
        active = self._create_definition(name="Quality", kind="categorical")
        archived = self._create_definition(
            name="Resolved",
            kind="boolean",
            archived=True,
        )

        response = self.client.get(
            self._endpoint(),
            {
                "search": "resolved",
                "kind": "boolean",
                "archived": "true",
                "order_by": "name",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([result["id"] for result in response.data["results"]], [str(archived.id)])
        self.assertNotIn(str(active.id), [result["id"] for result in response.data["results"]])

    def _create_definition(
        self,
        *,
        name: str = "Quality",
        kind: str = "categorical",
        archived: bool = False,
        config: dict | None = None,
    ) -> ScoreDefinition:
        payload = {
            "name": name,
            "kind": kind,
            "config": config
            or {
                "options": [
                    {"key": "good", "label": "Good"},
                    {"key": "bad", "label": "Bad"},
                ]
            },
        }
        response = self.client.post(self._endpoint(), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        if archived:
            definition.archived = True
            definition.save(update_fields=["archived", "updated_at"])
        return definition
