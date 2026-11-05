from collections.abc import Collection
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.orphan_cleanup_command import PlatformOrphanCleanupCommand
from products.logs.backend.models import LogsAlertConfiguration


class Command(PlatformOrphanCleanupCommand):
    help = "Delete the alerts platform's shadow copies of logs alerts that no longer exist."
    source_kind = SourceKind.LOGS

    def existing_source_ids(self, ids: Collection[UUID]) -> Collection[UUID]:
        # nosemgrep: idor-lookup-without-team
        return set(LogsAlertConfiguration.objects.filter(id__in=ids).values_list("id", flat=True))
