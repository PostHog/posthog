import json
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sonatypenexus import (
    SonatypeNexusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.settings import (
    ENDPOINTS,
    SONATYPE_NEXUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.sonatype_nexus import (
    SonatypeNexusPaginationError,
    SonatypeNexusResponseTimeoutError,
    SonatypeNexusResponseTooLargeError,
    SonatypeNexusResumeConfig,
    SonatypeNexusRetryableError,
    _fetch_page,
    _read_bounded,
    normalize_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.source import SonatypeNexusSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.sonatype_nexus"

# `_fetch_page` is wrapped by tenacity's @retry; call the underlying function directly so a
# retryable status raises immediately instead of sleeping through the backoff schedule.
_fetch_undecorated = _fetch_page.__wrapped__  # type: ignore[attr-defined]

_REPOSITORIES = [
    {"name": "maven-releases", "format": "maven2", "type": "hosted"},
    {"name": "maven-public", "format": "maven2", "type": "group"},
    {"name": "docker-proxy", "format": "docker", "type": "proxy"},
]


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    # Bodies are streamed and read through iter_content + json.loads, never .json(), and
    # `_fetch_page` reads the response inside a `with` block.
    payload = json.dumps(body).encode()
    resp.iter_content = mock.Mock(side_effect=lambda chunk_size: iter([payload]))
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def _page(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _run(endpoint: str, script: Script, resume_state: SonatypeNexusResumeConfig | None = None) -> DriveResult:
    config = SonatypeNexusSourceConfig(host="https://n.example.com", username="u", password="p")
    return SourceDriver(SonatypeNexusSource(), config).run(endpoint, script, resume_state=resume_state)


def _streaming_response(chunks: list[bytes], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.iter_content = mock.Mock(side_effect=lambda chunk_size: iter(chunks))
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://nexus.example.com", "https://nexus.example.com"),
            ("nexus.example.com", "https://nexus.example.com"),
            ("https://nexus.example.com/", "https://nexus.example.com"),
            ("http://nexus.internal:8081", "http://nexus.internal:8081"),
            # A pasted API base URL is tolerated by trimming the REST path suffix.
            ("https://nexus.example.com/service/rest/v1", "https://nexus.example.com"),
            ("https://nexus.example.com/service/rest/v1/", "https://nexus.example.com"),
            ("https://nexus.example.com/service/rest", "https://nexus.example.com"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "ftp://example.com",
            "https://",
            # SSRF: urlparse reads the host as example.com but urllib3 connects to
            # 127.0.0.1 (backslash / userinfo confusion), so these must be rejected.
            r"http://127.0.0.1\@example.com",
            r"http://127.0.0.1%5c@example.com",
            "https://user@127.0.0.1",
        ],
    )
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    @pytest.mark.parametrize(
        "cloud, host, expect_raise",
        [
            # On cloud the credentials would egress over the public internet, so
            # plaintext http is rejected while https is fine.
            (True, "http://nexus.example.com", True),
            (True, "https://nexus.example.com", False),
            # Self-hosted operators control their network path, so http stays allowed.
            (False, "http://nexus.internal:8081", False),
        ],
    )
    def test_http_requires_https_only_on_cloud(self, cloud, host, expect_raise):
        with mock.patch(f"{_MODULE}.is_cloud", return_value=cloud):
            if expect_raise:
                with pytest.raises(ValueError):
                    normalize_host(host)
            else:
                assert normalize_host(host) == host


class TestFetchPage:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable_error(self, status_code):
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        with pytest.raises(SonatypeNexusRetryableError):
            _fetch_undecorated(session, "https://x", mock.MagicMock())

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise_for_status(self, status_code):
        session = mock.MagicMock()
        resp = _response({}, status_code=status_code)
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=resp)
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_undecorated(session, "https://x", mock.MagicMock())


class TestReadBounded:
    def test_oversized_body_aborts_instead_of_buffering(self):
        resp = _streaming_response([b"x" * 10, b"x" * 10])
        with pytest.raises(SonatypeNexusResponseTooLargeError):
            _read_bounded(resp, max_bytes=15)

    def test_slow_drip_body_aborts_on_total_deadline(self):
        # A body that stays under the per-read timeout but never finishes is aborted once the
        # total-transfer deadline passes, rather than holding the worker indefinitely.
        resp = _streaming_response([b"x", b"x"])
        with mock.patch(f"{_MODULE}.time.monotonic", side_effect=[0.0, 601.0]):
            with pytest.raises(SonatypeNexusResponseTimeoutError):
                _read_bounded(resp, max_bytes=1_000_000, max_seconds=600)


class TestGetRowsTopLevel:
    def test_repositories_single_fetch_yields_and_stops(self):
        result = _run("repositories", [_page(_REPOSITORIES)])

        assert result.items == [_REPOSITORIES]
        assert result.saved_states == []
        assert len(result.requests) == 1
        assert result.urls[0] == "https://n.example.com/service/rest/v1/repositories"

    def test_tasks_resumes_from_saved_token(self):
        result = _run(
            "tasks",
            [_page({"items": [{"id": "9"}], "continuationToken": None})],
            resume_state=SonatypeNexusResumeConfig(continuation_token="SAVED"),
        )

        assert result.requests[0].param("continuationToken") == "SAVED"

    def test_non_advancing_token_raises(self):
        # A server that keeps returning the same token would loop forever; it must fail instead.
        result = _run("tasks", always(_page({"items": [{"id": "1"}], "continuationToken": "STUCK"})))

        assert isinstance(result.raised, SonatypeNexusPaginationError)

    @mock.patch(f"{_MODULE}.MAX_PAGES_PER_ENDPOINT", 2)
    def test_page_ceiling_raises(self):
        # A server that hands out fresh tokens forever is bounded by the page ceiling.
        result = _run(
            "tasks",
            [
                _page({"items": [{"id": "1"}], "continuationToken": "A"}),
                _page({"items": [{"id": "2"}], "continuationToken": "B"}),
                _page({"items": [{"id": "3"}], "continuationToken": "C"}),
            ],
        )

        assert isinstance(result.raised, SonatypeNexusPaginationError)

    @mock.patch(f"{_MODULE}.MAX_PAGINATION_SECONDS", -1)
    def test_pagination_time_budget_raises(self):
        # Individually valid pages with fresh tokens must still fail once the cumulative
        # wall-clock budget is exhausted, so a slow-drip host can't run until the activity timeout.
        result = _run(
            "tasks",
            [
                _page({"items": [{"id": "1"}], "continuationToken": "A"}),
                _page({"items": [{"id": "2"}], "continuationToken": "B"}),
            ],
        )

        assert isinstance(result.raised, SonatypeNexusPaginationError)


class TestGetRowsRepositoryFanout:
    def test_resumes_from_bookmarked_repository_and_token(self):
        result = _run(
            "components",
            [
                _page(_REPOSITORIES),
                _page({"items": [{"id": "m1"}], "continuationToken": None}),
            ],
            resume_state=SonatypeNexusResumeConfig(continuation_token="SAVED", repository="maven-releases"),
        )

        assert [row["id"] for batch in result.items for row in batch] == ["m1"]
        # docker-proxy sorts before the bookmark, so it is skipped entirely.
        assert len(result.urls) == 2
        assert "repository=maven-releases" in result.urls[1]
        assert "continuationToken=SAVED" in result.urls[1]

    def test_repository_deleted_mid_sync_is_skipped(self):
        result = _run(
            "components",
            [
                _page(_REPOSITORIES),
                _page({}, status_code=404),
                _page({"items": [{"id": "m1"}], "continuationToken": None}),
            ],
        )

        # docker-proxy 404s (deleted between enumeration and fetch) and is skipped;
        # maven-releases still syncs.
        assert [row["id"] for batch in result.items for row in batch] == ["m1"]

    def test_non_advancing_token_raises(self):
        # A repository whose pages never advance the token must fail rather than loop forever.
        result = _run(
            "components",
            [
                _page(_REPOSITORIES),
                _page({"items": [{"id": "d1"}], "continuationToken": "STUCK"}),
                _page({"items": [{"id": "d2"}], "continuationToken": "STUCK"}),
            ],
        )

        assert isinstance(result.raised, SonatypeNexusPaginationError)

    @mock.patch(f"{_MODULE}.MAX_PAGINATION_SECONDS", -1)
    def test_pagination_time_budget_raises(self):
        # A per-repository walk of individually valid small pages must fail once the cumulative
        # wall-clock budget is exhausted, independent of the per-response transfer deadline.
        result = _run(
            "components",
            [
                _page(_REPOSITORIES),
                _page({"items": [{"id": "d1"}], "continuationToken": "A"}),
                _page({"items": [{"id": "d2"}], "continuationToken": "B"}),
            ],
        )

        assert isinstance(result.raised, SonatypeNexusPaginationError)

    @mock.patch(f"{_MODULE}.MAX_PAGINATION_SECONDS", -1)
    def test_pagination_time_budget_raises_on_terminal_pages(self):
        # A host that slow-drips a single terminal page (no continuation token) per repository
        # must still trip the cumulative deadline — the check runs after every response, not only
        # before continuing to a next page, so terminal pages can't bypass it across many repos.
        result = _run(
            "components",
            [
                _page(_REPOSITORIES),
                _page({"items": [{"id": "d1"}], "continuationToken": None}),
                _page({"items": [{"id": "m1"}], "continuationToken": None}),
            ],
        )

        assert isinstance(result.raised, SonatypeNexusPaginationError)


class TestGetRowsUsers:
    @pytest.mark.parametrize(
        "all_users, expected_external",
        [
            ([{"userId": "admin", "source": "default"}, {"userId": "jdoe", "source": "LDAP"}], [("LDAP", "jdoe")]),
            # A user id is unique only within its source, so a SAML user named like a local user is kept.
            ([{"userId": "admin", "source": "default"}, {"userId": "admin", "source": "SAML"}], [("SAML", "admin")]),
            ([{"userId": "admin", "source": "default"}], []),
            ([], []),
        ],
    )
    def test_local_users_in_full_then_only_external_users_from_cross_source_search(self, all_users, expected_external):
        local_users = [{"userId": "admin", "source": "default"}, {"userId": "ci-bot", "source": "default"}]

        result = _run("users", [_page(local_users), _page(all_users)])

        assert result.raised is None
        assert result.params("source") == ["default", None]
        assert [(row["source"], row["userId"]) for row in result.rows] == [
            ("default", "admin"),
            ("default", "ci-bot"),
            *expected_external,
        ]


_QUOTA = {"type": "spaceUsedQuota", "limit": 1024}


class TestGetRowsBlobStores:
    @pytest.mark.parametrize(
        "blob_store, script, expected_quota",
        [
            (
                {"name": "default", "softQuota": _QUOTA},
                [
                    _page(
                        {"isViolation": True, "message": "Blob store default is over quota", "blobStoreName": "default"}
                    )
                ],
                (True, "Blob store default is over quota"),
            ),
            # Without a soft quota, or for an unavailable blob store, no quota status is requested.
            ({"name": "default", "softQuota": None}, [], (None, None)),
            ({"name": "default"}, [], (None, None)),
            ({"name": "default", "softQuota": _QUOTA, "unavailable": True}, [], (None, None)),
        ],
    )
    def test_quota_status_merged_into_blob_store_row(self, blob_store, script, expected_quota):
        result = _run("blob_stores", [_page([blob_store]), *script])

        assert result.raised is None
        assert len(result.requests) == 1 + len(script)
        assert [(row["name"], row["quotaViolation"], row["quotaMessage"]) for row in result.rows] == [
            ("default", *expected_quota)
        ]

    def test_blob_store_deleted_before_quota_status_is_skipped_and_name_is_encoded(self):
        result = _run(
            "blob_stores",
            [
                _page([{"name": "s3 store/a", "softQuota": _QUOTA}, {"name": "default", "softQuota": _QUOTA}]),
                _page({}, status_code=404),
                _page({"isViolation": False, "message": "ok", "blobStoreName": "default"}),
            ],
        )

        assert result.raised is None
        assert result.urls[1] == "https://n.example.com/service/rest/v1/blobstores/s3%20store%2Fa/quota-status"
        assert [row["name"] for row in result.rows] == ["default"]

    def test_quota_status_forbidden_fails_the_sync(self):
        result = _run("blob_stores", [_page([{"name": "default", "softQuota": _QUOTA}]), _page({}, status_code=403)])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.rows == []


class TestSonatypeNexusSource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_primary_keys_and_no_partitioning(self, endpoint):
        config = SONATYPE_NEXUS_ENDPOINTS[endpoint]
        result = _run(endpoint, [_page({"items": []})])
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # No Nexus endpoint has a universally-populated stable timestamp, so
        # nothing is datetime-partitioned.
        assert response.partition_mode is None
        assert response.partition_keys is None
