import re
from pathlib import Path

from products.tracing.backend.presentation.views import _TracingAttributesQuerySerializer

SKILL_DIR = Path(__file__).parent / "exploring-apm-traces"

DOCUMENTED_ATTRIBUTE_TYPE_PATTERNS = [
    re.compile(r'attribute_type: "([^"]+)"(?: or "([^"]+)")?'),
    re.compile(r"apm-attributes-list` \(type `([^`]+)`\)"),
]


def test_documented_attribute_types_are_accepted_by_apm_attributes_list() -> None:
    accepted = set(_TracingAttributesQuerySerializer().fields["attribute_type"].choices)

    documented: set[str] = set()
    for doc in [SKILL_DIR / "SKILL.md", *sorted((SKILL_DIR / "references").glob("*.md"))]:
        content = doc.read_text(encoding="utf-8")
        for pattern in DOCUMENTED_ATTRIBUTE_TYPE_PATTERNS:
            for match in pattern.finditer(content):
                documented.update(value for value in match.groups() if value)

    assert documented
    assert documented - accepted == set()
