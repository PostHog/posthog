import re
from collections import Counter
from collections.abc import Iterable

from posthog.dataclasses import frozen

CODEOWNERS_PATH = ".github/CODEOWNERS"


@frozen
class OwnerRule:
    pattern: re.Pattern[str]
    owners: tuple[str, ...]


def parse_codeowners(text: str) -> tuple[OwnerRule, ...]:
    rules: list[OwnerRule] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        rules.append(OwnerRule(pattern=_compile(pattern), owners=tuple(owners)))
    return tuple(rules)


def owner_for(path: str, rules: Iterable[OwnerRule]) -> tuple[str, ...]:
    matched: tuple[str, ...] = ()
    for rule in rules:
        if rule.pattern.match(path):
            matched = rule.owners
    return matched


def dominant_owner(paths: Iterable[str], rules: Iterable[OwnerRule]) -> str | None:
    rule_list = list(rules)
    counts = Counter(owner for path in paths for owner in owner_for(path, rule_list))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.startswith("/")
    body = pattern.lstrip("/")
    directory_only = body.endswith("/")
    body = body.rstrip("/")
    parts: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if body.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
            continue
        if body.startswith("**", index):
            parts.append(".*")
            index += 2
            continue
        if char == "*":
            parts.append("[^/]*")
        elif char == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(char))
        index += 1
    regex = "".join(parts)
    if not anchored:
        regex = f"(?:.*/)?{regex}"
    last = body.rsplit("/", 1)[-1]
    looks_like_directory = directory_only or ("*" not in last and "." not in last)
    tail = "(?:/.*)?$" if looks_like_directory else "$"
    return re.compile(f"^{regex}{tail}")
