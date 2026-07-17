import json
import threading
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith import (
    DEFAULT_BASE_URL,
    FlagsmithResponseTimeoutError,
    FlagsmithResponseTooLargeError,
    FlagsmithResumeConfig,
    _initial_url,
    _pinned_next_url,
    _read_bounded,
    flagsmith_source,
    get_rows,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.settings import (
    ENDPOINTS,
    FLAGSMITH_ENDPOINTS,
)

API_BASE = f"{DEFAULT_BASE_URL}/api/v1"
SESSION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.make_tracked_session"
)
BUDGET_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.MAX_PAGES_PER_SYNC"
PARENTS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.MAX_FANOUT_PARENTS"
KEY_LENGTH_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith.MAX_FANOUT_KEY_LENGTH"
)


def _make_manager(resume_state: FlagsmithResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(results: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


def _resp(data: Any, status_code: int = 200) -> mock.MagicMock:
    # `_fetch_page` streams the body (`with session.get(..., stream=True) as response`) and reads
    # it via `_read_bounded`/`iter_content`, so the mock must act as its own context manager and
    # expose the JSON-encoded body through `iter_content`.
    resp = mock.MagicMock()
    body = json.dumps(data).encode()
    resp.iter_content.side_effect = lambda *args, **kwargs: iter([body])
    resp.json.return_value = data
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _probe_resp(status_code: int = 200) -> mock.MagicMock:
    # validate_credentials reads the status via `with session.get(..., stream=True) as response`.
    resp = mock.MagicMock(status_code=status_code)
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


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

    @pytest.mark.parametrize(
        "next_link, expected",
        [
            (f"{API_BASE}/organisations/?page=2", f"{API_BASE}/organisations/?page=2"),
            # A next link pointing at another host is rebuilt onto the configured base.
            ("https://evil.example.com/api/v1/organisations/?page=2", f"{API_BASE}/organisations/?page=2"),
            ("http://proxy.internal/api/v1/audit/?page=3&page_size=100", f"{API_BASE}/audit/?page=3&page_size=100"),
            (None, None),
            ("", None),
        ],
    )
    def test_pinned_next_url(self, next_link, expected):
        assert _pinned_next_url(DEFAULT_BASE_URL, next_link) == expected

    def test_initial_url_appends_params_to_path_with_query(self):
        url = _initial_url(DEFAULT_BASE_URL, "/environments/?project=1", {"page_size": 100})
        assert url == f"{API_BASE}/environments/?project=1&page_size=100"


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(SESSION_PATH)
    def test_returns_status_code(self, mock_session, status_code):
        mock_session.return_value.get.return_value = _probe_resp(status_code)
        assert validate_credentials("key", None) == status_code

    @mock.patch(SESSION_PATH)
    def test_uses_api_key_prefix(self, mock_session):
        mock_session.return_value.get.return_value = _probe_resp(200)
        validate_credentials("org-key", None)
        call = mock_session.return_value.get.call_args
        assert call.kwargs["headers"]["Authorization"] == "Api-Key org-key"
        assert call.args[0] == f"{API_BASE}/organisations/"

    @mock.patch(SESSION_PATH)
    def test_uses_custom_base_url(self, mock_session):
        mock_session.return_value.get.return_value = _probe_resp(200)
        validate_credentials("org-key", "https://flagsmith.example.com", "/projects/")
        assert mock_session.return_value.get.call_args.args[0] == "https://flagsmith.example.com/api/v1/projects/"

    @mock.patch(SESSION_PATH)
    def test_streams_probe_without_downloading_body(self, mock_session):
        # A hostile base_url must not be able to occupy the API worker with an endless body: the
        # probe streams and returns the status without consuming the body.
        resp = _probe_resp(200)
        mock_session.return_value.get.return_value = resp
        validate_credentials("key", None)
        assert mock_session.return_value.get.call_args.kwargs["stream"] is True
        resp.iter_content.assert_not_called()

    @mock.patch(SESSION_PATH)
    def test_returns_none_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", None) is None


class TestGetRowsTopLevel:
    @mock.patch(SESSION_PATH)
    def test_paginates_via_drf_next(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_page([{"id": 1}, {"id": 2}], f"{API_BASE}/organisations/?page=2")),
            _resp(_page([{"id": 3}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", None, "organisations", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == [1, 2, 3]
        # State saved after every page (final save records the empty next_url marker).
        saved_urls = [call.args[0].next_url for call in manager.save_state.call_args_list]
        assert saved_urls == [f"{API_BASE}/organisations/?page=2", ""]

    @mock.patch(SESSION_PATH)
    def test_projects_plain_array_yields_rows(self, mock_session):
        mock_session.return_value.get.return_value = _resp([{"id": 10}, {"id": 11}])

        batches = list(get_rows("key", None, "projects", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == [10, 11]
        assert mock_session.return_value.get.call_args.args[0] == f"{API_BASE}/projects/"

    @mock.patch(SESSION_PATH)
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_page([{"id": 9}], None))

        resume_url = f"{API_BASE}/organisations/?page=5"
        manager = _make_manager(FlagsmithResumeConfig(next_url=resume_url))

        list(get_rows("key", None, "organisations", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(SESSION_PATH)
    def test_resume_url_repinned_to_configured_base(self, mock_session):
        # A resume URL persisted before the source was retargeted must be re-pinned onto the current
        # base, or the current API key would be replayed to the previously configured (attacker) host.
        mock_session.return_value.get.return_value = _resp(_page([{"id": 9}], None))
        stale = "https://old-host.example.com/api/v1/organisations/?page=5"
        manager = _make_manager(FlagsmithResumeConfig(next_url=stale))

        list(get_rows("key", None, "organisations", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == f"{API_BASE}/organisations/?page=5"

    @mock.patch(SESSION_PATH)
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_page([], None))

        assert list(get_rows("key", None, "organisations", mock.MagicMock(), _make_manager())) == []

    @mock.patch(BUDGET_PATH, 5)
    @mock.patch(SESSION_PATH)
    def test_cyclic_next_link_is_capped(self, mock_session):
        # A hostile self-hosted host can return a non-empty `next` forever; pagination must
        # self-terminate at the page budget instead of looping on credentialed requests.
        mock_session.return_value.get.return_value = _resp(_page([{"id": 1}], f"{API_BASE}/organisations/?page=next"))

        manager = _make_manager()
        batches = list(get_rows("key", None, "organisations", mock.MagicMock(), manager))

        assert len(batches) == 5
        # Terminal resume state so a resume advances past the cyclic resource, not back into it.
        assert manager.save_state.call_args_list[-1].args[0].next_url == ""


class TestGetRowsFanout:
    @mock.patch(SESSION_PATH)
    def test_features_fan_out_per_project(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp([{"id": 1}, {"id": 2}]),  # projects (plain array)
            _resp(_page([{"id": 100, "name": "flag-a"}], None)),
            _resp(_page([{"id": 200, "name": "flag-b"}], None)),
        ]

        batches = list(get_rows("key", None, "features", mock.MagicMock(), _make_manager()))

        rows = [row for batch in batches for row in batch]
        assert rows == [
            {"id": 100, "name": "flag-a", "_project_id": "1"},
            {"id": 200, "name": "flag-b", "_project_id": "2"},
        ]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[0] == f"{API_BASE}/projects/"
        assert urls[1] == f"{API_BASE}/projects/1/features/?page_size=100&sort_field=created_date&sort_direction=ASC"
        assert urls[2] == f"{API_BASE}/projects/2/features/?page_size=100&sort_field=created_date&sort_direction=ASC"

    @mock.patch(SESSION_PATH)
    def test_environments_fan_out_uses_project_query_param(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp([{"id": 7}]),
            _resp(_page([{"id": 70, "api_key": "env-key"}], None)),
        ]

        batches = list(get_rows("key", None, "environments", mock.MagicMock(), _make_manager()))

        assert [row for batch in batches for row in batch] == [{"id": 70, "api_key": "env-key", "_project_id": "7"}]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[1] == f"{API_BASE}/environments/?project=7"

    @mock.patch(SESSION_PATH)
    def test_feature_states_enumerate_environments_via_projects(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp([{"id": 1}]),  # projects
            _resp(_page([{"id": 10, "api_key": "env-a"}, {"id": 11, "api_key": "env-b"}], None)),  # environments
            _resp(_page([{"id": 1000, "enabled": True}], None)),  # featurestates env-a
            _resp(_page([{"id": 2000, "enabled": False}], None)),  # featurestates env-b
        ]

        batches = list(get_rows("key", None, "feature_states", mock.MagicMock(), _make_manager()))

        rows = [row for batch in batches for row in batch]
        assert rows == [
            {"id": 1000, "enabled": True, "_environment_api_key": "env-a"},
            {"id": 2000, "enabled": False, "_environment_api_key": "env-b"},
        ]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[2] == f"{API_BASE}/environments/env-a/featurestates/"
        assert urls[3] == f"{API_BASE}/environments/env-b/featurestates/"

    @mock.patch(SESSION_PATH)
    def test_users_fan_out_injects_organisation_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_page([{"id": 5}], None)),  # organisations
            _resp([{"id": 500, "email": "a@example.com"}]),  # users (plain array)
        ]

        batches = list(get_rows("key", None, "users", mock.MagicMock(), _make_manager()))

        assert [row for batch in batches for row in batch] == [
            {"id": 500, "email": "a@example.com", "_organisation_id": "5"}
        ]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[1] == f"{API_BASE}/organisations/5/users/"

    @mock.patch(SESSION_PATH)
    def test_resume_skips_completed_parent(self, mock_session):
        # Project 1 finished last run (empty next_url marker); resume must start at project 2.
        mock_session.return_value.get.side_effect = [
            _resp([{"id": 1}, {"id": 2}]),
            _resp(_page([{"id": 200}], None)),
        ]
        manager = _make_manager(FlagsmithResumeConfig(next_url="", parent_key="1"))

        batches = list(get_rows("key", None, "segments", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == [200]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [f"{API_BASE}/projects/", f"{API_BASE}/projects/2/segments/?page_size=100"]

    @mock.patch(SESSION_PATH)
    def test_resume_midparent_uses_saved_url(self, mock_session):
        resume_url = f"{API_BASE}/projects/1/segments/?page=3&page_size=100"
        mock_session.return_value.get.side_effect = [
            _resp([{"id": 1}, {"id": 2}]),
            _resp(_page([{"id": 150}], None)),
            _resp(_page([{"id": 250}], None)),
        ]
        manager = _make_manager(FlagsmithResumeConfig(next_url=resume_url, parent_key="1"))

        list(get_rows("key", None, "segments", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [
            f"{API_BASE}/projects/",
            resume_url,
            f"{API_BASE}/projects/2/segments/?page_size=100",
        ]

    @mock.patch(SESSION_PATH)
    def test_fan_out_resume_url_repinned_to_configured_base(self, mock_session):
        # Same host-pinning guarantee on the fan-out resume path: a stale mid-parent URL must be
        # re-pinned to the current base rather than replayed to a since-changed host.
        stale = "https://old-host.example.com/api/v1/projects/1/segments/?page=3&page_size=100"
        mock_session.return_value.get.side_effect = [
            _resp([{"id": 1}, {"id": 2}]),
            _resp(_page([{"id": 150}], None)),
            _resp(_page([{"id": 250}], None)),
        ]
        manager = _make_manager(FlagsmithResumeConfig(next_url=stale, parent_key="1"))

        list(get_rows("key", None, "segments", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[1] == f"{API_BASE}/projects/1/segments/?page=3&page_size=100"

    @mock.patch(SESSION_PATH)
    def test_no_parents_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _resp([])

        assert list(get_rows("key", None, "features", mock.MagicMock(), _make_manager())) == []

    @mock.patch(BUDGET_PATH, 5)
    @mock.patch(SESSION_PATH)
    def test_budget_is_shared_across_fan_out_parents(self, mock_session):
        # Many parents, each with a cyclic child `next`. A per-parent cap would multiply into
        # budget-per-parent requests; the shared budget bounds the whole invocation instead.
        def _get(url, **kwargs):
            if "/features/" in url:
                return _resp(_page([{"id": 1}], f"{API_BASE}/projects/1/features/?page=next"))
            return _resp([{"id": 1}, {"id": 2}, {"id": 3}])  # projects (plain array, one fetch)

        mock_session.return_value.get.side_effect = _get

        list(get_rows("key", None, "features", mock.MagicMock(), _make_manager()))

        # 1 projects fetch + 4 feature fetches = the whole 5-page budget, not 5 per parent.
        assert mock_session.return_value.get.call_count == 5

    @mock.patch(PARENTS_PATH, 2)
    @mock.patch(SESSION_PATH)
    def test_fan_out_parent_count_is_capped(self, mock_session):
        # A hostile host can return a huge parent list in one page; enumeration must stop at the
        # cap so the retained parent list can't exhaust worker memory (only capped parents fan out).
        def _get(url, **kwargs):
            if url.endswith("/projects/"):
                return _resp([{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}])
            return _resp(_page([{"id": 100}], None))

        mock_session.return_value.get.side_effect = _get

        list(get_rows("key", None, "features", mock.MagicMock(), _make_manager()))

        child_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/features/" in c.args[0]]
        assert len(child_urls) == 2  # only the first 2 of 4 projects enumerated

    @mock.patch(KEY_LENGTH_PATH, 5)
    @mock.patch(SESSION_PATH)
    def test_oversized_parent_key_is_skipped(self, mock_session):
        # A hostile host can return an arbitrarily long id/api_key; over-length keys must be dropped
        # so they can't balloon the retained list or be interpolated into a child request URL.
        def _get(url, **kwargs):
            if url.endswith("/projects/"):
                return _resp([{"id": "x" * 50}, {"id": 2}])
            return _resp(_page([{"id": 100}], None))

        mock_session.return_value.get.side_effect = _get

        list(get_rows("key", None, "features", mock.MagicMock(), _make_manager()))

        child_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/features/" in c.args[0]]
        assert child_urls == [
            f"{API_BASE}/projects/2/features/?page_size=100&sort_field=created_date&sort_direction=ASC"
        ]


class TestErrors:
    @mock.patch(SESSION_PATH)
    def test_4xx_raises(self, mock_session):
        resp = _resp({}, status_code=403)
        resp.raise_for_status.side_effect = Exception("403 Client Error")
        mock_session.return_value.get.return_value = resp

        with pytest.raises(Exception, match="403 Client Error"):
            list(get_rows("key", None, "organisations", mock.MagicMock(), _make_manager()))


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
        response = flagsmith_source("key", None, endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_users_use_composite_primary_key(self):
        # A user can belong to more than one organisation, so `id` alone would collide.
        assert FLAGSMITH_ENDPOINTS["users"].primary_keys == ["id", "_organisation_id"]

    @pytest.mark.parametrize("endpoint", [e for e, c in FLAGSMITH_ENDPOINTS.items() if c.partition_key])
    def test_partition_keys_are_stable_creation_timestamps(self, endpoint):
        # Partitioning on a mutable field rewrites partitions every sync.
        assert FLAGSMITH_ENDPOINTS[endpoint].partition_key in ("created_date", "created_at")
