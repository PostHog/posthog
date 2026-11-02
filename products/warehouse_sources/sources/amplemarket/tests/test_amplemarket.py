from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.amplemarket import (
    AmplemarketResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.settings import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.source import AmplemarketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplemarket import (
    AmplemarketSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AmplemarketSource(), AmplemarketSourceConfig(api_key="api-key"))


def _page(data_key: str, items: list[dict[str, Any]], next_href: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if next_href is not None:
        body["_links"] = {"next": {"href": next_href}}
    return ScriptedResponse(json=body)


class TestValidateCredentials:
    def test_probes_account_info_with_bearer_token(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("api-key") is True

        request = network.requests_log[0]
        assert request.url == f"{BASE_URL}/account-info"
        assert request.headers["authorization"] == "Bearer api-key"


class TestPagination:
    def test_follows_relative_next_link(self) -> None:
        # Amplemarket returns HAL-style relative next hrefs with bracketed cursor params; the
        # paginator must resolve them against the base URL and drop the original params.
        next_href = "/sequences?page[after]=b&page[size]=20"
        result = _driver().run(
            "sequences",
            [
                _page("sequences", [{"id": "a"}, {"id": "b"}], next_href),
                _page("sequences", [{"id": "c"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert {request.origin for request in result.requests} == {BASE_URL}
        assert result.paths == ["/sequences", "/sequences"]
        assert result.queries == [{}, {"page[after]": ("b",), "page[size]": ("20",)}]
        # State is saved only while a next page exists, with the resolved absolute URL.
        assert result.saved_states == [AmplemarketResumeConfig(next_url=f"{BASE_URL}{next_href}")]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = f"{BASE_URL}/sequences?page[after]=x&page[size]=20"
        result = _driver().run(
            "sequences",
            [_page("sequences", [{"id": "y"}])],
            resume_state=AmplemarketResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["y"]
        assert {request.origin for request in result.requests} == {BASE_URL}
        assert result.paths == ["/sequences"]
        assert result.queries == [{"page[after]": ("x",), "page[size]": ("20",)}]


class TestFanout:
    def test_tasks_are_fetched_per_user(self) -> None:
        # /tasks requires a user_id filter, so the fan-out binds each parent user's id into the
        # child path and pages each user's tasks through their own next-link chain.
        result = _driver().run(
            "tasks",
            [
                _page("users", [{"id": "u1"}, {"id": "u2"}]),
                _page("tasks", [{"id": "t1", "user_id": "u1"}], "/tasks?user_id=u1&page[after]=t1"),
                _page("tasks", [{"id": "t2", "user_id": "u1"}]),
                _page("tasks", [{"id": "t3", "user_id": "u2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["t1", "t2", "t3"]
        assert {request.origin for request in result.requests} == {BASE_URL}
        assert result.paths == ["/users", "/tasks", "/tasks", "/tasks"]
        assert result.queries == [
            {},
            {"user_id": ("u1",)},
            {"user_id": ("u1",), "page[after]": ("t1",)},
            {"user_id": ("u2",)},
        ]

    @pytest.mark.parametrize(
        "endpoint, parent_key, child_key, parent_id_column, gone_status, child_paths",
        [
            ("contacts", "accounts", "contacts", "account_id", 404, ["/contacts", "/contacts", "/contacts"]),
            (
                "lead_list_entries",
                "lead_lists",
                "leads",
                "lead_list_id",
                410,
                ["/lead-lists/p1", "/lead-lists/p1", "/lead-lists/p2"],
            ),
        ],
    )
    def test_children_carry_parent_id_and_skip_deleted_parents(
        self,
        endpoint: str,
        parent_key: str,
        child_key: str,
        parent_id_column: str,
        gone_status: int,
        child_paths: list[str],
    ) -> None:
        # The parent id is part of the primary key, so every child row must carry it, and a parent
        # deleted after the listing must not fail the sync.
        result = _driver().run(
            endpoint,
            [
                _page(parent_key, [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]),
                _page(child_key, [{"id": "c1"}], f"{child_paths[0]}?page[after]=c1"),
                _page(child_key, [{"id": "c2"}]),
                _page(child_key, [{"id": "c1"}]),
                ScriptedResponse(status=gone_status, json={"_errors": [], "object": "error"}),
            ],
        )

        assert result.raised is None
        assert [(row[parent_id_column], row["id"]) for row in result.rows] == [("p1", "c1"), ("p1", "c2"), ("p2", "c1")]
        assert result.paths[1:4] == child_paths
