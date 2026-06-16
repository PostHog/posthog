from datetime import UTC, datetime, timedelta

from freshness import build_prompt, classify_freshness, format_marker, parse_marker, parse_tier, tier_to_hours
from parameterized import parameterized

NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


@parameterized.expand(
    [
        ("hot", 2),
        ("normal", 12),
        ("isolated", 48),
        ("default", 48),
        ("nonsense", 48),
    ]
)
def test_tier_to_hours(tier, expected):
    assert tier_to_hours(tier) == expected


@parameterized.expand(
    [
        ("bare word", "normal", "normal"),
        ("uppercase", "HOT", "hot"),
        ("with reasoning", "I'd say isolated since it's docs", "isolated"),
        ("ambiguous multiple tiers", "not hot, normal", "default"),
        ("unknown", "maybe medium?", "default"),
        ("empty", "", "default"),
    ]
)
def test_parse_tier(_name, text, expected):
    assert parse_tier(text) == expected


@parameterized.expand(
    [
        ("hot", 2, "2026-06-18T08:00:00+00:00"),
        ("normal", 12, "2026-06-17T00:00:00+00:00"),
        ("isolated", 48, "2026-06-20T12:00:00+00:00"),
    ]
)
def test_marker_roundtrip(tier, hours, deadline_iso):
    parsed = parse_marker(f"some summary text\n{format_marker(tier, hours, deadline_iso)}\nmore text")
    assert parsed == {"tier": tier, "budget_hours": hours, "deadline": datetime.fromisoformat(deadline_iso)}


@parameterized.expand(
    [
        ("no marker", "no marker here"),
        ("none", None),
        ("empty", ""),
        ("malformed deadline", "<!-- pr-freshness:v1 tier=normal budget_hours=12 deadline=not-a-date -->"),
    ]
)
def test_parse_marker_absent_or_invalid(_name, summary):
    assert parse_marker(summary) is None


@parameterized.expand(
    [
        ("within budget", 10, "success"),
        ("just inside", 1, "success"),
        ("just past", -1, "failure"),
        ("long overdue", -200, "failure"),
    ]
)
def test_classify_freshness(_name, hours_until_deadline, expected_conclusion):
    deadline = NOW + timedelta(hours=hours_until_deadline)
    conclusion, title, _summary = classify_freshness(NOW, deadline, "normal", 48)
    assert conclusion == expected_conclusion
    assert "48h" in title


def test_build_prompt_includes_signal():
    system, user = build_prompt("Add repo-wide linter", "Catches every nuance on master", ["tools/lint.py"])
    assert "hot" in system and "isolated" in system
    assert "Add repo-wide linter" in user
    assert "tools/lint.py" in user


def test_build_prompt_truncates_file_list():
    files = [f"src/file_{i}.py" for i in range(150)]
    _system, user = build_prompt("title", "body", files)
    assert "src/file_0.py" in user
    assert "and 50 more files" in user
    assert "src/file_149.py" not in user
