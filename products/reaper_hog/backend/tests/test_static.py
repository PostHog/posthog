from pathlib import Path

from products.reaper_hog.backend.facade.enums import RootKind
from products.reaper_hog.backend.logic.scouts.static import find_knip_workspaces, knip_hits

REPORT = {
    "files": ["apps/code/src/old/Thing.tsx"],
    "issues": [
        {
            "file": "apps/code/src/lib/util.ts",
            "exports": [{"name": "unusedA", "line": 3}],
            "types": [{"name": "OldType"}],
        },
        {"file": "apps/code/src/lib/clean.ts", "exports": [], "types": []},
    ],
}


def test_knip_hits_prefix_paths_with_the_workspace_and_split_files_from_exports() -> None:
    hits = {hit.root: hit for hit in knip_hits(REPORT, "products/desktop/")}

    unused_file = hits["products/desktop/apps/code/src/old/Thing.tsx"]
    assert (unused_file.root_kind, unused_file.files) == (
        RootKind.FILE,
        ["products/desktop/apps/code/src/old/Thing.tsx"],
    )
    exports = hits["products/desktop/apps/code/src/lib/util.ts:OldType,unusedA"]
    assert exports.root_kind == RootKind.SYMBOL
    assert exports.evidence["exports"] == "OldType, unusedA"
    assert len(hits) == 2


def test_find_knip_workspaces_walks_up_from_the_scope(tmp_path: Path) -> None:
    (tmp_path / "products/desktop/apps/code").mkdir(parents=True)
    (tmp_path / "products/desktop/knip.json").write_text("{}")
    (tmp_path / "products/other").mkdir()

    assert find_knip_workspaces(tmp_path, "products/desktop/apps/code") == [tmp_path / "products/desktop"]
    assert find_knip_workspaces(tmp_path, "products/other") == []
    assert find_knip_workspaces(tmp_path, None) == [tmp_path / "products/desktop"]
