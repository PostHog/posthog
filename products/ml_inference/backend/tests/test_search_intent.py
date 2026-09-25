from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionResult,
    SearchIntent,
    SearchIntentRequest,
)
from products.ml_inference.backend.facade.enums import SearchIntentSource
from products.ml_inference.backend.logic.search_intent import classify_search_intent

ALL_TABS = ("suggested_filters", "events", "event_properties", "person_properties", "pageview_urls", "email_addresses")


def _search(
    query: str, available: tuple[str, ...] = ALL_TABS, active: str = "events", team_id: int = 7
) -> SearchIntentRequest:
    return SearchIntentRequest(
        team_id=team_id, query=query, active_group_type=active, available_group_types=available, scene="Insight"
    )


def _answer(choice: str, confidence: float) -> DecisionResult:
    return DecisionResult(
        model="jevk5-0.2",
        answers={"tab": ChoiceAnswer(choice=choice, confidence=confidence, probabilities={choice: confidence})},
        input_tokens=90,
    )


@patch("products.ml_inference.backend.logic.search_intent.decisions.decide")
class TestClassifySearchIntent(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

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
            ("id_like", "user 12345678", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("opaque_token", "sess_a1b2c3d4", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("too_short", "e", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("one_option_left", "email", ("events", "suggested_filters"), None, SearchIntentSource.SKIPPED),
        ]
    )
    def test_never_asks_the_model_about_values_or_unanswerable_searches(
        self, decide: MagicMock, _name: str, query: str, available: tuple[str, ...], expected: str | None, source
    ) -> None:
        intent = classify_search_intent(_search(query, available))

        assert (intent.group_type, intent.source) == (expected, source)
        decide.assert_not_called()

    def test_offers_only_the_tabs_the_picker_shows(self, decide: MagicMock) -> None:
        decide.return_value = _answer("person_properties", 0.9)

        intent = classify_search_intent(_search("email"))

        assert intent == SearchIntent(
            group_type="person_properties",
            confidence=0.9,
            is_confident=True,
            source=SearchIntentSource.MODEL,
            suggests_switch=True,
        )
        sent = decide.call_args.args[0]
        assert set(sent.questions["tab"].criteria) == {
            "events",
            "event_properties",
            "person_properties",
            "pageview_urls",
            "email_addresses",
        }
        assert "Search: email" in sent.state

    @parameterized.expand(
        [
            ("confident_other_tab", "person_properties", 0.9, "events", True),
            ("weak_answer", "person_properties", 0.3, "events", False),
            ("already_on_that_tab", "person_properties", 0.9, "person_properties", False),
            ("on_the_all_tab", "person_properties", 0.9, "suggested_filters", False),
        ]
    )
    def test_suggests_a_switch_only_for_a_confident_different_tab(
        self, decide: MagicMock, _name: str, choice: str, confidence: float, active: str, expected: bool
    ) -> None:
        decide.return_value = _answer(choice, confidence)

        assert classify_search_intent(_search("email", active=active)).suggests_switch is expected

    def test_an_answer_outside_the_offered_tabs_is_dropped(self, decide: MagicMock) -> None:
        decide.return_value = _answer("cohorts", 0.99)

        assert classify_search_intent(_search("paying users")).source == SearchIntentSource.SKIPPED

    def test_the_same_search_is_answered_once_per_team(self, decide: MagicMock) -> None:
        decide.return_value = _answer("event_properties", 0.8)

        first = classify_search_intent(_search("current url"))
        second = classify_search_intent(_search("  current   url "))
        assert first == second
        assert decide.call_count == 1

        classify_search_intent(_search("current url", team_id=8))
        assert decide.call_count == 2


class TestSearchIntentEndpoint(APIBaseTest):
    def _post(self, body: dict | None = None):
        return self.client.post(
            f"/api/projects/{self.team.id}/ml_inference/search_intent/classify/",
            body or {"query": "email", "active_group_type": "events", "available_group_types": list(ALL_TABS)},
            format="json",
        )

    @patch("products.ml_inference.backend.logic.search_intent.decisions.decide")
    @patch("products.ml_inference.backend.facade.api.decisions.decisions_enabled", return_value=True)
    def test_returns_the_tab_for_the_team(self, _enabled, decide) -> None:
        cache.clear()
        decide.return_value = _answer("person_properties", 0.9)

        response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "group_type": "person_properties",
            "confidence": 0.9,
            "is_confident": True,
            "suggests_switch": True,
            "method": "model",
        }
        assert decide.call_args.args[0].team_id == self.team.id

    @parameterized.expand(
        [
            ("disabled", False, None, status.HTTP_404_NOT_FOUND),
            ("unreachable", True, DecisionGatewayUnreachableError("timeout"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("refused", True, DecisionGatewayError(500, "boom"), status.HTTP_503_SERVICE_UNAVAILABLE),
        ]
    )
    def test_the_picker_gets_a_plain_failure_when_there_is_no_answer(
        self, _name, enabled, error, expected_status
    ) -> None:
        cache.clear()
        with (
            patch("products.ml_inference.backend.facade.api.decisions.decisions_enabled", return_value=enabled),
            patch("products.ml_inference.backend.logic.search_intent.decisions.decide", side_effect=error),
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
