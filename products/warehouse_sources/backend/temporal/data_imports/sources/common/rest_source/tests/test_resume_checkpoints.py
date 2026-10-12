import json
from collections.abc import Callable, Iterator
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from requests import PreparedRequest, Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import RESTAPIConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import (
    activate_safe_point,
    reach_safe_point,
)


class PagedSession:
    def __init__(self, pages_by_path: dict[str, list[list[dict[str, Any]]]]) -> None:
        self.headers: dict[str, str] = {}
        self._pages_by_path = pages_by_path

    def prepare_request(self, request: Request) -> PreparedRequest:
        return Session().prepare_request(request)

    def send(self, prepared: PreparedRequest, **_kwargs: Any) -> Response:
        parts = urlsplit(cast(str, prepared.url))
        page = int(parse_qs(parts.query).get("page", ["0"])[0])
        pages = self._pages_by_path[parts.path]
        response = Response()
        response.status_code = 200
        response._content = json.dumps(pages[page] if page < len(pages) else []).encode()
        response.url = cast(str, prepared.url)
        return response


def paged_config(
    pages_by_path: dict[str, list[list[dict[str, Any]]]], resources: list[Any], total_pages: Optional[int] = None
) -> RESTAPIConfig:
    return cast(
        RESTAPIConfig,
        {
            "client": {
                "base_url": "https://api.example.com",
                "session": PagedSession(pages_by_path),
                "paginator": {"type": "page_number", "base_page": 0, "total_path": None, "maximum_page": total_pages},
            },
            "resources": resources,
        },
    )


def _resource(
    config: RESTAPIConfig, name: str, hook: Callable[[Optional[dict[str, Any]]], None], state: Any = None
) -> Resource:
    resources = rest_api_resources(config, 1, "job", None, resume_hook=hook, initial_paginator_state=state)
    return next(resource for resource in resources if resource.name == name)


def _wrapped(resource: Resource) -> Iterator[list[dict[str, Any]]]:
    yield from resource


ITEMS = {"/items": [[{"id": 1}], [{"id": 2}]]}
FANOUT = {
    "/parents": [[{"id": "a"}, {"id": "b"}]],
    "/parents/a/children": [[{"id": "a1"}], [{"id": "a2"}]],
    "/parents/b/children": [[{"id": "b1"}]],
}
FANOUT_RESOURCES: list[Any] = [
    "parents",
    {
        "name": "children",
        "endpoint": {
            "path": "/parents/{parent_id}/children",
            "params": {"parent_id": {"type": "resolve", "resource": "parents", "field": "id"}},
        },
    },
]


def _events(items: Any, events: list[Any], *, covers_framework_checkpoints: bool) -> list[Any]:
    with activate_safe_point(
        lambda: events.append("safe_point"), covers_framework_checkpoints=covers_framework_checkpoints
    ):
        for page in items:
            events.append([row["id"] for row in page])
    return events


@pytest.mark.parametrize(
    "wrapped,expected",
    [
        (False, [{"page": 1}, [1], "safe_point", None, [2], "safe_point"]),
        (True, [[1], {"page": 1}, [2], None]),
    ],
    ids=["pipeline_iterates_the_resource", "source_wraps_the_resource"],
)
def test_a_page_reaches_the_pipeline_with_its_resume_state_only_when_nothing_wraps_the_resource(
    wrapped: bool, expected: list[Any]
) -> None:
    events: list[Any] = []
    resource = _resource(paged_config(ITEMS, ["items"], total_pages=1), "items", events.append)

    _events(_wrapped(resource) if wrapped else resource, events, covers_framework_checkpoints=not wrapped)

    assert events == expected


def test_a_safe_point_inside_the_hook_waits_until_the_page_is_handed_on() -> None:
    events: list[Any] = []

    def hook(state: Optional[dict[str, Any]]) -> None:
        events.append(state)
        reach_safe_point()

    resource = _resource(paged_config(ITEMS, ["items"], total_pages=1), "items", hook)

    _events(resource, events, covers_framework_checkpoints=True)

    assert events == [{"page": 1}, [1], "safe_point", None, [2], "safe_point"]


def test_a_page_that_fails_its_transform_leaves_its_resume_state_unstaged() -> None:
    states: list[Any] = []
    resource = _resource(paged_config(ITEMS, ["items"], total_pages=1), "items", states.append)

    def fail_on_second_page(row: dict[str, Any]) -> dict[str, Any]:
        if row["id"] == 2:
            raise ValueError("bad row")
        return row

    resource.add_map(fail_on_second_page)

    with pytest.raises(ValueError, match="bad row"):
        _events(resource, [], covers_framework_checkpoints=True)

    assert states == [{"page": 1}]


def test_the_last_page_of_a_parent_is_handed_on_with_the_parent_recorded_complete() -> None:
    events: list[Any] = []
    resource = _resource(paged_config(FANOUT, FANOUT_RESOURCES, total_pages=1), "children", events.append)

    _events(resource, events, covers_framework_checkpoints=True)

    states_before = {tuple(page): events[index - 1] for index, page in enumerate(events) if isinstance(page, list)}
    assert states_before[("a1",)] == {
        "completed": [],
        "current": "/parents/a/children",
        "child_state": {"page": 1},
    }
    assert states_before[("a2",)] == {"completed": ["/parents/a/children"], "current": None, "child_state": None}
    assert states_before[("b1",)]["current"] == "/parents/b/children"


class _NoResumeStatePaginator(PageNumberPaginator):
    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return None


def test_a_parent_stays_in_progress_while_a_paginator_without_resume_state_has_more_pages() -> None:
    events: list[Any] = []
    children = {
        **FANOUT_RESOURCES[1],
        "endpoint": {**FANOUT_RESOURCES[1]["endpoint"], "paginator": _NoResumeStatePaginator()},
    }
    resource = _resource(paged_config(FANOUT, ["parents", children]), "children", events.append)

    _events(resource, events, covers_framework_checkpoints=True)

    assert events[events.index(["a1"]) - 1] == {
        "completed": [],
        "current": "/parents/a/children",
        "child_state": None,
    }


@pytest.mark.parametrize("stop_after_pages", [1, 2, 3])
def test_a_fan_out_resumed_from_the_state_staged_with_a_page_reads_every_row_once(stop_after_pages: int) -> None:
    states: list[Any] = []
    first = _resource(paged_config(FANOUT, FANOUT_RESOURCES), "children", states.append)
    rows: list[str] = []
    with activate_safe_point(lambda: None, covers_framework_checkpoints=True):
        for index, page in enumerate(first, start=1):
            rows.extend(row["id"] for row in page)
            if index == stop_after_pages:
                break

    resumed = _resource(paged_config(FANOUT, FANOUT_RESOURCES), "children", lambda _state: None, states[-1])
    rows.extend(row["id"] for page in resumed for row in page)

    assert rows == ["a1", "a2", "b1"]
