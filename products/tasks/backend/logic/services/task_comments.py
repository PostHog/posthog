from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import Count, Q, QuerySet

from posthog.models import Comment

from products.tasks.backend.facade import contracts
from products.tasks.backend.models import TaskArtifact, TaskRun, TaskThreadMessage

COMMENT_STATES = frozenset({"open", "resolved"})
LEGACY_TASK_RUN_LIMIT = 100
TASK_ARTIFACT_LIMIT = 500
CANVAS_EVENT_LIMIT = 500
LIST_CONTENT_BYTES = 1024
SELECTED_TEXT_BYTES = 1024
DETAIL_CONTENT_BUDGET_BYTES = 64 * 1024
ANCHOR_QUOTE_BYTES = 4096


class InvalidTaskCommentCursor(ValueError):
    pass


def _item_context(comment: Comment) -> dict:
    return comment.item_context if isinstance(comment.item_context, dict) else {}


def _content_chunk(content: str, *, limit: int, offset: int = 0) -> tuple[str, int | None]:
    encoded = content.encode("utf-8")
    end = min(len(encoded), offset + limit)
    chunk = encoded[offset:end].decode("utf-8", errors="ignore")
    return chunk, end if end < len(encoded) else None


def _bounded_anchor(comment: Comment) -> dict | None:
    anchor = _item_context(comment).get("anchor")
    if not isinstance(anchor, dict):
        return None
    kind = anchor.get("kind")
    allowed_fields_by_kind: dict[str, tuple[str, ...]] = {
        "text": ("prefix", "suffix", "start", "end"),
        "region": ("x", "y", "width", "height"),
    }
    if not isinstance(kind, str) or kind not in allowed_fields_by_kind:
        return None
    bounded = {"kind": kind}
    allowed_fields = allowed_fields_by_kind[kind]
    for field in allowed_fields:
        if field in anchor:
            bounded[field] = anchor[field]
    if kind == "text" and isinstance(anchor.get("quote"), str):
        bounded["quote"] = _content_chunk(anchor["quote"], limit=ANCHOR_QUOTE_BYTES)[0]
    return bounded


def _artifact_names(*, team_id: int, task_id: UUID, artifact_ids: Sequence[str]) -> dict[str, str]:
    wanted = set(artifact_ids)
    relational_ids: list[UUID] = []
    for artifact_id in wanted:
        try:
            relational_ids.append(UUID(artifact_id))
        except ValueError:
            pass
    names = {
        str(artifact_id): name
        for artifact_id, name in TaskArtifact.objects.for_team(team_id)
        .filter(task_id=task_id, id__in=relational_ids)
        .values_list("id", "name")
    }
    missing = wanted - names.keys()
    if not missing:
        return names
    for artifacts in (
        TaskRun.objects.filter(team_id=team_id, task_id=task_id)
        .order_by("-created_at", "-id")
        .values_list("artifacts", flat=True)[:LEGACY_TASK_RUN_LIMIT]
    ):
        for artifact in artifacts or []:
            artifact_id = str(artifact.get("id") or "") if isinstance(artifact, dict) else ""
            name = artifact.get("name") if isinstance(artifact, dict) else None
            if artifact_id in missing and isinstance(name, str) and name:
                names[artifact_id] = name
                missing.remove(artifact_id)
        if not missing:
            break
    return names


def _is_state_event(comment: Comment) -> bool:
    return _item_context(comment).get("threadState") in COMMENT_STATES


def _encode_cursor(created_at: datetime, comment_id: UUID) -> str:
    return urlsafe_b64encode(f"{created_at.isoformat()}|{comment_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    if len(cursor) > 256:
        raise InvalidTaskCommentCursor
    try:
        decoded = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        created_at, comment_id = decoded.rsplit("|", 1)
        parsed_created_at = datetime.fromisoformat(created_at)
        if parsed_created_at.utcoffset() is None:
            raise InvalidTaskCommentCursor
        return parsed_created_at, UUID(comment_id)
    except (ValueError, UnicodeDecodeError):
        raise InvalidTaskCommentCursor from None


def _comments(team_id: int, task_id: UUID) -> QuerySet[Comment]:
    task_id_string = str(task_id)
    return (
        Comment.objects.filter(team_id=team_id, deleted=False)
        .filter(
            Q(scope="task", item_id=task_id_string)
            | Q(scope__in=["task_artifact", "desktop_canvas"], item_context__taskId=task_id_string)
        )
        .filter(Q(item_context__isnull=True) | ~Q(item_context__has_key="is_emoji") | Q(item_context__is_emoji=False))
    )


def _canvas_names(*, team_id: int, task_id: UUID, canvas_ids: Sequence[str]) -> dict[str, str]:
    wanted = set(canvas_ids)
    names: dict[str, str] = {}
    if not wanted:
        return names
    for payload in (
        TaskThreadMessage.objects.for_team(team_id)
        .filter(task_id=task_id, event="canvas_created")
        .order_by("-created_at", "-id")
        .values_list("payload", flat=True)[:CANVAS_EVENT_LIMIT]
    ):
        canvas_url = payload.get("canvas_url") if isinstance(payload, dict) else None
        canvas_id = canvas_url.rstrip("/").rsplit("/", 1)[-1] if isinstance(canvas_url, str) else ""
        canvas_name = payload.get("canvas_name") if isinstance(payload, dict) else None
        if canvas_id in wanted and isinstance(canvas_name, str) and canvas_name:
            names.setdefault(canvas_id, canvas_name)
            if len(names) == len(wanted):
                break
    return names


def _target(comment: Comment, target_names: dict[tuple[str, str], str]) -> contracts.TaskCommentTargetDTO:
    if comment.scope == "task":
        return contracts.TaskCommentTargetDTO(id=str(comment.item_id), type="task", name="This task")
    item_id = comment.item_id or ""
    if comment.scope == "task_artifact":
        return contracts.TaskCommentTargetDTO(
            id=item_id, type="artifact", name=target_names.get(("artifact", item_id), item_id or "Artifact")
        )
    return contracts.TaskCommentTargetDTO(
        id=item_id, type="canvas", name=target_names.get(("canvas", item_id), item_id or "Canvas")
    )


def _resolved(root: Comment, latest_state: str | None) -> bool:
    if latest_state is not None:
        return latest_state == "resolved"
    return root.completed_at is not None


def _target_names_for_roots(*, team_id: int, task_id: UUID, roots: Sequence[Comment]) -> dict[tuple[str, str], str]:
    artifact_ids = [root.item_id for root in roots if root.scope == "task_artifact" and root.item_id]
    canvas_ids = [root.item_id for root in roots if root.scope == "desktop_canvas" and root.item_id]
    return {
        **{
            ("artifact", artifact_id): name
            for artifact_id, name in _artifact_names(
                team_id=team_id, task_id=task_id, artifact_ids=artifact_ids
            ).items()
        },
        **{
            ("canvas", canvas_id): name
            for canvas_id, name in _canvas_names(team_id=team_id, task_id=task_id, canvas_ids=canvas_ids).items()
        },
    }


def list_artifacts(*, team_id: int, task_id: UUID) -> list[contracts.TaskArtifactDTO]:
    artifacts: dict[tuple[str, str], contracts.TaskArtifactDTO] = {}
    relational_artifacts = (
        TaskArtifact.objects.for_team(team_id)
        .filter(task_id=task_id)
        .order_by("-updated_at", "-id")
        .values_list("id", "name")[:TASK_ARTIFACT_LIMIT]
    )
    for artifact_id, name in relational_artifacts:
        relational_id = str(artifact_id)
        artifacts[("artifact", relational_id)] = contracts.TaskArtifactDTO(id=relational_id, type="artifact", name=name)
    for manifest in (
        TaskRun.objects.filter(team_id=team_id, task_id=task_id)
        .order_by("-created_at", "-id")
        .values_list("artifacts", flat=True)[:LEGACY_TASK_RUN_LIMIT]
    ):
        for artifact in manifest or []:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("id") or "")
            artifact_name = artifact.get("name")
            artifact_key = ("artifact", artifact_id)
            if artifact_id and artifact_key not in artifacts and isinstance(artifact_name, str) and artifact_name:
                artifacts[artifact_key] = contracts.TaskArtifactDTO(id=artifact_id, type="artifact", name=artifact_name)
    for payload in (
        TaskThreadMessage.objects.for_team(team_id)
        .filter(task_id=task_id, event="canvas_created")
        .order_by("-created_at", "-id")
        .values_list("payload", flat=True)[:CANVAS_EVENT_LIMIT]
    ):
        canvas_url = payload.get("canvas_url") if isinstance(payload, dict) else None
        canvas_name = payload.get("canvas_name") if isinstance(payload, dict) else None
        canvas_id = canvas_url.rstrip("/").rsplit("/", 1)[-1] if isinstance(canvas_url, str) else ""
        if canvas_id:
            artifacts.setdefault(
                ("canvas", canvas_id),
                contracts.TaskArtifactDTO(
                    id=canvas_id,
                    type="canvas",
                    name=canvas_name if isinstance(canvas_name, str) and canvas_name else "Canvas",
                ),
            )
    return sorted(artifacts.values(), key=lambda artifact: (artifact.type, artifact.id))


def list_comments(
    *,
    team_id: int,
    task_id: UUID,
    artifact_id: str | None,
    include_resolved: bool,
    limit: int,
    cursor: str | None,
) -> contracts.TaskCommentPageDTO:
    roots_qs = _comments(team_id, task_id).filter(source_comment_id__isnull=True)
    if artifact_id:
        roots_qs = roots_qs.filter(scope__in=["task_artifact", "desktop_canvas"], item_id=artifact_id)
    scan_cursor = _decode_cursor(cursor) if cursor else None
    result: list[contracts.TaskCommentSummaryDTO] = []
    next_cursor = None
    while len(result) < limit:
        batch_qs = roots_qs
        if scan_cursor:
            before, before_id = scan_cursor
            batch_qs = batch_qs.filter(Q(created_at__lt=before) | Q(created_at=before, id__lt=before_id))
        remaining = limit - len(result)
        batch = list(batch_qs.order_by("-created_at", "-id")[: remaining + 1])
        has_more = len(batch) > remaining
        roots = batch[:remaining]
        if not roots:
            break
        root_ids = [root.id for root in roots]
        reply_qs = _comments(team_id, task_id).filter(source_comment_id__in=root_ids)
        human_replies = reply_qs.filter(
            Q(item_context__isnull=True)
            | ~Q(item_context__has_key="threadState")
            | ~Q(item_context__threadState__in=COMMENT_STATES)
        )
        reply_counts = dict(human_replies.values_list("source_comment_id").annotate(count=Count("id")))
        latest_states = {
            source_comment_id: item_context.get("threadState")
            for source_comment_id, item_context in reply_qs.filter(item_context__threadState__in=COMMENT_STATES)
            .order_by("source_comment_id", "-created_at", "-id")
            .distinct("source_comment_id")
            .values_list("source_comment_id", "item_context")
            if isinstance(item_context, dict)
        }
        target_names = _target_names_for_roots(team_id=team_id, task_id=task_id, roots=roots)
        for root in roots:
            resolved = _resolved(root, latest_states.get(root.id))
            if resolved and not include_resolved:
                continue
            content, content_next_offset = _content_chunk(root.content or "", limit=LIST_CONTENT_BYTES)
            anchor = _item_context(root).get("anchor")
            selected_text = anchor.get("quote") if isinstance(anchor, dict) else None
            if isinstance(selected_text, str):
                selected_text = _content_chunk(selected_text, limit=SELECTED_TEXT_BYTES)[0]
            else:
                selected_text = None
            result.append(
                contracts.TaskCommentSummaryDTO(
                    id=root.id,
                    target=_target(root, target_names),
                    content=content,
                    content_truncated=content_next_offset is not None,
                    selected_text=selected_text,
                    created_at=root.created_at,
                    reply_count=reply_counts.get(root.id, 0),
                    resolved=resolved,
                )
            )
        scan_cursor = (roots[-1].created_at, roots[-1].id)
        if len(result) == limit:
            next_cursor = _encode_cursor(*scan_cursor) if has_more else None
            break
        if not has_more:
            break
    return contracts.TaskCommentPageDTO(comments=result, next=next_cursor)


def _entry(comment: Comment, *, content_budget: int, content_offset: int = 0) -> contracts.TaskCommentEntryDTO:
    creator = comment.created_by
    author = " ".join(filter(None, [creator.first_name, creator.last_name])) or None if creator is not None else None
    content, content_next_offset = _content_chunk(comment.content or "", limit=content_budget, offset=content_offset)
    return contracts.TaskCommentEntryDTO(
        id=comment.id,
        content=content,
        content_truncated=content_next_offset is not None,
        content_next_offset=content_next_offset,
        author=author,
        created_at=comment.created_at,
        anchor=_bounded_anchor(comment),
        canvas_version_id=_item_context(comment).get("canvasVersionId"),
    )


def retrieve_comment(
    *,
    team_id: int,
    task_id: UUID,
    comment_id: UUID,
    limit: int,
    cursor: str | None,
    content_comment_id: UUID | None,
    content_offset: int,
) -> contracts.TaskCommentDetailDTO | None:
    root = (
        _comments(team_id, task_id)
        .select_related("created_by")
        .filter(id=comment_id, source_comment_id__isnull=True)
        .first()
    )
    if root is None:
        return None
    latest_state_reply = (
        _comments(team_id, task_id)
        .filter(source_comment_id=root.id, item_context__threadState__in=COMMENT_STATES)
        .order_by("-created_at", "-id")
        .first()
    )
    thread_comments_qs = (
        _comments(team_id, task_id)
        .filter(Q(id=root.id) | Q(source_comment_id=root.id))
        .filter(
            Q(id=root.id)
            | Q(item_context__isnull=True)
            | ~Q(item_context__has_key="threadState")
            | ~Q(item_context__threadState__in=COMMENT_STATES)
        )
    )
    if content_comment_id is not None:
        content_comment = thread_comments_qs.select_related("created_by").filter(id=content_comment_id).first()
        if content_comment is None:
            return None
        comments = [
            _entry(
                content_comment,
                content_budget=DETAIL_CONTENT_BUDGET_BYTES,
                content_offset=content_offset,
            )
        ]
        next_cursor = None
    else:
        comments_qs = thread_comments_qs
        if cursor:
            after, after_id = _decode_cursor(cursor)
            comments_qs = comments_qs.filter(Q(created_at__gt=after) | Q(created_at=after, id__gt=after_id))
        comment_models = list(comments_qs.select_related("created_by").order_by("created_at", "id")[: limit + 1])
        has_more = len(comment_models) > limit
        comment_models = comment_models[:limit]
        remaining_content_bytes = DETAIL_CONTENT_BUDGET_BYTES
        comments = []
        for comment in comment_models:
            entry = _entry(comment, content_budget=remaining_content_bytes)
            remaining_content_bytes -= len(entry.content.encode("utf-8"))
            comments.append(entry)
        next_cursor = (
            _encode_cursor(comment_models[-1].created_at, comment_models[-1].id)
            if has_more and comment_models
            else None
        )
    target_names = _target_names_for_roots(team_id=team_id, task_id=task_id, roots=[root])
    return contracts.TaskCommentDetailDTO(
        id=root.id,
        target=_target(root, target_names),
        resolved=_resolved(
            root,
            _item_context(latest_state_reply).get("threadState") if latest_state_reply else None,
        ),
        comments=comments,
        next=next_cursor,
    )
