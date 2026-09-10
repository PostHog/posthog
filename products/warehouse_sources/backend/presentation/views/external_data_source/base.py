"""Shared ground for the external data source view mixins.

Every mixin resolves its outbound collaborators (logger, error capture, the data warehouse
facade) through this module, so tests have one place to patch them. The mixins also inherit
the typing-only base below, which is what lets each one call across to attributes the
assembled viewset provides at runtime.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

import structlog
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.data_warehouse.backend.facade.api import (
    bulk_create_external_data_job_schedules,
    bulk_delete_external_data_schedules,
    cancel_external_data_workflow,
    delete_discover_schemas_schedule,
    delete_external_data_schedule,
    ensure_cdc_slot_cleanup_schedule,
    is_cdc_enabled_for_team,
    is_cdc_extraction_schedule_paused,
    sync_cdc_extraction_schedule,
    sync_discover_schemas_schedule,
    trigger_external_data_source_workflow,
    unpause_cdc_extraction_schedule,
)
from products.revenue_analytics.backend.facade.api import ensure_person_join
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import (
    AnySource,
    CDCSourceAdapter,
    Config,
    SourceRegistry,
    SourceSchema,
    WebhookSource,
    cdc_pg_connection,
    get_primary_key_columns,
    purge_buffer_prefix,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

__all__ = [
    "ExternalDataSourceViewSetBase",
    "SourceRegistry",
    "bulk_create_external_data_job_schedules",
    "bulk_delete_external_data_schedules",
    "cancel_external_data_workflow",
    "capture_exception",
    "cdc_pg_connection",
    "delete_discover_schemas_schedule",
    "delete_external_data_schedule",
    "ensure_cdc_slot_cleanup_schedule",
    "ensure_person_join",
    "get_primary_key_columns",
    "is_cdc_enabled_for_team",
    "is_cdc_extraction_schedule_paused",
    "logger",
    "purge_buffer_prefix",
    "sync_cdc_extraction_schedule",
    "sync_discover_schemas_schedule",
    "trigger_external_data_source_workflow",
    "unpause_cdc_extraction_schedule",
]


if TYPE_CHECKING:

    class ExternalDataSourceViewSetBase(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
        """The assembled viewset as each mixin sees it. Cross-mixin methods are declared here
        so a mixin can call one another mixin implements without importing it."""

        ordering: str

        def _assert_can_write_schemas(self, schemas: Iterable[ExternalDataSchema]) -> None: ...

        def _auto_register_webhook(
            self,
            source: WebhookSource,
            source_config: Config,
            source_id: str,
            source_schemas: list[SourceSchema],
            permission_errors: Mapping[str, str | None] | None = None,
        ) -> dict | None: ...

        def _setup_cdc_resources(
            self, adapter: CDCSourceAdapter, source_model: ExternalDataSource, payload: dict
        ) -> str | None: ...

        def _validate_source_config_and_credentials(
            self,
            source: AnySource,
            source_type_model: ExternalDataSourceType,
            payload: dict,
            access_method: str = ExternalDataSource.AccessMethod.WAREHOUSE,
        ) -> tuple[Response | None, Config | None]: ...

        def refresh_schemas(self, request: Request, *args: Any, **kwargs: Any) -> Response: ...

else:
    ExternalDataSourceViewSetBase = object
