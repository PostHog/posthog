from types import SimpleNamespace
from typing import Any, cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.today.backend.logic.writer import WriterError, WriterOutput, write

OUTPUT = WriterOutput.model_validate(
    {
        "headline": "One report needs your input this morning.",
        "paragraphs": [[{"text": "The checkout report", "item_key": "report:1", "highlight": True}]],
        "items": [
            {"item_key": "report:1", "label": "Checkout button hidden", "signal": "P2, waits for you"},
            {"item_key": "ticket:9", "label": "Ticket #1042", "signal": "6 unread messages"},
        ],
    }
)


def _response(stop_reason: str, parsed_output: WriterOutput | None) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed_output,
        usage=SimpleNamespace(input_tokens=3000, output_tokens=1000),
    )


class TestWrite(SimpleTestCase):
    def _write(self, response: SimpleNamespace) -> tuple[dict[str, Any], Any]:
        client = MagicMock()
        client.messages.parse.return_value = response
        with patch("products.today.backend.logic.writer.build_anthropic_client", return_value=client):
            return write(
                team=cast(Team, SimpleNamespace(id=1)),
                user=cast(User, SimpleNamespace(distinct_id="person-1")),
                fact_sheet={"items": []},
            )

    def test_items_become_the_stored_labels_and_signals(self) -> None:
        content, _cost = self._write(_response("end_turn", OUTPUT))

        assert content["labels"] == {"report:1": "Checkout button hidden", "ticket:9": "Ticket #1042"}
        assert content["signals"] == {"report:1": "P2, waits for you", "ticket:9": "6 unread messages"}
        assert content["paragraphs"][0][0] == {"text": "The checkout report", "item_key": "report:1", "highlight": True}

    @parameterized.expand([("refusal", "refusal", None), ("cut off", "max_tokens", OUTPUT)])
    def test_an_unfinished_answer_is_a_writer_error(
        self, _name: str, stop_reason: str, parsed_output: WriterOutput | None
    ) -> None:
        with self.assertRaises(WriterError):
            self._write(_response(stop_reason, parsed_output))
