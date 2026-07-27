import threading
from typing import TYPE_CHECKING

from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import AnySource


class SourceRegistry:
    """Registry for all available data warehouse sources"""

    _sources: dict[ExternalDataSourceType, "AnySource"] = {}
    _loaded: bool = False
    _load_lock = threading.Lock()

    @classmethod
    def _ensure_loaded(cls) -> None:
        # Sources self-register via @SourceRegistry.register on import. We import them
        # on first registry use rather than at package import, so a process that never
        # touches the registry (most of them) doesn't pay for every vendor SDK at startup.
        # Double-checked lock: concurrent first-callers in a web worker must not observe a
        # half-populated registry, and `_loaded` flips only after the import succeeds — so a
        # failed load (e.g. a broken optional dependency) is retried rather than cached.
        if cls._loaded:
            return
        with cls._load_lock:
            # another thread may have loaded while we waited for the lock; mypy can't model that
            if cls._loaded:
                return  # type: ignore[unreachable]
            from products.warehouse_sources.backend.temporal.data_imports.sources import (
                load_all_sources,  # noqa: PLC0415
            )

            load_all_sources()
            cls._loaded = True

    @classmethod
    def register(cls, source_class: type["AnySource"]):
        source_class_instance = source_class()
        source_type = source_class_instance.source_type

        cls._sources[source_type] = source_class_instance

        return source_class

    @classmethod
    def get_source(cls, source_type: ExternalDataSourceType) -> "AnySource":
        """Get a source instance by type"""

        cls._ensure_loaded()
        if source_type not in cls._sources:
            raise ValueError(f"Unknown source type: {source_type}")
        return cls._sources[source_type]

    @classmethod
    def get_all_sources(cls) -> dict[ExternalDataSourceType, "AnySource"]:
        """Get all registered sources"""

        cls._ensure_loaded()
        return cls._sources

    @classmethod
    def is_registered(cls, source_type: ExternalDataSourceType) -> bool:
        """Check if a source type is registered"""

        cls._ensure_loaded()
        return source_type in cls._sources

    @classmethod
    def get_registered_types(cls) -> list[ExternalDataSourceType]:
        """Get all registered source types"""

        cls._ensure_loaded()
        return list(cls._sources.keys())
