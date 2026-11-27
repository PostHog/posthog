import threading
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.sources.jenkins import jenkins
from products.warehouse_sources.sources.jenkins._config import JenkinsSourceConfig
from products.warehouse_sources.sources.jenkins.jenkins import (
    JenkinsResumeConfig,
    _build_change_rows,
    _discover_jobs,
    _is_job_container,
    _iter_job_builds,
    _pin_job_url,
    _to_epoch_ms,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.sources.jenkins.source import JenkinsSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)

HOST = "https://jenkins.example.com"


def _driver() -> SourceDriver:
    return SourceDriver(JenkinsSource(), JenkinsSourceConfig(host=HOST, username="user", api_token="token"))


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    return [row for table in result.items for row in table.to_pylist()]


def _resp(payload: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            ("adds_https_scheme", "jenkins.example.com", "https://jenkins.example.com"),
            ("keeps_http", "http://jenkins.local", "http://jenkins.local"),
            ("strips_trailing_slash", "https://jenkins.example.com/", "https://jenkins.example.com"),
            ("keeps_subpath", "https://ci.example.com/jenkins", "https://ci.example.com/jenkins"),
        ]
    )
    def test_normalizes(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    @parameterized.expand(
        [
            # Each of these would let the dialed host diverge from the host the SSRF allowlist checks,
            # or is otherwise not a plain http(s) base URL.
            ("empty", ""),
            ("blank", "   "),
            ("backslash_host_spoof", "https://169.254.169.254\\@internal"),
            ("userinfo_hides_host", "https://user@evil.example.com"),
            ("bad_scheme", "ftp://jenkins.example.com"),
            ("has_query", "https://jenkins.example.com?a=1"),
            ("has_fragment", "https://jenkins.example.com#frag"),
        ]
    )
    def test_rejects(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(raw)


class TestPinJobUrl:
    @parameterized.expand(
        [
            # Response-supplied job URLs are fetched with the stored Basic credentials, so only their
            # path may be trusted — an off-origin URL must be re-anchored, never dialed as returned.
            ("same_origin_passthrough", "https://j/job/svc/", "https://j/job/svc/"),
            ("off_host_reanchored", "http://evil.example/steal/", "https://j/steal/"),
            ("internal_ip_reanchored", "http://169.254.169.254/latest/", "https://j/latest/"),
            ("userinfo_dropped", "https://user:pw@j/job/svc/", "https://j/job/svc/"),
            ("query_and_fragment_dropped", "https://j/job/svc/?a=1#f", "https://j/job/svc/"),
            ("backslash_rejected", "https://j\\@evil/job/", None),
            ("relative_path_rejected", "job/svc/", None),
            ("non_string_rejected", 123, None),
            ("none_rejected", None, None),
        ]
    )
    def test_pins_to_configured_origin(self, _name: str, url: Any, expected: str | None) -> None:
        assert _pin_job_url("https://j", url) == expected


class TestIsJobContainer:
    @parameterized.expand(
        [
            ("folder", "com.cloudbees.hudson.plugins.folder.Folder", True),
            ("org_folder", "jenkins.branch.OrganizationFolder", True),
            ("multibranch", "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject", True),
            ("freestyle", "hudson.model.FreeStyleProject", False),
            ("pipeline", "org.jenkinsci.plugins.workflow.job.WorkflowJob", False),
            ("missing_class", None, False),
        ]
    )
    def test_container_detection(self, _name: str, cls: str | None, expected: bool) -> None:
        # Mis-detecting containers would either skip nested jobs (false negative) or issue a
        # pointless recursion into a leaf job (false positive), so the suffix match is load-bearing.
        assert _is_job_container({"_class": cls} if cls is not None else {}) is expected


class TestToEpochMs:
    @parameterized.expand(
        [
            # Jenkins build timestamps are epoch milliseconds; the watermark must be compared in ms,
            # so a datetime cursor has to be scaled up by 1000 (a seconds bug would break incremental).
            ("utc_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), 1767323045000),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), 1767323045000),
            ("date_value", date(2026, 1, 2), 1767312000000),
            ("iso_string", "2026-01-02T03:04:05Z", 1767323045000),
            ("passthrough_int", 1767323045000, 1767323045000),
            ("none", None, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_epoch_ms(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_epoch_ms(value) == expected


class TestIterJobBuilds:
    def _builds(self, *timestamps: int) -> list[dict[str, Any]]:
        return [{"number": i, "url": f"https://j/{i}/", "timestamp": ts} for i, ts in enumerate(timestamps)]

    def test_stops_at_watermark(self) -> None:
        # Newest-first; watermark falls between the 2nd and 3rd builds, so only the two newer ones
        # (>= watermark) are emitted and the walk stops without paging further.
        page = self._builds(3000, 2000, 1000)
        with mock.patch.object(jenkins, "_fetch", return_value=_resp({"builds": page})) as fetch:
            rows = list(_iter_job_builds(MagicMock(), "https://j/", ("u", "t"), MagicMock(), watermark_ms=2000))
        assert [r["timestamp"] for r in rows] == [3000, 2000]
        assert fetch.call_count == 1

    def test_advances_index_window_across_full_pages(self) -> None:
        # A full page means more builds may remain, so the window must advance; a short page ends it.
        pages = [_resp({"builds": self._builds(4000, 3000)}), _resp({"builds": self._builds(2000)})]
        with mock.patch.object(jenkins, "BUILDS_PAGE_SIZE", 2):
            with mock.patch.object(jenkins, "_fetch", side_effect=pages) as fetch:
                rows = list(_iter_job_builds(MagicMock(), "https://j/", ("u", "t"), MagicMock(), watermark_ms=None))
        assert fetch.call_count == 2
        assert len(rows) == 3

    def test_empty_page_terminates(self) -> None:
        with mock.patch.object(jenkins, "_fetch", return_value=_resp({"builds": []})) as fetch:
            rows = list(_iter_job_builds(MagicMock(), "https://j/", ("u", "t"), MagicMock(), watermark_ms=None))
        assert rows == []
        assert fetch.call_count == 1

    def test_stops_at_page_cap(self) -> None:
        # A server returning a full page for every window would loop forever; the page cap bounds it.
        full_page = _resp({"builds": self._builds(2, 1)})
        with mock.patch.object(jenkins, "BUILDS_PAGE_SIZE", 2):
            with mock.patch.object(jenkins, "MAX_BUILD_PAGES_PER_JOB", 3):
                with mock.patch.object(jenkins, "_fetch", return_value=full_page) as fetch:
                    rows = list(_iter_job_builds(MagicMock(), "https://j/", ("u", "t"), MagicMock(), watermark_ms=None))
        assert fetch.call_count == 3
        assert len(rows) == 6


class TestDiscoverJobs:
    def test_recurses_into_containers_and_dedupes(self) -> None:
        root = {
            "jobs": [
                {"name": "svc", "url": "https://j/job/svc/", "_class": "hudson.model.FreeStyleProject"},
                {"name": "team", "url": "https://j/job/team/", "_class": "com.cloudbees.hudson.plugins.folder.Folder"},
            ]
        }
        team = {
            "jobs": [
                {
                    "name": "api",
                    "url": "https://j/job/team/job/api/",
                    "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                },
                # A plugin linking the folder back to an already-seen job must not be re-emitted.
                {"name": "svc", "url": "https://j/job/svc/", "_class": "hudson.model.FreeStyleProject"},
            ]
        }

        def fake_fetch(_session: Any, url: str, *_args: Any, **_kwargs: Any) -> MagicMock:
            return _resp(team) if "team" in url else _resp(root)

        with mock.patch.object(jenkins, "_fetch", side_effect=fake_fetch):
            urls = [job["url"] for job in _discover_jobs(MagicMock(), "https://j", ("u", "t"), MagicMock())]

        assert sorted(urls) == ["https://j/job/svc/", "https://j/job/team/", "https://j/job/team/job/api/"]

    def test_off_origin_job_urls_are_never_fetched(self) -> None:
        # A compromised response marks an attacker URL as a buildable folder; recursion and the
        # yielded row must both stay pinned to the configured origin so the Basic credentials are
        # never sent off-instance.
        root = {
            "jobs": [
                {
                    "name": "evil",
                    "url": "http://evil.example/exfil/",
                    "_class": "com.cloudbees.hudson.plugins.folder.Folder",
                    "buildable": True,
                },
            ]
        }

        fetched: list[str] = []

        def fake_fetch(_session: Any, url: str, *_args: Any, **_kwargs: Any) -> MagicMock:
            fetched.append(url)
            return _resp(root if len(fetched) == 1 else {"jobs": []})

        with mock.patch.object(jenkins, "_fetch", side_effect=fake_fetch):
            rows = list(_discover_jobs(MagicMock(), "https://j", ("u", "t"), MagicMock()))

        assert [r["url"] for r in rows] == ["https://j/exfil/"]
        assert all(url.startswith("https://j/") for url in fetched)

    def test_respects_total_job_budget(self) -> None:
        # Breadth cap: a server returning a huge flat fan-out must stop once the budget is hit rather
        # than yielding (and, for folders, recursing into) an unbounded number of jobs.
        many = {
            "jobs": [
                {"name": f"j{i}", "url": f"https://j/job/j{i}/", "_class": "hudson.model.FreeStyleProject"}
                for i in range(10)
            ]
        }
        with mock.patch.object(jenkins, "MAX_TOTAL_JOBS", 3):
            with mock.patch.object(jenkins, "_fetch", return_value=_resp(many)):
                rows = list(_discover_jobs(MagicMock(), "https://j", ("u", "t"), MagicMock()))
        assert len(rows) == 3

    def test_respects_depth_cap(self) -> None:
        # Every level returns a folder pointing one level deeper; the cap must bound the fetches so a
        # pathological (or cyclic) folder tree can't loop forever.
        def fake_fetch(_session: Any, url: str, *_args: Any, **_kwargs: Any) -> MagicMock:
            depth = url.count("/job/")
            return _resp(
                {"jobs": [{"name": "f", "url": f"{url.split('/api')[0]}/job/f{depth}/", "_class": "...Folder"}]}
            )

        with mock.patch.object(jenkins, "MAX_JOB_DEPTH", 3):
            with mock.patch.object(jenkins, "_fetch", side_effect=fake_fetch) as fetch:
                list(_discover_jobs(MagicMock(), "https://j", ("u", "t"), MagicMock()))
        # Fetches happen at depths 0, 1, 2; the cap blocks descending to depth 3.
        assert fetch.call_count == 3


class _FakeRaw:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, amt: int, decode_content: bool = False) -> bytes:
        chunk = self._data[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


class _BlockingRaw:
    """A raw stream that blocks on read until the response is closed, then raises.

    Mimics a hostile host that keeps a socket read blocked (under the byte cap and idle socket
    timeout) until the download watchdog closes the connection.
    """

    def __init__(self) -> None:
        self._closed = threading.Event()

    def read(self, amt: int, decode_content: bool = False) -> bytes:
        if self._closed.wait(timeout=5):
            raise OSError("connection closed")
        return b""

    def close(self) -> None:
        self._closed.set()


class _FakeResponse:
    def __init__(self, data: bytes = b"", raw: Any = None) -> None:
        self.raw = raw if raw is not None else _FakeRaw(data)
        self.closed = False
        self._content: bytes | None = None

    def close(self) -> None:
        self.closed = True
        self.raw.close()


class TestReadBodyCapped:
    def test_rejects_response_over_cap(self) -> None:
        # A hostile/misconfigured host returning a body past the cap must raise (and release the
        # connection) instead of buffering the whole thing into worker memory.
        response: Any = _FakeResponse(b"y" * 50)
        with mock.patch.object(jenkins, "MAX_RESPONSE_BYTES", 10):
            with pytest.raises(ValueError):
                jenkins._read_body_capped(response, "https://j/")
        assert response.closed

    def test_caches_body_under_cap(self) -> None:
        # Under the cap the decoded body is cached so downstream `.json()` reads from memory.
        response: Any = _FakeResponse(b'{"ok": true}')
        jenkins._read_body_capped(response, "https://j/")
        assert response._content == b'{"ok": true}'

    def test_aborts_on_download_deadline(self) -> None:
        # A read kept blocked below the socket idle timeout must be cut off by the watchdog closing
        # the response, surfaced as a non-retryable deadline error, rather than holding the worker.
        response: Any = _FakeResponse(raw=_BlockingRaw())
        with mock.patch.object(jenkins, "MAX_DOWNLOAD_SECONDS", 0.05):
            with pytest.raises(ValueError, match="download deadline"):
                jenkins._read_body_capped(response, "https://j/")
        assert response.closed


class TestGetBuildRows:
    def test_resumes_from_saved_bookmark(self) -> None:
        jobs = [
            {"name": name, "url": f"https://jenkins.example.com/{name}/", "buildable": True} for name in ("a", "b", "c")
        ]
        driver = SourceDriver(
            JenkinsSource(),
            JenkinsSourceConfig(host="https://jenkins.example.com", username="user", api_token="token"),
        )
        result = driver.run(
            "builds",
            [
                ScriptedResponse(json={"jobs": jobs}),
                ScriptedResponse(json={"builds": []}),
                ScriptedResponse(json={"builds": []}),
            ],
            resume_state=JenkinsResumeConfig(next_job_url="https://jenkins.example.com/b/"),
        )
        # Only b and c are processed; a (already synced) is skipped.
        assert result.raised is None
        assert result.paths == ["/api/json", "/b/api/json", "/c/api/json"]
        assert result.saved_states == [JenkinsResumeConfig(next_job_url="https://jenkins.example.com/c/")]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, error = validate_credentials("https://jenkins.example.com", "user", "token")
        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert {request.path for request in network.requests_log} == {"/api/json"}
        assert network.requests_log[0].param("tree") == "nodeName"
        assert network.session_options == [{"redact_values": ("token",), "allow_redirects": False}]

    def test_invalid_url_short_circuits_without_request(self) -> None:
        with scripted_network([]) as network:
            ok, error = validate_credentials("https://user@evil.example.com", "user", "token")
        assert ok is False
        assert error is not None
        assert network.requests_log == []
        assert network.session_options == []


class TestSnapshotEndpoints:
    @parameterized.expand(
        [
            (
                "nodes",
                "/computer/api/json",
                {
                    "computer": [
                        {"displayName": "Built-In Node", "numExecutors": 2, "offline": False},
                        {"displayName": "agent-1", "numExecutors": 4, "offline": True},
                        {"numExecutors": 1},
                        "not-a-node",
                    ]
                },
                "displayName",
                ["Built-In Node", "agent-1"],
            ),
            (
                "queue_items",
                "/queue/api/json",
                {
                    "items": [
                        {"id": 11, "why": "Waiting for next available executor", "task": {"name": "svc"}},
                        {"id": 12, "why": "Build #3 is already in progress", "blocked": True},
                        {"why": "no id"},
                    ]
                },
                "id",
                [11, 12],
            ),
        ]
    )
    def test_reads_one_snapshot_and_drops_rows_without_a_key(
        self, endpoint: str, path: str, payload: dict[str, Any], key: str, expected: list[Any]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert result.paths == [path]
        assert [row[key] for row in _rows(result)] == expected


class TestBuildChangeRows:
    @parameterized.expand(
        [
            (
                "freestyle_change_set",
                {"changeSet": {"kind": "git", "items": [{"commitId": "a1", "msg": "fix"}]}},
                [("a1", "git")],
            ),
            (
                "pipeline_change_sets_across_two_repos",
                {
                    "changeSets": [
                        {"kind": "git", "items": [{"commitId": "a1"}, {"commitId": "b2"}]},
                        {"kind": "git", "items": [{"commitId": "c3"}]},
                    ]
                },
                [("a1", "git"), ("b2", "git"), ("c3", "git")],
            ),
            (
                # The same repository checked out twice lists its commits twice; the key is
                # (build_url, commitId), so a duplicate would multi-match on every merge.
                "duplicate_commit_kept_once",
                {
                    "changeSets": [
                        {"kind": "git", "items": [{"commitId": "a1"}]},
                        {"kind": "git", "items": [{"commitId": "a1"}]},
                    ]
                },
                [("a1", "git")],
            ),
            (
                "items_without_commit_id_dropped",
                {
                    "changeSet": {
                        "kind": "svn",
                        "items": [{"msg": "no id"}, {"commitId": ""}, "junk", {"commitId": "r9"}],
                    }
                },
                [("r9", "svn")],
            ),
            ("empty_change_log", {"changeSet": {"kind": None, "items": []}, "changeSets": None}, []),
            ("no_change_fields", {}, []),
        ]
    )
    def test_one_row_per_commit(
        self, _name: str, change_fields: dict[str, Any], expected: list[tuple[str, str | None]]
    ) -> None:
        build = {
            "job_url": "https://j/job/svc/",
            "url": "https://j/job/svc/7/",
            "number": 7,
            "created_at": "2026-01-02T03:04:05+00:00",
            **change_fields,
        }
        rows = list(_build_change_rows(MagicMock(), ("u", "t"), MagicMock(), build))
        assert [(row["commitId"], row["kind"]) for row in rows] == expected
        assert all(
            row["build_url"] == "https://j/job/svc/7/"
            and row["job_url"] == "https://j/job/svc/"
            and row["build_number"] == 7
            and row["created_at"] == "2026-01-02T03:04:05+00:00"
            for row in rows
        )


class TestTestReports:
    JOBS = {"jobs": [{"name": "svc", "url": f"{HOST}/job/svc/", "buildable": True}]}
    BUILDS = {
        "builds": [
            # Still running: no report yet, so no request is made for it.
            {"number": 9, "url": f"{HOST}/job/svc/9/", "timestamp": 1767323045000, "building": True},
            # The build URL in the response points elsewhere; the report URL must be rebuilt
            # from the pinned job URL so the credentials never leave the instance.
            {"number": 8, "url": "http://evil.example/exfil/8/", "timestamp": 1767323044000, "building": False},
            {"number": 7, "url": f"{HOST}/job/svc/7/", "timestamp": 1767323043000, "building": False},
        ]
    }
    REPORT = {"failCount": 1, "passCount": 41, "skipCount": 2, "suites": [{"name": "s", "cases": []}]}

    @parameterized.expand(
        [
            ("build_without_report_skipped", 404, None, [8]),
            ("permission_error_fails_the_sync", 403, "403 Client Error", []),
        ]
    )
    def test_fetches_one_report_per_finished_build(
        self, _name: str, second_status: int, error: str | None, expected_builds: list[int]
    ) -> None:
        result = _driver().run(
            "test_reports",
            [
                ScriptedResponse(json=self.JOBS),
                ScriptedResponse(json=self.BUILDS),
                ScriptedResponse(json=self.REPORT),
                ScriptedResponse(status=second_status),
            ],
        )
        assert result.paths == [
            "/api/json",
            "/job/svc/api/json",
            "/job/svc/8/testReport/api/json",
            "/job/svc/7/testReport/api/json",
        ]
        if error is None:
            assert result.raised is None
        else:
            assert error in str(result.raised)
        rows = _rows(result)
        assert [row["build_number"] for row in rows] == expected_builds
        if rows:
            assert rows[0]["build_url"] == "http://evil.example/exfil/8/"
            assert rows[0]["job_url"] == f"{HOST}/job/svc/"
            assert (rows[0]["passCount"], rows[0]["failCount"], rows[0]["skipCount"]) == (41, 1, 2)
