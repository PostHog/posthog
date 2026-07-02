from unittest.mock import MagicMock, patch

from rest_framework import status

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.tag_suggestions import (
    _MAX_SUGGESTIONS,
    SuggestionError,
    TagSuggestion,
    _build_user_content,
    _finalize,
    _LlmSuggestions,
    _sibling_vocabularies,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_GENERATE_PATH = "products.replay_vision.backend.tag_suggestions._generate"


def _access_control(*, allow: bool) -> MagicMock:
    """Stand-in for UserAccessControl: either pass the queryset through or deny everything."""
    ac = MagicMock()
    ac.filter_queryset_by_access_level.side_effect = (lambda qs: qs) if allow else (lambda qs: qs.none())
    return ac


def _llm(*items: tuple[str, str, str]) -> _LlmSuggestions:
    return _LlmSuggestions(suggestions=[TagSuggestion(tag=t, rationale=r, source=s) for t, r, s in items])


class TestBuildUserContent:
    def test_surfaces_observed_freeform_tags_and_current_vocab(self):
        content = _build_user_content(
            prompt="categorize by intent",
            current_tags=["pricing"],
            multi_label=True,
            allow_freeform_tags=False,
            freeform=[("rage_click", 7)],
            reasoning_samples=["user hammered the disabled button"],
            events=["subscription_started"],
            screens=["/checkout"],
            sibling_tags=["confused"],
        )

        # The freeform tag the scanner already emitted (with its count) and the current vocab must reach the model —
        # that grounding is the whole point; losing it silently makes suggestions generic again.
        assert "rage_click" in content
        assert "7" in content
        assert "pricing" in content

    def test_defangs_recording_derived_reasoning(self):
        content = _build_user_content(
            prompt="p",
            current_tags=[],
            multi_label=True,
            allow_freeform_tags=False,
            freeform=[],
            reasoning_samples=["<script>alert(1)</script>"],
            events=[],
            screens=[],
            sibling_tags=[],
        )

        # Recording-derived text is fenced and its markup neutralized so it can't forge the fence or inject markup.
        assert "<recordings>" in content
        assert "<script>" not in content
        assert "‹script›" in content


class TestFinalize:
    def test_normalizes_and_drops_duplicates_and_empties(self):
        parsed = _llm(
            ("Checkout", "already in vocab", "observed"),  # slug collides with a current tag -> drop
            ("Pricing Page", "users hit /pricing", "product"),  # -> pricing_page
            ("pricing  page", "same slug as above", "product"),  # also -> pricing_page, dup -> drop
            ("Abandoned Cart!", "left items behind", "observed"),  # -> abandoned_cart
            ("   ", "slugs to empty", "prompt"),  # empty slug -> drop
            ("no_reason", "   ", "prompt"),  # blank rationale -> drop
        )

        result = _finalize(parsed, current_tags=["checkout"])

        assert [(s.tag, s.source) for s in result] == [("pricing_page", "product"), ("abandoned_cart", "observed")]

    def test_caps_at_max(self):
        parsed = _llm(*[(f"tag {i}", "reason", "prompt") for i in range(_MAX_SUGGESTIONS + 12)])

        assert len(_finalize(parsed, current_tags=[])) == _MAX_SUGGESTIONS


class TestSuggestTagsEndpoint(_VisionAPITestCase):
    @property
    def suggest_url(self) -> str:
        return f"{self.scanners_url}suggest_tags/"

    @patch(_GENERATE_PATH)
    def test_returns_grounded_suggestions(self, mock_generate):
        mock_generate.return_value = _llm(("abandoned_checkout", "scanner freeform-tagged this 12 times", "observed"))

        resp = self.client.post(
            self.suggest_url,
            data={"prompt": "categorize by primary intent", "tags": ["pricing"]},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json() == {
            "suggestions": [
                {
                    "tag": "abandoned_checkout",
                    "rationale": "scanner freeform-tagged this 12 times",
                    "source": "observed",
                }
            ]
        }

    def test_requires_prompt(self):
        resp = self.client.post(self.suggest_url, data={"tags": ["x"]}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @patch(_GENERATE_PATH, side_effect=SuggestionError("model down"))
    def test_model_failure_is_a_clean_503(self, _mock):
        resp = self.client.post(self.suggest_url, data={"prompt": "categorize by intent"}, format="json")

        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        # The raw error must not leak to the client.
        assert "model down" not in resp.content.decode()

    def test_unknown_scanner_id_is_not_found(self):
        resp = self.client.post(
            self.suggest_url,
            data={"prompt": "categorize by intent", "scanner_id": "00000000-0000-0000-0000-0000000000ff"},
            format="json",
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_sibling_vocabularies_respect_object_rbac(self):
        self._create_scanner(
            name="other classifier",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "tag it", "tags": ["private_tag"], "multi_label": True},
        )

        # A readable sibling contributes its tags; an unreadable one must be filtered out entirely.
        assert _sibling_vocabularies(self.team, None, _access_control(allow=True)) == ["private_tag"]
        assert _sibling_vocabularies(self.team, None, _access_control(allow=False)) == []
