from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.harness.cli import SkillDelivery, parse_args


@pytest.mark.parametrize(
    "argv,expected_delivery",
    [
        ([], "bundled"),
        (["--skill-delivery", "exec"], "exec"),
    ],
)
def test_skill_delivery_defaults_to_bundled_and_allows_exec(argv: list[str], expected_delivery: SkillDelivery) -> None:
    assert parse_args(argv).skill_delivery == expected_delivery


@pytest.mark.parametrize(
    "argv,expected",
    [([], 2), (["--infra-retries", "0"], 0), (["--infra-retries", "3"], 3), (["--infra-retries", "-1"], None)],
)
def test_infrastructure_retry_budget(argv: list[str], expected: int | None) -> None:
    if expected is None:
        with pytest.raises(SystemExit) as error:
            parse_args(argv)
        assert error.value.code == 2
    else:
        assert parse_args(argv).infrastructure_retries == expected


@pytest.mark.parametrize("argv,verbose", [([], False), (["--verbose"], True)])
def test_console_output_detail(argv: list[str], verbose: bool) -> None:
    assert parse_args(argv).verbose is verbose
