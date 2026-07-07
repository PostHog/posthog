"""Tests for deny-list pattern matching in gates.py."""

from pathlib import Path

import pytest

from gates import (
    DEPENDENCY_ECOSYSTEMS,
    DISMISS_TIME_LOCKFILES,
    build_ownership,
    dependency_manifests_without_lockfile,
    detect_deny_categories,
    detect_ownership,
    detect_title_scrutiny_flags,
    has_dependency_changes,
    is_size_exempt,
    substantive_size,
)
from policy import OwnershipSource

# ── False positives that should NOT trigger ──────────────────────


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            [
                "frontend/src/queries/nodes/InsightViz/EditorFilters/SessionAnalysisWarning.tsx",
                "frontend/src/queries/nodes/InsightViz/EditorFilters/SuggestionBanner.tsx",
                "frontend/src/queries/nodes/InsightViz/EditorFilters/EditorFilterItems.tsx",
            ],
            id="session-analysis-warning-component",
        ),
        pytest.param(
            ["frontend/src/lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic.ts"],
            id="localstorage-recents-logic",
        ),
        pytest.param(
            ["frontend/src/lib/utils/tokenizer.ts"],
            id="tokenizer-not-auth-token",
        ),
        pytest.param(
            ["frontend/src/scenes/session-recordings/SessionRecordingPlayer.tsx"],
            id="session-recording-not-auth",
        ),
        pytest.param(
            ["frontend/src/lib/components/KeyboardShortcut.tsx"],
            id="keyboard-not-crypto-key",
        ),
        pytest.param(
            ["frontend/src/lib/hooks/useRoutingLogic.ts"],
            id="routing-logic-not-infra",
        ),
        pytest.param(
            ["products/signals/backend/temporal/backfill_error_tracking.py"],
            id="temporal-backfill-workflow-not-migration",
        ),
        pytest.param(
            ["posthog/management/commands/backfill_distinct_id_overrides.py"],
            id="backfill-management-command-not-migration",
        ),
        pytest.param(
            ["posthog/dags/backfill_materialized_column.py"],
            id="dagster-backfill-dag-not-migration",
        ),
        pytest.param(
            ["posthog/management/commands/migrate_team.py"],
            id="migrate-operator-command-not-migration",
        ),
        pytest.param(
            ["ee/api/subscription.py", "ee/api/test/test_subscription.py"],
            id="insight-subscriptions-not-billing",
        ),
        pytest.param(
            ["posthog/api/routing.py"],
            id="drf-routers-not-infra",
        ),
        pytest.param(
            ["docs/internal/checking-deploy-timing.md"],
            id="deploy-timing-docs-not-infra",
        ),
        pytest.param(
            ["products/conversations/backend/api/tests/test_slack_message_routing.py"],
            id="message-routing-test-not-infra",
        ),
        pytest.param(
            ["products/web_analytics/backend/temporal/health_checks/authorized_urls.py"],
            id="authorized-urls-domain-config-not-auth",
        ),
        pytest.param(
            ["dustbin/deploy.py"],
            id="bin-deploy-needs-path-anchor",
        ),
        pytest.param(
            ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py"],
            id="stripe-connector-not-billing",
        ),
        pytest.param(
            ["frontend/package.json"],
            id="manifest-without-lockfile-not-deps",
        ),
        pytest.param(
            ["pyproject.toml"],
            id="pyproject-without-lockfile-not-deps",
        ),
        pytest.param(
            ["common/esbuilder/tsconfig.json"],
            id="tsconfig-not-deps",
        ),
    ],
)
def test_no_false_positive(files: list[str]) -> None:
    assert detect_deny_categories(files) == []


# ── True positives that SHOULD trigger ───────────────────────────


@pytest.mark.parametrize(
    "files, expected_category",
    [
        pytest.param(
            ["posthog/api/authentication.py"],
            "auth",
            id="authentication-api-file",
        ),
        pytest.param(
            ["frontend/src/scenes/authentication/passwordResetLogic.ts"],
            "auth",
            id="authentication-scene-tree",
        ),
        pytest.param(
            ["posthog/api/login.py"],
            "auth",
            id="login-endpoint",
        ),
        pytest.param(
            ["posthog/models/oauth_config.py"],
            "auth",
            id="oauth-config",
        ),
        pytest.param(
            ["posthog/api/auth/session_token.py"],
            "auth",
            id="auth-session-token-path",
        ),
        pytest.param(
            ["posthog/crypto/encrypt.py"],
            "crypto_secrets",
            id="encryption-file",
        ),
        pytest.param(
            ["posthog/settings/.env.example"],
            "crypto_secrets",
            id="dot-env-file",
        ),
        pytest.param(
            ["posthog/api/api_key.py"],
            "crypto_secrets",
            id="api-key-file",
        ),
        pytest.param(
            ["posthog/models/secret_key_store.py"],
            "crypto_secrets",
            id="secret-key-file",
        ),
        pytest.param(
            ["posthog/migrations/0400_add_column.py"],
            "migrations",
            id="migration-file",
        ),
        pytest.param(
            ["rust/persons_migrations/20260206000001_add_last_seen_at.sql"],
            "migrations",
            id="rust-sqlx-migration",
        ),
        pytest.param(
            [".github/workflows/ci.yml"],
            "infra_cicd",
            id="github-workflow",
        ),
        pytest.param(
            ["bin/deploy-hobby"],
            "infra_cicd",
            id="deploy-hobby-script",
        ),
        pytest.param(
            ["livestream/deploy.sh"],
            "infra_cicd",
            id="deploy-sh-script",
        ),
        pytest.param(
            [".github/pr-deploy/values.yaml.tmpl"],
            "infra_cicd",
            id="pr-deploy-directory",
        ),
        pytest.param(
            ["posthog/models/two_factor_auth.py"],
            "auth",
            id="two-factor-auth-file",
        ),
        pytest.param(
            ["posthog/billing/stripe_webhook.py"],
            "billing",
            id="billing-file",
        ),
        pytest.param(
            ["pnpm-lock.yaml"],
            "deps_toolchain",
            id="pnpm-lockfile",
        ),
        pytest.param(
            ["rust/Cargo.lock"],
            "deps_toolchain",
            id="cargo-lockfile",
        ),
        pytest.param(
            ["composer.lock"],
            "deps_toolchain",
            id="composer-lockfile",
        ),
        pytest.param(
            ["requirements.txt"],
            "deps_toolchain",
            id="requirements-pins-directly",
        ),
        pytest.param(
            ["common/ingestion/requirements-dev.txt"],
            "deps_toolchain",
            id="requirements-variant-pins-too",
        ),
        pytest.param(
            ["frontend/package.json", "pnpm-lock.yaml"],
            "deps_toolchain",
            id="manifest-with-lockfile",
        ),
    ],
)
def test_true_positive(files: list[str], expected_category: str) -> None:
    result = detect_deny_categories(files)
    assert expected_category in result, f"Expected '{expected_category}' in {result}"


# ── Title scrutiny flags (titles never hard-deny) ────────────────


@pytest.mark.parametrize(
    "subject, expected_flags",
    [
        pytest.param("fix: oauth login redirect", ["auth"], id="auth-keywords"),
        pytest.param("fix: stripe invoice pagination", ["billing"], id="billing-keywords"),
        pytest.param("feat(subscriptions): raise hourly org cap", [], id="insight-subscription-not-billing"),
        pytest.param("chore: migrate helm chart to terraform", ["infra_cicd"], id="infra-keywords"),
        pytest.param("fix: authorized urls health check", ["auth"], id="title-only-past-participle"),
        pytest.param("fix(insights): trend legend overlap", [], id="neutral-title"),
        pytest.param("fix: authentication flow", ["auth"], id="authentication-long-form"),
        pytest.param("feat: stripe oauth billing sync", ["auth", "billing"], id="two-category-title"),
    ],
)
def test_title_scrutiny_flags(subject: str, expected_flags: list[str]) -> None:
    # Titles flag for LLM scrutiny but never deny — a title-only keyword
    # must not put the PR in T2-never (56-83% of those merged unchanged).
    assert detect_title_scrutiny_flags(subject) == expected_flags


# ── Deny-list bypass via ignored_files ───────────────────────────


def test_ignored_files_bypass_deny_list() -> None:
    files = [
        "posthog/migrations/1117_alter_integration_kind.py",
        "posthog/migrations/max_migration.txt",
    ]
    ignored = set(files)

    assert detect_deny_categories(files, ignored_files=ignored) == []


def test_ignored_files_does_not_bypass_other_deny_list_files() -> None:
    files = [
        "posthog/migrations/1117_alter_integration_kind.py",
        "posthog/migrations/1118_add_column.py",
    ]
    ignored = {"posthog/migrations/1117_alter_integration_kind.py"}

    assert detect_deny_categories(files, ignored_files=ignored) == ["migrations"]


# ── Data warehouse connector exemption (auth + billing) ──────────


@pytest.mark.parametrize(
    "files, exempt_category",
    [
        pytest.param(
            ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/auth.py"],
            "auth",
            id="dwh-source-auth-file",
        ),
        pytest.param(
            [
                "products/warehouse_sources/backend/temporal/data_imports/sources/salesforce/source.py",
                "products/warehouse_sources/backend/temporal/data_imports/sources/salesforce/settings.py",
            ],
            "auth",
            id="dwh-source-multi-file",
        ),
        pytest.param(
            ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/stripe_billing.py"],
            "billing",
            id="dwh-source-billing-file",
        ),
    ],
)
def test_dwh_source_exempt(files: list[str], exempt_category: str) -> None:
    assert exempt_category not in detect_deny_categories(files)


def test_dwh_source_still_denies_non_exempt_categories() -> None:
    # Only auth/billing are exempted — crypto/secrets still applies to
    # connector files that handle stored customer API keys.
    files = ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/api_key_store.py"]
    result = detect_deny_categories(files)
    assert "auth" not in result
    assert "crypto_secrets" in result


def test_dwh_source_mixed_still_denies() -> None:
    # The exemption is per-path, not per-PR: a real auth file alongside
    # connector files must still deny.
    files = [
        "products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py",
        "posthog/api/authentication.py",
    ]
    assert "auth" in detect_deny_categories(files)


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


# ── Dependency manifests without a lockfile ──────────────────────


@pytest.mark.parametrize(
    "files, expected",
    [
        pytest.param(
            ["frontend/package.json", "frontend/src/app.ts"],
            ["frontend/package.json"],
            id="manifest-only-flagged",
        ),
        pytest.param(
            ["frontend/package.json", "pnpm-lock.yaml"],
            [],
            id="lockfile-present-hard-denies-instead",
        ),
        pytest.param(
            ["common/esbuilder/tsconfig.json"],
            ["common/esbuilder/tsconfig.json"],
            id="tsconfig-flagged",
        ),
        pytest.param(
            ["posthog/api/insight.py"],
            [],
            id="no-manifests",
        ),
        pytest.param(
            ["frontend/package.json", "rust/Cargo.lock"],
            ["frontend/package.json"],
            id="unrelated-ecosystem-lockfile-does-not-suppress",
        ),
        pytest.param(
            ["common/esbuilder/tsconfig.json", "pnpm-lock.yaml"],
            ["common/esbuilder/tsconfig.json"],
            id="tsconfig-has-no-lockfile-always-flagged",
        ),
        pytest.param(
            ["composer.json"],
            ["composer.json"],
            id="composer-manifest-flagged",
        ),
        pytest.param(
            ["docs/some_tsconfig_notes.md"],
            [],
            id="tsconfig-substring-not-manifest",
        ),
    ],
)
def test_dependency_manifests_without_lockfile(files: list[str], expected: list[str]) -> None:
    # The deny-list no longer blocks manifest-only changes, so this helper is
    # what routes them to the reviewer's scripts/hooks guard — if it breaks,
    # a package.json scripts edit sails through with no scrutiny at all.
    assert dependency_manifests_without_lockfile(files) == expected


@pytest.mark.parametrize("ecosystem", list(DEPENDENCY_ECOSYSTEMS))
def test_dependency_ecosystem_names_are_lowercase(ecosystem: str) -> None:
    # Call sites match against Path(...).name.lower(); a mixed-case entry
    # here would silently never match and go unrecognized in a security gate.
    spec = DEPENDENCY_ECOSYSTEMS[ecosystem]
    for name in (*spec.manifests, *spec.lockfiles):
        assert name == name.lower()


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("common/esbuilder/tsconfig.json", id="tsconfig"),
        pytest.param("setup.py", id="setup-py"),
        pytest.param("setup.cfg", id="setup-cfg"),
        pytest.param("pipfile", id="pipfile-manifest"),
        pytest.param("gemfile", id="gemfile-manifest"),
        pytest.param("composer.json", id="composer-manifest"),
        pytest.param("pipfile.lock", id="pipfile-lock"),
        pytest.param("gemfile.lock", id="gemfile-lock"),
        pytest.param("composer.lock", id="composer-lock"),
    ],
)
def test_has_dependency_changes_recognizes_uncurated_manifests_and_lockfiles(path: str) -> None:
    # Pins the members that DEPENDENCY_ECOSYSTEMS added beyond the old
    # curated set — a future narrowing of the table should fail here rather
    # than silently stop flagging these as dependency changes.
    assert has_dependency_changes([path]) is True


def test_dismiss_time_trust_is_opt_in_per_ecosystem() -> None:
    # Dismiss-time trust must be an explicit per-ecosystem decision: go.sum
    # (trusted_at_dismiss unset) stays out even though it is a deny-listed
    # lockfile, while node's lockfiles — including npm-shrinkwrap.json — opt
    # in. Catches a revert to deriving trust from the whole lockfile set.
    assert "go.sum" not in DISMISS_TIME_LOCKFILES
    assert "pnpm-lock.yaml" in DISMISS_TIME_LOCKFILES
    assert "npm-shrinkwrap.json" in DISMISS_TIME_LOCKFILES


# ── Ownership sources ────────────────────────────────────────────

_PH_PRODUCT = (OwnershipSource(format="ph-product", glob="products/*/product.yaml"),)


@pytest.mark.parametrize(
    "owners_yaml, expected_teams",
    [
        pytest.param("owners:\n  - team-devex\n", ["@PostHog/team-devex"], id="plain-slug-prefixed"),
        pytest.param("owners:\n  - '@PostHog/team-x'\n", [], id="already-prefixed-skipped"),
        pytest.param("owners:\n  - team-CHANGEME\n", [], id="changeme-skipped"),
        pytest.param("name: foo\n", [], id="ownerless"),
        pytest.param("owners: value: bad\n", [], id="unparseable"),
    ],
)
def test_product_yaml_owner_normalization(tmp_path: Path, owners_yaml: str, expected_teams: list[str]) -> None:
    product_dir = tmp_path / "products" / "foo"
    product_dir.mkdir(parents=True)
    (product_dir / "product.yaml").write_text(owners_yaml)

    resolvers = build_ownership(tmp_path, _PH_PRODUCT)
    ownership = detect_ownership(["products/foo/backend/models.py"], resolvers)

    assert ownership["teams"] == expected_teams


def test_ownership_unions_codeowners_and_product_yaml(tmp_path: Path) -> None:
    codeowners = tmp_path / ".github" / "CODEOWNERS-soft"
    codeowners.parent.mkdir(parents=True)
    codeowners.write_text("products/foo/sub/ @PostHog/team-a\nposthog/ @PostHog/team-c\n")
    product_dir = tmp_path / "products" / "foo"
    product_dir.mkdir(parents=True)
    (product_dir / "product.yaml").write_text("owners:\n  - team-b\n")

    resolvers = build_ownership(
        tmp_path,
        (
            OwnershipSource(format="gh-codeowners", path=".github/CODEOWNERS-soft"),
            OwnershipSource(format="ph-product", glob="products/*/product.yaml"),
        ),
    )

    both = detect_ownership(["products/foo/sub/x.py"], resolvers)
    assert both["teams"] == ["@PostHog/team-a", "@PostHog/team-b"]
    assert both["cross_team"] is True

    product_only = detect_ownership(["products/foo/y.py"], resolvers)
    assert product_only["teams"] == ["@PostHog/team-b"]
    assert product_only["cross_team"] is False

    outside = detect_ownership(["posthog/models/x.py"], resolvers)
    assert outside["teams"] == ["@PostHog/team-c"]
