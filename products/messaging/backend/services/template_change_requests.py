"""A request to change the file of a template managed by code, carried out by a PostHog Code task.

The task edits the file in the template's repository and opens a pull request. PostHog never changes the template
here: the next upload of the changed file publishes it.
"""

import re
from typing import Final

from posthog.models import Team, User
from posthog.utils import absolute_uri

from products.messaging.backend.facade.contracts import (
    TemplateChangePrompt,
    TemplateChangeRefused,
    TemplateChangeRequested,
)
from products.messaging.backend.services import template_change_prompt
from products.messaging.backend.services.template_change_prompt import PromptedTemplate
from products.messaging.backend.services.template_ownership import not_managed_by_code
from products.tasks.backend.facade import (
    access as tasks_access,
    api as tasks_facade,
    repo_selection as tasks_repo_selection,
    usage as tasks_usage,
)
from products.tasks.backend.facade.compute_quota import ComputeBillingLimitExceeded

GITHUB_REPOSITORY: Final = re.compile(
    r"^github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<name>[A-Za-z0-9._-]+?)(?:\.git)?$", re.IGNORECASE
)
CHANGE_RULES: Final = (
    "Change only this file. Open a pull request. Do not upload the template or call PostHog's email template tools."
)
TASK_TITLE_MAX_LENGTH: Final = 255


def request_change(
    team: Team, user: User, template: PromptedTemplate, instruction: str, *, from_sandbox: bool
) -> TemplateChangeRequested:
    """Start a PostHog Code task that changes the template's file as `instruction` asks, and opens a pull request.

    Raises TemplateChangeRefused when PostHog Code can't take the request.
    """
    prompt = template_change_prompt.change_prompt(team.id, template)
    if prompt is None or template.key is None:
        raise not_managed_by_code()
    _require_posthog_code(team, user, from_sandbox=from_sandbox)
    repository = _github_repository(template.source_repository)
    _require_connected(team.id, repository)
    try:
        created = tasks_facade.create_and_run_task(
            team=team,
            title=_title(template.key),
            description=_description(prompt, instruction),
            origin_product=tasks_facade.TaskOriginProduct.USER_CREATED,
            user_id=user.id,
            repository=repository,
            create_pr=True,
            # The task changes a file in the repository. It has no reason to write to PostHog, so it can't change
            # the template there either.
            posthog_mcp_scopes="read_only",
        )
    except (ValueError, ComputeBillingLimitExceeded) as e:
        raise TemplateChangeRefused(
            code="posthog_code_run_failed",
            detail=str(e) or "PostHog Code could not start the task.",
            why="PostHog Code refused to start the task.",
            fix="Fix what the detail names, then request the change again.",
        ) from e
    return TemplateChangeRequested(
        task_id=created.task_id,
        task_url=absolute_uri(f"/project/{team.id}/tasks/{created.task_id}"),
        repository=repository,
    )


def _title(key: str) -> str:
    title = f"Change the `{key}` email template"
    if len(title) <= TASK_TITLE_MAX_LENGTH:
        return title
    return f"{title[: TASK_TITLE_MAX_LENGTH - 1]}…"


def _description(prompt: TemplateChangePrompt, instruction: str) -> str:
    # The starter names the file. A sentence that doesn't start with it, such as one from an agent, gets it in front.
    request = (
        instruction
        if instruction.startswith(prompt.starter)
        else f"{prompt.starter}what this request asks for: {instruction}"
    )
    return "\n\n".join([request, prompt.context, CHANGE_RULES])


def _require_posthog_code(team: Team, user: User, *, from_sandbox: bool) -> None:
    if from_sandbox:
        raise _posthog_code_not_available(
            why="A PostHog Code task runs at a person's request, so a task already running can't start another one.",
            fix="Ask the person to request the change from the template's page in PostHog, or to call this route "
            "themselves.",
        )
    try:
        decision = tasks_access.get_desktop_access_decision(user, team.organization)
    except tasks_access.DesktopAccessResolutionError:
        raise _posthog_code_not_available(
            why="PostHog couldn't check whether this organization can use PostHog Code.",
            fix="Try again in a few minutes.",
        ) from None
    if not decision.allowed:
        raise _posthog_code_not_available(
            why="This organization can't use PostHog Code.",
            fix="Edit the template's file in its repository yourself, then upload it.",
        )
    if tasks_usage.task_run_usage_limited(user, team.id):
        raise _posthog_code_not_available(
            why="This organization used up its PostHog Code credits.",
            fix="Edit the template's file in its repository yourself, then upload it. PostHog Code is available again "
            "when the credits renew.",
        )


def _github_repository(source_repository: str | None) -> str:
    if not source_repository:
        raise TemplateChangeRefused(
            code="template_repository_missing",
            detail="PostHog doesn't know which repository this template's file is in.",
            why="The uploads of this template sent no `source.repository`.",
            fix="Upload the template again with `source.repository`, such as `github.com/example/app`. posthog-node "
            "detects it from the git checkout or the CI environment when the upload doesn't set it.",
        )
    match = GITHUB_REPOSITORY.match(source_repository)
    if match is None:
        raise TemplateChangeRefused(
            code="template_repository_unsupported",
            detail=f"PostHog Code can't change files in `{source_repository}`.",
            why="PostHog Code opens pull requests only on GitHub repositories, stored as `github.com/<owner>/<name>`.",
            fix="Edit the template's file in its repository yourself, then upload it.",
        )
    return f"{match['owner']}/{match['name']}"


def _require_connected(team_id: int, repository: str) -> None:
    if repository.lower() not in tasks_repo_selection.list_team_connected_repositories(team_id):
        raise TemplateChangeRefused(
            code="github_repository_not_connected",
            detail=f"This project's GitHub integration can't reach `{repository}`.",
            why="PostHog Code works only in repositories that the project's GitHub integration can reach.",
            fix=f"Connect GitHub in the project's integrations and give the PostHog app access to `{repository}`, "
            "then request the change again.",
        )


def _posthog_code_not_available(*, why: str, fix: str) -> TemplateChangeRefused:
    return TemplateChangeRefused(
        code="posthog_code_not_available",
        detail="PostHog Code is not available to start this change.",
        why=why,
        fix=fix,
    )
