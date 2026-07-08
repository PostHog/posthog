"""Temporal registration for the signal-emission workflows/activities driven off
warehouse data imports. These run on the VIDEO_EXPORT_TASK_QUEUE (signals worker)
and are wired into the worker by `start_temporal_worker`.

They live in the signals product (not warehouse_sources) because they depend on
signals internals; warehouse_sources only triggers them by workflow name via
`external_product_hooks`, so it never imports them.
"""

from products.signals.backend.emission.conversations_coordinator import (
    ConversationsSignalsCoordinatorWorkflow,
    EmitConversationsSignalsWorkflow,
    emit_conversations_signals_activity,
    get_conversations_signals_enabled_teams_activity,
)
from products.signals.backend.emission.emit_signals import (
    EmitDataImportSignalsWorkflow,
    emit_data_import_signals_activity,
)

EMIT_SIGNALS_WORKFLOWS = [
    EmitDataImportSignalsWorkflow,
    ConversationsSignalsCoordinatorWorkflow,
    EmitConversationsSignalsWorkflow,
]
EMIT_SIGNALS_ACTIVITIES = [
    emit_data_import_signals_activity,
    emit_conversations_signals_activity,
    get_conversations_signals_enabled_teams_activity,
]
