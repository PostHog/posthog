from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.creator_backfill_command import PlatformCreatorBackfillCommand
from products.logs.backend.models import LogsAlertConfiguration


class Command(PlatformCreatorBackfillCommand):
    help = "Copy each logs alert's creator onto its alerts platform copy, where the copy has none."
    source_kind = SourceKind.LOGS
    source_model = LogsAlertConfiguration
