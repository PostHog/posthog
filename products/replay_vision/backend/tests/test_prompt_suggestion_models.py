from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import ReplayScannerPromptSuggestion
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class TestSuggestionConfigFields(_VisionAPITestCase):
    def test_config_fields_default_and_persist(self) -> None:
        scanner = self._create_scanner(scanner_type="classifier")
        suggestion = ReplayScannerPromptSuggestion.objects.create(
            scanner=scanner,
            team_id=scanner.team_id,
            suggested_prompt="p",
            base_prompt="p",
            base_config={"prompt": "p", "tags": ["a"]},
            suggested_config={"prompt": "p", "tags": ["a", "b"]},
            changes=[
                {"field": "tags", "kind": "tags", "op": "add", "before": ["a"], "after": ["a", "b"], "rationale": "x"}
            ],
        )
        suggestion.refresh_from_db()
        assert suggestion.suggested_config == {"prompt": "p", "tags": ["a", "b"]}
        assert suggestion.changes == [
            {"field": "tags", "kind": "tags", "op": "add", "before": ["a"], "after": ["a", "b"], "rationale": "x"}
        ]

    def test_config_fields_null_by_default(self) -> None:
        scanner = self._create_scanner(scanner_type="monitor")
        suggestion = ReplayScannerPromptSuggestion.objects.create(
            scanner=scanner, team_id=scanner.team_id, suggested_prompt="p", base_prompt="p"
        )
        assert suggestion.base_config is None
        assert suggestion.suggested_config is None
        assert suggestion.changes == []
