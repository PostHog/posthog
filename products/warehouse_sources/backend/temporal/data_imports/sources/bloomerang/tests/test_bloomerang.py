from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.bloomerang import (
    BloomerangResumeConfig,
    _build_params,
    _format_last_modified,
    bloomerang_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.settings import BLOOMERANG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.source import BloomerangSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bloomerang import (
    BloomerangSourceConfig,
)


class TestFormatLastModified:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_last_modified(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_incremental_endpoint_with_cursor(self) -> None:
        params = _build_params(
            BLOOMERANG_ENDPOINTS["Constituents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {
            "lastModified": "2026-03-04T02:58:14Z",
            "orderBy": "LastModifiedDate",
            "orderDirection": "Asc",
        }

    @parameterized.expand(
        [
            ("Constituents", "Id"),
            # Refunds, SoftCredits, and Notes reject `orderBy=Id`.
            ("SoftCredits", "CreatedDate"),
            ("Notes", "CreatedDate"),
        ]
    )
    def test_incremental_endpoint_without_cursor_falls_back_to_stable_sort(
        self, endpoint: str, expected_sort: str
    ) -> None:
        # First-ever sync: no watermark yet, but the endpoint still supports sorting, so page
        # boundaries must stay stable rather than sending no params at all.
        params = _build_params(
            BLOOMERANG_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {"orderBy": expected_sort, "orderDirection": "Asc"}

    def test_full_refresh_endpoint_with_sort_support_never_filters(self) -> None:
        # Transactions has no server-side lastModified filter; a cursor must not leak into the request.
        params = _build_params(
            BLOOMERANG_ENDPOINTS["Transactions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"orderBy": "Id", "orderDirection": "Asc"}


def _response(items: list[dict[str, Any]], *, total_filtered: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {}
    body["Results"] = items
    body["Total"] = total_filtered if total_filtered is not None else len(items)
    if total_filtered is not None:
        body["TotalFiltered"] = total_filtered
    body["Start"] = 0
    body["ResultCount"] = len(items)
    return ScriptedResponse(json=body)


def _make_manager(resume_state: BloomerangResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return bloomerang_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestBloomerangSourceTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(BloomerangSource(), BloomerangSourceConfig(api_key="key"))

    def test_paginates_until_short_page(self) -> None:
        # A full first page (== PAGE_SIZE) signals more rows remain; the paginator only stops once
        # a page comes back shorter than PAGE_SIZE.
        first_page = [{"Id": i} for i in range(1, 51)]
        result = self._driver().run(
            "Appeals",
            [
                _response(first_page, total_filtered=51),
                _response([{"Id": 51}], total_filtered=51),
            ],
        )

        assert result.raised is None
        assert [row["Id"] for row in result.rows] == list(range(1, 52))
        assert result.params("skip") == ["0", "50"]
        assert result.params("take") == ["50", "50"]

    def test_production_sync_does_not_follow_redirects(self) -> None:
        # `X-Api-Key` isn't the standard Authorization header, so `requests` won't strip it on a
        # cross-origin redirect — pin `allow_redirects=False` the same way the credential probe does.
        result = self._driver().run(
            "Appeals", [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})]
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/v2/appeals"]

    def test_saves_resume_state_only_while_pages_remain(self) -> None:
        first_page = [{"Id": i} for i in range(1, 51)]
        result = self._driver().run(
            "Appeals",
            [
                _response(first_page, total_filtered=51),
                _response([{"Id": 51}], total_filtered=51),
            ],
        )

        # State is saved only while more pages remain (offset 0 -> next offset 50), never on the
        # final (short) page.
        assert result.raised is None
        assert result.saved_states == [BloomerangResumeConfig(next_offset=50)]

    def test_resumes_from_saved_offset(self) -> None:
        result = self._driver().run(
            "Appeals",
            [_response([{"Id": 51}], total_filtered=51)],
            resume_state=BloomerangResumeConfig(next_offset=50),
        )

        assert result.raised is None
        assert [row["Id"] for row in result.rows] == [51]
        assert result.params("skip") == ["50"]

    def test_incremental_cursor_added_to_request(self) -> None:
        result = self._driver().run(
            "Constituents",
            [_response([{"Id": 1}], total_filtered=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("lastModified") == "2026-03-04T02:58:14Z"
        assert result.requests[0].param("orderBy") == "LastModifiedDate"

    def test_tasks_requests_every_status(self) -> None:
        result = self._driver().run("Tasks", [_response([{"Id": 1}], total_filtered=1)])

        assert result.raised is None
        assert result.requests[0].param("status") == "Active|Complete|Archived"
        assert result.requests[0].param("orderBy") == "CreatedDate"

    def test_audit_trail_endpoint_flattens_rows(self) -> None:
        result = self._driver().run(
            "Constituents",
            [
                _response(
                    [
                        {
                            "Id": 1,
                            "AuditTrail": {
                                "CreatedDate": "2026-01-01T00:00:00Z",
                                "LastModifiedDate": "2026-01-02T00:00:00Z",
                            },
                        }
                    ],
                    total_filtered=1,
                )
            ],
        )

        assert result.raised is None
        assert result.rows[0]["CreatedDate"] == "2026-01-01T00:00:00Z"
        assert result.rows[0]["LastModifiedDate"] == "2026-01-02T00:00:00Z"
        assert "AuditTrail" not in result.rows[0]

    def test_relationships_fan_out_reads_every_child_page_and_skips_missing_parents(self) -> None:
        child_first_page = [{"Id": i, "AccountId1": 102} for i in range(1, 51)]
        result = self._driver().run(
            "Relationships",
            [
                _response([{"Id": 101}, {"Id": 102}, {"Id": 103}], total_filtered=3),
                ScriptedResponse(status=404),
                _response(child_first_page, total_filtered=51),
                _response([{"Id": 51, "AccountId1": 102}], total_filtered=51),
                _response([], total_filtered=0),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v2/constituents",
            "/v2/constituent/101/relationships",
            "/v2/constituent/102/relationships",
            "/v2/constituent/102/relationships",
            "/v2/constituent/103/relationships",
        ]
        assert result.requests[0].param("orderBy") == "Id"
        assert [row["Id"] for row in result.rows] == list(range(1, 52))
        assert {row["ConstituentId"] for row in result.rows} == {102}
        # While constituent 102 has a child page left, a resume reads it again from its first page.
        assert result.saved_states == [
            BloomerangResumeConfig(next_offset=0, parent_index=1),
            BloomerangResumeConfig(next_offset=0, parent_index=2),
        ]

    def test_pledge_payment_failures_fan_out_over_pledge_designations_only(self) -> None:
        result = self._driver().run(
            "PledgePaymentFailures",
            [
                _response(
                    [
                        {"Id": 1, "Designations": [{"Id": 11, "Type": "Pledge"}, {"Id": 12, "Type": "Donation"}]},
                        {"Id": 2, "Designations": [{"Id": 21, "Type": "Pledge"}]},
                        {"Id": 3, "Designations": None},
                    ],
                    total_filtered=3,
                ),
                _response([{"Id": 900, "Date": "2026-01-05", "Amount": 25.0}], total_filtered=1),
                _response([{"Id": 901, "Date": "2026-02-05", "Amount": 10.0}], total_filtered=1),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v2/transactions",
            "/v2/pledge/11/paymentFailures",
            "/v2/pledge/21/paymentFailures",
        ]
        assert result.requests[0].param("type") == "Pledge"
        assert [(row["PledgeId"], row["Id"]) for row in result.rows] == [(11, 900), (21, 901)]
        assert result.saved_states == [
            BloomerangResumeConfig(next_offset=0, parent_index=1),
            BloomerangResumeConfig(next_offset=50, parent_index=0),
        ]

    def test_fan_out_resumes_at_saved_parent_page_and_parent(self) -> None:
        result = self._driver().run(
            "Relationships",
            [
                _response([{"Id": 151}, {"Id": 152}], total_filtered=52),
                _response([{"Id": 7}], total_filtered=1),
            ],
            resume_state=BloomerangResumeConfig(next_offset=50, parent_index=1),
        )

        assert result.raised is None
        assert result.paths == ["/v2/constituents", "/v2/constituent/152/relationships"]
        assert result.params("skip") == ["50", "0"]
        assert result.rows == [{"Id": 7, "ConstituentId": 152}]

    @parameterized.expand(
        [
            ("Constituents", "merge"),
            ("Transactions", "replace"),
            ("Appeals", "replace"),
        ]
    )
    def test_write_disposition_merges_only_for_incremental_sync(self, endpoint, expected_disposition) -> None:
        resource = _source(
            endpoint,
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        ).items()

        write_disposition = resource._hints.get("write_disposition")
        if expected_disposition == "merge":
            assert write_disposition == {"disposition": "merge", "strategy": "upsert"}
        else:
            assert write_disposition == "replace"


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, 200),
        ]
    )
    def test_status_mapping(self, status_code, expected_valid, expected_status) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, returned_status = validate_credentials("key")

        assert is_valid is expected_valid
        assert returned_status == expected_status
        assert network.requests_log[0].path == "/v2/constituents"

    def test_sends_api_key_header_without_following_redirects(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})]
        ) as network:
            is_valid, status = validate_credentials("secret-key")

        assert (is_valid, status) == (False, 302)
        assert network.requests_log[0].headers["x-api-key"] == "secret-key"
        assert [request.path for request in network.requests_log] == ["/v2/constituents"]
