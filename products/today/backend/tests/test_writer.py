from types import SimpleNamespace
from typing import cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from openai import LengthFinishReasonError
from parameterized import parameterized

from posthog.models import Team, User

from products.today.backend.logic.content import BriefingContent, ContentSegment
from products.today.backend.logic.writer import WriterError, WriterOutput, write
from products.today.backend.models import DailyBriefing
from products.today.backend.tests.test_checks import FACT_SHEET

OUTPUT = WriterOutput.model_validate(
    {
        "headline": "One report needs your input.",
        "paragraphs": [[{"text": "The checkout report", "item_key": "report:1", "highlight": True}]],
        "items": [
            {"item_key": "report:1", "label": "Checkout button hidden", "signal": "P2, waits for you"},
            {"item_key": "ticket:9", "label": "Ticket #1042", "signal": "6 unread messages"},
        ],
    }
)


def _response(finish_reason: str, parsed: WriterOutput | None, refusal: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class TestWrite(SimpleTestCase):
    def _write(self, response: SimpleNamespace | Exception) -> tuple[BriefingContent, MagicMock]:
        client = MagicMock()
        if isinstance(response, Exception):
            client.chat.completions.parse.side_effect = response
        else:
            client.chat.completions.parse.return_value = response
        with patch("products.today.backend.logic.writer.build_openai_client", return_value=client) as build:
            content = write(
                team=cast(Team, SimpleNamespace(id=1)),
                user=cast(User, SimpleNamespace(distinct_id="person-1")),
                briefing=cast(DailyBriefing, SimpleNamespace(id="b-1", edition="morning", trigger="schedule")),
                fact_sheet=FACT_SHEET,
                attempt=1,
            )
        return content, build

    def test_items_become_the_stored_labels_and_signals(self) -> None:
        content, _ = self._write(_response("stop", OUTPUT))

        assert content.labels == {"report:1": "Checkout button hidden", "ticket:9": "Ticket #1042"}
        assert content.signals == {"report:1": "P2, waits for you", "ticket:9": "6 unread messages"}
        assert content.paragraphs[0][0] == ContentSegment(
            text="The checkout report", item_key="report:1", highlight=True
        )

    def test_every_attempt_is_traced_under_its_briefing(self) -> None:
        _, build = self._write(_response("stop", OUTPUT))

        kwargs = build.call_args.kwargs
        assert kwargs["trace_id"] == "b-1"
        assert kwargs["ai_product"] == "today"
        assert kwargs["properties"]["today_attempt"] == "1"

    @parameterized.expand(
        [
            ("refusal", _response("stop", None, refusal="I cannot write that")),
            ("no parsed output", _response("content_filter", None)),
            ("cut off", LengthFinishReasonError(completion=MagicMock())),
        ]
    )
    def test_an_unfinished_answer_is_a_writer_error(self, _name: str, response: SimpleNamespace | Exception) -> None:
        with self.assertRaises(WriterError):
            self._write(response)
