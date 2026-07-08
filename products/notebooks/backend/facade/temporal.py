"""
Facade re-exports for Temporal wiring.

The worker bootstrap (`start_temporal_worker`) registers notebook workflows and
activities through these re-exports rather than importing ``backend.temporal``
directly.
"""

from ..temporal import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)
