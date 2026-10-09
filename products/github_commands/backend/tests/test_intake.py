import time
from typing import Any

import pytest

from products.github_commands.backend.logic.intake import CommentCommandRequest, Dropped, read_comment_command
from products.github_commands.backend.logic.parsing import (
    MAX_ARGUMENT_LENGTH,
    AmbiguousCommand,
    ParsedCommand,
    parse_command,
)


def _payload(body: str = "@posthog stamp", **overrides: Any) -> dict[str, Any]:
    comment: dict[str, Any] = {
        "id": 555,
        "html_url": "https://github.com/acme/widgets/pull/7#issuecomment-555",
        "body": body,
        "author_association": "MEMBER",
        "performed_via_github_app": None,
        "user": {"id": 4242, "login": "octo", "type": "User"},
    }
    comment.update(overrides.pop("comment", {}))
    payload: dict[str, Any] = {
        "action": "created",
        "installation": {"id": 99},
        "repository": {"full_name": "acme/widgets"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/repos/acme/widgets/pulls/7"}},
        "comment": comment,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "body,expected",
    [
        ("@posthog stamp", ParsedCommand(verb="stamp", argument="")),
        ("@PostHog Review --full", ParsedCommand(verb="review", argument="--full")),
        ("Looks good.\n\n@posthog qa the billing page", ParsedCommand(verb="qa", argument="the billing page")),
        ("@posthog", ParsedCommand(verb="help", argument="")),
        # Talking about the bot is not asking it to do something.
        ("thanks @posthog review was useful", None),
        # Other accounts that share the prefix.
        ("@posthog-bot stamp", None),
        ("@posthogx stamp", None),
        # Quoting a command, as every reply to one does, must not run it again.
        ("> @posthog stamp\n\nWhy did this run?", None),
        # Markdown keeps a line without ">" inside the quote until a blank line.
        ("> Example command:\n@posthog qa", None),
        ("> Why did this run?\n\n@posthog stamp", ParsedCommand(verb="stamp", argument="")),
        # GitHub shows a tab-indented line as code.
        ("\t@posthog qa", None),
        # A fence with an info string inside a block is displayed text, not the end of the block.
        ("```\n```python\n@posthog qa\n```", None),
        ("<pre>\n\n@posthog qa\n\n</pre>", None),
        ("<blockquote>\n@posthog qa\n</blockquote>", None),
        ("<blockquote>\n@posthog qa</blockquote>", None),
        # A fence can open a list item, and its closing fence is indented to the item's content.
        ("- ```\n  @posthog qa\n  ```", None),
        ("```\n    ```\n@posthog qa\n```", None),
        (" ~~~\n    ~~~\n@posthog qa\n ~~~", None),
        ("- ```\n  filler\n```\n@posthog qa", None),
        ("1. ```\n   filler\n```\n@posthog qa", None),
        ("1. ```\n   @posthog qa\n   ```", None),
        ("- ```\n  example\n  ```\n\n@posthog stamp", ParsedCommand(verb="stamp", argument="")),
        # Removing the code span must not move the mention to the start of the line.
        ("`Example only:` @posthog qa", None),
        ("```\n@posthog stamp\n```", None),
        ("~~~md\n@posthog stamp\n~~~", None),
        # A shorter fence inside a longer one is displayed text, not the end of the block.
        ("````\n```\n@posthog stamp\n```\n````", None),
        ("`@posthog stamp`", None),
        ("Run `this\n@posthog stamp` later", None),
        ("<!-- @posthog stamp -->", None),
        ("<!--\n@posthog stamp\n-->", None),
        ("@posthog stamp\n@posthog qa", AmbiguousCommand(count=2)),
        # Text inside a list item, wherever its fences open and close, is not a top-level paragraph.
        ("- ```\n  example\n````\n  ```\n@posthog qa\n````", None),
        ("- ```\nfiller\n  ```\n@posthog stamp", None),
        ("- item\n  ```\nfiller\n```\n@posthog stamp", None),
        ("- item\n    ```\n  @posthog stamp", None),
        ("- item\n\t```\n  @posthog stamp", None),
        ("- item\n\n@posthog stamp", ParsedCommand(verb="stamp", argument="")),
        # Bold text is still the person's own words.
        ("**@posthog stamp**", ParsedCommand(verb="stamp", argument="")),
    ],
)
def test_parse_command(body: str, expected: object) -> None:
    assert parse_command(body) == expected


def test_parse_command_reads_a_long_backtick_run_in_linear_time() -> None:
    # GitHub accepts comments up to 65,536 characters, and intake parses them inside the webhook
    # request before any author check.
    body = "Example: " + "`" * 65_000

    started = time.perf_counter()
    parsed = parse_command(body)
    elapsed = time.perf_counter() - started

    assert parsed is None
    assert elapsed < 1.0


def test_parse_command_strips_characters_that_hide_or_reorder_text() -> None:
    parsed = parse_command("@posthog qa check‮ the​ form\x07 " + "x" * 500)

    assert isinstance(parsed, ParsedCommand)
    assert parsed.argument.startswith("check the form ")
    assert len(parsed.argument) == MAX_ARGUMENT_LENGTH


def test_read_comment_command_copies_identifiers_and_the_command_only() -> None:
    assert read_comment_command(_payload("@posthog qa signup flow")) == CommentCommandRequest(
        installation_id="99",
        repository="acme/widgets",
        pr_number=7,
        comment_id=555,
        comment_url="https://github.com/acme/widgets/pull/7#issuecomment-555",
        commenter_github_id=4242,
        commenter_login="octo",
        verb="qa",
        argument="signup flow",
    )


@pytest.mark.parametrize(
    "payload,reason",
    [
        (_payload(action="edited"), "not_created"),
        (_payload(issue={"number": 7}), "not_pull_request"),
        (_payload("nice work"), "no_command"),
        (_payload(comment={"user": {"id": 1, "login": "posthog[bot]", "type": "Bot"}}), "bot_author"),
        (_payload(comment={"user": {"id": 1, "login": "helper[bot]", "type": "User"}}), "bot_author"),
        (_payload(comment={"performed_via_github_app": {"slug": "some-agent"}}), "app_authored"),
        (_payload(comment={"author_association": "CONTRIBUTOR"}), "untrusted_association"),
        (_payload(comment={"author_association": "NONE"}), "untrusted_association"),
        (_payload(repository={"full_name": "acme/widgets/../../orgs"}), "malformed"),
        (_payload(installation={}), "malformed"),
    ],
)
def test_read_comment_command_drops(payload: dict[str, Any], reason: str) -> None:
    assert read_comment_command(payload) == Dropped(reason=reason)  # type: ignore[arg-type]
