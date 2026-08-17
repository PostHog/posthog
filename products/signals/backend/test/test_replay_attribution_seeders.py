from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.signals.evals.constants import (
    DATA_MODULE,
    ELEMENT_TEXT_CASE,
    EXCEPTION_CASE,
    UPLOAD_BUTTON_TEXT,
    AttributionCase,
)
from products.signals.evals.seeders import seed_element_text_attribution, seed_exception_attribution
from products.tasks.backend.logic.services.custom_prompt_internals import CustomPromptSandboxContext

_WINDOW_SECONDS = 5
# The window the eval's own skill prescribes: session-scoped, five seconds either side of the anchor.
_WINDOW_QUERY = f"""
SELECT event, elements_chain_texts, elements_chain_ids, JSONExtract(properties, '$exception_sources', 'Array(String)')
FROM events
WHERE team_id = %(team_id)s
  AND JSONExtractString(properties, '$session_id') = %(session_id)s
  AND timestamp >= toDateTime64(%(anchor)s, 6) - INTERVAL {_WINDOW_SECONDS} SECOND
  AND timestamp <= toDateTime64(%(anchor)s, 6) + INTERVAL {_WINDOW_SECONDS} SECOND
ORDER BY timestamp ASC
"""


class TestReplayAttributionSeeders(ClickhouseTestMixin, BaseTest):
    def _seed(self, seeder: Any) -> list[tuple]:
        seed = seeder(CustomPromptSandboxContext(team_id=self.team.id, user_id=self.user.id))
        return sync_execute(
            _WINDOW_QUERY,
            {"team_id": self.team.id, "session_id": seed["session_id"], "anchor": seed["anchor"]},
        )

    # Every case's score depends on the event at the finding's instant being reachable by exactly this
    # query. A wrong property key or a timestamp off by more than the window returns nothing, the case
    # falls back to attributing by route, and the suite reports an attribution regression that never
    # happened. Events seeded outside the window are context (a pageview well before the click), so
    # the expectation is the window's contents, not everything the case seeds.
    @parameterized.expand(
        [
            (seed_element_text_attribution, ELEMENT_TEXT_CASE),
            (seed_exception_attribution, EXCEPTION_CASE),
        ]
    )
    def test_seeded_anchor_event_is_reachable_by_the_window_query(self, seeder: Any, case: AttributionCase) -> None:
        rows = self._seed(seeder)
        in_window = {event.event for event in case.events if abs(event.offset_seconds) <= _WINDOW_SECONDS}
        assert in_window, "case seeds nothing at its own anchor"
        assert {row[0] for row in rows} == in_window

    # `elements_chain_texts` is a ClickHouse MATERIALIZED column that regex-extracts `text="..."` out
    # of the raw chain. A chain written in the wrong shape inserts fine and silently extracts nothing,
    # leaving the text tier with no anchor while the seed still looks like it worked.
    def test_seeded_element_chain_yields_the_on_screen_text(self) -> None:
        rows = self._seed(seed_element_text_attribution)
        texts = {text for row in rows for text in row[1]}
        assert UPLOAD_BUTTON_TEXT in texts

    # Hedgebox carries no ids anywhere, so the identifier tier is genuinely absent. If ids ever start
    # appearing here, the suite is no longer testing the fixture it documents.
    def test_seeded_element_chain_carries_no_identifiers(self) -> None:
        rows = self._seed(seed_element_text_attribution)
        assert not [entry for row in rows for entry in row[2]]

    # The strongest anchor is only strong if it survives the round trip as an array.
    def test_seeded_exception_carries_the_source_file(self) -> None:
        rows = self._seed(seed_exception_attribution)
        sources = [source for row in rows for source in row[3]]
        assert DATA_MODULE in sources
