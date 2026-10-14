from collections.abc import Collection
from datetime import datetime

from django.db import connection, transaction

from posthog.dataclasses import frozen
from posthog.event_usage import report_user_or_team_action
from posthog.models import Team, User
from posthog.models.scoping.manager import resolve_effective_team_id

from products.wizard.backend.facade.contracts import RecordWizardScanInput, WizardScanResult, WizardScanTool
from products.wizard.backend.models import WizardDetectedTool, WizardScan
from products.wizard.backend.observability.config import (
    WIZARD_POSTHOG_ALTERNATIVE_DETECTED_EVENT,
    WIZARD_POSTHOG_ALTERNATIVE_REMOVED_EVENT,
)
from products.wizard.backend.tool_catalog.catalog import classify_tool


@frozen
class _PostHogAlternativeSighting:
    kind: str
    alternative_to: tuple[str, ...]
    first_detection: bool
    # Seen again after a scan of the workspace no longer found it.
    returned: bool
    signal_sources: tuple[str, ...]


@frozen
class _PostHogAlternativeRemoval:
    kind: str
    alternative_to: tuple[str, ...]


@frozen
class _ScanChanges:
    sightings: tuple[_PostHogAlternativeSighting, ...]
    removals: tuple[_PostHogAlternativeRemoval, ...]


def _signals_json(tool: WizardScanTool) -> list[dict[str, str | None]]:
    return [{"source": signal.source, "name": signal.name, "file": signal.file} for signal in tool.signals]


def _classify(row: WizardDetectedTool) -> None:
    classification = classify_tool(row.kind)
    row.warehouse_source_type = classification.warehouse_source_type if classification else None
    row.alternative_to = list(classification.alternative_to) if classification else []


def record_scan(params: RecordWizardScanInput) -> WizardScanResult:
    # A scan can repeat the same kind when the wizard matches it in two manifests. The first wins.
    tools: dict[str, WizardScanTool] = {}
    for tool in params.tools:
        tools.setdefault(tool.kind, tool)

    # A child environment's scans are stored under its parent team. The lookup, the created row and the lock
    # must use the same id, or a replayed session misses its stored scan and fails on the unique constraint.
    team_id = resolve_effective_team_id(params.team_id)

    with transaction.atomic():
        _lock_workspace(team_id, params.workspace_fingerprint)
        scan, created = WizardScan.objects.for_team(team_id, canonical=True).get_or_create(
            team_id=team_id,
            session_id=params.session_id,
            defaults={
                "created_by_id": params.created_by_id,
                "workspace_fingerprint": params.workspace_fingerprint,
                "program": params.program,
                "wizard_version": params.wizard_version,
                "scanned_at": params.scanned_at,
                "detected_count": len(tools),
            },
        )
        if not created:
            return WizardScanResult(id=scan.id, created=False)

        # Tool state follows the newest scan of the workspace. A scan that arrives after a newer one is stored,
        # but it changes nothing, even when the newer scan found no tools at all. Both reads use the writer, because
        # a lagging read replica can miss the scan or tool rows that the previous holder of the lock committed.
        newer_scan_exists = (
            WizardScan.objects.for_team(team_id, canonical=True)
            .using("default")
            .filter(workspace_fingerprint=params.workspace_fingerprint, scanned_at__gt=scan.scanned_at)
            .exists()
        )
        if not newer_scan_exists:
            existing = {
                row.kind: row
                for row in WizardDetectedTool.objects.for_team(team_id, canonical=True)
                .using("default")
                .filter(workspace_fingerprint=params.workspace_fingerprint)
            }
            changes = _apply_scan(scan, tools, existing, complete=params.complete)
            # robust: the scan is already stored, so an analytics failure must not turn the request into a 500.
            # A lambda rather than functools.partial, because Django logs a robust callback's failure through
            # its __qualname__, which a partial does not have.
            transaction.on_commit(lambda: _report_posthog_alternative_changes(scan, changes), robust=True)

    return WizardScanResult(id=scan.id, created=True)


def _lock_workspace(team_id: int, workspace_fingerprint: str) -> None:
    # Scans of one workspace from different sessions write the same tool rows. Without the lock, two first scans
    # both insert a row and one fails on the unique constraint, and the newest-scan check can miss a scan that
    # commits in between. The lock ends with the transaction.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team_id, f"wizard-scan:{workspace_fingerprint}"]
        )


def _apply_scan(
    scan: WizardScan, tools: dict[str, WizardScanTool], existing: dict[str, WizardDetectedTool], *, complete: bool
) -> _ScanChanges:
    scanned_at: datetime = scan.scanned_at
    to_create: list[WizardDetectedTool] = []
    to_update: list[WizardDetectedTool] = []
    sightings: list[_PostHogAlternativeSighting] = []
    removals: list[_PostHogAlternativeRemoval] = []

    for kind, tool in tools.items():
        row = existing.get(kind)
        returned = row is not None and row.removed_at is not None
        if row is None:
            row = WizardDetectedTool(
                team_id=scan.team_id,
                workspace_fingerprint=scan.workspace_fingerprint,
                kind=kind,
                first_seen_scan=scan,
                first_seen_at=scanned_at,
            )
            to_create.append(row)
        else:
            to_update.append(row)
        row.signals = _signals_json(tool)
        row.last_seen_scan = scan
        row.last_seen_at = scanned_at
        row.removed_in_scan = None
        row.removed_at = None
        _classify(row)
        if row.alternative_to:
            sightings.append(
                _PostHogAlternativeSighting(
                    kind=kind,
                    alternative_to=tuple(row.alternative_to),
                    first_detection=kind not in existing,
                    returned=returned,
                    signal_sources=tuple(sorted({signal.source for signal in tool.signals})),
                )
            )

    for kind, row in existing.items():
        if complete and kind not in tools and row.removed_at is None:
            row.removed_in_scan = scan
            row.removed_at = scanned_at
            to_update.append(row)
            if row.alternative_to:
                removals.append(
                    _PostHogAlternativeRemoval(
                        kind=kind,
                        alternative_to=tuple(row.alternative_to),
                    )
                )

    # Scoped explicitly, because the ambient team context is not always the scanned team.
    tools_of_team = WizardDetectedTool.objects.for_team(scan.team_id)
    tools_of_team.bulk_create(to_create)
    tools_of_team.bulk_update(
        to_update,
        [
            "signals",
            "warehouse_source_type",
            "alternative_to",
            "last_seen_scan",
            "last_seen_at",
            "removed_in_scan",
            "removed_at",
        ],
    )
    return _ScanChanges(sightings=tuple(sightings), removals=tuple(removals))


def _report_posthog_alternative_changes(scan: WizardScan, changes: _ScanChanges) -> None:
    if not changes.sightings and not changes.removals:
        return
    team = Team.objects.select_related("organization").get(id=scan.team_id)
    user = User.objects.filter(id=scan.created_by_id).first() if scan.created_by_id else None
    scan_properties = {
        "program": scan.program,
        "wizard_version": scan.wizard_version,
        "wizard_session_id": scan.session_id,
        "workspace_fingerprint": scan.workspace_fingerprint,
    }

    def report(event: str, properties: dict[str, object]) -> None:
        report_user_or_team_action(
            event,
            {**scan_properties, **properties},
            user=user,
            team=team,
            # The user's current organization can differ from the scanned project's.
            organization=team.organization,
        )

    for sighting in changes.sightings:
        report(
            WIZARD_POSTHOG_ALTERNATIVE_DETECTED_EVENT,
            {
                "kind": sighting.kind,
                "alternative_to": list(sighting.alternative_to),
                "first_detection": sighting.first_detection,
                "returned": sighting.returned,
                "signal_sources": list(sighting.signal_sources),
            },
        )
    for removal in changes.removals:
        report(
            WIZARD_POSTHOG_ALTERNATIVE_REMOVED_EVENT,
            {
                "kind": removal.kind,
                "alternative_to": list(removal.alternative_to),
            },
        )


def organization_has_detected_tool(*, organization_id: str, kinds: Collection[str]) -> bool:
    # Reads across teams on purpose: the question is whether any project in the organization uses the tool.
    return (
        WizardDetectedTool.objects.unscoped()
        .filter(team__organization_id=organization_id, kind__in=kinds, removed_at__isnull=True)
        .exists()
    )
