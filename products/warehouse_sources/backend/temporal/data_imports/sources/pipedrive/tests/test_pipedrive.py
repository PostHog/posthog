import json
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive import (
    PAGE_SIZE,
    WEBHOOK_AUTH_USER,
    PipedriveResumeConfig,
    _webhook_table_transformer,
    base_url,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    normalize_company_domain,
    pipedrive_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import endpoints_for_version

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    items: Optional[list[dict[str, Any]]],
    additional_data: Optional[dict[str, Any]] = None,
    *,
    drop_data: bool = False,
    status: int = 200,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_data:
        body["data"] = items or []
    if additional_data is not None:
        body["additional_data"] = additional_data
    resp = Response()
    resp.status_code = status
    resp.reason = "Unauthorized" if status == 401 else "OK"
    resp.url = f"https://acme.pipedrive.com/api/v2/deals?limit={PAGE_SIZE}"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: PipedriveResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(
    session: mock.MagicMock,
    responses: list[Response],
    *,
    prepared_url: Optional[str] = None,
    urls: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared. The prepared request carries a real on-host URL so the client's SSRF
    host check (allowed_hosts is pinned) sees a valid host.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        if urls is not None:
            urls.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = prepared_url or "https://acme.pipedrive.com/api/v2/deals"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _webhook_manager(enabled: bool = False) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
    return manager


def _source(endpoint: str, manager: mock.MagicMock, webhook_manager: mock.MagicMock | None = None):
    return pipedrive_source(
        "acme",
        "token",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        webhook_source_manager=webhook_manager or _webhook_manager(),
    )


class TestNormalizeCompanyDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("mycompany", "mycompany"),
            ("MyCompany", "mycompany"),
            ("mycompany.pipedrive.com", "mycompany"),
            ("https://mycompany.pipedrive.com", "mycompany"),
            ("http://mycompany.pipedrive.com/", "mycompany"),
            ("  mycompany  ", "mycompany"),
            ("my-company-123", "my-company-123"),
        ],
    )
    def test_normalizes_valid_domains(self, raw: str, expected: str) -> None:
        assert normalize_company_domain(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "my company",
            "evil.com",
            "mycompany.pipedrive.com.evil.com",
            "http://169.254.169.254",
            "foo_bar",
        ],
    )
    def test_rejects_invalid_domains(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_company_domain(raw)

    def test_rejection_message_guides_without_echoing_input(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            normalize_company_domain("https://secret-subdomain.example.com/")
        message = str(exc_info.value)
        assert "secret-subdomain" not in message
        assert "pipedrive.com" in message

    def test_base_url_is_pinned_to_pipedrive(self) -> None:
        assert base_url("mycompany") == "https://mycompany.pipedrive.com"
        assert base_url("https://MyCompany.pipedrive.com") == "https://mycompany.pipedrive.com"


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    def test_returns_status_code(self, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("acme", "token") == status_code

        assert {request.url for request in network.requests_log} == {"https://acme.pipedrive.com/api/v1/users/me"}
        # Auth header travels on the probe request; token redaction is configured on the session.
        assert all(request.headers["x-api-token"] == "token" for request in network.requests_log)
        assert network.session_options[0]["redact_values"] == ("token",)

    def test_returns_none_on_transport_error(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("acme", "token") is None

        assert {request.path for request in network.requests_log} == {"/api/v1/users/me"}

    def test_propagates_invalid_domain(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com", "token")


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_cursor_endpoint_and_saves_state_after_yield(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}], {"next_cursor": "c2"}),
                _response([{"id": 2}], {"next_cursor": None}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("deals", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # First page carries only limit; the cursor is injected on the second request.
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {"limit": PAGE_SIZE, "cursor": "c2"}
        # State saved once, after the first page (pointing at the cursor for page 2); final page saves nothing.
        manager.save_state.assert_called_once_with(PipedriveResumeConfig(paginator_state={"cursor": "c2"}))

    @pytest.mark.parametrize("terminal_cursor", [{}, {"next_cursor": None}, {"next_cursor": ""}])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_terminates_when_no_next_cursor(
        self, MockSession: mock.MagicMock, terminal_cursor: dict[str, Any]
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], terminal_cursor)])

        manager = _make_manager()
        rows = _rows(_source("deals", manager))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_offset_endpoint_and_progresses_start(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(
            session,
            [
                _response(full_page, {"pagination": {"more_items_in_collection": True, "next_start": PAGE_SIZE}}),
                _response([{"id": 9999}], {"pagination": {"more_items_in_collection": False}}),
            ],
        )

        manager = _make_manager()
        # `notes` is an offset-paginated endpoint under every version (activities is offset only
        # under a v1 pin; the default is now v2, where it paginates by cursor).
        rows = _rows(_source("notes", manager))

        assert [r["id"] for r in rows] == [*range(PAGE_SIZE), 9999]
        # OffsetPaginator injects start + limit; a full page advances start by the page size.
        assert params[0] == {"start": 0, "limit": PAGE_SIZE}
        assert params[1] == {"start": PAGE_SIZE, "limit": PAGE_SIZE}
        # Short second page ends pagination; checkpoint saved once after the first (full) page.
        manager.save_state.assert_called_once_with(PipedriveResumeConfig(paginator_state={"offset": PAGE_SIZE}))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}], {"pagination": {"more_items_in_collection": False}})])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_cursor_from_saved_paginator_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 9}], {"next_cursor": None})])

        manager = _make_manager(PipedriveResumeConfig(paginator_state={"cursor": "resume-me"}))
        rows = _rows(_source("deals", manager))

        assert rows == [{"id": 9}]
        # The saved cursor seeds the very first request.
        assert params[0] == {"limit": PAGE_SIZE, "cursor": "resume-me"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_offset_from_saved_paginator_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 9}], {"pagination": {"more_items_in_collection": False}})])

        manager = _make_manager(PipedriveResumeConfig(paginator_state={"offset": 500}))
        _rows(_source("notes", manager))

        assert params[0] == {"start": 500, "limit": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_next_url_resume_starts_fresh(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], {"next_cursor": None})])

        # Old-shape state (full next_url, no paginator_state) still parses but restarts the endpoint.
        manager = _make_manager(
            PipedriveResumeConfig(next_url=f"https://acme.pipedrive.com/api/v2/deals?limit={PAGE_SIZE}&cursor=old")
        )
        rows = _rows(_source("deals", manager))

        assert rows == [{"id": 1}]
        assert params[0] == {"limit": PAGE_SIZE}
        assert "cursor" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_non_retryable_error(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True, status=401)])

        with pytest.raises(Exception, match="401 Client Error"):
            _rows(_source("deals", _make_manager()))

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_transient_server_error_then_succeeds(
        self, MockSession: mock.MagicMock, _mock_sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, drop_data=True, status=500),
                _response([{"id": 7}], {"next_cursor": None}),
            ],
        )

        rows = _rows(_source("deals", _make_manager()))

        assert rows == [{"id": 7}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_off_host_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # A prepared URL off the pinned pipedrive host must be refused before the request leaves.
        _wire(session, [_response([{"id": 1}])], prepared_url="https://evil.example.com/steal")

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("deals", _make_manager()))


class TestLookupEndpoints:
    @pytest.mark.parametrize("endpoint", ["lead_labels", "activity_types", "project_boards"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_every_row_in_one_request(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE + 100)]
        params = _wire(session, [_response(full_page)])

        rows = _rows(_source(endpoint, _make_manager()))

        assert len(rows) == PAGE_SIZE + 100
        assert session.send.call_count == 1
        assert params == [{}]


BASE = "https://acme.pipedrive.com"
DEAL_LIST_PARAMS = {"limit": PAGE_SIZE, "sort_by": "id", "sort_direction": "asc"}


class TestDealFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deal_products_batches_active_and_archived_deals(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], {"next_cursor": None}),
                _response([{"id": 10, "deal_id": 1}], {"next_cursor": "c2"}),
                _response([{"id": 11, "deal_id": 2}], {"next_cursor": None}),
                _response([{"id": 3}], {"next_cursor": None}),
                _response([{"id": 12, "deal_id": 3}], {"next_cursor": None}),
            ],
            urls=urls,
        )
        manager = _make_manager()

        rows = _rows(_source("deal_products", manager))

        assert [row["id"] for row in rows] == [10, 11, 12]
        assert urls == [
            f"{BASE}/api/v2/deals",
            f"{BASE}/api/v2/deals/products",
            f"{BASE}/api/v2/deals/products",
            f"{BASE}/api/v2/deals/archived",
            f"{BASE}/api/v2/deals/products",
        ]
        assert params == [
            DEAL_LIST_PARAMS,
            {"deal_ids": "1,2", "limit": PAGE_SIZE},
            {"deal_ids": "1,2", "limit": PAGE_SIZE, "cursor": "c2"},
            DEAL_LIST_PARAMS,
            {"deal_ids": "3", "limit": PAGE_SIZE},
        ]
        assert manager.save_state.call_args.args[0] == PipedriveResumeConfig(
            paginator_state={"parent_index": 1, "parent_page": None, "done_through": 3, "group": None, "child": None}
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deal_changelog_reads_each_deal_and_skips_a_deleted_one(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        change = {"field_key": "stage_id", "old_value": "1", "new_value": "2", "time": "2024-05-01 10:00:00"}
        _wire(
            session,
            [
                _response([{"id": 7}, {"id": 8}], {"next_cursor": None}),
                _response([dict(change)], {"next_cursor": None}),
                _response(None, drop_data=True, status=404),
                _response([], {"next_cursor": None}),
            ],
            urls=urls,
        )

        rows = _rows(_source("deal_changelog", _make_manager()))

        assert rows == [{**change, "deal_id": 7}]
        assert urls == [
            f"{BASE}/api/v2/deals",
            f"{BASE}/api/v1/deals/7/changelog",
            f"{BASE}/api/v1/deals/8/changelog",
            f"{BASE}/api/v2/deals/archived",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_continues_inside_the_saved_deal(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(
            session,
            [
                _response([{"field_key": "status", "time": "2024-05-02 09:00:00"}], {"next_cursor": None}),
                _response([{"id": 5}, {"id": 6}, {"id": 7}], {"next_cursor": None}),
                _response([{"field_key": "value", "time": "2024-05-03 09:00:00"}], {"next_cursor": None}),
            ],
            urls=urls,
        )
        manager = _make_manager(
            PipedriveResumeConfig(
                paginator_state={
                    "parent_index": 1,
                    "parent_page": {"cursor": "p2"},
                    "done_through": 5,
                    "group": [6],
                    "child": {"cursor": "c9"},
                }
            )
        )

        rows = _rows(_source("deal_changelog", manager))

        assert [row["deal_id"] for row in rows] == [6, 7]
        assert urls == [
            f"{BASE}/api/v1/deals/6/changelog",
            f"{BASE}/api/v2/deals/archived",
            f"{BASE}/api/v1/deals/7/changelog",
        ]
        assert params == [
            {"limit": PAGE_SIZE, "cursor": "c9"},
            {**DEAL_LIST_PARAMS, "cursor": "p2"},
            {"limit": PAGE_SIZE},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_finishes_the_saved_batch_when_its_deals_changed(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(
            session,
            [
                _response([{"id": 31, "deal_id": 2}], {"next_cursor": None}),
                # Deal 2 was deleted and deal 4 added since the crash, so a rebuilt batch would differ.
                _response([{"id": 1}, {"id": 3}, {"id": 4}], {"next_cursor": None}),
                _response([{"id": 41, "deal_id": 4}], {"next_cursor": None}),
                _response([], {"next_cursor": None}),
            ],
            urls=urls,
        )
        manager = _make_manager(
            PipedriveResumeConfig(
                paginator_state={
                    "parent_index": 0,
                    "parent_page": None,
                    "done_through": None,
                    "group": [1, 2, 3],
                    "child": {"cursor": "c2"},
                }
            )
        )

        rows = _rows(_source("deal_products", manager))

        assert [row["id"] for row in rows] == [31, 41]
        assert urls[:3] == [
            f"{BASE}/api/v2/deals/products",
            f"{BASE}/api/v2/deals",
            f"{BASE}/api/v2/deals/products",
        ]
        assert params[0] == {"deal_ids": "1,2,3", "limit": PAGE_SIZE, "cursor": "c2"}
        assert params[2] == {"deal_ids": "4", "limit": PAGE_SIZE}


MAIL_THREADS_URL = f"{BASE}/api/v1/mailbox/mailThreads"


def _folder_params(folder: str, start: int = 0) -> dict[str, Any]:
    return {"folder": folder, "start": start, "limit": PAGE_SIZE}


class TestMailbox:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mail_threads_reads_every_folder_once_per_thread(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                # Thread 2 holds an inbox and a sent message, so it lists in both folders.
                _response([{"id": 2}, {"id": 3}]),
                _response([]),
                _response(None),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("mail_threads", manager))

        assert [row["id"] for row in rows] == [1, 2, 3]
        assert params == [_folder_params(folder) for folder in ("inbox", "sent", "archive", "drafts")]
        assert manager.save_state.call_args.args[0] == PipedriveResumeConfig(paginator_state={"folder_index": 4})

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mail_messages_reads_each_thread_and_skips_a_deleted_one(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response([{"id": 10, "mail_thread_id": 1}, {"id": 11, "mail_thread_id": 1}]),
                _response(None, drop_data=True, status=404),
                _response([{"id": 1}]),
                _response([]),
                _response([]),
            ],
            urls=urls,
        )
        manager = _make_manager()

        rows = _rows(_source("mail_messages", manager))

        assert [row["id"] for row in rows] == [10, 11]
        assert urls == [
            MAIL_THREADS_URL,
            f"{MAIL_THREADS_URL}/1/mailMessages",
            f"{MAIL_THREADS_URL}/2/mailMessages",
            MAIL_THREADS_URL,
            MAIL_THREADS_URL,
            MAIL_THREADS_URL,
        ]
        assert [call.args[0].paginator_state for call in manager.save_state.call_args_list] == [
            {"folder_index": 0, "page": None, "done_ids": [1]},
            # Inbox is done, and the inbox thread listed again in sent is skipped.
            {"folder_index": 1},
            {"folder_index": 2},
            {"folder_index": 3},
            {"folder_index": 4},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mail_messages_resume_continues_inside_the_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(
            session,
            [
                # The resume lists the inbox and the sent pages before the saved one to rebuild
                # the threads already read.
                _response([{"id": 7}]),
                _response([{"id": 4}]),
                # A reply moved thread 6 ahead of thread 5, which was done before the crash, and
                # thread 7 was already read from the inbox.
                _response([{"id": 6}, {"id": 5}, {"id": 7}]),
                _response([{"id": 60, "mail_thread_id": 6}]),
                _response([]),
                _response([]),
            ],
            urls=urls,
        )
        manager = _make_manager(
            PipedriveResumeConfig(paginator_state={"folder_index": 1, "page": {"offset": 500}, "done_ids": [5]})
        )

        rows = _rows(_source("mail_messages", manager))

        assert [row["id"] for row in rows] == [60]
        assert urls == [MAIL_THREADS_URL] * 3 + [f"{MAIL_THREADS_URL}/6/mailMessages"] + [MAIL_THREADS_URL] * 2
        assert params[:3] == [_folder_params("inbox"), _folder_params("sent"), _folder_params("sent", start=500)]
        assert params[4:] == [_folder_params("archive"), _folder_params("drafts")]
        assert [call.args[0].paginator_state for call in manager.save_state.call_args_list] == [
            {"folder_index": 1, "page": {"offset": 500}, "done_ids": [5, 6]},
            {"folder_index": 2},
            {"folder_index": 3},
            {"folder_index": 4},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mail_threads_resume_skips_threads_read_before_the_crash(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response([{"id": 2}, {"id": 3}]),
                _response([]),
                _response(None),
            ],
        )
        manager = _make_manager(PipedriveResumeConfig(paginator_state={"folder_index": 1}))

        rows = _rows(_source("mail_threads", manager))

        assert [row["id"] for row in rows] == [3]


class TestProjectPhases:
    @pytest.mark.parametrize(
        "resume_state, boards, phase_pages, expected_phase_boards, expected_ids, expected_done",
        [
            (None, [1, 2, 3], [[{"id": 11}], [], [{"id": 31}, {"id": 32}]], [1, 2, 3], [11, 31, 32], [1, 3]),
            # Board 1 was deleted after it was read, so board 2 is now first in the listing.
            ({"done_board_ids": [1]}, [2, 3], [[{"id": 21}], [{"id": 31}]], [2, 3], [21, 31], [1, 2, 3]),
            ({"done_board_ids": [1, 2]}, [1, 2, 3], [[{"id": 31}]], [3], [31], [1, 2, 3]),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_the_phases_of_each_board(
        self,
        MockSession: mock.MagicMock,
        resume_state: Optional[dict[str, Any]],
        boards: list[int],
        phase_pages: list[list[dict[str, Any]]],
        expected_phase_boards: list[int],
        expected_ids: list[int],
        expected_done: list[int],
    ) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(
            session,
            [_response([{"id": board_id} for board_id in boards]), *(_response(page) for page in phase_pages)],
            urls=urls,
        )
        manager = _make_manager(PipedriveResumeConfig(paginator_state=resume_state) if resume_state else None)

        rows = _rows(_source("project_phases", manager))

        assert [row["id"] for row in rows] == expected_ids
        assert urls == [f"{BASE}/api/v1/projects/boards"] + [f"{BASE}/api/v1/projects/phases"] * len(phase_pages)
        assert params[1:] == [{"board_id": board_id} for board_id in expected_phase_boards]
        assert manager.save_state.call_args.args[0] == PipedriveResumeConfig(
            paginator_state={"done_board_ids": expected_done}
        )


class TestPipedriveSourcePartitioning:
    @pytest.mark.parametrize(
        "endpoint, expected_primary_keys, expected_partition_keys, expected_mode",
        [
            ("deals", ["id"], ["add_time"], "datetime"),
            ("activities", ["id"], ["add_time"], "datetime"),
            ("users", ["id"], None, None),
            ("deal_fields", ["id"], None, None),
            ("lead_labels", ["id"], None, None),
            ("deal_products", ["deal_id", "id"], ["add_time"], "datetime"),
            ("deal_changelog", ["deal_id", "field_key", "time"], ["time"], "datetime"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_partitioning(
        self,
        MockSession: mock.MagicMock,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_partition_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == expected_mode
        assert response.partition_format == ("week" if expected_mode else None)


class TestEndpointsForVersion:
    @pytest.mark.parametrize(
        "api_version, expected_path, expected_pagination",
        [
            ("v1", "/api/v1/activities", "offset"),
            ("v2", "/api/v2/activities", "cursor"),
            # A pin we don't recognise resolves to the current (v2) endpoint, not the sunset one.
            ("v99", "/api/v2/activities", "cursor"),
        ],
    )
    def test_activities_endpoint_switches_by_version(
        self, api_version: str, expected_path: str, expected_pagination: str
    ) -> None:
        activities = endpoints_for_version(api_version)["activities"]
        assert activities.path == expected_path
        assert activities.pagination == expected_pagination

    def test_shared_endpoints_are_version_independent(self) -> None:
        # Only `activities` diverges; everything else must be identical across versions.
        v1 = {name: cfg for name, cfg in endpoints_for_version("v1").items() if name != "activities"}
        v2 = {name: cfg for name, cfg in endpoints_for_version("v2").items() if name != "activities"}
        assert v1 == v2


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hf_1"


class TestWebhookManagement:
    def test_create_registers_a_wildcard_v2_subscription_with_generated_credentials(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(status=201, json={"success": True, "data": {"id": 9}}),
                ScriptedResponse(json={"data": []}),
            ]
        ) as network:
            result = create_webhook("acme", "token", WEBHOOK_URL)

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["POST", "GET"]
        assert [request.path for request in network.requests_log] == ["/api/v1/webhooks", "/api/v1/webhooks"]
        assert network.requests_log[0].headers["x-api-token"] == "token"
        body = network.requests_log[0].json()
        assert body["subscription_url"] == WEBHOOK_URL
        assert (body["event_action"], body["event_object"]) == ("*", "*")
        assert body["version"] == "2.0"
        # Pipedrive signs nothing, so the generated basic auth credentials are the only thing
        # separating our ingest endpoint from an unauthenticated one. They have to reach both
        # Pipedrive and the hog function or every delivery is unverifiable.
        assert body["http_auth_user"] == result.extra_inputs["http_auth_user"] == WEBHOOK_AUTH_USER
        assert body["http_auth_password"] == result.extra_inputs["http_auth_password"]
        assert len(body["http_auth_password"]) >= 32
        assert network.session_options[0]["redact_values"] == ("token", body["http_auth_password"])

    def test_create_generates_a_fresh_password_each_time(self) -> None:
        script = [
            ScriptedResponse(status=201, json={"success": True, "data": {"id": 9}}),
            ScriptedResponse(json={"data": []}),
        ] * 2
        with scripted_network(script) as network:
            first = create_webhook("acme", "token", WEBHOOK_URL)
            second = create_webhook("acme", "token", WEBHOOK_URL)

        assert first.extra_inputs["http_auth_password"] != second.extra_inputs["http_auth_password"]
        assert [request.method for request in network.requests_log] == ["POST", "GET", "POST", "GET"]

    def test_create_removes_the_subscription_it_replaces(self) -> None:
        # Each create mints a new password, so an older subscription on the same URL would keep
        # delivering with credentials the hog function no longer accepts.
        with scripted_network(
            [
                ScriptedResponse(status=201, json={"success": True, "data": {"id": 9}}),
                ScriptedResponse(
                    json={
                        "data": [
                            {"id": 4, "subscription_url": WEBHOOK_URL},
                            {"id": 9, "subscription_url": WEBHOOK_URL},
                            {"id": 5, "subscription_url": "https://someone-else.example.com/hook"},
                        ]
                    }
                ),
                ScriptedResponse(json={"success": True}),
            ]
        ) as network:
            result = create_webhook("acme", "token", WEBHOOK_URL)

        assert result.success is True
        assert [request.url for request in network.requests_log if request.method == "DELETE"] == [
            "https://acme.pipedrive.com/api/v1/webhooks/4"
        ]

    def test_create_succeeds_even_if_cleanup_fails(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=201, json={"success": True, "data": {"id": 9}}), ScriptedResponse(status=403)]
        ) as network:
            result = create_webhook("acme", "token", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs["http_auth_password"]
        assert [request.method for request in network.requests_log] == ["POST", "GET"]

    @pytest.mark.parametrize(
        "status, expected_fragment",
        [
            (401, "rejected the API token"),
            (403, "rejected the API token"),
            (500, "Pipedrive API error (500)"),
        ],
    )
    def test_create_maps_api_failures_to_an_actionable_error(self, status: int, expected_fragment: str) -> None:
        with scripted_network([ScriptedResponse(status=status, json={"success": False})]) as network:
            result = create_webhook("acme", "token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and expected_fragment in result.error
        assert [request.method for request in network.requests_log] == ["POST"]

    def test_create_rejects_an_invalid_company_domain(self) -> None:
        with scripted_network([]) as network:
            result = create_webhook("evil.example.com", "token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "Invalid Pipedrive company domain" in result.error
        assert network.requests_log == []

    def test_delete_removes_only_our_subscriptions(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {"id": 1, "subscription_url": WEBHOOK_URL},
                            {"id": 2, "subscription_url": "https://someone-else.example.com/hook"},
                            {"id": 3, "subscription_url": WEBHOOK_URL},
                        ]
                    }
                ),
                ScriptedResponse(json={"success": True}),
                ScriptedResponse(json={"success": True}),
            ]
        ) as network:
            result = delete_webhook("acme", "token", WEBHOOK_URL)

        assert result.success is True
        deleted_urls = [request.url for request in network.requests_log if request.method == "DELETE"]
        assert deleted_urls == [
            "https://acme.pipedrive.com/api/v1/webhooks/1",
            "https://acme.pipedrive.com/api/v1/webhooks/3",
        ]

    def test_delete_succeeds_when_the_webhook_is_already_gone(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": None})]) as network:
            result = delete_webhook("acme", "token", WEBHOOK_URL)

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_external_info_reports_the_registered_subscription(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {
                                "id": 1,
                                "subscription_url": WEBHOOK_URL,
                                "event_action": "*",
                                "event_object": "*",
                                "is_active": 1,
                                "add_time": "2026-05-01 10:00:00",
                                "name": "PostHog data warehouse",
                            }
                        ]
                    }
                )
            ]
        ) as network:
            info = get_external_webhook_info("acme", "token", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["*.*"]
        assert info.status == "active"
        assert info.created_at == "2026-05-01 10:00:00"
        assert [request.path for request in network.requests_log] == ["/api/v1/webhooks"]

    def test_external_info_reports_a_missing_subscription(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": [{"id": 1, "subscription_url": "https://other/hook"}]})]):
            info = get_external_webhook_info("acme", "token", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is None

    def test_external_info_surfaces_an_api_failure(self) -> None:
        with scripted_network([ScriptedResponse(status=403, json={})]):
            info = get_external_webhook_info("acme", "token", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None and "rejected the API token" in info.error


def _delivery(entity_id: int, action: str, timestamp: str, **fields: Any) -> dict[str, Any]:
    return {
        "meta": {"action": action, "entity": "deal", "version": "2.0", "timestamp": timestamp},
        "data": {"id": entity_id, **fields},
        "previous": {},
    }


class TestWebhookTableTransformer:
    def test_keeps_only_the_latest_delivery_per_id(self) -> None:
        # Delta merge dedupes across syncs but not within one batch, so a create followed by a
        # change for the same deal would otherwise merge the same primary key twice.
        table = table_from_py_list(
            [
                _delivery(1, "create", "2026-05-01T10:00:00.000Z", title="Draft"),
                _delivery(1, "change", "2026-05-01T10:05:00.000Z", title="Renewal"),
                _delivery(2, "create", "2026-05-01T10:01:00.000Z", title="Other"),
            ]
        )

        rows = sorted(_webhook_table_transformer(table).to_pylist(), key=lambda row: row["id"])

        assert rows == [{"id": 1, "title": "Renewal"}, {"id": 2, "title": "Other"}]

    def test_drops_deletions_and_rows_without_an_id(self) -> None:
        table = table_from_py_list(
            [
                _delivery(1, "delete", "2026-05-01T10:00:00.000Z", title="Gone"),
                {"meta": {"action": "create", "entity": "deal"}, "data": {"title": "No id"}, "previous": {}},
                _delivery(2, "create", "2026-05-01T10:01:00.000Z", title="Kept"),
            ]
        )

        assert _webhook_table_transformer(table).to_pylist() == [{"id": 2, "title": "Kept"}]

    def test_empty_batch_yields_no_rows(self) -> None:
        assert _webhook_table_transformer(table_from_py_list([])).num_rows == 0


class TestWebhookSourceWiring:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_webhook_sync_reads_pushed_rows_instead_of_polling(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], {"next_cursor": None})])
        webhook_manager = _webhook_manager(enabled=True)

        response = _source("deals", _make_manager(), webhook_manager)
        items = response.items()

        assert items is webhook_manager.get_items.return_value
        assert webhook_manager.get_items.call_args.kwargs["table_transformer"] is _webhook_table_transformer
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_poll_still_runs_when_webhook_sync_is_off(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], {"next_cursor": None})])
        webhook_manager = _webhook_manager(enabled=False)

        rows = _rows(_source("deals", _make_manager(), webhook_manager))

        assert rows == [{"id": 1}]
        webhook_manager.get_items.assert_not_called()
