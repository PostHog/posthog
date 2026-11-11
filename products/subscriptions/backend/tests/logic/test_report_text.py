import pytest

from markdown_it import MarkdownIt

from posthog.slack.markdown import slack_rich_text

from products.subscriptions.backend.logic.report_text import (
    ReportDocument,
    ReportSection,
    ReportSubsection,
    ReportSummary,
    ReportText,
    ReportTextItem,
)


@pytest.mark.parametrize("prefix", ["", "- ", "* ", "• ", "1. ", "- - "])
def test_findings_have_one_bullet(prefix: str) -> None:
    finding = ReportText(
        items=[ReportTextItem(kind="text", text=prefix), ReportTextItem(kind="value", text="12 requests")]
    )
    document = ReportDocument(
        topic=None,
        sections=[
            ReportSection(
                heading="Traffic",
                findings=[finding],
                subsections=[ReportSubsection(heading="Requests", findings=[finding], visuals=[])],
                visuals=[],
            )
        ],
        custom_layout=[],
    )

    rendered = document.render()

    assert rendered == "## Traffic\n\n- **12 requests**\n\n### Requests\n\n- **12 requests**"
    tokens = MarkdownIt("commonmark").parse(rendered)
    assert len([token for token in tokens if token.type == "list_item_open"]) == 2
    assert ReportSummary(findings=[finding]).render(slack_formatting=True) == "• *12 requests*"

    assert ReportSummary(findings=[finding]).render() == "- **12 requests**"


@pytest.mark.parametrize(("direction", "triangle"), [("increase", "▲"), ("decrease", "▼")])
def test_measured_changes_keep_their_direction_in_each_format(direction: str, triangle: str) -> None:
    finding = ReportText.model_validate(
        {
            "items": [
                {"kind": "name", "text": "Requests"},
                {"kind": "text", "text": " changed by "},
                {"kind": "change", "text": "12%", "direction": direction},
            ]
        }
    )
    summary = ReportSummary(findings=[finding])

    assert summary.render() == f"- **Requests** changed by **{triangle} 12%**"
    assert summary.render(slack_formatting=True) == f"• *Requests* changed by *{triangle} 12%*"


@pytest.mark.parametrize(
    ("items", "expected_email"),
    [
        (
            [
                {
                    "kind": "text",
                    "text": "Checkouts rose 18% to 2,340 on November 10, up from $1,150/day over the last 7 days.",
                }
            ],
            "- Checkouts rose **18%** to **2,340** on _November 10_, up from **$1,150**/day over _the last 7 days_.",
        ),
        (
            [{"kind": "text", "text": "Median load took 3h 15m on 2026-03-02 (Monday) and -4.5% on 4 March 2026."}],
            "- Median load took **3h 15m** on _2026-03-02_ (_Monday_) and **-4.5%** on _4 March 2026_.",
        ),
        (
            [
                {
                    "kind": "text",
                    "text": "In 2026, see `step_3 90d` and [Mar 3 report](https://example.com/r/2026-03-03) for 41 rows.",
                }
            ],
            "- In 2026, see `step_3 90d` and [Mar 3 report](https://example.com/r/2026-03-03) for **41** rows.",
        ),
        (
            [
                {"kind": "name", "text": "Checkouts"},
                {"kind": "text", "text": " reached "},
                {"kind": "value", "text": "2,340 orders"},
                {"kind": "text", "text": " on "},
                {"kind": "time", "text": "November 10"},
                {"kind": "text", "text": ", "},
                {"kind": "change", "text": "18%", "direction": "increase"},
                {"kind": "text", "text": " vs "},
                {"kind": "link", "text": "last week", "url": "https://example.com/p/7"},
                {"kind": "text", "text": "."},
            ],
            "- **Checkouts** reached **2,340 orders** on _November 10_, **▲ 18%** vs [last week](https://example.com/p/7).",
        ),
    ],
    ids=["untagged_values_and_dates", "untagged_durations_and_iso_dates", "code_and_link_labels", "tagged_items"],
)
def test_summary_styles_values_and_dates_regardless_of_tagging(items: list[dict], expected_email: str) -> None:
    summary = ReportSummary(findings=[ReportText.model_validate({"items": items})])

    assert summary.render() == expected_email
    assert summary.render(slack_formatting=True) == "• " + expected_email[2:].replace("**", "*")


def test_untagged_summary_reaches_slack_as_bold_and_italic_rich_text() -> None:
    summary = ReportSummary(
        findings=[ReportText(items=[ReportTextItem(kind="text", text="Signups hit 512 on Nov 4, up 9%.")])]
    )

    block = slack_rich_text(summary.render(slack_formatting=True), allowed_root="https://app.example.com/")

    section = block["elements"][0]["elements"][0]
    assert [(element["text"], element["style"]) for element in section["elements"]] == [
        ("Signups hit ", {}),
        ("512", {"bold": True}),
        (" on ", {}),
        ("Nov 4", {"italic": True}),
        (", up ", {}),
        ("9%", {"bold": True}),
        (".", {}),
    ]
