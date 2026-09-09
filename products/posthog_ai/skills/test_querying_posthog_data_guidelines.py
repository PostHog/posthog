import re
from pathlib import Path

from posthog.hogql.functions.mapping import find_hogql_aggregation, find_hogql_function, find_hogql_posthog_function

GUIDELINES = Path(__file__).parent / "querying-posthog-data" / "references" / "guidelines.md"
TABLE_HEADING = "##### Unsupported/changed functions"

# Rows about call syntax rather than whether the name exists. HogQL resolves these
# names; the guidance is about the arguments or the window clause they need.
SYNTAX_ONLY_NAMES = {"LAG", "LEAD", "count"}

FUNCTION_IN_BACKTICKS = re.compile(r"`(\w+)\(")


def _resolves(name: str) -> bool:
    return bool(find_hogql_function(name) or find_hogql_aggregation(name) or find_hogql_posthog_function(name))


def _rows() -> list[tuple[str, str]]:
    lines = GUIDELINES.read_text().splitlines()
    assert TABLE_HEADING in lines, f"{TABLE_HEADING} is gone from guidelines.md — retarget this test"
    start = lines.index(TABLE_HEADING)
    rows = []
    for line in lines[start + 1 :]:
        if line.startswith("#####"):
            break
        # Prose under the table names supported functions; only pipe rows are claims.
        if "|" not in line:
            continue
        dont_use, _, use_instead = line.partition("|")
        rows.append((dont_use, use_instead))
    return rows


def test_recommended_replacements_exist_in_hogql() -> None:
    # A guidelines row that names a function HogQL does not have sends every agent
    # reading it straight into a query error.
    missing = [
        name for _, use_instead in _rows() for name in FUNCTION_IN_BACKTICKS.findall(use_instead) if not _resolves(name)
    ]
    assert not missing, (
        f"guidelines.md recommends functions HogQL does not support: {missing}. "
        "Check posthog/hogql/functions/ for the supported name."
    )


def test_discouraged_functions_are_really_unsupported() -> None:
    # The reverse drift is quieter and just as costly: once HogQL gains a function,
    # a row still listing it makes agents rewrite working SQL or report it as broken.
    supported = [
        name
        for dont_use, _ in _rows()
        for name in FUNCTION_IN_BACKTICKS.findall(dont_use)
        if name not in SYNTAX_ONLY_NAMES and _resolves(name)
    ]
    assert not supported, (
        f"guidelines.md tells agents not to use functions HogQL now supports: {supported}. "
        "Drop the row, or add it to SYNTAX_ONLY_NAMES if the guidance is about its arguments."
    )
