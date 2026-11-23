from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from . import project_api
from .mappings import load_mapping, validate_key
from .translate_out import translate_error
from .types import Credentials, EngineError, Entity, EntityPage

_ABSENT = object()


def _malformed() -> EngineError:
    return EngineError(
        [
            {
                "code": "lookup_failed",
                "message": "PostHog could not read the complete context page. Try pulling the page again.",
            }
        ]
    )


def _moved() -> EngineError:
    return EngineError(
        [{"code": "stack_moved", "message": "The wiki changed while reading its pages. Start the pull again."}]
    )


def _wiki_problem(status: int, problem: Any, *, missing_path: str | None = None) -> object:
    if isinstance(problem, dict):
        detail = problem.get("detail")
        if (
            status == 403
            and (
                problem.get("code") == "feature_flag_required"
                or detail == "This action requires feature flag 'context-layer' to be enabled for your organization."
            )
        ) or (status == 404 and detail == "The context layer is not enabled for this organization."):
            raise EngineError(translate_error("the context layer is not enabled for project"))
        if status == 409 and (problem.get("head_sha") or problem.get("current_head")):
            raise _moved()
        if status == 404 and missing_path is not None and detail == f"no page at {missing_path}":
            return _ABSENT
    raise EngineError(translate_error(f"HTTP {status}"))


def _read_page(
    credentials: Credentials, path: str, deadline: float | None, *, head: str | None = None, allow_missing: bool = False
) -> Entity | None:
    if validate_key("context_page", path) is not None:
        raise EngineError(
            [{"code": "entity_read_invalid", "message": "Choose a valid context page path and try the pull again."}]
        )
    base = project_api.collection_url(credentials, load_mapping("context_page")["read_api"]["collection"])
    query = {"path": path}
    if head is not None:
        query["head_sha"] = head
    page = project_api.get(
        credentials,
        base._replace(query=urlencode(query)),
        deadline,
        on_error=lambda status, problem: _wiki_problem(status, problem, missing_path=path if allow_missing else None),
    )
    if page is _ABSENT:
        return None
    if (
        not isinstance(page, dict)
        or page.get("path") != path
        or not isinstance(content := page.get("content"), str)
        or not isinstance(revision := page.get("head_sha"), str)
        or not revision
        or page.get("complete") is not True
        or type(page.get("offset")) is not int
        or page["offset"] != 0
        or page.get("next_offset") is not None
    ):
        raise _malformed()
    length = page.get("total_length")
    if length is not None and (type(length) is not int or length != len(content)):
        raise _malformed()
    if head is not None and head != revision:
        raise _moved()
    return {
        "entity_id": path,
        "name": path,
        "body": {"path": path, "content": content.replace("\r\n", "\n").replace("\r", "\n")},
    }


def existing_pages(credentials: Credentials, paths: Iterable[str], deadline: float | None) -> Iterator[dict[str, str]]:
    for path in paths:
        if _read_page(credentials, path, deadline, allow_missing=True) is not None:
            yield {"path": path, "id": path}


def _organization(credentials: Credentials, deadline: float) -> str:
    # The project page route has no tree. Organization listings expose the team IDs visible to this credential.
    project = str(credentials["project_id"])
    found = set()
    for row in project_api.rows(credentials, project_api.api_url(credentials, "organizations"), deadline):
        teams = row.get("teams")
        if not isinstance(teams, list):
            raise _malformed()
        if any(isinstance(team, dict) and str(team.get("id")) == project for team in teams):
            try:
                found.add(str(UUID(row["id"])))
            except (KeyError, ValueError, TypeError, AttributeError):
                raise _malformed() from None
    if len(found) != 1:
        raise EngineError(
            [
                {
                    "code": "lookup_failed",
                    "message": "Check that your API key can identify this project's organization, or pull the pages by path.",
                }
            ]
        )
    return found.pop()


def read_pages(
    credentials: Credentials, ids: list[str] | None, offset: int, limit: int, deadline: float, revision: str | None
) -> EntityPage:
    head = None
    if ids is None:
        org = _organization(credentials, deadline)
        route = load_mapping("context_page")["read_api"]["organization_tree"]
        tree = project_api.get(
            credentials,
            project_api.api_url(credentials, f"organizations/{org}/{route}"),
            deadline,
            on_error=_wiki_problem,
        )
        if (
            not isinstance(tree, dict)
            or not isinstance(head := tree.get("head_sha"), str)
            or not head
            or len(head) > 64
            or not isinstance(paths := tree.get("paths"), list)
            or not all(isinstance(path, str) for path in paths)
        ):
            raise _malformed()
        if revision is not None and revision != head:
            raise _moved()
        ordered = sorted({path for path in paths if validate_key("context_page", path) is None})
    else:
        if not isinstance(ids, list) or not all(
            isinstance(path, str) and validate_key("context_page", path) is None for path in ids
        ):
            raise EngineError(
                [{"code": "entity_read_invalid", "message": "Choose valid context page paths and try the pull again."}]
            )
        ordered = list(dict.fromkeys(ids))
    results = []
    for path in ordered[offset : offset + limit]:
        page = _read_page(credentials, path, deadline, head=head)
        if page is None:
            raise _malformed()
        results.append(page)
    cursor = None
    if offset + limit < len(ordered):
        cursor = str(offset + limit) if head is None else f"{offset + limit}.{head}"
    return {"results": results, "next_cursor": cursor}
