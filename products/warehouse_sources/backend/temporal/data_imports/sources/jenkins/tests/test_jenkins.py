from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins import jenkins
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.jenkins import (
    JenkinsResumeConfig,
    _discover_jobs,
    _get_build_rows,
    _is_job_container,
    _iter_job_builds,
    _to_epoch_ms,
    normalize_base_url,
    validate_credentials,
)


def _resp(payload: Any, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.status_code = status
    response.ok = 200 <= status < 400
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

    def test_full_refresh_yields_all_with_derived_fields(self) -> None:
        page = self._builds(3000, 2000, 1000)
        with mock.patch.object(jenkins, "_fetch", return_value=_resp({"builds": page})):
            rows = list(_iter_job_builds(MagicMock(), "https://j/", ("u", "t"), MagicMock(), watermark_ms=None))
        assert [r["number"] for r in rows] == [0, 1, 2]
        # Every row carries the parent job URL and a created_at derived from the epoch-ms timestamp.
        assert all(r["job_url"] == "https://j/" for r in rows)
        assert rows[0]["created_at"] == datetime.fromtimestamp(3000 / 1000, tz=UTC).isoformat()

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


class _FakeManager:
    def __init__(self, state: JenkinsResumeConfig | None) -> None:
        self._state = state
        self.saved: list[JenkinsResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JenkinsResumeConfig | None:
        return self._state

    def save_state(self, data: JenkinsResumeConfig) -> None:
        self.saved.append(data)


class TestGetBuildRows:
    def _run(self, manager: _FakeManager) -> None:
        job_urls = ["https://j/a/", "https://j/b/", "https://j/c/"]
        batcher = MagicMock()
        batcher.should_yield.return_value = False
        with mock.patch.object(jenkins, "_iter_buildable_job_urls", return_value=job_urls):
            with mock.patch.object(jenkins, "_iter_job_builds", return_value=iter([])):
                list(
                    _get_build_rows(
                        MagicMock(), "https://j", ("u", "t"), MagicMock(), batcher, manager, watermark_ms=None
                    )
                )

    def test_bookmarks_next_job_after_each_completes(self) -> None:
        # After finishing job a, the bookmark points at b; after b, at c. The last job saves nothing,
        # so a resume never restarts at a job whose rows already fully landed.
        manager = _FakeManager(state=None)
        self._run(manager)
        assert [s.next_job_url for s in manager.saved] == ["https://j/b/", "https://j/c/"]

    def test_resumes_from_saved_bookmark(self) -> None:
        manager = _FakeManager(state=JenkinsResumeConfig(next_job_url="https://j/b/"))
        with mock.patch.object(jenkins, "_iter_job_builds", return_value=iter([])) as iter_builds:
            with mock.patch.object(
                jenkins, "_iter_buildable_job_urls", return_value=["https://j/a/", "https://j/b/", "https://j/c/"]
            ):
                batcher = MagicMock()
                batcher.should_yield.return_value = False
                list(
                    _get_build_rows(
                        MagicMock(), "https://j", ("u", "t"), MagicMock(), batcher, manager, watermark_ms=None
                    )
                )
        # Only b and c are processed; a (already synced) is skipped.
        processed = [call.args[1] for call in iter_builds.call_args_list]
        assert processed == ["https://j/b/", "https://j/c/"]

    def test_stale_bookmark_restarts_from_beginning(self) -> None:
        # The bookmarked job was deleted between runs; fall back to the full list rather than syncing
        # nothing (merge dedupes the re-pulled rows).
        manager = _FakeManager(state=JenkinsResumeConfig(next_job_url="https://j/gone/"))
        with mock.patch.object(jenkins, "_iter_job_builds", return_value=iter([])) as iter_builds:
            with mock.patch.object(jenkins, "_iter_buildable_job_urls", return_value=["https://j/a/", "https://j/b/"]):
                batcher = MagicMock()
                batcher.should_yield.return_value = False
                list(
                    _get_build_rows(
                        MagicMock(), "https://j", ("u", "t"), MagicMock(), batcher, manager, watermark_ms=None
                    )
                )
        processed = [call.args[1] for call in iter_builds.call_args_list]
        assert processed == ["https://j/a/", "https://j/b/"]


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
        session = MagicMock()
        session.get.return_value = _resp({}, status=status)
        with mock.patch.object(jenkins, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("https://jenkins.example.com", "user", "token")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_invalid_url_short_circuits_without_request(self) -> None:
        with mock.patch.object(jenkins, "make_tracked_session") as make_session:
            ok, error = validate_credentials("https://user@evil.example.com", "user", "token")
        assert ok is False
        make_session.assert_not_called()
