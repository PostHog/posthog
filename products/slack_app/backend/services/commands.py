from typing import TYPE_CHECKING

from posthog.models.integration import Integration, SlackIntegration

if TYPE_CHECKING:
    from products.slack_app.backend.api import RulesCommand
    from products.slack_app.backend.services.integration_resolver import ResolutionResult


def _handle_help(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    *,
    command_prefix: str = "@PostHog",
) -> None:
    from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin

    # Task creation only makes sense on the mention surface — slash commands lack the thread
    # context the workflow needs, so omit it when the user discovered help via ``/posthog``.
    lines = ["*Available commands:*\n"]
    if command_prefix == "@PostHog":
        lines.append(f"`{command_prefix} <task description>` — Create a task for the agent to work on")
    lines.extend(
        [
            f"`{command_prefix} rules list` — Show all routing rules",
            f'`{command_prefix} rules add "description" org/repo` — Add a routing rule',
            f'`{command_prefix} rules add "description"` — Add a routing rule (pick repo from list)',
            f"`{command_prefix} rules remove <number(s)>` — Remove routing rules by number (e.g. `remove 1` or `remove 1,2`)",
            f"`{command_prefix} project` — Show which PostHog project your mentions route to in this workspace",
            f"`{command_prefix} project <id>` — Set the PostHog project your mentions route to in this workspace",
        ]
    )

    # The workspace-wide default is admins/owners-only, so only surface it to them.
    if is_slack_workspace_admin(slack, integration, slack_user_id):
        lines.append(
            f"`{command_prefix} project workspace <id>` — Set the workspace-wide default project (Slack admins/owners only)"
        )

    lines.append(f"`{command_prefix} help` — Show this message\n")
    if command_prefix == "@PostHog":
        lines.append("You can also reply in an active thread to send follow-up messages to the agent.")

    slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text="\n".join(lines))


def _handle_rules_list(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    *,
    command_prefix: str = "@PostHog",
) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    rules = list(RepoRoutingRule.objects.filter(team_id=integration.team_id).order_by("priority", "id"))
    if not rules:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f'No routing rules configured. Add one with `{command_prefix} rules add "description" '
                "[org/repo]`. Omit the repo to pick from a list."
            ),
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

    all_repos = _get_full_repo_names(integration, user_id=user_id)
    if not all_repos:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No connected GitHub repositories found for your account.",
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
    *,
    command_prefix: str = "@PostHog",
) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    if not rule_numbers or any(n < 1 for n in rule_numbers):
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Please provide valid rule number(s). Use `{command_prefix} rules list` to see current rules.",
        )
        return

    rules = list(RepoRoutingRule.objects.filter(team_id=integration.team_id).order_by("priority", "id"))
    invalid = [n for n in rule_numbers if n > len(rules)]
    if invalid:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Rule {'number' if len(invalid) == 1 else 'numbers'} {', '.join(f'#{n}' for n in invalid)} {'does' if len(invalid) == 1 else 'do'} not exist. There are {len(rules)} rule(s). Use `{command_prefix} rules list` to see them.",
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


def _handle_project_show(
    slack: SlackIntegration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    slack_workspace_id: str,
    user_id: int,
    workspace_candidates: list[Integration] | None = None,
    *,
    command_prefix: str = "@PostHog",
) -> None:
    from posthog.models.user import User

    from products.slack_app.backend.services.integration_resolver import (
        format_project_candidate_list,
        load_integrations,
        resolve_from_candidates,
    )

    user = User.objects.get(id=user_id)
    if workspace_candidates is not None:
        result = resolve_from_candidates(
            workspace_candidates,
            slack_team_id=slack_workspace_id,
            slack_user_id=slack_user_id,
            user=user,
        )
    else:
        result = load_integrations(
            slack_team_id=slack_workspace_id,
            kinds=["slack"],
            slack_user_id=slack_user_id,
            user=user,
        )

    if result.integration is not None:
        target = result.integration
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=(
                f"Your mentions in this workspace route to *{target.team.organization.name} · "
                f"{target.team.name}* (id `{target.team_id}`). "
                f"Change it with `{command_prefix} project <id>`."
            ),
        )
        return

    if not result.candidates:
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=("I couldn't find your PostHog account in any organization connected to this Slack workspace."),
        )
        return

    lines = format_project_candidate_list(result.candidates)
    slack.client.chat_postEphemeral(
        channel=channel,
        user=slack_user_id,
        thread_ts=thread_ts,
        text=(
            "You haven't set a default project for this Slack workspace yet. Available PostHog "
            "projects you can pick:\n"
            f"{lines}\n\n"
            f"Set one with `{command_prefix} project <id>`."
        ),
    )


def _handle_project_set(
    slack: SlackIntegration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    slack_workspace_id: str,
    user_id: int,
    target_team_id: int,
    workspace_candidates: list[Integration] | None = None,
) -> None:
    from posthog.models.user import User

    from products.slack_app.backend.models import SlackSettings

    user = User.objects.get(id=user_id)
    if not user.teams.filter(id=target_team_id).exists():
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=f"You don't have access to project `{target_team_id}`.",
        )
        return

    if workspace_candidates is not None:
        target = next((c for c in workspace_candidates if c.team_id == target_team_id), None)
    else:
        target = (
            Integration.objects.filter(
                kind="slack",
                integration_id=slack_workspace_id,
                team_id=target_team_id,
            )
            .select_related("team", "team__organization")
            .first()
        )
    if target is None:
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=f"Project `{target_team_id}` isn't connected to this Slack workspace.",
        )
        return

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=slack_user_id,
        defaults={"default_integration": target},
    )
    slack.client.chat_postEphemeral(
        channel=channel,
        user=slack_user_id,
        thread_ts=thread_ts,
        text=(
            f"Default set to *{target.team.organization.name} · {target.team.name}* "
            f"(id `{target.team_id}`). I'll route future mentions here — mention me again to "
            "start a task."
        ),
    )


def _handle_project_set_workspace(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    slack_workspace_id: str,
    user_id: int,
    target_team_id: int,
    workspace_candidates: list[Integration] | None = None,
    *,
    command_prefix: str = "@PostHog",
) -> None:
    """Set the workspace-wide default project (the ``slack_user_id IS NULL`` row),
    which applies to every Slack user in the workspace without a personal default.
    Restricted to Slack workspace admins and owners.
    """
    from posthog.models.user import User

    from products.slack_app.backend.models import SlackSettings
    from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin

    if not is_slack_workspace_admin(slack, integration, slack_user_id):
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text="Only Slack workspace admins or owners can set the workspace-wide default project.",
        )
        return

    user = User.objects.get(id=user_id)
    if not user.teams.filter(id=target_team_id).exists():
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=f"You don't have access to project `{target_team_id}`.",
        )
        return

    if workspace_candidates is not None:
        target = next((c for c in workspace_candidates if c.team_id == target_team_id), None)
    else:
        target = (
            Integration.objects.filter(
                kind="slack",
                integration_id=slack_workspace_id,
                team_id=target_team_id,
            )
            .select_related("team", "team__organization")
            .first()
        )
    if target is None:
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=f"Project `{target_team_id}` isn't connected to this Slack workspace.",
        )
        return

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=None,
        defaults={"default_integration": target},
    )
    slack.client.chat_postEphemeral(
        channel=channel,
        user=slack_user_id,
        thread_ts=thread_ts,
        text=(
            f"Workspace-wide default set to *{target.team.organization.name} · {target.team.name}* "
            f"(id `{target.team_id}`). Mentions from anyone without a personal default "
            f"(`{command_prefix} project <id>`) now route here."
        ),
    )


def resolve_command_target(
    *,
    slack_team_id: str,
    command: "RulesCommand",
    slack_user_id: str,
    user_id: int,
    channel: str,
    thread_ts: str,
) -> tuple[list[Integration], "ResolutionResult"]:
    """Load workspace candidates and decide which one to dispatch against.

    Returns ``(workspace_candidates, result)``. ``result.integration`` is
    ``None`` when no candidate can be auto-picked for the acting user — either
    because access filtering left them with nothing (``result.candidates``
    empty) or because they have access to multiple projects and haven't set a
    default (``result.candidates`` non-empty). The caller picks the appropriate
    "no access" vs "pick a project" message based on which.
    """
    from posthog.models.user import User

    from products.slack_app.backend.services.integration_resolver import (
        ResolutionResult,
        load_integrations,
        resolve_from_candidates,
    )

    initial = load_integrations(slack_team_id=slack_team_id, kinds=["slack"])
    candidates = initial.candidates
    if not candidates:
        return [], ResolutionResult(integration=None, source="needs_picker", candidates=[])

    # Workspace-level commands don't act on team data: ``help`` posts static
    # text, and ``project_*`` commands enforce access inside the handler. They
    # run against any workspace integration as a probe.
    if command.action in ("project_show", "project_set", "project_set_workspace", "help"):
        return candidates, ResolutionResult(integration=candidates[0], source="sole_candidate", candidates=candidates)

    # Team-scoped commands (``list``/``add``/``remove``) must go through the
    # access-filtered resolver — including the single-integration case, where
    # the shortcut would otherwise dispatch against a project the user has no
    # access to.
    result = resolve_from_candidates(
        candidates,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        user=User.objects.get(id=user_id),
        channel=channel,
        thread_ts=thread_ts,
    )
    return candidates, result


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
    workspace_candidates: list[Integration] | None = None,
    command_prefix: str = "@PostHog",
) -> None:
    """Run the right handler for a parsed ``RulesCommand``. Assumes the caller has
    already resolved a single ``integration`` to act on; project commands also
    accept ``workspace_candidates`` so ``project_set`` can skip a DB lookup.

    ``rules add`` without an inline repo is handled here as a plain "specify the
    repo" reply. The mention workflow's picker flow must catch that case
    *before* calling this dispatcher.

    ``command_prefix`` is the entry-point token surfaced in user-facing help and
    error strings — ``@PostHog`` for mentions, ``/posthog`` for the slash command
    surface. Defaults preserve the mention copy for existing callers.
    """
    if command.action == "help":
        _handle_help(slack, integration, channel, thread_ts, slack_user_id, command_prefix=command_prefix)
    elif command.action == "list":
        _handle_rules_list(slack, integration, channel, thread_ts, command_prefix=command_prefix)
    elif command.action == "add":
        if not command.repository:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f'Please specify the repo inline: `{command_prefix} rules add "description" org/repo`.',
            )
        else:
            _handle_rules_add(
                slack, integration, channel, thread_ts, user_id, command.rule_text or "", command.repository
            )
    elif command.action == "remove":
        _handle_rules_remove(
            slack, integration, channel, thread_ts, command.rule_numbers, command_prefix=command_prefix
        )
    elif command.action == "project_show":
        _handle_project_show(
            slack,
            channel,
            thread_ts,
            slack_user_id,
            slack_workspace_id,
            user_id,
            workspace_candidates=workspace_candidates,
            command_prefix=command_prefix,
        )
    elif command.action == "project_set":
        if command.project_team_id is None:
            return
        _handle_project_set(
            slack,
            channel,
            thread_ts,
            slack_user_id,
            slack_workspace_id,
            user_id,
            command.project_team_id,
            workspace_candidates=workspace_candidates,
        )
    elif command.action == "project_set_workspace":
        if command.project_team_id is None:
            return
        _handle_project_set_workspace(
            slack,
            integration,
            channel,
            thread_ts,
            slack_user_id,
            slack_workspace_id,
            user_id,
            command.project_team_id,
            workspace_candidates=workspace_candidates,
            command_prefix=command_prefix,
        )
