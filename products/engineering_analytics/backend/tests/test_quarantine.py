import json
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest
from unittest import TestCase, mock

from django.core.cache import cache
from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework import status

from products.engineering_analytics.backend.facade import contracts
from products.engineering_analytics.backend.logic.quarantine import (
    QUARANTINE_FILENAME,
    _canonical_entry,
    _lifecycle_for,
    _remove_entry,
    _selector_kind,
    _upsert_entry,
    build_quarantine,
    parse_quarantine_text,
    render_quarantine_file,
    request_quarantine,
)

_TODAY = date(2026, 6, 12)
_REQUESTS_GET = "products.engineering_analytics.backend.logic.quarantine.requests.get"
_MAX_BYTES = "products.engineering_analytics.backend.logic.quarantine._MAX_QUARANTINE_BYTES"
_FOR_TEAM = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.for_team"
_VIEWS = "products.engineering_analytics.backend.presentation.views.api"
_Q = "products.engineering_analytics.backend.logic.quarantine"

# The exact bytes core.render (and therefore `hogli test:quarantine add`) writes for one
# full entry: version, then entries sorted by id, 4-space indent, trailing newline. If this
# breaks, the bot's PR diff would diverge from a human's and `quarantine check` could flag it.
_GOLDEN_ONE = (
    "{\n"
    '    "version": 1,\n'
    '    "entries": [\n'
    "        {\n"
    '            "id": "a/b.py::T::t",\n'
    '            "runner": "pytest",\n'
    '            "reason": "flaky",\n'
    '            "owner": "@PostHog/team-foo",\n'
    '            "issue": "https://github.com/PostHog/posthog/issues/1",\n'
    '            "added": "2026-06-01",\n'
    '            "expires": "2026-06-20",\n'
    '            "mode": "run"\n'
    "        }\n"
    "    ]\n"
    "}\n"
)


def _curated_source(results: list[tuple[str, str]]) -> mock.Mock:
    """A stand-in CuratedGitHubSource: run_source() feeds the repo SQL, run() returns the rows."""
    source = mock.Mock()
    source.run_source.return_value = "(runs)"
    source.run.return_value = SimpleNamespace(results=results)
    return source


def _entry(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": "posthog/api/test/test_foo.py::TestFoo::test_bar",
        "runner": "pytest",
        "reason": "flaky",
        "owner": "@PostHog/team-foo",
        "issue": "https://github.com/PostHog/posthog/issues/1",
        "added": "2026-06-01",
        "expires": "2026-06-20",
        "mode": "run",
    }
    raw.update(overrides)
    return {key: value for key, value in raw.items() if value is not None}


def _text(*entries: dict[str, Any]) -> str:
    return json.dumps({"version": 1, "entries": list(entries)})


def _response(status_code: int = 200, text: str = "", headers: dict[str, str] | None = None) -> mock.MagicMock:
    """A streamed requests response: usable as a context manager, body delivered via iter_content."""
    body = text.encode("utf-8")
    response = mock.MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.iter_content.side_effect = lambda *args, **kwargs: iter([body])
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _github_mock(**overrides: Any) -> mock.Mock:
    github = mock.Mock()
    github.organization.return_value = "PostHog"
    github.get_default_branch.return_value = "master"
    github.get_file_contents.return_value = None
    github.create_issue.return_value = {"number": 4242, "repository": "posthog"}
    github.create_branch.return_value = {"success": True, "sha": "branchsha"}
    github.update_file.return_value = {"success": True, "commit_sha": "commitsha"}
    github.create_pull_request.return_value = {
        "success": True,
        "pr_url": "https://github.com/PostHog/posthog/pull/99",
    }
    for name, value in overrides.items():
        getattr(github, name).return_value = value
    return github


def _request(**overrides: Any) -> contracts.QuarantineRequest:
    fields: dict[str, Any] = {
        "operation": contracts.QuarantineRequestAction.QUARANTINE,
        "selector": "posthog/api/test/test_foo.py::TestFoo::test_bar",
        "repo": "PostHog/posthog",
        "reason": "flaky under shards",
        "owner": "@PostHog/team-foo",
        "issue": "",
        "expires": None,
        "mode": contracts.QuarantineMode.RUN,
    }
    fields.update(overrides)
    return contracts.QuarantineRequest(**fields)


class TestQuarantineParse(TestCase):
    def test_parses_valid_file_and_applies_defaults(self) -> None:
        full = _entry()
        minimal = {"id": "posthog/api/test", "added": "2026-06-01", "expires": "2026-06-09"}
        entries, errors, warnings = parse_quarantine_text(_text(full, minimal), _TODAY)

        assert errors == [] and warnings == []
        by_id = {entry.id: entry for entry in entries}
        assert by_id[full["id"]].mode == contracts.QuarantineMode.RUN
        assert by_id[full["id"]].issue == "https://github.com/PostHog/posthog/issues/1"
        assert by_id[full["id"]].days_until_expiry == 8
        defaulted = by_id["posthog/api/test"]
        assert (defaulted.runner, defaulted.reason, defaulted.owner, defaulted.issue) == ("pytest", "", "", "")
        assert defaulted.mode == contracts.QuarantineMode.RUN
        assert defaulted.days_until_expiry == -3

    @parameterized.expand(
        [
            ("malformed_json", "{not json", "invalid JSON"),
            ("not_an_object", "[]", "top level must be an object"),
            ("wrong_version", '{"version": 2, "entries": []}', "unsupported version"),
            ("entries_not_a_list", '{"version": 1, "entries": {}}', "'entries' must be a list"),
        ]
    )
    def test_top_level_problems_yield_one_error_and_no_entries(self, _name: str, text: str, message: str) -> None:
        entries, errors, warnings = parse_quarantine_text(text, _TODAY)

        assert entries == [] and warnings == []
        assert len(errors) == 1 and message in errors[0]

    @parameterized.expand(
        [
            ("not_an_object", "just-a-string", "must be an object"),
            ("missing_id", _entry(id=None), "'id' must be a non-empty string"),
            ("bad_mode", _entry(mode="pause"), "'mode' must be one of"),
            ("bad_date", _entry(expires="next week"), "must be an ISO date"),
            ("non_string_reason", _entry(reason=42), "'reason' must be a string"),
        ]
    )
    def test_malformed_entry_dropped_while_good_ones_kept(self, _name: str, bad: Any, message: str) -> None:
        good = _entry(id="posthog/api/test/test_ok.py")
        entries, errors, warnings = parse_quarantine_text(_text(bad, good), _TODAY)

        assert [entry.id for entry in entries] == ["posthog/api/test/test_ok.py"]
        assert len(errors) == 1 and message in errors[0]
        assert warnings == []

    def test_unknown_entry_fields_warn_and_entry_is_kept(self) -> None:
        entries, errors, warnings = parse_quarantine_text(_text(_entry(snooze_until="2027-01-01")), _TODAY)

        assert len(entries) == 1
        assert errors == []
        assert len(warnings) == 1 and "snooze_until" in warnings[0]

    @parameterized.expand(
        [
            (8, contracts.QuarantineLifecycle.ACTIVE),
            (7, contracts.QuarantineLifecycle.EXPIRING_SOON),
            (0, contracts.QuarantineLifecycle.EXPIRING_SOON),
            (-1, contracts.QuarantineLifecycle.IN_GRACE),
            (-7, contracts.QuarantineLifecycle.IN_GRACE),
            (-8, contracts.QuarantineLifecycle.OVERDUE),
        ]
    )
    def test_lifecycle_boundaries(self, days: int, expected: contracts.QuarantineLifecycle) -> None:
        assert _lifecycle_for(days) == expected

    @parameterized.expand(
        [
            ("product:batch-exports", contracts.QuarantineSelectorKind.PRODUCT),
            ("posthog/api/test/test_foo.py::TestFoo::test_bar", contracts.QuarantineSelectorKind.TEST),
            ("posthog/api/test/test_foo.py::TestFoo", contracts.QuarantineSelectorKind.TEST),
            ("posthog/api/test/test_foo.py", contracts.QuarantineSelectorKind.FILE),
            ("frontend/src/scenes/dashboard/dashboardLogic.test.ts", contracts.QuarantineSelectorKind.FILE),
            ("posthog/api/test", contracts.QuarantineSelectorKind.DIRECTORY),
        ]
    )
    def test_selector_kind(self, selector: str, expected: contracts.QuarantineSelectorKind) -> None:
        assert _selector_kind(selector) == expected

    def test_sorts_most_urgent_first_then_expiry_then_id(self) -> None:
        text = _text(
            _entry(id="zz", added="2026-06-01", expires="2026-07-02"),
            _entry(id="aa", added="2026-06-01", expires="2026-07-02"),
            _entry(id="grace", added="2026-05-12", expires="2026-06-09"),
            _entry(id="active-late", added="2026-06-08", expires="2026-07-07"),
            _entry(id="soon", added="2026-05-20", expires="2026-06-15"),
            _entry(id="overdue", added="2026-05-05", expires="2026-06-02"),
        )
        entries, errors, _warnings = parse_quarantine_text(text, _TODAY)

        assert errors == []
        assert [entry.id for entry in entries] == ["overdue", "grace", "soon", "aa", "zz", "active-late"]


class TestQuarantineBuild(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @freeze_time("2026-06-12")
    def test_fetches_and_parses_remote_file(self) -> None:
        with mock.patch(_REQUESTS_GET, return_value=_response(200, _text(_entry()))) as get:
            result = build_quarantine(team=self.team, repo="PostHog/posthog")

        assert result.available is True
        assert result.repo == contracts.RepoRef(provider="github", owner="PostHog", name="posthog")
        assert result.source_url == "https://github.com/PostHog/posthog/blob/HEAD/.test_quarantine.json"
        assert len(result.entries) == 1
        assert result.entries[0].days_until_expiry == 8
        assert result.entries[0].lifecycle == contracts.QuarantineLifecycle.ACTIVE
        get.assert_called_once_with(
            "https://raw.githubusercontent.com/PostHog/posthog/HEAD/.test_quarantine.json", timeout=3, stream=True
        )

    def test_404_means_unavailable_without_errors(self) -> None:
        with mock.patch(_REQUESTS_GET, return_value=_response(404)):
            result = build_quarantine(team=self.team, repo="PostHog/posthog")

        assert result.available is False
        assert result.entries == [] and result.parse_errors == []
        assert result.repo == contracts.RepoRef(provider="github", owner="PostHog", name="posthog")
        assert result.source_url == ""

    @parameterized.expand(
        [
            ("timeout", requests.Timeout("boom")),
            ("server_error", 500),
        ]
    )
    def test_fetch_failure_reported_as_single_parse_error(self, _name: str, failure: Exception | int) -> None:
        kwargs: dict[str, Any] = (
            {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": _response(failure)}
        )
        with mock.patch(_REQUESTS_GET, **kwargs):
            result = build_quarantine(team=self.team, repo="PostHog/posthog")

        assert result.available is False
        assert len(result.parse_errors) == 1 and "could not fetch" in result.parse_errors[0]

    @parameterized.expand(["PostHog", "Post Hog/repo", "PostHog/po$thog", "-bad/repo", "a/b/c", "PostHog/"])
    def test_invalid_repo_rejected_before_fetch(self, repo: str) -> None:
        with mock.patch(_REQUESTS_GET) as get:
            result = build_quarantine(team=self.team, repo=repo)

        assert result.available is False
        assert len(result.parse_errors) == 1 and "invalid repo" in result.parse_errors[0]
        get.assert_not_called()

    def test_caches_fetched_text(self) -> None:
        with mock.patch(_REQUESTS_GET, return_value=_response(200, _text(_entry()))) as get:
            build_quarantine(team=self.team, repo="PostHog/posthog")
            result = build_quarantine(team=self.team, repo="PostHog/posthog")

        assert get.call_count == 1
        assert result.available is True and len(result.entries) == 1

    def test_oversized_streamed_body_rejected_and_not_cached(self) -> None:
        # No Content-Length header: the cap must hold on the streamed bytes, and a
        # hostile oversize response must not poison the cache for the next caller.
        with mock.patch(_MAX_BYTES, 16), mock.patch(_REQUESTS_GET, return_value=_response(200, _text(_entry()))) as get:
            first = build_quarantine(team=self.team, repo="PostHog/posthog")
            second = build_quarantine(team=self.team, repo="PostHog/posthog")

        assert first.available is False
        assert len(first.parse_errors) == 1 and "exceeds" in first.parse_errors[0]
        assert second.available is False
        assert get.call_count == 2

    def test_oversized_content_length_rejected_before_reading_body(self) -> None:
        response = _response(200, _text(_entry()), headers={"Content-Length": str(10 * 1024 * 1024)})
        with mock.patch(_REQUESTS_GET, return_value=response):
            result = build_quarantine(team=self.team, repo="PostHog/posthog")

        assert result.available is False and "exceeds" in result.parse_errors[0]
        response.iter_content.assert_not_called()

    def test_resolves_most_active_repo_from_workflow_runs(self) -> None:
        source = _curated_source([("PostHog", "posthog.com")])
        with (
            mock.patch(_FOR_TEAM, return_value=source),
            mock.patch(_REQUESTS_GET, return_value=_response(200, _text(_entry()))),
        ):
            result = build_quarantine(team=self.team)

        assert result.repo == contracts.RepoRef(provider="github", owner="PostHog", name="posthog.com")
        assert source.run.call_args.kwargs["query_type"] == "engineering_analytics.quarantine_repo"

    def test_no_recent_runs_means_unavailable(self) -> None:
        with (
            mock.patch(_FOR_TEAM, return_value=_curated_source([])),
            mock.patch(_REQUESTS_GET) as get,
        ):
            result = build_quarantine(team=self.team)

        assert result.available is False
        assert len(result.parse_errors) == 1 and "could not determine a repository" in result.parse_errors[0]
        get.assert_not_called()

    def test_no_connected_source_is_fail_open(self) -> None:
        with (
            mock.patch(_FOR_TEAM, side_effect=contracts.GitHubSourceNotConnectedError("no GitHub source connected")),
            mock.patch(_REQUESTS_GET) as get,
        ):
            result = build_quarantine(team=self.team)

        assert result.available is False
        assert "pass ?repo=owner/name" in result.parse_errors[0]
        get.assert_not_called()

    def test_debug_reads_local_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / QUARANTINE_FILENAME).write_text(_text(_entry()))
            with override_settings(DEBUG=True, BASE_DIR=tmp), mock.patch(_REQUESTS_GET) as get:
                result = build_quarantine(team=self.team)

        assert result.available is True
        assert result.repo is None and result.source_url == ""
        assert len(result.entries) == 1
        get.assert_not_called()


class TestQuarantineAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/quarantine/"

    @freeze_time("2026-06-12")
    def test_quarantine_serializes(self) -> None:
        with mock.patch(_REQUESTS_GET, return_value=_response(200, _text(_entry()))):
            response = self.client.get(self._url(), {"repo": "PostHog/posthog"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["available"] is True
        assert body["repo"] == {"provider": "github", "owner": "PostHog", "name": "posthog"}
        assert body["source_url"] == "https://github.com/PostHog/posthog/blob/HEAD/.test_quarantine.json"
        entry = body["entries"][0]
        assert entry["id"] == "posthog/api/test/test_foo.py::TestFoo::test_bar"
        assert entry["mode"] == "run"
        assert entry["lifecycle"] == "active"
        assert entry["selector_kind"] == "test"
        assert entry["days_until_expiry"] == 8
        assert entry["expires"] == "2026-06-20"

    def test_quarantine_available_false_when_repo_has_no_file(self) -> None:
        with mock.patch(_REQUESTS_GET, return_value=_response(404)):
            response = self.client.get(self._url(), {"repo": "PostHog/no-quarantine"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["available"] is False
        assert body["entries"] == [] and body["parse_errors"] == []

    def test_repo_param_passes_through_to_facade(self) -> None:
        empty = contracts.QuarantineFile(
            available=False,
            entries=[],
            parse_errors=[],
            parse_warnings=[],
            repo=None,
            source_url="",
            generated_at=datetime(2026, 6, 12, tzinfo=UTC),
        )
        with mock.patch(f"{_VIEWS}.get_quarantine", return_value=empty) as get:
            response = self.client.get(self._url(), {"repo": "PostHog/posthog.com"})

        assert response.status_code == status.HTTP_200_OK
        assert get.call_args.kwargs["repo"] == "PostHog/posthog.com"
        assert get.call_args.kwargs["team"] == self.team


class TestQuarantineRender(TestCase):
    def test_render_matches_core_byte_for_byte(self) -> None:
        entry = _canonical_entry(
            {
                "id": "a/b.py::T::t",
                "runner": "pytest",
                "reason": "flaky",
                "owner": "@PostHog/team-foo",
                "issue": "https://github.com/PostHog/posthog/issues/1",
                "added": "2026-06-01",
                "expires": "2026-06-20",
                "mode": "run",
            }
        )
        assert render_quarantine_file([entry], {}) == _GOLDEN_ONE

    def test_render_round_trips_through_the_read_parser(self) -> None:
        entry = _canonical_entry(_entry())
        text = render_quarantine_file([entry], {})
        parsed, errors, warnings = parse_quarantine_text(text, _TODAY)
        assert errors == [] and warnings == []
        assert parsed[0].id == _entry()["id"]

    def test_empty_issue_is_omitted(self) -> None:
        entry = _canonical_entry(_entry(issue=""))
        assert "issue" not in entry
        assert '"issue"' not in render_quarantine_file([entry], {})

    def test_unknown_fields_and_top_level_extras_are_preserved_sorted(self) -> None:
        entry = _canonical_entry(_entry(zeta="z", alpha="a"))
        keys = list(entry.keys())
        assert keys[-2:] == ["alpha", "zeta"]
        rendered = render_quarantine_file([entry], {"generated_by": "test"})
        assert json.loads(rendered)["generated_by"] == "test"

    def test_render_sorts_entries_by_id_then_runner(self) -> None:
        first = _canonical_entry(_entry(id="a/z.py"))
        second = _canonical_entry(_entry(id="a/a.py"))
        rendered = render_quarantine_file([first, second], {})
        ids = [e["id"] for e in json.loads(rendered)["entries"]]
        assert ids == ["a/a.py", "a/z.py"]

    @parameterized.expand(
        [
            ("missing_id", {"added": "2026-06-01", "expires": "2026-06-20"}),
            ("bad_date", {"id": "x", "added": "nope", "expires": "2026-06-20"}),
            ("not_an_object", "just a string"),
        ]
    )
    def test_canonical_entry_rejects_malformed(self, _name: str, raw: Any) -> None:
        with self.assertRaises(contracts.QuarantineWriteError):
            _canonical_entry(raw)

    def test_upsert_replaces_same_id_and_runner(self) -> None:
        existing = _canonical_entry(_entry(reason="old"))
        replacement = _canonical_entry(_entry(reason="new"))
        result = _upsert_entry([existing], replacement)
        assert len(result) == 1 and result[0]["reason"] == "new"

    def test_remove_drops_selector_across_runners(self) -> None:
        keep = _canonical_entry(_entry(id="other"))
        drop = _canonical_entry(_entry())
        result = _remove_entry([keep, drop], _entry()["id"])
        assert [e["id"] for e in result] == ["other"]


class TestQuarantineRequest(BaseTest):
    def _install(self, github: mock.Mock, *, has_integration: bool = True, connected: bool = True) -> mock.Mock:
        gh_patch = mock.patch(f"{_Q}.GitHubIntegration", return_value=github)
        integration_patch = mock.patch(f"{_Q}.Integration")
        # The explicit repo override is authorized against the team's connected GitHub sources;
        # mock that list so the real _repo_is_connected runs against a matching source (or none).
        sources = [SimpleNamespace(repo="PostHog/posthog")] if connected else []
        sources_patch = mock.patch(f"{_Q}.list_github_sources", return_value=sources)
        gh_patch.start()
        integration_cls = integration_patch.start()
        sources_patch.start()
        self.addCleanup(gh_patch.stop)
        self.addCleanup(integration_patch.stop)
        self.addCleanup(sources_patch.stop)
        integration_cls.objects.filter.return_value.first.return_value = object() if has_integration else None
        return github

    @freeze_time("2026-06-12")
    def test_quarantine_opens_issue_then_pr_and_writes_canonical_entry(self) -> None:
        github = self._install(_github_mock())
        result = request_quarantine(team=self.team, request=_request())

        assert result.issue_url == "https://github.com/PostHog/posthog/issues/4242"
        assert result.pr_url == "https://github.com/PostHog/posthog/pull/99"
        assert result.branch.startswith("quarantine/")

        github.create_issue.assert_called_once()
        issue_config = github.create_issue.call_args.args[0]
        assert _request().selector in issue_config["title"] and issue_config["repository"] == "posthog"

        committed = github.update_file.call_args.args[2]
        entry = json.loads(committed)["entries"][0]
        assert entry["id"] == _request().selector
        assert entry["mode"] == "run"
        assert entry["expires"] == "2026-06-26"
        assert entry["issue"] == "https://github.com/PostHog/posthog/issues/4242"
        assert github.create_pull_request.call_args.args[3] == result.branch  # head branch
        assert github.create_pull_request.call_args.args[4] == "master"  # base branch

    @freeze_time("2026-06-12")
    def test_skip_mode_is_persisted(self) -> None:
        github = self._install(_github_mock())
        request_quarantine(team=self.team, request=_request(mode=contracts.QuarantineMode.SKIP))
        entry = json.loads(github.update_file.call_args.args[2])["entries"][0]
        assert entry["mode"] == "skip"

    @freeze_time("2026-06-12")
    def test_extend_reuses_existing_issue_and_files_no_new_one(self) -> None:
        existing = _text(_entry(expires="2026-06-15", issue="https://github.com/PostHog/posthog/issues/7"))
        github = self._install(_github_mock(get_file_contents={"content": existing, "sha": "s"}))
        result = request_quarantine(
            team=self.team,
            request=_request(
                operation=contracts.QuarantineRequestAction.EXTEND,
                selector=_entry()["id"],
                issue="https://github.com/PostHog/posthog/issues/7",
                expires=date(2026, 6, 25),
            ),
        )
        github.create_issue.assert_not_called()
        assert result.issue_url == ""
        entry = json.loads(github.update_file.call_args.args[2])["entries"][0]
        assert entry["expires"] == "2026-06-25"
        assert entry["issue"] == "https://github.com/PostHog/posthog/issues/7"

    def test_remove_drops_the_entry_without_an_issue(self) -> None:
        github = self._install(_github_mock(get_file_contents={"content": _text(_entry()), "sha": "s"}))
        result = request_quarantine(
            team=self.team,
            request=_request(operation=contracts.QuarantineRequestAction.REMOVE, selector=_entry()["id"]),
        )
        github.create_issue.assert_not_called()
        assert result.issue_url == "" and result.branch.startswith("unquarantine/")
        assert json.loads(github.update_file.call_args.args[2])["entries"] == []

    def test_remove_of_absent_entry_is_a_clear_error(self) -> None:
        github = self._install(_github_mock(get_file_contents={"content": _text(), "sha": "s"}))
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(
                team=self.team,
                request=_request(operation=contracts.QuarantineRequestAction.REMOVE, selector="not/there"),
            )
        github.create_branch.assert_not_called()

    def test_no_github_integration_is_a_clear_error(self) -> None:
        self._install(_github_mock(), has_integration=False)
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request())

    def test_app_installed_on_wrong_org_is_rejected(self) -> None:
        self._install(_github_mock(organization="SomeoneElse"))
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request())

    def test_explicit_repo_outside_the_team_is_rejected_before_any_write(self) -> None:
        # A client-supplied repo the team hasn't connected as a GitHub source must not get the
        # App's write token, even when it sits in the install's org.
        github = self._install(_github_mock(), connected=False)
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request(repo="PostHog/not-ours"))
        github.create_branch.assert_not_called()
        github.create_issue.assert_not_called()

    @parameterized.expand(
        [
            ("missing_token", ValueError("GitHub access token not configured")),
            ("api_failure", Exception("Failed to get default branch: HTTP 404")),
        ]
    )
    def test_github_failure_becomes_a_user_safe_error_not_a_500(self, _name: str, failure: Exception) -> None:
        # get_default_branch raises plain ValueError/Exception, not QuarantineWriteError; without
        # translation those escape as a 500 instead of the user-safe 400 the rest of the path gives.
        github = self._install(_github_mock())
        github.get_default_branch.side_effect = failure
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request())
        github.create_branch.assert_not_called()

    def test_malformed_existing_file_aborts_without_writing(self) -> None:
        github = self._install(_github_mock(get_file_contents={"content": "{ not json", "sha": "s"}))
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request())
        github.create_branch.assert_not_called()

    @parameterized.expand(
        [
            ("past", date(2026, 6, 1)),
            ("too_far", date(2026, 8, 1)),
        ]
    )
    @freeze_time("2026-06-12")
    def test_expiry_bounds_are_enforced(self, _name: str, expires: date) -> None:
        self._install(_github_mock())
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request(expires=expires))

    @parameterized.expand([("reason", {"reason": ""}), ("owner", {"owner": ""})])
    @freeze_time("2026-06-12")
    def test_quarantine_requires_reason_and_owner(self, _name: str, overrides: dict[str, Any]) -> None:
        self._install(_github_mock())
        with self.assertRaises(contracts.QuarantineWriteError):
            request_quarantine(team=self.team, request=_request(**overrides))


class TestQuarantineRequestAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/quarantine/request/"

    def _body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "operation": "quarantine",
            "selector": "posthog/api/test/test_foo.py::TestFoo::test_bar",
            "repo": "PostHog/posthog",
            "reason": "flaky",
            "owner": "@PostHog/team-foo",
        }
        body.update(overrides)
        return body

    def test_returns_201_with_pr_and_issue_links(self) -> None:
        result = contracts.QuarantineRequestResult(
            pr_url="https://github.com/PostHog/posthog/pull/99",
            issue_url="https://github.com/PostHog/posthog/issues/4242",
            branch="quarantine/foo-20260612",
        )
        with mock.patch(f"{_VIEWS}.request_quarantine", return_value=result) as called:
            response = self.client.post(self._url(), self._body(), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["pr_url"].endswith("/pull/99")
        assert body["issue_url"].endswith("/issues/4242")
        assert called.call_args.kwargs["team"] == self.team
        assert called.call_args.kwargs["request"].selector == self._body()["selector"]

    @parameterized.expand(
        [
            # quarantine sends a blank issue (the server files one); remove sends no reason/owner.
            ("blank_issue_on_quarantine", {"issue": ""}),
            ("blank_reason_owner_on_remove", {"operation": "remove", "reason": "", "owner": "", "issue": ""}),
        ]
    )
    def test_blank_optional_strings_reach_the_facade(self, _name: str, overrides: dict[str, Any]) -> None:
        result = contracts.QuarantineRequestResult(pr_url="https://x/pull/1", issue_url="", branch="b")
        with mock.patch(f"{_VIEWS}.request_quarantine", return_value=result) as called:
            response = self.client.post(self._url(), self._body(**overrides), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        called.assert_called_once()

    def test_write_error_becomes_400_with_detail(self) -> None:
        with mock.patch(
            f"{_VIEWS}.request_quarantine",
            side_effect=contracts.QuarantineWriteError("The connected GitHub App is installed on 'X', not 'PostHog'."),
        ):
            response = self.client.post(self._url(), self._body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not 'PostHog'" in response.json()["detail"]

    @parameterized.expand(
        [
            ("missing_selector", {"selector": None}),
            ("missing_action", {"operation": None}),
            ("bad_action", {"operation": "nuke"}),
        ]
    )
    def test_invalid_body_is_rejected(self, _name: str, overrides: dict[str, Any]) -> None:
        body = self._body()
        for key, value in overrides.items():
            if value is None:
                body.pop(key, None)
            else:
                body[key] = value
        with mock.patch(f"{_VIEWS}.request_quarantine") as called:
            response = self.client.post(self._url(), body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        called.assert_not_called()
