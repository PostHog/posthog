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
    _lifecycle_for,
    _selector_kind,
    build_quarantine,
    parse_quarantine_text,
)

_TODAY = date(2026, 6, 12)
_REQUESTS_GET = "products.engineering_analytics.backend.logic.quarantine.requests.get"
_FOR_TEAM = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.for_team"
_VIEWS = "products.engineering_analytics.backend.presentation.views.api"


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


def _response(status_code: int = 200, text: str = "") -> mock.Mock:
    return mock.Mock(status_code=status_code, text=text)


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
            "https://raw.githubusercontent.com/PostHog/posthog/HEAD/.test_quarantine.json", timeout=3
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
