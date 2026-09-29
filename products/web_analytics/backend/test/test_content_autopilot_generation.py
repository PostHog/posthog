from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import httpx
from anthropic import APIConnectionError
from parameterized import parameterized

from products.web_analytics.backend.content_autopilot.edits import PageEdit, apply_edits
from products.web_analytics.backend.content_autopilot.llm import ContentAutopilotLLMError, call_json


class _FakeStream:
    def __init__(self, events: Iterator[SimpleNamespace]) -> None:
        self._events = events

    def __iter__(self) -> Iterator[SimpleNamespace]:
        return self._events

    def close(self) -> None:
        pass


class _DroppingStreamClient:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def with_options(self, **kwargs: Any) -> "_DroppingStreamClient":
        return self

    def _create(self, **kwargs: Any) -> _FakeStream:
        self.calls += 1
        dropped = self.calls == 1

        def events() -> Iterator[SimpleNamespace]:
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text='{"ok": '))
            if dropped:
                raise httpx.RemoteProtocolError("peer closed connection")
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="true}"))
            yield SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"))

        return _FakeStream(events())


class TestCallJson(SimpleTestCase):
    def test_retries_a_stream_that_drops_mid_response(self) -> None:
        client = _DroppingStreamClient()

        with patch("products.web_analytics.backend.content_autopilot.llm.time.sleep"):
            result = call_json(client, system="s", user="u", schema={}, max_tokens=10, team_id=1)  # type: ignore[arg-type]

        assert result == {"ok": True}
        assert client.calls == 2

    def test_stops_retrying_at_the_callers_deadline(self) -> None:
        clock = SimpleNamespace(now=0.0)
        calls: list[float] = []

        def create(**kwargs: Any) -> _FakeStream:
            calls.append(kwargs["timeout"])
            raise APIConnectionError(request=httpx.Request("POST", "https://gateway.example.com"))

        def sleep(seconds: float) -> None:
            clock.now += seconds

        client = SimpleNamespace(with_options=lambda **kwargs: client, messages=SimpleNamespace(create=create))
        fake_time = SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep)

        with patch("products.web_analytics.backend.content_autopilot.llm.time", fake_time):
            with self.assertRaises(ContentAutopilotLLMError):
                call_json(client, system="s", user="u", schema={}, max_tokens=10, team_id=1, timeout_seconds=5.0)  # type: ignore[arg-type]

        assert calls == [5.0, 3.0]


EDITABLE_PAGE = """# Session replay

Old intro.

## What does it capture?

Clicks.

```bash
# install
```

### Console logs

Logs too.

## Pricing

Free.

```text
a


b
```

## Frequently asked questions

### Is it free?

Yes.
"""


class TestApplyEdits(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "replacing_a_section_drops_its_subsections",
                PageEdit(
                    action="replace_section",
                    heading="What does it capture?",
                    markdown="## What does it capture?\n\nEverything.",
                ),
                ["Everything.", "## Pricing"],
                ["Clicks.", "Console logs", "# install"],
                (),
            ),
            (
                "inserting_after_a_section_skips_its_subsections",
                PageEdit(
                    action="insert_after_section", heading="What does it capture?", markdown="## Is it private?\n\nYes."
                ),
                ["Logs too.", "## Is it private?", "## Pricing"],
                [],
                (),
            ),
            (
                "replacing_the_intro_keeps_the_title",
                PageEdit(action="replace_intro", heading="", markdown="New answer."),
                ["# Session replay", "New answer.", "## What does it capture?"],
                ["Old intro."],
                (),
            ),
            (
                "appending_lands_before_the_faq",
                PageEdit(action="append", heading="", markdown="## How do I start?\n\nInstall."),
                ["## Pricing", "## How do I start?", "## Frequently asked questions"],
                [],
                (),
            ),
            (
                "an_unknown_heading_is_appended_and_reported",
                PageEdit(action="replace_section", heading="Nope", markdown="## Setup\n\nSteps."),
                ["b\n```", "## Setup", "## Frequently asked questions"],
                [],
                ("Nope",),
            ),
        ]
    )
    def test_places_the_edit(
        self, _name: str, edit: PageEdit, ordered: list[str], absent: list[str], unplaced: tuple[str, ...]
    ) -> None:
        applied = apply_edits(EDITABLE_PAGE, [edit])

        positions = [applied.markdown.index(fragment) for fragment in ordered]
        assert positions == sorted(positions)
        assert all(fragment not in applied.markdown for fragment in absent)
        assert applied.unplaced == unplaced
        assert "a\n\n\nb" in applied.markdown
