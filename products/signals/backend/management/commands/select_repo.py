"""Local dev tool for testing repository selection in isolation. DEBUG only.

Exercises the repo selection flow against synthetic signals and optionally a custom
candidate repo list. Intended to be reworked into an eval harness — keeping it now
preserves coverage of the sandbox-based repo selection path.
"""

import asyncio
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Reuse the dummy repo constant for the sandbox clone
from products.signals.backend.report_generation.select_repo import (
    REPO_SELECTION_DUMMY_REPOSITORY,
    RepoSelectionResult,
    _build_repo_selection_prompt,
    select_repository_for_report,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.services.custom_prompt_runner import resolve_sandbox_context_for_local_dev

# Synthetic signals that span multiple product areas so the agent has to reason about repo relevance.
TEST_SIGNALS = [
    SignalData(
        signal_id="test-posthog-js-autocapture-001",
        content=(
            "Bug report: autocapture is not firing click events on dynamically inserted DOM nodes "
            "in single-page applications. The issue appears to be in the MutationObserver setup "
            "that watches for new elements. Customers using React or Vue with client-side routing "
            "are most affected."
        ),
        source_product="github_issues",
        source_type="bug",
        source_id="8001",
        weight=0.7,
        timestamp=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
        extra={
            "labels": ["bug", "autocapture"],
            "url": "https://github.com/PostHog/posthog-js/issues/8001",
        },
    ),
    SignalData(
        signal_id="test-posthog-js-session-replay-002",
        content=(
            "Feature request: add support for masking specific CSS selectors in session recordings. "
            "Currently the SDK only supports class-based masking via `maskAllInputs`. Customers want "
            "fine-grained control to mask individual components by CSS selector without adding classes. "
            "This would be a change in the rrweb integration layer of the JS SDK."
        ),
        source_product="github_issues",
        source_type="enhancement",
        source_id="8002",
        weight=0.5,
        timestamp=datetime(2025, 12, 11, 14, 30, 0, tzinfo=UTC),
        extra={
            "labels": ["feature", "session-replay", "sdk"],
        },
    ),
    SignalData(
        signal_id="test-posthog-js-feature-flags-003",
        content=(
            "Bug report: feature flag evaluation in the JavaScript SDK returns stale values after "
            "a page navigation in SPAs. The local evaluation cache is not invalidated when the URL "
            "changes. This causes users to see the wrong variant until a full page reload."
        ),
        source_product="zendesk",
        source_type="bug",
        source_id="55123",
        weight=0.8,
        timestamp=datetime(2025, 12, 12, 9, 15, 0, tzinfo=UTC),
        extra={
            "labels": ["bug", "feature-flags"],
        },
    ),
]

# Repos the agent should be able to choose from.
# In real usage these come from the team's GitHub integrations.
DEFAULT_CANDIDATE_REPOS = [
    "PostHog/posthog",
    "PostHog/posthog-js",
    "PostHog/posthog-python",
    "PostHog/posthog-ios",
]


class Command(BaseCommand):
    help = "Local dev tool: test repo selection in isolation. DEBUG only. Will be reworked into evals."

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def add_arguments(self, parser):
        parser.add_argument(
            "--repos",
            nargs="*",
            default=None,
            help=(
                "Candidate repos in owner/repo format. "
                "If omitted, uses the team's GitHub integrations (same as production). "
                "Pass explicit repos to test without integrations, e.g.: --repos PostHog/posthog PostHog/posthog-js"
            ),
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream full raw S3 log lines instead of only agent messages",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        verbose = options["verbose"]
        explicit_repos: list[str] | None = options["repos"]

        signals = list(TEST_SIGNALS)

        self.stdout.write(f"Signals: {len(signals)}")

        if explicit_repos is not None:
            if len(explicit_repos) < 2:
                raise CommandError("Pass at least 2 repos with --repos (with 1 repo, selection is skipped).")
            self.stdout.write(f"Candidate repos (explicit): {explicit_repos}")
            result = self._run_with_explicit_repos(signals, explicit_repos, verbose=verbose)
        else:
            self.stdout.write("Candidate repos: from team's GitHub integrations")
            result = self._run_from_integrations(signals, verbose=verbose)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Repo Selection Result ==="))
        if result.repository:
            self.stdout.write(f"Repository: {result.repository}")
        else:
            self.stdout.write("Repository: None (no match)")
        self.stdout.write(f"Reason: {result.reason}")

    def _run_from_integrations(self, signals: list[SignalData], *, verbose: bool) -> RepoSelectionResult:
        """Run repo selection using the team's actual GitHub integrations."""
        try:
            context = resolve_sandbox_context_for_local_dev(REPO_SELECTION_DUMMY_REPOSITORY)
        except RuntimeError as e:
            raise CommandError(str(e)) from e

        return asyncio.run(
            select_repository_for_report(
                team_id=context.team_id,
                user_id=context.user_id,
                signals=signals,
                verbose=verbose,
                output_fn=self._flushing_write,
            )
        )

    def _run_with_explicit_repos(
        self, signals: list[SignalData], candidate_repos: list[str], *, verbose: bool
    ) -> RepoSelectionResult:
        """Run repo selection with an explicit candidate list, bypassing GitHub integrations."""
        from products.tasks.backend.services.custom_prompt_executor import run_sandbox_agent_get_structured_output
        from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

        try:
            context_for_dev = resolve_sandbox_context_for_local_dev(REPO_SELECTION_DUMMY_REPOSITORY)
        except RuntimeError as e:
            raise CommandError(str(e)) from e

        prompt = _build_repo_selection_prompt(signals, candidate_repos)
        context = CustomPromptSandboxContext(
            team_id=context_for_dev.team_id,
            user_id=context_for_dev.user_id,
            repository=REPO_SELECTION_DUMMY_REPOSITORY,
        )

        result = asyncio.run(
            run_sandbox_agent_get_structured_output(
                prompt=prompt,
                context=context,
                model_to_validate=RepoSelectionResult,
                step_name="repo_selection",
                verbose=verbose,
                output_fn=self._flushing_write,
            )
        )

        if result.repository is not None:
            result.repository = result.repository.strip().lower()
        candidate_repos_lower = {r.lower() for r in candidate_repos}
        if result.repository is not None and result.repository not in candidate_repos_lower:
            self.stdout.write(
                self.style.WARNING(
                    f"Agent selected '{result.repository}' which is not in the candidate list, treating as no match."
                )
            )
            return RepoSelectionResult(
                repository=None,
                reason=f"Agent selected '{result.repository}' which is not in the candidate list. Original reason: '{result.reason}'",
            )

        return result
