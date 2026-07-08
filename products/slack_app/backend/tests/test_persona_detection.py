import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from products.slack_app.backend import persona_onboarding
from products.slack_app.backend.services import slack_search

WORKSPACE = "T1"
SLACK_USER = "U1"


def _slack(missing_scopes: set[str] | None = None, title: str = "") -> MagicMock:
    slack = MagicMock()
    slack.missing_scopes.return_value = missing_scopes or set()
    slack.client.users_info.return_value = {"user": {"profile": {"title": title}}}
    return slack


def _authored(count: int) -> list[dict]:
    return [{"user": SLACK_USER, "text": "…"} for _ in range(count)]


def _fake_search(csm_results: list[dict], engineer_results: list[dict]):
    def fake(slack, *, action_token, query, **kwargs):
        if query == persona_onboarding._CSM_MESSAGE_QUERY:
            return csm_results
        if query == persona_onboarding._ENGINEER_MESSAGE_QUERY:
            return engineer_results
        return []

    return fake


class TestPersonaDetection:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        cache.clear()
        yield
        cache.clear()

    def _enable_search(self) -> None:
        slack_search.cache_action_token(WORKSPACE, SLACK_USER, "tok-1")

    @parameterized.expand(
        [
            ("clear_csm_margin", 3, 0, "csm"),
            ("clear_engineer_margin", 0, 3, "engineer"),
            ("csm_exactly_at_ratio", 6, 3, "csm"),
            ("below_min_hits", 2, 0, None),
            ("ambiguous_margin", 4, 3, None),
        ]
    )
    def test_message_scores_decide_candidate_only_with_clear_margin(self, _name, csm_hits, engineer_hits, expected):
        self._enable_search()
        with patch.object(slack_search, "search_messages", _fake_search(_authored(csm_hits), _authored(engineer_hits))):
            candidate, source = persona_onboarding.detect_persona(_slack(), WORKSPACE, SLACK_USER)
        if expected is None:
            assert source != persona_onboarding.DETECTION_SOURCE_MESSAGES
        else:
            assert (candidate, source) == (expected, persona_onboarding.DETECTION_SOURCE_MESSAGES)

    def test_other_authors_messages_do_not_count(self, monkeypatch):
        self._enable_search()
        other_authored = [{"user": "U_SOMEONE_ELSE", "text": "renewal QBR"} for _ in range(10)]
        monkeypatch.setattr(slack_search, "search_messages", _fake_search(other_authored, []))
        candidate, source = persona_onboarding.detect_persona(
            _slack(title="Customer Success Manager"), WORKSPACE, SLACK_USER
        )
        assert (candidate, source) == ("csm", persona_onboarding.DETECTION_SOURCE_TITLE)

    def test_ambiguous_messages_fall_through_to_title(self, monkeypatch):
        self._enable_search()
        monkeypatch.setattr(slack_search, "search_messages", _fake_search([], []))
        candidate, source = persona_onboarding.detect_persona(
            _slack(title="Senior Software Engineer"), WORKSPACE, SLACK_USER
        )
        assert (candidate, source) == ("engineer", persona_onboarding.DETECTION_SOURCE_TITLE)

    @parameterized.expand(
        [
            ("no_cached_token", None),
            ("missing_scope", {"search:read.public"}),
        ]
    )
    def test_search_unavailable_falls_to_title(self, _name, missing_scopes):
        if missing_scopes is not None:
            self._enable_search()

        def boom(*args, **kwargs):
            raise AssertionError("search must not be called when unavailable")

        with patch.object(slack_search, "search_messages", boom):
            candidate, source = persona_onboarding.detect_persona(
                _slack(missing_scopes=missing_scopes or set(), title="CSM, EMEA"), WORKSPACE, SLACK_USER
            )
        assert (candidate, source) == ("csm", persona_onboarding.DETECTION_SOURCE_TITLE)

    @parameterized.expand(
        [
            ("empty_title", ""),
            ("unrecognized_title", "Chief Vibes Officer"),
        ]
    )
    def test_no_signal_anywhere_returns_none(self, _name, title):
        candidate, source = persona_onboarding.detect_persona(_slack(title=title), WORKSPACE, SLACK_USER)
        assert (candidate, source) == (None, None)

    def test_title_fetch_error_returns_none(self):
        slack = _slack()
        slack.client.users_info.side_effect = RuntimeError("slack down")
        candidate, source = persona_onboarding.detect_persona(slack, WORKSPACE, SLACK_USER)
        assert (candidate, source) == (None, None)


class TestToolDetection:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        cache.clear()
        yield
        cache.clear()

    @parameterized.expand(
        [
            ("above_threshold", 3, ["Linear"]),
            ("below_threshold", 2, []),
        ]
    )
    def test_tool_detected_only_at_hit_threshold(self, _name, hit_count, expected):
        slack_search.cache_action_token(WORKSPACE, SLACK_USER, "tok-1")

        def fake(slack, *, action_token, query, **kwargs):
            return [{"user": "U_ANY"}] * hit_count if query == "linear.app" else []

        with patch.object(slack_search, "search_messages", fake):
            assert persona_onboarding.detect_workspace_tools(_slack(), WORKSPACE, SLACK_USER) == expected

    def test_unavailable_search_returns_no_tools(self, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError("search must not be called when unavailable")

        monkeypatch.setattr(slack_search, "search_messages", boom)
        assert persona_onboarding.detect_workspace_tools(_slack(), WORKSPACE, SLACK_USER) == []


class TestSlackSearchDegradation:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        cache.clear()
        yield
        cache.clear()

    @parameterized.expand(
        [
            ("api_error", RuntimeError("rate limited"), None),
            ("malformed_response", None, {"ok": True}),
            ("results_not_a_list", None, {"ok": True, "results": {"messages": "nope"}}),
        ]
    )
    def test_search_messages_returns_empty_on_failure(self, _name, side_effect, return_value):
        slack = MagicMock()
        if side_effect is not None:
            slack.client.api_call.side_effect = side_effect
        else:
            slack.client.api_call.return_value = return_value
        assert slack_search.search_messages(slack, action_token="tok", query="q") == []

    def test_search_messages_returns_result_messages(self):
        slack = MagicMock()
        slack.client.api_call.return_value = {"ok": True, "results": {"messages": [{"user": "U2"}]}}
        assert slack_search.search_messages(slack, action_token="tok", query="q") == [{"user": "U2"}]

    @parameterized.expand(
        [
            ("token_and_user", {"action_token": "tok-9", "user": SLACK_USER}, "tok-9"),
            ("missing_token", {"user": SLACK_USER}, None),
            ("missing_user", {"action_token": "tok-9"}, None),
            ("non_string_token", {"action_token": 7, "user": SLACK_USER}, None),
        ]
    )
    def test_cache_action_token_from_event_guards(self, _name, event, expected):
        slack_search.cache_action_token_from_event(WORKSPACE, event)
        assert slack_search.get_cached_action_token(WORKSPACE, SLACK_USER) == expected
