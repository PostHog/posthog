from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import asyncify

from products.docs_freshness.backend.facade.contracts import LandedCommit, PullRequestHead
from products.docs_freshness.backend.logic import impact_check
from products.docs_freshness.backend.logic.impact_check import ImpactVerdict
from products.docs_freshness.backend.temporal.client import start_check_pull_request_head
from products.docs_freshness.backend.temporal.contracts import RecordVerdictInput


@activity.defn(name="docs_freshness_check_head")
@asyncify
def check_head(head: PullRequestHead) -> ImpactVerdict | None:
    return impact_check.check_pull_request_head(head)


@activity.defn(name="docs_freshness_record_verdict")
@asyncify
def record_verdict(input: RecordVerdictInput) -> None:
    impact_check.record_verdict(input.head, input.verdict_name, input.verdict)


@activity.defn(name="docs_freshness_start_landed_check")
async def start_landed_check(commit: LandedCommit) -> None:
    head = await database_sync_to_async(impact_check.landed_pull_request_head)(commit)
    if head is None:
        return
    await start_check_pull_request_head(activity.client(), head)
