import re
import json
import typing
import datetime as dt
import dataclasses

from django.conf import settings
from asgiref.sync import sync_to_async

import temporalio.activity as activity
import temporalio.workflow as workflow
from temporalio import exceptions as temporal_exceptions

from posthog.temporal.common.logger import get_internal_logger, bind_temporal_worker_logger_async
from posthog.temporal.common.schedule import convert_schedule_trigger_to_frequency

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, update_should_sync
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import EmitSignalsActivityInputs
from products.warehouse_sources.backend.temporal.data_imports.metrics import (
    get_data_import_finished_metric,
    get_v3_lock_skipped_metric,
)
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import finish_row_tracking, get_rows
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    CheckPipelineVersionActivityInputs,
    ReleaseV3LockActivityInputs,
    acquire_v3_pipeline_lock_activity,
    check_pipeline_version_activity,
    release_v3_pipeline_lock_activity,
)
