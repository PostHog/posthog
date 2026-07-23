from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import Mock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    _make_paginate_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
    required_parents_from_endpoint_configs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResolvedParam


@dataclass
class _EndpointConfig:
    name: str
    path: str
    incremental_fields: list[Any]
    default_incremental_field: str | None = None
    page_size: int = 100


class _DummyPaginator(BasePaginator):
    def update_state(self, response, data=None) -> None:
        self._has_next_page = False

    def update_request(self, request) -> None:
        return None


def _build_endpoint_configs() -> dict[str, _EndpointConfig]:
    return {
        "parents": _EndpointConfig(
            name="parents",
            path="/parents",
            incremental_fields=[],
            page_size=3,
        ),
        "children": _EndpointConfig(
            name="children",
            path="/parents/{parent_id}/children",
            incremental_fields=[],
            page_size=7,
        ),
    }


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_uses_custom_page_size_param(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            page_size_param="page_size",
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_resource = config["resources"][0]
    child_resource = config["resources"][1]
    assert parent_resource["endpoint"]["params"]["page_size"] == 3
    assert child_resource["endpoint"]["params"]["page_size"] == 7
    assert "limit" not in parent_resource["endpoint"]["params"]
    assert "limit" not in child_resource["endpoint"]["params"]


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_forwards_endpoint_extras(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": "items", "paginator": _DummyPaginator()},
            child_endpoint_extra={"data_selector": "items", "paginator": _DummyPaginator()},
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_endpoint = config["resources"][0]["endpoint"]
    child_endpoint = config["resources"][1]["endpoint"]
    assert parent_endpoint["data_selector"] == "items"
    assert child_endpoint["data_selector"] == "items"
    assert isinstance(parent_endpoint["paginator"], _DummyPaginator)
    assert isinstance(child_endpoint["paginator"], _DummyPaginator)


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_backwards_compatible_defaults(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_resource = config["resources"][0]
    child_resource = config["resources"][1]
    assert parent_resource["endpoint"]["params"]["limit"] == 3
    assert child_resource["endpoint"]["params"]["limit"] == 7
    assert "data_selector" not in parent_resource["endpoint"]
    assert "data_selector" not in child_resource["endpoint"]


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_threads_resume_state(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    resume_hook = Mock()
    initial_state = {"completed": ["/parents/a/children"], "current": None, "child_state": None}
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            resume_hook=resume_hook,
            initial_paginator_state=initial_state,
        )
    except StopIteration:
        pass

    kwargs = mock_rest_api_resources.call_args.kwargs
    assert kwargs["resume_hook"] is resume_hook
    assert kwargs["initial_paginator_state"] == initial_state


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_rejects_params_in_endpoint_extras(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []

    with pytest.raises(ValueError, match="Do not pass 'params' in child_endpoint_extra"):
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            child_endpoint_extra={"params": {"limit": 1}},
        )


def test_paginate_dependent_resource_does_not_leak_params_across_parents() -> None:
    captured_initial_params: list[dict[str, Any]] = []

    def fake_paginate(**kwargs):
        params = kwargs["params"]
        # Snapshot the params as they arrive for the first page of each parent
        captured_initial_params.append(dict(params))
        # Page 1: return data with original params
        yield [{"id": "child_1", "token": "tok_page1"}]
        # Between pages the real paginator mutates params (removes since/until, adds before)
        params.pop("since", None)
        params.pop("until", None)
        params["before"] = "tok_page1"
        # Page 2: return data with mutated params
        yield [{"id": "child_2", "token": "tok_page2"}]

    mock_client = Mock()
    mock_client.paginate = fake_paginate

    resolved_param = ResolvedParam(
        param_name="parent_id",
        resolve_config={"type": "resolve", "resource": "parents", "field": "id"},
    )

    paginate_fn = _make_paginate_dependent_resource(
        client=mock_client,
        resolved_param=resolved_param,
        include_from_parent=[],
        default_columns_config=None,
        incremental_object=None,
        incremental_param=None,
        incremental_cursor_transform=None,
        db_incremental_field_last_value=None,
    )

    results: list[list[dict[str, Any]]] = []
    for page in paginate_fn(
        items=[{"id": "parent_a"}, {"id": "parent_b"}],
        method="get",
        path="/parents/{parent_id}/children",
        params={"page_size": 100, "since": "2026-01-01", "until": "2026-03-01"},
        paginator=None,
        data_selector="items",
        hooks=None,
    ):
        if isinstance(page, list):
            results.append(page)

    assert len(captured_initial_params) == 2
    # Parent B's first request must have the original since/until,
    # not the before token left over from parent A's page 2
    for params_snapshot in captured_initial_params:
        assert params_snapshot["since"] == "2026-01-01"
        assert params_snapshot["until"] == "2026-03-01"
        assert "before" not in params_snapshot


class _FakeResumableClient:
    # paginate() simulates page-by-page pagination with resume: it honors
    # initial_paginator_state["page"] as the start index and calls resume_hook after each page.
    def __init__(self, pages_by_path: dict[str, list[list[dict[str, Any]]]]) -> None:
        self.pages_by_path = pages_by_path

    def paginate(
        self,
        *,
        method,
        path,
        params,
        paginator,
        data_selector,
        hooks,
        resume_hook=None,
        initial_paginator_state=None,
        data_selector_required=False,
    ):
        pages = self.pages_by_path[path]
        start = initial_paginator_state["page"] if initial_paginator_state else 0
        for i in range(start, len(pages)):
            yield pages[i]
            if resume_hook is not None:
                resume_hook({"page": i + 1} if i < len(pages) - 1 else None)


_RESOLVED_PARAM = ResolvedParam(
    param_name="parent_id",
    resolve_config={"type": "resolve", "resource": "parents", "field": "id"},
)


def _dependent_fn(client, resume_hook=None, initial_state=None):
    return _make_paginate_dependent_resource(
        client=client,
        resolved_param=_RESOLVED_PARAM,
        include_from_parent=[],
        default_columns_config=None,
        incremental_object=None,
        incremental_param=None,
        incremental_cursor_transform=None,
        db_incremental_field_last_value=None,
        resume_hook=resume_hook,
        initial_state=initial_state,
    )


def _drive(paginate_fn) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in paginate_fn(
        items=[{"id": "a"}, {"id": "b"}],
        method="get",
        path="/parents/{parent_id}/children",
        params={},
        paginator=None,
        data_selector=None,
        hooks=None,
    ):
        rows.extend(page)
    return rows


def test_dependent_resume_checkpoints_completed_parents() -> None:
    client = _FakeResumableClient(
        {
            "/parents/a/children": [[{"id": "a1"}], [{"id": "a2"}]],
            "/parents/b/children": [[{"id": "b1"}]],
        }
    )
    checkpoints: list[Any] = []
    rows = _drive(_dependent_fn(client, resume_hook=checkpoints.append))

    assert [r["id"] for r in rows] == ["a1", "a2", "b1"]
    # Final checkpoint records both parents fully synced, nothing in progress.
    assert checkpoints[-1] == {
        "completed": ["/parents/a/children", "/parents/b/children"],
        "current": None,
        "child_state": None,
    }


def test_dependent_resume_skips_completed_and_resumes_current() -> None:
    client = _FakeResumableClient(
        {
            "/parents/a/children": [[{"id": "a1"}], [{"id": "a2"}]],
            "/parents/b/children": [[{"id": "b1"}], [{"id": "b2"}]],
        }
    )
    # Parent a already fully synced; parent b was mid-way (its child cursor is at page index 1).
    initial_state = {
        "completed": ["/parents/a/children"],
        "current": "/parents/b/children",
        "child_state": {"page": 1},
    }
    rows = _drive(_dependent_fn(client, resume_hook=lambda _s: None, initial_state=initial_state))

    # a is skipped entirely (no re-yield); b resumes from page 1, so only b2 (b1 already synced).
    assert [r["id"] for r in rows] == ["b2"]


def test_dependent_resume_disabled_without_hook_processes_all() -> None:
    client = _FakeResumableClient(
        {
            "/parents/a/children": [[{"id": "a1"}]],
            "/parents/b/children": [[{"id": "b1"}]],
        }
    )
    rows = _drive(_dependent_fn(client, resume_hook=None))
    assert [r["id"] for r in rows] == ["a1", "b1"]


_WAREHOUSE_FANOUT = DependentEndpointConfig(
    parent_name="parents",
    resolve_param="parent_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "parent_id"},
    parent_source="warehouse",
)


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_uri",
    return_value="s3://bucket/team_1_x_y/parents",
)
@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
)
def test_warehouse_parent_builds_data_iterator_and_404_ignore(
    mock_reader, mock_resolve, mock_rest_api_resources
) -> None:
    mock_rest_api_resources.return_value = []
    mock_reader.return_value = iter([[{"id": "p1"}]])
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=_WAREHOUSE_FANOUT,
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            source_id="source-1",
            use_warehouse_parent=True,
        )
    except StopIteration:
        pass

    # The URI is resolved eagerly at build time (sync context), not lazily on iteration.
    mock_resolve.assert_called_once_with(1, "source-1", "parents")

    config = mock_rest_api_resources.call_args.args[0]
    parent_resource = config["resources"][0]
    child_resource = config["resources"][1]

    pages = list(parent_resource["data_iterator"]())
    assert pages == [[{"id": "p1"}]]
    mock_reader.assert_called_once_with(
        table_uri="s3://bucket/team_1_x_y/parents", parent_name="parents", columns=["id"], page_size=3
    )
    assert child_resource["endpoint"]["response_actions"] == [{"status_code": 404, "action": "ignore"}]


@patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_warehouse_parent_config_stays_on_api_path_when_not_enabled(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=_WAREHOUSE_FANOUT,
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            source_id="source-1",
            use_warehouse_parent=False,
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_resource = config["resources"][0]
    child_resource = config["resources"][1]
    assert "data_iterator" not in parent_resource
    assert parent_resource["endpoint"]["params"]["limit"] == 3
    assert "response_actions" not in child_resource["endpoint"]


def test_warehouse_parent_requires_source_id() -> None:
    with pytest.raises(ValueError, match="source_id is required"):
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=_WAREHOUSE_FANOUT,
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            use_warehouse_parent=True,
        )


class _FakeChildOnlyClient:
    """Fails the test if any request goes to the parent listing path."""

    def __init__(self) -> None:
        self.requested_paths: list[str] = []

    def paginate(self, *, method, path, params, paginator, data_selector, hooks, **kwargs):
        self.requested_paths.append(path)
        assert path != "/parents", "warehouse-parent fan-out must not fetch the parent endpoint"
        parent_id = path.split("/")[2]
        yield [{"id": f"child-of-{parent_id}"}]


@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_uri",
    return_value="s3://bucket/team_1_x_y/parents",
)
@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
)
def test_warehouse_parent_drives_child_without_parent_http(mock_reader, _mock_resolve) -> None:
    mock_reader.return_value = iter([[{"id": "p1"}, {"id": "p2"}], [{"id": "p3"}]])
    fake_client = _FakeChildOnlyClient()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.RESTClient",
        return_value=fake_client,
    ):
        resource = build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=_WAREHOUSE_FANOUT,
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            source_id="source-1",
            use_warehouse_parent=True,
        )
        rows = [row for page in resource for row in page]

    # One child fetch per warehouse parent row, parent id injected and renamed.
    assert rows == [
        {"id": "child-of-p1", "parent_id": "p1"},
        {"id": "child-of-p2", "parent_id": "p2"},
        {"id": "child-of-p3", "parent_id": "p3"},
    ]
    assert fake_client.requested_paths == [
        "/parents/p1/children",
        "/parents/p2/children",
        "/parents/p3/children",
    ]


class _ConfigWithFanout:
    def __init__(self, fanout: DependentEndpointConfig | None) -> None:
        self.fanout = fanout


def test_required_parents_from_endpoint_configs() -> None:
    configs = {
        "children": _ConfigWithFanout(_WAREHOUSE_FANOUT),
        "api_children": _ConfigWithFanout(
            DependentEndpointConfig(
                parent_name="parents", resolve_param="parent_id", resolve_field="id", include_from_parent=[]
            )
        ),
        "parents": _ConfigWithFanout(None),
    }
    assert required_parents_from_endpoint_configs(configs, "children") == ["parents"]
    assert required_parents_from_endpoint_configs(configs, "api_children") == []
    assert required_parents_from_endpoint_configs(configs, "parents") == []
    assert required_parents_from_endpoint_configs(configs, "unknown") == []
