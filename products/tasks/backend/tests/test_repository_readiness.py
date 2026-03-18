from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.repository_readiness import (
    MAX_CANDIDATE_PATHS,
    RepositoryScanEvidence,
    _applicable_capabilities,
    _candidate_path_score,
    _classify_repository,
    _select_candidate_paths,
    _should_scan_path,
    compute_repository_readiness,
)


def _empty_evidence(**overrides: Any) -> RepositoryScanEvidence:
    return RepositoryScanEvidence(
        found_posthog_init=overrides.get("found_posthog_init", False),
        found_posthog_capture=overrides.get("found_posthog_capture", False),
        found_error_signal=overrides.get("found_error_signal", False),
        captured_event_names=overrides.get("captured_event_names", []),
        files_scanned=overrides.get("files_scanned", 0),
        detected_files_count=overrides.get("detected_files_count", 0),
        frontend_markers=overrides.get("frontend_markers", 0),
        backend_markers=overrides.get("backend_markers", 0),
    )


class TestShouldScanPath(TestCase):
    @parameterized.expand(
        [
            ("typescript", "src/index.ts", True),
            ("tsx", "components/App.tsx", True),
            ("javascript", "lib/utils.js", True),
            ("jsx", "views/Home.jsx", True),
            ("python", "app/main.py", True),
            ("go", "cmd/server.go", True),
            ("java", "src/Main.java", True),
            ("ruby", "app/models/user.rb", True),
            ("php", "src/Controller.php", True),
            ("csharp", "Program.cs", True),
            ("minified_js", "dist/bundle.min.js", False),
            ("node_modules", "node_modules/lodash/index.js", False),
            ("dist_dir", "dist/app.js", False),
            ("build_dir", "build/output.js", False),
            ("coverage_dir", "coverage/lcov.js", False),
            ("next_dir", ".next/static/app.js", False),
            ("vendor_dir", "vendor/lib.go", False),
            ("markdown", "README.md", False),
            ("json", "package.json", False),
            ("yaml", "config.yaml", False),
            ("case_insensitive_ext", "SRC/INDEX.TS", True),
            ("case_insensitive_prefix", "NODE_MODULES/foo.js", False),
        ]
    )
    def test_should_scan_path(self, _name: str, path: str, expected: bool) -> None:
        assert _should_scan_path(path) == expected


class TestCandidatePathScore(TestCase):
    @parameterized.expand(
        [
            ("no_keywords", "src/utils.ts", 1),
            ("posthog_keyword", "src/posthog.ts", 3),
            ("analytics_keyword", "lib/analytics.py", 2),
            ("tracking_keyword", "tracking/events.js", 2),
            ("telemetry_keyword", "telemetry.go", 2),
            ("instrument_keyword", "instrument.ts", 2),
            ("error_keyword", "src/error-handler.ts", 3),
            ("replay_keyword", "src/replay.ts", 3),
            ("src_prefix", "src/main.ts", 1),
            ("app_prefix", "app/main.ts", 1),
            ("no_prefix", "lib/main.ts", 0),
            ("multiple_keywords", "src/posthog-analytics.ts", 5),
            ("all_keywords", "src/posthog-analytics-tracking-telemetry-instrument-error-replay.ts", 15),
        ]
    )
    def test_candidate_path_score(self, _name: str, path: str, expected: int) -> None:
        assert _candidate_path_score(path) == expected


class TestSelectCandidatePaths(TestCase):
    def test_filters_unscannable(self) -> None:
        paths = ["src/main.ts", "README.md", "package.json", "src/utils.py"]
        result = _select_candidate_paths(paths)
        assert set(result) == {"src/main.ts", "src/utils.py"}

    def test_sorts_by_score_descending(self) -> None:
        paths = ["lib/utils.ts", "src/posthog.ts", "app/main.ts"]
        result = _select_candidate_paths(paths)
        assert result[0] == "src/posthog.ts"

    def test_truncates_to_max(self) -> None:
        paths = [f"src/file{i}.ts" for i in range(MAX_CANDIDATE_PATHS + 20)]
        result = _select_candidate_paths(paths)
        assert len(result) == MAX_CANDIDATE_PATHS


class TestClassifyRepository(TestCase):
    @parameterized.expand(
        [
            ("test_repo", "org/test-app", [], _empty_evidence(), "test_or_sandbox", True),
            ("sandbox_repo", "org/my-sandbox", [], _empty_evidence(), "test_or_sandbox", True),
            ("demo_repo", "org/demo-project", [], _empty_evidence(), "test_or_sandbox", True),
            ("sdk_repo", "org/posthog-sdk", [], _empty_evidence(), "sdk_or_library", True),
            ("library_repo", "org/my-library", [], _empty_evidence(), "sdk_or_library", True),
            (
                "frontend_by_markers",
                "org/myrepo",
                ["package.json"],
                _empty_evidence(frontend_markers=1),
                "frontend_js",
                False,
            ),
            (
                "backend_by_markers",
                "org/myrepo",
                ["pyproject.toml"],
                _empty_evidence(backend_markers=1),
                "backend_service",
                False,
            ),
            ("frontend_by_name", "org/my-web-app", [], _empty_evidence(), "frontend_js", False),
            ("backend_by_name", "org/my-server", [], _empty_evidence(), "backend_service", False),
            (
                "frontend_by_extension",
                "org/myrepo",
                ["src/App.tsx"],
                _empty_evidence(),
                "frontend_js",
                False,
            ),
            (
                "backend_by_extension",
                "org/myrepo",
                ["main.py"],
                _empty_evidence(),
                "backend_service",
                False,
            ),
            ("unknown_fallback", "org/myrepo", [], _empty_evidence(), "unknown", False),
        ]
    )
    def test_classify_repository(
        self,
        _name: str,
        repository: str,
        tree_paths: list[str],
        evidence: RepositoryScanEvidence,
        expected_classification: str,
        expected_excluded: bool,
    ) -> None:
        classification, excluded = _classify_repository(repository, tree_paths, evidence)
        assert classification == expected_classification
        assert excluded == expected_excluded

    def test_test_hint_takes_priority_over_file_markers(self) -> None:
        evidence = _empty_evidence(frontend_markers=5)
        classification, excluded = _classify_repository("org/test-app", ["package.json"], evidence)
        assert classification == "test_or_sandbox"
        assert excluded is True


class TestApplicableCapabilities(TestCase):
    @parameterized.expand(
        [
            ("excluded", "frontend_js", True, {"tracking": False, "computer_vision": False, "errors": False}),
            ("frontend", "frontend_js", False, {"tracking": True, "computer_vision": True, "errors": True}),
            ("backend", "backend_service", False, {"tracking": True, "computer_vision": False, "errors": True}),
            ("unknown", "unknown", False, {"tracking": True, "computer_vision": False, "errors": True}),
            (
                "unhandled_classification",
                "sdk_or_library",
                False,
                {"tracking": False, "computer_vision": False, "errors": False},
            ),
        ]
    )
    def test_applicable_capabilities(
        self,
        _name: str,
        classification: str,
        excluded: bool,
        expected: dict[str, bool],
    ) -> None:
        assert _applicable_capabilities(classification, excluded) == expected


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestComputeRepositoryReadiness(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def test_no_github_integration_returns_needs_setup(self) -> None:
        result = compute_repository_readiness(team=self.team, repository="org/repo")
        assert result["overall"] == "needs_setup"
        assert result["coreSuggestions"]["state"] == "needs_setup"
        assert result["cacheAgeSeconds"] == 0

    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_no_access_token_returns_unknown(self, mock_integration_cls: MagicMock, mock_refresh: MagicMock) -> None:
        integration = MagicMock()
        integration.id = 1
        integration.sensitive_config = {}
        mock_integration_cls.objects.filter.return_value.first.return_value = integration

        result = compute_repository_readiness(team=self.team, repository="org/repo")
        assert result["overall"] == "unknown"

    def _mock_integration(self, mock_integration_cls: MagicMock) -> MagicMock:
        integration = MagicMock()
        integration.id = 1
        integration.sensitive_config = {"access_token": "ghp_test"}
        mock_integration_cls.objects.filter.return_value.first.return_value = integration
        return integration

    @patch("products.tasks.backend.repository_readiness._scan_repository")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_scan_failure_graceful_degradation(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)
        mock_scan.side_effect = RuntimeError("GitHub API down")

        with patch("products.tasks.backend.repository_readiness.logger") as mock_logger:
            result = compute_repository_readiness(team=self.team, repository="org/repo")
            mock_logger.exception.assert_called_once()

        assert result["scan"]["filesScanned"] == 0
        assert result["scan"]["foundPosthogInit"] is False
        assert "overall" in result

    @patch("products.tasks.backend.repository_readiness._scan_repository")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_cache_hit_returns_cache_age(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)
        mock_scan.return_value = (_empty_evidence(), [])

        compute_repository_readiness(team=self.team, repository="org/repo")

        result = compute_repository_readiness(team=self.team, repository="org/repo")
        assert result["cacheAgeSeconds"] >= 0

    @patch("products.tasks.backend.repository_readiness._scan_repository")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_refresh_bypasses_cache(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)
        mock_scan.return_value = (_empty_evidence(), [])

        compute_repository_readiness(team=self.team, repository="org/repo")

        compute_repository_readiness(team=self.team, repository="org/repo", refresh=True)
        assert mock_scan.call_count == 2

    @patch("products.tasks.backend.repository_readiness._scan_repository")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_detected_state_when_code_found_but_settings_off(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)
        evidence = _empty_evidence(
            found_posthog_init=True,
            found_posthog_capture=True,
            found_error_signal=True,
            frontend_markers=1,
        )
        mock_scan.return_value = (evidence, ["package.json", "src/app.tsx"])

        self.team.proactive_tasks_enabled = False
        self.team.session_recording_opt_in = False
        self.team.autocapture_exceptions_opt_in = False
        self.team.save()

        result = compute_repository_readiness(team=self.team, repository="org/repo")

        assert result["coreSuggestions"]["state"] == "detected"
        assert result["replayInsights"]["state"] == "detected"
        assert result["errorInsights"]["state"] == "detected"
        assert result["overall"] == "detected"
        assert result["scan"]["foundPosthogInit"] is True
        assert result["scan"]["foundPosthogCapture"] is True
        assert result["scan"]["foundErrorSignal"] is True

    @patch("products.tasks.backend.repository_readiness._scan_repository")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_waiting_for_data_when_code_found_and_settings_on(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)
        evidence = _empty_evidence(
            found_posthog_init=True,
            found_posthog_capture=True,
            found_error_signal=True,
            frontend_markers=1,
        )
        mock_scan.return_value = (evidence, ["package.json", "src/app.tsx"])

        self.team.proactive_tasks_enabled = True
        self.team.session_recording_opt_in = True
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()

        result = compute_repository_readiness(team=self.team, repository="org/repo")

        assert result["coreSuggestions"]["state"] == "waiting_for_data"
        assert result["replayInsights"]["state"] == "waiting_for_data"
        assert result["errorInsights"]["state"] == "waiting_for_data"
        assert result["overall"] == "partial"

    @patch("products.tasks.backend.repository_readiness._scan_repository")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_needs_setup_when_no_code_evidence(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)
        mock_scan.return_value = (_empty_evidence(frontend_markers=1), ["package.json", "src/app.tsx"])

        result = compute_repository_readiness(team=self.team, repository="org/repo")

        assert result["coreSuggestions"]["state"] == "needs_setup"
        assert result["replayInsights"]["state"] == "needs_setup"
        assert result["errorInsights"]["state"] == "needs_setup"
        assert result["overall"] == "needs_setup"
        assert result["scan"]["foundPosthogInit"] is False

    @patch("products.tasks.backend.repository_readiness.time")
    @patch("products.tasks.backend.repository_readiness._fetch_file_content")
    @patch("products.tasks.backend.repository_readiness._fetch_repository_tree")
    @patch("products.tasks.backend.repository_readiness._refresh_installation_token")
    @patch("products.tasks.backend.repository_readiness.Integration")
    def test_time_budget_exceeded_returns_partial_results(
        self,
        mock_integration_cls: MagicMock,
        mock_refresh: MagicMock,
        mock_tree: MagicMock,
        mock_content: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        self._mock_integration(mock_integration_cls)

        mock_tree.return_value = ([f"src/file{i}.ts" for i in range(10)], "main")
        mock_content.return_value = "const x = 1;"

        call_count = 0

        def monotonic_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return 0.0
            return 31.0

        mock_time.monotonic.side_effect = monotonic_side_effect

        with patch("products.tasks.backend.repository_readiness.logger") as mock_logger:
            result = compute_repository_readiness(team=self.team, repository="org/repo")
            budget_warnings = [c for c in mock_logger.warning.call_args_list if "scan_time_budget_exceeded" in str(c)]
            assert len(budget_warnings) == 1

        assert "scan" in result
