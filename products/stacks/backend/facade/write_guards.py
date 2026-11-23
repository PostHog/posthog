"""The write guard core runs on every unsafe request that loads an entity of a kind stacks can manage.

Only `posthog/managed_writes.py` reads `WRITE_GUARDS`.
"""

from posthog.managed_writes import WriteGuard

from ..logic import managed

WRITE_GUARDS = (WriteGuard(model_labels=frozenset(managed.KIND_BY_MODEL), check=managed.check_write),)
