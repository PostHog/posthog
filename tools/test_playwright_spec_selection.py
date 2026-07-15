from __future__ import annotations

import sys
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest

SCRIPT_PATH = Path(__file__).with_name("playwright_spec_selection.py")


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("playwright_spec_selection", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


selection = _load_module()

# A small stand-in map + spec set so select() cases don't depend on the real repo layout.
FAKE_SPECS = {
    "playwright/e2e/auth.spec.ts",
    "playwright/e2e/billing/billing.spec.ts",
    "playwright/e2e/product-analytics/dashboards.spec.ts",
    "playwright/e2e/product-analytics/insights/trends.spec.ts",
    "products/surveys/frontend/e2e/crud.spec.ts",
}
FAKE_MAP = {
    "force_full": ["posthog/**", "pnpm-lock.yaml", "playwright/*.ts"],
    "products": {"surveys": ["products/surveys/frontend/e2e/"]},
    "scenes": {
        "billing": ["playwright/e2e/billing/"],
        "insights": ["playwright/e2e/product-analytics/"],
    },
    "explicit": {"products/web_analytics/frontend/**": ["playwright/e2e/auth.spec.ts"]},
}


class TestPlaywrightSpecSelection(unittest.TestCase):
    def _select(self, changed: list[str]) -> dict:
        return selection.select(changed, FAKE_MAP, FAKE_SPECS)

    def test_select_behavior_matrix(self) -> None:
        # (name, changed files, expected mode, expected specs (selected) or reason category (full))
        cases: list[tuple[str, list[str], str, set[str] | str]] = [
            (
                "mapped product frontend narrows to that product's specs",
                ["products/surveys/frontend/logic.ts"],
                "selected",
                {"products/surveys/frontend/e2e/crud.spec.ts"},
            ),
            (
                "mapped scene narrows to its spec dir (nested change still resolves)",
                ["frontend/src/scenes/insights/views/deep/nested.ts"],
                "selected",
                {
                    "playwright/e2e/product-analytics/dashboards.spec.ts",
                    "playwright/e2e/product-analytics/insights/trends.spec.ts",
                },
            ),
            (
                "explicit rule maps a spec-less product frontend",
                ["products/web_analytics/frontend/tiles.ts"],
                "selected",
                {"playwright/e2e/auth.spec.ts"},
            ),
            (
                "directly edited spec runs itself",
                ["playwright/e2e/auth.spec.ts"],
                "selected",
                {"playwright/e2e/auth.spec.ts"},
            ),
            # Fail-closed: the core safety property. Any of these dropping to "selected" is a
            # coverage hole. The category is the analytics grouping key, so lock it too.
            ("unmapped scene forces full", ["frontend/src/scenes/settings/x.ts"], "full", "unmapped_scene"),
            ("unmapped product forces full", ["products/messaging/frontend/x.ts"], "full", "unmapped_product"),
            ("unrecognized path forces full", ["some/random/file.ts"], "full", "unmapped_path"),
            # force_full wins even when another changed file would have narrowed.
            (
                "force-full pattern forces full alongside a mappable file",
                ["products/surveys/frontend/logic.ts", "posthog/models/team.py"],
                "full",
                "force_full",
            ),
            # `*` must not cross `/`: a nested spec dir change must not be swallowed by `playwright/*.ts`.
            (
                "single-star force-full does not swallow nested spec changes",
                ["playwright/e2e/billing/billing.spec.ts"],
                "selected",
                {"playwright/e2e/billing/billing.spec.ts"},
            ),
            ("empty diff defaults to full", [], "full", "empty_diff"),
        ]
        for name, changed, mode, expected in cases:
            with self.subTest(name):
                result = self._select(changed)
                self.assertEqual(result["mode"], mode, msg=name)
                if mode == "selected":
                    self.assertEqual(set(result["spec_files"]), expected, msg=name)
                else:
                    self.assertTrue(result["full_run_reasons"], msg=f"{name}: expected a reason")
                    self.assertEqual(result["full_run_reason_category"], expected, msg=name)

    def test_over_ceiling_forces_full(self) -> None:
        changed = [f"products/surveys/frontend/f{i}.ts" for i in range(selection.MAX_CHANGED_FILES + 1)]
        self.assertEqual(self._select(changed)["mode"], "full")

    def test_real_map_targets_resolve_on_disk(self) -> None:
        # Guards against map drift: if a spec is renamed/deleted and a target stops
        # resolving, expand_target raises at runtime and CI silently falls open to
        # permanent full runs. This locks every target to a real spec in the two roots.
        area_map = selection.load_map(selection.MAP_PATH)
        all_specs = selection.discover_specs(selection.REPO_ROOT)
        self.assertTrue(all_specs, "no Playwright specs discovered — wrong REPO_ROOT?")

        targets: list[str] = []
        for spec_globs in area_map.get("products", {}).values():
            targets += spec_globs
        for spec_globs in area_map.get("scenes", {}).values():
            targets += spec_globs
        for spec_globs in area_map.get("explicit", {}).values():
            targets += spec_globs

        for target in targets:
            with self.subTest(target):
                resolved = selection.expand_target(target, all_specs)  # raises MapError if empty
                for spec in resolved:
                    self.assertTrue(
                        spec.startswith("playwright/e2e/") or "/frontend/e2e/" in spec,
                        msg=f"{target} -> {spec} is outside the spec roots",
                    )

    def test_every_spec_is_mapped_or_explicitly_full_suite_only(self) -> None:
        # Forces a conscious decision on every new spec: reachable by a map target
        # (it runs on selective runs for its area) or listed in full_suite_only (it
        # only runs on full suites and when directly edited). Without this, a new
        # spec next to file-level map entries silently never runs selectively.
        area_map = selection.load_map(selection.MAP_PATH)
        all_specs = selection.discover_specs(selection.REPO_ROOT)

        reachable: set[str] = set()
        for section in ("products", "scenes", "explicit"):
            for targets in area_map.get(section, {}).values():
                for target in targets:
                    reachable |= selection.expand_target(target, all_specs)
        full_suite_only = set(area_map.get("full_suite_only", []))

        self.assertEqual(
            full_suite_only - all_specs,
            set(),
            msg="full_suite_only lists specs that no longer exist — remove them from tools/playwright_area_map.json",
        )
        self.assertEqual(
            full_suite_only & reachable,
            set(),
            msg="full_suite_only lists specs already reachable by a map target — remove the redundant entries",
        )
        self.assertEqual(
            all_specs - reachable - full_suite_only,
            set(),
            msg=(
                "new spec(s) not reachable by any map target: add a mapping in "
                "tools/playwright_area_map.json (products/scenes/explicit) or list them "
                "under full_suite_only to accept they only run in full suites"
            ),
        )


if __name__ == "__main__":
    unittest.main()
