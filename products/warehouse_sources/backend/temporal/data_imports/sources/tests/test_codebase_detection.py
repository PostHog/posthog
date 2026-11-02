import re

import pytest

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.facade.codebase_detection import Detection, fields_require_ui
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
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
        "`codebase_detection = detect(...)` on the source class, or `NOT_DETECTABLE` when no "
        f"package, .env key or script tag gives it away: {missing}"
    )
    assert unreleased == [], f"Unreleased sources must not set `codebase_detection`: {unreleased}"


# The wizard validates each catalog entry against these shapes and skips any entry that fails, so a
# declaration outside them silently stops being detected. The env shape also rules out patterns that
# backtrack badly, because the wizard runs them on its main thread.
ENV_KEY_PATTERN_SHAPE = re.compile(r"^\^(?:(?:[A-Za-z0-9_]|\((?:[A-Za-z0-9_]+\|)*[A-Za-z0-9_]+\))\??)+\$?$")
LABEL_SHAPE = re.compile(r"^[\w .,&()+/'!-]{1,80}$")
PACKAGE_SHAPE = re.compile(r"^[A-Za-z0-9@/._:+~-]{1,214}$")
SCRIPT_HOST_SHAPE = re.compile(r"^[a-z0-9.-]{1,253}$")


def test_detection_fits_the_shapes_the_wizard_accepts() -> None:
    for source_type, source in ALL_SOURCES.items():
        detection = source.codebase_detection
        if not isinstance(detection, Detection):
            continue
        assert LABEL_SHAPE.match(source.get_source_config.label or str(source_type)), source_type
        for pattern in detection.env_key_patterns:
            assert ENV_KEY_PATTERN_SHAPE.match(pattern), f"{source_type}: {pattern!r}"
        for host in detection.script_hosts:
            assert SCRIPT_HOST_SHAPE.match(host), f"{source_type}: {host!r}"
        for names in detection.packages.values():
            for name in names:
                assert PACKAGE_SHAPE.match(name), f"{source_type}: {name!r}"


@pytest.mark.parametrize(
    "source_type, requires_ui",
    [
        # Every login option is OAuth or a key file upload, though each option marks its field optional.
        (ExternalDataSourceType.BIGQUERY, True),
        (ExternalDataSourceType.GOOGLEADS, True),
        # One login option takes a pasted API key.
        (ExternalDataSourceType.STRIPE, False),
        (ExternalDataSourceType.POSTGRES, False),
    ],
    ids=str,
)
def test_fields_require_ui_only_when_no_option_can_be_typed(
    source_type: ExternalDataSourceType, requires_ui: bool
) -> None:
    assert fields_require_ui(ALL_SOURCES[source_type].get_source_config.fields) is requires_ui
