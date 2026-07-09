import pytest

from parameterized import parameterized

from products.feature_flags.scripts.region_report import (
    FlagSummary,
    diff_flags,
    max_rollout_percentage,
    print_flag_only_section,
    summarize_flag,
)


@parameterized.expand(
    [
        ("no_groups", {}, None),
        ("empty_groups", {"groups": []}, None),
        ("missing_percentage_defaults_to_100", {"groups": [{"properties": []}]}, 100),
        ("explicit_percentage", {"groups": [{"properties": [], "rollout_percentage": 25}]}, 25),
        ("explicit_zero", {"groups": [{"rollout_percentage": 0}]}, 0),
        (
            "multiple_groups_takes_max",
            {"groups": [{"rollout_percentage": 10}, {"rollout_percentage": 50}, {"rollout_percentage": 30}]},
            50,
        ),
    ]
)
def test_max_rollout_percentage(name: str, filters: dict, expected: int | None) -> None:
    assert max_rollout_percentage(filters) == expected


@parameterized.expand(
    [
        ("no_multivariate_key", {}, False),
        ("multivariate_with_variants", {"multivariate": {"variants": [{"key": "a", "rollout_percentage": 100}]}}, True),
        ("multivariate_with_empty_variants", {"multivariate": {"variants": []}}, False),
    ]
)
def test_summarize_flag_multivariate(name: str, filters: dict, expected_is_multivariate: bool) -> None:
    flag = {"key": "my-flag", "name": "My flag", "active": True, "archived": False, "filters": filters}
    assert summarize_flag(flag).is_multivariate == expected_is_multivariate


def _summary(key: str, active: bool = True, rollout: int | None = 100) -> FlagSummary:
    return FlagSummary(
        key=key, name=key, active=active, archived=False, max_rollout_percentage=rollout, is_multivariate=False
    )


def test_diff_flags_only_in_one_region() -> None:
    us_flags = {"us-only": _summary("us-only")}
    eu_flags = {"eu-only": _summary("eu-only")}

    only_us, only_eu, differences = diff_flags(us_flags, eu_flags)

    assert set(only_us) == {"us-only"}
    assert set(only_eu) == {"eu-only"}
    assert differences == []


@parameterized.expand(
    [
        ("identical", True, 50, True, 50, False),
        ("active_differs", True, 50, False, 50, True),
        ("rollout_differs", True, 50, True, 90, True),
        ("both_differ", True, 50, False, 90, True),
    ]
)
def test_diff_flags_common_flag(
    name: str, us_active: bool, us_rollout: int, eu_active: bool, eu_rollout: int, expect_diff: bool
) -> None:
    us_flags = {"shared": _summary("shared", active=us_active, rollout=us_rollout)}
    eu_flags = {"shared": _summary("shared", active=eu_active, rollout=eu_rollout)}

    only_us, only_eu, differences = diff_flags(us_flags, eu_flags)

    assert only_us == {}
    assert only_eu == {}
    assert [key for key, _, _ in differences] == (["shared"] if expect_diff else [])


def test_print_flag_only_section_markdown_renders_pipe_table(capsys: pytest.CaptureFixture[str]) -> None:
    flags = {"my-flag": _summary("my-flag")}

    print_flag_only_section("Flags only in US", flags, markdown=True)

    output = capsys.readouterr().out
    assert "| key | name | active | rollout |" in output
    assert "| --- | --- | --- | --- |" in output
    assert "| my-flag | my-flag | True | 100% |" in output


def test_print_flag_only_section_markdown_escapes_pipe_in_value(capsys: pytest.CaptureFixture[str]) -> None:
    flags = {
        "my-flag": FlagSummary(
            key="my-flag", name="A | B", active=True, archived=False, max_rollout_percentage=100, is_multivariate=False
        )
    }

    print_flag_only_section("Flags only in US", flags, markdown=True)

    output = capsys.readouterr().out
    assert "A \\| B" in output
