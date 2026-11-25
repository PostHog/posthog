from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.sources.moxie import moxie as moxie_module
from products.warehouse_sources.sources.moxie._config import MoxieSourceConfig
from products.warehouse_sources.sources.moxie.moxie import (
    MoxieHostNotAllowedError,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.sources.moxie.source import MoxieSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route, scripted_network

BASE_URL = "https://pod00.withmoxie.dev/api/public"


class _RecordingPacer:
    def __init__(self, per_second: float, hold_seconds: float) -> None:
        self.per_second = per_second
        self.turns = 0
        self.throttles: list[Optional[float]] = []

    def wait_turn(self) -> None:
        self.turns += 1

    def throttled(self, retry_after: Optional[float]) -> None:
        self.throttles.append(retry_after)


@pytest.fixture
def pacers() -> Any:
    created: list[_RecordingPacer] = []

    def build(per_second: float, hold_seconds: float) -> _RecordingPacer:
        pacer = _RecordingPacer(per_second, hold_seconds)
        created.append(pacer)
        return pacer

    with mock.patch.object(moxie_module, "RequestPacer", side_effect=build):
        yield created


def _driver(base_url: str = BASE_URL) -> SourceDriver:
    return SourceDriver(MoxieSource(), MoxieSourceConfig(base_url=base_url, api_key="test_key"))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://pod00.withmoxie.dev/api/public", "https://pod00.withmoxie.dev/api/public"),
            ("https://pod00.withmoxie.dev/api/public/", "https://pod00.withmoxie.dev/api/public"),
            ("pod00.withmoxie.dev", "https://pod00.withmoxie.dev/api/public"),
            ("http://pod00.withmoxie.dev", "http://pod00.withmoxie.dev/api/public"),
            ("  https://pod00.withmoxie.dev/api/public  ", "https://pod00.withmoxie.dev/api/public"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalizes_variants(self, raw: str | None, expected: str) -> None:
        assert normalize_base_url(raw) == expected


class TestMoxieTransport:
    @pytest.mark.parametrize("endpoint", ["email_templates", "invoice_templates", "vendor_names", "form_names"])
    def test_scalar_endpoints_wrap_bare_strings_into_rows(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=["Template A", "Template B"])])

        assert result.raised is None
        assert result.items == [[{"name": "Template A"}, {"name": "Template B"}]]

    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("tasks", "/api/public/action/tasks/list"),
            ("tickets", "/api/public/action/tickets/list"),
            ("agreements", "/api/public/action/agreements/search"),
            ("opportunities", "/api/public/action/opportunities/search"),
        ],
    )
    def test_object_endpoints_request_documented_path_and_pass_rows_through(self, endpoint: str, path: str) -> None:
        row = {"id": "abc123", "created": "2024-01-02T03:04:05Z"}
        result = _driver().run(endpoint, [ScriptedResponse(json=[row])])

        assert result.raised is None
        assert result.paths == [path]
        assert result.items == [[row]]

    def test_opportunities_include_archived(self) -> None:
        result = _driver().run("opportunities", [ScriptedResponse(json=[{"id": "o1", "archive": True}])])

        assert result.raised is None
        assert result.params("includeArchived") == ["true"]

    def test_ticket_comments_fan_out_over_tickets_and_follow_the_cursor(self, pacers: Any) -> None:
        result = _driver().run(
            "ticket_comments",
            route(
                {
                    "/action/tickets/list": [ScriptedResponse(json=[{"id": "t1"}, {"id": "t2"}, {"id": "t3"}])],
                    "/action/tickets/comments/list": [
                        ScriptedResponse(
                            json={"comments": [{"id": "c1", "ticketId": "t1"}], "nextCursor": "n1", "hasMore": True}
                        ),
                        ScriptedResponse(
                            json={"comments": [{"id": "c2", "ticketId": "t1"}], "nextCursor": None, "hasMore": False}
                        ),
                        # A ticket deleted after the ticket listing.
                        ScriptedResponse(status=404, json={"status": 404, "error": "Not Found"}),
                        ScriptedResponse(json={"comments": [], "nextCursor": None, "hasMore": False}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2"]
        comment_requests = [query for path, query in zip(result.paths, result.queries) if "comments" in path]
        assert [query["ticketId"] for query in comment_requests] == [("t1",), ("t1",), ("t2",), ("t3",)]
        assert [query.get("cursor") for query in comment_requests] == [None, ("n1",), None, None]
        assert all(query["commentType"] == ("ALL",) and query["limit"] == ("100",) for query in comment_requests)

    def test_ticket_comments_stop_on_a_repeated_cursor(self, pacers: Any) -> None:
        page = ScriptedResponse(json={"comments": [], "nextCursor": "same", "hasMore": True})
        result = _driver().run(
            "ticket_comments",
            route(
                {
                    "/action/tickets/list": [ScriptedResponse(json=[{"id": "t1"}])],
                    "/action/tickets/comments/list": [page, page, page],
                }
            ),
        )

        assert isinstance(result.raised, ValueError)
        assert "repeated cursor" in str(result.raised)

    def test_ticket_comments_resume_after_the_last_finished_ticket(self, pacers: Any) -> None:
        tickets = ScriptedResponse(json=[{"id": "t1"}, {"id": "t2"}])
        t1_comments = ScriptedResponse(
            json={"comments": [{"id": "c1", "ticketId": "t1"}], "nextCursor": None, "hasMore": False}
        )
        first = _driver().run(
            "ticket_comments",
            route(
                {
                    "/action/tickets/list": [tickets],
                    "/action/tickets/comments/list": [t1_comments, ScriptedResponse(status=400, json={})],
                }
            ),
        )
        assert first.raised is not None
        assert first.committed_states

        second = _driver().run(
            "ticket_comments",
            route(
                {
                    "/action/tickets/list": [tickets],
                    "/action/tickets/comments/list": [
                        ScriptedResponse(
                            json={"comments": [{"id": "c2", "ticketId": "t2"}], "nextCursor": None, "hasMore": False}
                        )
                    ],
                }
            ),
            resume_state=first.committed_states[-1],
        )

        assert second.raised is None
        assert [row["id"] for row in second.rows] == ["c2"]
        assert [query["ticketId"] for path, query in zip(second.paths, second.queries) if "comments" in path] == [
            ("t2",)
        ]

    def test_project_notes_fan_out_over_projects(self, pacers: Any) -> None:
        result = _driver().run(
            "project_notes",
            route(
                {
                    "/action/projects/search": [ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}])],
                    "/action/projects/notes/search": [
                        ScriptedResponse(json=[{"id": "n1", "projectId": "p1"}, {"id": "n2", "projectId": "p1"}]),
                        ScriptedResponse(json=[]),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["n1", "n2"]
        assert result.params("projectId") == [None, "p1", "p2"]

    @pytest.mark.parametrize(
        "headers, reported", [({"Retry-After": "7"}, 7.0), ({}, None)], ids=["retry_after", "no_header"]
    )
    def test_fan_out_paces_every_request_and_reports_a_429(
        self, pacers: list[_RecordingPacer], headers: dict[str, str], reported: Optional[float]
    ) -> None:
        result = _driver().run(
            "project_notes",
            route(
                {
                    "/action/projects/search": [ScriptedResponse(json=[{"id": "p1"}])],
                    "/action/projects/notes/search": [
                        ScriptedResponse(status=429, headers=headers),
                        ScriptedResponse(json=[{"id": "n1", "projectId": "p1"}]),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["n1"]
        assert len(pacers) == 1
        assert pacers[0].per_second * 300 < 100
        assert pacers[0].turns == len(result.requests) == 3
        assert pacers[0].throttles == [reported]

    def test_time_entries_under_the_cap_take_one_unbounded_call(self) -> None:
        rows = [{"id": "e1", "timerStart": "2024-01-01T09:00:00Z"}]
        result = _driver().run("time_entries", [ScriptedResponse(json=rows)])

        assert result.raised is None
        assert result.paths == ["/api/public/action/timeWorked/list"]
        assert result.queries == [{}]
        assert result.rows == rows

    def test_time_entries_at_the_cap_switch_to_timer_start_windows(self) -> None:
        capped = [{"id": "e1"}, {"id": "e2"}]
        with mock.patch.object(moxie_module, "TIME_ENTRIES_ROW_CAP", 2):
            result = _driver().run(
                "time_entries",
                [
                    ScriptedResponse(json=capped),
                    ScriptedResponse(json=[]),
                    ScriptedResponse(json=[{"id": "e1"}]),
                    ScriptedResponse(json=[{"id": "e2"}]),
                ],
            )

        assert result.raised is None
        assert result.rows == [{"id": "e1"}, {"id": "e2"}]
        upper = result.params("earliest")[3]
        assert upper is not None and datetime.fromisoformat(upper) > datetime.now(UTC)
        assert result.params("earliest") == [None, None, "2000-01-01T00:00:00Z", upper]
        assert result.params("latest") == [None, "2000-01-01T00:00:00Z", upper, None]

    def test_workspace_users_flattens_nested_user_id(self) -> None:
        row = {"userType": "OWNER", "user": {"userId": 42, "firstName": "Alex"}}
        result = _driver().run("workspace_users", [ScriptedResponse(json=[row])])

        assert result.raised is None
        assert result.items == [[{**row, "user_id": 42}]]

    def test_host_check_blocks_before_any_request(self) -> None:
        with mock.patch.object(moxie_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("clients", [])

        assert isinstance(result.raised, MoxieHostNotAllowedError)
        assert "internal address" in str(result.raised)
        assert result.requests == []

    def test_plaintext_http_is_rejected_before_any_request(self) -> None:
        result = _driver(base_url="http://pod00.withmoxie.dev/api/public").run("clients", [])

        assert isinstance(result.raised, MoxieHostNotAllowedError)
        assert "HTTPS" in str(result.raised)
        assert result.requests == []


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _fake_time_entries_api(
    entries: list[dict[str, Any]], cap: int
) -> tuple[Any, list[Optional[moxie_module.TimeWindow]]]:
    """Answer like List Time Entries: inclusive `timerStart` bounds, at most `cap` rows, no order."""
    calls: list[Optional[moxie_module.TimeWindow]] = []

    def fetch(window: Optional[moxie_module.TimeWindow]) -> list[dict[str, Any]]:
        calls.append(window)
        matching = [
            entry
            for entry in entries
            if window is None
            or (
                (window.earliest is None or window.earliest <= datetime.fromisoformat(entry["timerStart"]))
                and (window.latest is None or datetime.fromisoformat(entry["timerStart"]) <= window.latest)
            )
        ]
        return list(reversed(matching))[:cap]

    return fetch, calls


def _entry(entry_id: str, start: datetime) -> dict[str, Any]:
    return {"id": entry_id, "timerStart": start.isoformat()}


class TestIterTimeEntries:
    def test_splits_capped_windows_and_reads_each_entry_once(self) -> None:
        first_window = moxie_module.TimeWindow(
            earliest=moxie_module.TIME_ENTRIES_EARLIEST, latest=NOW + timedelta(days=366)
        )
        halves = moxie_module._split(first_window)
        assert halves is not None
        boundary = halves[0].latest
        assert boundary is not None
        entries = [
            # Outside the split range, so only the open-ended edge windows return them.
            _entry("before", datetime(1995, 5, 1, tzinfo=UTC)),
            _entry("after", NOW + timedelta(days=800)),
            _entry("a", datetime(2001, 5, 1, tzinfo=UTC)),
            _entry("b", datetime(2010, 5, 1, tzinfo=UTC)),
            # On the shared bound of two windows, so both calls return it.
            _entry("c", boundary),
            _entry("d", datetime(2020, 5, 1, tzinfo=UTC)),
            _entry("e", datetime(2025, 5, 1, tzinfo=UTC)),
        ]
        fetch, calls = _fake_time_entries_api(entries, cap=3)

        with mock.patch.object(moxie_module, "TIME_ENTRIES_ROW_CAP", 3):
            pages = list(moxie_module.iter_time_entries(fetch, NOW))

        ids = [row["id"] for page in pages for row in page]
        assert sorted(ids) == ["a", "after", "b", "before", "c", "d", "e"]
        assert calls[0] is None
        assert calls[1] == moxie_module.TimeWindow(earliest=None, latest=moxie_module.TIME_ENTRIES_EARLIEST)
        assert calls[2] == first_window
        assert calls[-1] == moxie_module.TimeWindow(earliest=first_window.latest, latest=None)

    def test_a_capped_window_that_cannot_split_fails_instead_of_dropping_rows(self) -> None:
        instant = datetime(2024, 3, 3, 12, 0, 0, tzinfo=UTC)
        entries = [_entry(entry_id, instant) for entry_id in ("x", "y", "z")]
        fetch, calls = _fake_time_entries_api(entries, cap=3)

        with mock.patch.object(moxie_module, "TIME_ENTRIES_ROW_CAP", 3):
            with pytest.raises(moxie_module.MoxieTimeEntriesCapError):
                list(moxie_module.iter_time_entries(fetch, NOW))

        # About 30 halvings reach one second from the first window, with at most two calls each.
        assert len(calls) <= 64

    @pytest.mark.parametrize("rows", [[], [{"id": "only", "timerStart": "2024-01-01T00:00:00+00:00"}]])
    def test_under_the_cap_yields_the_single_call(self, rows: list[dict[str, Any]]) -> None:
        fetch, calls = _fake_time_entries_api(rows, cap=10)

        pages = list(moxie_module.iter_time_entries(fetch, NOW))

        assert pages == ([rows] if rows else [])
        assert calls == [None]


class TestValidateCredentials:
    def test_probes_clients_list_with_api_key_header_and_redaction(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(BASE_URL, "test_key", team_id=1)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == f"{BASE_URL}/action/clients/list"
        assert network.requests_log[0].headers["x-api-key"] == "test_key"
        # The key must be registered for redaction in tracked telemetry.
        assert network.session_options[0]["redact_values"] == ("test_key",)

    def test_blank_base_url_is_rejected(self) -> None:
        is_valid, message = validate_credentials("", "test_key", team_id=1)
        assert is_valid is False
        assert message == "That doesn't look like a Moxie workspace base URL."

    def test_plaintext_http_is_rejected_before_any_request(self) -> None:
        is_valid, message = validate_credentials("http://pod00.withmoxie.dev/api/public", "test_key", team_id=1)
        assert is_valid is False
        assert message is not None and "HTTPS" in message

    def test_host_not_allowed_is_rejected(self) -> None:
        with mock.patch.object(moxie_module, "_is_host_safe", return_value=(False, "internal address")):
            is_valid, message = validate_credentials(BASE_URL, "test_key", team_id=1)
        assert is_valid is False
        assert message == "internal address"
