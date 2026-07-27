"""
Facade re-export for file-system registry wiring.

Core's file-system "unfiled" sync is a generic registry keyed by model class — it calls
``model_cls.get_file_system_unfiled(...)`` and ``instance.get_file_system_representation()``
on each registered ``FileSystemSyncMixin`` model. That dispatch needs the model class
itself, so ``Task`` crosses the boundary as a class (registry wiring), not as data.

Do NOT use this to query tasks from other products — use ``facade.api`` functions for that.
"""

from products.tasks.backend.models import Task

__all__ = ["Task"]
