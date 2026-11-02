from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lattice import (
    LatticeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice import (
    LatticeResumeConfig,
    _base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.source import LatticeSource


def _response(
    items: list[dict[str, Any]],
    *,
    has_more: bool = False,
    ending_cursor: str | None = None,
    page_info: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = (
        {"data": items, "pageInfo": {"endCursor": ending_cursor, "hasNextPage": has_more}}
        if page_info
        else {"data": items, "hasMore": has_more, "endingCursor": ending_cursor}
    )
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(LatticeSource(), LatticeSourceConfig(region="us", api_key="key"))


class TestBaseUrl:
    def test_invalid_region_raises(self) -> None:
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            # Keys inherit the creating user's privileges; 403 means a scope
            # gap, not a bad key.
            (403, True, None),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("us", "key") == (expected_valid, expected_message)

        assert [request.path for request in network.requests_log] == ["/v1/users"]
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    def test_validate_credentials_rejects_bad_region_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("evil", "key")

        assert is_valid is False
        assert error is not None
        assert network.requests_log == []


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, page_info",
        [
            ("users", False),
            # /v1/goals/updates nests the cursor under pageInfo instead of the top level.
            ("goal_updates", True),
        ],
    )
    def test_paginates_via_ending_cursor(self, endpoint: str, page_info: bool) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "1"}], has_more=True, ending_cursor="cur_abc", page_info=page_info),
                _response([{"id": "2"}], page_info=page_info),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        # Checkpoint saved after the first page (points at the next cursor); the second page ends it.
        assert result.saved_states == [LatticeResumeConfig(starting_after="cur_abc")]
        assert result.params("startingAfter") == [None, "cur_abc"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "users",
            [_response([])],
            resume_state=LatticeResumeConfig(starting_after="cur_resume"),
        )

        assert result.raised is None
        assert result.params("startingAfter") == ["cur_resume"]


class TestReviewCycleFanout:
    @pytest.mark.parametrize(
        "endpoint, resume_state, expected_child_urls",
        [
            (
                "reviews",
                None,
                [
                    "https://api.latticehq.com/v1/reviewCycle/c1/reviews",
                    "https://api.latticehq.com/v1/reviewCycle/c2/reviews",
                ],
            ),
            (
                "reviewees",
                None,
                [
                    "https://api.latticehq.com/v1/reviewCycle/c1/reviewees",
                    "https://api.latticehq.com/v1/reviewCycle/c2/reviewees",
                ],
            ),
            (
                "reviews",
                LatticeResumeConfig(
                    fanout_state={"completed": ["/v1/reviewCycle/c1/reviews"], "current": None, "child_state": None}
                ),
                ["https://api.latticehq.com/v1/reviewCycle/c2/reviews"],
            ),
        ],
    )
    def test_fans_out_over_review_cycles(
        self, endpoint: str, resume_state: LatticeResumeConfig | None, expected_child_urls: list[str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "c1"}, {"id": "c2"}]),
                *[_response([{"id": "r1"}]) for _ in expected_child_urls],
            ],
            resume_state=resume_state,
        )

        assert result.raised is None
        urls_without_query = [url.split("?")[0] for url in result.urls]
        assert urls_without_query[0] == "https://api.latticehq.com/v1/reviewCycles"
        assert urls_without_query[1:] == expected_child_urls
        # Review ids repeat across cycles, so each row must carry its cycle for the composite key.
        expected_cycles = [url.split("/")[-2] for url in expected_child_urls]
        assert [(row["review_cycle_id"], row["id"]) for row in result.rows] == [
            (cycle, "r1") for cycle in expected_cycles
        ]


class TestUserFanout:
    @pytest.mark.parametrize(
        "endpoint, child_row, expected_row_fields",
        [
            ("user_tasks", {"id": "t1"}, {"id": "t1"}),
            (
                "user_custom_attributes",
                {"customAttribute": {"id": "ca1", "name": "Office"}, "customAttributeValue": {"id": "cv1"}},
                {"custom_attribute_id": "ca1", "custom_attribute_value_id": "cv1"},
            ),
            # A row missing its nested objects must still sync rather than fail the run.
            (
                "user_custom_attributes",
                {"customAttribute": None},
                {"custom_attribute_id": None, "custom_attribute_value_id": None},
            ),
        ],
    )
    def test_fans_out_over_users(
        self, endpoint: str, child_row: dict[str, Any], expected_row_fields: dict[str, Any]
    ) -> None:
        child_path = {"user_tasks": "tasks", "user_custom_attributes": "customAttributes"}[endpoint]
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "u1"}, {"id": "u2"}]),
                _response([child_row]),
                _response([child_row]),
            ],
        )

        assert result.raised is None
        assert [url.split("?")[0] for url in result.urls] == [
            "https://api.latticehq.com/v1/users",
            f"https://api.latticehq.com/v1/user/u1/{child_path}",
            f"https://api.latticehq.com/v1/user/u2/{child_path}",
        ]
        # Each row carries its user so the composite primary key stays unique across users.
        assert [row["user_id"] for row in result.rows] == ["u1", "u2"]
        for row in result.rows:
            assert {key: row[key] for key in expected_row_fields} == expected_row_fields
