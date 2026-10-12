from datetime import datetime
from functools import partial

from django.db import connection, transaction

from posthog.dataclasses import frozen
from posthog.event_usage import report_user_or_team_action
from posthog.models import Team, User

from products.wizard.backend.facade.contracts import RecordWizardScanInput, WizardScanResult, WizardScanTool
from products.wizard.backend.models import WizardDetectedTool, WizardScan
from products.wizard.backend.tool_catalog.catalog import classify_tool


@frozen
class _CompetitorSighting:
    kind: str
    competes_with: tuple[str, ...]
    first_detection: bool
    signal_sources: tuple[str, ...]


@frozen
class _CompetitorRemoval:
    kind: str
    competes_with: tuple[str, ...]
    days_detected: int


@frozen
class _ScanChanges:
    sightings: tuple[_CompetitorSighting, ...]
    removals: tuple[_CompetitorRemoval, ...]


def _signals_json(tool: WizardScanTool) -> list[dict[str, str | None]]:
    return [{"source": signal.source, "name": signal.name, "file": signal.file} for signal in tool.signals]


def _classify(row: WizardDetectedTool) -> None:
    classification = classify_tool(row.kind)
    row.warehouse_source_type = classification.warehouse_source_type if classification else None
    row.competes_with = list(classification.competes_with) if classification else []


def record_scan(params: RecordWizardScanInput) -> WizardScanResult:
    # A scan can repeat the same kind when the wizard matches it in two manifests. The first wins.
    tools: dict[str, WizardScanTool] = {}
    for tool in params.tools:
        tools.setdefault(tool.kind, tool)

    with transaction.atomic():
        _lock_workspace(params.team_id, params.workspace_fingerprint)
        scan, created = WizardScan.objects.for_team(params.team_id).get_or_create(
            team_id=params.team_id,
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
        # but it changes nothing, even when the newer scan found no tools at all.
        newer_scan_exists = (
            WizardScan.objects.for_team(params.team_id)
            .filter(workspace_fingerprint=params.workspace_fingerprint, scanned_at__gt=scan.scanned_at)
            .exists()
        )
        if not newer_scan_exists:
            existing = {
                row.kind: row
                for row in WizardDetectedTool.objects.for_team(params.team_id).filter(
                    workspace_fingerprint=params.workspace_fingerprint
                )
            }
            changes = _apply_scan(scan, tools, existing)
            # robust: the scan is already stored, so an analytics failure must not turn the request into a 500.
            transaction.on_commit(partial(_report_competitor_changes, scan, changes), robust=True)

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
    scan: WizardScan, tools: dict[str, WizardScanTool], existing: dict[str, WizardDetectedTool]
) -> _ScanChanges:
    scanned_at: datetime = scan.scanned_at
    to_create: list[WizardDetectedTool] = []
    to_update: list[WizardDetectedTool] = []
    sightings: list[_CompetitorSighting] = []
    removals: list[_CompetitorRemoval] = []

    for kind, tool in tools.items():
        row = existing.get(kind)
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
        if row.competes_with:
            sightings.append(
                _CompetitorSighting(
                    kind=kind,
                    competes_with=tuple(row.competes_with),
                    first_detection=kind not in existing,
                    signal_sources=tuple(sorted({signal.source for signal in tool.signals})),
                )
            )

    for kind, row in existing.items():
        if kind not in tools and row.removed_at is None:
            row.removed_in_scan = scan
            row.removed_at = scanned_at
            to_update.append(row)
            if row.competes_with:
                removals.append(
                    _CompetitorRemoval(
                        kind=kind,
                        competes_with=tuple(row.competes_with),
                        days_detected=(scanned_at - row.first_seen_at).days,
                    )
                )

    WizardDetectedTool.objects.bulk_create(to_create)
    WizardDetectedTool.objects.bulk_update(
        to_update,
        [
            "signals",
            "warehouse_source_type",
            "competes_with",
            "last_seen_scan",
            "last_seen_at",
            "removed_in_scan",
            "removed_at",
        ],
    )
    return _ScanChanges(sightings=tuple(sightings), removals=tuple(removals))


def _report_competitor_changes(scan: WizardScan, changes: _ScanChanges) -> None:
    if not changes.sightings and not changes.removals:
        return
    team = Team.objects.get(id=scan.team_id)
    user = User.objects.filter(id=scan.created_by_id).first() if scan.created_by_id else None
    scan_properties = {
        "program": scan.program,
        "wizard_session_id": scan.session_id,
        "workspace_fingerprint": scan.workspace_fingerprint,
    }
    for sighting in changes.sightings:
        report_user_or_team_action(
            "competitor detected",
            {
                **scan_properties,
                "kind": sighting.kind,
                "competes_with": list(sighting.competes_with),
                "first_detection": sighting.first_detection,
                "signal_sources": list(sighting.signal_sources),
            },
            user=user,
            team=team,
        )
    for removal in changes.removals:
        report_user_or_team_action(
            "competitor removed",
            {
                **scan_properties,
                "kind": removal.kind,
                "competes_with": list(removal.competes_with),
                "days_detected": removal.days_detected,
            },
            user=user,
            team=team,
        )
