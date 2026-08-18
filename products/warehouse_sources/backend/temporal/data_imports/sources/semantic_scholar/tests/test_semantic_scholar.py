import json
import datetime
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar import (
    SemanticScholarResumeConfig,
    build_date_window,
    semantic_scholar_source,
    utc_today,
    validate_author_search,
    validate_paper_search,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    AUTHORS_ENDPOINT,
    PAPERS_ENDPOINT,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar"
TODAY = utc_today()


def _papers_page(token: Optional[str], rows: Optional[list[dict[str, Any]]] = None) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps(
        {"total": 1, "token": token, "data": rows if rows is not None else [{"paperId": "P1"}]}
    ).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _authors_page(rows: Optional[list[dict[str, Any]]] = None) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps({"total": 1, "offset": 0, "data": rows if rows is not None else []}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _http(status_code: int, body: Optional[dict[str, Any]] = None) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body if body is not None else {}).encode()
    return response


def _manager(resume_state: Optional[SemanticScholarResumeConfig] = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _drive(
    endpoint: str,
    responses: list[Response],
    manager: MagicMock,
    query: str = "quantum computing",
    author_query: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[dict[str, Any]]:
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

        response = semantic_scholar_source(
            api_key="key",
            query=query,
            author_query=author_query,
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        list(cast(Iterable[Any], response.items()))

    return sent_params


class TestBuildDateWindow:
    @pytest.mark.parametrize(
        "from_value,cap,expected",
        [
            (None, TODAY, f":{TODAY.isoformat()}"),
            ("", TODAY, f":{TODAY.isoformat()}"),
            ("not-a-date", TODAY, f":{TODAY.isoformat()}"),
            (datetime.date(2024, 1, 1), TODAY, f"2024-01-01:{TODAY.isoformat()}"),
            (datetime.datetime(2024, 1, 1, 12, 30), TODAY, f"2024-01-01:{TODAY.isoformat()}"),
            ("2024-01-01", TODAY, f"2024-01-01:{TODAY.isoformat()}"),
            ("2024-01-01T12:30:00Z", TODAY, f"2024-01-01:{TODAY.isoformat()}"),
        ],
    )
    def test_window_is_built_from_the_watermark(self, from_value: Any, cap: datetime.date, expected: str) -> None:
        assert build_date_window(from_value, cap) == expected

    def test_a_future_watermark_is_pulled_back_to_the_cap(self) -> None:
        # Nothing ever lowers a watermark, so a bound past the cap has to be pulled back to it
        # rather than asking for an empty window on every run.
        future = TODAY + datetime.timedelta(days=365)

        assert build_date_window(future, TODAY) == f"{TODAY.isoformat()}:{TODAY.isoformat()}"


class TestPapersPagination:
    def test_first_request_sends_no_token_and_later_pages_follow_the_response_token(self) -> None:
        manager = _manager()

        sent_params = _drive(PAPERS_ENDPOINT, [_papers_page("t1"), _papers_page("t2"), _papers_page(None)], manager)

        assert "token" not in sent_params[0]
        assert [params["token"] for params in sent_params[1:]] == ["t1", "t2"]

    def test_state_is_saved_after_every_non_terminal_page(self) -> None:
        manager = _manager()

        _drive(PAPERS_ENDPOINT, [_papers_page("t1"), _papers_page("t2"), _papers_page(None)], manager)

        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            SemanticScholarResumeConfig(token="t1"),
            SemanticScholarResumeConfig(token="t2"),
        ]

    def test_a_null_token_saves_no_state(self) -> None:
        # `token` is null once a query is exhausted; nothing further to resume from.
        manager = _manager()

        _drive(PAPERS_ENDPOINT, [_papers_page(None)], manager)

        manager.save_state.assert_not_called()

    def test_resume_starts_from_the_saved_token(self) -> None:
        manager = _manager(SemanticScholarResumeConfig(token="saved-token"))

        sent_params = _drive(PAPERS_ENDPOINT, [_papers_page(None)], manager)

        assert sent_params[0]["token"] == "saved-token"


class TestAuthorsPagination:
    def test_pagination_advances_by_the_page_size(self) -> None:
        manager = _manager()

        sent_params = _drive(
            AUTHORS_ENDPOINT,
            [_authors_page([{"authorId": "A1"}] * 1000), _authors_page([])],
            manager,
            author_query="Jane Smith",
        )

        assert [params["offset"] for params in sent_params] == [0, 1000]
        assert all(params["limit"] == 1000 for params in sent_params)

    def test_a_short_page_ends_pagination(self) -> None:
        manager = _manager()

        sent_params = _drive(
            AUTHORS_ENDPOINT, [_authors_page([{"authorId": "A1"}])], manager, author_query="Jane Smith"
        )

        assert len(sent_params) == 1

    def test_resume_starts_from_the_saved_offset(self) -> None:
        manager = _manager(SemanticScholarResumeConfig(offset=2000))

        sent_params = _drive(AUTHORS_ENDPOINT, [_authors_page([])], manager, author_query="Jane Smith")

        assert sent_params[0]["offset"] == 2000


class TestRequestParams:
    def test_incremental_run_sends_a_capped_publication_date_window(self) -> None:
        sent_params = _drive(
            PAPERS_ENDPOINT,
            [_papers_page(None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2024, 1, 1),
        )

        assert sent_params[0]["publicationDateOrYear"] == f"2024-01-01:{TODAY.isoformat()}"
        # The watermark only advances correctly if rows arrive oldest first.
        assert sent_params[0]["sort"] == "publicationDate:asc"

    def test_first_incremental_run_sends_only_the_cap(self) -> None:
        sent_params = _drive(
            PAPERS_ENDPOINT,
            [_papers_page(None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert sent_params[0]["publicationDateOrYear"] == f":{TODAY.isoformat()}"

    def test_full_refresh_sends_no_date_bound(self) -> None:
        sent_params = _drive(PAPERS_ENDPOINT, [_papers_page(None)], _manager(), should_use_incremental_field=False)

        assert "publicationDateOrYear" not in sent_params[0]

    def test_the_window_stays_stable_across_pages_of_one_run(self) -> None:
        sent_params = _drive(
            PAPERS_ENDPOINT,
            [_papers_page("t1"), _papers_page(None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2024, 1, 1),
        )

        assert sent_params[0]["publicationDateOrYear"] == sent_params[1]["publicationDateOrYear"]

    def test_authors_never_sends_a_sort_or_date_bound(self) -> None:
        sent_params = _drive(AUTHORS_ENDPOINT, [_authors_page([])], _manager(), author_query="Jane Smith")

        assert "sort" not in sent_params[0]
        assert "publicationDateOrYear" not in sent_params[0]


class TestSourceResponseMetadata:
    def test_papers_response_metadata(self) -> None:
        response = semantic_scholar_source(
            api_key="key",
            query="quantum computing",
            author_query=None,
            endpoint=PAPERS_ENDPOINT,
            team_id=1,
            job_id="job",
            resumable_source_manager=_manager(),
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

        assert response.name == PAPERS_ENDPOINT
        assert response.primary_keys == ["paperId"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["publicationDate"]

    def test_authors_response_metadata(self) -> None:
        response = semantic_scholar_source(
            api_key="key",
            query="quantum computing",
            author_query="Jane Smith",
            endpoint=AUTHORS_ENDPOINT,
            team_id=1,
            job_id="job",
            resumable_source_manager=_manager(),
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

        assert response.name == AUTHORS_ENDPOINT
        assert response.primary_keys == ["authorId"]
        # Author search has no documented sort guarantee.
        assert response.sort_mode is None

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError):
            semantic_scholar_source(
                api_key="key",
                query="quantum computing",
                author_query=None,
                endpoint="Nonsense",
                team_id=1,
                job_id="job",
                resumable_source_manager=_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,body,expected_ok,expected_message",
        [
            (200, {"total": 0, "token": None, "data": []}, True, None),
            (
                403,
                {"message": "Forbidden"},
                False,
                "Your Semantic Scholar API key is invalid. Check the key and try again.",
            ),
            (
                429,
                {"message": "Too Many Requests"},
                False,
                "Semantic Scholar rate-limited this request. Add an API key, or wait a moment and try again.",
            ),
            (
                400,
                {"error": "Search returned too many hits (15754802 of 10000000)"},
                False,
                "Semantic Scholar rejected the search query: Search returned too many hits (15754802 of 10000000)",
            ),
            (400, {}, False, "Semantic Scholar rejected the search query."),
            (500, {}, False, "Semantic Scholar API returned 500."),
        ],
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_paper_search_status_mapping(
        self,
        mock_session: MagicMock,
        status_code: int,
        body: dict[str, Any],
        expected_ok: bool,
        expected_message: Optional[str],
    ) -> None:
        mock_session.return_value.get.return_value = _http(status_code, body)

        assert validate_paper_search("key", "quantum computing") == (expected_ok, expected_message)

    @patch(f"{MODULE}.make_tracked_session")
    def test_author_search_reports_its_own_field_label(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _http(400, {"error": "bad query"})

        assert validate_author_search("key", "Jane Smith") == (
            False,
            "Semantic Scholar rejected the author search query: bad query",
        )

    @patch(f"{MODULE}.make_tracked_session")
    def test_a_blank_api_key_sends_no_header(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _http(200, {"total": 0, "token": None, "data": []})

        validate_paper_search("", "quantum computing")

        assert mock_session.return_value.get.call_args.kwargs["headers"] == {}
