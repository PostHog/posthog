import re
import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response
from requests.exceptions import ProxyError, RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp import (
    MailchimpPaginator,
    MailchimpResumeConfig,
    _fetch_contacts_for_list,
    _format_incremental_value,
    _get_contacts_iterator,
    _get_endpoint_iterator,
    _incremental_query_params,
    extract_data_center,
    mailchimp_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.settings import MAILCHIMP_ENDPOINTS


class TestExtractDataCenter:
    def test_basic_key(self):
        assert extract_data_center("abc123def456-us6") == "us6"

    def test_multiple_dashes(self):
        assert extract_data_center("abc-def-ghi-us10") == "us10"

    def test_invalid_key_raises(self):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center("invalidkey")

    @pytest.mark.parametrize(
        "malicious_key",
        [
            "key-evil.com/#",
            "key-evil.com/path",
            "key-us6.attacker.com",
            "key-dc:8080",
            "key-",
            "key- spaces",
        ],
    )
    def test_malicious_dc_values_raise(self, malicious_key):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center(malicious_key)


class TestValidateCredentials:
    def test_success(self, monkeypatch):
        get_mock = MagicMock(return_value=_make_http_response({}, status_code=200))
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(get_mock)})(),
        )
        assert validate_credentials("key-us6") == (True, None)

    def test_invalid_api_key_format_is_surfaced(self):
        valid, error = validate_credentials("invalidkey")
        assert valid is False
        assert error is not None and "Invalid Mailchimp API key format" in error

    @pytest.mark.parametrize(
        "exception",
        [
            ProxyError("Cannot connect to proxy.", OSError("Tunnel connection failed: 502 Bad gateway")),
            RequestException("connection reset"),
        ],
    )
    def test_network_errors_return_friendly_message_without_raw_details(self, monkeypatch, exception):
        get_mock = MagicMock(side_effect=exception)
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(get_mock)})(),
        )

        valid, error = validate_credentials("key-us6")

        assert valid is False
        assert error == "Could not reach the Mailchimp API. Check your network connection and try again."


class TestFormatIncrementalValue:
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 45)
        result = _format_incremental_value(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_date(self):
        d = date(2024, 1, 15)
        result = _format_incremental_value(d)
        assert result == "2024-01-15T00:00:00+00:00"

    def test_string(self):
        assert _format_incremental_value("2024-01-15") == "2024-01-15"


class TestMailchimpPaginator:
    def test_initial_state(self):
        paginator = MailchimpPaginator(page_size=100)
        assert paginator._page_size == 100
        assert paginator._offset == 0

    def test_update_state_has_more(self):
        paginator = MailchimpPaginator(page_size=100)
        response = MagicMock()
        response.json.return_value = {"total_items": 250, "lists": []}
        paginator.update_state(response)
        assert paginator._offset == 100
        assert paginator._has_next_page is True

    def test_update_state_no_more(self):
        paginator = MailchimpPaginator(page_size=100)
        paginator._offset = 200
        response = MagicMock()
        response.json.return_value = {"total_items": 250, "lists": []}
        paginator.update_state(response)
        assert paginator._offset == 300
        assert paginator._has_next_page is False

    @pytest.mark.parametrize(
        ("label", "seeded_offset"),
        [
            ("fresh", None),
            ("resumed", 2000),
        ],
    )
    def test_init_request_sets_offset_and_count(self, label: str, seeded_offset: int | None) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        if seeded_offset is not None:
            paginator.set_resume_state({"offset": seeded_offset})

        request = Request(method="GET", url="https://us6.api.mailchimp.com/3.0/lists")
        paginator.init_request(request)

        assert request.params["count"] == 1000
        assert request.params["offset"] == (seeded_offset if seeded_offset is not None else 0)

    def test_get_resume_state_returns_current_offset(self) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        response = MagicMock()
        response.json.return_value = {"total_items": 3000}
        paginator.update_state(response)  # _offset advances to 1000

        assert paginator.get_resume_state() == {"offset": 1000}

    def test_set_resume_state_round_trip(self) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        paginator.set_resume_state({"offset": 5000})

        assert paginator._offset == 5000
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"offset": 5000}

    def test_set_resume_state_ignores_missing_offset(self) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        paginator.set_resume_state({})

        assert paginator._offset == 0


def _fake_manager(*, can_resume: bool = False, load_state: MailchimpResumeConfig | None = None) -> MagicMock:
    """Build a ResumableSourceManager test double matching the protocol used by the loop."""
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = load_state
    return manager


def _build_response(members: list[dict[str, Any]], total_items: int) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"members": members, "total_items": total_items}
    response.raise_for_status.return_value = None
    return response


class TestFetchContactsForList:
    @pytest.mark.parametrize(
        ("label", "start_offset", "members", "total_items", "expected_ids", "expected_checkpoint"),
        [
            (
                "fresh_page_checkpoints_at_offset_zero",
                0,
                [{"id": "m1"}, {"id": "m2"}],
                2,
                ["m1", "m2"],
                MailchimpResumeConfig(list_id="list_a", offset=0),
            ),
            (
                "resume_page_checkpoints_at_start_offset",
                1000,
                [{"id": "m3"}],
                1001,
                ["m3"],
                MailchimpResumeConfig(list_id="list_a", offset=1000),
            ),
            (
                "empty_page_is_not_checkpointed",
                0,
                [],
                0,
                [],
                None,
            ),
        ],
    )
    def test_single_page_behaviour(
        self,
        monkeypatch,
        label: str,
        start_offset: int,
        members: list[dict[str, Any]],
        total_items: int,
        expected_ids: list[str],
        expected_checkpoint: MailchimpResumeConfig | None,
    ) -> None:
        manager = _fake_manager()
        get_mock = MagicMock(side_effect=[_build_response(members, total_items=total_items)])
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(get_mock)})(),
        )

        emitted = list(
            _fetch_contacts_for_list(
                api_key="key-us6",
                dc="us6",
                list_id="list_a",
                since_last_changed=None,
                resumable_source_manager=manager,
                start_offset=start_offset,
            )
        )

        assert [c["id"] for c in emitted] == expected_ids
        assert all(c["list_id"] == "list_a" for c in emitted)
        assert get_mock.call_args.kwargs["params"]["offset"] == start_offset

        if expected_checkpoint is None:
            manager.save_state.assert_not_called()
        else:
            manager.save_state.assert_called_once_with(expected_checkpoint)

    def test_multi_page_advances_offset_and_checkpoints_each_page(self, monkeypatch) -> None:
        # total_items=2001 with page_size=1000 → pages at offsets 0, 1000, 2000.
        # After the third page, offset becomes 3000 and the `offset >= total_items` guard terminates the loop.
        manager = _fake_manager()
        responses = [_build_response([{"id": f"m{i}"}], total_items=2001) for i in range(3)]
        get_mock = MagicMock(side_effect=responses)
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(get_mock)})(),
        )

        emitted = list(
            _fetch_contacts_for_list(
                api_key="key-us6",
                dc="us6",
                list_id="list_a",
                since_last_changed=None,
                resumable_source_manager=manager,
                start_offset=0,
            )
        )

        assert [c["id"] for c in emitted] == ["m0", "m1", "m2"]
        assert [call.kwargs["params"]["offset"] for call in get_mock.call_args_list] == [0, 1000, 2000]
        assert manager.save_state.call_args_list == [
            ((MailchimpResumeConfig(list_id="list_a", offset=0),),),
            ((MailchimpResumeConfig(list_id="list_a", offset=1000),),),
            ((MailchimpResumeConfig(list_id="list_a", offset=2000),),),
        ]


class TestGetContactsIterator:
    @pytest.mark.parametrize(
        (
            "label",
            "can_resume",
            "load_state",
            "list_ids",
            "page_by_list_offset",
            "expected_emitted",
            "expected_visits",
            "expected_checkpoints",
            "load_state_called",
        ),
        [
            (
                "fresh_run_iterates_all_lists",
                False,
                None,
                ["list_a", "list_b"],
                {
                    ("list_a", 0): ([{"id": "a1"}], 1),
                    ("list_b", 0): ([{"id": "b1"}], 1),
                },
                [("list_a", "a1"), ("list_b", "b1")],
                [("list_a", 0), ("list_b", 0)],
                [
                    MailchimpResumeConfig(list_id="list_a", offset=0),
                    MailchimpResumeConfig(list_id="list_b", offset=0),
                ],
                False,
            ),
            (
                "resume_skips_prior_lists_and_starts_mid_list",
                True,
                MailchimpResumeConfig(list_id="list_b", offset=1000),
                ["list_a", "list_b", "list_c"],
                {
                    ("list_b", 1000): ([{"id": "b2"}], 1001),
                    ("list_c", 0): ([{"id": "c1"}], 1),
                },
                [("list_b", "b2"), ("list_c", "c1")],
                [("list_b", 1000), ("list_c", 0)],
                [
                    MailchimpResumeConfig(list_id="list_b", offset=1000),
                    MailchimpResumeConfig(list_id="list_c", offset=0),
                ],
                True,
            ),
            (
                "resume_falls_back_to_fresh_when_list_id_missing",
                True,
                MailchimpResumeConfig(list_id="gone", offset=500),
                ["list_a"],
                {
                    ("list_a", 0): ([{"id": "a1"}], 1),
                },
                [("list_a", "a1")],
                [("list_a", 0)],
                [MailchimpResumeConfig(list_id="list_a", offset=0)],
                True,
            ),
        ],
    )
    def test_iteration(
        self,
        monkeypatch,
        label: str,
        can_resume: bool,
        load_state: MailchimpResumeConfig | None,
        list_ids: list[str],
        page_by_list_offset: dict[tuple[str, int], tuple[list[dict[str, Any]], int]],
        expected_emitted: list[tuple[str, str]],
        expected_visits: list[tuple[str, int]],
        expected_checkpoints: list[MailchimpResumeConfig],
        load_state_called: bool,
    ) -> None:
        manager = _fake_manager(can_resume=can_resume, load_state=load_state)
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp._fetch_all_lists",
            lambda api_key, dc: [{"id": lid} for lid in list_ids],
        )
        visited: list[tuple[str, int]] = []

        def fake_get(url, **kwargs):
            offset = kwargs["params"]["offset"]
            for lid in list_ids:
                if f"/lists/{lid}/members" in url:
                    visited.append((lid, offset))
                    members, total_items = page_by_list_offset.get((lid, offset), ([], 0))
                    return _build_response(members, total_items=total_items)
            raise AssertionError(f"unexpected url={url}")

        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(fake_get)})(),
        )

        emitted = list(_get_contacts_iterator(api_key="key-us6", resumable_source_manager=manager))

        assert [(c["list_id"], c["id"]) for c in emitted] == expected_emitted
        assert visited == expected_visits
        assert manager.save_state.call_args_list == [((cp,),) for cp in expected_checkpoints]
        if load_state_called:
            manager.load_state.assert_called_once()
        else:
            manager.load_state.assert_not_called()


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestRestEndpointResumeBehavior:
    """End-to-end resume behaviour of the shared ``rest_api_resource`` path used
    for ``lists``/``campaigns``/``reports`` (offset/count pagination)."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``mailchimp_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` is a list
        of shallow copies of ``request.params`` captured at send-time — the
        underlying Request object is mutated in-place by the paginator between
        pages, so we can't rely on mock ``call_args_list`` to preserve history.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params))
            return next(response_iter)

        # The REST path builds its own capture-disabled session in mailchimp_source and passes it
        # into the config, so patch it at that origin rather than inside rest_client.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = mailchimp_source(
                api_key="key-us6",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            # SourceResponse.items is Iterable | AsyncIterable; the REST path is sync.
            list(cast(Iterable[Any], response.items()))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        data_key = endpoint  # lists/campaigns/reports all use their own name as data_selector
        responses = [
            _make_http_response({data_key: [{"id": "a"}], "total_items": 2500}),
            _make_http_response({data_key: [{"id": "b"}], "total_items": 2500}),
            _make_http_response({data_key: [{"id": "c"}], "total_items": 2500}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        assert [p["offset"] for p in sent_params] == [0, 1000, 2000]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MailchimpResumeConfig(offset=1000),
            MailchimpResumeConfig(offset=2000),
        ]

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_resume_seeds_paginator_with_saved_offset(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MailchimpResumeConfig(offset=2000)

        data_key = endpoint
        responses = [
            _make_http_response({data_key: [{"id": "c"}], "total_items": 2500}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        assert [p["offset"] for p in sent_params] == [2000]

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_terminal_single_page_does_not_save_state(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        data_key = endpoint
        responses = [
            _make_http_response({data_key: [{"id": "only"}], "total_items": 1}),
        ]
        self._drive(endpoint, manager, responses)

        manager.save_state.assert_not_called()

    def test_saved_state_with_zero_offset_is_ignored(self) -> None:
        # A zero-offset checkpoint is equivalent to a fresh run — don't seed.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MailchimpResumeConfig(offset=0)

        responses = [
            _make_http_response({"lists": [{"id": "a"}], "total_items": 1}),
        ]
        _, sent_params = self._drive("lists", manager, responses)

        assert [p["offset"] for p in sent_params] == [0]

    def test_saved_state_serialization_round_trip_with_list_id_absent(self) -> None:
        # REST-endpoint checkpoints omit list_id; ensure ResumableSourceManager's
        # asdict/json round trip reproduces the dataclass unchanged.
        import dataclasses

        cfg = MailchimpResumeConfig(offset=1500)
        as_json = json.dumps(dataclasses.asdict(cfg))
        reconstituted = MailchimpResumeConfig(**json.loads(as_json))
        assert reconstituted == cfg
        assert reconstituted.list_id is None


def _routed_session(routes: dict[str, list[dict[str, Any]]]) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    """Session double serving canned JSON bodies keyed by API path, recording every call.

    A path may map to several bodies; the nth request to it gets the nth body, and the last
    body repeats once they run out.
    """
    calls: list[tuple[str, dict[str, Any]]] = []
    seen: dict[str, int] = {}

    def get(url: str, params: dict[str, Any] | None = None, timeout: int | None = None) -> MagicMock:
        path = url.split("/3.0", 1)[1]
        calls.append((path, dict(params or {})))

        bodies = routes[path]
        index = min(seen.get(path, 0), len(bodies) - 1)
        seen[path] = seen.get(path, 0) + 1

        response = MagicMock()
        response.json.return_value = bodies[index]
        response.raise_for_status.return_value = None
        return response

    session = MagicMock()
    session.get.side_effect = get
    return session, calls


def _patch_session(monkeypatch, session: Any) -> None:
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp._mailchimp_session",
        lambda *a, **k: session,
    )


class TestEndpointConfigInvariants:
    @pytest.mark.parametrize("name", sorted(MAILCHIMP_ENDPOINTS))
    def test_fan_out_path_placeholders_match_declared_parents(self, name: str) -> None:
        # A placeholder with no matching parent raises KeyError at str.format() time — mid-sync,
        # on that endpoint only. `contacts` is exempt: it formats its path in its own iterator.
        config = MAILCHIMP_ENDPOINTS[name]
        if name == "contacts":
            return

        placeholders = set(re.findall(r"\{(\w+)\}", config.path))
        assert placeholders == {parent.inject_as for parent in config.parents}

    @pytest.mark.parametrize("name", sorted(MAILCHIMP_ENDPOINTS))
    def test_fan_out_primary_keys_include_every_parent_id(self, name: str) -> None:
        # Child rows are pooled from every parent, so a key without the parent id is not unique
        # table-wide and every later merge multi-matches the duplicates.
        config = MAILCHIMP_ENDPOINTS[name]
        for parent in config.parents:
            assert parent.inject_as in config.primary_keys


class TestIncrementalQueryParams:
    @pytest.mark.parametrize(
        ("endpoint", "field", "expected"),
        [
            # Guards the params the pre-existing endpoints have always sent.
            ("campaigns", "create_time", {"since_create_time": "2024-01-02T03:04:05+00:00"}),
            ("campaigns", "send_time", {"since_send_time": "2024-01-02T03:04:05+00:00"}),
            ("reports", "send_time", {"since_send_time": "2024-01-02T03:04:05+00:00"}),
            ("reports", "create_time", {}),
            ("lists", None, {}),
            ("automations", "create_time", {"since_create_time": "2024-01-02T03:04:05+00:00"}),
            ("automations", "start_time", {"since_start_time": "2024-01-02T03:04:05+00:00"}),
            ("templates", "date_created", {"since_date_created": "2024-01-02T03:04:05+00:00"}),
            ("list_segments", "updated_at", {"since_updated_at": "2024-01-02T03:04:05+00:00"}),
            ("list_segments", "created_at", {"since_created_at": "2024-01-02T03:04:05+00:00"}),
            # No server-side filter available, so the endpoint stays on full refresh.
            ("ecommerce_orders", "processed_at_foreign", {}),
        ],
    )
    def test_field_maps_to_vendor_filter(self, endpoint: str, field: str | None, expected: dict[str, str]) -> None:
        assert (
            _incremental_query_params(
                MAILCHIMP_ENDPOINTS[endpoint],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5),
                incremental_field=field,
            )
            == expected
        )

    def test_no_filter_sent_when_incremental_is_off(self) -> None:
        assert (
            _incremental_query_params(
                MAILCHIMP_ENDPOINTS["automations"],
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5),
                incremental_field="create_time",
            )
            == {}
        )


class TestGenericEndpointIterator:
    @pytest.mark.parametrize(
        ("endpoint", "routes", "expected_paths", "expected_params"),
        [
            (
                # count/offset endpoint: both params sent.
                "list_activity",
                {
                    "/lists": [{"lists": [{"id": "l1"}], "total_items": 1}],
                    "/lists/l1/activity": [{"activity": [{"day": "2024-01-01"}], "total_items": 1}],
                },
                ["/lists", "/lists/l1/activity"],
                {"count": 1000, "offset": 0},
            ),
            (
                # `count` is accepted but `offset` is not — sending it risks a 400.
                "landing_pages",
                {"/landing-pages": [{"landing_pages": [{"id": "p1"}], "total_items": 1}]},
                ["/landing-pages"],
                {"count": 1000},
            ),
            (
                # No pagination params at all on this endpoint.
                "verified_domains",
                {"/verified-domains": [{"domains": [{"domain": "example.com"}], "total_items": 1}]},
                ["/verified-domains"],
                {},
            ),
        ],
    )
    def test_only_supported_pagination_params_are_sent(
        self,
        monkeypatch,
        endpoint: str,
        routes: dict[str, list[dict[str, Any]]],
        expected_paths: list[str],
        expected_params: dict[str, Any],
    ) -> None:
        session, calls = _routed_session(routes)
        _patch_session(monkeypatch, session)

        rows = list(_get_endpoint_iterator("key-us6", MAILCHIMP_ENDPOINTS[endpoint], _fake_manager()))

        assert [path for path, _ in calls] == expected_paths
        assert calls[-1][1] == expected_params
        assert len(rows) == 1

    def test_fan_out_injects_parent_id_onto_rows_the_api_omits(self, monkeypatch) -> None:
        # /reports/{id}/locations rows carry no campaign_id, so without injection the
        # primary key would collapse every campaign's regions onto each other.
        session, calls = _routed_session(
            {
                "/reports": [{"reports": [{"id": "c1"}, {"id": "c2"}], "total_items": 2}],
                "/reports/c1/locations": [{"locations": [{"country_code": "US", "region": "CA"}], "total_items": 1}],
                "/reports/c2/locations": [{"locations": [{"country_code": "GB", "region": ""}], "total_items": 1}],
            }
        )
        _patch_session(monkeypatch, session)

        rows = list(_get_endpoint_iterator("key-us6", MAILCHIMP_ENDPOINTS["report_locations"], _fake_manager()))

        assert rows == [
            {"campaign_id": "c1", "country_code": "US", "region": "CA"},
            {"campaign_id": "c2", "country_code": "GB", "region": ""},
        ]
        assert [path for path, _ in calls] == ["/reports", "/reports/c1/locations", "/reports/c2/locations"]

    def test_two_level_fan_out_resolves_both_parents(self, monkeypatch) -> None:
        session, calls = _routed_session(
            {
                "/lists": [{"lists": [{"id": "l1"}], "total_items": 1}],
                "/lists/l1/segments": [{"segments": [{"id": 7}, {"id": 8}], "total_items": 2}],
                "/lists/l1/segments/7/members": [{"members": [{"id": "m1"}], "total_items": 1}],
                "/lists/l1/segments/8/members": [{"members": [{"id": "m2"}], "total_items": 1}],
            }
        )
        _patch_session(monkeypatch, session)

        rows = list(_get_endpoint_iterator("key-us6", MAILCHIMP_ENDPOINTS["list_segment_members"], _fake_manager()))

        assert rows == [
            {"id": "m1", "list_id": "l1", "segment_id": "7"},
            {"id": "m2", "list_id": "l1", "segment_id": "8"},
        ]
        assert calls[-1][0] == "/lists/l1/segments/8/members"

    def test_single_object_endpoint_yields_one_row_per_parent(self, monkeypatch) -> None:
        session, _ = _routed_session(
            {
                "/campaigns": [{"campaigns": [{"id": "c1"}], "total_items": 1}],
                "/campaigns/c1/content": [{"html": "<p>hi</p>", "plain_text": "hi"}],
            }
        )
        _patch_session(monkeypatch, session)

        rows = list(_get_endpoint_iterator("key-us6", MAILCHIMP_ENDPOINTS["campaign_content"], _fake_manager()))

        assert rows == [{"campaign_id": "c1", "html": "<p>hi</p>", "plain_text": "hi"}]

    def test_multi_page_child_checkpoints_each_page_against_its_parent(self, monkeypatch) -> None:
        session, calls = _routed_session(
            {
                "/reports": [{"reports": [{"id": "c1"}], "total_items": 1}],
                "/reports/c1/sent-to": [
                    {"sent_to": [{"email_id": "e1"}], "total_items": 1500},
                    {"sent_to": [{"email_id": "e2"}], "total_items": 1500},
                ],
            }
        )
        manager = _fake_manager()
        _patch_session(monkeypatch, session)

        rows = list(_get_endpoint_iterator("key-us6", MAILCHIMP_ENDPOINTS["report_sent_to"], manager))

        assert [row["email_id"] for row in rows] == ["e1", "e2"]
        assert [params.get("offset") for path, params in calls if path.endswith("/sent-to")] == [0, 1000]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            MailchimpResumeConfig(offset=0, parent_ids=["c1"]),
            MailchimpResumeConfig(offset=1000, parent_ids=["c1"]),
        ]

    def test_resume_skips_completed_parents_and_seeds_the_saved_offset(self, monkeypatch) -> None:
        session, calls = _routed_session(
            {
                "/reports": [{"reports": [{"id": "c1"}, {"id": "c2"}], "total_items": 2}],
                "/reports/c2/sent-to": [{"sent_to": [{"email_id": "e9"}], "total_items": 1001}],
            }
        )
        _patch_session(monkeypatch, session)

        rows = list(
            _get_endpoint_iterator(
                "key-us6",
                MAILCHIMP_ENDPOINTS["report_sent_to"],
                _fake_manager(can_resume=True, load_state=MailchimpResumeConfig(offset=1000, parent_ids=["c2"])),
            )
        )

        assert [row["email_id"] for row in rows] == ["e9"]
        assert [path for path, _ in calls] == ["/reports", "/reports/c2/sent-to"]
        assert calls[-1][1]["offset"] == 1000

    def test_checkpoint_for_a_vanished_parent_falls_back_to_a_fresh_run(self, monkeypatch) -> None:
        # Honouring a checkpoint whose campaign no longer exists would skip every parent and
        # sync nothing at all.
        session, calls = _routed_session(
            {
                "/reports": [{"reports": [{"id": "c1"}], "total_items": 1}],
                "/reports/c1/sent-to": [{"sent_to": [{"email_id": "e1"}], "total_items": 1}],
            }
        )
        _patch_session(monkeypatch, session)

        rows = list(
            _get_endpoint_iterator(
                "key-us6",
                MAILCHIMP_ENDPOINTS["report_sent_to"],
                _fake_manager(can_resume=True, load_state=MailchimpResumeConfig(offset=2000, parent_ids=["deleted"])),
            )
        )

        assert [row["email_id"] for row in rows] == ["e1"]
        assert calls[-1][1]["offset"] == 0

    def test_incremental_filter_is_forwarded_to_the_child_request(self, monkeypatch) -> None:
        session, calls = _routed_session(
            {
                "/lists": [{"lists": [{"id": "l1"}], "total_items": 1}],
                "/lists/l1/segments": [{"segments": [{"id": 1}], "total_items": 1}],
            }
        )
        _patch_session(monkeypatch, session)

        list(
            _get_endpoint_iterator(
                "key-us6",
                MAILCHIMP_ENDPOINTS["list_segments"],
                _fake_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 6, 7, 8, 9),
                incremental_field="updated_at",
            )
        )

        # The parent listing must stay unfiltered, or new segments on old audiences go missing.
        assert calls[0] == ("/lists", {"count": 1000, "offset": 0})
        assert calls[1][1]["since_updated_at"] == "2024-05-06T07:08:09+00:00"


class TestSourceResponseForNewEndpoints:
    def test_fan_out_endpoint_is_routed_away_from_the_rest_path(self, monkeypatch) -> None:
        # Routing a fan-out endpoint through rest_api_resource would request the literal
        # unformatted `/reports/{campaign_id}/locations` and 404.
        session, calls = _routed_session(
            {
                "/reports": [{"reports": [{"id": "c1"}], "total_items": 1}],
                "/reports/c1/locations": [{"locations": [{"country_code": "US", "region": ""}], "total_items": 1}],
            }
        )
        _patch_session(monkeypatch, session)

        response = mailchimp_source(
            api_key="key-us6",
            endpoint="report_locations",
            team_id=1,
            job_id="job",
            resumable_source_manager=_fake_manager(),
        )
        rows = list(cast(Iterable[Any], response.items()))

        assert response.primary_keys == ["campaign_id", "country_code", "region"]
        assert rows == [{"campaign_id": "c1", "country_code": "US", "region": ""}]
        assert [path for path, _ in calls] == ["/reports", "/reports/c1/locations"]

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_partition_keys"),
        [
            ("lists", ["id"], ["date_created"]),
            ("contacts", ["list_id", "id"], None),
            ("ecommerce_orders", ["store_id", "id"], ["processed_at_foreign"]),
            ("verified_domains", ["domain"], None),
            ("report_unsubscribed", ["campaign_id", "email_id"], ["timestamp"]),
        ],
    )
    def test_primary_and_partition_keys_come_from_the_endpoint_config(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_partition_keys: list[str] | None,
    ) -> None:
        response = mailchimp_source(
            api_key="key-us6",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=_fake_manager(),
        )

        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_partition_keys
