from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kustomer import (
    KustomerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer import (
    KustomerResumeConfig,
    _clean_org_name,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source import KustomerSource


def _driver() -> SourceDriver:
    return SourceDriver(KustomerSource(), KustomerSourceConfig(org_name="myorg", api_key="key"))


def _page(items: list[dict[str, Any]], next_link: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items, "links": {}}
    if next_link:
        body["links"]["next"] = next_link
    return ScriptedResponse(json=body)


class TestCleanOrgName:
    @pytest.mark.parametrize("value", ["", "my org", "org?x=1", "../evil"])
    def test_invalid_org_names_raise(self, value: str) -> None:
        with pytest.raises(ValueError):
            _clean_org_name(value)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            # Role-scoped keys without the customers grant still 403; only 401
            # means the key itself is bad.
            (403, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("myorg", "key") is expected

        assert [request.path for request in network.requests_log] == ["/v1/customers"]
        assert network.requests_log[0].param("page[size]") == "1"

    def test_validate_credentials_rejects_bad_org_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("my org!", "key") is False

        assert network.requests_log == []


class TestRequestParams:
    @pytest.mark.parametrize(
        "endpoint, expected_params",
        [
            # The sub-statuses list rejects requests without the `resource` filter.
            ("sub_statuses", {"resource": "conversation", "sort": None}),
            # Page-number lists sort ascending so new rows do not shift later pages.
            ("messages", {"sort": "asc"}),
            ("notes", {"sort": "asc"}),
            ("work_items", {"sort": "asc"}),
            # Without `user=false` only the API key owner's sessions come back.
            ("work_sessions", {"sort": "asc", "user": "false", "active": "false"}),
            ("queues", {"sort": None, "user": None}),
            # Page-number lists take `pageSize`, not the JSON:API `page[size]`.
            ("routing_statuses", {"pageSize": "100"}),
            ("klasses", {"pageSize": "100", "status": None}),
        ],
    )
    def test_endpoint_request_params(self, endpoint: str, expected_params: dict[str, str | None]) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        for name, value in expected_params.items():
            assert result.params(name) == [value]


class TestPagination:
    def test_paginates_via_links_next_and_absolutizes(self) -> None:
        result = _driver().run(
            "customers",
            [
                _page([{"id": "1"}], next_link="/v1/customers?page%5Bafter%5D=abc&page%5Bsize%5D=100"),
                _page([{"id": "2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert len(result.saved_states) == 1
        saved_url = result.saved_states[0].next_url
        assert saved_url.startswith("https://myorg.api.kustomerapp.com/v1/customers?")
        # The second request targets the absolutized next link.
        assert result.urls[1] == saved_url

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://myorg.api.kustomerapp.com/v1/customers?page%5Bafter%5D=resume"
        result = _driver().run(
            "customers", [_page([{"id": "9"}])], resume_state=KustomerResumeConfig(next_url=resume_url)
        )

        assert result.raised is None
        assert result.urls == [resume_url]

    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.com/steal",
            "//attacker.com/steal",
            "http://myorg.api.kustomerapp.com/v1/customers",  # downgraded scheme
            "https://myorg.api.kustomerapp.com.evil.com/v1/customers",  # look-alike host
        ],
    )
    def test_off_host_next_link_is_rejected(self, next_link: str) -> None:
        result = _driver().run("customers", [_page([{"id": "1"}], next_link=next_link)])

        assert isinstance(result.raised, ValueError)
        assert result.saved_states == []
        assert result.paths == ["/v1/customers"]

    def test_off_host_resume_state_is_rejected(self) -> None:
        result = _driver().run(
            "customers",
            [_page([{"id": "1"}])],
            resume_state=KustomerResumeConfig(next_url="https://attacker.com/steal"),
        )

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


def _klass(klass_id: str, name: str) -> dict[str, Any]:
    return {"type": "klass", "id": klass_id, "attributes": {"name": name}}


class TestKObjectsFanout:
    def test_walks_every_klass_and_tags_rows_with_klass_id(self) -> None:
        result = _driver().run(
            "kobjects",
            [
                _page([_klass("k1", "order"), _klass("k2", "subscription")]),
                _page([{"id": "o1"}], next_link="/v1/klasses/order?page=2&pageSize=100&sort=asc"),
                _page([{"id": "o2"}]),
                _page([{"id": "s1"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/klasses", "/v1/klasses/order", "/v1/klasses/order", "/v1/klasses/subscription"]
        assert result.queries[1]["sort"] == ("asc",)
        assert result.queries[1]["pageSize"] == ("100",)
        assert result.queries[2]["page"] == ("2",)
        assert [(row["klass_id"], row["id"]) for row in result.rows] == [("k1", "o1"), ("k1", "o2"), ("k2", "s1")]
        assert all("_klasses_id" not in row for row in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == ["klass_id", "id"]
        assert result.saved_states[-1] == KustomerResumeConfig(
            fanout_state={
                "completed": ["/v1/klasses/order", "/v1/klasses/subscription"],
                "current": None,
                "child_state": None,
            }
        )

    @parameterized.expand(
        [
            ("completed_klass_skipped", ["/v1/klasses/order"], None, None, ["/v1/klasses", "/v1/klasses/subscription"]),
            (
                "in_progress_klass_continues_from_next_url",
                [],
                "/v1/klasses/order",
                {"next_url": "https://myorg.api.kustomerapp.com/v1/klasses/order?page=3&pageSize=100&sort=asc"},
                ["/v1/klasses", "/v1/klasses/order", "/v1/klasses/subscription"],
            ),
        ]
    )
    def test_resumes_from_fanout_state(
        self,
        _name: str,
        completed: list[str],
        current: str | None,
        child_state: dict[str, Any] | None,
        expected_paths: list[str],
    ) -> None:
        resume = KustomerResumeConfig(
            fanout_state={"completed": completed, "current": current, "child_state": child_state}
        )
        result = _driver().run(
            "kobjects",
            [
                _page([_klass("k1", "order"), _klass("k2", "subscription")]),
                _page([{"id": "x1"}]),
                _page([{"id": "x2"}]),
            ],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.paths == expected_paths
        if child_state is not None:
            assert result.urls[1] == child_state["next_url"]
