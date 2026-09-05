import pytest

from products.reaperhog.backend.logic.owners import dominant_owner, owner_for, parse_codeowners

CODEOWNERS = """
# comment
*.py @PostHog/python
posthog/hogql/** @PostHog/hogql
posthog/hogql/database/schema/**
.github/workflows/ci-security.yaml @PostHog/team-security
products/desktop/ @PostHog/desktop @PostHog/dx
/frontend/src/lib/constants.tsx @PostHog/flags
"""


@pytest.mark.parametrize(
    "path,expected",
    [
        ("posthog/api/thing.py", ("@PostHog/python",)),
        ("posthog/hogql/parser.py", ("@PostHog/hogql",)),
        ("posthog/hogql/database/schema/events.py", ()),
        (".github/workflows/ci-security.yaml", ("@PostHog/team-security",)),
        (".github/workflows/ci-backend.yaml", ()),
        ("products/desktop/apps/code/src/main.ts", ("@PostHog/desktop", "@PostHog/dx")),
        ("frontend/src/lib/constants.tsx", ("@PostHog/flags",)),
        ("frontend/src/lib/utils.tsx", ()),
    ],
)
def test_last_matching_rule_wins(path: str, expected: tuple[str, ...]) -> None:
    assert owner_for(path, parse_codeowners(CODEOWNERS)) == expected


def test_dominant_owner_is_the_most_common_across_files() -> None:
    rules = parse_codeowners(CODEOWNERS)

    assert dominant_owner(["posthog/a.py", "posthog/hogql/b.py", "posthog/c.py"], rules) == "@PostHog/python"
    assert dominant_owner(["frontend/src/lib/utils.tsx"], rules) is None
