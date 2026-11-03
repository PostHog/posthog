"""Synthetic repository catalog and cases for the repository-selection evals.

Pure and Django-free, so the catalog is unit-testable and byte-for-byte reproducible.
The seeder installs it into each case's isolated team; prompts, scorers, and seeders all
import the names below so they cannot drift apart.

Everything here is invented. The `fernhill` organization, its repositories, and every path
and README line exist only in this file.

Model-visible input is a case's Slack thread and the seeded catalog. Expected answers live
in `SelectorExpectation` and `RoutingExpectation`, which only scorers read.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal

from posthog.dataclasses import frozen

FIXTURE_VERSION = "2026-11-03.1"

ORG = "fernhill"
BOT_MENTION = "@PostHog"

STOREFRONT = f"{ORG}/storefront"
CORE_API = f"{ORG}/core-api"
DOCS_SITE = f"{ORG}/docs-site"
MARKETING_SITE = f"{ORG}/marketing-site"
IOS_SDK = f"{ORG}/fernhill-ios"
ANDROID_SDK = f"{ORG}/fernhill-android"
PAYMENTS_UI = f"{ORG}/payments-ui"
HERMES = f"{ORG}/hermes"
ATLAS = f"{ORG}/atlas"


@frozen
class FixtureRepository:
    full_name: str
    description: str
    primary_language: str
    topics: tuple[str, ...]
    private: bool
    readme: str
    tree_paths: tuple[str, ...]
    archived: bool = False

    @property
    def name(self) -> str:
        return self.full_name.split("/", 1)[1]

    @property
    def default_branch_sha(self) -> str:
        # Stable per content, so a reseeded catalog reads as the same commit.
        digest = hashlib.sha256(f"{self.full_name}\n{self.readme}\n{chr(10).join(self.tree_paths)}".encode())
        # A git commit SHA is 40 hex characters.
        return digest.hexdigest()[:40]


REPOSITORIES: tuple[FixtureRepository, ...] = (
    FixtureRepository(
        full_name=STOREFRONT,
        description="Customer-facing web shop: catalogue, cart, checkout, and account signup.",
        primary_language="TypeScript",
        topics=("nextjs", "react", "ecommerce"),
        private=True,
        readme=(
            "# Storefront\n\n"
            "The Next.js web shop customers use at shop.fernhill.example. It renders the product catalogue, "
            "the cart, the checkout flow, and account signup.\n\n"
            "## Analytics\n\n"
            "Product analytics is initialised in `src/analytics/posthog-init.ts` with autocapture enabled. "
            "Custom events, including `signup_completed` and `checkout_started`, are captured from "
            "`src/analytics/events.ts`.\n\n"
            "## Development\n\n`pnpm install && pnpm dev`\n"
        ),
        tree_paths=(
            "package.json",
            "next.config.mjs",
            "src/analytics/posthog-init.ts",
            "src/analytics/events.ts",
            "src/analytics/track-signup-completed.ts",
            "src/pages/index.tsx",
            "src/pages/cart.tsx",
            "src/pages/checkout/index.tsx",
            "src/pages/checkout/confirmation.tsx",
            "src/pages/signup/index.tsx",
            "src/pages/signup/SignupForm.tsx",
            "src/pages/signup/SignupForm.module.css",
            "src/components/checkout/PayButton.tsx",
            "src/components/checkout/AddressFields.tsx",
            "src/components/checkout/OrderSummary.tsx",
            "src/components/catalogue/ProductCard.tsx",
            "src/components/layout/Header.tsx",
            "src/lib/api-client.ts",
            "src/lib/money.ts",
            "tests/checkout/pay-button.spec.ts",
            "tests/signup/signup-form.spec.ts",
        ),
    ),
    FixtureRepository(
        full_name=CORE_API,
        description="Django REST backend for accounts, projects, orders, and billing.",
        primary_language="Python",
        topics=("django", "rest-api", "backend"),
        private=True,
        readme=(
            "# Core API\n\n"
            "The Django REST Framework service behind the storefront and the mobile apps. It owns accounts, "
            "projects, orders, and billing webhooks.\n\n"
            "Access checks live in `accounts/permissions.py`; each viewset declares its own "
            "`permission_classes`.\n\n"
            "## Running\n\n`uv sync && ./manage.py runserver`\n"
        ),
        tree_paths=(
            "pyproject.toml",
            "manage.py",
            "core_api/settings.py",
            "core_api/urls.py",
            "accounts/models.py",
            "accounts/permissions.py",
            "accounts/views/signup.py",
            "accounts/views/session.py",
            "accounts/tests/test_permissions.py",
            "api/projects/viewsets.py",
            "api/projects/serializers.py",
            "api/projects/pagination.py",
            "api/projects/tests/test_viewsets.py",
            "api/orders/viewsets.py",
            "api/orders/serializers.py",
            "billing/stripe_webhooks.py",
            "billing/invoices.py",
            "billing/tests/test_webhooks.py",
        ),
    ),
    FixtureRepository(
        full_name=DOCS_SITE,
        description="Source of docs.fernhill.example, the product documentation website.",
        primary_language="TypeScript",
        topics=("astro", "documentation", "website"),
        private=False,
        readme=(
            "# Docs site\n\n"
            "The Astro site served at docs.fernhill.example. Pages live in `src/content/docs/`; the "
            "getting-started guide is `src/content/docs/getting-started.mdx`.\n\n"
            "Large screenshots go through `src/components/ResponsiveImage.astro`.\n"
        ),
        tree_paths=(
            "package.json",
            "astro.config.mjs",
            "src/content/docs/getting-started.mdx",
            "src/content/docs/sdks/ios.mdx",
            "src/content/docs/sdks/android.mdx",
            "src/content/docs/api/authentication.mdx",
            "src/components/ResponsiveImage.astro",
            "src/components/Search.astro",
            "src/components/Sidebar.astro",
            "src/layouts/DocsLayout.astro",
            "public/images/getting-started/dashboard-overview.png",
            "public/images/getting-started/install-snippet.png",
        ),
    ),
    FixtureRepository(
        full_name=MARKETING_SITE,
        description="The marketing homepage, pricing page, and blog at fernhill.example.",
        primary_language="TypeScript",
        topics=("website", "marketing", "blog"),
        private=False,
        readme=(
            "# Marketing site\n\n"
            "Homepage, pricing, customer stories, and the blog at fernhill.example. Product documentation is "
            "not here.\n"
        ),
        tree_paths=(
            "package.json",
            "src/pages/index.tsx",
            "src/pages/pricing.tsx",
            "src/pages/customers/[slug].tsx",
            "src/pages/blog/[slug].tsx",
            "src/components/Hero.tsx",
            "src/components/PricingTable.tsx",
            "content/blog/2026-launch-week.md",
        ),
    ),
    FixtureRepository(
        full_name=IOS_SDK,
        description="Fernhill iOS SDK: event capture and session replay for Swift apps.",
        primary_language="Swift",
        topics=("ios", "sdk", "swift", "session-replay"),
        private=False,
        readme=(
            "# Fernhill iOS SDK\n\n"
            "Swift package for capturing events and recording sessions in iOS apps. Session replay starts "
            "with `FernhillReplay.start()`.\n\n"
            "## Changelog\n\nSee `CHANGELOG.md`. Version 3.19.0 moved replay start into app launch.\n"
        ),
        tree_paths=(
            "Package.swift",
            "CHANGELOG.md",
            "Sources/Fernhill/Fernhill.swift",
            "Sources/Fernhill/Capture/EventQueue.swift",
            "Sources/Fernhill/Replay/FernhillReplay.swift",
            "Sources/Fernhill/Replay/ReplayRecorder.swift",
            "Sources/Fernhill/Replay/ReplayConfig.swift",
            "Sources/Fernhill/Lifecycle/AppLaunchObserver.swift",
            "Tests/FernhillTests/ReplayTests.swift",
            "Tests/FernhillTests/AppLaunchTests.swift",
        ),
    ),
    FixtureRepository(
        full_name=ANDROID_SDK,
        description="Fernhill Android SDK: event capture and session replay for Kotlin apps.",
        primary_language="Kotlin",
        topics=("android", "sdk", "kotlin", "session-replay"),
        private=False,
        readme=(
            "# Fernhill Android SDK\n\n"
            "Kotlin library for capturing events and recording sessions in Android apps. Version 3.19.0 "
            "added frame batching to session replay.\n"
        ),
        tree_paths=(
            "build.gradle.kts",
            "CHANGELOG.md",
            "fernhill/src/main/java/com/fernhill/Fernhill.kt",
            "fernhill/src/main/java/com/fernhill/capture/EventQueue.kt",
            "fernhill/src/main/java/com/fernhill/replay/ReplayRecorder.kt",
            "fernhill/src/main/java/com/fernhill/replay/FrameBatcher.kt",
            "fernhill/src/main/java/com/fernhill/replay/ReplayConfig.kt",
            "fernhill/src/test/java/com/fernhill/replay/FrameBatcherTest.kt",
        ),
    ),
    # Misleading name: the checkout code lives in the storefront. This repo holds old prototypes.
    FixtureRepository(
        full_name=PAYMENTS_UI,
        description="Design prototypes for an early payments page. Not deployed.",
        primary_language="JavaScript",
        topics=("prototype", "design"),
        private=True,
        readme=(
            "# payments-ui\n\n"
            "Static design prototypes from the 2024 payments redesign. Nothing here is built or deployed; "
            "the production checkout was rebuilt elsewhere.\n"
        ),
        tree_paths=(
            "README.md",
            "prototypes/pay-page-v1.html",
            "prototypes/pay-page-v2.html",
            "prototypes/assets/pay-page.css",
        ),
    ),
    # Routing-rule targets. Nothing in their caches ties them to the rules' topics, so only the
    # rule can steer a request here.
    FixtureRepository(
        full_name=HERMES,
        description="Internal service.",
        primary_language="Python",
        topics=("internal",),
        private=True,
        readme="# Hermes\n\nInternal service. Deploy with `make deploy`.\n",
        tree_paths=(
            "pyproject.toml",
            "Makefile",
            "hermes/app.py",
            "hermes/handlers/query.py",
            "hermes/handlers/index.py",
            "hermes/store.py",
            "tests/test_query.py",
        ),
    ),
    FixtureRepository(
        full_name=ATLAS,
        description="Internal service.",
        primary_language="TypeScript",
        topics=("internal",),
        private=True,
        readme="# Atlas\n\nInternal service. `pnpm start` runs it locally.\n",
        tree_paths=(
            "package.json",
            "src/server.ts",
            "src/routes/home.tsx",
            "src/routes/tiles.tsx",
            "src/lib/fetcher.ts",
            "tests/home.spec.ts",
        ),
    ),
)

REPOSITORY_NAMES: tuple[str, ...] = tuple(repo.full_name for repo in REPOSITORIES)


@frozen
class RoutingRuleFixture:
    rule_text: str
    repository: str


@frozen
class ThreadMessage:
    user: str
    text: str


Stage = Literal["cascade", "classifier", "selector"]
Outcome = Literal["auto", "no_repo", "found", "no_match"]


@frozen
class SelectorExpectation:
    """What the discovery agent should return. Exactly one of `accepted` or `abstain` is set."""

    accepted: tuple[str, ...] = ()
    abstain: bool = False

    def __post_init__(self) -> None:
        if bool(self.accepted) == self.abstain:
            raise ValueError("A selector expectation names accepted repositories or an abstention, not both")
        unknown = set(self.accepted) - set(REPOSITORY_NAMES)
        if unknown:
            raise ValueError(f"Expected repositories are not in the catalog: {sorted(unknown)}")


@frozen
class RoutingExpectation:
    stage: Stage
    outcome: Outcome
    # Set when the terminal stage selects a repository; scored against the selected repo.
    selector: SelectorExpectation | None = None
    # Set for cascade selections, which are deterministic.
    repository: str | None = None


@frozen
class RepoSelectionScenario:
    name: str
    description: str
    thread: tuple[ThreadMessage, ...]
    routing_rules: tuple[RoutingRuleFixture, ...] = ()

    @property
    def mention_text(self) -> str:
        # The message that addresses the bot. Later replies are thread context, as in Slack.
        return next(message.text for message in reversed(self.thread) if BOT_MENTION in message.text)

    @property
    def context_block(self) -> str:
        # The same rendering the Slack discovery activity hands the selector.
        return "\n".join(f"{message.user}: {message.text}" for message in self.thread)


@frozen
class RoutingCase:
    scenario: RepoSelectionScenario
    expected: RoutingExpectation
    note: str = ""


@frozen
class SelectorCase:
    scenario: RepoSelectionScenario
    expected: SelectorExpectation
    # Names the property this case isolates, for per-category reporting.
    category: str


def _thread(*messages: tuple[str, str]) -> tuple[ThreadMessage, ...]:
    return tuple(ThreadMessage(user=user, text=text) for user, text in messages)


def _ask(text: str, *earlier: tuple[str, str]) -> tuple[ThreadMessage, ...]:
    return _thread(*earlier, ("tester", text))


SUPPORT_DESK_RULE = RoutingRuleFixture(rule_text="Anything about the internal support desk", repository=HERMES)
METRICS_DASHBOARD_RULE = RoutingRuleFixture(rule_text="The internal metrics dashboard", repository=ATLAS)
CATCH_ALL_RULE = RoutingRuleFixture(rule_text="Route every request to the internal service", repository=HERMES)


def _scenario(
    name: str,
    description: str,
    thread: tuple[ThreadMessage, ...],
    routing_rules: Sequence[RoutingRuleFixture] = (),
) -> RepoSelectionScenario:
    return RepoSelectionScenario(name=name, description=description, thread=thread, routing_rules=tuple(routing_rules))


# Scenarios that reach the discovery agent, shared by both suites so a selector change and an
# end-to-end change are measured on the same request text.
DOCS_SITE_SLOW = _scenario(
    "marketing_site",
    "Performance complaint about the docs site; the marketing site is a same-domain distractor.",
    _thread(
        ("tester", "@PostHog the docs site loads really slowly on mobile"),
        ("other", "yeah I noticed the same on /docs/getting-started"),
    ),
)
IOS_CRASH = _scenario(
    "sdk_specific_trace_trip",
    "iOS SDK crash with a stack frame; the Android SDK also has replay code.",
    _thread(
        ("tester", "@PostHog the iOS SDK is crashing on app launch after upgrade to 3.19"),
        ("other", "stack trace shows FernhillReplay.start() failing"),
    ),
)
AUTOCAPTURE_CHECKOUT = _scenario(
    "sdk_instrumentation_on_own_site",
    "Analytics SDK misbehaving on the team's own site; the fix is in the site's code.",
    _thread(
        ("tester", "@PostHog autocapture isn't picking up clicks on our checkout button, other buttons work"),
        ("other", "we just shipped a redesign yesterday"),
    ),
)
MISSING_SIGNUP_EVENTS = _scenario(
    "wrong_data_tracking_bug",
    "Missing analytics data is almost always a tracking bug in the team's code.",
    _thread(
        ("tester", "@PostHog we're not seeing any signup_completed events even though we tested signups today"),
        ("other", "the funnel shows 0 conversions but our team manually completed 5"),
    ),
)
VAGUE_SIGNUP_RENDER = _scenario(
    "vague_code_bug",
    "Vague but code-flavored; the cache disambiguates the signup UI.",
    _ask("@PostHog there's a bug in how we render user signup, can you fix it"),
)
PROJECTS_VIEWSET = _scenario(
    "api_viewset",
    "An explicit code pattern (viewset) names backend code.",
    _ask("@PostHog the /api/projects/ viewset crashes on large payloads, can you fix it"),
)
SIGNUP_TSX = _scenario(
    "explicit_code_file",
    "An explicit .tsx file extension names frontend code.",
    _ask("@PostHog add a Cancel button to the signup form in the .tsx component"),
)
PERMISSION_REFACTOR = _scenario(
    "refactor_request",
    "A code-flavored refactor with no debug terms.",
    _ask("@PostHog please refactor the user permission check into a single helper"),
)
SUPPORT_DESK = _scenario(
    "routing_rule_steers_vague_ask",
    "A configured routing rule steers an ask no cache content links to a repository.",
    _ask("@PostHog the internal support desk search endpoint is throwing 500s, can you fix it"),
    routing_rules=(SUPPORT_DESK_RULE,),
)
METRICS_DASHBOARD = _scenario(
    "routing_rule_overrides_no_repo_gate",
    "A routing rule keeps a product-term ask (dashboard) from stopping at the no-repo gate.",
    _ask("@PostHog the internal metrics dashboard shows a blank page, can you fix it"),
    routing_rules=(METRICS_DASHBOARD_RULE,),
)

ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase(
        scenario=_scenario(
            "explicit_mention",
            "The cascade picks the repo directly when the text names a connected org/repo.",
            _ask(f"@PostHog can you look at {CORE_API} and fix the readme typo"),
        ),
        expected=RoutingExpectation(stage="cascade", outcome="auto", repository=CORE_API),
    ),
    RoutingCase(
        scenario=_scenario(
            "ci_run_link",
            "The cascade reads the repo out of a workflow-run link.",
            _ask(f"@PostHog is this flaky? https://github.com/{STOREFRONT}/actions/runs/30560492835"),
        ),
        expected=RoutingExpectation(stage="cascade", outcome="auto", repository=STOREFRONT),
    ),
    RoutingCase(
        scenario=_scenario(
            "ci_run_link_earlier_in_the_thread",
            "The cascade reads the repo from a link posted before the mention.",
            _ask(
                "@PostHog is this one flaky?",
                ("tester", f"https://github.com/{STOREFRONT}/actions/runs/30560492835 went red again"),
            ),
        ),
        expected=RoutingExpectation(stage="cascade", outcome="auto", repository=STOREFRONT),
    ),
    RoutingCase(
        scenario=_scenario(
            "billing_question",
            "A billing question needs no repository.",
            _ask("@PostHog how do I update the credit card on our subscription?"),
        ),
        expected=RoutingExpectation(stage="classifier", outcome="no_repo"),
    ),
    RoutingCase(
        scenario=_scenario(
            "dashboard_config",
            "The product-term heuristic stops a dashboard question with no code pattern.",
            _ask("@PostHog the dashboard tile filters are not persisting across refreshes"),
        ),
        expected=RoutingExpectation(stage="classifier", outcome="no_repo"),
    ),
    RoutingCase(
        scenario=DOCS_SITE_SLOW,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(DOCS_SITE,))
        ),
    ),
    RoutingCase(
        scenario=IOS_CRASH,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(IOS_SDK,))
        ),
    ),
    RoutingCase(
        scenario=_scenario(
            "posthog_product_hang",
            "A complaint about an analytics product page is a product question, not the team's code.",
            _thread(
                ("tester", "@PostHog the trends page hangs forever when I add 10+ series"),
                ("other", "tried Firefox and Chrome, just a spinner"),
            ),
        ),
        expected=RoutingExpectation(stage="classifier", outcome="no_repo"),
    ),
    RoutingCase(
        scenario=AUTOCAPTURE_CHECKOUT,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(STOREFRONT,))
        ),
    ),
    RoutingCase(
        scenario=MISSING_SIGNUP_EVENTS,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(STOREFRONT,))
        ),
        note="The thread says 'events' and 'funnel', which the product-term heuristic treats as an analytics ask.",
    ),
    RoutingCase(
        scenario=VAGUE_SIGNUP_RENDER,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(STOREFRONT,))
        ),
    ),
    RoutingCase(
        scenario=PROJECTS_VIEWSET,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(CORE_API,))
        ),
    ),
    RoutingCase(
        scenario=SIGNUP_TSX,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(STOREFRONT,))
        ),
    ),
    RoutingCase(
        scenario=PERMISSION_REFACTOR,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(CORE_API,))
        ),
    ),
    RoutingCase(
        scenario=SUPPORT_DESK,
        expected=RoutingExpectation(
            stage="selector", outcome="found", selector=SelectorExpectation(accepted=(HERMES,))
        ),
        note="The rule is the only signal linking 'support desk' to hermes, so a pass means the rule reached the agent.",
    ),
    RoutingCase(
        scenario=METRICS_DASHBOARD,
        expected=RoutingExpectation(stage="selector", outcome="found", selector=SelectorExpectation(accepted=(ATLAS,))),
        note="Without a rule, 'dashboard' stops at the heuristic; a pass means rules reached the needs-repo gate.",
    ),
    RoutingCase(
        scenario=_scenario(
            "routing_rule_loses_to_explicit_mention",
            "An explicit org/repo wins in the cascade; the rule never reaches the agent.",
            _ask(f"@PostHog can you look at {CORE_API} and fix the readme typo"),
            routing_rules=(CATCH_ALL_RULE,),
        ),
        expected=RoutingExpectation(stage="cascade", outcome="auto", repository=CORE_API),
    ),
)

SELECTOR_CASES: tuple[SelectorCase, ...] = (
    SelectorCase(scenario=DOCS_SITE_SLOW, expected=SelectorExpectation(accepted=(DOCS_SITE,)), category="domain"),
    SelectorCase(scenario=IOS_CRASH, expected=SelectorExpectation(accepted=(IOS_SDK,)), category="identifier"),
    SelectorCase(
        scenario=AUTOCAPTURE_CHECKOUT, expected=SelectorExpectation(accepted=(STOREFRONT,)), category="domain"
    ),
    SelectorCase(
        scenario=MISSING_SIGNUP_EVENTS, expected=SelectorExpectation(accepted=(STOREFRONT,)), category="identifier"
    ),
    SelectorCase(scenario=VAGUE_SIGNUP_RENDER, expected=SelectorExpectation(accepted=(STOREFRONT,)), category="vague"),
    SelectorCase(scenario=PROJECTS_VIEWSET, expected=SelectorExpectation(accepted=(CORE_API,)), category="identifier"),
    SelectorCase(scenario=SIGNUP_TSX, expected=SelectorExpectation(accepted=(STOREFRONT,)), category="identifier"),
    SelectorCase(scenario=PERMISSION_REFACTOR, expected=SelectorExpectation(accepted=(CORE_API,)), category="vague"),
    SelectorCase(scenario=SUPPORT_DESK, expected=SelectorExpectation(accepted=(HERMES,)), category="routing_rule"),
    SelectorCase(scenario=METRICS_DASHBOARD, expected=SelectorExpectation(accepted=(ATLAS,)), category="routing_rule"),
    SelectorCase(
        scenario=_scenario(
            "misleading_repo_name",
            "The repo named for payments holds undeployed prototypes; the checkout code is in the storefront.",
            _ask("@PostHog the pay button on the checkout page does nothing on Safari, can you fix it"),
        ),
        expected=SelectorExpectation(accepted=(STOREFRONT,)),
        category="misleading_name",
    ),
    SelectorCase(
        scenario=_scenario(
            "replay_regression_both_sdks",
            "Both mobile SDKs changed replay in 3.19, so either is a defensible subject.",
            _ask("@PostHog session replay drops frames on mobile after the 3.19 upgrade"),
        ),
        expected=SelectorExpectation(accepted=(IOS_SDK, ANDROID_SDK)),
        category="ambiguous",
    ),
    SelectorCase(
        scenario=_scenario(
            "no_plausible_match_desktop_installer",
            "A code request about a desktop installer that no candidate contains.",
            _ask("@PostHog the Windows desktop installer (.msi) fails with error 1603, can you fix the build script"),
        ),
        expected=SelectorExpectation(abstain=True),
        category="no_match",
    ),
    SelectorCase(
        scenario=_scenario(
            "no_plausible_match_billing",
            "A billing question that reaches the selector directly; no candidate owns it.",
            _ask("@PostHog how do I update the credit card on our subscription?"),
        ),
        expected=SelectorExpectation(abstain=True),
        category="no_match",
    ),
    SelectorCase(
        scenario=_scenario(
            "no_plausible_match_hr_tooling",
            "An internal operations request with a misleadingly technical word.",
            _ask("@PostHog please update the API key for our payroll provider in the HR portal"),
        ),
        expected=SelectorExpectation(abstain=True),
        category="no_match",
    ),
)


def fixture_fingerprint() -> str:
    """Hash of everything a model can see, so a result is tied to the exact catalog it ran on."""
    digest = hashlib.sha256(FIXTURE_VERSION.encode())
    for repo in REPOSITORIES:
        digest.update(repr(repo).encode())
    for case in (*ROUTING_CASES, *SELECTOR_CASES):
        digest.update(repr(case).encode())
    return digest.hexdigest()[:16]
