from __future__ import annotations

import sys
import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest
from unittest import mock

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
    "ignore": ["docs/**", "**/*.md"],
    "smoke_subset": ["playwright/e2e/auth.spec.ts"],
    "scenes_smoke_only": ["inbox"],
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
        # (name, changed files, expected mode,
        #  selected -> expected specs; full -> (reason category, reason detail))
        cases: list[tuple[str, list[str], str, set[str] | tuple[str, str]]] = [
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
            # coverage hole. Category + detail are the analytics grouping keys (detail names the
            # map gap to close and must stay low-cardinality), so lock both.
            (
                "unmapped scene forces full",
                ["frontend/src/scenes/settings/x.ts"],
                "full",
                ("unmapped_scene", "settings"),
            ),
            (
                "unmapped product forces full",
                ["products/messaging/frontend/x.ts"],
                "full",
                ("unmapped_product", "messaging"),
            ),
            ("unrecognized path forces full", ["some/random/file.ts"], "full", ("unmapped_path", "some/random/")),
            # unmapped_path detail is normalized to a bounded dir prefix, not the raw (high-cardinality) file path.
            ("deep unmapped path caps to leading segments", ["a/b/c/d/e.ts"], "full", ("unmapped_path", "a/b/c/")),
            # force_full wins even when another changed file would have narrowed; detail is the matched pattern.
            (
                "force-full pattern forces full alongside a mappable file",
                ["products/surveys/frontend/logic.ts", "posthog/models/team.py"],
                "full",
                ("force_full", "posthog/**"),
            ),
            # `*` must not cross `/`: a nested spec dir change must not be swallowed by `playwright/*.ts`.
            (
                "single-star force-full does not swallow nested spec changes",
                ["playwright/e2e/billing/billing.spec.ts"],
                "selected",
                {"playwright/e2e/billing/billing.spec.ts"},
            ),
            ("empty diff defaults to full", [], "full", ("empty_diff", "")),
            # Ignore-listed paths must not force full (that's the feature) and must not
            # outrank force_full (that would let an ignore glob swallow a critical path).
            (
                "ignored file contributes nothing alongside a mapped file",
                ["docs/handbook/page.txt", "products/surveys/frontend/logic.ts"],
                "selected",
                {"products/surveys/frontend/e2e/crud.spec.ts"},
            ),
            (
                "all-ignored diff falls closed to full with its own category",
                ["docs/handbook/page.txt", "some/notes.md"],
                "full",
                ("all_ignored", ""),
            ),
            (
                "force-full wins over ignore for the same file",
                ["posthog/README.md"],
                "full",
                ("force_full", "posthog/**"),
            ),
            # A smoke-only scene (declared: no direct coverage) narrows to the smoke
            # subset instead of forcing full — regressing this reverts the scene to
            # paying for the whole suite that never exercises it.
            (
                "smoke-only scene narrows to the smoke subset",
                ["frontend/src/scenes/inbox/components/Inbox.tsx"],
                "selected",
                {"playwright/e2e/auth.spec.ts"},
            ),
        ]
        for name, changed, mode, expected in cases:
            with self.subTest(name):
                result = self._select(changed)
                self.assertEqual(result["mode"], mode, msg=name)
                if mode == "selected":
                    self.assertEqual(set(result["spec_files"]), expected, msg=name)
                else:
                    category, detail = expected
                    self.assertTrue(result["full_run_reasons"], msg=f"{name}: expected a reason")
                    self.assertEqual(result["full_run_reason_category"], category, msg=name)
                    self.assertEqual(result["full_run_reason_detail"], detail, msg=name)

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

        targets: list[str] = list(area_map.get("smoke_subset", []))
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

    def test_smoke_only_scenes_are_consistent(self) -> None:
        # A scene in both `scenes` and `scenes_smoke_only` is a contradiction — the
        # mapped entry silently wins and the smoke declaration is dead weight. And a
        # non-empty smoke-only list with an empty smoke_subset would send every
        # smoke-only scene to the defensive no_specs full run, silently killing the
        # mechanism.
        area_map = selection.load_map(selection.MAP_PATH)
        overlap = set(area_map.get("scenes_smoke_only", [])) & set(area_map.get("scenes", {}))
        self.assertEqual(overlap, set(), msg="scene(s) listed in both scenes and scenes_smoke_only")
        if area_map.get("scenes_smoke_only"):
            self.assertTrue(
                area_map.get("smoke_subset"),
                msg="scenes_smoke_only requires a non-empty smoke_subset",
            )

    def test_ignore_patterns_never_match_specs(self) -> None:
        # An over-broad ignore entry (e.g. "playwright/**") would make a directly-edited
        # spec contribute nothing — the one selection miss the master backstop can't
        # attribute. Lock ignore to non-spec paths.
        area_map = selection.load_map(selection.MAP_PATH)
        all_specs = selection.discover_specs(selection.REPO_ROOT)
        for pattern in area_map.get("ignore", []):
            with self.subTest(pattern):
                rx = selection._compile_glob(pattern)
                matched = sorted(s for s in all_specs if rx.match(s))
                self.assertEqual(matched, [], msg=f"ignore pattern {pattern!r} matches spec files")

    def test_git_failure_tags_git_diff_failed_and_keeps_known_totals(self) -> None:
        # A git environment failure (e.g. a missing binary) surfaces as OSError, not
        # CalledProcessError. It must read as git_diff_failed — not map_load_failed — and
        # must keep the spec count already discovered, so selector_error telemetry points
        # at the real cause instead of reporting a false zero total.
        args = argparse.Namespace(map=str(selection.MAP_PATH), base_ref="origin/master")
        with mock.patch.object(selection, "changed_files_from_git", side_effect=FileNotFoundError("git missing")):
            result = selection._compute_result(args)

        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["full_run_reason_category"], "selector_error")
        self.assertEqual(result["full_run_reason_detail"], "git_diff_failed")
        self.assertGreater(result["total_spec_count"], 0)

    def test_every_spec_is_mapped_or_explicitly_full_suite_only(self) -> None:
        # Forces a conscious decision on every new spec: reachable by a map target
        # (it runs on selective runs for its area) or listed in full_suite_only (it
        # only runs on full suites and when directly edited). Without this, a new
        # spec next to file-level map entries silently never runs selectively.
        area_map = selection.load_map(selection.MAP_PATH)
        all_specs = selection.discover_specs(selection.REPO_ROOT)

        reachable: set[str] = set()
        for target in area_map.get("smoke_subset", []):
            reachable |= selection.expand_target(target, all_specs)
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
