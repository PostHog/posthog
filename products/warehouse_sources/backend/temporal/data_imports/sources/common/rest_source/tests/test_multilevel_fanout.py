from typing import Any
from unittest.mock import patch

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    build_resource_dependency_graph,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient


def _paginate_stub(pages_by_path: dict[str, list[dict[str, Any]]]):
    def paginate(
        self,
        *,
        path="",
        method="get",
        params=None,
        json=None,
        paginator=None,
        data_selector=None,
        hooks=None,
        resume_hook=None,
        initial_paginator_state=None,
        data_selector_required=False,
    ):
        yield pages_by_path[path]

    return paginate


class TestMultiParamResolution:
    def test_two_resolve_params_from_same_parent_bind_into_path(self) -> None:
        config: dict[str, Any] = {
            "client": {"base_url": "https://api.example.com"},
            "resources": [
                {"name": "tables", "endpoint": {"path": "/tables"}},
                {
                    "name": "rows",
                    "endpoint": {
                        "path": "/docs/{doc_id}/tables/{table_id}/rows",
                        "params": {
                            "doc_id": {"type": "resolve", "resource": "tables", "field": "doc_id"},
                            "table_id": {"type": "resolve", "resource": "tables", "field": "id"},
                        },
                    },
                },
            ],
        }
        pages = {
            "/tables": [{"id": "t1", "doc_id": "d1"}],
            "/docs/d1/tables/t1/rows": [{"row": 1}],
        }
        with patch.object(RESTClient, "paginate", _paginate_stub(pages)):
            resources = rest_api_resources(config, team_id=1, job_id="j", db_incremental_field_last_value=None)
            rows_resource = next(r for r in resources if r.name == "rows")
            rows = [row for page in rows_resource for row in page]
        assert rows == [{"row": 1}]

    def test_resolve_params_from_different_parents_rejected(self) -> None:
        with pytest.raises(ValueError, match="same\\s+parent"):
            build_resource_dependency_graph(
                {},
                [
                    {"name": "a", "endpoint": {"path": "/a"}},
                    {"name": "b", "endpoint": {"path": "/b"}},
                    {
                        "name": "c",
                        "endpoint": {
                            "path": "/a/{x}/b/{y}",
                            "params": {
                                "x": {"type": "resolve", "resource": "a", "field": "id"},
                                "y": {"type": "resolve", "resource": "b", "field": "id"},
                            },
                        },
                    },
                ],
            )


class TestChainedFanout:
    def _three_level_config(self) -> dict[str, Any]:
        return {
            "client": {"base_url": "https://api.example.com"},
            "resources": [
                {"name": "orgs", "endpoint": {"path": "/orgs"}},
                {
                    "name": "projects",
                    "include_from_parent": ["id"],
                    "endpoint": {
                        "path": "/orgs/{org_id}/projects",
                        "params": {"org_id": {"type": "resolve", "resource": "orgs", "field": "id"}},
                    },
                },
                {
                    "name": "errors",
                    "endpoint": {
                        "path": "/projects/{project_id}/errors",
                        "params": {"project_id": {"type": "resolve", "resource": "projects", "field": "id"}},
                    },
                },
            ],
        }

    def test_two_level_chain_yields_grandchild_rows(self) -> None:
        pages = {
            "/orgs": [{"id": "o1"}],
            "/orgs/o1/projects": [{"id": "p1"}, {"id": "p2"}],
            "/projects/p1/errors": [{"e": "p1-a"}],
            "/projects/p2/errors": [{"e": "p2-a"}],
        }
        with patch.object(RESTClient, "paginate", _paginate_stub(pages)):
            resources = rest_api_resources(
                self._three_level_config(), team_id=1, job_id="j", db_incremental_field_last_value=None
            )
            errors = next(r for r in resources if r.name == "errors")
            rows = [row for page in errors for row in page]
        assert rows == [{"e": "p1-a"}, {"e": "p2-a"}]

    def test_chained_fanout_disables_resume_instead_of_corrupting_state(self) -> None:
        # With 2+ dependent resources one shared resume hook would be consumed at several
        # levels; the framework must not call it at all.
        pages = {
            "/orgs": [{"id": "o1"}],
            "/orgs/o1/projects": [{"id": "p1"}],
            "/projects/p1/errors": [{"e": 1}],
        }
        checkpoints: list[Any] = []
        with patch.object(RESTClient, "paginate", _paginate_stub(pages)):
            resources = rest_api_resources(
                self._three_level_config(),
                team_id=1,
                job_id="j",
                db_incremental_field_last_value=None,
                resume_hook=checkpoints.append,
            )
            errors = next(r for r in resources if r.name == "errors")
            list(errors)
        assert checkpoints == []
