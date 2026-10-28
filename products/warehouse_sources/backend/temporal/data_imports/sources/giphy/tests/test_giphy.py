from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.giphy import GiphySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.giphy import (
    PAGE_SIZE,
    GiphyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.source import GiphySource


def _driver(*, api_key: str = "KEY", search_query: str | None = None) -> SourceDriver:
    return SourceDriver(GiphySource(), GiphySourceConfig(api_key=api_key, search_query=search_query))


def _gif_page(ids: list[str], total_count: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": [{"id": item_id, "type": "gif"} for item_id in ids],
            "pagination": {"count": len(ids), "total_count": total_count},
            "meta": {"status": 200, "msg": "OK"},
        }
    )


class TestPagination:
    def test_paginates_until_total_count_reached(self) -> None:
        full = [str(i) for i in range(PAGE_SIZE)]
        result = _driver().run(
            "gifs_trending",
            [_gif_page(full, total_count=PAGE_SIZE + 2), _gif_page(["x", "y"], total_count=PAGE_SIZE + 2)],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 2
        assert result.rows[-1] == {"id": "y", "type": "gif"}
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]


class TestResume:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "gifs_trending",
            [_gif_page(["x", "y"], total_count=PAGE_SIZE + 2)],
            resume_state=GiphyResumeConfig(offset=PAGE_SIZE),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["x", "y"]
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestSearch:
    @parameterized.expand(["gifs_search", "stickers_search"])
    def test_search_without_query_raises(self, endpoint: str) -> None:
        result = _driver(search_query="   ").run(endpoint, [])

        assert isinstance(result.raised, ValueError)
        assert "requires a search query" in str(result.raised)
        assert result.requests == []


class TestTermList:
    def test_term_list_explodes_strings_single_fetch(self) -> None:
        result = _driver().run(
            "trending_search_terms",
            [ScriptedResponse(json={"data": ["cats", "dogs", "memes"], "meta": {"status": 200}})],
        )

        assert result.raised is None
        assert result.rows == [{"search_term": "cats"}, {"search_term": "dogs"}, {"search_term": "memes"}]
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestRedaction:
    def test_api_key_registered_for_value_redaction(self) -> None:
        # The key rides in the query string, so it must reach make_tracked_session as a redacted value
        # or it leaks into tracked URLs, samples, and raised error messages.
        result = _driver().run("gifs_trending", [_gif_page(["a"], total_count=1)])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("KEY",)

    def test_client_error_message_does_not_leak_api_key(self) -> None:
        api_key = "super-secret-key"
        result = _driver(api_key=api_key, search_query="cats").run(
            "gifs_search",
            [ScriptedResponse(status=400, json={"meta": {"status": 400, "msg": "Bad Request"}})],
        )

        assert isinstance(result.raised, HTTPError)
        assert api_key not in str(result.raised)
        assert "api.giphy.com/v1/gifs/search" in str(result.raised)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("gifs_trending", ["id"]),
            ("stickers_trending", ["id"]),
            ("gifs_search", ["id"]),
            ("stickers_search", ["id"]),
            ("categories", ["name_encoded"]),
            ("trending_search_terms", ["search_term"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        result = _driver(search_query="cats").run(endpoint, [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_maps_to_validity(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("KEY") is expected

        assert network.requests_log[0].path == "/v1/gifs/trending"
        assert network.requests_log[0].param("api_key") == "KEY"
