from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Tally is a single-tenant API — no per-account subdomain.
TALLY_BASE_URL = "https://api.tally.so"

# The API is date-versioned. Without this header the response shape is governed by whatever version
# the API key happened to be created against (the 2025-02-01 release turned /forms from a bare array
# into a paginated envelope), so every request pins it explicitly.
TALLY_VERSION_HEADER = "tally-version"
TALLY_API_VERSION = "2025-02-01"

# /forms and /forms/{formId}/submissions both cap `limit` at 500. Tally allows 100 requests per
# minute and submissions are fetched once per form, so the largest page keeps the fan-out cheap.
FORMS_PAGE_SIZE = 500
SUBMISSIONS_PAGE_SIZE = 500
# /webhooks caps `limit` at 100.
WEBHOOKS_PAGE_SIZE = 100

# `filter` values accepted by /forms/{formId}/submissions. Typed as literals so they stay
# assignment-compatible with the generated config field.
SUBMISSION_FILTER_COMPLETED: Literal["completed"] = "completed"
SUBMISSION_FILTER_ALL: Literal["all"] = "all"


@dataclass
class TallyEndpointConfig:
    name: str
    path: str
    # jsonpath to the row array. Tally wraps rows under a per-endpoint key rather than a shared one.
    data_selector: str
    # Read by the fan-out helper for the parent/child `limit`; ignored when `page_size_param` is None.
    page_size: int = FORMS_PAGE_SIZE
    # Query param carrying the page size, or None for endpoints that document no page-size param.
    page_size_param: Optional[str] = "limit"
    # False for endpoints that return the whole collection in one response.
    paginated: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used to partition the Delta table — never a mutable field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    fanout: Optional[DependentEndpointConfig] = None
    # Response fields nulled out before rows are written — secret material we must never persist.
    redact_fields: tuple[str, ...] = ()
    # Whether responses may be retained as HTTP samples. False for endpoints whose bodies carry
    # secrets the name-based sample scrubbers can't recognise.
    capture_samples: bool = True


def _forms_fanout(parent_params: Optional[dict[str, object]] = None) -> DependentEndpointConfig:
    # Child rows already carry `formId`, but injecting the parent id guarantees the composite
    # primary key's column exists even if a future response shape drops it.
    return DependentEndpointConfig(
        parent_name="forms",
        resolve_param="formId",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "formId"},
        parent_params=dict(parent_params or {}),
    )


TALLY_ENDPOINTS: dict[str, TallyEndpointConfig] = {
    "workspaces": TallyEndpointConfig(
        name="workspaces",
        path="/workspaces",
        data_selector="items",
        # /workspaces documents `page` only, so no page-size param is sent.
        page_size_param=None,
        partition_key="createdAt",
    ),
    "forms": TallyEndpointConfig(
        name="forms",
        path="/forms",
        data_selector="items",
        page_size=FORMS_PAGE_SIZE,
        partition_key="createdAt",
    ),
    # One request per form. Questions are what make the submission `responses` readable — answers
    # are keyed by question id, so without this table the submissions rows are opaque.
    "questions": TallyEndpointConfig(
        name="questions",
        path="/forms/{formId}/questions",
        data_selector="questions",
        # The endpoint returns every question in one unpaginated response and documents no params.
        page_size_param=None,
        paginated=False,
        # A question id is only unique within its form.
        primary_keys=["formId", "id"],
        partition_key="createdAt",
        # The fan-out helper applies one page-size param to parent and child alike, and the child
        # takes none — so the parent's page size is passed as an explicit parent param instead.
        fanout=_forms_fanout(parent_params={"limit": FORMS_PAGE_SIZE}),
    ),
    # The main fact table: one row per submission, with its answers nested under `responses`.
    "submissions": TallyEndpointConfig(
        name="submissions",
        path="/forms/{formId}/submissions",
        data_selector="submissions",
        page_size=SUBMISSIONS_PAGE_SIZE,
        # Tally documents the submission id as the id of a submission within a form, so the parent
        # form is part of the key — the table aggregates submissions across every form.
        primary_keys=["formId", "id"],
        partition_key="submittedAt",
        incremental_fields=[incremental_field("submittedAt")],
        default_incremental_field="submittedAt",
        # Tally documents no sort order for submissions, and the table interleaves one form's
        # history after another's, so the stream is not globally ascending. "desc" makes the
        # pipeline hold the watermark until the whole sync finishes instead of advancing it
        # per batch, which would strand the forms that had not been read yet.
        sort_mode="desc",
        fanout=_forms_fanout(),
    ),
    # Webhook configs carry the signing secret and any custom auth headers — credentials that would
    # let anyone with warehouse read access forge signed deliveries or reuse embedded tokens. Null
    # them before they land, and keep the raw responses out of HTTP sample capture entirely.
    "webhooks": TallyEndpointConfig(
        name="webhooks",
        path="/webhooks",
        data_selector="webhooks",
        page_size=WEBHOOKS_PAGE_SIZE,
        partition_key="createdAt",
        redact_fields=("signingSecret", "httpHeaders"),
        capture_samples=False,
    ),
}

ENDPOINTS = tuple(TALLY_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TALLY_ENDPOINTS.items()
}
