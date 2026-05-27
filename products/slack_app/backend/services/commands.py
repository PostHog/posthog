from typing import TYPE_CHECKING

from posthog.models.integration import Integration, SlackIntegration

if TYPE_CHECKING:
    from products.slack_app.backend.api import RulesCommand


def _handle_help(slack: SlackIntegration, channel: str, thread_ts: str) -> None:
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            "*Available commands:*\n\n"
            "`@PostHog <task description>` — Create a task for the agent to work on\n"
            "`@PostHog rules list` — Show all routing rules\n"
            '`@PostHog rules add "description" org/repo` — Add a routing rule\n'
            '`@PostHog rules add "description"` — Add a routing rule (pick repo from list)\n'
            "`@PostHog rules remove <number(s)>` — Remove routing rules by number (e.g. `remove 1` or `remove 1,2`)\n"
            "`@PostHog default repo set org/repo` — Set your default repository for this channel\n"
            "`@PostHog default repo show` — Show your default repository for this channel\n"
            "`@PostHog default repo clear` — Clear your default repository for this channel\n"
            "`@PostHog project` — Show which PostHog project your mentions route to in this workspace\n"
            "`@PostHog project <id>` — Set the PostHog project your mentions route to in this workspace\n"
            "`@PostHog help` — Show this message\n\n"
            "You can also reply in an active thread to send follow-up messages to the agent."
        ),
    )


def _handle_rules_list(slack: SlackIntegration, integration: Integration, channel: str, thread_ts: str) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    rules = list(RepoRoutingRule.objects.filter(team_id=integration.team_id).order_by("priority", "id"))
    if not rules:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text='No routing rules configured. Add one with `@PostHog rules add "description" [org/repo]`. Omit the repo to pick from a list.',
        )
        return

    lines = [f"{i + 1}. {r.rule_text} → `{r.repository}`" for i, r in enumerate(rules)]
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="*Routing rules:*\n" + "\n".join(lines),
    )


def _handle_rules_add(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    user_id: int,
    rule_text: str,
    repository: str,
) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names

    all_repos = _get_full_repo_names(integration)
    if not all_repos:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No connected GitHub repositories found for this project.",
        )
        return

    matched_repo = _extract_explicit_repo(repository, all_repos)
    if not matched_repo:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Repository `{repository}` is not connected to this project.",
        )
        return

    current_max = (
        RepoRoutingRule.objects.filter(team_id=integration.team_id)
        .order_by("-priority")
        .values_list("priority", flat=True)
        .first()
    )
    max_priority = (current_max + 1) if current_max is not None else 0
    RepoRoutingRule.objects.create(
        team_id=integration.team_id,
        rule_text=rule_text,
        repository=matched_repo,
        priority=max_priority,
        created_by_id=user_id,
    )
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Added rule: {rule_text} → `{matched_repo}`",
    )


def _handle_rules_remove(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    rule_numbers: list[int] | None,
) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    if not rule_numbers or any(n < 1 for n in rule_numbers):
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Please provide valid rule number(s). Use `@PostHog rules list` to see current rules.",
        )
        return

    rules = list(RepoRoutingRule.objects.filter(team_id=integration.team_id).order_by("priority", "id"))
    invalid = [n for n in rule_numbers if n > len(rules)]
    if invalid:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Rule {'number' if len(invalid) == 1 else 'numbers'} {', '.join(f'#{n}' for n in invalid)} {'does' if len(invalid) == 1 else 'do'} not exist. There are {len(rules)} rule(s). Use `@PostHog rules list` to see them.",
        )
        return

    to_delete = sorted(set(rule_numbers), reverse=True)
    removed: list[str] = []
    for n in to_delete:
        rule = rules[n - 1]
        removed.append(f"#{n}: {rule.rule_text}")
        rule.delete()

    removed.reverse()
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Removed rule{'s' if len(removed) > 1 else ''} {', '.join(removed)}",
    )


def _handle_default_repo_set(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    user_id: int,
    repository: str,
) -> None:
    from posthog.models.user_repo_preference import UserRepoPreference

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names

    all_repos = _get_full_repo_names(integration)
    matched_repo = _extract_explicit_repo(repository, all_repos)
    if not matched_repo:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Repository `{repository}` is not connected to this project.",
        )
        return

    UserRepoPreference.set_default(
        team_id=integration.team_id,
        user_id=user_id,
        scope_type="slack_channel",
        scope_id=channel,
        repository=matched_repo,
    )
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Default repository for this channel set to `{matched_repo}`.",
    )


def _handle_default_repo_show(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> None:
    from posthog.models.user_repo_preference import UserRepoPreference

    default = UserRepoPreference.get_default(
        team_id=integration.team_id,
        user_id=user_id,
        scope_type="slack_channel",
        scope_id=channel,
    )
    if default:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Your default repository for this channel is `{default}`.",
        )
    else:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No default repository set for this channel. Use `@PostHog default repo set org/repo` to set one.",
        )


def _handle_default_repo_clear(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> None:
    from posthog.models.user_repo_preference import UserRepoPreference

    cleared = UserRepoPreference.clear_default(
        team_id=integration.team_id,
        user_id=user_id,
        scope_type="slack_channel",
        scope_id=channel,
    )
    if cleared:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Default repository for this channel has been cleared.",
        )
    else:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No default repository was set for this channel.",
        )


def dispatch_rules_command(
    command: "RulesCommand",
    slack: SlackIntegration,
    integration: Integration,
    *,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    slack_workspace_id: str,
    user_id: int,
) -> None:
    """Run the right handler for a parsed ``RulesCommand``. Assumes the caller has
    already resolved a single ``integration`` to act on.

    ``rules add`` without an inline repo is handled here as a plain "specify the
    repo" reply. The mention workflow's picker flow must catch that case
    *before* calling this dispatcher.
    """
    if command.action == "help":
        _handle_help(slack, channel, thread_ts)
    elif command.action == "list":
        _handle_rules_list(slack, integration, channel, thread_ts)
    elif command.action == "add":
        if not command.repository:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text='Please specify the repo inline: `@PostHog rules add "description" org/repo`.',
            )
        else:
            _handle_rules_add(
                slack, integration, channel, thread_ts, user_id, command.rule_text or "", command.repository
            )
    elif command.action == "remove":
        _handle_rules_remove(slack, integration, channel, thread_ts, command.rule_numbers)
    elif command.action == "default_set":
        _handle_default_repo_set(slack, integration, channel, thread_ts, user_id, command.repository or "")
    elif command.action == "default_show":
        _handle_default_repo_show(slack, integration, channel, thread_ts, user_id)
    elif command.action == "default_clear":
        _handle_default_repo_clear(slack, integration, channel, thread_ts, user_id)
