from parameterized import parameterized

from products.skills.backend.api.skill_import import import_problems
from products.skills.backend.api.skill_serializers import MAX_SKILL_FILE_BYTES
from products.skills.backend.marketplace.packaging import SkillExport, SkillFileExport, build_skill_zip, parse_skill_zip


def _round_tripped(**overrides) -> SkillExport:
    fields = {"name": "a-skill", "description": "A skill.", "body": "# a-skill\n", "version": 1, **overrides}
    return parse_skill_zip(build_skill_zip(SkillExport(**fields)))


class TestImportProblems:
    @parameterized.expand(
        [
            (
                "description over the spec limit",
                {"description": "d" * 1025},
                "description is 1025 characters; the spec maximum is 1024",
            ),
            ("license over the cap", {"license": "L" * 256}, "license must be 255 characters or fewer"),
            (
                "compatibility over the cap",
                {"compatibility": "C" * 501},
                "compatibility must be 500 characters or fewer",
            ),
            ("body over the byte cap", {"body": "# a-skill\n" + "x" * 1_000_001}, "body: "),
            (
                "bundled file over the byte cap",
                {"files": [SkillFileExport(path="data.txt", content="x" * (MAX_SKILL_FILE_BYTES + 1))]},
                f"file 'data.txt': content must be {MAX_SKILL_FILE_BYTES} bytes or fewer",
            ),
            (
                "bundled files colliding case-insensitively",
                {
                    "files": [
                        SkillFileExport(path="Notes.md", content="a"),
                        SkillFileExport(path="notes.md", content="b"),
                    ]
                },
                "file 'notes.md': collides with another file (case-insensitive)",
            ),
        ]
    )
    def test_reports_each_limit_the_import_path_enforces(self, _label, overrides, expected) -> None:
        problems = import_problems(_round_tripped(**overrides))

        assert len(problems) == 1, problems
        assert expected in problems[0]

    def test_reports_nothing_for_a_zip_within_every_limit(self) -> None:
        export = _round_tripped(
            license="MIT",
            compatibility="claude-code",
            allowed_tools=["Bash", "Write"],
            files=[SkillFileExport(path="scripts/run.sh", content="#!/bin/bash\necho hi\n")],
        )

        assert import_problems(export) == []
