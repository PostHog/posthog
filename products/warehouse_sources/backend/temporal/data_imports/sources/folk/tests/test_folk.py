from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.folk import (
    FolkResumeConfig,
    FolkUntrustedURLError,
    _validate_pagination_url,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.settings import FOLK_BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.source import FolkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.folk import FolkSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(FolkSource(), FolkSourceConfig(api_key="folk_test"))


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    pagination = {"nextLink": next_url} if next_url else {}
    return ScriptedResponse(json={"data": {"items": items, "pagination": pagination}})


class TestValidatePaginationUrl:
    def test_api_origin_url_is_returned_unchanged(self) -> None:
        url = "https://api.folk.app/v1/people?limit=100&cursor=eyJvZmZzZXQiOjEwMH0%3D"
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/v1/people?cursor=x"),
            ("http_downgrade", "http://api.folk.app/v1/people?cursor=x"),
            ("userinfo_confusion", "https://api.folk.app@evil.example.com/v1/people"),
            ("wrong_path", "https://api.folk.app/steal-token"),
        ]
    )
    def test_off_origin_urls_are_refused(self, _name: str, url: str) -> None:
        # A poisoned resume state or hostile response must not retarget the bearer-token request.
        with pytest.raises(FolkUntrustedURLError):
            _validate_pagination_url(url)


class TestPagination:
    def test_follows_next_link_and_reads_the_items_envelope(self) -> None:
        second = "https://api.folk.app/v1/people?limit=100&cursor=abc"
        result = _driver().run(
            "people",
            [
                _page([{"id": "per_1", "fullName": "Alice"}], next_url=second),
                _page([{"id": "per_2", "fullName": "Bob"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "per_1", "fullName": "Alice"}, {"id": "per_2", "fullName": "Bob"}]
        assert result.urls == [f"{FOLK_BASE_URL}/v1/people?limit=100", second]
        assert result.params("limit") == ["100", "100"]
        assert result.params("cursor") == [None, "abc"]
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert result.queries[1] == {"limit": ("100",), "cursor": ("abc",)}
        assert result.saved_states == [FolkResumeConfig(next_url=second)]

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = "https://api.folk.app/v1/people?limit=100&cursor=page3"
        result = _driver().run("people", [_page([{"id": "per_9"}])], resume_state=FolkResumeConfig(next_url=resume_url))

        # Starts at the resumed URL, not the freshly-built first page.
        assert result.raised is None
        assert result.rows == [{"id": "per_9"}]
        assert result.urls == [resume_url]
        assert result.queries == [{"limit": ("100",), "cursor": ("page3",)}]

    def test_off_origin_next_link_is_refused(self) -> None:
        result = _driver().run(
            "people", [_page([{"id": "per_1"}], next_url="https://evil.example.com/v1/people?cursor=x")]
        )

        assert isinstance(result.raised, FolkUntrustedURLError)
        assert result.paths == ["/v1/people"]

    def test_poisoned_resume_url_is_refused(self) -> None:
        result = _driver().run(
            "people", [], resume_state=FolkResumeConfig(next_url="https://evil.example.com/v1/people")
        )

        assert isinstance(result.raised, FolkUntrustedURLError)
        # Refused before any request carries the bearer token off-origin.
        assert result.requests == []


_GROUPS = _page([{"id": "grp_1", "name": "Sales"}, {"id": "grp_2", "name": "Hiring"}])


class TestGroupFanout:
    def test_group_members_walk_every_group_and_carry_the_group_id(self) -> None:
        second = "https://api.folk.app/v1/groups/grp_1/members?limit=100&cursor=m2"
        result = _driver().run(
            "group_members",
            [
                _GROUPS,
                _page([{"id": "usr_1", "role": "owner"}], next_url=second),
                _page([{"id": "usr_2", "role": "reader"}]),
                _page([{"id": "usr_1", "role": "admin"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/groups",
            "/v1/groups/grp_1/members",
            "/v1/groups/grp_1/members",
            "/v1/groups/grp_2/members",
        ]
        assert result.rows == [
            {"id": "usr_1", "role": "owner", "groupId": "grp_1"},
            {"id": "usr_2", "role": "reader", "groupId": "grp_1"},
            {"id": "usr_1", "role": "admin", "groupId": "grp_2"},
        ]
        assert result.saved_states == [
            FolkResumeConfig(remaining_group_ids=["grp_1", "grp_2"]),
            FolkResumeConfig(next_url=second, remaining_group_ids=["grp_1", "grp_2"], remaining_child_keys=[""]),
            FolkResumeConfig(remaining_group_ids=["grp_2"]),
            FolkResumeConfig(remaining_group_ids=["grp_2"]),
            FolkResumeConfig(remaining_group_ids=[]),
        ]

    def test_custom_objects_list_each_object_type_and_skip_one_deleted_since_discovery(self) -> None:
        person_fields = [
            {"name": "Deals", "type": "objectField"},
            {"name": "Job Applications", "type": "objectField"},
            {"name": "Stage", "type": "singleSelect"},
        ]
        result = _driver().run(
            "custom_objects",
            route(
                {
                    "/v1/groups": [_GROUPS],
                    "/custom-fields/person": [_page(person_fields), _page([])],
                    "/grp_1/Deals": [_page([{"id": "obj_1", "createdAt": "2025-01-01T00:00:00Z"}])],
                    "/grp_1/Job%20Applications": [ScriptedResponse(status=404)],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/groups",
            "/v1/groups/grp_1/custom-fields/person",
            "/v1/groups/grp_1/Deals",
            "/v1/groups/grp_1/Job%20Applications",
            "/v1/groups/grp_2/custom-fields/person",
        ]
        assert result.rows == [
            {"id": "obj_1", "createdAt": "2025-01-01T00:00:00Z", "groupId": "grp_1", "objectType": "Deals"}
        ]

    def test_custom_fields_cover_people_companies_and_each_object_type(self) -> None:
        result = _driver().run(
            "group_custom_fields",
            [
                _page([{"id": "grp_1", "name": "Sales"}]),
                _page([{"name": "Deals", "type": "objectField"}]),
                _page([{"name": "Deals", "type": "objectField"}]),
                _page([{"name": "Industry", "type": "textField"}]),
                _page([{"name": "Amount", "type": "numericField"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/groups",
            "/v1/groups/grp_1/custom-fields/person",
            "/v1/groups/grp_1/custom-fields/person",
            "/v1/groups/grp_1/custom-fields/company",
            "/v1/groups/grp_1/custom-fields/Deals",
        ]
        assert [(row["entityType"], row["name"]) for row in result.rows] == [
            ("person", "Deals"),
            ("company", "Industry"),
            ("Deals", "Amount"),
        ]

    @parameterized.expand(
        [
            # The resumed type still exists: continue its walk at the saved page.
            ("continues_saved_page", ["Deals"], "Deals", "o3"),
            # The resumed type was deleted: skip it, and do not re-read types finished before it.
            ("skips_deleted_type", ["Gone", "Projects"], "Projects", None),
        ]
    )
    def test_resumes_inside_a_group_without_relisting_groups(
        self, _name: str, child_keys: list[str], expected_type: str, expected_cursor: str | None
    ) -> None:
        resume_url = f"https://api.folk.app/v1/groups/grp_2/{child_keys[0]}?limit=100&cursor=o3"
        object_types = [{"name": "Deals", "type": "objectField"}, {"name": "Projects", "type": "objectField"}]
        result = _driver().run(
            "custom_objects",
            [_page(object_types), _page([{"id": "obj_9"}])],
            resume_state=FolkResumeConfig(
                next_url=resume_url, remaining_group_ids=["grp_2"], remaining_child_keys=child_keys
            ),
        )

        assert result.raised is None
        assert result.paths == ["/v1/groups/grp_2/custom-fields/person", f"/v1/groups/grp_2/{expected_type}"]
        assert result.params("cursor")[1] == expected_cursor
        assert result.rows == [{"id": "obj_9", "groupId": "grp_2", "objectType": expected_type}]


class TestUnknownEndpoint:
    def test_unknown_endpoint_raises_a_retryable_unknown_resource_error(self) -> None:
        # A web pod can offer a table this worker's catalog doesn't know yet; the named error is
        # classified retryable so the sync recovers once the rollout finishes.
        result = _driver().run("deals", [])

        assert isinstance(result.raised, UnknownResourceError)
        assert result.requests == []


class TestProbeCredentials:
    @parameterized.expand(
        [("top_level", "people", "/v1/people"), ("group_scoped_probes_groups", "group_members", "/v1/groups")]
    )
    def test_schema_probe_path(self, _name: str, endpoint: str, expected_path: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            probe_credentials("folk_test", endpoint)

        assert [request.path for request in network.requests_log] == [expected_path]

    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            status = probe_credentials("folk_test")

        assert status == status_code
        assert [request.path for request in network.requests_log] == ["/v1/users/me"]
        assert network.requests_log[0].headers["authorization"] == "Bearer folk_test"
        assert network.session_options[0]["redact_values"] == ("folk_test",)
