from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pexels import PexelsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.pexels import (
    PexelsResumeConfig,
    _build_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source import PexelsSource


def _driver(api_key: str = "k", search_query: str | None = None) -> SourceDriver:
    return SourceDriver(PexelsSource(), PexelsSourceConfig(api_key=api_key, search_query=search_query))


def _page(items: list[dict[str, Any]], data_key: str = "photos") -> ScriptedResponse:
    return ScriptedResponse(json={data_key: items})


_PHOTO = {"id": 7, "type": "Photo", "photographer": "A. Example"}
_VIDEO = {"id": 7, "type": "Video", "duration": 12}


class TestBuildUrl:
    @parameterized.expand(
        [
            ("encodes_spaces", "https://api.pexels.com/v1/search", {"query": "red car"}, "query=red+car"),
            ("no_params", "https://api.pexels.com/v1/curated", {}, None),
            ("page_param", "https://api.pexels.com/v1/curated", {"per_page": 80, "page": 2}, "per_page=80&page=2"),
        ]
    )
    def test_build_url(self, _name: str, base: str, params: dict, expected_fragment: str | None) -> None:
        url = _build_url(base, params)
        if expected_fragment is None:
            assert url == base
        else:
            assert expected_fragment in url


class TestAuth:
    def test_request_sends_raw_key_as_authorization_without_bearer(self) -> None:
        # The framework api_key auth must put the raw key on Authorization (no "Bearer " prefix);
        # exercise a real prepare_request so the auth is actually applied.
        result = _driver(api_key="raw-key").run("curated_photos", [_page([])])

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "raw-key"
        assert "Bearer" not in result.requests[0].headers["authorization"]


class TestPagination:
    def test_search_endpoint_sends_query_param(self) -> None:
        result = _driver(search_query="red car").run("search_photos", [_page([{"id": 1}]), _page([])])

        assert result.raised is None
        assert result.requests[0].param("query") == "red car"

    @parameterized.expand([("none", None), ("empty", "")])
    def test_search_endpoint_without_query_raises(self, _name: str, query: str | None) -> None:
        # A missing query on a search endpoint must fail loudly, not send a literal `?query=None`.
        result = _driver(search_query=query).run("search_photos", [])

        assert isinstance(result.raised, ValueError)
        assert "requires a search query" in str(result.raised)
        assert result.requests == []


class TestCollectionMedia:
    @parameterized.expand(
        [
            ("empty_collection", ScriptedResponse(json={"media": []})),
            ("collection_deleted_after_listing", ScriptedResponse(status=404, json={"error": "Not Found"})),
        ]
    )
    def test_walks_every_owned_collection(self, _name: str, second_collection: ScriptedResponse) -> None:
        result = _driver().run(
            "collection_media",
            route(
                {
                    "/v1/collections": [
                        _page([{"id": "abc1"}, {"id": "def2"}], "collections"),
                        _page([], "collections"),
                    ],
                    "/v1/collections/abc1": [_page([_PHOTO, _VIDEO], "media"), _page([], "media")],
                    "/v1/collections/def2": [second_collection],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {**_PHOTO, "collection_id": "abc1"},
            {**_VIDEO, "collection_id": "abc1"},
        ]
        assert [(r.path, r.param("page"), r.param("per_page")) for r in result.requests] == [
            ("/v1/collections", "1", "80"),
            ("/v1/collections/abc1", "1", "80"),
            ("/v1/collections/abc1", "2", "80"),
            ("/v1/collections/def2", "1", "80"),
            ("/v1/collections", "2", "80"),
        ]


class TestResume:
    def test_resumes_from_saved_page(self) -> None:
        # A resumed job must start at the saved page, not page 1.
        result = _driver().run(
            "curated_photos", [_page([{"id": 2}]), _page([])], resume_state=PexelsResumeConfig(page=2)
        )

        assert result.raised is None
        assert result.rows == [{"id": 2}]
        assert result.params("page")[0] == "2"

    @parameterized.expand(
        [
            (
                "skips_finished_collection",
                {"completed": ["/v1/collections/abc1"], "current": None, "child_state": None},
                [("/v1/collections/def2", "1")],
            ),
            (
                "continues_collection_in_progress",
                {"completed": [], "current": "/v1/collections/abc1", "child_state": {"page": 3}},
                [("/v1/collections/abc1", "3"), ("/v1/collections/def2", "1")],
            ),
        ]
    )
    def test_collection_media_resumes_from_saved_fanout_state(
        self, _name: str, fanout_state: dict[str, Any], expected_child_requests: list[tuple[str, str]]
    ) -> None:
        result = _driver().run(
            "collection_media",
            route(
                {
                    "/v1/collections": [
                        _page([{"id": "abc1"}, {"id": "def2"}], "collections"),
                        _page([], "collections"),
                    ],
                    "/v1/collections/abc1": [_page([], "media")],
                    "/v1/collections/def2": [_page([], "media")],
                }
            ),
            resume_state=PexelsResumeConfig(fanout_state=fanout_state),
        )

        assert result.raised is None
        child_requests = [(r.path, r.param("page")) for r in result.requests if r.path != "/v1/collections"]
        assert child_requests == expected_child_requests


class TestRetryClassification:
    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        # A 401 is a credential problem — it must surface immediately, not retry.
        result = _driver().run("curated_photos", [ScriptedResponse(status=401, json={"error": "boom"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestApiKeyRedaction:
    # Pexels sends the key as a raw Authorization value the sampler can't scrub by name, so the
    # source must register it for redaction (via the framework auth's secret_values) or the plaintext
    # key leaks into captured samples.
    def test_source_registers_api_key_for_redaction(self) -> None:
        result = _driver(api_key="secret-key").run("curated_photos", [_page([])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("secret-key",)

    def test_validate_credentials_registers_api_key_for_redaction(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("secret-key") is True

        assert network.session_options[0]["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("k") is expected

        assert network.requests_log[0].path == "/v1/curated"
