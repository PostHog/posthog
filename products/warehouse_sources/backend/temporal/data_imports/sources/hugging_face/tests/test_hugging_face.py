from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.huggingface import (
    HuggingFaceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.hugging_face import (
    HUGGING_FACE_BASE_URL,
    _build_initial_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import (
    HUGGING_FACE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.source import HuggingFaceSource


def _driver() -> SourceDriver:
    return SourceDriver(HuggingFaceSource(), HuggingFaceSourceConfig(api_token="hf_token", author="acme"))


def _discussion(repo: str, repo_type: str, num: int) -> dict[str, Any]:
    return {"num": num, "repo": {"name": repo, "type": repo_type}, "createdAt": "2024-01-01T00:00:00.000Z"}


class TestBuildInitialParams:
    @parameterized.expand(
        [("models", "author"), ("datasets", "author"), ("spaces", "author"), ("collections", "owner")]
    )
    def test_every_endpoint_is_scoped_to_author(self, endpoint: str, param: str) -> None:
        params = _build_initial_params(HUGGING_FACE_ENDPOINTS[endpoint], author="acme")
        assert params[param] == "acme"


class TestLikes:
    def test_follows_next_link_past_empty_page_and_flattens_repo(self) -> None:
        # The Hub filters likes after paging, so an empty page can still carry a next link.
        page2 = "https://huggingface.co/api/users/acme/likes?cursor=2"
        page3 = "https://huggingface.co/api/users/acme/likes?cursor=3"
        result = _driver().run(
            "likes",
            [
                ScriptedResponse(json=[], headers={"Link": f'<{page2}>; rel="next"'}),
                ScriptedResponse(
                    json=[{"createdAt": "2024-01-01T00:00:00.000Z", "repo": {"name": "x/y", "type": "model"}}],
                    headers={"Link": f'<{page3}>; rel="next"'},
                ),
                ScriptedResponse(
                    json=[{"createdAt": "2024-01-02T00:00:00.000Z", "repo": {"name": "x/y", "type": "dataset"}}]
                ),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/users/acme/likes"] * 3
        assert result.params("cursor") == [None, "2", "3"]
        assert result.requests[0].origin == HUGGING_FACE_BASE_URL
        assert [(row["repo_type"], row["repo_name"]) for row in result.rows] == [
            ("model", "x/y"),
            ("dataset", "x/y"),
        ]


class TestTags:
    @parameterized.expand([("model_tags", "/api/models-tags-by-type"), ("dataset_tags", "/api/datasets-tags-by-type")])
    def test_flattens_tags_grouped_by_type(self, endpoint: str, path: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={
                        "library": [{"id": "pytorch", "label": "PyTorch", "type": "library"}],
                        "license": [
                            {"id": "license:mit", "label": "mit", "type": "license"},
                            {"id": "license:apache-2.0", "label": "apache-2.0", "type": "license"},
                        ],
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.paths == [path]
        assert [(row["type"], row["id"]) for row in result.rows] == [
            ("library", "pytorch"),
            ("license", "license:mit"),
            ("license", "license:apache-2.0"),
        ]


class TestDiscussions:
    def _routes(self) -> dict[str, list[ScriptedResponse]]:
        return {
            "/api/models": [ScriptedResponse(json=[{"id": "acme/m1"}, {"id": "acme/m2"}])],
            "/api/datasets": [ScriptedResponse(json=[{"id": "acme/d1"}])],
            "/api/spaces": [ScriptedResponse(json=[])],
            "/api/models/acme/m1/discussions": [
                ScriptedResponse(
                    json={
                        "discussions": [_discussion("acme/m1", "model", 3), _discussion("acme/m1", "model", 2)],
                        "count": 3,
                        "start": 0,
                    }
                ),
                ScriptedResponse(json={"discussions": [_discussion("acme/m1", "model", 1)], "count": 3, "start": 2}),
            ],
            "/api/models/acme/m2/discussions": [
                ScriptedResponse(json={"error": "Discussions are disabled for this repo"}, status=403)
            ],
            "/api/datasets/acme/d1/discussions": [
                ScriptedResponse(json={"discussions": [_discussion("acme/d1", "dataset", 1)], "count": 1, "start": 0})
            ],
        }

    def test_fans_out_over_every_repo_kind(self) -> None:
        result = _driver().run("discussions", route(self._routes()))

        assert result.raised is None
        assert [(row["repo_type"], row["repo_name"], row["num"]) for row in result.rows] == [
            ("model", "acme/m1", 3),
            ("model", "acme/m1", 2),
            ("model", "acme/m1", 1),
            ("dataset", "acme/d1", 1),
        ]
        # Pagination stops at the reported count, so no repo pays a trailing empty-page request.
        sent = [(request.path, request.param("p")) for request in result.requests]
        assert {path for path, _page in sent} == set(self._routes())
        assert ("/api/models/acme/m1/discussions", "0") in sent
        assert ("/api/models/acme/m1/discussions", "1") in sent
        assert ("/api/models/acme/m1/discussions", "2") not in sent
        assert ("/api/datasets/acme/d1/discussions", "1") not in sent


class TestRetries:
    def test_unauthorized_raises_http_error(self) -> None:
        result = _driver().run("models", [ScriptedResponse(json={"error": "unauthorized"}, status=401)])

        assert isinstance(result.raised, HTTPError)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("hf_token") is expected

        assert network.requests_log[0].path == "/api/whoami-v2"
        assert network.requests_log[0].headers["authorization"] == "Bearer hf_token"


class TestHuggingFaceSourceResponse:
    @parameterized.expand([("models",), ("datasets",), ("spaces",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["createdAt"]
