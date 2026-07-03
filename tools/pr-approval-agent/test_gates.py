"""Tests for deny-list pattern matching in gates.py."""

import pytest

from gates import detect_deny_categories, is_size_exempt, substantive_size

# ── False positives that should NOT trigger ──────────────────────


@pytest.mark.parametrize(
    "files, subject",
    [
        pytest.param(
            [
                "frontend/src/queries/nodes/InsightViz/EditorFilters/SessionAnalysisWarning.tsx",
                "frontend/src/queries/nodes/InsightViz/EditorFilters/SuggestionBanner.tsx",
                "frontend/src/queries/nodes/InsightViz/EditorFilters/EditorFilterItems.tsx",
            ],
            "chore(insights): extract SessionAnalysisWarning, SuggestionBanner, EditorFilterItems",
            id="session-analysis-warning-component",
        ),
        pytest.param(
            ["frontend/src/lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic.ts"],
            "fix(taxonomic-filter): scope recents localStorage key by team id",
            id="localstorage-key-in-title",
        ),
        pytest.param(
            ["frontend/src/lib/utils/tokenizer.ts"],
            "fix: improve tokenizer performance",
            id="tokenizer-not-auth-token",
        ),
        pytest.param(
            ["frontend/src/scenes/session-recordings/SessionRecordingPlayer.tsx"],
            "feat(replay): add session recording playback controls",
            id="session-recording-not-auth",
        ),
        pytest.param(
            ["frontend/src/lib/components/KeyboardShortcut.tsx"],
            "fix: keyboard shortcut not working",
            id="keyboard-not-crypto-key",
        ),
        pytest.param(
            ["frontend/src/lib/hooks/useRoutingLogic.ts"],
            "fix: routing logic for dashboard",
            id="routing-logic-not-infra",
        ),
        pytest.param(
            ["products/signals/backend/temporal/backfill_error_tracking.py"],
            "chore(sig): scopes and tags for exception capture",
            id="temporal-backfill-workflow-not-migration",
        ),
        pytest.param(
            ["posthog/management/commands/backfill_distinct_id_overrides.py"],
            "feat: backfill distinct id overrides",
            id="backfill-management-command-not-migration",
        ),
        pytest.param(
            ["posthog/dags/backfill_materialized_column.py"],
            "fix: dagster backfill dag",
            id="dagster-backfill-dag-not-migration",
        ),
        pytest.param(
            ["posthog/management/commands/migrate_team.py"],
            "fix: team migration command",
            id="migrate-operator-command-not-migration",
        ),
    ],
)
def test_no_false_positive(files: list[str], subject: str) -> None:
    assert detect_deny_categories(files, subject) == []


# ── True positives that SHOULD trigger ───────────────────────────


@pytest.mark.parametrize(
    "files, subject, expected_category",
    [
        pytest.param(
            ["posthog/api/authentication.py"],
            "fix: auth flow redirect",
            "auth",
            id="auth-file-and-title",
        ),
        pytest.param(
            ["posthog/api/login.py"],
            "fix: login endpoint",
            "auth",
            id="login-endpoint",
        ),
        pytest.param(
            ["posthog/models/oauth_config.py"],
            "feat: add oauth config",
            "auth",
            id="oauth-config",
        ),
        pytest.param(
            ["posthog/api/auth/session_token.py"],
            "fix: session token refresh",
            "auth",
            id="auth-session-token-path",
        ),
        pytest.param(
            ["posthog/crypto/encrypt.py"],
            "feat: add encryption support",
            "crypto_secrets",
            id="encryption-file",
        ),
        pytest.param(
            ["posthog/settings/.env.example"],
            "chore: update env example",
            "crypto_secrets",
            id="dot-env-file",
        ),
        pytest.param(
            ["posthog/api/api_key.py"],
            "fix: api key rotation",
            "crypto_secrets",
            id="api-key-file",
        ),
        pytest.param(
            ["posthog/models/secret_key_store.py"],
            "feat: secret key management",
            "crypto_secrets",
            id="secret-key-file",
        ),
        pytest.param(
            ["posthog/migrations/0400_add_column.py"],
            "feat: add new column",
            "migrations",
            id="migration-file",
        ),
        pytest.param(
            ["rust/persons_migrations/20260206000001_add_last_seen_at.sql"],
            "feat: add last_seen_at to persons",
            "migrations",
            id="rust-sqlx-migration",
        ),
        pytest.param(
            [".github/workflows/ci.yml"],
            "chore(ci): update workflow",
            "infra_cicd",
            id="github-workflow",
        ),
        pytest.param(
            ["posthog/billing/stripe_webhook.py"],
            "fix: billing webhook",
            "billing",
            id="billing-file",
        ),
        pytest.param(
            ["package.json"],
            "chore: update dependencies",
            "deps_toolchain",
            id="package-json",
        ),
        pytest.param(
            ["pyproject.toml"],
            "chore: bump version",
            "deps_toolchain",
            id="pyproject-toml",
        ),
    ],
)
def test_true_positive(files: list[str], subject: str, expected_category: str) -> None:
    result = detect_deny_categories(files, subject)
    assert expected_category in result, f"Expected '{expected_category}' in {result}"


# ── Deny-list bypass via ignored_files ───────────────────────────


def test_ignored_files_bypass_deny_list() -> None:
    files = [
        "posthog/migrations/1117_alter_integration_kind.py",
        "posthog/migrations/max_migration.txt",
    ]
    ignored = set(files)

    assert detect_deny_categories(files, "feat: add postgresql integration", ignored_files=ignored) == []


def test_ignored_files_does_not_bypass_other_deny_list_files() -> None:
    files = [
        "posthog/migrations/1117_alter_integration_kind.py",
        "posthog/migrations/1118_add_column.py",
    ]
    ignored = {"posthog/migrations/1117_alter_integration_kind.py"}

    assert detect_deny_categories(files, "feat: integration field", ignored_files=ignored) == ["migrations"]


# ── Data warehouse source auth exemption ─────────────────────────


@pytest.mark.parametrize(
    "files, subject",
    [
        pytest.param(
            ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/auth.py"],
            "fix(stripe): refresh oauth token before sync",
            id="dwh-source-auth-file-and-title",
        ),
        pytest.param(
            ["products/warehouse_sources/backend/temporal/data_imports/sources/postgres/source.py"],
            "fix(postgres): treat invalid SSH tunnel auth as non-retryable",
            id="dwh-source-auth-in-title-only",
        ),
        pytest.param(
            [
                "products/warehouse_sources/backend/temporal/data_imports/sources/salesforce/source.py",
                "products/warehouse_sources/backend/temporal/data_imports/sources/salesforce/settings.py",
            ],
            "fix(salesforce): treat deleted oauth credential as non-retryable",
            id="dwh-source-multi-file-oauth-credential",
        ),
    ],
)
def test_dwh_source_auth_exempt(files: list[str], subject: str) -> None:
    assert "auth" not in detect_deny_categories(files, subject)


def test_dwh_source_still_denies_non_auth_categories() -> None:
    # Only `auth` is exempted — crypto/secrets still applies to source files.
    files = ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/api_key_store.py"]
    result = detect_deny_categories(files, "feat(stripe): rotate api key")
    assert "auth" not in result
    assert "crypto_secrets" in result


@pytest.mark.parametrize(
    "files, subject",
    [
        pytest.param(
            [
                "products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py",
                "posthog/api/authentication.py",
            ],
            "fix: stripe auth and login flow",
            id="dwh-source-mixed-real-auth-file",
        ),
        pytest.param(
            [
                "products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py",
                "posthog/api/foo.py",
            ],
            "fix: oauth login redirect",
            id="dwh-source-mixed-unrelated-file-auth-title",
        ),
    ],
)
def test_dwh_source_mixed_still_denies(files: list[str], subject: str) -> None:
    # Auth gate must still fire when any non-source file is in the change set.
    assert "auth" in detect_deny_categories(files, subject)


# ── Size-ceiling exemptions ──────────────────────────────────────


@pytest.mark.parametrize(
    "path, exempt",
    [
        pytest.param("docs/internal/monorepo-layout.md", True, id="markdown"),
        pytest.param(".agents/skills/foo/SKILL.md", True, id="skill-markdown"),
        pytest.param("docs/example-snippet.ts", True, id="docs-dir-artifact-extension"),
        pytest.param("posthog/api/test/__snapshots__/test_api.ambr", True, id="ambr-snapshot"),
        pytest.param("frontend/__snapshots__/scene.storyshot", True, id="storyshot-extension"),
        pytest.param("posthog/test/__snapshots__/helper.py", False, id="executable-under-snapshots-counted"),
        pytest.param("frontend/src/generated/core/api.schemas.ts", True, id="generated-dir"),
        pytest.param("products/tasks/frontend/generated/api.ts", True, id="product-generated-dir"),
        pytest.param("frontend/src/queries/schema/schema-general.ts", True, id="queries-schema"),
        pytest.param("frontend/src/types.gen.ts", True, id="dot-gen-suffix"),
        pytest.param("pnpm-lock.yaml", False, id="lockfile-yaml-counted"),
        pytest.param("uv.lock", True, id="lockfile-lock-ext"),
        pytest.param("posthog/api/insight.py", False, id="python-code"),
        pytest.param("frontend/src/scenes/insights/Insight.tsx", False, id="frontend-code"),
        pytest.param("posthog/settings/web.py", False, id="settings-code"),
        pytest.param("docker-compose.dev.yml", False, id="yaml-config"),
        pytest.param("package.json", False, id="json-config"),
        pytest.param("regenerated_totals.py", False, id="generated-substring-not-dir"),
        pytest.param("frontend/src/generated/core/evil.py", False, id="generated-dir-executable-py"),
        pytest.param("frontend/src/generated/core/build.sh", False, id="generated-dir-executable-sh"),
        pytest.param("docs/generate_sidebar.py", False, id="docs-dir-executable-py"),
    ],
)
def test_is_size_exempt(path: str, exempt: bool) -> None:
    assert is_size_exempt(path) is exempt


def test_substantive_size_counts_only_non_exempt_files() -> None:
    # A docs-heavy PR must not be size-denied for its prose, and a code-heavy
    # PR must not slip under the ceiling by padding with docs.
    files = [
        {"filename": "docs/big-rewrite.md", "additions": 2000, "deletions": 500},
        {"filename": "frontend/src/generated/core/api.ts", "additions": 900, "deletions": 900},
        {"filename": "posthog/api/insight.py", "additions": 30, "deletions": 10},
        {"filename": "posthog/api/test/test_insight.py", "additions": 50, "deletions": 0},
    ]

    lines, file_count = substantive_size(files)

    assert lines == 90
    assert file_count == 2
