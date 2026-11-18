from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.dataclasses import frozen

from ..logic.sync import sync_access_rules


@frozen
class SyncOutcome:
    status: str
    rule_count: int | None


@activity.defn
async def sync_access_rules_activity() -> SyncOutcome:
    result = await sync_to_async(sync_access_rules)()
    return SyncOutcome(status=result.status, rule_count=result.rule_count)
