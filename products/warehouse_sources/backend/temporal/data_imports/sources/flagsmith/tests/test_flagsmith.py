import threading
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith import (
    DEFAULT_BASE_URL,
    FlagsmithResponseTimeoutError,
    FlagsmithResponseTooLargeError,
    FlagsmithResumeConfig,
    _read_bounded,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.settings import (
    ENDPOINTS,
    FLAGSMITH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.source import FlagsmithSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flagsmith import (
    FlagsmithSourceConfig,
)

API_BASE = f"{DEFAULT_BASE_URL}/api/v1"
BUDGET_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.MAX_PAGES_PER_SYNC"
PARENTS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.MAX_FANOUT_PARENTS"
KEY_LENGTH_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.MAX_FANOUT_KEY_LENGTH"
)


def _driver() -> SourceDriver:
    return SourceDriver(FlagsmithSource(), FlagsmithSourceConfig(api_key="key"))


def _page(results: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


class TestUrlHelpers:
    @pytest.mark.parametrize(
        "base_url, expected",
        [
            (None, DEFAULT_BASE_URL),
            ("", DEFAULT_BASE_URL),
            ("  ", DEFAULT_BASE_URL),
            ("https://flagsmith.example.com", "https://flagsmith.example.com"),
            ("https://flagsmith.example.com/", "https://flagsmith.example.com"),
            ("flagsmith.example.com", "https://flagsmith.example.com"),
            ("http://flagsmith.internal:8000", "http://flagsmith.internal:8000"),
        ],
    )
    def test_normalize_base_url_valid(self, base_url, expected):
        assert normalize_base_url(base_url) == expected

    @pytest.mark.parametrize(
        "base_url",
        [
            "ftp://flagsmith.example.com",
            "https://user@flagsmith.example.com",
            "https://user:pass@flagsmith.example.com",
            "https://169.254.169.254\\@flagsmith.example.com",
            "https://flagsmith.example.com%5C@evil.example.com",
            "https://flagsmith.example.com?next=x",
            "https://flagsmith.example.com#frag",
        ],
    )
    def test_normalize_base_url_rejects_unsafe(self, base_url):
        with pytest.raises(ValueError):
            normalize_base_url(base_url)


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [403])
    def test_returns_status_code(self, status_code):
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key", None) == status_code

        assert network.requests_log[0].path == "/api/v1/organisations/"

    def test_returns_none_on_exception(self):
        with scripted_network([ConnectionError("boom")]) as network:
            assert validate_credentials("key", None) is None

        assert network.requests_log[0].path == "/api/v1/organisations/"


class TestGetRowsTopLevel:
    def test_resume_url_repinned_to_configured_base(self):
        # A resume URL persisted before the source was retargeted must be re-pinned onto the current
        # base, or the current API key would be replayed to the previously configured (attacker) host.
        stale = "https://old-host.example.com/api/v1/organisations/?page=5"
        result = _driver().run(
            "organisations",
            [ScriptedResponse(json=_page([{"id": 9}]))],
            resume_state=FlagsmithResumeConfig(next_url=stale),
        )

        assert result.raised is None
        assert result.urls[0] == f"{API_BASE}/organisations/?page=5"
        assert result.rows == [{"id": 9}]


class TestGetRowsFanout:
    def test_feature_states_enumerate_environments_via_projects(self):
        result = _driver().run(
            "feature_states",
            [
                ScriptedResponse(json=[{"id": 1}]),  # projects
                ScriptedResponse(json=_page([{"id": 10, "api_key": "env-a"}, {"id": 11, "api_key": "env-b"}])),
                ScriptedResponse(json=_page([{"id": 1000, "enabled": True}])),  # featurestates env-a
                ScriptedResponse(json=_page([{"id": 2000, "enabled": False}])),  # featurestates env-b
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 1000, "enabled": True, "_environment_api_key": "env-a"},
            {"id": 2000, "enabled": False, "_environment_api_key": "env-b"},
        ]
        assert result.urls[2:] == [
            f"{API_BASE}/environments/env-a/featurestates/",
            f"{API_BASE}/environments/env-b/featurestates/",
        ]

    def test_users_fan_out_injects_organisation_id(self):
        result = _driver().run(
            "users",
            [
                ScriptedResponse(json=_page([{"id": 5}])),  # organisations
                ScriptedResponse(json=[{"id": 500, "email": "a@example.com"}]),  # users (plain array)
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 500, "email": "a@example.com", "_organisation_id": "5"}]
        assert result.urls[1] == f"{API_BASE}/organisations/5/users/"

    def test_resume_skips_completed_parent(self):
        # Project 1 finished last run (empty next_url marker); resume must start at project 2.
        result = _driver().run(
            "segments",
            [ScriptedResponse(json=[{"id": 1}, {"id": 2}]), ScriptedResponse(json=_page([{"id": 200}]))],
            resume_state=FlagsmithResumeConfig(next_url="", parent_key="1"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [200]
        assert result.urls == [f"{API_BASE}/projects/", f"{API_BASE}/projects/2/segments/?page_size=100"]

    def test_fan_out_resume_url_repinned_to_configured_base(self):
        # Same host-pinning guarantee on the fan-out resume path: a stale mid-parent URL must be
        # re-pinned to the current base rather than replayed to a since-changed host.
        stale = "https://old-host.example.com/api/v1/projects/1/segments/?page=3&page_size=100"
        result = _driver().run(
            "segments",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(json=_page([{"id": 150}])),
                ScriptedResponse(json=_page([{"id": 250}])),
            ],
            resume_state=FlagsmithResumeConfig(next_url=stale, parent_key="1"),
        )

        assert result.raised is None
        assert result.urls[1] == f"{API_BASE}/projects/1/segments/?page=3&page_size=100"

    def test_no_parents_yields_nothing(self):
        result = _driver().run("features", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.rows == []

    @mock.patch(KEY_LENGTH_PATH, 5)
    def test_oversized_parent_key_is_skipped(self):
        # A hostile host can return an arbitrarily long id/api_key; over-length keys must be dropped
        # so they can't balloon the retained list or be interpolated into a child request URL.
        result = _driver().run(
            "features",
            [ScriptedResponse(json=[{"id": "x" * 50}, {"id": 2}]), ScriptedResponse(json=_page([{"id": 100}]))],
        )

        assert result.raised is None
        assert [url for url in result.urls if "/features/" in url] == [
            f"{API_BASE}/projects/2/features/?page_size=100&sort_field=created_date&sort_direction=ASC"
        ]


class TestGetRowsTwoLevelFanout:
    # Identity traits and feature segments need two identifiers per request, so their parent
    # enumeration walks a second level and both identifiers are injected into each row.

    @mock.patch(PARENTS_PATH, 2)
    def test_identity_parent_cap_spans_environments(self):
        # The cap bounds the identities retained across the whole fan-out; applied per environment
        # it would let the retained list grow with the environment count.
        result = _driver().run(
            "identity_traits",
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(json=_page([{"id": 10, "api_key": "env-a"}, {"id": 11, "api_key": "env-b"}])),
                ScriptedResponse(json=_page([{"id": 500}, {"id": 501}])),
                ScriptedResponse(json=_page([{"id": 9000}])),
                ScriptedResponse(json=_page([{"id": 9000}])),
            ],
        )

        assert result.raised is None
        assert [url for url in result.urls if url.endswith("/traits/")] == [
            f"{API_BASE}/environments/env-a/identities/500/traits/",
            f"{API_BASE}/environments/env-a/identities/501/traits/",
        ]

    def test_feature_segments_pair_environments_with_features(self):
        # The listing requires both filters, and a pair only resolves inside the project that owns
        # both, so the cross product is built per project rather than globally.
        result = _driver().run(
            "feature_segments",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(json=_page([{"id": 10}, {"id": 11}])),
                ScriptedResponse(json=_page([{"id": 100}])),
                ScriptedResponse(json=_page([{"id": 20}])),
                ScriptedResponse(json=_page([{"id": 200}])),
                *[ScriptedResponse(json=_page([{"id": 7, "segment": 3}])) for _ in range(3)],
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 7, "segment": 3, "_environment_id": "10", "_feature_id": "100"},
            {"id": 7, "segment": 3, "_environment_id": "11", "_feature_id": "100"},
            {"id": 7, "segment": 3, "_environment_id": "20", "_feature_id": "200"},
        ]
        assert [url for url in result.urls if "/feature-segments/" in url] == [
            f"{API_BASE}/features/feature-segments/?environment=10&feature=100",
            f"{API_BASE}/features/feature-segments/?environment=11&feature=100",
            f"{API_BASE}/features/feature-segments/?environment=20&feature=200",
        ]

    def test_versions_skip_environments_without_v2_versioning(self):
        # Flagsmith rejects the version listing outright on an environment still using unversioned
        # feature states, so those environments must be dropped from the enumeration rather than
        # failing the whole sync on the first one.
        result = _driver().run(
            "environment_feature_versions",
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(
                    json=_page(
                        [
                            {"id": 10, "use_v2_feature_versioning": True},
                            {"id": 11, "use_v2_feature_versioning": False},
                            {"id": 12},
                        ]
                    )
                ),
                ScriptedResponse(json=_page([{"id": 100}])),
                ScriptedResponse(json=_page([{"uuid": "v-1", "created_at": "2026-09-01T00:00:00Z"}])),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"uuid": "v-1", "created_at": "2026-09-01T00:00:00Z", "_environment_id": "10", "_feature_id": "100"}
        ]
        assert [url for url in result.urls if "/versions/" in url] == [
            f"{API_BASE}/environments/10/features/100/versions/?page_size=100"
        ]


class TestGetRowsThreeLevelFanout:
    # Evaluation data and segment members each need three identifiers per request: a project and a
    # resource inside it in the path, plus an environment of that project as a required filter.

    def test_evaluation_data_pairs_features_with_environments_of_the_same_project(self):
        result = _driver().run(
            "evaluation_data",
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(json=_page([{"id": 10}, {"id": 11}])),
                ScriptedResponse(json=_page([{"id": 100}])),
                ScriptedResponse(json=[{"day": "2026-09-01", "count": 5, "labels": None}]),
                ScriptedResponse(json=[{"day": "2026-09-01", "count": 5, "labels": None}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {
                "day": "2026-09-01",
                "count": 5,
                "labels": None,
                "_project_id": "1",
                "_feature_id": "100",
                "_environment_id": "10",
            },
            {
                "day": "2026-09-01",
                "count": 5,
                "labels": None,
                "_project_id": "1",
                "_feature_id": "100",
                "_environment_id": "11",
            },
        ]
        assert [url for url in result.urls if "/evaluation-data/" in url] == [
            f"{API_BASE}/projects/1/features/100/evaluation-data/?environment_id=10&period=30",
            f"{API_BASE}/projects/1/features/100/evaluation-data/?environment_id=11&period=30",
        ]

    @mock.patch(BUDGET_PATH, 4)
    def test_repeating_body_cursor_is_capped(self):
        # A host that keeps returning the same `next_cursor` would page forever; the shared budget
        # has to terminate it just as it does a cyclic `next` link.
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if "/members/" in request.path:
                return ScriptedResponse(json={"results": [{"identity_key": "k"}], "next_cursor": "same"})
            if request.path.endswith("/projects/"):
                return ScriptedResponse(json=[{"id": 1}])
            if request.path.endswith("/environments/"):
                return ScriptedResponse(json=_page([{"id": 10}]))
            return ScriptedResponse(json=_page([{"id": 300}]))

        result = _driver().run("segment_members", answer)

        assert result.raised is None
        assert len(result.requests) == 4


class TestErrors:
    def test_4xx_raises(self):
        result = _driver().run("organisations", [ScriptedResponse(status=403, json={})])

        assert isinstance(result.raised, Exception)
        assert "403 Client Error" in str(result.raised)


class TestReadBounded:
    # A customer-controlled self-hosted host could return an arbitrarily large or slow-dripped
    # body; these guard that the byte cap and transfer deadline both fail the read.
    def test_raises_when_body_exceeds_byte_cap(self):
        resp = mock.MagicMock()
        resp.iter_content.return_value = iter([b"x" * 10, b"y" * 10])
        with pytest.raises(FlagsmithResponseTooLargeError):
            _read_bounded(resp, max_bytes=15)

    def test_aborts_when_read_blocks_past_deadline(self):
        # A trickle host makes `iter_content` block mid-chunk so no in-loop deadline check runs;
        # the wall-clock deadline must still abort the read and close the response to unblock it.
        blocker = threading.Event()

        def _stalled_iter(*args, **kwargs):
            blocker.wait(timeout=10)
            yield b"late"

        resp = mock.MagicMock()
        resp.iter_content.side_effect = _stalled_iter
        try:
            with pytest.raises(FlagsmithResponseTimeoutError):
                _read_bounded(resp, max_bytes=100, max_seconds=0.1)
            resp.close.assert_called_once()
        finally:
            blocker.set()


class TestFlagsmithSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = FLAGSMITH_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None

    def test_users_use_composite_primary_key(self):
        # A user can belong to more than one organisation, so `id` alone would collide.
        assert FLAGSMITH_ENDPOINTS["users"].primary_keys == ["id", "_organisation_id"]

    @pytest.mark.parametrize("endpoint", [e for e, c in FLAGSMITH_ENDPOINTS.items() if c.partition_key])
    def test_partition_keys_are_stable_creation_timestamps(self, endpoint):
        # Partitioning on a mutable field rewrites partitions every sync. `day` is the evaluation
        # bucket a usage row belongs to, which never moves even as its count is refreshed.
        assert FLAGSMITH_ENDPOINTS[endpoint].partition_key in ("created_date", "created_at", "day")
