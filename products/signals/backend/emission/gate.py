"""The signal-emission gate the data-import pipeline asks before spawning the signals
child workflow. Registered into warehouse_sources via external_product_hooks at app-ready;
warehouse_sources calls it without importing signals (which depends on warehouse_sources).
"""

from products.signals.backend.emission.registry import get_signal_source_identity
from products.signals.backend.models import SignalSourceConfig


def emit_signals_enabled(team_id: int, source_type: str, schema_name: str, ai_data_processing_approved: bool) -> bool:
    if not ai_data_processing_approved:
        return False
    identity = get_signal_source_identity(source_type, schema_name)
    if identity is None:
        return False
    source_product, signal_source_type = identity
    return SignalSourceConfig.objects.filter(
        team_id=team_id,
        source_product=source_product,
        source_type=signal_source_type,
        enabled=True,
    ).exists()
