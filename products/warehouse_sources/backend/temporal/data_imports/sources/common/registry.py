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
        # half-populated registry, and `_loaded` flips only after the load returns — so a load
        # that raises outright is retried rather than cached. A single source module that can't
        # be imported is skipped by `load_all_sources`, leaving it absent here (and reported as
        # an unknown type by `get_source`) rather than taking every other source down with it.
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
    def _load_one(cls, source_type: ExternalDataSourceType) -> None:
        # Importing every source module costs seconds per process, and a request typically
        # needs a handful of types. Import only the module for this type; `get_source` falls
        # back to the full load when that leaves the type unregistered.
        if cls._loaded or source_type in cls._sources:
            return
        from products.warehouse_sources.backend.temporal.data_imports.sources import load_source  # noqa: PLC0415

        load_source(source_type)

    @classmethod
    def get_source(cls, source_type: ExternalDataSourceType) -> "AnySource":
        """Get a source instance by type"""

        # Callers may hand us the raw string value (e.g. an `oauth_accounts` query param). The
        # str-mixin enum compares equal to its value, so the `in cls._sources` checks below still
        # work, but the lazy single-module load reads `source_type.name`, which a plain str lacks.
        # Coerce to a real enum member first so both the lazy and full-load paths resolve, and so
        # an unknown value surfaces as ValueError rather than AttributeError.
        try:
            source_type = ExternalDataSourceType(source_type)
        except ValueError:
            raise ValueError(f"Unknown source type: {source_type}")

        cls._load_one(source_type)
        if source_type not in cls._sources:
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
