from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry

from products.signals.evals.agentic.datasets import EvalCase, RepoSelectionCase, ScoutCase
from products.signals.evals.agentic.repos import REGISTRY
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def seed_research_sessions(context: CustomPromptSandboxContext, case: EvalCase | None = None) -> dict[str, object]:
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
    return {"session_ids": list(SESSION_IDS)}


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


def _seed_error_tracking(context: CustomPromptSandboxContext, *, broad_reach: bool) -> dict[str, object]:
    from django.apps import apps

    from posthog.clickhouse.client import sync_execute
    from posthog.models import Person, Team
    from posthog.models.event.util import bulk_create_events, format_clickhouse_timestamp
    from posthog.models.utils import uuid7

    from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE

    ErrorTrackingIssue = apps.get_model("error_tracking", "ErrorTrackingIssue")
    ErrorTrackingIssueFingerprintV2 = apps.get_model("error_tracking", "ErrorTrackingIssueFingerprintV2")
    team = Team.objects.get(id=context.team_id)
    ErrorTrackingIssue.objects.filter(team=team).delete()

    now = datetime.now(UTC)
    issue = ErrorTrackingIssue.objects.create(id=uuid7(), team=team, name="Checkout token missing")
    fingerprint = ErrorTrackingIssueFingerprintV2.objects.create(
        team=team,
        issue=issue,
        fingerprint="signals-eval-checkout-token-missing",
    )
    sync_execute(
        INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
        {
            "fingerprint": fingerprint.fingerprint,
            "issue_id": str(issue.id),
            "team_id": team.id,
            "issue_name": issue.name,
            "issue_description": "Checkout requests fail when their payment token is absent.",
            "issue_status": issue.status,
            "issue_severity": issue.severity,
            "assigned_user_id": None,
            "assigned_role_id": None,
            "first_seen": format_clickhouse_timestamp(now - timedelta(hours=2)),
            "is_deleted": 0,
            "version": int(fingerprint.created_at.timestamp() * 1000),
        },
    )

    count = 180 if broad_reach else 3
    people: dict[str, Person] = {}
    events = []
    for index in range(count):
        distinct_id = f"signals-eval-checkout-{index}"
        person_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{team.id}:{distinct_id}")
        people[distinct_id] = Person(uuid=person_id, team_id=team.id, properties={}, created_at=now)
        timestamp = now - timedelta(minutes=90 - (index % 80))
        events.append(
            {
                "event": "$exception",
                "distinct_id": distinct_id,
                "team_id": team.id,
                "timestamp": timestamp,
                "properties": {
                    "$current_url": "https://app.hedgebox.test/checkout",
                    "$pathname": "/checkout",
                    "$exception_issue_id": str(issue.id),
                    "$exception_fingerprint": fingerprint.fingerprint,
                    "$exception_types": ["CheckoutTokenError"],
                    "$exception_values": ["Payment token missing during checkout"],
                    "$exception_sources": ["payments/api/checkout.py"],
                    "$exception_functions": ["create_checkout"],
                    "$exception_list": [
                        {
                            "type": "CheckoutTokenError",
                            "value": "Payment token missing during checkout",
                            "stacktrace": {
                                "type": "resolved",
                                "frames": [
                                    {
                                        "in_app": True,
                                        "resolved": True,
                                        "resolved_name": "create_checkout",
                                        "source": "payments/api/checkout.py",
                                        "lang": "python",
                                        "line": 84,
                                    }
                                ],
                            },
                        }
                    ],
                },
                "person_mode": "full",
            }
        )
    bulk_create_events(events, person_mapping=people)
    return {
        "issue_id": str(issue.id),
        "issue_name": issue.name,
        "occurrences": count,
        "distinct_users": count,
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


def seed_scout_project(context: CustomPromptSandboxContext, case: EvalCase | None = None) -> dict[str, object]:
    if not isinstance(case, ScoutCase) or case.seed is None:
        raise ValueError("scout cases require a project-data seed")
    if case.seed == "error_burst":
        return _seed_error_tracking(context, broad_reach=True)
    if case.seed == "error_low_volume":
        return _seed_error_tracking(context, broad_reach=False)
    return _seed_product_funnel(context, denominator_holds=case.seed == "funnel_regression")
