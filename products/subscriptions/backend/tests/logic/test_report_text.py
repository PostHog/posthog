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

    assert rendered == "## Traffic\n\n- `12 requests`\n\n### Requests\n\n- `12 requests`"
    tokens = MarkdownIt("commonmark").parse(rendered)
    assert len([token for token in tokens if token.type == "list_item_open"]) == 2
    assert ReportSummary(findings=[finding]).render() == "- `12 requests`"


@pytest.mark.parametrize(("direction", "triangle"), [("increase", "▲"), ("decrease", "▼")])
def test_measured_changes_keep_their_direction(direction: str, triangle: str) -> None:
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

    assert summary.render() == f"- `Requests` changed by `{triangle} 12%`"


def _visual(text: str) -> ReportText:
    return ReportText(items=[ReportTextItem(kind="text", text=text)])


@pytest.mark.parametrize(
    ("visuals", "table_rows"),
    [
        (["| Alert type | Orgs |", "| --- | --- |", "| Trends threshold | 503 |", "| Logs threshold | 51 |"], [3]),
        (["| Alert type | Orgs |\n\n| --- | --- |\n\n| Trends threshold | 503 |"], [2]),
        (["| A | B |", "| --- | --- |", "| 1 | 2 |", "| C | D |", "| --- | --- |", "| 3 | 4 |"], [2, 2]),
        (["| A | B |", "| - | - |", "| 1 | 2 |", "| C | D |", "| :-- | -: |", "| 3 | 4 |"], [2, 2]),
    ],
    ids=["one_visual_per_row", "blank_lines_inside_one_visual", "two_tables_stay_apart", "short_separators"],
)
def test_table_visuals_render_as_markdown_tables(visuals: list[str], table_rows: list[int]) -> None:
    section = ReportSection(
        heading="Alert adoption",
        findings=[_visual("Every alert type dropped week over week.")],
        subsections=[],
        visuals=[_visual(text) for text in visuals],
    )
    document = ReportDocument(topic=None, sections=[section], custom_layout=[])

    tokens = MarkdownIt("commonmark").enable("table").parse(document.render())

    rows_per_table: list[int] = []
    for token in tokens:
        if token.type == "table_open":
            rows_per_table.append(0)
        elif token.type == "tr_open":
            rows_per_table[-1] += 1
    assert rows_per_table == table_rows


def test_styled_items_keep_their_spaces_outside_the_markers() -> None:
    finding = ReportText.model_validate(
        {
            "items": [
                {"kind": "name", "text": "Load `time` "},
                {"kind": "text", "text": "rose to"},
                {"kind": "value", "text": " 18s"},
                {"kind": "text", "text": " on"},
                {"kind": "time", "text": " Nov 4 "},
                {"kind": "text", "text": "after"},
                {"kind": "change", "text": " 3s ", "direction": "increase"},
                {"kind": "text", "text": "in a day."},
            ]
        }
    )

    assert ReportSummary(findings=[finding]).render() == "- `Load time` rose to `18s` on _Nov 4_ after `▲ 3s` in a day."
