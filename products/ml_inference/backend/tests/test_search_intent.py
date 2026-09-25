import threading
import dataclasses
from concurrent.futures import Future

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.ai.prompts import PromptResult
from rest_framework import status

from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import ChoiceAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult

from products.ml_inference.backend.facade.contracts import SearchIntent, SearchIntentRequest
from products.ml_inference.backend.facade.enums import SearchIntentSource
from products.ml_inference.backend.logic.search_intent import classify_search_intent
from products.ml_inference.backend.logic.search_intent_prompt import (
    BUNDLED_SEARCH_INTENT_PROMPT,
    SearchIntentPrompt,
    _PromptRefresher,
    parse_search_intent_prompt,
)

ALL_TABS = ("suggested_filters", "events", "event_properties", "person_properties", "pageview_urls", "email_addresses")


def _search(
    query: str, available: tuple[str, ...] = ALL_TABS, active: str = "events", team_id: int = 7
) -> SearchIntentRequest:
    return SearchIntentRequest(
        team_id=team_id, query=query, active_group_type=active, available_group_types=available, scene="Insight"
    )


BUILD_CLIENT = "products.ml_inference.backend.logic.search_intent.build_system_one_client"


def _answer(choice: str, confidence: float) -> SystemOneResult:
    return SystemOneResult(
        model="jevk5-0.2",
        answers={"tab": ChoiceAnswer(choice=choice, confidence=confidence, probabilities={choice: confidence})},
        input_tokens=90,
    )


class TestClassifySearchIntent(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        build = patch(BUILD_CLIENT).start()
        self.addCleanup(patch.stopall)
        self.decide = build.return_value.decide

    @parameterized.expand(
        [
            ("email_value", "ada@example.com", ALL_TABS, "email_addresses", SearchIntentSource.RULE),
            (
                "email_value_without_email_tab",
                "ada@example.com",
                ("events", "person_properties"),
                "person_properties",
                SearchIntentSource.RULE,
            ),
            ("partial_email", "ada@exa", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("url_value", "https://example.com/pricing", ALL_TABS, "pageview_urls", SearchIntentSource.RULE),
            ("path_value", "/pricing", ALL_TABS, "pageview_urls", SearchIntentSource.RULE),
            ("path_with_query", "/reset?token=abc", ALL_TABS, "pageview_urls", SearchIntentSource.RULE),
            (
                "path_without_url_tab",
                "/search?q=ada",
                ("events", "person_properties"),
                None,
                SearchIntentSource.SKIPPED,
            ),
            ("id_like", "user 12345678", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("opaque_token", "sess_a1b2c3d4", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("opaque_token_in_words", "session sess_a1b2c3d4", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("too_short", "e", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("one_option_left", "email", ("events", "suggested_filters"), None, SearchIntentSource.SKIPPED),
        ]
    )
    def test_never_asks_the_model_about_values_or_unanswerable_searches(
        self, _name: str, query: str, available: tuple[str, ...], expected: str | None, source
    ) -> None:
        intent = classify_search_intent(_search(query, available))

        assert (intent.group_type, intent.source) == (expected, source)
        self.decide.assert_not_called()

    def test_offers_only_the_tabs_the_picker_shows(self) -> None:
        self.decide.return_value = _answer("person_properties", 0.9)

        intent = classify_search_intent(_search("email"))

        assert intent == SearchIntent(
            group_type="person_properties",
            confidence=0.9,
            is_confident=True,
            source=SearchIntentSource.MODEL,
            suggests_switch=True,
        )
        sent = self.decide.call_args.kwargs
        assert set(sent["questions"]["tab"].criteria) == {
            "events",
            "event_properties",
            "person_properties",
            "pageview_urls",
            "email_addresses",
        }
        assert "Search: email" in sent["state"]

    @parameterized.expand(
        [
            ("confident_other_tab", "person_properties", 0.9, "events", True),
            ("weak_answer", "person_properties", 0.3, "events", False),
            ("already_on_that_tab", "person_properties", 0.9, "person_properties", False),
            ("on_the_all_tab", "person_properties", 0.9, "suggested_filters", False),
        ]
    )
    def test_suggests_a_switch_only_for_a_confident_different_tab(
        self, _name: str, choice: str, confidence: float, active: str, expected: bool
    ) -> None:
        self.decide.return_value = _answer(choice, confidence)

        assert classify_search_intent(_search("email", active=active)).suggests_switch is expected

    def test_an_answer_outside_the_offered_tabs_is_dropped(self) -> None:
        self.decide.return_value = _answer("cohorts", 0.99)

        assert classify_search_intent(_search("paying users")).source == SearchIntentSource.SKIPPED

    def test_asks_with_the_managed_prompt(self) -> None:
        self.decide.return_value = _answer("person_properties", 0.9)
        prompt = SearchIntentPrompt(
            instructions="Which tab?",
            options={"events": "An event.", "person_properties": "A person property."},
            confident_threshold=0.95,
            version=7,
        )

        intent = classify_search_intent(_search("email"), prompt=prompt)

        assert (intent.is_confident, intent.prompt_version) == (False, 7)
        question = self.decide.call_args.kwargs["questions"]["tab"]
        assert (question.instructions, question.criteria) == ("Which tab?", prompt.options)

    @parameterized.expand(
        [
            ("same_team_and_prompt", 7, BUNDLED_SEARCH_INTENT_PROMPT, 1),
            ("other_team", 8, BUNDLED_SEARCH_INTENT_PROMPT, 2),
            ("new_wording", 7, dataclasses.replace(BUNDLED_SEARCH_INTENT_PROMPT, instructions="Which tab?"), 2),
            ("new_threshold", 7, dataclasses.replace(BUNDLED_SEARCH_INTENT_PROMPT, confident_threshold=0.9), 2),
        ]
    )
    def test_the_same_search_is_answered_once_per_team_and_prompt(
        self, _name: str, second_team: int, second_prompt: SearchIntentPrompt, expected_calls: int
    ) -> None:
        self.decide.return_value = _answer("event_properties", 0.8)

        classify_search_intent(_search("current url"), prompt=BUNDLED_SEARCH_INTENT_PROMPT)
        classify_search_intent(_search("  current   url ", team_id=second_team), prompt=second_prompt)

        assert self.decide.call_count == expected_calls


MANAGED_OPTIONS = {"events": "An event.", "person_properties": "A person property."}


class TestSearchIntentPrompt(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "valid",
                {"options": MANAGED_OPTIONS, "confident_threshold": 0.7},
                MANAGED_OPTIONS,
                0.7,
            ),
            (
                "options_not_a_dict",
                {"options": ["events"], "confident_threshold": 0.7},
                BUNDLED_SEARCH_INTENT_PROMPT.options,
                0.7,
            ),
            (
                "blank_meaning",
                {"options": {"events": " "}, "confident_threshold": 0.7},
                BUNDLED_SEARCH_INTENT_PROMPT.options,
                0.7,
            ),
            (
                "threshold_out_of_range",
                {"options": MANAGED_OPTIONS, "confident_threshold": 60},
                MANAGED_OPTIONS,
                BUNDLED_SEARCH_INTENT_PROMPT.confident_threshold,
            ),
            (
                "more_options_than_the_gateway_takes",
                {"options": {f"tab_{i}": "A tab." for i in range(17)}, "confident_threshold": 0.7},
                BUNDLED_SEARCH_INTENT_PROMPT.options,
                0.7,
            ),
            ("no_config", None, BUNDLED_SEARCH_INTENT_PROMPT.options, BUNDLED_SEARCH_INTENT_PROMPT.confident_threshold),
        ]
    )
    def test_a_malformed_config_part_falls_back_to_the_bundled_part(
        self, _name: str, config: dict | None, options: dict[str, str], threshold: float
    ) -> None:
        prompt = parse_search_intent_prompt(
            PromptResult(source="api", prompt="Which tab?", name="n", version=4, config=config)
        )

        assert prompt == SearchIntentPrompt(
            instructions="Which tab?", options=options, confident_threshold=threshold, version=4
        )

    def test_the_sdk_fallback_is_the_bundled_prompt(self) -> None:
        result = PromptResult(source="code_fallback", prompt=BUNDLED_SEARCH_INTENT_PROMPT.instructions)

        assert parse_search_intent_prompt(result) is BUNDLED_SEARCH_INTENT_PROMPT

    def test_a_request_never_waits_for_the_prompt_fetch(self) -> None:
        managed = dataclasses.replace(BUNDLED_SEARCH_INTENT_PROMPT, instructions="Which tab?", version=3)
        release = threading.Event()
        fetches: list[Future] = []

        def slow_fetch(**_kwargs: object) -> SearchIntentPrompt:
            assert release.wait(timeout=5)
            return managed

        refresher = _PromptRefresher()
        submit = refresher._executor.submit
        with (
            patch("products.ml_inference.backend.logic.search_intent_prompt.fetch_search_intent_prompt", slow_fetch),
            patch.object(refresher._executor, "submit", side_effect=lambda fn: fetches.append(submit(fn))),
        ):
            assert refresher.current() is BUNDLED_SEARCH_INTENT_PROMPT
            assert refresher.current() is BUNDLED_SEARCH_INTENT_PROMPT
            release.set()
            fetches[0].result(timeout=5)

            assert refresher.current() == managed
            assert len(fetches) == 1


class TestSearchIntentEndpoint(APIBaseTest):
    def _post(self, body: dict | None = None):
        return self.client.post(
            f"/api/projects/{self.team.id}/ml_inference/search_intent/classify/",
            body or {"query": "email", "active_group_type": "events", "available_group_types": list(ALL_TABS)},
            format="json",
        )

    @patch(BUILD_CLIENT)
    @patch("products.ml_inference.backend.facade.api.decisions.decisions_enabled", return_value=True)
    def test_returns_the_tab_for_the_team(self, _enabled, build) -> None:
        cache.clear()
        build.return_value.decide.return_value = _answer("person_properties", 0.9)

        response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "group_type": "person_properties",
            "confidence": 0.9,
            "is_confident": True,
            "suggests_switch": True,
            "method": "model",
            "prompt_version": None,
        }
        assert build.call_args.kwargs["distinct_id"] == team_distinct_id(self.team.id)

    @parameterized.expand(
        [
            ("disabled", False, None, status.HTTP_404_NOT_FOUND),
            ("not_configured", True, SystemOneNotConfigured("no gateway"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("unreachable", True, SystemOneRequestFailed("timeout"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("refused", True, SystemOneRequestFailed("boom", status_code=500), status.HTTP_503_SERVICE_UNAVAILABLE),
        ]
    )
    def test_the_picker_gets_a_plain_failure_when_there_is_no_answer(
        self, _name, enabled, error, expected_status
    ) -> None:
        cache.clear()
        with (
            patch("products.ml_inference.backend.facade.api.decisions.decisions_enabled", return_value=enabled),
            patch(BUILD_CLIENT, side_effect=error),
        ):
            response = self._post()

        assert response.status_code == expected_status

    def test_rejects_a_scene_that_is_not_an_id(self) -> None:
        response = self._post(
            {
                "query": "email",
                "active_group_type": "events",
                "available_group_types": ["events"],
                "scene": "https://example.com/?email=ada@example.com",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
