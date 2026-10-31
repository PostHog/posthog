from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mightynetworks import (
    MightyNetworksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.mighty_networks import (
    MightyNetworksResumeConfig,
    check_endpoint_access,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.settings import PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.source import MightyNetworksSource


def _driver() -> SourceDriver:
    return SourceDriver(MightyNetworksSource(), MightyNetworksSourceConfig(network_id="1234", api_key="key"))


def _response(
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_data_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_data_key:
        body["data"] = items or []
    if total_pages is not None:
        body["meta"] = {"current_page": current_page or 1, "total_pages": total_pages}
    return ScriptedResponse(json=body)


class TestMightyNetworksSourceNonFanout:
    def test_paginates_until_total_pages(self) -> None:
        result = _driver().run(
            "Members",
            [
                _response([{"id": 1}, {"id": 2}], current_page=1, total_pages=2),
                _response([{"id": 3}], current_page=2, total_pages=2),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        # total_pages=2 terminates after the last page — no extra empty-page request.
        assert len(result.requests) == 2
        assert result.urls[0].split("?")[0] == "https://api.mn.co/admin/v1/networks/1234/members"
        assert result.paths == ["/admin/v1/networks/1234/members"] * 2
        assert result.queries == [
            {"per_page": (str(PER_PAGE),), "page": ("1",)},
            {"per_page": (str(PER_PAGE),), "page": ("2",)},
        ]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "Members",
            [_response([{"id": 2}], current_page=2, total_pages=2)],
            resume_state=MightyNetworksResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [2]
        assert result.params("page") == ["2"]

    def test_missing_data_key_raises(self) -> None:
        # data_selector_required=True: a response shape change fails loud instead of silently
        # syncing zero rows.
        result = _driver().run("Members", [_response(None, drop_data_key=True)])

        assert isinstance(result.raised, ValueError)
        assert "data_selector" in str(result.raised)

    @parameterized.expand(
        [
            ("Members", "/members"),
            ("Spaces", "/spaces"),
            ("Posts", "/posts"),
            ("Events", "/events"),
            ("Plans", "/plans"),
            ("Subscriptions", "/subscriptions"),
            ("Purchases", "/purchases"),
            ("Tags", "/tags"),
            ("Badges", "/badges"),
        ]
    )
    def test_endpoint_paths(self, endpoint: str, path: str) -> None:
        result = _driver().run(endpoint, [_response([], total_pages=1)])

        assert result.raised is None
        assert result.urls[0].split("?")[0] == f"https://api.mn.co/admin/v1/networks/1234{path}"

    def test_subscriptions_row_hoists_nested_id(self) -> None:
        result = _driver().run(
            "Subscriptions",
            [
                _response(
                    [{"member_id": 9, "subscription": {"id": 55, "purchased_at": "2026-01-01T00:00:00Z"}}],
                    total_pages=1,
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {
                "member_id": 9,
                "subscription": {"id": 55, "purchased_at": "2026-01-01T00:00:00Z"},
                "id": 55,
            }
        ]

    def test_purchases_row_hoists_nested_fields(self) -> None:
        result = _driver().run(
            "Purchases",
            [
                _response(
                    [
                        {
                            "member_id": 9,
                            "purchase": {
                                "id": 77,
                                "created_at": "2026-01-01T00:00:00Z",
                                "updated_at": "2026-01-02T00:00:00Z",
                            },
                        }
                    ],
                    total_pages=1,
                )
            ],
        )

        assert result.raised is None
        assert result.rows[0]["id"] == 77
        assert result.rows[0]["created_at"] == "2026-01-01T00:00:00Z"
        assert result.rows[0]["updated_at"] == "2026-01-02T00:00:00Z"


class TestMightyNetworksSourceFanout:
    @parameterized.expand(
        [
            ("SpaceMembers", "spaces", "members", "space_id", True),
            ("PlanMembers", "plans", "members", "plan_id", True),
            ("MemberTags", "members", "tags", "member_id", False),
            ("MemberBadges", "members", "badges", "member_id", False),
            ("EventRsvps", "events", "rsvps", "event_id", False),
        ]
    )
    def test_fans_out_per_parent_and_keys_rows_by_parent(
        self, endpoint: str, parent: str, child: str, parent_key: str, resumable: bool
    ) -> None:
        base = "/admin/v1/networks/1234"
        result = _driver().run(
            endpoint,
            route(
                {
                    f"{base}/{parent}": [_response([{"id": 10}, {"id": 20}], total_pages=1)],
                    f"{base}/{parent}/10/{child}": [
                        _response([{"id": 1}], current_page=1, total_pages=2),
                        _response([{"id": 2}], current_page=2, total_pages=2),
                    ],
                    f"{base}/{parent}/20/{child}": [_response([{"id": 1}], total_pages=1)],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            f"{base}/{parent}",
            f"{base}/{parent}/10/{child}",
            f"{base}/{parent}/10/{child}",
            f"{base}/{parent}/20/{child}",
        ]
        assert [(row[parent_key], row["id"]) for row in result.rows] == [(10, 1), (10, 2), (20, 1)]
        assert all(f"_{parent.capitalize()}_id" not in row for row in result.rows)
        # A checkpoint over network-wide parents would list every member or event it completed.
        assert bool(result.saved_states) is resumable

    def test_skips_parent_deleted_before_its_child_fetch(self) -> None:
        result = _driver().run(
            "SpaceMembers",
            route(
                {
                    "/admin/v1/networks/1234/spaces": [_response([{"id": 10}, {"id": 20}], total_pages=1)],
                    "/admin/v1/networks/1234/spaces/10/members": [ScriptedResponse(status=404)],
                    "/admin/v1/networks/1234/spaces/20/members": [_response([{"id": 1}], total_pages=1)],
                }
            ),
        )

        assert result.raised is None
        assert [(row["space_id"], row["id"]) for row in result.rows] == [(20, 1)]

    def test_resume_skips_parents_already_read(self) -> None:
        result = _driver().run(
            "SpaceMembers",
            route(
                {
                    "/admin/v1/networks/1234/spaces": [_response([{"id": 10}, {"id": 20}], total_pages=1)],
                    "/admin/v1/networks/1234/spaces/20/members": [_response([{"id": 3}], total_pages=1)],
                }
            ),
            resume_state=MightyNetworksResumeConfig(
                fanout_state={"completed": ["/spaces/10/members"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/admin/v1/networks/1234/spaces", "/admin/v1/networks/1234/spaces/20/members"]
        assert [(row["space_id"], row["id"]) for row in result.rows] == [(20, 3)]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key", "1234") == (True, 200)

        assert [request.path for request in network.requests_log] == ["/admin/v1/networks/1234/me"]
        assert network.requests_log[0].headers["authorization"] == "Bearer key"


class TestCheckEndpointAccess:
    def test_forbidden_returns_vendor_message(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=403, json={"message": "Token is missing the members scope"})]
        ) as network:
            assert check_endpoint_access("key", "1234", "Members") == "Token is missing the members scope"

        assert [request.path for request in network.requests_log] == ["/admin/v1/networks/1234/members"]
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    def test_forbidden_without_parseable_body_falls_back_to_generic_message(self) -> None:
        with scripted_network([ScriptedResponse(status=403, body=b"not json")]):
            assert check_endpoint_access("key", "1234", "Members") == (
                "Your Mighty Networks API token doesn't have permission to read this data."
            )

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("not_found", 404)])
    def test_non_403_statuses_are_not_treated_as_permission_errors(self, _name: str, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            assert check_endpoint_access("key", "1234", "Members") is None

    def test_transport_error_is_not_treated_as_permission_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert check_endpoint_access("key", "1234", "Members") is None
