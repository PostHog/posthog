from typing import Any

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


class TestTasksFanout:
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
