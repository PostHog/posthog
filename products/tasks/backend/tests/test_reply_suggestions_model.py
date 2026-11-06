import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.reply_suggestions import ReplySuggestionAttribution, SuggestedReply, suggest_replies

ATTRIBUTION = ReplySuggestionAttribution(ai_product="posthog_ai", properties={})
OPEN_PR = SuggestedReply(label="Yes, open the PR", reply="Yes, open the pull request with the fix")
KEEP_LOCAL = SuggestedReply(label="No, keep it local", reply="No, keep the change local for now")


def _suggestion(label: str, reply: str) -> dict[str, str]:
    return {"label": label, "reply": reply}


def _completion(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestSuggestReplies(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "keeps_order_and_caps_count",
                json.dumps(
                    {
                        "suggestions": [
                            _suggestion(OPEN_PR.label, OPEN_PR.reply),
                            _suggestion(KEEP_LOCAL.label, KEEP_LOCAL.reply),
                            _suggestion("Add tests", "Add tests for the empty case too"),
                            _suggestion("Use option 2", "Use option 2"),
                        ]
                    }
                ),
                [OPEN_PR, KEEP_LOCAL, SuggestedReply(label="Add tests", reply="Add tests for the empty case too")],
            ),
            (
                # Slack rejects the whole message for one label over 75 characters.
                "drops_overlong_and_duplicate_labels",
                json.dumps(
                    {
                        "suggestions": [
                            _suggestion("x" * 76, "x"),
                            _suggestion(OPEN_PR.label, OPEN_PR.reply),
                            _suggestion("Yes,  open the PR", "Yes, open it"),
                            _suggestion("", "No label"),
                        ]
                    }
                ),
                [OPEN_PR],
            ),
            (
                "a_missing_reply_sends_the_label",
                json.dumps({"suggestions": [_suggestion("Use option 2", "")]}),
                [SuggestedReply(label="Use option 2", reply="Use option 2")],
            ),
            ("answer_asks_nothing", json.dumps({"suggestions": []}), []),
            ("prose_instead_of_json", "Sure, here are some ideas", []),
            ("wrong_shape", json.dumps({"suggestions": "Yes"}), []),
        ]
    )
    def test_suggestions_from_model_reply(self, _name: str, content: str, expected: list[SuggestedReply]) -> None:
        with patch("products.tasks.backend.logic.reply_suggestions.build_ai_gateway_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.return_value = _completion(content)
            assert suggest_replies("Should I open a PR?", ATTRIBUTION) == expected

    @parameterized.expand([(False, None), (True, {"X-PostHog-Privacy-Mode": "true"})])
    def test_privacy_mode_asks_the_gateway_not_to_record_the_prompt(self, privacy_mode: bool, headers) -> None:
        attribution = ReplySuggestionAttribution(ai_product="posthog_ai", properties={}, privacy_mode=privacy_mode)
        with patch("products.tasks.backend.logic.reply_suggestions.build_ai_gateway_openai_client") as build:
            create = build.return_value.with_options.return_value.chat.completions.create
            create.return_value = _completion(json.dumps({"suggestions": []}))
            suggest_replies("Should I open a PR?", attribution)

        assert create.call_args.kwargs.get("extra_headers") == headers

    def test_model_failure_offers_nothing(self) -> None:
        with patch("products.tasks.backend.logic.reply_suggestions.build_ai_gateway_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.side_effect = TimeoutError()
            assert suggest_replies("Should I open a PR?", ATTRIBUTION) == []

    def test_the_person_message_reaches_the_model_apart_from_the_answer(self) -> None:
        with patch("products.tasks.backend.logic.reply_suggestions.build_ai_gateway_openai_client") as build:
            create = build.return_value.with_options.return_value.chat.completions.create
            create.return_value = _completion(json.dumps({"suggestions": []}))
            suggest_replies("Should I open a PR?", ATTRIBUTION, "Why does the retry never stop?")

        content = create.call_args.kwargs["messages"][1]["content"]
        assert content == (
            "<person_message>\nWhy does the retry never stop?\n</person_message>\n\n"
            "<agent_answer>\nShould I open a PR?\n</agent_answer>"
        )
