from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from posthog.models import User

from products.signals.backend.models import (
    SignalDomainPreference,
    SignalProductDomain,
    SignalRepositoryAreaActivity,
    SignalReviewerExclusion,
)
from products.signals.backend.report_generation.repo_activity import (
    ACTIVITY_STALE_AFTER,
    MAX_CONTRIBUTORS_PER_AREA,
    area_for_path,
)


def suggested_domain_preferences(*, team_id: int, user: User) -> list[dict]:
    login = (user.get_github_login() or "").lower()
    if not login:
        return []
    now = timezone.now()
    decided = SignalDomainPreference.objects.for_team(team_id).filter(user=user).values("domain_id")
    repeated = (
        SignalReviewerExclusion.objects.for_team(team_id)
        .filter(
            user=user, created_at__gte=now - timedelta(days=30), report__status="ready", report__routing__accepted=True
        )
        .exclude(report__routing__domain_id__in=decided)
        .values("report__routing__domain_id")
        .annotate(removals=Count("report_id", distinct=True))
        .filter(removals__gte=3)
    )
    counts = {row["report__routing__domain_id"]: row["removals"] for row in repeated}
    suggestions = []
    for domain in SignalProductDomain.objects.for_team(team_id).filter(id__in=counts, archived=False):
        if not domain.repository or not domain.code_paths:
            continue
        areas = {
            area_for_path(path.rstrip("/*") + "/__routing__" if path.endswith(("/", "*")) else path)
            for path in domain.code_paths
        }
        rows = list(
            SignalRepositoryAreaActivity.objects.for_team(team_id).filter(
                repository=domain.repository.lower(), area__in=areas, refreshed_at__gte=now - ACTIVITY_STALE_AFTER
            )
        )
        # Missing/stale or capped maps cannot establish absence. Never request a fetch on an inbox read.
        if len(rows) != len(areas) or any(
            not isinstance(row.contributors, list) or len(row.contributors) >= MAX_CONTRIBUTORS_PER_AREA for row in rows
        ):
            continue
        if any(
            not isinstance(entry, dict) or not isinstance(entry.get("login"), str) or entry["login"].lower() == login
            for row in rows
            for entry in row.contributors
        ):
            continue
        suggestions.append(
            {
                "domain": domain,
                "removals": counts[domain.id],
                "explanation": "You repeatedly removed yourself, and the current repository cache shows no recent attributed contributions here. Review whether this domain still belongs in your suggestions.",
            }
        )
    return suggestions
