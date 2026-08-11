import pytest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import AIBurstRateThrottle

from products.posthog_ai.backend.models.assistant import CoreMemory
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.scanner_draft import (
    DraftError,
    _build_user_content,
    _business_context,
    _existing_scanners,
    _ExistingScanner,
    _finalize,
    _LlmDraft,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_GENERATE_PATH = "products.replay_vision.backend.scanner_draft._generate"


def _access_control(*, allow: bool) -> MagicMock:
    ac = MagicMock()
    ac.filter_queryset_by_access_level.side_effect = (lambda qs: qs) if allow else (lambda qs: qs.none())
    return ac


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
    def test_surfaces_goal_and_taxonomy_inside_the_untrusted_fence(self):
        content = _build_user_content(
            "find users who get stuck during onboarding", ["subscription_started"], ["/onboarding"]
        )

        assert "find users who get stuck during onboarding" in content
        fenced = content.split("<product-data>")[1].split("</product-data>")[0]
        assert "subscription_started" in fenced
        assert "/onboarding" in fenced

    def test_omits_empty_taxonomy_sections(self):
        content = _build_user_content("goal", [], [])

        assert "<product-data>" not in content
        assert "custom events" not in content
        assert "Screens/paths" not in content
        assert "business context" not in content
        assert "already has" not in content

    def test_surfaces_business_context_and_existing_scanners(self):
        scanner = _ExistingScanner(name="Checkout drop-off", scanner_type="monitor", gist="Flags abandoned checkouts.")
        content = _build_user_content(
            "goal", [], [], scanners=[scanner], business_context="Acme sells anvils to coyotes."
        )

        # Both grounding blocks must reach the model; losing one silently makes drafts generic again.
        assert "Acme sells anvils to coyotes." in content
        assert "Checkout drop-off (monitor): Flags abandoned checkouts." in content


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


class TestDraftGrounding(_VisionAPITestCase):
    def test_existing_scanners_respect_object_rbac(self):
        self._create_scanner(
            name="Checkout drop-off",
            scanner_type=ScannerType.MONITOR,
            description="Flags abandoned checkouts.",
            scanner_config={"prompt": "Did the user abandon checkout?"},
        )

        # A readable scanner is summarized for the prompt; an unreadable one must be filtered out entirely.
        allowed = _existing_scanners(self.team, _access_control(allow=True))
        assert allowed == [
            _ExistingScanner(name="Checkout drop-off", scanner_type="monitor", gist="Flags abandoned checkouts.")
        ]
        assert _existing_scanners(self.team, _access_control(allow=False)) == []

    def test_existing_scanner_gist_falls_back_to_prompt(self):
        self._create_scanner(
            name="Rage clicks",
            scanner_type=ScannerType.MONITOR,
            description="",
            scanner_config={"prompt": "Did the user rage click anywhere?"},
        )

        (scanner,) = _existing_scanners(self.team, _access_control(allow=True))
        assert scanner.gist == "Did the user rage click anywhere?"

    @patch("products.replay_vision.backend.scanner_draft.is_core_memory_disabled", return_value=False)
    def test_business_context_prefers_core_memory(self, _flag):
        CoreMemory.objects.create(team=self.team, text="Acme sells anvils to coyotes.")
        self.team.project.product_description = "an anvil shop"
        self.team.project.save()

        assert _business_context(self.team, self.user) == "Acme sells anvils to coyotes."

    @patch("products.replay_vision.backend.scanner_draft.is_core_memory_disabled", return_value=False)
    def test_business_context_falls_back_to_product_description(self, _flag):
        self.team.project.product_description = "an anvil shop"
        self.team.project.save()

        assert _business_context(self.team, self.user) == "an anvil shop"

    @patch("products.replay_vision.backend.scanner_draft.is_core_memory_disabled", return_value=True)
    def test_business_context_skips_core_memory_when_disabled(self, _flag):
        # Teams that opted out of Max's memory must not have it fed to the draft model either.
        CoreMemory.objects.create(team=self.team, text="Acme sells anvils to coyotes.")

        assert _business_context(self.team, self.user) == ""


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

    @patch("products.replay_vision.backend.scanner_draft.is_core_memory_disabled", return_value=False)
    @patch(_GENERATE_PATH)
    def test_grounds_the_model_call_in_scanners_and_business_context(self, mock_generate, _flag):
        mock_generate.return_value = _draft()
        self._create_scanner(
            name="Checkout drop-off",
            scanner_type=ScannerType.MONITOR,
            description="Flags abandoned checkouts.",
            scanner_config={"prompt": "Did the user abandon checkout?"},
        )
        CoreMemory.objects.create(team=self.team, text="Acme sells anvils to coyotes.")

        resp = self.client.post(self.draft_url, data={"goal": "like Checkout drop-off but for signup"}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.json()
        user_content = mock_generate.call_args.kwargs["user_content"]
        assert "Checkout drop-off (monitor): Flags abandoned checkouts." in user_content
        assert "Acme sells anvils to coyotes." in user_content

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

    @patch("products.replay_vision.backend.scanner_draft.is_core_memory_disabled", return_value=False)
    @patch(_GENERATE_PATH)
    def test_scoped_token_requests_exclude_business_context(self, mock_generate, _flag):
        # Core memory's own API is INTERNAL (session-only); a scoped key must not read it through here.
        mock_generate.return_value = _draft()
        CoreMemory.objects.create(team=self.team, text="Acme sells anvils to coyotes.")
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="draft-scope-test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=["replay_scanner:read", "session_recording:read"],
        )

        resp = self.client.post(
            self.draft_url, data={"goal": "find rage clicks"}, format="json", HTTP_AUTHORIZATION=f"Bearer {value}"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert "Acme sells anvils to coyotes." not in mock_generate.call_args.kwargs["user_content"]

    def test_is_gated_by_the_shared_ai_throttles(self):
        # Denying the throttle and asserting the status proves it is wired into the request path;
        # inspecting get_throttles() alone passes even if DRF never consults it.
        with (
            patch.object(AIBurstRateThrottle, "allow_request", return_value=False),
            patch.object(AIBurstRateThrottle, "wait", return_value=None),
        ):
            resp = self.client.post(self.draft_url, data={"goal": "find rage clicks"}, format="json")

        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
