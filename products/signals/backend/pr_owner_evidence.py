from __future__ import annotations

import re
import json
import hashlib
from collections import defaultdict

from django.db.models import Q
from django.utils import timezone

from owners_yaml.matcher import compile_pattern

from posthog.egress.limiter.policies import Priority
from posthog.models import Team
from posthog.models.integration import GitHubIntegration
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher
from posthog.ownership.paths import UNOWNED_TEAM, own_paths

from products.signals.backend.artefact_schemas import PROwnerEvidence, PROwnerIdentity, PROwnerInput
from products.signals.backend.assignment_service import AssignmentSnapshot
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalRepositoryAreaActivity,
    SignalScoutNote,
    SignalScratchpad,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.repo_activity import areas_for_paths
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_logins_by_user_uuid,
    resolve_org_github_login_to_users,
)
from products.signals.backend.scout_harness.profile.builders import _recent_reviewer_corrections

MAX_OWNER_CANDIDATES = 200
MAX_OWNER_EVIDENCE_BYTES = 100_000
_TEAM_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")


class OwnerEvidenceUnavailable(ValueError):
    pass


def report_owner_version(report: SignalReport) -> str:
    findings = list(
        SignalReportArtefact.objects.filter(team_id=report.team_id, report_id=report.id, type="signal_finding")
        .order_by("id")
        .values_list("id", "updated_at")
    )
    return hashlib.sha256(json.dumps([report.title, report.summary, findings], default=str).encode()).hexdigest()


class PROwnerEvidenceReader:
    def __init__(self, github: GitHubIntegration, *, team: Team, report: SignalReport) -> None:
        self.github = github
        self.team = team
        self.report = report

    def collect(self, inputs: PROwnerInput, snapshot: AssignmentSnapshot) -> PROwnerInput:
        files = self.github.list_pull_request_files(inputs.repository, inputs.pr_number)
        if not files.get("success") or len(files["paths"]) >= 100:
            raise OwnerEvidenceUnavailable("pr_files_unavailable_or_incomplete")
        paths = tuple(sorted(set(files["paths"])))
        reader = AuthenticatedRepoFiles(
            inputs.repository,
            GitHubFilesFetcher.from_integration(self.github, priority=Priority.BATCH),
            fresh_head=True,
        )
        evidence: list[PROwnerEvidence] = []
        team_paths: dict[str, list[str]] = defaultdict(list)
        candidate_teams: dict[str, set[str]] = defaultdict(set)
        candidates: set[str] = set()
        root = reader.read("owners.yaml")
        if root is not None:
            ownership = own_paths(reader, root, list(paths))
            for path, slug in ownership.team_by_path.items():
                if slug != UNOWNED_TEAM:
                    team_paths[slug].append(path)
            evidence.append(
                PROwnerEvidence(ref="owners.yaml", kind="ownership", content=json.dumps(dict(ownership.team_by_path)))
            )

        for location in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            content = reader.read(location)
            if content is None:
                continue
            if len(content.encode()) > 3 * 1024 * 1024:
                raise OwnerEvidenceUnavailable("codeowners_too_large")
            matches: dict[str, list[str]] = {}
            for line in content.splitlines():
                parts = line.split()
                if len(parts) < 2 or parts[0].startswith(("#", "!")) or "[" in parts[0]:
                    continue
                matcher = compile_pattern(parts[0])
                for path in paths:
                    if matcher.test(path):
                        matches[path] = parts[1:]
            for path, handles in matches.items():
                for handle in handles:
                    if not handle.startswith("@"):
                        continue
                    owner = handle[1:].lower()
                    if "/" in owner:
                        org, slug = owner.split("/", 1)
                        if org == inputs.repository.split("/", 1)[0].lower():
                            team_paths[slug].append(path)
                    else:
                        candidates.add(owner)
            evidence.append(PROwnerEvidence(ref=location, kind="ownership", content=json.dumps(matches)))
            break

        if len(team_paths) > 8:
            raise OwnerEvidenceUnavailable("too_many_owning_teams")
        for slug in sorted(team_paths):
            if not _TEAM_SLUG.fullmatch(slug):
                raise OwnerEvidenceUnavailable("invalid_owning_team")
            members = self.github.list_team_members(inputs.repository.split("/", 1)[0], slug)
            if not members.get("success"):
                raise OwnerEvidenceUnavailable("owning_team_lookup_failed")
            for login in members["logins"]:
                normalized = login.lower()
                candidates.add(normalized)
                candidate_teams[normalized].add(slug)

        for entry in snapshot.reviewers:
            if entry.github_login:
                candidates.add(entry.github_login.lower())
        candidates.update(
            get_org_member_github_logins_by_user_uuid(
                self.team.id, [entry.user_uuid for entry in snapshot.reviewers if entry.user_uuid]
            ).values()
        )
        evidence.append(
            PROwnerEvidence(
                ref=f"reviewers:{snapshot.state.reviewers_id}",
                kind="research",
                content=json.dumps([entry.model_dump(mode="json") for entry in snapshot.reviewers]),
            )
        )
        evidence.append(
            PROwnerEvidence(ref=f"report:{self.report.id}", kind="research", content=(self.report.summary or "")[:8000])
        )
        findings = SignalReportArtefact.objects.filter(
            team_id=self.team.id, report_id=self.report.id, type="signal_finding"
        ).order_by("-created_at", "-id")[:20]
        for finding in findings:
            evidence.append(
                PROwnerEvidence(ref=f"finding:{finding.id}", kind="research", content=finding.content[:8000])
            )

        history = (
            SignalRepositoryAreaActivity.objects.for_team(self.team.id)
            .filter(team_id=self.team.id, repository=inputs.repository.lower(), area__in=areas_for_paths(list(paths)))
            .exclude(refreshed_at=None)
            .order_by("area")
        )
        for activity in history:
            if activity.refreshed_at is None:
                continue
            evidence.append(
                PROwnerEvidence(
                    ref=f"history:{activity.area}:{activity.refreshed_at.isoformat()}",
                    kind="history",
                    content=json.dumps(activity.contributors)[:8000],
                )
            )
            for contributor in activity.contributors:
                if isinstance(contributor, dict) and isinstance(contributor.get("login"), str):
                    candidates.add(contributor["login"].lower())

        for correction in _recent_reviewer_corrections(self.team)["corrections"]:
            candidate_labels = [*correction["before"], *correction["after"]]
            candidates.update(
                label.lower() for label in candidate_labels if isinstance(label, str) and not label.startswith("user:")
            )
            candidates.update(
                get_org_member_github_logins_by_user_uuid(
                    self.team.id,
                    [
                        label.removeprefix("user:")
                        for label in candidate_labels
                        if isinstance(label, str) and label.startswith("user:")
                    ],
                ).values()
            )
            evidence.append(
                PROwnerEvidence(
                    ref=f"correction:{correction['report_id']}:{correction['at']}",
                    kind="correction",
                    content=json.dumps(correction)[:8000],
                )
            )
        notes = (
            SignalScoutNote.objects.for_team(self.team.id)
            .filter(origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .order_by("-created_at")[:10]
        )
        for note in notes:
            evidence.append(PROwnerEvidence(ref=f"note:{note.id}", kind="correction", content=note.content[:8000]))

        memory_scope = Q()
        for area in areas_for_paths(list(paths)):
            if area:
                memory_scope |= Q(key__icontains=area)
        if memory_scope:
            memories = (
                SignalScratchpad.objects.for_team(self.team.id)
                .filter(key__startswith="reviewer:")
                .filter(memory_scope)
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
                .order_by("-updated_at")[:10]
            )
            for memory in memories:
                evidence.append(
                    PROwnerEvidence(
                        ref=f"memory:{memory.id}:{memory.updated_at.isoformat()}",
                        kind="research",
                        content=memory.content[:8000],
                    )
                )

        candidates = {login for login in candidates if re.fullmatch(r"[a-z0-9](?:-?[a-z0-9]){0,38}", login)}
        if len(candidates) > MAX_OWNER_CANDIDATES:
            raise OwnerEvidenceUnavailable("candidate_budget_exceeded")
        members_by_login = resolve_org_github_login_to_users(self.team.id, candidates)
        eligible = set(self.team.all_users_with_access().filter(is_active=True).values_list("id", flat=True))
        opted_in = set(
            SignalUserAutonomyConfig.objects.filter(
                user_id__in=[user.id for user in members_by_login.values()], github_assign_on_pull_request=True
            ).values_list("user_id", flat=True)
        )
        identities = []
        for login in sorted(candidates):
            member = members_by_login.get(login)
            if member is not None and (
                member.id not in eligible
                or (member.get_github_login(include_team_fallback=False) or "").lower() != login
            ):
                continue
            if member is None and not candidate_teams[login]:
                continue
            identities.append(
                PROwnerIdentity(
                    login=login,
                    user_uuid=member.uuid if member else None,
                    teams=tuple(sorted(candidate_teams[login])),
                    opted_in=member is not None and member.id in opted_in,
                )
            )
        collected = inputs.model_copy(
            update={"paths": paths, "identities": tuple(identities), "evidence": tuple(evidence)}
        )
        if len(collected.model_dump_json().encode()) > MAX_OWNER_EVIDENCE_BYTES:
            raise OwnerEvidenceUnavailable("evidence_budget_exceeded")
        return collected
