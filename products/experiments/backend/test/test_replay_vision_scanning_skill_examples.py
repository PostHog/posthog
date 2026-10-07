import re
import json
from pathlib import Path

from parameterized import parameterized

from posthog.schema import RecordingsQuery

# Agents copy the skill's fenced examples verbatim into vision-scanners-create calls, so each one
# must stay accepted by the schema it targets. This asserts runtime acceptance of the embedded
# artifacts; the surrounding prose is not inspected.
_SKILL_PATH = Path(__file__).parents[2] / "skills" / "scanning-experiments-with-replay-vision" / "SKILL.md"
_BLOCKS = re.findall(r"```(json|sql)\n(.*?)```", _SKILL_PATH.read_text(), re.DOTALL)
_JSON_BLOCKS = [(i, body) for i, (lang, body) in enumerate(_BLOCKS) if lang == "json"]


class TestReplayVisionScanningSkillExamples:
    def test_extraction_still_finds_the_examples(self):
        # Exact counts, not floors: a new example whose fence the regex can't parse (```JSON,
        # a trailing space) would ship unvalidated while the old blocks kept a floor green.
        assert len(_JSON_BLOCKS) == 2
        assert len(_BLOCKS) == len(_JSON_BLOCKS)

    @parameterized.expand(_JSON_BLOCKS)
    def test_json_examples_stay_valid(self, index, body):
        data = json.loads(body)
        # Full query examples must satisfy the real pydantic model (extra="forbid" rejects
        # renamed or invented top-level fields); fragments only need to be valid JSON.
        if isinstance(data, dict) and data.get("kind") == "RecordingsQuery":
            RecordingsQuery.model_validate(data)
