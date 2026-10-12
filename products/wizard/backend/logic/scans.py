from datetime import datetime

from django.db import transaction

from products.wizard.backend.facade.contracts import RecordWizardScanInput, WizardScanResult, WizardScanTool
from products.wizard.backend.models import WizardDetectedTool, WizardScan
from products.wizard.backend.tool_catalog.catalog import get_tool


def _signals_json(tool: WizardScanTool) -> list[dict[str, str | None]]:
    return [{"source": signal.source, "name": signal.name, "file": signal.file} for signal in tool.signals]


def _classify(row: WizardDetectedTool) -> None:
    catalog_tool = get_tool(row.kind)
    row.warehouse_source_type = (
        catalog_tool.warehouse_source_type.value if catalog_tool and catalog_tool.warehouse_source_type else None
    )
    row.competes_with = [product.value for product in catalog_tool.competes_with] if catalog_tool else []


def record_scan(params: RecordWizardScanInput) -> WizardScanResult:
    # A scan can repeat the same kind when the wizard matches it in two manifests. The first wins.
    tools: dict[str, WizardScanTool] = {}
    for tool in params.tools:
        tools.setdefault(tool.kind, tool)

    with transaction.atomic():
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

        existing = {
            row.kind: row
            for row in WizardDetectedTool.objects.for_team(params.team_id)
            .select_for_update()
            .filter(workspace_fingerprint=params.workspace_fingerprint)
        }
        _apply_scan(scan, tools, existing)

    return WizardScanResult(id=scan.id, created=True)


def _apply_scan(scan: WizardScan, tools: dict[str, WizardScanTool], existing: dict[str, WizardDetectedTool]) -> None:
    scanned_at: datetime = scan.scanned_at
    to_create: list[WizardDetectedTool] = []
    to_update: list[WizardDetectedTool] = []

    for kind, tool in tools.items():
        row = existing.get(kind)
        if row is None:
            row = WizardDetectedTool(
                team_id=scan.team_id,
                workspace_fingerprint=scan.workspace_fingerprint,
                kind=kind,
                signals=_signals_json(tool),
                first_seen_scan=scan,
                first_seen_at=scanned_at,
                last_seen_scan=scan,
                last_seen_at=scanned_at,
            )
            _classify(row)
            to_create.append(row)
        # A scan that reaches us after a newer sighting or removal for the same workspace must not move
        # state back, so it is compared with whichever of the two happened last.
        elif scanned_at > max(row.last_seen_at, row.removed_at or row.last_seen_at):
            row.signals = _signals_json(tool)
            row.last_seen_scan = scan
            row.last_seen_at = scanned_at
            row.removed_in_scan = None
            row.removed_at = None
            _classify(row)
            to_update.append(row)

    for kind, row in existing.items():
        if kind not in tools and row.removed_at is None and scanned_at > row.last_seen_at:
            row.removed_in_scan = scan
            row.removed_at = scanned_at
            to_update.append(row)

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
