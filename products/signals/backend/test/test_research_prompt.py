from datetime import datetime

import pytest

from products.signals.backend.report_generation.research import _render_signal_for_research
from products.signals.backend.temporal.types import SignalData


def _make_signal(extra: dict) -> SignalData:
    return SignalData(
        signal_id="sig-1",
        content="Thing is broken",
        source_product="conversations",
        source_type="ticket",
        source_id="t-1",
        weight=1.0,
        timestamp=datetime(2026, 4, 1, 12, 0, 0),
        extra=extra,
    )


class TestRenderSignalForResearch:
    def test_renders_attached_images_with_author_prefix(self):
        signal = _make_signal(
            {
                "images": [
                    {"url": "https://media.posthog.com/a.png", "author": "customer"},
                    {"url": "https://media.posthog.com/b.png", "author": "team"},
                ]
            }
        )

        rendered = _render_signal_for_research(signal, index=1, total=1)

        assert (
            "- images: [customer] https://media.posthog.com/a.png, [team] https://media.posthog.com/b.png"
        ) in rendered

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"images": []},
            {"images": None},
        ],
    )
    def test_omits_attached_images_line_when_empty_or_missing(self, extra):
        signal = _make_signal(extra)

        rendered = _render_signal_for_research(signal, index=1, total=1)

        assert "- images:" not in rendered

    def test_skips_image_entries_without_url(self):
        signal = _make_signal(
            {
                "images": [
                    {"url": "", "author": "customer"},
                    {"author": "team"},
                    {"url": "https://media.posthog.com/ok.png", "author": "customer"},
                ]
            }
        )

        rendered = _render_signal_for_research(signal, index=1, total=1)

        assert "- images: [customer] https://media.posthog.com/ok.png" in rendered
        assert "[team]" not in rendered
