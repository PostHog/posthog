import pytest

from markdown_it import MarkdownIt

from products.subscriptions.backend.logic.report_text import (
    ReportDocument,
    ReportSection,
    ReportSubsection,
    ReportText,
    ReportTextItem,
)
from products.subscriptions.backend.temporal.llm_change_summary import SlackSummaryContent


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
    assert SlackSummaryContent(findings=[finding]).render() == "• *12 requests*"
