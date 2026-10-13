import io
from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    CheckoutComResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.reports import (
    MAX_DISCOVERY_PAGES,
    CheckoutComReportKeyError,
    CheckoutComReportParseError,
    CheckoutComReportsListingError,
    _parse_report_file_rows,
    checkout_com_reports_source,
    discover_report_types,
    report_type_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.reports.make_tracked_session"
)


class _FakeRaw:
    """Stand-in for `response.raw`: a readable byte stream the file path streams CSV off."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)
        self.decode_content = False

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        return self._buffer.read(*args, **kwargs)

    def readable(self) -> bool:
        return True


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Optional[dict[str, Any]] = None,
        text: str = "",
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.raw = _FakeRaw(text.encode())
        self.headers = headers or {}
        self.closed = False

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise Exception(f"{self.status_code} Client Error for url")

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    """Replays a queued list of responses and records each request's URL and kwargs."""

    def __init__(self, responses: Optional[list[_FakeResponse]] = None) -> None:
        self._responses = list(responses or [])
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append({"url": url, **kwargs})
        if not self._responses:
            raise AssertionError(f"unexpected request to {url}")
        return self._responses.pop(0)


class _FakeManager(ResumableSourceManager[CheckoutComResumeConfig]):
    """In-memory stand-in for the Redis-backed manager (no `super().__init__`)."""

    def __init__(self, resume_state: Optional[CheckoutComResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[CheckoutComResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[CheckoutComResumeConfig]:
        return self._resume_state

    def save_state(self, data: CheckoutComResumeConfig) -> None:
        self.saved_states.append(data)


def _report(
    report_id: str,
    created_on: str,
    report_type: str = "FinancialActions",
    files: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "id": report_id,
        "created_on": created_on,
        "last_modified_on": created_on,
        "type": report_type,
        "description": "Financial Actions by Payout ID",
        "account": {"client_id": "cli_1", "entity_id": "ent_1"},
        "tags": [],
        "from": "2024-01-01T00:00:00Z",
        "to": "2024-01-02T00:00:00Z",
        "files": files if files is not None else [],
        "_links": {"self": {"href": f"https://api.checkout.com/reports/{report_id}"}},
    }


def _csv_file(file_id: str) -> dict[str, Any]:
    return {
        "id": file_id,
        "filename": f"{file_id}.csv",
        "format": "CSV",
        "_links": {"self": {"href": f"https://api.checkout.com/files/{file_id}"}},
    }


def _listing(reports: list[dict[str, Any]], next_token: Optional[str] = None) -> _FakeResponse:
    links: dict[str, Any] = {"self": {"href": "https://api.checkout.com/reports"}}
    if next_token:
        links["next"] = {"href": f"https://api.checkout.com/reports?pagination_token={next_token}"}
    return _FakeResponse(json_data={"count": len(reports), "limit": 100, "data": reports, "_links": links})


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for chunk in source_response.items() for row in chunk]


def _source(
    schema_name: str,
    manager: Optional[_FakeManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return checkout_com_reports_source(
        environment="production",
        client_id="ack_id",
        client_secret="secret",
        schema_name=schema_name,
        logger=mock.MagicMock(),
        resumable_source_manager=manager or _FakeManager(),
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestReportTypeTableName:
    @pytest.mark.parametrize(
        "report_type, expected",
        [
            ("FinancialActions", "financial_actions_report"),
            ("Financial Actions", "financial_actions_report"),
            ("Payments", "payments_report"),
            ("Balances", "balances_report"),
            ("", None),
            ("!!!", None),
        ],
    )
    def test_maps_api_types_to_stable_table_names(self, report_type, expected):
        assert report_type_table_name(report_type) == expected


class TestParseReportFileRows:
    def test_parses_current_layout_with_metadata_and_skips_blank_lines(self):
        text = "Action ID,Payment ID,Report ID\nact_1,pay_1,csv_value\n\nact_2,pay_2,csv_value\n"
        logger = mock.MagicMock()
        metadata = {"report_id": "rpt_1", "file_id": "file_1"}

        rows = list(_parse_report_file_rows(io.StringIO(text), metadata, logger))

        assert rows == [
            # The CSV's own `Report ID` column loses to the injected metadata, which
            # carries the dedupe key.
            {
                "action_id": "act_1",
                "payment_id": "pay_1",
                "report_id": "rpt_1",
                "file_id": "file_1",
                "file_row_index": 0,
            },
            {
                "action_id": "act_2",
                "payment_id": "pay_2",
                "report_id": "rpt_1",
                "file_id": "file_1",
                "file_row_index": 1,
            },
        ]
        logger.warning.assert_not_called()

    # Legacy report generators make header and data-row widths disagree without
    # changing what a row means: a trailing delimiter on every data row adds an empty
    # overflow cell, a trailing delimiter on the header line adds an unnamed column,
    # and ragged writers omit trailing empty fields. Files like these used to parse to
    # zero rows while the sync reported success.
    @pytest.mark.parametrize(
        "text, expected",
        [
            pytest.param(
                "Action ID,Amount,Payout ID\nact_1,10,pout_1,\nact_2,20,pout_2,\n",
                [("act_1", "10", "pout_1"), ("act_2", "20", "pout_2")],
                id="trailing-delimiter-on-data-rows",
            ),
            pytest.param(
                "Action ID,Amount,Payout ID,\nact_1,10,pout_1\nact_2,20,pout_2\n",
                [("act_1", "10", "pout_1"), ("act_2", "20", "pout_2")],
                id="trailing-delimiter-on-header",
            ),
            pytest.param(
                "Action ID,Amount,Payout ID\nact_1,10,pout_1\nact_2,20\n",
                [("act_1", "10", "pout_1"), ("act_2", "20", "")],
                id="ragged-rows-omit-trailing-empty-fields",
            ),
        ],
    )
    def test_width_variant_layouts_parse_all_rows(self, text, expected):
        logger = mock.MagicMock()

        rows = list(_parse_report_file_rows(io.StringIO(text), {"file_id": "file_1"}, logger))

        assert [(row["action_id"], row["amount"], row["payout_id"]) for row in rows] == expected
        assert [row["file_row_index"] for row in rows] == [0, 1]
        # Layout variants are parsed, not treated as malformed, so a large legacy file
        # doesn't emit one warning per row.
        logger.warning.assert_not_called()

    def test_malformed_row_below_skip_threshold_warns_and_keeps_the_rest(self):
        # An unquoted embedded delimiter adds a cell that carries a value, which no
        # header assignment can make safe; that row is skipped, the rest survive.
        good_rows = "\n".join(f"act_{i},{i}" for i in range(19))
        text = f"Action ID,Amount\n{good_rows}\nact_bad,1,000\n"
        logger = mock.MagicMock()

        rows = list(_parse_report_file_rows(io.StringIO(text), {"file_id": "file_1"}, logger))

        assert len(rows) == 19
        assert all(row["action_id"] != "act_bad" for row in rows)
        logger.warning.assert_called_once()

    def test_skip_ratio_above_threshold_fails_the_file(self):
        good_rows = "\n".join(f"act_{i},10" for i in range(6))
        malformed_rows = "\n".join(f"act_bad_{i},1,000" for i in range(4))
        text = f"Action ID,Amount\n{good_rows}\n{malformed_rows}\n"

        with pytest.raises(CheckoutComReportParseError, match="skipped 4 of 10"):
            list(_parse_report_file_rows(io.StringIO(text), {"file_id": "file_1"}, mock.MagicMock()))

    def test_file_whose_data_rows_all_fail_to_parse_raises(self):
        text = "Action ID,Amount\nact_1,1,000\nact_2,2,000\n"

        with pytest.raises(CheckoutComReportParseError, match="none parsed"):
            list(_parse_report_file_rows(io.StringIO(text), {"file_id": "file_1"}, mock.MagicMock()))

    # A scheduled report over a period with no activity is header-only (or empty) by
    # design, so a file with no data lines at all yields nothing rather than raising —
    # raising would wedge the sync permanently on a legitimately quiet period. Only a
    # file whose data lines exist but all fail to parse is a defect (tested above).
    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("", id="zero-byte-file"),
            pytest.param("Action ID,Amount\n", id="header-only"),
            pytest.param("Action ID,Amount\n\n  \n", id="header-and-blank-lines"),
        ],
    )
    def test_file_with_no_data_lines_is_empty_not_a_defect(self, text):
        assert list(_parse_report_file_rows(io.StringIO(text), {}, mock.MagicMock())) == []

    def test_missing_key_column_raises_rather_than_loading_undedupable_rows(self):
        # Without the key column the merge cannot match a restated row, so every
        # regenerated file would add another copy instead of updating one.
        text = "Payment ID,Amount\npay_1,10\n"

        with pytest.raises(CheckoutComReportKeyError):
            list(_parse_report_file_rows(io.StringIO(text), {"file_id": "file_1"}, mock.MagicMock(), "action_id"))


class TestReportsMetadataTable:
    @mock.patch(SESSION_PATCH)
    def test_paginates_sorts_ascending_and_strips_links(self, mock_make_session):
        # Pages arrive newest-first to prove the source re-sorts before yielding.
        api_session = _FakeSession(
            [
                _listing([_report("rpt_2", "2024-02-01T00:00:00Z")], next_token="tok_1"),
                _listing([_report("rpt_1", "2024-01-01T00:00:00Z")]),
            ]
        )
        mock_make_session.side_effect = [api_session]

        rows = _rows(_source("reports"))

        assert [row["id"] for row in rows] == ["rpt_1", "rpt_2"]
        assert api_session.requests[1]["params"]["pagination_token"] == "tok_1"
        assert all("_links" not in row for row in rows)
        assert all(kwargs.get("auth") is not None for kwargs in api_session.requests)

    @mock.patch(SESSION_PATCH)
    def test_missing_data_key_yields_nothing(self, mock_make_session):
        api_session = _FakeSession([_FakeResponse(json_data={"count": 0})])
        mock_make_session.side_effect = [api_session]

        assert _rows(_source("reports")) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.reports.MAX_LIST_PAGES", 2
    )
    @mock.patch(SESSION_PATCH)
    def test_sync_fails_loudly_when_listing_exceeds_page_cap(self, mock_make_session):
        api_session = _FakeSession(
            [_listing([_report(f"rpt_{page}", "2024-01-01T00:00:00Z")], next_token=f"tok_{page}") for page in range(3)]
        )
        mock_make_session.side_effect = [api_session]
        manager = _FakeManager()

        # A partial listing must not produce rows: yielding would advance the
        # incremental watermark past the reports that were never listed.
        with pytest.raises(CheckoutComReportsListingError):
            _rows(_source("reports", manager=manager))
        assert manager.saved_states == []


class TestReportFileSync:
    @mock.patch(SESSION_PATCH)
    def test_syncs_matching_reports_and_follows_redirect_without_credentials(self, mock_make_session):
        csv_text = 'Action ID,Amount\nact_1,"multi\nline"\nact_2,20\n'
        api_session = _FakeSession(
            [
                _listing(
                    [
                        _report("rpt_other", "2024-01-01T00:00:00Z", report_type="Payments"),
                        _report(
                            "rpt_1",
                            "2024-02-01T00:00:00Z",
                            files=[
                                _csv_file("file_1"),
                                {"id": "file_2", "filename": "file_2.xlsx", "format": "XLSX"},
                            ],
                        ),
                    ]
                ),
                _FakeResponse(
                    status_code=302,
                    headers={
                        "Location": "https://files.example.com/signed?X-Amz-Credential=AKIA%2F1&X-Amz-Signature=sig123"
                    },
                ),
            ]
        )
        file_session = _FakeSession([_FakeResponse(text=csv_text)])
        mock_make_session.side_effect = [api_session, file_session]
        manager = _FakeManager()
        logger = mock.MagicMock()

        response = checkout_com_reports_source(
            environment="production",
            client_id="ack_id",
            client_secret="secret",
            schema_name="financial_actions_report",
            logger=logger,
            resumable_source_manager=manager,
        )
        rows = _rows(response)

        assert rows == [
            {
                "action_id": "act_1",
                "amount": "multi\nline",
                "report_id": "rpt_1",
                "report_created_on": "2024-02-01T00:00:00Z",
                "report_from": "2024-01-01T00:00:00Z",
                "report_to": "2024-01-02T00:00:00Z",
                "report_entity_id": "ent_1",
                "file_id": "file_1",
                "file_row_index": 0,
            },
            {
                "action_id": "act_2",
                "amount": "20",
                "report_id": "rpt_1",
                "report_created_on": "2024-02-01T00:00:00Z",
                "report_from": "2024-01-01T00:00:00Z",
                "report_to": "2024-01-02T00:00:00Z",
                "report_entity_id": "ent_1",
                "file_id": "file_1",
                "file_row_index": 1,
            },
        ]
        # The bearer-authenticated session never follows the redirect; the signed
        # storage URL is fetched by a separate session with no credentials attached.
        file_request = api_session.requests[1]
        assert file_request["url"] == "https://api.checkout.com/reports/rpt_1/files/file_1"
        assert file_request["auth"] is not None
        assert file_request["stream"] is True
        assert file_session.requests == [
            {
                "url": "https://files.example.com/signed?X-Amz-Credential=AKIA%2F1&X-Amz-Signature=sig123",
                "stream": True,
                "timeout": mock.ANY,
            }
        ]
        # The signed URL's raw query values are in the file session's redaction set, so
        # the replayable download credentials never appear in request logs.
        file_session_redactions = mock_make_session.call_args_list[1].kwargs["redact_values"]
        assert "sig123" in file_session_redactions
        assert "AKIA%2F1" in file_session_redactions
        # The XLSX file is skipped with a warning, and the report checkpoints once
        # after its files are fully yielded.
        logger.warning.assert_called_once()
        assert manager.saved_states == [
            CheckoutComResumeConfig(report_created_on="2024-02-01T00:00:00Z", report_id="rpt_1")
        ]

    @mock.patch(SESSION_PATCH)
    def test_direct_file_response_without_redirect_parses(self, mock_make_session):
        api_session = _FakeSession(
            [
                _listing([_report("rpt_1", "2024-02-01T00:00:00Z", files=[_csv_file("file_1")])]),
                _FakeResponse(text="Action ID\nact_1\n"),
            ]
        )
        mock_make_session.side_effect = [api_session]

        rows = _rows(_source("financial_actions_report"))

        assert [row["action_id"] for row in rows] == ["act_1"]
        # No redirect means no separate download session is ever built.
        assert mock_make_session.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_file_parsing_to_zero_rows_fails_the_sync_without_checkpointing(self, mock_make_session):
        api_session = _FakeSession(
            [
                _listing([_report("rpt_1", "2024-02-01T00:00:00Z", files=[_csv_file("file_1")])]),
                _FakeResponse(text="Action ID,Amount\nact_1,1,000\n"),
            ]
        )
        mock_make_session.side_effect = [api_session]
        manager = _FakeManager()

        with pytest.raises(CheckoutComReportParseError):
            _rows(_source("financial_actions_report", manager=manager))
        # The failed report is not checkpointed, so a retry re-reads it instead of
        # resuming past data that never loaded.
        assert manager.saved_states == []

    @mock.patch(SESSION_PATCH)
    def test_restatements_are_read_oldest_first_so_the_newest_copy_wins(self, mock_make_session):
        # The writer keeps the last occurrence of a key in a batch, so read order decides
        # which copy of a restated action survives. Reports must be walked oldest-first and
        # files within a report in id order, whatever order the listing returned them in.
        api_session = _FakeSession(
            [
                _listing(
                    [
                        _report(
                            "rpt_new",
                            "2024-02-01T00:00:00Z",
                            files=[_csv_file("file_z"), _csv_file("file_a")],
                        ),
                        _report("rpt_old", "2024-01-01T00:00:00Z", files=[_csv_file("file_m")]),
                    ]
                ),
                _FakeResponse(text="Action ID,Amount\nact_1,10\n"),
                _FakeResponse(text="Action ID,Amount\nact_1,20\n"),
                _FakeResponse(text="Action ID,Amount\nact_1,30\n"),
            ]
        )
        mock_make_session.side_effect = [api_session]

        rows = _rows(_source("financial_actions_report"))

        assert [(row["file_id"], row["amount"]) for row in rows] == [
            ("file_m", "10"),
            ("file_a", "20"),
            ("file_z", "30"),
        ]

    @pytest.mark.parametrize("location", [None, "http://files.example.com/signed"])
    @mock.patch(SESSION_PATCH)
    def test_non_https_redirect_location_raises(self, mock_make_session, location):
        headers = {"Location": location} if location else {}
        api_session = _FakeSession(
            [
                _listing([_report("rpt_1", "2024-02-01T00:00:00Z", files=[_csv_file("file_1")])]),
                _FakeResponse(status_code=302, headers=headers),
            ]
        )
        mock_make_session.side_effect = [api_session]

        with pytest.raises(ValueError):
            _rows(_source("financial_actions_report"))

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected",
        [
            (True, datetime(2024, 1, 2, tzinfo=UTC), "2024-01-02T00:00:00Z"),
            (True, None, None),
            (False, datetime(2024, 1, 2, tzinfo=UTC), None),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_incremental_watermark_becomes_created_after(
        self, mock_make_session, should_use_incremental_field, last_value, expected
    ):
        api_session = _FakeSession([_listing([])])
        mock_make_session.side_effect = [api_session]

        _rows(
            _source(
                "financial_actions_report",
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )
        )

        assert api_session.requests[0]["params"].get("created_after") == expected

    @mock.patch(SESSION_PATCH)
    def test_resume_fast_forwards_listing_and_skips_completed_report(self, mock_make_session):
        api_session = _FakeSession(
            [
                _listing(
                    [
                        _report("rpt_done", "2024-02-01T00:00:00Z", files=[_csv_file("file_done")]),
                        _report("rpt_next", "2024-02-02T00:00:00Z", files=[_csv_file("file_next")]),
                    ]
                ),
                _FakeResponse(text="Action ID\nact_9\n"),
            ]
        )
        mock_make_session.side_effect = [api_session]
        manager = _FakeManager(CheckoutComResumeConfig(report_created_on="2024-02-01T00:00:00Z", report_id="rpt_done"))

        rows = _rows(
            _source(
                "financial_actions_report",
                manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )

        # The checkpoint wins over the older incremental watermark, and the already
        # completed boundary report is not re-downloaded.
        assert api_session.requests[0]["params"]["created_after"] == "2024-02-01T00:00:00Z"
        assert [row["report_id"] for row in rows] == ["rpt_next"]
        assert manager.saved_states == [
            CheckoutComResumeConfig(report_created_on="2024-02-02T00:00:00Z", report_id="rpt_next")
        ]


class TestDiscoverReportTypes:
    @mock.patch(SESSION_PATCH)
    def test_dedupes_types_and_skips_unusable_ones(self, mock_make_session):
        api_session = _FakeSession(
            [
                _listing(
                    [
                        _report("rpt_1", "2024-01-01T00:00:00Z", report_type="FinancialActions"),
                        _report("rpt_2", "2024-01-02T00:00:00Z", report_type="FinancialActions"),
                        _report("rpt_3", "2024-01-03T00:00:00Z", report_type="Payments"),
                        _report("rpt_4", "2024-01-04T00:00:00Z", report_type=""),
                    ]
                )
            ]
        )
        mock_make_session.side_effect = [api_session]

        assert discover_report_types("production", "ack_id", "secret") == {
            "financial_actions_report": "FinancialActions",
            "payments_report": "Payments",
        }

    @mock.patch(SESSION_PATCH)
    def test_discovery_is_bounded_to_max_pages(self, mock_make_session):
        api_session = _FakeSession(
            [
                _listing([_report(f"rpt_{page}", "2024-01-01T00:00:00Z")], next_token=f"tok_{page}")
                for page in range(MAX_DISCOVERY_PAGES + 5)
            ]
        )
        mock_make_session.side_effect = [api_session]

        discover_report_types("production", "ack_id", "secret")

        assert len(api_session.requests) == MAX_DISCOVERY_PAGES


class TestCheckoutComReportsSourceResponse:
    @pytest.mark.parametrize(
        "schema_name, primary_keys, partition_keys",
        [
            ("reports", ["id"], ["created_on"]),
            ("balances_report", ["file_id", "file_row_index"], ["report_created_on"]),
            # Report types Checkout.com regenerates over an overlapping range key on the
            # action instead, and stay unpartitioned: the merge matches on primary key and
            # partition together, so partitioning on report creation time would put a
            # restatement in a different partition and insert a copy instead of updating.
            ("financial_actions_report", ["action_id", "breakdown_type"], None),
            ("financial_actions_by_payout_report", ["action_id", "breakdown_type"], None),
        ],
    )
    def test_response_metadata(self, schema_name, primary_keys, partition_keys):
        response = _source(schema_name)

        assert response.name == schema_name
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        # Reports are re-sorted oldest-first before yielding, so ascending watermark
        # commits are safe.
        assert response.sort_mode == "asc"

    def test_unknown_schema_raises(self):
        with pytest.raises(ValueError):
            _source("nope")
