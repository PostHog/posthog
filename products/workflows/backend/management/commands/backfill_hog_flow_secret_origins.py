from typing import Optional

from products.cdp.backend.management.commands.backfill_secret_origins import Command as HogFunctionCommand
from products.cdp.backend.services.secret_origins_backfill import BackfillReport
from products.workflows.backend.facade.secrets import backfill_hog_flow_secret_origins


class Command(HogFunctionCommand):
    help = "Bind stored secret inputs of workflow steps to the origins they may be sent to. Dry run by default."
    subject = "workflow steps"

    def backfill(self, *, commit: bool, team_id: Optional[int], batch_size: int) -> BackfillReport:
        return backfill_hog_flow_secret_origins(commit=commit, team_id=team_id, batch_size=batch_size)
