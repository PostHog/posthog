import pytest

from products.subscriptions.evals.styling import (
    ARM_STRUCTURED,
    DatesStyled,
    NamesTagged,
    NotMisstyled,
    ValuesStyled,
    extract_input_values,
)


def _output(rendered: str) -> dict:
    return {
        "arms": {ARM_STRUCTURED: rendered},
        "input_values": ["1,463", "18%", "4d 4h"],
        "input_names": ["Weekly signups", "Upgrades this week"],
    }


@pytest.mark.parametrize(
    ("rendered", "expected"),
    [
        (
            "• Weekly signups rose 18% to 1,463 on Nov 9, taking 4d 4h.",
            {"values_styled": 0.0, "dates_styled": 0.0, "names_tagged": 0.0, "not_misstyled": 1.0},
        ),
        (
            "• *Weekly signups* rose *18%* to *1,463* on _Nov 9_, taking _4d 4h_.",
            {"values_styled": 1.0, "dates_styled": 1.0, "names_tagged": 1.0, "not_misstyled": 1.0},
        ),
        (
            "• *Weekly signups* rose *18%* to 1,463 on *Nov 9*.",
            {"values_styled": 0.5, "dates_styled": 0.0, "names_tagged": 1.0, "not_misstyled": 0.0},
        ),
        (
            "• *Upgrades this week* hit *1,463*, see `*18%*`.",
            {"values_styled": 1.0, "dates_styled": None, "names_tagged": 1.0, "not_misstyled": 0.0},
        ),
        (
            "• *Weekly signups* reached *1,463* over the last _7 days_.",
            {"values_styled": 1.0, "dates_styled": 1.0, "names_tagged": 1.0, "not_misstyled": 1.0},
        ),
    ],
    ids=[
        "untagged",
        "fully_styled",
        "bold_date_and_unstyled_value",
        "date_word_in_name_and_styled_code",
        "window_qualifier_outside_italic",
    ],
)
def test_scorers_read_styles_as_slack_renders_them(rendered: str, expected: dict) -> None:
    output = _output(rendered)
    scores = {
        scorer.metric: scorer._run_eval_sync(output).score
        for scorer in (
            ValuesStyled(ARM_STRUCTURED),
            DatesStyled(ARM_STRUCTURED),
            NamesTagged(ARM_STRUCTURED),
            NotMisstyled(ARM_STRUCTURED),
        )
    }

    assert scores == expected


def test_input_values_keep_thousands_separators_and_durations() -> None:
    summary = (
        "- signed_up: latest=1,463 (2026-11-09), change=up 18%, avg=$1,067.50, max=4d 4h, window trend=up (4 points)"
    )

    assert set(extract_input_values([summary])) == {"1,463", "18%", "$1,067.50", "4d 4h"}
