import json
import datetime
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.openalex import (
    PAGE_SIZE,
    OpenAlexResumeConfig,
    build_filter,
    openalex_source,
    utc_today,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.settings import (
    ENDPOINTS,
    OPENALEX_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.openalex.openalex"
INSTITUTION_FILTER = "authorships.institutions.lineage:i27837315"
TODAY = utc_today()


def _page(cursor: Optional[str], rows: Optional[list[dict[str, Any]]] = None) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps(
        {"meta": {"count": 1, "next_cursor": cursor}, "results": rows if rows is not None else [{"id": "W1"}]}
    ).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _http(status_code: int) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = b"{}"
    return response


def _manager(resume_state: Optional[OpenAlexResumeConfig] = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _drive(
    endpoint: str,
    responses: list[Response],
    manager: MagicMock,
    entity_filter: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[dict[str, Any]]:
    # The paginator mutates one Request in place across pages, so snapshot params at send time
    # rather than reading them back off the mock's call list.
    sent_params: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_params.append(dict(request.params or {}))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    ) as mock_session_factory:
        session = mock_session_factory.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = fake_send

        response = openalex_source(
            api_key="key",
            endpoint=endpoint,
            entity_filter=entity_filter,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )
        list(cast(Iterable[Any], response.items()))

    return sent_params


class TestBuildFilter:
    @pytest.mark.parametrize(
        "base_filter,watermark,expected",
        [
            (None, None, None),
            ("", None, None),
            ("   ", None, None),
            (INSTITUTION_FILTER, None, INSTITUTION_FILTER),
            ("  " + INSTITUTION_FILTER + "  ", None, INSTITUTION_FILTER),
            (None, datetime.date(2026, 7, 1), "from_publication_date:2026-07-01"),
            (None, datetime.datetime(2026, 7, 1, 13, 45), "from_publication_date:2026-07-01"),
            (None, "2026-07-01", "from_publication_date:2026-07-01"),
            (None, "2026-07-01T13:45:00Z", "from_publication_date:2026-07-01"),
            (None, "", None),
            (None, "not-a-date", None),
            (
                INSTITUTION_FILTER,
                datetime.date(2026, 7, 1),
                f"{INSTITUTION_FILTER},from_publication_date:2026-07-01",
            ),
        ],
    )
    def test_clauses_are_comma_joined(self, base_filter: Any, watermark: Any, expected: Optional[str]) -> None:
        assert build_filter(base_filter, watermark) == expected

    def test_the_cap_is_rendered_as_a_to_publication_date_clause(self) -> None:
        assert build_filter(None, datetime.date(2026, 7, 1), datetime.date(2026, 7, 20)) == (
            "from_publication_date:2026-07-01,to_publication_date:2026-07-20"
        )

    def test_a_cap_without_a_watermark_still_bounds_the_first_run(self) -> None:
        assert build_filter(INSTITUTION_FILTER, None, datetime.date(2026, 7, 20)) == (
            f"{INSTITUTION_FILTER},to_publication_date:2026-07-20"
        )

    def test_a_watermark_past_the_cap_is_pulled_back_to_it(self) -> None:
        # A watermark ahead of the cap would otherwise ask for an empty window on every run,
        # and nothing ever lowers a watermark, so the table would never sync again.
        assert build_filter(None, datetime.date(2027, 1, 1), datetime.date(2026, 7, 20)) == (
            "from_publication_date:2026-07-20,to_publication_date:2026-07-20"
        )


class TestPagination:
    def test_first_request_seeds_the_cursor_and_later_pages_follow_next_cursor(self) -> None:
        manager = _manager()

        sent_params = _drive("topics", [_page("c1"), _page("c2"), _page(None)], manager)

        # Without the "*" seed OpenAlex falls back to page-number paging, which is capped at
        # 10,000 records, so a large table would silently truncate.
        assert [params["cursor"] for params in sent_params] == ["*", "c1", "c2"]
        assert {params["per_page"] for params in sent_params} == {PAGE_SIZE}

    def test_state_is_saved_after_every_non_terminal_page(self) -> None:
        manager = _manager()

        _drive("topics", [_page("c1"), _page("c2"), _page(None)], manager)

        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            OpenAlexResumeConfig(cursor="c1"),
            OpenAlexResumeConfig(cursor="c2"),
        ]

    def test_single_page_run_saves_no_state(self) -> None:
        manager = _manager()

        _drive("topics", [_page(None)], manager)

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    def test_resume_starts_from_the_saved_cursor(self) -> None:
        manager = _manager(OpenAlexResumeConfig(cursor="saved-cursor"))

        sent_params = _drive("topics", [_page(None)], manager)

        assert sent_params[0]["cursor"] == "saved-cursor"


class TestRequestParams:
    def test_incremental_run_sends_the_watermark_as_a_server_side_filter(self) -> None:
        sent_params = _drive(
            "works",
            [_page(None)],
            _manager(),
            entity_filter=INSTITUTION_FILTER,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert sent_params[0]["filter"] == (
            f"{INSTITUTION_FILTER},from_publication_date:2026-07-01,to_publication_date:{TODAY.isoformat()}"
        )
        # The watermark only advances correctly if rows arrive oldest first.
        assert sent_params[0]["sort"] == "publication_date"

    def test_first_incremental_run_sends_the_user_filter_and_the_cap(self) -> None:
        sent_params = _drive(
            "works",
            [_page(None)],
            _manager(),
            entity_filter=INSTITUTION_FILTER,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert sent_params[0]["filter"] == f"{INSTITUTION_FILTER},to_publication_date:{TODAY.isoformat()}"

    def test_incremental_runs_never_read_past_today(self) -> None:
        # OpenAlex carries future publication dates. The pipeline checkpoints the largest
        # value it sees, so fetching one would pin the watermark in the future and silently
        # skip everything published between now and then, forever.
        sent_params = _drive(
            "works",
            [_page(None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert f"to_publication_date:{TODAY.isoformat()}" in sent_params[0]["filter"]

    def test_a_future_watermark_does_not_wedge_the_table(self) -> None:
        # Nothing ever lowers a watermark, so a bound past the cap has to be pulled back to it
        # rather than left asking for an empty window on every run.
        sent_params = _drive(
            "works",
            [_page(None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=TODAY + datetime.timedelta(days=365),
        )

        assert sent_params[0]["filter"] == (
            f"from_publication_date:{TODAY.isoformat()},to_publication_date:{TODAY.isoformat()}"
        )

    def test_the_cap_stays_stable_across_pages_of_one_run(self) -> None:
        # The filter has to stay identical for the life of a cursor walk, so the cap is pinned
        # once per run rather than recomputed per page.
        sent_params = _drive(
            "works",
            [_page("c1"), _page(None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert sent_params[0]["filter"] == sent_params[1]["filter"]

    def test_full_refresh_sends_no_publication_date_bounds(self) -> None:
        # A full refresh checkpoints nothing, so there is no watermark to protect and no
        # reason to hide ahead-of-print works from the table.
        sent_params = _drive("works", [_page(None)], _manager(), should_use_incremental_field=False)

        assert "filter" not in sent_params[0]

    def test_full_refresh_ignores_a_stale_watermark(self) -> None:
        sent_params = _drive(
            "works",
            [_page(None)],
            _manager(),
            entity_filter=INSTITUTION_FILTER,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert sent_params[0]["filter"] == INSTITUTION_FILTER

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name != "works"])
    def test_only_works_sends_a_sort(self, endpoint: str) -> None:
        # `sort=publication_date` is a works-only field; sending it elsewhere is a 400.
        sent_params = _drive(endpoint, [_page(None)], _manager())

        assert "sort" not in sent_params[0]

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name not in ("works", "authors", "awards")])
    def test_unfilterable_endpoints_send_no_filter(self, endpoint: str) -> None:
        sent_params = _drive(endpoint, [_page(None)], _manager())

        assert "filter" not in sent_params[0]


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        endpoint_config = OPENALEX_ENDPOINTS[endpoint]
        response = openalex_source(
            api_key="key",
            endpoint=endpoint,
            entity_filter=None,
            team_id=1,
            job_id="job",
            resumable_source_manager=_manager(),
            db_incremental_field_last_value=None,
        )

        assert response.name == endpoint
        # Every OpenAlex entity is keyed by its canonical OpenAlex URL, unique per entity type.
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [endpoint_config.partition_key]
        # Declaring "asc" on an endpoint we cannot order would checkpoint a bogus watermark.
        assert response.sort_mode == ("asc" if endpoint == "works" else None)

    def test_works_rows_are_batched_tighter_than_the_default(self) -> None:
        works = openalex_source(
            api_key="key",
            endpoint="works",
            entity_filter=None,
            team_id=1,
            job_id="job",
            resumable_source_manager=_manager(),
            db_incremental_field_last_value=None,
        )
        topics = openalex_source(
            api_key="key",
            endpoint="topics",
            entity_filter=None,
            team_id=1,
            job_id="job",
            resumable_source_manager=_manager(),
            db_incremental_field_last_value=None,
        )

        assert works.chunk_size is not None and works.chunk_size_bytes is not None
        assert topics.chunk_size is None and topics.chunk_size_bytes is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_message",
        [
            (200, True, None),
            (401, False, "Invalid OpenAlex API key"),
            (403, False, "Invalid OpenAlex API key"),
            (500, False, "OpenAlex API returned 500"),
        ],
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_key_probe_status_mapping(
        self, mock_session: MagicMock, status_code: int, expected_ok: bool, expected_message: Optional[str]
    ) -> None:
        mock_session.return_value.get.return_value = _http(status_code)

        assert validate_credentials("key", {}) == (expected_ok, expected_message)

    @pytest.mark.parametrize(
        "status_code,expected_message",
        [
            (400, "The works filter is not a valid OpenAlex filter expression"),
            (403, "The works filter needs an OpenAlex plan your API key does not have"),
            (500, "OpenAlex API returned 500 for the works filter"),
        ],
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_a_rejected_filter_is_not_reported_as_a_bad_key(
        self, mock_session: MagicMock, status_code: int, expected_message: str
    ) -> None:
        mock_session.return_value.get.side_effect = [_http(200), _http(status_code)]

        assert validate_credentials("key", {"works": "bogus_field:x"}) == (False, expected_message)

    @pytest.mark.parametrize("entity_filter", [None, "", "   "])
    @patch(f"{MODULE}.make_tracked_session")
    def test_blank_filters_are_not_probed(self, mock_session: MagicMock, entity_filter: Optional[str]) -> None:
        mock_session.return_value.get.return_value = _http(200)

        assert validate_credentials("key", {"works": entity_filter}) == (True, None)
        assert mock_session.return_value.get.call_count == 1

    @patch(f"{MODULE}.make_tracked_session")
    def test_every_configured_filter_is_probed_against_its_own_entity(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _http(200)

        assert validate_credentials("key", {"works": INSTITUTION_FILTER, "awards": "funder.id:f1"}) == (True, None)

        probed = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert probed == [
            "https://api.openalex.org/domains",
            "https://api.openalex.org/works",
            "https://api.openalex.org/awards",
        ]
