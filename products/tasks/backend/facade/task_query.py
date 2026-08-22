import re
from typing import Literal, cast
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery
from django.db.models.fields.json import KeyTextTransform

from posthog.dataclasses import frozen
from posthog.models import User

from products.tasks.backend.models import Channel, Task, TaskPin, TaskRun, TaskThreadMessage, TaskThreadMessageMention

TaskQueryKey = Literal[
    "created-by",
    "commented-by",
    "mentions",
    "involves",
    "space",
    "repo",
    "status",
    "origin",
    "is",
    "pr",
    "ci",
    "type",
    "saved",
]

_KEY_ALIASES: dict[str, TaskQueryKey] = {
    "created-by": "created-by",
    "author": "created-by",
    "by": "created-by",
    "commented-by": "commented-by",
    "commenter": "commented-by",
    "mentions": "mentions",
    "mentioned": "mentions",
    "involves": "involves",
    "space": "space",
    "channel": "space",
    "repo": "repo",
    "repository": "repo",
    "status": "status",
    "origin": "origin",
    "is": "is",
    "pr": "pr",
    "ci": "ci",
    "type": "type",
    "saved": "saved",
}

_STATUS_ALIASES = {"running": "in_progress", "done": "completed"}
_IS_STATUS_SUGAR = {"running": "in_progress", "done": "completed", "failed": "failed"}
_ORIGIN_ALIASES = {
    "desktop": "user_created",
    "user": "user_created",
    "scout": "signals_scout",
    "signals": "signal_report",
    "ai": "posthog_ai",
    "max": "posthog_ai",
    "errors": "error_tracking",
    "support": "support_queue",
    "replay": "session_summaries",
}
_TASK_RUN_STATUSES = {status.value for status in TaskRun.Status}
_PR_VALUES = {"any", "none", "open", "draft", "merged", "closed"}
_CI_ALIASES = {"red": "failing", "green": "passing"}
_CI_VALUES = {"red", "green", "failing", "passing", "pending", "none"}
_TYPE_VALUES = {"task", "space", "command", "saved"}
_CHUNK_RE = re.compile(r'(?:[^\s"]+|"[^"]*")+')
_TOKEN_RE = re.compile(r"^(-)?([A-Za-z][A-Za-z-]*):(.*)$")
_QUOTED_VALUE_RE = re.compile(r'"([^"]*)"')


class TaskQueryError(ValueError):
    pass


@frozen
class TaskQueryToken:
    key: TaskQueryKey
    value: str
    negated: bool


@frozen
class ParsedTaskQuery:
    text: str
    tokens: tuple[TaskQueryToken, ...]


def parse_task_query(query: str) -> ParsedTaskQuery:
    words: list[str] = []
    tokens: list[TaskQueryToken] = []

    for raw in _CHUNK_RE.findall(query):
        match = _TOKEN_RE.fullmatch(raw)
        key = _KEY_ALIASES.get(match.group(2).lower()) if match else None
        if match is None or key is None:
            words.append(_unquote(raw))
            continue

        value = _unquote(match.group(3))
        if value == "":
            raise TaskQueryError(f'A value is required after "{match.group(2)}:"')
        negated = match.group(1) == "-"
        if value.lower().startswith("not:"):
            negated = True
            value = value[4:]
        if value == "":
            raise TaskQueryError(f'A value is required after "{match.group(2)}:"')
        token = TaskQueryToken(key=key, value=value, negated=negated)
        _validate_token(token)
        tokens.append(token)

    return ParsedTaskQuery(text=" ".join(words), tokens=tuple(tokens))


def filter_tasks_by_query(
    tasks: QuerySet[Task],
    *,
    query: str,
    team_id: int,
    organization_id: UUID,
    user_id: int | None,
) -> QuerySet[Task]:
    parsed = parse_task_query(query)
    positives: dict[TaskQueryKey, list[str]] = {}
    negatives: dict[TaskQueryKey, list[str]] = {}

    for token in parsed.tokens:
        values = negatives if token.negated else positives
        values.setdefault(token.key, []).append(token.value)

    if parsed.text:
        tasks = _filter_text(tasks, parsed.text)

    tasks = _filter_people(
        tasks,
        positives.get("created-by", []),
        negatives.get("created-by", []),
        team_id,
        organization_id,
        user_id,
        "created_by",
    )
    tasks = _filter_people(
        tasks,
        positives.get("commented-by", []),
        negatives.get("commented-by", []),
        team_id,
        organization_id,
        user_id,
        "commented_by",
    )
    tasks = _filter_people(
        tasks,
        positives.get("mentions", []),
        negatives.get("mentions", []),
        team_id,
        organization_id,
        user_id,
        "mentions",
    )
    tasks = _filter_people(
        tasks,
        positives.get("involves", []),
        negatives.get("involves", []),
        team_id,
        organization_id,
        user_id,
        "involves",
    )
    tasks = _filter_channels(tasks, positives.get("space", []), negatives.get("space", []), team_id, user_id)
    tasks = _filter_repositories(tasks, positives.get("repo", []), negatives.get("repo", []))
    tasks = _filter_origins(tasks, positives.get("origin", []), negatives.get("origin", []))
    tasks = _filter_archived(tasks, positives.get("is", []), negatives.get("is", []))
    tasks = _filter_pinned(tasks, positives.get("is", []), negatives.get("is", []), user_id)
    tasks = _filter_types(tasks, positives.get("type", []), negatives.get("type", []))
    _reject_saved_searches(positives.get("saved", []), negatives.get("saved", []))

    status_values = _status_values(positives.get("status", []), positives.get("is", []))
    excluded_status_values = _status_values(negatives.get("status", []), negatives.get("is", []))
    if status_values or excluded_status_values:
        tasks = _annotate_latest_status(tasks, team_id)
        if status_values:
            tasks = tasks.filter(**{"_task_query_latest_status__in": status_values})
        if excluded_status_values:
            tasks = tasks.exclude(**{"_task_query_latest_status__in": excluded_status_values})

    pr_values = positives.get("pr", [])
    excluded_pr_values = negatives.get("pr", [])
    if pr_values or excluded_pr_values:
        tasks = _annotate_latest_pr(tasks, team_id)
        if pr_values:
            tasks = tasks.filter(_pr_condition(pr_values))
        if excluded_pr_values:
            tasks = tasks.exclude(_pr_condition(excluded_pr_values))

    ci_values = _ci_values(positives.get("ci", []))
    excluded_ci_values = _ci_values(negatives.get("ci", []))
    if ci_values or excluded_ci_values:
        tasks = _annotate_latest_ci_status(tasks, team_id)
        if ci_values:
            tasks = tasks.filter(**{"_task_query_latest_ci_status__in": ci_values})
        if excluded_ci_values:
            tasks = tasks.exclude(**{"_task_query_latest_ci_status__in": excluded_ci_values})

    return tasks


def _unquote(value: str) -> str:
    return _QUOTED_VALUE_RE.sub(r"\1", value)


def _normalize(value: str) -> str:
    return value.strip().lower()


def _validate_token(token: TaskQueryToken) -> None:
    value = _normalize(token.value)
    if token.key == "status" and value not in _STATUS_ALIASES and value not in _TASK_RUN_STATUSES:
        raise TaskQueryError(
            f'Unknown status "{token.value}". Expected one of: {", ".join(sorted(_TASK_RUN_STATUSES))}'
        )
    if token.key == "is" and value not in {"archived", "pinned", *_IS_STATUS_SUGAR}:
        raise TaskQueryError('Unknown "is:" value. Expected archived, pinned, running, done, or failed')
    if token.key == "pr" and value not in _PR_VALUES:
        raise TaskQueryError(f'Unknown "pr:" value. Expected one of: {", ".join(sorted(_PR_VALUES))}')
    if token.key == "ci" and value not in _CI_VALUES:
        raise TaskQueryError(f'Unknown "ci:" value. Expected one of: {", ".join(sorted(_CI_VALUES))}')
    if token.key == "type" and value not in _TYPE_VALUES:
        raise TaskQueryError(f'Unknown "type:" value. Expected one of: {", ".join(sorted(_TYPE_VALUES))}')


def _filter_text(tasks: QuerySet[Task], text: str) -> QuerySet[Task]:
    matches = Q(title__icontains=text) | Q(description__icontains=text)
    number = text.split("-")[-1].strip()
    if number.isdigit():
        matches |= Q(task_number=int(number))
    return tasks.filter(matches)


def _matching_member_ids(organization_id: UUID, value: str, user_id: int | None) -> set[int]:
    normalized = _normalize(value)
    if normalized in {"@me", "me"}:
        if user_id is None:
            raise TaskQueryError('"@me" requires an authenticated user')
        return {user_id}

    name_parts = normalized.split(maxsplit=1)
    matches = Q(email__iexact=normalized) | Q(first_name__istartswith=normalized) | Q(last_name__istartswith=normalized)
    if len(name_parts) == 2:
        matches |= Q(first_name__istartswith=name_parts[0], last_name__istartswith=name_parts[1])
    member_ids = set(User.objects.filter(organization=organization_id).filter(matches).values_list("id", flat=True))
    if not member_ids:
        raise TaskQueryError(f'No teammate matches "{value}"')
    return member_ids


def _member_ids(organization_id: UUID, values: list[str], user_id: int | None) -> set[int]:
    return set().union(*(_matching_member_ids(organization_id, value, user_id) for value in values))


def _commented_by_condition(team_id: int, member_ids: set[int]) -> Exists:
    return Exists(
        TaskThreadMessage.objects.for_team(team_id).filter(
            task=OuterRef("pk"),
            author_id__in=member_ids,
            author_kind=TaskThreadMessage.AuthorKind.HUMAN,
        )
    )


def _mentions_condition(team_id: int, member_ids: set[int]) -> Exists:
    return Exists(
        TaskThreadMessageMention.objects.for_team(team_id)
        .filter(task=OuterRef("pk"), mentioned_user_id__in=member_ids)
        .exclude(message__event="turn_complete")
    )


def _filter_people(
    tasks: QuerySet[Task],
    values: list[str],
    excluded_values: list[str],
    team_id: int,
    organization_id: UUID,
    user_id: int | None,
    query_type: Literal["created_by", "commented_by", "mentions", "involves"],
) -> QuerySet[Task]:
    def condition(member_ids: set[int]) -> Q | Exists:
        if query_type == "created_by":
            return Q(created_by_id__in=member_ids)
        if query_type == "commented_by":
            return _commented_by_condition(team_id, member_ids)
        if query_type == "mentions":
            return _mentions_condition(team_id, member_ids)
        return cast(Q | Exists, Q(created_by_id__in=member_ids) | _commented_by_condition(team_id, member_ids))

    if values:
        tasks = tasks.filter(condition(_member_ids(organization_id, values, user_id)))
    if excluded_values:
        tasks = tasks.exclude(condition(_member_ids(organization_id, excluded_values, user_id)))
    return tasks


def _channel_ids(team_id: int, values: list[str], user_id: int | None) -> set[UUID]:
    ids: set[UUID] = set()
    available = Channel.objects.for_team(team_id).filter(Channel.visible_to_q(user_id))
    for value in values:
        channel_ids = set(
            available.filter(name__iexact=_normalize(value).removeprefix("#")).values_list("id", flat=True)
        )
        if not channel_ids:
            raise TaskQueryError(f'No space named "{value}"')
        ids.update(channel_ids)
    return ids


def _filter_channels(
    tasks: QuerySet[Task], values: list[str], excluded_values: list[str], team_id: int, user_id: int | None
) -> QuerySet[Task]:
    if values:
        tasks = tasks.filter(channel_id__in=_channel_ids(team_id, values, user_id))
    if excluded_values:
        tasks = tasks.exclude(channel_id__in=_channel_ids(team_id, excluded_values, user_id))
    return tasks


def _repository_condition(values: list[str]) -> Q:
    condition = Q(pk__in=[])
    for value in values:
        normalized = _normalize(value)
        if "/" in normalized:
            condition |= Q(repository__iexact=normalized)
        else:
            condition |= Q(repository__iendswith=f"/{normalized}")
    return condition


def _filter_repositories(tasks: QuerySet[Task], values: list[str], excluded_values: list[str]) -> QuerySet[Task]:
    if values:
        tasks = tasks.filter(_repository_condition(values))
    if excluded_values:
        tasks = tasks.exclude(_repository_condition(excluded_values))
    return tasks


def _origin_values(values: list[str]) -> set[str]:
    return {_ORIGIN_ALIASES.get(_normalize(value), _normalize(value)) for value in values}


def _filter_origins(tasks: QuerySet[Task], values: list[str], excluded_values: list[str]) -> QuerySet[Task]:
    if values:
        tasks = tasks.filter(origin_product__in=_origin_values(values))
    if excluded_values:
        tasks = tasks.exclude(origin_product__in=_origin_values(excluded_values))
    return tasks


def _filter_archived(tasks: QuerySet[Task], values: list[str], excluded_values: list[str]) -> QuerySet[Task]:
    wants_archived = any(_normalize(value) == "archived" for value in values)
    excludes_archived = any(_normalize(value) == "archived" for value in excluded_values)
    if wants_archived:
        tasks = tasks.filter(archived=True)
    if excludes_archived:
        tasks = tasks.filter(archived=False)
    if not wants_archived and not excludes_archived:
        tasks = tasks.filter(archived=False)
    return tasks


def _filter_pinned(
    tasks: QuerySet[Task], values: list[str], excluded_values: list[str], user_id: int | None
) -> QuerySet[Task]:
    wants_pinned = any(_normalize(value) == "pinned" for value in values)
    excludes_pinned = any(_normalize(value) == "pinned" for value in excluded_values)
    if not wants_pinned and not excludes_pinned:
        return tasks
    if user_id is None:
        return tasks.none()
    is_pinned = Exists(TaskPin.objects.filter(task=OuterRef("pk"), user_id=user_id))
    if wants_pinned:
        tasks = tasks.filter(is_pinned)
    if excludes_pinned:
        tasks = tasks.exclude(is_pinned)
    return tasks


def _filter_types(tasks: QuerySet[Task], values: list[str], excluded_values: list[str]) -> QuerySet[Task]:
    if excluded_values or any(_normalize(value) != "task" for value in values):
        raise TaskQueryError('This tool returns tasks only. Use "type:task" or omit "type:".')
    return tasks


def _reject_saved_searches(values: list[str], excluded_values: list[str]) -> None:
    if values or excluded_values:
        raise TaskQueryError("Saved searches are available in PostHog Desktop but cannot be queried through this tool.")


def _status_values(statuses: list[str], is_values: list[str]) -> set[str]:
    values = {_STATUS_ALIASES.get(_normalize(status), _normalize(status)) for status in statuses}
    values.update(_IS_STATUS_SUGAR[_normalize(value)] for value in is_values if _normalize(value) in _IS_STATUS_SUGAR)
    return values


def _ci_values(values: list[str]) -> set[str]:
    return {_CI_ALIASES.get(_normalize(value), _normalize(value)) for value in values}


def _latest_run(team_id: int) -> QuerySet[TaskRun]:
    return TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id).order_by("-created_at", "-id")


def _annotate_latest_status(tasks: QuerySet[Task], team_id: int) -> QuerySet[Task]:
    return tasks.annotate(_task_query_latest_status=Subquery(_latest_run(team_id).values("status")[:1]))


def _annotate_latest_pr(tasks: QuerySet[Task], team_id: int) -> QuerySet[Task]:
    latest_run = _latest_run(team_id)
    return tasks.annotate(
        _task_query_latest_pr_url=Subquery(
            latest_run.annotate(value=KeyTextTransform("pr_url", "output")).values("value")[:1]
        ),
        _task_query_latest_pr_state=Subquery(
            latest_run.annotate(value=KeyTextTransform("pr_state", "output")).values("value")[:1]
        ),
        _task_query_latest_pr_merged=Subquery(
            latest_run.annotate(value=KeyTextTransform("pr_merged", "output")).values("value")[:1]
        ),
    )


def _annotate_latest_ci_status(tasks: QuerySet[Task], team_id: int) -> QuerySet[Task]:
    return tasks.annotate(
        _task_query_latest_ci_status=Subquery(
            _latest_run(team_id).annotate(value=KeyTextTransform("ci_status", "output")).values("value")[:1]
        )
    )


def _pr_condition(values: list[str]) -> Q:
    condition = Q(pk__in=[])
    for value in values:
        normalized = _normalize(value)
        if normalized == "any":
            condition |= (
                Q(_task_query_latest_pr_url__isnull=False)
                | Q(_task_query_latest_pr_state__isnull=False)
                | Q(_task_query_latest_pr_merged="true")
            )
        elif normalized == "none":
            condition |= Q(
                _task_query_latest_pr_url__isnull=True,
                _task_query_latest_pr_state__isnull=True,
                _task_query_latest_pr_merged__isnull=True,
            ) | Q(
                _task_query_latest_pr_url__isnull=True,
                _task_query_latest_pr_state__isnull=True,
                _task_query_latest_pr_merged="false",
            )
        elif normalized == "merged":
            condition |= Q(_task_query_latest_pr_state="merged") | Q(_task_query_latest_pr_merged="true")
        else:
            condition |= Q(_task_query_latest_pr_state=normalized)
    return condition
