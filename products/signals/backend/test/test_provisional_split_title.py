import pytest

from products.signals.backend.temporal.grouping import PROVISIONAL_TITLE_MAX_CHARS, provisional_split_title

TITLE_LINE = "The filter resets whenever the chart reloads"
OVERLONG_LINE = "The export dialog stays open after the download finishes and blocks the page behind it"


class TestProvisionalSplitTitle:
    @pytest.mark.parametrize(
        "description,expected",
        [
            # A transcript greeting is a fragment, so none of these has a line that reads as a title.
            ("C: Good morning,", "New conversations signal"),
            ("C: Good morning,\nC: one question", "New conversations signal"),
            ("", "New conversations signal"),
            ("   \n\t\n", "New conversations signal"),
            # The first line long enough to read as a title wins, with the speaker prefix removed.
            (f"C: Good morning,\nC: {TITLE_LINE}", TITLE_LINE),
            (f"Customer: {TITLE_LINE}", TITLE_LINE),
            # Transcript sources escape punctuation, which must not reach the title.
            (
                r"A: The filter resets itself whenever the chart reloads\.",
                "The filter resets itself whenever the chart reloads.",
            ),
            # Only a single letter or a role is a speaker, so a two-letter word stays as content.
            ("UI: the breakdown control stops responding", "UI: the breakdown control stops responding"),
            ("The    filter   resets  whenever the chart reloads", TITLE_LINE),
        ],
    )
    def test_builds_a_readable_title(self, description, expected):
        assert provisional_split_title(description, "conversations") == expected

    def test_long_line_is_truncated_on_a_word_boundary(self):
        title = provisional_split_title(OVERLONG_LINE, "replay_vision")

        assert title == "The export dialog stays open after the download finishes and blocks…"
        assert OVERLONG_LINE.startswith(title.removesuffix("…"))

    def test_line_at_the_limit_is_kept_whole(self):
        description = "x" * PROVISIONAL_TITLE_MAX_CHARS

        assert provisional_split_title(description, "conversations") == description

    @pytest.mark.parametrize(
        "source_product,expected",
        [
            ("conversations", "New conversations signal"),
            ("replay_vision", "New replay vision signal"),
            ("", "New signal"),
        ],
    )
    def test_fallback_names_the_source(self, source_product, expected):
        assert provisional_split_title("C: Hi", source_product) == expected
