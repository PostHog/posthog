from typing import Literal

import pytest

from posthog.dataclasses import frozen

from products.github_commands.backend.logic.schema import (
    COMMAND_DECLARATIONS,
    HELP,
    LOOP,
    QA,
    REVIEW,
    STAMP,
    ArgumentError,
    CommandDeclaration,
    LoopArgs,
    QaArgs,
    ReviewArgs,
    StampArgs,
    option,
    parse_arguments,
    resolve_verb,
    signature,
    text,
    usage,
)


@frozen
class _ModeArgs:
    mode: Literal["quick", "deep"] = option("How hard to look.", default="quick")


_MODE = CommandDeclaration(verb="mode", summary="Test command.", args=_ModeArgs, dispatches_to="Tests")


@pytest.mark.parametrize(
    "declaration,raw,expected",
    [
        (REVIEW, "", ReviewArgs(deep=False)),
        (REVIEW, "--deep", ReviewArgs(deep=True)),
        (STAMP, "", StampArgs()),
        # Prose keeps its apostrophes and words, because nothing splits it like a shell.
        (
            QA,
            "don't change the signup form's \"Next\" button",
            QaArgs(focus="don't change the signup form's \"Next\" button"),
        ),
        (QA, "-- --looks-like-a-flag", QaArgs(focus="--looks-like-a-flag")),
        # Option scanning stops at the first word, so a later `--x` is part of the text.
        (QA, "check the form --deep", QaArgs(focus="check the form --deep")),
        (QA, "", QaArgs(focus="")),
        (LOOP, "Triage PR", LoopArgs(name="Triage PR")),
        (_MODE, "--mode deep", _ModeArgs(mode="deep")),
        (_MODE, "--mode=deep", _ModeArgs(mode="deep")),
        (_MODE, "", _ModeArgs(mode="quick")),
    ],
)
def test_parse_arguments_accepts(declaration: CommandDeclaration[object], raw: str, expected: object) -> None:
    assert parse_arguments(declaration, raw) == expected


@pytest.mark.parametrize(
    "declaration,raw",
    [
        (REVIEW, "--deep --deep"),
        (REVIEW, "--nope"),
        (REVIEW, "--deep=yes"),
        (REVIEW, "some text"),
        (STAMP, "now"),
        (LOOP, ""),
        (LOOP, "--"),
        (_MODE, "--mode other"),
        (_MODE, "--mode=other"),
        (_MODE, "--mode"),
        (_MODE, "--mode="),
    ],
)
def test_parse_arguments_rejects(declaration: CommandDeclaration[object], raw: str) -> None:
    assert isinstance(parse_arguments(declaration, raw), ArgumentError)


def test_an_unknown_option_is_not_repeated_in_the_reason() -> None:
    # The reason goes into a public reply, which must never carry text the commenter wrote.
    result = parse_arguments(REVIEW, "--ping-@someone")

    assert isinstance(result, ArgumentError)
    assert "someone" not in result.reason


@frozen
class _ListArgs:
    items: list[str] = option("Not a supported type.")


@frozen
class _TwoTextArgs:
    first: str = text("Some text.")
    second: str = text("More text.")


def test_an_unsupported_declaration_fails_when_declared() -> None:
    with pytest.raises(ValueError):
        CommandDeclaration(verb="bad", summary="Bad.", args=_ListArgs, dispatches_to="Tests")
    with pytest.raises(ValueError):
        CommandDeclaration(verb="bad", summary="Bad.", args=_TwoTextArgs, dispatches_to="Tests")


@pytest.mark.parametrize("verb,expected", [("approve", "stamp"), ("stamp", "stamp"), ("help", None), ("nope", None)])
def test_resolve_verb(verb: str, expected: str | None) -> None:
    assert resolve_verb(verb) == expected


def test_signature_and_usage_cover_every_declaration() -> None:
    commands = signature()["commands"]
    assert isinstance(commands, list)
    listed = [command["verb"] for command in commands]

    assert sorted(listed) == sorted(declaration.verb for declaration in (*COMMAND_DECLARATIONS, HELP))
    assert [usage(declaration) for declaration in (REVIEW, STAMP, QA, LOOP, _MODE)] == [
        "@posthog review [--deep]",
        "@posthog stamp",
        "@posthog qa [<focus>]",
        "@posthog loop <name>",
        "@posthog mode [--mode <quick|deep>]",
    ]
