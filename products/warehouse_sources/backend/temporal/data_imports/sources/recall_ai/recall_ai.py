from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.settings import (
    RECALL_AI_ENDPOINTS,
    USAGE_BACKFILL_DAYS,
    USAGE_ENDPOINT,
    USAGE_REQUEST_INTERVAL_SECONDS,
    USAGE_RESTATEMENT_DAYS,
)

# API keys are region-scoped and each region is its own host. The allowlist pins outbound
# traffic to *.recall.ai even if a stored config carries an unexpected region value.
REGIONS = ("us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1")


@frozen
class RecallAIResumeConfig:
    next_url: Optional[str] = None
    # The next UTC day the usage walk requests, as an ISO date.
    next_date: Optional[str] = None


def base_url_for_region(region: str) -> str:
    if region not in REGIONS:
        raise ValueError(f"Unknown Recall.ai region: {region}")
    return f"https://{region}.recall.ai"


def _to_iso8601(value: Any) -> Optional[str]:
    """Format the incremental watermark for Recall.ai's ISO 8601 datetime filters.
    Truncating to whole seconds only widens the window, so a boundary row is re-fetched
    and deduped on merge rather than skipped."""
    if value is None:
        return None
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _scrub_fields(fields: tuple[str, ...]):
    def scrub(item: dict[str, Any]) -> dict[str, Any]:
        for field in fields:
            *parents, leaf = field.split(".")
            target: Any = item
            for parent in parents:
                target = target.get(parent) if isinstance(target, dict) else None
            if isinstance(target, dict):
                target.pop(leaf, None)
        return item

    return scrub


def get_resource(
    endpoint: str, should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]
) -> EndpointResource:
    config = RECALL_AI_ENDPOINTS[endpoint]

    params: dict[str, Any] = dict(config.extra_params)
    # Only send the lower-bound filter once a real watermark exists; the first incremental
    # sync goes out unfiltered and still advances the watermark from the synced rows.
    if should_use_incremental_field and db_incremental_field_last_value is not None and config.incremental_param:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_field,
            "initial_value": None,
            "convert": _to_iso8601,
        }

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            # Paginated list responses carry an absolute next-page URL in their body, which
            # also keeps any filter params on later pages.
            **(
                {"data_selector": "results", "paginator": JSONResponsePaginator(next_url_path="next")}
                if config.paginated
                else {"paginator": SinglePagePaginator()}
            ),
        },
        "table_format": "delta",
    }


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _usage_rows(
    api_key: str,
    region: str,
    resumable_source_manager: ResumableSourceManager[RecallAIResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    today = _utc_today()
    day = today - timedelta(days=USAGE_BACKFILL_DAYS)
    watermark = _to_date(db_incremental_field_last_value)
    if watermark is not None:
        day = watermark - timedelta(days=USAGE_RESTATEMENT_DAYS)

    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        resumed_day = _to_date(resume_config.next_date) if resume_config is not None else None
        if resumed_day is not None and resumed_day > day:
            day = resumed_day

    url = f"{base_url_for_region(region)}{RECALL_AI_ENDPOINTS[USAGE_ENDPOINT].path}"
    session = make_tracked_session(
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )

    first_request = True
    while day <= today:
        if not first_request:
            interruptible_wait(USAGE_REQUEST_INTERVAL_SECONDS, safe_point=resumable_source_manager.safe_point)
        first_request = False

        # Both bounds round up to UTC midnight, so [day, day + 1) covers exactly one UTC day.
        next_day = day + timedelta(days=1)
        response = session.get(
            url,
            params={"start": _to_iso8601(day), "end": _to_iso8601(next_day)},
            timeout=60,
            allow_redirects=False,
        )
        response.raise_for_status()
        body = response.json()

        if next_day <= today:
            resumable_source_manager.save_state(RecallAIResumeConfig(next_date=next_day.isoformat()))
        yield {"date": day.isoformat(), "bot_total": body.get("bot_total") if isinstance(body, dict) else None}
        day = next_day


def recall_ai_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecallAIResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    endpoint_config = RECALL_AI_ENDPOINTS[endpoint]

    if endpoint == USAGE_ENDPOINT:
        return SourceResponse(
            name=endpoint,
            items=lambda: _usage_rows(
                api_key,
                region,
                resumable_source_manager,
                db_incremental_field_last_value if should_use_incremental_field else None,
            ),
            primary_keys=["date"],
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=[endpoint_config.partition_key],
            # Days are requested oldest first, one ordered series per run.
            sort_mode="asc",
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url_for_region(region),
            # Recall.ai requires the literal "Token " prefix, not "Bearer ".
            "auth": {
                "type": "api_key",
                "api_key": f"Token {api_key}",
                "name": "Authorization",
                "location": "header",
            },
            "headers": {"Accept": "application/json"},
            # Pin next-page and resume URLs to the region origin: a forged/off-host `next`
            # link would otherwise carry the Authorization header to an attacker-controlled
            # or internal destination. Pair host-pinning with rejecting redirects outright.
            "allowed_hosts": [],
            "allow_redirects": False,
            # Rows of scrubbed endpoints carry credentials (calendar OAuth secrets, SDK upload
            # tokens, meeting platform tokens), scrubbed below before they reach the warehouse,
            # which aren't covered by the generic sample denylist — disable diagnostic HTTP
            # capture for these endpoints so raw responses are never stored.
            **({"capture": False} if endpoint_config.scrub_fields else {}),
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.next_url:
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(RecallAIResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if endpoint_config.scrub_fields:
        resource = resource.add_map(_scrub_fields(endpoint_config.scrub_fields))

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        # The API documents no ordering and its cursor pagination accepts no sort param, so
        # assume nothing: "desc" commits the incremental watermark only when the sync
        # completes, which is correct whatever order rows actually arrive in.
        sort_mode="desc",
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url_for_region(region)}/api/v1/bot/",
        headers={"Authorization": f"Token {api_key}"},
        # The probe sends the key via Authorization, which `requests` already strips on a
        # cross-host redirect, but pin it anyway: it's a one-word defense against a future
        # change to this probe (e.g. a custom header) reintroducing the leak silently.
        allow_redirects=False,
    )
