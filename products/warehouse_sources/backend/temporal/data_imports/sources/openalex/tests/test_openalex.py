import datetime
from typing import Any, Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openalex import (
    OpenalexSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.openalex import (
    PAGE_SIZE,
    OpenAlexResumeConfig,
    build_filter,
    utc_today,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.settings import (
    ENDPOINTS,
    OPENALEX_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source import OpenalexSource

INSTITUTION_FILTER = "authorships.institutions.lineage:i27837315"
TODAY = utc_today()


def _page(cursor: Optional[str], rows: Optional[list[dict[str, Any]]] = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={"meta": {"count": 1, "next_cursor": cursor}, "results": rows if rows is not None else [{"id": "W1"}]}
    )


def _drive(
    endpoint: str,
    responses: list[ScriptedResponse],
    entity_filter: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    resume_state: Optional[OpenAlexResumeConfig] = None,
) -> DriveResult:
    config = OpenalexSourceConfig(
        api_key="key",
        works_filter=entity_filter if endpoint == "works" else None,
        authors_filter=entity_filter if endpoint == "authors" else None,
        awards_filter=entity_filter if endpoint == "awards" else None,
    )
    return SourceDriver(OpenalexSource(), config).run(
        endpoint,
        responses,
        resume_state=resume_state,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


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
        result = _drive("topics", [_page("c1"), _page("c2"), _page(None)])

        # Without the "*" seed OpenAlex falls back to page-number paging, which is capped at
        # 10,000 records, so a large table would silently truncate.
        assert result.raised is None
        assert result.params("cursor") == ["*", "c1", "c2"]
        assert set(result.params("per_page")) == {str(PAGE_SIZE)}

    def test_state_is_saved_after_every_non_terminal_page(self) -> None:
        result = _drive("topics", [_page("c1"), _page("c2"), _page(None)])

        assert result.raised is None
        assert result.saved_states == [
            OpenAlexResumeConfig(cursor="c1"),
            OpenAlexResumeConfig(cursor="c2"),
        ]

    def test_single_page_run_saves_no_state(self) -> None:
        result = _drive("topics", [_page(None)])

        assert result.raised is None
        assert result.saved_states == []
        assert result.params("cursor") == ["*"]

    def test_resume_starts_from_the_saved_cursor(self) -> None:
        result = _drive("topics", [_page(None)], resume_state=OpenAlexResumeConfig(cursor="saved-cursor"))

        assert result.raised is None
        assert result.params("cursor") == ["saved-cursor"]


class TestRequestParams:
    def test_incremental_run_sends_the_watermark_as_a_server_side_filter(self) -> None:
        result = _drive(
            "works",
            [_page(None)],
            entity_filter=INSTITUTION_FILTER,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert result.raised is None
        assert result.requests[0].param("filter") == (
            f"{INSTITUTION_FILTER},from_publication_date:2026-07-01,to_publication_date:{TODAY.isoformat()}"
        )
        # The watermark only advances correctly if rows arrive oldest first.
        assert result.requests[0].param("sort") == "publication_date"

    def test_first_incremental_run_sends_the_user_filter_and_the_cap(self) -> None:
        result = _drive(
            "works",
            [_page(None)],
            entity_filter=INSTITUTION_FILTER,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("filter") == f"{INSTITUTION_FILTER},to_publication_date:{TODAY.isoformat()}"

    def test_incremental_runs_never_read_past_today(self) -> None:
        # OpenAlex carries future publication dates. The pipeline checkpoints the largest
        # value it sees, so fetching one would pin the watermark in the future and silently
        # skip everything published between now and then, forever.
        result = _drive(
            "works",
            [_page(None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert result.raised is None
        assert f"to_publication_date:{TODAY.isoformat()}" in (result.requests[0].param("filter") or "")

    def test_a_future_watermark_does_not_wedge_the_table(self) -> None:
        # Nothing ever lowers a watermark, so a bound past the cap has to be pulled back to it
        # rather than left asking for an empty window on every run.
        result = _drive(
            "works",
            [_page(None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=TODAY + datetime.timedelta(days=365),
        )

        assert result.raised is None
        assert result.requests[0].param("filter") == (
            f"from_publication_date:{TODAY.isoformat()},to_publication_date:{TODAY.isoformat()}"
        )

    def test_the_cap_stays_stable_across_pages_of_one_run(self) -> None:
        # The filter has to stay identical for the life of a cursor walk, so the cap is pinned
        # once per run rather than recomputed per page.
        result = _drive(
            "works",
            [_page("c1"), _page(None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert result.raised is None
        assert result.params("filter")[0] == result.params("filter")[1]

    def test_full_refresh_sends_no_publication_date_bounds(self) -> None:
        # A full refresh checkpoints nothing, so there is no watermark to protect and no
        # reason to hide ahead-of-print works from the table.
        result = _drive("works", [_page(None)], should_use_incremental_field=False)

        assert result.raised is None
        assert result.requests[0].param("filter") is None

    def test_full_refresh_ignores_a_stale_watermark(self) -> None:
        result = _drive(
            "works",
            [_page(None)],
            entity_filter=INSTITUTION_FILTER,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime.date(2026, 7, 1),
        )

        assert result.raised is None
        assert result.requests[0].param("filter") == INSTITUTION_FILTER

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name != "works"])
    def test_only_works_sends_a_sort(self, endpoint: str) -> None:
        # `sort=publication_date` is a works-only field; sending it elsewhere is a 400.
        result = _drive(endpoint, [_page(None)])

        assert result.raised is None
        assert result.requests[0].param("sort") is None

    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name not in ("works", "authors", "awards")])
    def test_unfilterable_endpoints_send_no_filter(self, endpoint: str) -> None:
        result = _drive(endpoint, [_page(None)])

        assert result.raised is None
        assert result.requests[0].param("filter") is None


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        endpoint_config = OPENALEX_ENDPOINTS[endpoint]
        result = _drive(endpoint, [_page(None)])
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        # Every OpenAlex entity is keyed by its canonical OpenAlex URL, unique per entity type.
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [endpoint_config.partition_key]
        # Declaring "asc" on an endpoint we cannot order would checkpoint a bogus watermark.
        assert response.sort_mode == ("asc" if endpoint == "works" else None)

    def test_works_rows_are_batched_tighter_than_the_default(self) -> None:
        works = _drive("works", [_page(None)]).response
        topics = _drive("topics", [_page(None)]).response

        assert works is not None and topics is not None
        assert works.chunk_size is not None and works.chunk_size_bytes is not None
        assert topics.chunk_size is None and topics.chunk_size_bytes is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_message",
        [
            (200, True, None),
        ],
    )
    def test_key_probe_status_mapping(
        self, status_code: int, expected_ok: bool, expected_message: Optional[str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            outcome = validate_credentials("key", {})

        assert outcome == (expected_ok, expected_message)
        assert {request.path for request in network.requests_log} == {"/domains"}

    @pytest.mark.parametrize(
        "status_code,expected_message",
        [
            (400, "The works filter is not a valid OpenAlex filter expression"),
            (403, "The works filter needs an OpenAlex plan your API key does not have"),
            (500, "OpenAlex API returned 500 for the works filter"),
        ],
    )
    def test_a_rejected_filter_is_not_reported_as_a_bad_key(self, status_code: int, expected_message: str) -> None:
        with scripted_network(
            lambda request: ScriptedResponse(status=200 if request.path == "/domains" else status_code)
        ) as network:
            outcome = validate_credentials("key", {"works": "bogus_field:x"})

        assert outcome == (False, expected_message)
        assert network.requests_log[0].path == "/domains"
        assert {request.path for request in network.requests_log} == {"/domains", "/works"}
        assert network.requests_log[1].param("filter") == "bogus_field:x"

    @pytest.mark.parametrize("entity_filter", [None, "", "   "])
    def test_blank_filters_are_not_probed(self, entity_filter: Optional[str]) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            outcome = validate_credentials("key", {"works": entity_filter})

        assert outcome == (True, None)
        assert [request.path for request in network.requests_log] == ["/domains"]

    def test_every_configured_filter_is_probed_against_its_own_entity(self) -> None:
        with scripted_network([ScriptedResponse(status=200)] * 3) as network:
            outcome = validate_credentials("key", {"works": INSTITUTION_FILTER, "awards": "funder.id:f1"})

        assert outcome == (True, None)

        probed = [request.url.split("?", 1)[0] for request in network.requests_log]
        assert probed == [
            "https://api.openalex.org/domains",
            "https://api.openalex.org/works",
            "https://api.openalex.org/awards",
        ]
        assert [request.param("filter") for request in network.requests_log] == [
            None,
            INSTITUTION_FILTER,
            "funder.id:f1",
        ]
