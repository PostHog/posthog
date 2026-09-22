from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry

from products.event_definitions.backend.logic.placeholder import (
    PlaceholderEventDefinition,
    create_placeholder_event_definitions,
)
from products.signals.evals.agentic.datasets import EvalCase, RepoSelectionCase, ResearchCase, ResearchSeed, ScoutCase
from products.signals.evals.agentic.repos import REGISTRY
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def _write_events(team_id: int, rows: list[dict]) -> None:
    from posthog.models import Person
    from posthog.models.event.util import bulk_create_events

    create_placeholder_event_definitions(
        team_id=team_id,
        definitions=[PlaceholderEventDefinition(name=name) for name in sorted({row["event"] for row in rows})],
    )
    people = {
        row["distinct_id"]: Person(
            uuid=uuid.uuid5(uuid.NAMESPACE_URL, f"{team_id}:{row['distinct_id']}"),
            team_id=team_id,
            properties={},
            created_at=row["timestamp"],
        )
        for row in rows
    }
    events = [
        {
            **row,
            "team_id": team_id,
            "properties": row.get("properties", {}),
            "person_mode": "full",
        }
        for row in rows
    ]
    bulk_create_events(events, person_mapping=people)


def _seed_research_events(context: CustomPromptSandboxContext, scenario: ResearchSeed) -> dict[str, object]:
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    rows: list[dict] = []

    if scenario == "checkout_browser_regression":
        for days_ago in range(7, 1, -1):
            timestamp = now - timedelta(days=days_ago)
            for index in range(80):
                browser = "Safari" if index < 40 else "Chrome"
                distinct_id = f"signals-eval-checkout-{days_ago}-{index}"
                properties = {"$browser": browser, "$browser_version": "17.4" if browser == "Safari" else "126"}
                rows.append(
                    {
                        "event": "checkout_started",
                        "distinct_id": distinct_id,
                        "timestamp": timestamp,
                        "properties": properties,
                    }
                )
                if index < 28 or 40 <= index < 68:
                    rows.append(
                        {
                            "event": "checkout_completed",
                            "distinct_id": distinct_id,
                            "timestamp": timestamp + timedelta(minutes=5),
                            "properties": properties,
                        }
                    )

        timestamp = now - timedelta(days=1)
        for index in range(80):
            browser = "Safari" if index < 60 else "Chrome"
            distinct_id = f"signals-eval-checkout-latest-{index}"
            properties = {"$browser": browser, "$browser_version": "17.4" if browser == "Safari" else "126"}
            rows.append(
                {
                    "event": "checkout_started",
                    "distinct_id": distinct_id,
                    "timestamp": timestamp,
                    "properties": properties,
                }
            )
            completed = index < 8 or 60 <= index < 74
            if completed:
                rows.append(
                    {
                        "event": "checkout_completed",
                        "distinct_id": distinct_id,
                        "timestamp": timestamp + timedelta(minutes=5),
                        "properties": properties,
                    }
                )
            elif index < 60:
                rows.append(
                    {
                        "event": "$exception",
                        "distinct_id": distinct_id,
                        "timestamp": timestamp + timedelta(minutes=3),
                        "properties": {
                            **properties,
                            "$exception_types": ["CheckoutTokenError"],
                            "$exception_values": ["Payment token missing during checkout"],
                            "$exception_sources": ["payments/api/checkout.py"],
                            "$exception_functions": ["create_checkout"],
                        },
                    }
                )
        _write_events(context.team_id, rows)
        return {"scenario": scenario, "baseline_conversion": 0.7, "latest_conversion": 0.275}

    if scenario == "signup_volume_drop":
        for days_ago in range(14, 0, -1):
            latest = days_ago <= 2
            starts = 30 if latest else 100
            completions = 18 if latest else 60
            timestamp = now - timedelta(days=days_ago)
            for index in range(starts):
                distinct_id = f"signals-eval-signup-{days_ago}-{index}"
                rows.append({"event": "signup_started", "distinct_id": distinct_id, "timestamp": timestamp})
                if index < completions:
                    rows.append(
                        {
                            "event": "signed_up",
                            "distinct_id": distinct_id,
                            "timestamp": timestamp + timedelta(minutes=4),
                        }
                    )
        _write_events(context.team_id, rows)
        return {"scenario": scenario, "baseline_conversion": 0.6, "latest_conversion": 0.6}

    for days_ago in range(7, 1, -1):
        timestamp = now - timedelta(days=days_ago)
        for index in range(80):
            rows.append(
                {
                    "event": "uploaded_file",
                    "distinct_id": f"signals-eval-upload-{days_ago}-{index}",
                    "timestamp": timestamp,
                    "properties": {"$browser": "Chrome", "$browser_version": "126", "file_size_b": 25_000_000},
                }
            )

    timestamp = now - timedelta(days=1)
    for index in range(70):
        safari = index < 16
        rows.append(
            {
                "event": "uploaded_file",
                "distinct_id": f"signals-eval-upload-latest-{index}",
                "timestamp": timestamp + timedelta(minutes=10),
                "properties": {
                    "$browser": "Safari" if safari else "Chrome",
                    "$browser_version": "17.4" if safari else "126",
                    "file_size_b": 25_000_000,
                },
            }
        )
    for user_index in range(18):
        for retry in range(5):
            rows.append(
                {
                    "event": "$exception",
                    "distinct_id": f"signals-eval-upload-latest-{user_index}",
                    "timestamp": timestamp + timedelta(minutes=retry),
                    "properties": {
                        "$browser": "Safari",
                        "$browser_version": "17.4",
                        "$exception_types": ["UploadChunkError"],
                        "$exception_values": ["Chunk upload failed before finalize"],
                        "$exception_sources": ["src/lib/uploads.ts"],
                        "$exception_functions": ["finalizeUpload"],
                    },
                }
            )
    _write_events(context.team_id, rows)
    return {"scenario": scenario, "retry_errors": 90, "affected_users": 18, "eventual_successes": 16}


def seed_research_project(context: CustomPromptSandboxContext, case: EvalCase | None = None) -> dict[str, object]:
    from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

    from products.signals.evals.agentic.cases.research import SESSION_IDS

    now = datetime.now(UTC)
    for index, session_id in enumerate(SESSION_IDS):
        first_timestamp = now - timedelta(days=index + 1, minutes=10)
        produce_replay_summary(
            team_id=context.team_id,
            session_id=session_id,
            distinct_id=f"signals-eval-session-{index + 1}",
            first_timestamp=first_timestamp,
            last_timestamp=first_timestamp + timedelta(minutes=10),
            first_url="https://app.hedgebox.test/app/files",
            all_urls=["https://app.hedgebox.test/app/files"],
            click_count=4,
            keypress_count=2,
            mouse_activity_count=8,
            active_milliseconds=180_000,
            snapshot_source="web",
            snapshot_library="web",
        )
    result: dict[str, object] = {"session_ids": list(SESSION_IDS)}
    if isinstance(case, ResearchCase) and case.seed:
        result.update(_seed_research_events(context, case.seed))
    return result


def seed_repository_catalog(context: CustomPromptSandboxContext, case: EvalCase | None = None) -> dict[str, object]:
    selected = set(case.candidate_repos) if isinstance(case, RepoSelectionCase) else set()
    repo_definitions = [repo for repo in REGISTRY.values() if not selected or repo.full_name in selected]
    repositories = [
        {"id": index, "name": repo.repo, "full_name": repo.full_name}
        for index, repo in enumerate(repo_definitions, start=1)
    ]
    integration = Integration.objects.create(
        team_id=context.team_id,
        kind="github",
        integration_id=f"eval-{context.team_id}",
        config={"installation_id": f"eval-{context.team_id}"},
        sensitive_config={"access_token": "signals-eval-public-repositories"},
        repository_cache=repositories,
        repository_cache_updated_at=timezone.now(),
    )
    IntegrationRepositoryCacheEntry.objects.bulk_create(
        [
            IntegrationRepositoryCacheEntry(
                integration=integration,
                team_id=context.team_id,
                full_name=repo.full_name,
                description=repo.domain,
                topics=[],
                archived=False,
                fork=False,
                primary_language=repo.primary_language,
                default_branch=repo.default_branch,
                default_branch_sha=repo.default_branch_sha or "0" * 40,
                readme=repo.domain,
                tree_paths="\n".join(("README.md", *repo.tree_paths)),
            )
            for repo in repo_definitions
        ]
    )
    return {"integration_id": integration.id, "repository_count": len(repositories)}


def _seed_error_tracking(context: CustomPromptSandboxContext, *, scenario: str) -> dict[str, object]:
    from django.apps import apps

    from posthog.clickhouse.client import sync_execute
    from posthog.models import Team
    from posthog.models.event.util import format_clickhouse_timestamp
    from posthog.models.utils import uuid7

    from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE
    from products.signals.backend.models import SignalScratchpad

    ErrorTrackingIssue = apps.get_model("error_tracking", "ErrorTrackingIssue")
    ErrorTrackingIssueFingerprintV2 = apps.get_model("error_tracking", "ErrorTrackingIssueFingerprintV2")
    team = Team.objects.get(id=context.team_id)
    ErrorTrackingIssue.objects.filter(team=team).delete()

    now = datetime.now(UTC)
    if scenario in {"error_burst", "error_low_volume"}:
        name = "Checkout token missing"
        description = "Checkout requests fail when their payment token is absent."
        fingerprint_value = "signals-eval-checkout-token-missing"
        exception_type = "CheckoutTokenError"
        exception_value = "Payment token missing during checkout"
        source = "payments/api/checkout.py"
        function = "create_checkout"
        path = "/checkout"
        count = 180 if scenario == "error_burst" else 3
        distinct_users = count
        age = timedelta(hours=2)
    elif scenario == "error_stuck_loop":
        name = "Upload finalize retry loop"
        description = "Upload finalization retries without making progress."
        fingerprint_value = "signals-eval-upload-finalize-loop"
        exception_type = "UploadFinalizeError"
        exception_value = "Upload could not be finalized"
        source = "uploads/finalize.py"
        function = "finalizeUpload"
        path = "/files"
        count = 2_000
        distinct_users = 2
        age = timedelta(hours=2)
    elif scenario == "error_upstream_noise":
        name = "OpenAI rate limit"
        description = "The upstream model provider is rate limiting background summaries."
        fingerprint_value = "signals-eval-openai-rate-limit"
        exception_type = "RateLimitError"
        exception_value = "OpenAI request exceeded the configured rate limit"
        source = "integrations/openai.py"
        function = "summarizeFile"
        path = "/files"
        count = 240
        distinct_users = 24
        age = timedelta(days=7)
    else:
        raise ValueError(f"unknown error-tracking seed {scenario!r}")

    issue = ErrorTrackingIssue.objects.create(id=uuid7(), team=team, name=name)
    fingerprint = ErrorTrackingIssueFingerprintV2.objects.create(
        team=team,
        issue=issue,
        fingerprint=fingerprint_value,
    )
    sync_execute(
        INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
        {
            "fingerprint": fingerprint.fingerprint,
            "issue_id": str(issue.id),
            "team_id": team.id,
            "issue_name": issue.name,
            "issue_description": description,
            "issue_status": issue.status,
            "issue_severity": issue.severity,
            "assigned_user_id": None,
            "assigned_role_id": None,
            "first_seen": format_clickhouse_timestamp(now - age),
            "is_deleted": 0,
            "version": int(fingerprint.created_at.timestamp() * 1000),
        },
    )

    rows = []
    for index in range(count):
        distinct_id = f"signals-eval-{scenario}-{index % distinct_users}"
        timestamp = now - timedelta(seconds=(index * age.total_seconds() / count))
        rows.append(
            {
                "event": "$exception",
                "distinct_id": distinct_id,
                "timestamp": timestamp,
                "properties": {
                    "$current_url": f"https://app.hedgebox.test{path}",
                    "$pathname": path,
                    "$exception_issue_id": str(issue.id),
                    "$exception_fingerprint": fingerprint.fingerprint,
                    "$exception_types": [exception_type],
                    "$exception_values": [exception_value],
                    "$exception_sources": [source],
                    "$exception_functions": [function],
                    "$exception_list": [
                        {
                            "type": exception_type,
                            "value": exception_value,
                            "stacktrace": {
                                "type": "resolved",
                                "frames": [
                                    {
                                        "in_app": True,
                                        "resolved": True,
                                        "resolved_name": function,
                                        "source": source,
                                        "lang": "python",
                                        "line": 84,
                                    }
                                ],
                            },
                        }
                    ],
                },
            }
        )
    _write_events(team.id, rows)
    if scenario == "error_upstream_noise":
        SignalScratchpad.all_teams.create(
            team=team,
            key="noise:error_tracking:openai-rate-limit",
            content=(
                "OpenAI RateLimitError from summarizeFile is known upstream provider noise at a steady baseline. "
                "Do not report unless its count-to-user shape changes materially."
            ),
        )
    return {
        "issue_id": str(issue.id),
        "issue_name": issue.name,
        "occurrences": count,
        "distinct_users": distinct_users,
    }


def _seed_product_funnel(context: CustomPromptSandboxContext, *, denominator_holds: bool) -> dict[str, object]:
    from posthog.models import EventDefinition, Person, Team
    from posthog.models.event.util import bulk_create_events

    from products.product_analytics.backend.facade.models import Insight
    from products.signals.backend.models import SignalScratchpad

    team = Team.objects.get(id=context.team_id)
    start_event = "signals_eval_activation_started"
    conversion_event = "signals_eval_workspace_created"
    now = datetime.now(UTC)
    for name in (start_event, conversion_event):
        EventDefinition.objects.get_or_create(
            team=team,
            project=team.project,
            name=name,
            defaults={"last_seen_at": now},
        )
    insight = Insight.objects.create(
        team=team,
        created_by_id=context.user_id,
        name="Signals eval activation funnel",
        description="Activation from starting setup to creating a workspace.",
        saved=True,
        query={
            "kind": "FunnelsQuery",
            "series": [
                {"event": start_event, "kind": "EventsNode"},
                {"event": conversion_event, "kind": "EventsNode"},
            ],
        },
    )

    anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)
    people: dict[str, Person] = {}
    events = []
    window_stats = []
    for weeks_ago in range(6, -1, -1):
        latest = weeks_ago == 0
        entrants = 80 if denominator_holds or not latest else 16
        converted = (52 if not latest else 24) if denominator_holds else (52 if not latest else 5)
        window_start = anchor - timedelta(days=7 * (weeks_ago + 1))
        for index in range(entrants):
            distinct_id = f"signals-eval-funnel-{weeks_ago}-{index}"
            person_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{team.id}:{distinct_id}")
            people[distinct_id] = Person(uuid=person_id, team_id=team.id, properties={}, created_at=window_start)
            timestamp = window_start + timedelta(hours=(index * 2) % 156, minutes=index % 55)
            properties = {
                "$browser": ("Chrome", "Safari", "Firefox")[index % 3],
                "$geoip_country_code": ("US", "GB", "DE", "PL")[index % 4],
            }
            events.append(
                {
                    "event": start_event,
                    "distinct_id": distinct_id,
                    "team_id": team.id,
                    "timestamp": timestamp,
                    "properties": properties,
                    "person_mode": "full",
                }
            )
            if index < converted:
                events.append(
                    {
                        "event": conversion_event,
                        "distinct_id": distinct_id,
                        "team_id": team.id,
                        "timestamp": timestamp + timedelta(minutes=5),
                        "properties": properties,
                        "person_mode": "full",
                    }
                )
        window_stats.append({"weeks_ago": weeks_ago, "entrants": entrants, "converted": converted})
    bulk_create_events(events, person_mapping=people)
    SignalScratchpad.all_teams.create(
        team=team,
        key=f"watchlist:product_analytics:flow:{insight.short_id}",
        content=(
            f"Saved funnel {insight.short_id}: {start_event} -> {conversion_event}. Score the latest complete "
            "7-day window against the prior six complete 7-day windows; this flow is due now."
        ),
    )
    return {
        "insight_id": insight.id,
        "insight_short_id": insight.short_id,
        "events": [start_event, conversion_event],
        "windows": window_stats,
    }


def _seed_web_vitals(context: CustomPromptSandboxContext, *, high_volume: bool) -> dict[str, object]:
    from posthog.models import Team

    team = Team.objects.get(id=context.team_id)
    now = datetime.now(UTC)
    sample_count = 1_200 if high_volume else 30
    rows = [
        {
            "event": "$web_vitals",
            "distinct_id": f"signals-eval-vitals-{index % 400}",
            "timestamp": now - timedelta(minutes=(index * 7) % (7 * 24 * 60)),
            "properties": {
                "$host": "app.hedgebox.test",
                "$pathname": "/files",
                "$current_url": "https://app.hedgebox.test/files",
                "$device_type": "Desktop" if index % 4 else "Mobile",
                "$browser": ("Chrome", "Safari", "Firefox")[index % 3],
                "$web_vitals_LCP_value": 5_100 + (index % 300),
                "$web_vitals_FCP_value": 1_100 + (index % 100),
                "$web_vitals_INP_value": 140 + (index % 30),
                "$web_vitals_CLS_value": 0.05,
            },
        }
        for index in range(sample_count)
    ]
    _write_events(team.id, rows)
    return {
        "path": "/files",
        "samples": sample_count,
        "lcp_band": "poor",
        "high_volume": high_volume,
    }


def seed_scout_project(context: CustomPromptSandboxContext, case: EvalCase | None = None) -> dict[str, object]:
    if not isinstance(case, ScoutCase) or case.seed is None:
        raise ValueError("scout cases require a project-data seed")
    if case.seed.startswith("error_"):
        return _seed_error_tracking(context, scenario=case.seed)
    if case.seed.startswith("web_vitals_"):
        return _seed_web_vitals(context, high_volume=case.seed == "web_vitals_poor_lcp")
    return _seed_product_funnel(context, denominator_holds=case.seed == "funnel_regression")
