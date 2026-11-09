import json
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.slack_app.backend.logic.reply_presentation import (
    PresentationAttribution,
    check_presentation,
    present_reply,
    presentation_blocks,
)

ANSWER = "Weekly signups reached 1,204, down -12% on last week. See https://us.posthog.com/project/2/insights/abc12"
INSIGHT_URL = "https://us.posthog.com/project/2/insights/abc12"


def _spec(metrics: list[dict[str, str]] | None = None, links: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"metrics": metrics or [], "links": links or []}


def _completion(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestCheckPresentation:
    @parameterized.expand(
        [
            (
                "grounded",
                _spec([{"label": "Signups", "value": "1,204"}], [{"label": "Open", "url": INSIGHT_URL}]),
                True,
            ),
            ("nothing_to_show", _spec(), True),
            ("invented_value", _spec([{"label": "Signups", "value": "1,300"}]), False),
            ("rounded_value", _spec([{"label": "Signups", "value": "1.2k"}]), False),
            ("url_not_in_answer", _spec(links=[{"label": "Open", "url": "https://example.com/x"}]), False),
            ("not_https", _spec(links=[{"label": "Open", "url": "javascript:alert(1)"}]), False),
            ("too_many_metrics", _spec([{"label": "Signups", "value": "1,204"}] * 5), False),
            ("unknown_component", {**_spec(), "table": []}, False),
            ("not_an_object", None, False),
        ]
    )
    def test_only_grounded_specs_inside_the_catalog_pass(
        self, _name: str, raw: dict[str, Any] | None, passes: bool
    ) -> None:
        check = check_presentation(raw, ANSWER)

        assert (check.spec is not None) == passes
        assert bool(check.errors) != passes

    def test_metric_text_cannot_inject_slack_mentions(self) -> None:
        check = check_presentation(_spec([{"label": "<!channel> Signups", "value": "1,204"}]), ANSWER)
        assert check.spec is not None

        text = presentation_blocks(check.spec)[0]["fields"][0]["text"]

        assert "<!channel>" not in text
        assert "&lt;!channel&gt;" in text


class TestPresentReply:
    @parameterized.expand(
        [
            ("first_try", ['{"metrics": [{"label": "Signups", "value": "1,204"}], "links": []}'], 1, True),
            (
                "repaired",
                [
                    '{"metrics": [{"label": "Signups", "value": "1,300"}], "links": []}',
                    '{"metrics": [{"label": "Signups", "value": "1,204"}], "links": []}',
                ],
                2,
                True,
            ),
            ("gives_up", ["not json", "still not json"], 2, False),
        ]
    )
    def test_invalid_specs_get_one_repair_with_the_errors(
        self, _name: str, replies: list[str], attempts: int, presented: bool
    ) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = [_completion(reply) for reply in replies]
        with patch(
            "products.slack_app.backend.logic.reply_presentation.build_ai_gateway_openai_client"
        ) as build_client:
            build_client.return_value.with_options.return_value = client

            presentation = present_reply(ANSWER, PresentationAttribution())

        assert presentation.attempts == attempts
        assert (presentation.spec is not None) == presented
        if attempts == 2:
            repair_request = client.chat.completions.create.call_args_list[1].kwargs["messages"][-1]["content"]
            assert "Fix these problems" in repair_request
            first_errors = check_presentation(json.loads(replies[0]) if replies[0].startswith("{") else None, ANSWER)
            assert all(error in repair_request for error in first_errors.errors)
