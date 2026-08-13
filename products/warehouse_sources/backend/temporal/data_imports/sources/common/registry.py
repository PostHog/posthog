import threading
from typing import TYPE_CHECKING

from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import AnySource


class SourceRegistry:
    """Registry for all available data warehouse sources"""

    _sources: dict[ExternalDataSourceType, "AnySource"] = {}
    _loaded: bool = False
    _attempted_types: set[ExternalDataSourceType] = set()
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
    def _ensure_source_loaded(cls, source_type: ExternalDataSourceType) -> None:
        # Targeted twin of `_ensure_loaded` for single-type lookups: imports only the module
        # that registers `source_type`, so asking for one source doesn't pay the cold import
        # of the whole catalog and its vendor SDKs. `_loaded` stays False, which keeps the
        # complete-catalog callers (`get_all_sources`, `get_registered_types`) bulk-loading
        # on their first use. Shares `_load_lock` with the bulk path so the two can't
        # interleave; the serialization is noise next to the import cost. `_attempted_types`
        # mirrors the bulk loader's failure isolation: a module that fails to import is
        # reported once by `load_source` and its type stays unregistered, rather than
        # re-running the broken import on every lookup. Only types that resolved to a module
        # are cached, because lookups accept arbitrary values (callers pass raw model-field
        # strings) and caching unresolvable ones would grow the set without bound.
        if cls._loaded or source_type in cls._sources:
            return
        with cls._load_lock:
            if cls._loaded or source_type in cls._sources or source_type in cls._attempted_types:
                return
            from products.warehouse_sources.backend.temporal.data_imports.sources import load_source  # noqa: PLC0415

            if load_source(source_type):
                cls._attempted_types.add(source_type)

    @classmethod
    def register(cls, source_class: type["AnySource"]):
        source_class_instance = source_class()
        source_type = source_class_instance.source_type

        cls._sources[source_type] = source_class_instance

        return source_class

    @classmethod
    def get_source(cls, source_type: ExternalDataSourceType) -> "AnySource":
        """Get a source instance by type"""

        cls._ensure_source_loaded(source_type)
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

        cls._ensure_source_loaded(source_type)
        return source_type in cls._sources

    @classmethod
    def get_registered_types(cls) -> list[ExternalDataSourceType]:
        """Get all registered source types"""

        cls._ensure_loaded()
        return list(cls._sources.keys())
