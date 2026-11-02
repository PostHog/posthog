import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.agilecrm import (
    AgileCRMResumeConfig,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import AGILECRM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.source import AgileCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.agilecrm import (
    AgileCRMSourceConfig,
)

PAGE_SIZE = AGILECRM_ENDPOINTS["contacts"].page_size


def _driver() -> SourceDriver:
    return SourceDriver(AgileCRMSource(), AgileCRMSourceConfig(domain="acme", email="a@b.com", api_key="key"))


def _page(rows: object) -> ScriptedResponse:
    return ScriptedResponse(json=rows)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("simple", "acme", "https://acme.agilecrm.com/dev/api"),
            ("with_hyphen", "my-company", "https://my-company.agilecrm.com/dev/api"),
            ("trims_whitespace", "  acme  ", "https://acme.agilecrm.com/dev/api"),
        ]
    )
    def test_valid_domains(self, _name: str, domain: str, expected: str) -> None:
        assert base_url(domain) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            # A `#`/`/`/`.` in the domain could break out of the agilecrm.com host and retarget the
            # basic-auth credentials at an attacker-controlled server, so these must be rejected.
            ("fragment_breakout", "evil.com#"),
            ("slash_breakout", "evil.com/"),
            ("dotted", "evil.com"),
            ("at_breakout", "user@evil.com"),
        ]
    )
    def test_invalid_domains_rejected(self, _name: str, domain: str) -> None:
        with pytest.raises(ValueError):
            base_url(domain)


class TestPagination:
    def test_paginates_until_short_page(self) -> None:
        first_page = [{"id": i} for i in range(PAGE_SIZE - 1)] + [{"id": PAGE_SIZE, "cursor": "CURSOR1"}]
        second_page = [{"id": 9001}]  # short page -> terminal
        result = _driver().run("contacts", [_page(first_page), _page(second_page)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        # First request has no cursor; the second carries the cursor from the last item of page one.
        assert result.params("cursor") == [None, "CURSOR1"]
        assert result.params("page_size") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # The cursor is navigation metadata and must never leak into the warehouse rows.
        assert all("cursor" not in row for row in result.rows)
        # Checkpoint saved after the first page (points at the next page); the short page ends it.
        assert result.saved_states == [AgileCRMResumeConfig(cursor="CURSOR1")]

    def test_stops_when_full_page_has_no_cursor(self) -> None:
        # A full page whose last item carries no cursor must terminate rather than loop forever.
        full_page_no_cursor = [{"id": i} for i in range(PAGE_SIZE)]
        result = _driver().run("contacts", [_page(full_page_no_cursor)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_stops_on_short_page_even_with_cursor(self) -> None:
        # A short page is terminal even if its last item still carries a cursor.
        short_page = [{"id": 1}, {"id": 2, "cursor": "DANGLING"}]
        result = _driver().run("contacts", [_page(short_page)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        assert len(result.requests) == 1
        assert all("cursor" not in row for row in result.rows)
        assert result.saved_states == []

    def test_resume_uses_saved_cursor(self) -> None:
        result = _driver().run("contacts", [_page([{"id": 1}])], resume_state=AgileCRMResumeConfig(cursor="SAVED"))

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.params("cursor") == ["SAVED"]

    def test_non_list_body_raises_loudly(self) -> None:
        # A 200 object body means the response shape changed — fail loud, not silently mis-sync.
        result = _driver().run("contacts", [_page({"error": "something went wrong"})])

        assert isinstance(result.raised, ValueError)
        assert "Required a list response body" in str(result.raised)


class TestTickets:
    def test_lists_via_all_tickets_filter(self) -> None:
        # The default filter list has "All Tickets" second — listing must resolve it, not grab the first.
        filters = [
            {"id": 1, "name": "New Tickets", "is_default_filter": True},
            {"id": 2, "name": "All Tickets", "is_default_filter": True},
        ]
        tickets_page = [{"id": 100, "subject": "x", "cursor": "C"}]  # short page -> terminal
        result = _driver().run("tickets", [_page(filters), _page(tickets_page)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [100]
        assert all("cursor" not in row for row in result.rows)
        assert result.paths[1] == "/dev/api/tickets/filter"
        assert result.requests[1].param("filter_id") == "2"
        assert result.requests[1].param("global_sort_key") == "-last_updated_time"

    def test_no_filters_yields_nothing(self) -> None:
        # Without a saved filter there is no way to list tickets, so the table stays empty.
        result = _driver().run("tickets", [_page([])])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1


class TestFanout:
    def test_contact_notes_inject_parent_id(self) -> None:
        contacts_page = [{"id": 1}, {"id": 2}]  # short page -> terminal
        notes_1 = [{"id": 10, "subject": "a"}]
        notes_2 = [{"id": 11, "subject": "b", "cursor": "X"}]
        result = _driver().run("contact_notes", [_page(contacts_page), _page(notes_1), _page(notes_2)])

        # Each note carries the id of the contact it was fetched for (part of the composite key), and
        # the navigation cursor never leaks into a row.
        assert result.raised is None
        assert result.rows == [
            {"id": 10, "subject": "a", "contact_id": 1},
            {"id": 11, "subject": "b", "contact_id": 2},
        ]
        assert result.paths[1:] == ["/dev/api/contacts/1/notes", "/dev/api/contacts/2/notes"]

    def test_ticket_notes_fan_out_over_tickets(self) -> None:
        # Parent enumeration for ticket messages goes through the ticket filter, then per-ticket notes.
        filters = [{"id": 2, "name": "All Tickets", "is_default_filter": True}]
        tickets_page = [{"id": 5}]  # short page -> terminal
        messages = [{"id": 50, "ticket_id": 5, "plain_text": "hi"}]
        result = _driver().run("ticket_notes", [_page(filters), _page(tickets_page), _page(messages)])

        assert result.raised is None
        assert result.rows == [{"id": 50, "ticket_id": 5, "plain_text": "hi"}]
        assert result.paths[2] == "/dev/api/tickets/notes/5"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("acme", "a@b.com", "key") is expected

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/dev/api/contacts"
        assert network.requests_log[0].param("page_size") == "1"

    def test_invalid_domain_short_circuits_to_false(self) -> None:
        # An invalid domain must fail before any request is attempted.
        with scripted_network([]) as network:
            assert validate_credentials("evil.com#", "a@b.com", "key") is False

        assert network.requests_log == []
        assert network.session_options == []
