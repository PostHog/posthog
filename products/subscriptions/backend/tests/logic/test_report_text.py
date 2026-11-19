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
    ("lines", "expected"),
    [
        (["First line", "Second line"], "First line\nSecond line"),
        (["First line\n", "Second line\n"], "First line\nSecond line\n"),
        (["First line", "\n", "Second line"], "First line\n\nSecond line"),
        (["First line", "", "Second line"], "First line\n\nSecond line"),
        (["First line", "\\n", "\\n", "Second line"], "First line\n\n\nSecond line"),
        (["First line\n\\n\nSecond line \\n"], "First line\n\nSecond line \\n"),
    ],
    ids=["per_line", "existing_newlines", "spacer", "empty_line", "literal_spacers", "literal_spacer_inside_a_part"],
)
def test_custom_layout_preserves_lines(lines: list[str], expected: str) -> None:
    document = ReportDocument(topic=None, sections=[], custom_layout=[_visual(line) for line in lines])

    assert document.render() == expected


def test_custom_layout_keeps_the_template_formatting() -> None:
    document = ReportDocument.model_validate(
        {
            "topic": None,
            "sections": [],
            "custom_layout": [
                {
                    "items": [
                        {"kind": "text", "text": "**"},
                        {"kind": "name", "text": "Daily jobs"},
                        {"kind": "text", "text": ": "},
                        {"kind": "value", "text": "7"},
                        {"kind": "text", "text": "**"},
                    ]
                },
                {"items": [{"kind": "text", "text": "Errors: "}, {"kind": "value", "text": "2"}]},
                {
                    "items": [
                        {"kind": "text", "text": "Change since "},
                        {"kind": "time", "text": "Monday"},
                        {"kind": "text", "text": ": "},
                        {"kind": "change", "text": "3", "direction": "increase"},
                    ]
                },
                {
                    "items": [
                        {"kind": "text", "text": "*"},
                        {"kind": "name", "text": "Signups"},
                        {"kind": "text", "text": "*"},
                        {"kind": "text", "text": "rose to"},
                        {"kind": "value", "text": "~158"},
                    ]
                },
            ],
        }
    )

    assert document.render() == "**Daily jobs: 7**\nErrors: 2\nChange since Monday: ▲ 3\n*Signups* rose to ~158"


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
