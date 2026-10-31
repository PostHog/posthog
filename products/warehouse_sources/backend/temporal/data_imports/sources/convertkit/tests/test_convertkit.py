from datetime import UTC, date, datetime

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit import (
    ConvertKitResumeConfig,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source import ConvertKitSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.convertkit import (
    ConvertKitSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ConvertKitSource(), ConvertKitSourceConfig(api_key="key"))


def _page(key: str, ids: list[int], *, has_next: bool = False, end_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            key: [{"id": i} for i in ids],
            "pagination": {"has_next_page": has_next, "end_cursor": end_cursor},
        }
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestRequestParams:
    @parameterized.expand(
        [
            ("created_at", "created_after", "updated_after"),
            ("updated_at", "updated_after", "created_after"),
        ]
    )
    def test_incremental_field_maps_to_filter_param(
        self, incremental_field: str, expected_param: str, other_param: str
    ) -> None:
        result = _driver().run(
            "subscribers",
            [_page("subscribers", [1])],
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param(expected_param) == "2026-01-02T03:04:05Z"
        # Only the chosen field's param is set.
        assert result.requests[0].param(other_param) is None


class TestPagination:
    def test_paginates_until_no_next_page(self) -> None:
        result = _driver().run(
            "subscribers",
            [
                _page("subscribers", [1, 2], has_next=True, end_cursor="C2"),
                _page("subscribers", [3]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert len(result.requests) == 2
        # The second request carries the cursor from the first page.
        assert result.params("after") == [None, "C2"]
        # State saved once, pointing at the first page's end_cursor; the last page ends without a save.
        assert result.saved_states == [ConvertKitResumeConfig(after="C2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "subscribers",
            [_page("subscribers", [9])],
            resume_state=ConvertKitResumeConfig(after="C5"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [9]
        assert result.params("after") == ["C5"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_at_source_create", 403, None, True),
            ("forbidden_for_specific_endpoint", 403, "subscribers", False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, endpoint: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, _error = validate_credentials("key", endpoint)

        assert is_valid is expected_valid
        assert network.requests_log[0].path == "/v4/subscribers"

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))) as network:
            is_valid, error = validate_credentials("key")

        assert is_valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v4/subscribers"}

    def test_unknown_endpoint_returns_error_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("key", "not_a_real_endpoint")

        assert is_valid is False
        assert error is not None
        assert network.requests_log == []


class TestConvertKitSource:
    @parameterized.expand(
        [
            ("subscribers", ["id"], "created_at"),
            ("purchases", ["id"], "transaction_time"),
            ("custom_fields", ["id"], None),
            ("email_templates", ["id"], None),
        ]
    )
    def test_source_response_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [_page(endpoint, [])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


JUNCTIONS = [
    ("form_subscribers", "forms", "/v4/forms/{}/subscribers", "form_id", "added_after"),
    ("tag_subscribers", "tags", "/v4/tags/{}/subscribers", "tag_id", "tagged_after"),
    ("sequence_subscribers", "sequences", "/v4/sequences/{}/subscribers", "sequence_id", "added_after"),
]
INCREMENTAL_JUNCTIONS = [JUNCTIONS[0], JUNCTIONS[2]]


class TestSubscriberJunctions:
    @parameterized.expand(JUNCTIONS)
    def test_fans_out_over_parents_and_injects_the_parent_id(
        self, endpoint: str, parent_key: str, child_path: str, parent_column: str, _filter: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page(parent_key, [11, 12]),
                _page("subscribers", [1]),
                _page("subscribers", [2]),
            ],
        )

        assert result.raised is None
        # Every row carries the parent it came from, which is what makes the key unique table-wide.
        assert [(row[parent_column], row["id"]) for row in result.rows] == [(11, 1), (12, 2)]
        assert result.paths[1:] == [child_path.format(11), child_path.format(12)]
        # Every subscriber state, not just the active ones Kit returns by default.
        assert result.requests[1].param("status") == "all"

    @parameterized.expand(INCREMENTAL_JUNCTIONS)
    def test_incremental_watermark_narrows_each_child_request(
        self, endpoint: str, parent_key: str, _child_path: str, _parent_column: str, filter_param: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page(parent_key, [11]),
                _page("subscribers", [1]),
            ],
            incremental_field=filter_param.replace("_after", "_at"),
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param(filter_param) == "2026-01-02T03:04:05Z"
        # The parent listing is walked in full, so only the child is windowed.
        assert result.requests[0].param(filter_param) is None

    def test_resume_skips_synced_parents_and_continues_the_one_in_flight(self) -> None:
        result = _driver().run(
            "form_subscribers",
            [
                _page("forms", [11, 12]),
                _page("subscribers", [2]),
            ],
            resume_state=ConvertKitResumeConfig(
                completed=["/v4/forms/11/subscribers"],
                current="/v4/forms/12/subscribers",
                child_state={"after": "C9"},
            ),
        )

        assert result.raised is None
        assert [row["form_id"] for row in result.rows] == [12]
        assert [request.origin + request.path for request in result.requests] == [
            "https://api.kit.com/v4/forms",
            "https://api.kit.com/v4/forms/12/subscribers",
        ]
        assert result.params("after")[1] == "C9"


class TestValidateFanoutCredentials:
    def test_probes_the_parent_listing(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            is_valid, _error = validate_credentials("key", "form_subscribers")

        assert is_valid is True
        # The child path carries an unresolved id placeholder, so probing it would 404 and
        # report a working key as broken.
        assert network.requests_log[0].url == "https://api.kit.com/v4/forms?per_page=1"


def _clicks_page(broadcast_id: int, link_ids: list[int]) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "broadcast": {
                "id": broadcast_id,
                "clicks": [{"id": i, "url": f"https://example.com/{i}", "unique_clicks": i} for i in link_ids],
            },
            "pagination": {"has_next_page": False, "end_cursor": None},
        }
    )


class TestBroadcastClicks:
    def test_reads_the_nested_click_list_and_injects_the_broadcast_id(self) -> None:
        result = _driver().run(
            "broadcast_clicks",
            [
                _page("broadcasts", [11, 12]),
                _clicks_page(11, [51, 52]),
                _clicks_page(12, [53]),
            ],
        )

        assert result.raised is None
        assert [(row["broadcast_id"], row["id"]) for row in result.rows] == [(11, 51), (11, 52), (12, 53)]
        assert result.rows[0]["url"] == "https://example.com/51"
        assert result.paths[1] == "/v4/broadcasts/11/clicks"
