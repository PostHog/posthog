import pytest
from unittest.mock import patch

from rest_framework import status

from products.replay_vision.backend.scanner_draft import DraftError, _build_user_content, _finalize, _LlmDraft
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_GENERATE_PATH = "products.replay_vision.backend.scanner_draft._generate"


def _draft(**overrides) -> _LlmDraft:
    base = {
        "scanner_type": "monitor",
        "name": "Checkout abandonment",
        "description": "Flags sessions where the user abandons checkout.",
        "prompt": "Did the user abandon checkout? Answer yes or no with a one-sentence reason.",
    }
    base.update(overrides)
    return _LlmDraft(**base)


class TestBuildUserContent:
    def test_surfaces_goal_and_taxonomy(self):
        content = _build_user_content(
            "find users who get stuck during onboarding", ["subscription_started"], ["/onboarding"]
        )

        assert "find users who get stuck during onboarding" in content
        assert "subscription_started" in content
        assert "/onboarding" in content

    def test_omits_empty_taxonomy_sections(self):
        content = _build_user_content("goal", [], [])

        assert "custom events" not in content
        assert "Screens/paths" not in content


class TestFinalize:
    def test_monitor_config_is_prompt_only(self):
        result = _finalize(_draft())

        assert result.scanner_type == "monitor"
        assert result.scanner_config == {
            "prompt": "Did the user abandon checkout? Answer yes or no with a one-sentence reason."
        }

    def test_classifier_tags_are_slugified_and_deduped(self):
        result = _finalize(
            _draft(
                scanner_type="classifier",
                tags=["Pricing Page", "pricing  page", "Abandoned Cart!", "   "],
                multi_label=True,
            )
        )

        assert result.scanner_config["tags"] == ["pricing_page", "abandoned_cart"]
        assert result.scanner_config["multi_label"] is True

    def test_scorer_scale_falls_back_when_inverted(self):
        result = _finalize(_draft(scanner_type="scorer", scale_min=10, scale_max=0, scale_label="frustration"))

        assert result.scanner_config["scale"] == {"min": 0, "max": 10, "label": "frustration"}

    def test_scorer_keeps_valid_scale_and_drops_blank_label(self):
        result = _finalize(_draft(scanner_type="scorer", scale_min=1, scale_max=5, scale_label="  "))

        assert result.scanner_config["scale"] == {"min": 1, "max": 5}

    def test_summarizer_carries_length(self):
        result = _finalize(_draft(scanner_type="summarizer", length="short"))

        assert result.scanner_config == {"prompt": _draft().prompt, "length": "short"}

    def test_blank_prompt_is_an_error(self):
        with pytest.raises(DraftError):
            _finalize(_draft(prompt="   "))


class TestDraftScannerEndpoint(_VisionAPITestCase):
    @property
    def draft_url(self) -> str:
        return f"{self.scanners_url}draft/"

    @patch(_GENERATE_PATH)
    def test_returns_normalized_draft(self, mock_generate):
        mock_generate.return_value = _draft(
            scanner_type="classifier",
            name="User intent",
            description="Tags each session by intent.",
            prompt="Classify the session by primary user intent.",
            tags=["Browsing", "Purchasing"],
            multi_label=False,
        )

        resp = self.client.post(self.draft_url, data={"goal": "understand what users come here to do"}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json() == {
            "name": "User intent",
            "description": "Tags each session by intent.",
            "scanner_type": "classifier",
            "scanner_config": {
                "prompt": "Classify the session by primary user intent.",
                "tags": ["browsing", "purchasing"],
                "multi_label": False,
            },
        }

    def test_requires_goal(self):
        resp = self.client.post(self.draft_url, data={}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @patch(_GENERATE_PATH, side_effect=DraftError("model down"))
    def test_model_failure_is_a_clean_503(self, _mock):
        resp = self.client.post(self.draft_url, data={"goal": "find rage clicks"}, format="json")

        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        # The raw error must not leak to the client.
        assert "model down" not in resp.content.decode()

    @patch(
        "products.replay_vision.backend.scanner_draft.genai.Client",
        side_effect=ValueError("Missing key inputs argument!"),
    )
    def test_client_construction_failure_is_a_clean_503(self, _mock):
        resp = self.client.post(self.draft_url, data={"goal": "find rage clicks"}, format="json")

        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_requires_ai_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        resp = self.client.post(self.draft_url, data={"goal": "find rage clicks"}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "allow AI analysis" in resp.content.decode()
