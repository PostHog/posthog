"""Tests for product isolation tooling — scan classification and move mechanics."""

from __future__ import annotations

from pathlib import Path

import pytest

import hogli_commands.product.isolate as iso
from hogli_commands.product.isolate import (
    Reference,
    _module_dotted,
    absolutize_relative_imports,
    build_move_plan,
    classify_reference,
    core_coupling_count,
    detect_viewset_modules,
    internal_import_count,
    pin_task_names,
    rewrite_paths,
    scan_references,
    shared_task_names,
)

# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module,importer,expected",
    [
        ("products.logs.backend.models", "posthog/api/team.py", "model-access"),
        ("products.logs.backend.logs_query_runner", "posthog/hogql_queries/query_runner.py", "query-runner"),
        ("products.logs.backend.tasks", "posthog/tasks/scheduled.py", "celery-task"),
        ("products.logs.backend.temporal.metrics", "posthog/temporal/common/worker.py", "temporal-wiring"),
        ("products.logs.backend.models", "posthog/hogql/database/schema/test/test_system_tables.py", "test-fixture"),
        ("products.logs.backend.models", "posthog/api/test_team.py", "test-fixture"),
        ("products.logs.backend.alert_utils", "posthog/api/team.py", "other-internal"),
    ],
)
def test_classify_reference(module: str, importer: str, expected: str) -> None:
    assert classify_reference(module, importer) == expected


def test_scan_references_classifies_imports_and_strings(tmp_path: Path) -> None:
    caller = tmp_path / "posthog" / "api" / "thing.py"
    caller.parent.mkdir(parents=True)
    caller.write_text(
        "from products.logs.backend.models import TeamLogsConfig\n"
        'patched = patch("products.logs.backend.api.export_asset")\n'
        "from products.logs.backend.facade.api import get_config\n"
    )
    own = tmp_path / "products" / "logs" / "backend" / "x.py"
    own.parent.mkdir(parents=True)
    own.write_text("from products.logs.backend.models import TeamLogsConfig\n")

    refs = scan_references("logs", [caller, own], tmp_path)

    kinds = {(r.kind, r.is_import) for r in refs}
    assert ("model-access", True) in kinds
    assert ("string-reference", False) in kinds
    # facade imports and the product's own files are not cross-boundary references
    assert all("facade" not in r.module for r in refs)
    assert all(not r.file.startswith("products/logs/") for r in refs)


def test_core_coupling_count_only_counts_core_imports() -> None:
    refs = [
        Reference(
            file="posthog/api/team.py", line=1, module="products.x.backend.models", kind="model-access", is_import=True
        ),
        Reference(file="ee/thing.py", line=1, module="products.x.backend.models", kind="model-access", is_import=True),
        Reference(
            file="products/other/backend/y.py",
            line=1,
            module="products.x.backend.models",
            kind="model-access",
            is_import=True,
        ),
        Reference(
            file="posthog/api/team.py",
            line=2,
            module="products.x.backend.api",
            kind="string-reference",
            is_import=False,
        ),
    ]
    assert core_coupling_count(refs) == 2


# ---------------------------------------------------------------------------
# path rewriting
# ---------------------------------------------------------------------------


def test_rewrite_paths_respects_word_boundaries() -> None:
    renames = {"products.logs.backend.api": "products.logs.backend.presentation.views.api"}
    text = (
        "from products.logs.backend.api import LogsViewSet\n"
        "import products.logs.backend.api as logs\n"
        'p = patch("products.logs.backend.api.export_asset")\n'
        "from products.logs.backend.apps import LogsConfig\n"
        "from products.logs.backend.api_extra import x\n"
    )
    result = rewrite_paths(text, renames)
    assert "from products.logs.backend.presentation.views.api import LogsViewSet" in result
    assert "import products.logs.backend.presentation.views.api as logs" in result
    assert 'patch("products.logs.backend.presentation.views.api.export_asset")' in result
    # apps and api_extra must survive untouched
    assert "from products.logs.backend.apps import LogsConfig" in result
    assert "from products.logs.backend.api_extra import x" in result


def test_rewrite_paths_longest_rename_wins() -> None:
    renames = {
        "products.x.backend.api": "products.x.backend.presentation.views.api",
        "products.x.backend.api_v2": "products.x.backend.presentation.views.api_v2",
    }
    text = "import products.x.backend.api_v2\nimport products.x.backend.api\n"
    result = rewrite_paths(text, renames)
    assert "import products.x.backend.presentation.views.api_v2" in result
    assert "import products.x.backend.presentation.views.api\n" in result


# ---------------------------------------------------------------------------
# relative import absolutization
# ---------------------------------------------------------------------------


def test_absolutize_relative_imports() -> None:
    text = "from .models import Thing\nfrom . import logic\nfrom ..shared import other\n"
    result, warnings = absolutize_relative_imports(text, "products.logs.backend")
    assert "from products.logs.backend.models import Thing" in result
    assert "from products.logs.backend import logic" in result
    # multi-level imports are reported, not guessed
    assert "from ..shared import other" in result
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# celery task pinning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected_fragment",
    [
        ("@shared_task\ndef other_task():\n    pass\n", '@shared_task(name="products.logs.backend.tasks.other_task")'),
        (
            "@shared_task(ignore_result=True)\ndef cleanup_task() -> None:\n    pass\n",
            '@shared_task(ignore_result=True, name="products.logs.backend.tasks.cleanup_task")',
        ),
        # nested parens in the args must not truncate the match at the inner )
        (
            "@shared_task(expires=timedelta(hours=1))\ndef expiring():\n    pass\n",
            '@shared_task(expires=timedelta(hours=1), name="products.logs.backend.tasks.expiring")',
        ),
    ],
)
def test_pin_task_names(source: str, expected_fragment: str) -> None:
    result, warnings = pin_task_names(source, "products.logs.backend.tasks")
    assert expected_fragment in result
    assert warnings == []


def test_pin_task_names_existing_name_untouched() -> None:
    text = '@shared_task(name="legacy.name")\ndef named_task():\n    pass\n'
    result, warnings = pin_task_names(text, "products.logs.backend.tasks")
    assert result == text
    assert warnings == []


def test_pin_task_names_warns_when_not_directly_above_def() -> None:
    text = "@shared_task\n@wraps(inner)\ndef stacked():\n    pass\n"
    result, warnings = pin_task_names(text, "products.logs.backend.tasks")
    assert result == text
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# viewset detection and thin/thick signal
# ---------------------------------------------------------------------------


def _write_backend(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "api.py").write_text(
        "from rest_framework import viewsets\n"
        "from products.demo.backend.runner import Runner\n"
        "from .models import Thing\n"
        "class DemoViewSet(viewsets.ViewSet):\n    pass\n"
    )
    (backend / "models.py").write_text("class Thing:\n    pass\n")
    (backend / "routes.py").write_text("from products.demo.backend.api import DemoViewSet\n")
    (backend / "tasks.py").write_text("from celery import shared_task\n\n@shared_task\ndef tick():\n    pass\n")
    return backend


def test_detect_viewset_modules(tmp_path: Path) -> None:
    backend = _write_backend(tmp_path)
    assert [p.name for p in detect_viewset_modules(backend)] == ["api.py"]


def test_detect_viewset_modules_includes_api_subpackage(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    (backend / "api").mkdir(parents=True)
    (backend / "api" / "views.py").write_text(
        "from rest_framework import viewsets\nclass FooViewSet(viewsets.ViewSet):\n    pass\n"
    )
    # root-only by default — the api/ subpackage is opt-in
    assert detect_viewset_modules(backend) == []
    assert [p.name for p in detect_viewset_modules(backend, include_api=True)] == ["views.py"]


def test_module_dotted_keeps_intermediate_package() -> None:
    assert _module_dotted("wa", Path("api/heatmaps_api.py")) == "products.wa.backend.api.heatmaps_api"
    assert _module_dotted("wa", Path("views.py")) == "products.wa.backend.views"


def test_build_move_plan_relocates_whole_api_subpackage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iso, "PRODUCTS_DIR", tmp_path)
    backend = tmp_path / "wa" / "backend"
    api = backend / "api"
    api.mkdir(parents=True)
    (api / "__init__.py").write_text("from .api import WebAnalyticsViewSet\n")
    (api / "api.py").write_text(
        "from rest_framework import viewsets\nclass WebAnalyticsViewSet(viewsets.ViewSet):\n    pass\n"
    )
    (api / "heatmaps_utils.py").write_text("WIDTH = 1\n")
    (backend / "serializers.py").write_text("from rest_framework import serializers\n")

    plan = build_move_plan("wa")

    views_dir = backend / "presentation" / "views"
    # the whole package moves — viewsets, helpers, and __init__ — into presentation/views/
    assert {src.name for src, _ in plan.view_moves} == {"__init__.py", "api.py", "heatmaps_utils.py"}
    assert all(dst.parent == views_dir for _, dst in plan.view_moves)
    # one prefix rename covers bare-package imports, dotted modules, and @patch strings
    assert plan.module_renames["products.wa.backend.api"] == "products.wa.backend.presentation.views"
    # serializers.py is pulled into presentation/ as strict-lint demands
    assert plan.serializers_move == (backend / "serializers.py", backend / "presentation" / "serializers.py")
    assert plan.module_renames["products.wa.backend.serializers"] == "products.wa.backend.presentation.serializers"


def test_build_move_plan_views_override_keeps_subdir_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iso, "PRODUCTS_DIR", tmp_path)
    backend = tmp_path / "wa" / "backend"
    (backend / "api").mkdir(parents=True)
    (backend / "api" / "heatmaps_api.py").write_text("x = 1\n")

    plan = build_move_plan("wa", views=["api/heatmaps_api.py"])

    # the override must not flatten the dotted path to backend.heatmaps_api
    assert plan.module_renames == {
        "products.wa.backend.api.heatmaps_api": "products.wa.backend.presentation.views.heatmaps_api"
    }


def test_internal_import_count_counts_internals_and_relatives(tmp_path: Path) -> None:
    backend = _write_backend(tmp_path)
    assert internal_import_count(backend / "api.py", "demo") == 2


def test_shared_task_names(tmp_path: Path) -> None:
    backend = _write_backend(tmp_path)
    assert shared_task_names(backend / "tasks.py") == ["tick"]
