"""
Contract types for usage_ingestion.

Frozen dataclasses that define what this product exposes to other products. No Django imports.

Empty for now: core only reaches in for the two Celery tasks it schedules, which are re-exported
from ``facade.tasks``. Usage records themselves cross process boundaries over gRPC, not in-process,
so their shape lives in ``proto/usage_ingestion/v1/service.proto``. Contracts land here when a
Python caller in another product needs a usage record or a team-to-organization mapping directly.
"""
