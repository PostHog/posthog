from __future__ import annotations

import pytest

import click
from hogli_commands.isolated_test_runs import (
    IsolatedDatabases,
    group_isolated_databases,
    isolation_name,
    select_for_drop,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("isolated-test-databases", "isolatedtestdata"),
        ("Agent_A2B", "agenta2b"),
        ("iso_measure", "isomeasure"),
    ],
)
def test_isolation_name_is_a_short_lowercase_identifier(raw: str, expected: str) -> None:
    assert isolation_name(raw) == expected


def test_isolation_name_without_letters_or_digits_is_refused() -> None:
    with pytest.raises(click.UsageError):
        isolation_name("--__--")


def test_group_isolated_databases_never_matches_shared_databases() -> None:
    groups = group_isolated_databases(
        postgres=[
            "posthog",
            "posthog_persons",
            "test_posthog",
            "test_posthog_persons",
            "test_posthog_gw0",
            "test_dagster",
            "test_posthog_iso_foo",
            "test_posthog_iso_foo_persons",
            "test_posthog_iso_foo_stamphog",
            "test_posthog_iso_foo_gw1",
            "test_posthog_iso_foo_gw1_persons",
            "test_posthog_iso_foobar",
        ],
        clickhouse=["posthog", "posthog_test", "posthog_test_gw0", "posthog_test_iso_foo", "posthog_test_iso_foobar"],
        running=["foobar"],
    )

    assert groups == [
        IsolatedDatabases(
            name="foo",
            postgres=(
                "test_posthog_iso_foo",
                "test_posthog_iso_foo_gw1",
                "test_posthog_iso_foo_gw1_persons",
                "test_posthog_iso_foo_persons",
                "test_posthog_iso_foo_stamphog",
            ),
            clickhouse=("posthog_test_iso_foo",),
            running=False,
        ),
        IsolatedDatabases(
            name="foobar",
            postgres=("test_posthog_iso_foobar",),
            clickhouse=("posthog_test_iso_foobar",),
            running=True,
        ),
    ]


_IDLE = IsolatedDatabases("idle", ("test_posthog_iso_idle",), ("posthog_test_iso_idle",), running=False)
_BUSY = IsolatedDatabases("busy", ("test_posthog_iso_busy",), ("posthog_test_iso_busy",), running=True)


@pytest.mark.parametrize(
    "names, drop_all, expected",
    [
        (["idle"], False, [_IDLE]),
        (["Idle"], False, [_IDLE]),
        ([], True, [_IDLE]),
        (["busy"], False, click.UsageError),
        (["missing"], False, click.UsageError),
    ],
)
def test_select_for_drop_keeps_running_and_unknown_names_out(
    names: list[str], drop_all: bool, expected: list[IsolatedDatabases] | type[Exception]
) -> None:
    if isinstance(expected, list):
        assert select_for_drop([_IDLE, _BUSY], names, drop_all) == expected
    else:
        with pytest.raises(expected):
            select_for_drop([_IDLE, _BUSY], names, drop_all)
