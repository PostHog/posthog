from django.test import SimpleTestCase

from parameterized import parameterized

from products.replay_vision.backend import feedback_themes, prompt_suggestions, tag_suggestions
from products.replay_vision.backend.models.replay_scanner import ScannerModel


class TestInteractiveHelperModel(SimpleTestCase):
    @parameterized.expand(
        [
            ("tag_suggestions", tag_suggestions._SUGGESTION_MODEL),
            ("prompt_suggestions", prompt_suggestions._SUGGESTION_MODEL),
            ("feedback_themes", feedback_themes._THEMES_MODEL),
        ]
    )
    def test_helper_uses_a_supported_non_retired_model(self, _name: str, model: str) -> None:
        # Guards the outage where these helpers pointed at a retired preview model id that the Gemini
        # API no longer served, 503-ing every "Suggest with PostHog AI" click. A model that isn't a
        # live ScannerModel choice is exactly that class of bug.
        assert model in set(ScannerModel.values)
