import pytest

from markdown_it import MarkdownIt

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
