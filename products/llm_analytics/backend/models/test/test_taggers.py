from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError

from products.llm_analytics.backend.models.taggers import LLMTaggerConfig, TagDefinition, Tagger


class TestLLMTaggerConfig(BaseTest):
    def test_valid_config(self):
        config = LLMTaggerConfig(
            prompt="Which features were discussed?",
            tags=[
                TagDefinition(name="billing", description="Billing related"),
                TagDefinition(name="analytics", description="Analytics related"),
            ],
            min_tags=0,
            max_tags=2,
        )
        assert config.prompt == "Which features were discussed?"
        assert len(config.tags) == 2
        assert config.min_tags == 0
        assert config.max_tags == 2

    def test_empty_prompt_rejected(self):
        with self.assertRaises(Exception):
            LLMTaggerConfig(
                prompt="",
                tags=[TagDefinition(name="billing")],
            )

    def test_whitespace_prompt_rejected(self):
        with self.assertRaises(Exception):
            LLMTaggerConfig(
                prompt="   ",
                tags=[TagDefinition(name="billing")],
            )

    def test_empty_tags_list_rejected(self):
        with self.assertRaises(Exception):
            LLMTaggerConfig(
                prompt="Test prompt",
                tags=[],
            )

    def test_duplicate_tag_names_rejected(self):
        with self.assertRaises(Exception):
            LLMTaggerConfig(
                prompt="Test prompt",
                tags=[
                    TagDefinition(name="billing"),
                    TagDefinition(name="billing"),
                ],
            )

    def test_empty_tag_name_rejected(self):
        with self.assertRaises(Exception):
            TagDefinition(name="")

    def test_whitespace_tag_name_stripped(self):
        tag = TagDefinition(name="  billing  ")
        assert tag.name == "billing"

    def test_tag_description_optional(self):
        tag = TagDefinition(name="billing")
        assert tag.description == ""

    def test_min_tags_default_zero(self):
        config = LLMTaggerConfig(
            prompt="Test",
            tags=[TagDefinition(name="a")],
        )
        assert config.min_tags == 0

    def test_max_tags_default_none(self):
        config = LLMTaggerConfig(
            prompt="Test",
            tags=[TagDefinition(name="a")],
        )
        assert config.max_tags is None


class TestTaggerModel(BaseTest):
    def _make_tagger_config(self, **overrides):
        defaults = {
            "prompt": "Which product features were discussed?",
            "tags": [
                {"name": "billing", "description": "Billing related"},
                {"name": "analytics", "description": "Analytics related"},
            ],
            "min_tags": 0,
            "max_tags": 2,
        }
        return {**defaults, **overrides}

    def test_compiles_bytecode_for_conditions_with_properties(self):
        tagger = Tagger.objects.create(
            team=self.team,
            name="Test Tagger",
            tagger_config=self._make_tagger_config(),
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
                    ],
                }
            ],
        )

        tagger.refresh_from_db()

        assert len(tagger.conditions) == 1
        assert "bytecode" in tagger.conditions[0]
        assert tagger.conditions[0]["bytecode"] is not None
        assert isinstance(tagger.conditions[0]["bytecode"], list)

    def test_sets_bytecode_error_when_compilation_fails(self):
        with patch("posthog.cdp.filters.compile_filters_bytecode") as mock_compile:
            mock_compile.return_value = {"bytecode": None, "bytecode_error": "Invalid property filter"}

            tagger = Tagger.objects.create(
                team=self.team,
                name="Test Tagger",
                tagger_config=self._make_tagger_config(),
                enabled=True,
                created_by=self.user,
                conditions=[
                    {
                        "id": "cond-1",
                        "rollout_percentage": 100,
                        "properties": [{"key": "invalid"}],
                    }
                ],
            )

            tagger.refresh_from_db()

            assert len(tagger.conditions) == 1
            assert tagger.conditions[0]["bytecode_error"] == "Invalid property filter"

    def test_handles_empty_properties_list(self):
        tagger = Tagger.objects.create(
            team=self.team,
            name="Test Tagger",
            tagger_config=self._make_tagger_config(),
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [],
                }
            ],
        )

        tagger.refresh_from_db()

        assert len(tagger.conditions) == 1
        assert tagger.conditions[0]["properties"] == []
        assert "bytecode" in tagger.conditions[0]

    def test_compiles_bytecode_for_multiple_conditions(self):
        tagger = Tagger.objects.create(
            team=self.team,
            name="Test Tagger",
            tagger_config=self._make_tagger_config(),
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
                    ],
                },
                {
                    "id": "cond-2",
                    "rollout_percentage": 50,
                    "properties": [{"key": "name", "value": "test", "operator": "exact", "type": "person"}],
                },
            ],
        )

        tagger.refresh_from_db()

        assert len(tagger.conditions) == 2
        assert tagger.conditions[0]["bytecode"] is not None
        assert tagger.conditions[1]["bytecode"] is not None

    def test_preserves_other_condition_fields(self):
        tagger = Tagger.objects.create(
            team=self.team,
            name="Test Tagger",
            tagger_config=self._make_tagger_config(),
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "my-custom-id",
                    "rollout_percentage": 75,
                    "properties": [],
                }
            ],
        )

        tagger.refresh_from_db()

        assert tagger.conditions[0]["id"] == "my-custom-id"
        assert tagger.conditions[0]["rollout_percentage"] == 75

    def test_validates_tagger_config_on_save(self):
        tagger = Tagger.objects.create(
            team=self.team,
            name="Test Tagger",
            tagger_config=self._make_tagger_config(),
            enabled=True,
            created_by=self.user,
            conditions=[],
        )

        tagger.refresh_from_db()

        assert tagger.tagger_config["prompt"] == "Which product features were discussed?"
        assert len(tagger.tagger_config["tags"]) == 2
        assert tagger.tagger_config["tags"][0]["name"] == "billing"

    def test_invalid_tagger_config_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            Tagger.objects.create(
                team=self.team,
                name="Test Tagger",
                tagger_config={"prompt": "", "tags": []},
                enabled=True,
                created_by=self.user,
                conditions=[],
            )

    def test_tagger_config_strips_none_values(self):
        tagger = Tagger.objects.create(
            team=self.team,
            name="Test Tagger",
            tagger_config={
                "prompt": "Test",
                "tags": [{"name": "billing", "description": ""}],
                "min_tags": 0,
                "max_tags": None,
            },
            enabled=True,
            created_by=self.user,
            conditions=[],
        )

        tagger.refresh_from_db()

        # max_tags=None should be excluded
        assert "max_tags" not in tagger.tagger_config

    @patch("posthog.plugins.plugin_server_api.reload_taggers_on_workers")
    def test_sends_reload_signal_on_save(self, mock_reload):
        with self.captureOnCommitCallbacks(execute=True):
            tagger = Tagger.objects.create(
                team=self.team,
                name="Test Tagger",
                tagger_config=self._make_tagger_config(),
                enabled=True,
                created_by=self.user,
                conditions=[],
            )

        mock_reload.assert_called_once_with(team_id=self.team.id, tagger_ids=[str(tagger.id)])

    @patch("posthog.plugins.plugin_server_api.reload_taggers_on_workers")
    def test_sends_reload_signal_on_update(self, mock_reload):
        with self.captureOnCommitCallbacks(execute=True):
            tagger = Tagger.objects.create(
                team=self.team,
                name="Original Name",
                tagger_config=self._make_tagger_config(),
                enabled=True,
                created_by=self.user,
                conditions=[],
            )

        mock_reload.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            tagger.name = "Updated Name"
            tagger.save()

        mock_reload.assert_called_once_with(team_id=self.team.id, tagger_ids=[str(tagger.id)])
