from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.created_at_backfill_command import PlatformCreatedAtBackfillCommand
from products.logs.backend.models import LogsAlertConfiguration


class Command(PlatformCreatedAtBackfillCommand):
    help = (
        "Copy each logs alert's created_at onto its alerts platform copy, where the two differ. "
        "Writes nothing without --apply."
    )
    source_kind = SourceKind.LOGS
    source_model = LogsAlertConfiguration
