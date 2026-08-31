"""Cross-boundary reverse accessors, read from the Django model graph.

A relation field (FK, O2O, M2M) that crosses a product boundary without `related_name="+"` adds a
reverse accessor to the target class. There is no import and no name-level use, so the AST channels
in crossings.py cannot see it; only the model registry can. This module owns the introspection and
returns plain edge lines; crossings.py turns them into baseline rows.

"""

from __future__ import annotations

import os
import re
import sys
import subprocess
from pathlib import Path

from .paths import FIRST_PARTY_ROOTS, REPO_ROOT

FIRST_PARTY = tuple(f"{root}." for root in FIRST_PARTY_ROOTS)

_EDGE_LINE = re.compile(r"^\S+ \S+ \S+$")


def reverse_accessor_edges() -> list[str]:
    """One line per cross-boundary relation with a visible accessor: `target owner.Model.field accessor`.

    Requires a populated Django app registry (`django.setup()` has run).
    """
    # noqa comments: Django is only importable after setup; hogli loads this module without it.
    from django.apps import apps  # noqa: PLC0415
    from django.db.models import Model  # noqa: PLC0415
    from django.db.models.fields.related import RelatedField  # noqa: PLC0415

    def boundary(model: type[Model]) -> str:
        # Ownership comes from the defining module, not _meta.app_label: product models that keep a
        # legacy label ("ee" on access_control's Role) would otherwise read as core and bypass the
        # ratchet, and relations between two such models would read as cross-product.
        module = model.__module__
        return module.split(".")[1] if module.startswith("products.") else "core"

    def label(model: type[Model]) -> str:
        # Rows carry the module-derived product name, not _meta.app_label, so a product's rows
        # survive the per-product filter even when the model keeps a legacy label (ee.Role).
        # Core models keep their app label (posthog/ee) — "core" would erase real information.
        owner = boundary(model)
        return owner if owner != "core" else model._meta.app_label

    out = set()
    for model in apps.get_models():
        if model._meta.auto_created:
            continue  # auto-created M2M through models restate the M2M field's own edge
        if model._meta.proxy:
            continue  # a proxy shares its parent's fields and creates no accessor of its own
        for field in model._meta.get_fields(include_hidden=False):
            # RelatedField narrows the get_fields() union to the concrete relation fields
            # (FK, O2O, M2M) that install a reverse descriptor.
            if not isinstance(field, RelatedField) or field.related_model is None:
                continue
            if field.model is not model:
                continue  # a concrete parent's field — only the parent installs the reverse descriptor
            related_model = field.related_model
            if related_model == "self":
                continue  # self-referential — never cross-boundary
            # A proxy target installs its reverse descriptor on the concrete model, so the
            # boundary check must see the concrete model, not the proxy.
            target = related_model._meta.concrete_model
            if target is None or not target.__module__.startswith(FIRST_PARTY):
                continue
            if boundary(model) == boundary(target):
                continue
            rel = field.remote_field
            if rel.hidden and not rel.related_query_name:
                continue  # related_name="+" with no explicit query name — fully sealed
            # An explicit related_query_name keeps filter() traversal alive even under
            # related_name="+", so the edge stays in the ratchet under a query: marker naming
            # the live traversal (get_accessor_name() would return the literal "+").
            accessor = f"query:{field.related_query_name()}" if rel.hidden else rel.get_accessor_name()
            out.add(f"{label(target)}.{target.__name__} {label(model)}.{model.__name__}.{field.name} {accessor}")
    return sorted(out)


_SUBPROCESS_BOOTSTRAP = """
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
# settings.TEST gates the AppConfig.ready() side effects (Redis template sync, Celery
# enqueues) — a model-graph read must not fire them.
os.environ["TEST"] = "1"
import django

django.setup()
from hogli_commands.product.reverse_accessors import reverse_accessor_edges

print("\\n".join(reverse_accessor_edges()))
"""


def reverse_accessor_edge_lines() -> list[str]:
    """Edges via the current process when Django is booted, else via a subprocess.

    `django.setup()` runs every AppConfig.ready() (registries, clients, checks), so the subprocess
    path costs a few seconds. A caller that already booted Django — pytest does — gets the walk for
    free in-process.
    """
    try:
        from django.apps import apps  # noqa: PLC0415 — probe, not a dependency: hogli runs without Django booted

        ready = apps.ready
    except Exception:
        ready = False
    if ready:
        return reverse_accessor_edges()

    # The CLI reaches hogli_commands through sys.path, not site-packages, and the settings module
    # needs the repo root as cwd — hand the subprocess both explicitly.
    package_root = Path(__file__).parents[2]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(package_root), os.environ.get("PYTHONPATH", "")])}
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_BOOTSTRAP],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"reverse accessor capture failed:\n{result.stderr[-2000:]}")
    return [line for line in result.stdout.splitlines() if _EDGE_LINE.match(line)]
