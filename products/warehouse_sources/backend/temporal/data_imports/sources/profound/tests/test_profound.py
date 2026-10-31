from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.profound import (
    ProfoundSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound import (
    ProfoundCategoriesError,
    ProfoundResumeConfig,
    _to_report_date,
    fetch_category_ids,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.source import ProfoundSource

CATEGORIES_PATH = "/v1/org/categories"


def _driver() -> SourceDriver:
    return SourceDriver(ProfoundSource(), ProfoundSourceConfig(api_key="key"))


def _json_response(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _report_response(rows: list[dict[str, Any]], *, next_cursor: str | None = None) -> ScriptedResponse:
    return _json_response({"info": {"next_cursor": next_cursor}, "data": rows})


def _categories(*ids: str) -> list[ScriptedResponse]:
    return [_json_response([{"id": category_id} for category_id in ids])]


class TestFetchCategoryIds:
    def test_ids_are_read_from_a_bare_array(self) -> None:
        with scripted_network(_categories("c1", "c2")):
            assert fetch_category_ids("key") == ["c1", "c2"]

    def test_an_unexpected_shape_raises(self) -> None:
        # Silently syncing 0 report rows would look like an empty account.
        with scripted_network([_json_response({"data": []})]):
            try:
                fetch_category_ids("key")
            except ProfoundCategoriesError:
                return
        raise AssertionError("expected ProfoundCategoriesError")

    def test_the_request_never_follows_a_redirect(self) -> None:
        # The API key rides the custom X-API-Key header, which requests would replay to a redirect.
        redirect = ScriptedResponse(status=302, json=[], headers={"Location": "https://evil.example.com/steal"})

        with scripted_network([redirect]) as network:
            fetch_category_ids("key")

        assert [request.origin for request in network.requests_log] == ["https://api.tryprofound.com"]

    def test_the_key_is_sent_in_the_api_key_header_and_redacted(self) -> None:
        with scripted_network(_categories("c1")) as network:
            fetch_category_ids("key")

        assert network.requests_log[0].headers["x-api-key"] == "key"
        assert network.session_options[0]["redact_values"] == ("key",)


class TestReportRequests:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 6, 9, 15, 0, tzinfo=UTC), "2026-06-09"),
            ("date", date(2026, 6, 9), "2026-06-09"),
            ("iso_string", "2026-06-09T15:00:00Z", "2026-06-09"),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_report_date(self, _name: str, value: Any, expected: str | None) -> None:
        # The report body takes YYYY-MM-DD; a full timestamp is rejected with a 422.
        assert _to_report_date(value) == expected


class TestReportFanOut:
    @staticmethod
    def _script(*report_pages: ScriptedResponse, categories: tuple[str, ...] = ("c1", "c2")) -> Callable[..., Any]:
        return route({CATEGORIES_PATH: _categories(*categories), "/v2/reports/citations": list(report_pages)})

    def test_resume_seeds_the_saved_cursor_only_for_its_own_category(self) -> None:
        result = _driver().run(
            "Citations",
            self._script(_report_response([{"domain": "a.com"}]), _report_response([{"domain": "b.com"}])),
            resume_state=ProfoundResumeConfig(category_id="c1", cursor="mid"),
        )

        bodies = [request.json() for request in result.requests if request.method == "POST"]
        assert bodies[0]["cursor"] == "mid"
        # The next category starts from its first page, not from the previous category's cursor.
        assert "cursor" not in bodies[1]

    def test_a_run_with_no_saved_state_starts_every_category_from_its_first_page(self) -> None:
        result = _driver().run(
            "Citations", self._script(_report_response([{"domain": "a.com"}]), _report_response([{"domain": "b.com"}]))
        )

        bodies = [request.json() for request in result.requests if request.method == "POST"]
        assert [body["category_id"] for body in bodies] == ["c1", "c2"]
        assert all("cursor" not in body for body in bodies)

    def test_a_finished_category_clears_its_cursor(self) -> None:
        # Leaving the last cursor in place would restart a finished category mid-walk on the next
        # attempt and skip its earlier pages.
        result = _driver().run(
            "Citations",
            self._script(
                _report_response([{"domain": "a.com"}], next_cursor="cur1"),
                _report_response([]),
                _report_response([{"domain": "a.com"}], next_cursor="cur1"),
                _report_response([]),
            ),
        )

        assert ProfoundResumeConfig(category_id="c1", cursor=None) in result.saved_states

    def test_visibility_flattens_the_nested_asset(self) -> None:
        # `asset` arrives as a nested object, and a dict cannot serve as a primary key column.
        result = _driver().run(
            "Visibility",
            route(
                {
                    CATEGORIES_PATH: _categories("c1"),
                    "/v2/reports/visibility": [
                        _report_response([{"date": "2026-06-09", "asset": {"name": "Acme", "owned": True}}])
                    ],
                }
            ),
        )

        assert result.rows[0]["asset_name"] == "Acme"
        assert result.rows[0]["asset_owned"] is True


class TestReferenceEndpoints:
    @parameterized.expand(["Categories", "Models", "Regions", "Domains"])
    def test_bare_array_endpoints_need_no_wrapper_key(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_json_response([{"id": "1"}, {"id": "2"}])])

        assert [row["id"] for row in result.rows] == ["1", "2"]

    @parameterized.expand(["Assets", "Personas"])
    def test_wrapped_endpoints_select_the_data_key(self, endpoint: str) -> None:
        # These two wrap their array in `data` where the other four return it bare.
        result = _driver().run(endpoint, [_json_response({"data": [{"id": "1"}]})])

        assert [row["id"] for row in result.rows] == ["1"]

    @parameterized.expand([("CitationCategories", "citation-categories"), ("CitationTags", "citation-tags")])
    def test_per_category_endpoints_fan_out_and_stamp_the_category(self, endpoint: str, path_segment: str) -> None:
        # The rows carry only `value` and `name`, which repeat across categories, so `category_id`
        # has to come from the request for the primary key to be unique.
        result = _driver().run(
            endpoint,
            [
                _json_response([{"id": "c1"}, {"id": "c2"}]),
                _json_response({"data": [{"value": "owned", "name": "Owned"}]}),
                _json_response({"data": [{"value": "owned", "name": "Owned"}]}),
            ],
        )

        assert result.paths[1].endswith(f"/v1/org/categories/c1/{path_segment}")
        assert result.paths[2].endswith(f"/v1/org/categories/c2/{path_segment}")
        assert [(row["category_id"], row["value"]) for row in result.rows] == [("c1", "owned"), ("c2", "owned")]
        assert all("_Categories_id" not in row for row in result.rows)


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("Visibility", ["category_id", "date", "asset_name"]),
            ("Citations", ["category_id", "date", "domain"]),
            ("Categories", ["id"]),
        ]
    )
    def test_primary_keys(self, endpoint: str, expected: list[str]) -> None:
        # A report row is unique only per category and day, so the key needs all three parts.
        def vendor(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "GET":
                return _json_response([{"id": "c1"}])
            return _report_response([])

        response = _driver().run(endpoint, vendor).response

        assert response is not None
        assert response.primary_keys == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=[]))) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == CATEGORIES_PATH
