import re
import json
from pathlib import Path

import pytest

from posthog.schema import RecordingsQuery

from posthog.hogql.parser import parse_select

# Agents copy the skill's fenced examples verbatim into vision-scanners-create / execute-sql
# calls, so each one must stay accepted by the schema or parser it targets. This asserts
# runtime acceptance of the embedded artifacts; the surrounding prose is not inspected.
_SKILL_PATH = Path(__file__).parents[2] / "skills" / "scanning-experiments-with-replay-vision" / "SKILL.md"
_BLOCKS = re.findall(r"```(json|sql)\n(.*?)```", _SKILL_PATH.read_text(), re.DOTALL)
_JSON_BLOCKS = [(i, body) for i, (lang, body) in enumerate(_BLOCKS) if lang == "json"]
_SQL_BLOCKS = [(i, body) for i, (lang, body) in enumerate(_BLOCKS) if lang == "sql"]


def test_extraction_still_finds_the_examples():
    # Guards the extractor itself: a fence-style change must not silently skip every block.
    assert len(_JSON_BLOCKS) >= 3
    assert len(_SQL_BLOCKS) >= 2


@pytest.mark.parametrize("index,body", _JSON_BLOCKS, ids=[f"json-block-{i}" for i, _ in _JSON_BLOCKS])
def test_json_examples_stay_valid(index, body):
    data = json.loads(body)
    # Full query examples must satisfy the real pydantic model (extra="forbid" rejects
    # renamed or invented top-level fields); fragments only need to be valid JSON.
    if isinstance(data, dict) and data.get("kind") == "RecordingsQuery":
        RecordingsQuery.model_validate(data)


@pytest.mark.parametrize("index,body", _SQL_BLOCKS, ids=[f"sql-block-{i}" for i, _ in _SQL_BLOCKS])
def test_sql_examples_parse_as_hogql(index, body):
    parse_select(body)
