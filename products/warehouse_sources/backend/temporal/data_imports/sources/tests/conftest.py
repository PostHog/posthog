import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources import (
    PLUGIN_SOURCES_PACKAGE,
    SourceRegistry,
    source_module_path,
)

# The parameters through which a test runs once per source. Their values are source keys.
PER_SOURCE_PARAMETERS = ("source_type", "name")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--source-vendors",
        default=None,
        help=(
            "Comma-separated vendor directory names under products/warehouse_sources/sources/. The tests that run once per source "
            "then run only for these vendors. The tests of the whole catalog still run. CI sets it on a "
            "pull request that changes only these vendors."
        ),
    )


def _plugin_vendor(module_path: str | None) -> str | None:
    """The vendor directory under the plugin sources of a source module, or None for a vendor in the product."""
    prefix = f"{PLUGIN_SOURCES_PACKAGE}."
    if module_path is None or not module_path.startswith(prefix):
        return None
    parts = module_path.removeprefix(prefix).split(".")
    if len(parts) == 2 and parts[1] == "source":
        return parts[0]
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    option = config.getoption("--source-vendors")
    if option is None:
        return
    vendors = {vendor for vendor in option.split(",") if vendor}
    vendor_by_key = {
        str(source_type): _plugin_vendor(source_module_path(source_type))
        for source_type in SourceRegistry.get_all_sources()
    }
    missing = sorted(vendors - set(vendor_by_key.values()))
    if missing:
        # A narrowed run that matches no source would run none of its tests and still pass.
        raise pytest.UsageError(f"--source-vendors names vendors that register no source: {', '.join(missing)}")

    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        callspec = getattr(item, "callspec", None)
        params = callspec.params if callspec is not None else {}
        keys = {str(params[name]) for name in PER_SOURCE_PARAMETERS if name in params} & vendor_by_key.keys()
        if keys and not any(vendor_by_key[key] in vendors for key in keys):
            deselected.append(item)
        else:
            kept.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
