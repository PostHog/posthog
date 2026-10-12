import re

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.facade.codebase_detection import Detection
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

ALL_SOURCES = SourceRegistry.get_all_sources()


def test_released_sources_and_only_they_declare_codebase_detection() -> None:
    missing = sorted(
        str(source_type)
        for source_type, source in ALL_SOURCES.items()
        if not source.get_source_config.unreleasedSource and source.codebase_detection is None
    )
    unreleased = sorted(
        str(source_type)
        for source_type, source in ALL_SOURCES.items()
        if source.get_source_config.unreleasedSource and source.codebase_detection is not None
    )
    assert missing == [], (
        "Released sources must say how the wizard detects them in a codebase. Set "
        "`codebase_detection = detect(...)` on the source class, or `not_detectable(reason)` when no "
        f"package, .env key or script tag gives it away: {missing}"
    )
    assert unreleased == [], f"Unreleased sources must not set `codebase_detection`: {unreleased}"


def test_env_key_patterns_are_anchored_regexes() -> None:
    for source_type, source in ALL_SOURCES.items():
        if not isinstance(source.codebase_detection, Detection):
            continue
        for pattern in source.codebase_detection.env_key_patterns:
            # Unanchored, a pattern matches any key that merely contains the vendor name.
            assert pattern.startswith("^"), f"{source_type}: {pattern!r} is not anchored"
            re.compile(pattern)
