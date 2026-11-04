from pathlib import Path

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.source_icons import SourceIconFinder


@pytest.fixture
def plugin_sources_dir(tmp_path: Path):
    vendor = tmp_path / "acme_crm"
    vendor.mkdir()
    (vendor / "icon.png").write_bytes(b"png")
    (vendor / "source.py").write_text("SECRET = 'code'")
    (tmp_path / "icon.png").write_bytes(b"not a vendor icon")
    with patch("products.warehouse_sources.backend.source_icons.PLUGIN_SOURCES_DIR", tmp_path):
        yield tmp_path


@pytest.mark.parametrize(
    "path,found",
    [
        ("warehouse-sources/acme_crm/icon.png", True),
        ("warehouse-sources/acme_crm/source.py", False),
        ("warehouse-sources/../icon.png", False),
        ("warehouse-sources/acme_crm/../icon.png", False),
        ("services/acme_crm/icon.png", False),
    ],
)
def test_finder_serves_only_vendor_icons(plugin_sources_dir: Path, path: str, found: bool) -> None:
    finder = SourceIconFinder()

    assert bool(finder.find(path)) is found
    assert [listed for listed, _storage in finder.list(None)] == ["acme_crm/icon.png"]
