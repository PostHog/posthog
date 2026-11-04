"""The append-only log of reviewer routing runs: what each run did with every owner, and why.

`PullRequest.routing` is the state machine and keeps only the latest result. A run that made its
GitHub writes is recorded here once, from its saved record, so a reader can later ask why an owner
was or was not asked to review.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import router, transaction

import structlog

from products.stamphog.backend.facade.enums import RoutingOwnerOutcome
from products.stamphog.backend.logic.routing.comment import clean_reason
from products.stamphog.backend.logic.scrubbing import scrub_credentials
from products.stamphog.backend.models import PullRequest, RoutingRun, RoutingRunOwner

logger = structlog.get_logger(__name__)


def _owner_row(entry: Mapping[str, Any], *, run: RoutingRun, refused: set[str]) -> RoutingRunOwner:
    outcome = entry["outcome"]
    # The plan decided every outcome. Only GitHub's answer to the requests comes after it.
    if outcome == RoutingOwnerOutcome.REQUESTED and entry["owner"] in refused:
        outcome = RoutingOwnerOutcome.REFUSED
    return RoutingRunOwner(
        team_id=run.team_id,
        run=run,
        owner=entry["owner"],
        kind=entry["kind"],
        outcome=outcome,
        reason=entry["reason"],
        # The model read untrusted pull request content, so its reason is cleaned like the comment's.
        model_reason=clean_reason(scrub_credentials(entry["model_reason"])),
        pins=entry["pins"],
        lines=entry["lines"],
        file_count=entry["file_count"],
    )


def record_routing_run(pr_obj: PullRequest, record: Mapping[str, Any]) -> None:
    """Write one run and its owner rows from a saved record whose requests went out."""
    if "run_id" not in record:
        # A release before the run log planned this run, so its record has no owner outcomes to write.
        logger.warning("stamphog_reviewer_routing_run_log_skipped", pr_number=pr_obj.pr_number)
        return
    run = RoutingRun(
        team_id=pr_obj.team_id,
        id=record["run_id"],
        pull_request=pr_obj,
        head_sha=record["head_sha"],
        mode=record["mode"],
        trigger=record["trigger"],
        scope=record["scope"],
        fork=record["fork"],
        llm_skipped=record["llm_skipped"] or "",
        model=record["model"] or "",
        files_truncated=record["files_truncated"],
        additions_resolved=record["additions_resolved"],
    )
    refused = set(record["refused"])
    owners = [_owner_row(entry, run=run, refused=refused) for entry in record["candidates"]]
    write_db = router.db_for_write(RoutingRun)
    # The stored row already holds the canonical team id. bulk_create skips the team lookup a save makes.
    with transaction.atomic(using=write_db):
        RoutingRun.objects.for_team(pr_obj.team_id, canonical=True).using(write_db).bulk_create([run])
        RoutingRunOwner.objects.for_team(pr_obj.team_id, canonical=True).using(write_db).bulk_create(owners)
