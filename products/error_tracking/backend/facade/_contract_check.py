"""Contract-check for the Error tracking facade public surface.

Walks every name in :mod:`products.error_tracking.backend.facade` ``__all__``,
collects a structural fingerprint of each contract dataclass and public
function, and compares it against a committed lock file at
``products/error_tracking/backend/facade/.contract-lock.json``.

Additions are always allowed. Removals, renames, parameter drops, or type
narrowings break the check with a non-zero exit code.

Usage::

    python products/error_tracking/backend/facade/_contract_check.py
    python products/error_tracking/backend/facade/_contract_check.py --update

Run from the repo root so Django can pick up the settings module.
"""

from __future__ import annotations

import os
import sys
import json
import inspect
import argparse
import dataclasses
from pathlib import Path
from typing import Any

LOCK_FILE = Path(__file__).resolve().parent / ".contract-lock.json"


def _stringify_annotation(annotation: Any) -> str:
    if annotation is inspect.Signature.empty:
        return "<unset>"
    if isinstance(annotation, str):
        return annotation
    return str(annotation)


def _dataclass_snapshot(cls: type) -> dict[str, Any]:
    fields = dataclasses.fields(cls)
    return {
        "frozen": bool(cls.__dataclass_params__.frozen),  # type: ignore[attr-defined]
        "fields": {f.name: _stringify_annotation(f.type) for f in fields},
    }


def _callable_snapshot(func: Any) -> dict[str, Any]:
    signature = inspect.signature(func)
    parameters: dict[str, dict[str, str]] = {}
    for name, param in signature.parameters.items():
        parameters[name] = {
            "kind": param.kind.name,
            "annotation": _stringify_annotation(param.annotation),
            "default": "<empty>" if param.default is inspect.Parameter.empty else "<set>",
        }
    return {
        "parameters": parameters,
        "return": _stringify_annotation(signature.return_annotation),
    }


def _class_snapshot(cls: type) -> dict[str, Any]:
    # StrEnum and plain classes — only record names & type label.
    return {
        "kind": "class",
        "qualname": cls.__qualname__,
        "bases": [base.__name__ for base in cls.__bases__],
    }


def _build_snapshot() -> dict[str, Any]:
    from importlib import import_module

    # Make the repo root importable regardless of cwd.
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Django has to be configured before touching anything that pulls in
    # posthog.models — which the facade does indirectly.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django

    django.setup()

    facade = import_module("products.error_tracking.backend.facade")
    exported = getattr(facade, "__all__", [])

    contracts: dict[str, Any] = {}
    functions: dict[str, Any] = {}
    classes: dict[str, Any] = {}

    for name in sorted(exported):
        obj = getattr(facade, name)
        if dataclasses.is_dataclass(obj):
            contracts[name] = _dataclass_snapshot(obj)
        elif inspect.isfunction(obj) or inspect.iscoroutinefunction(obj):
            functions[name] = _callable_snapshot(obj)
        elif inspect.isclass(obj):
            classes[name] = _class_snapshot(obj)
        else:
            # Plain values (constants, re-exported instances) — store repr.
            functions.setdefault("_values", {})[name] = {"repr": repr(obj)[:200]}

    return {
        "version": 1,
        "contracts": contracts,
        "functions": functions,
        "classes": classes,
    }


def _load_lock() -> dict[str, Any] | None:
    if not LOCK_FILE.exists():
        return None
    return json.loads(LOCK_FILE.read_text())


def _write_lock(snapshot: dict[str, Any]) -> None:
    LOCK_FILE.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")


def _diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for section in ("contracts", "functions", "classes"):
        old_section = old.get(section, {}) or {}
        new_section = new.get(section, {}) or {}

        for name in sorted(old_section.keys()):
            if name not in new_section:
                errors.append(f"{section}: `{name}` was removed from the public surface")
                continue

            old_entry = old_section[name]
            new_entry = new_section[name]

            if section == "contracts":
                old_fields = set(old_entry.get("fields", {}).keys())
                new_fields = set(new_entry.get("fields", {}).keys())
                for field in sorted(old_fields - new_fields):
                    errors.append(f"contracts: `{name}.{field}` field was removed")
                for field in sorted(old_fields & new_fields):
                    if old_entry["fields"][field] != new_entry["fields"][field]:
                        errors.append(
                            f"contracts: `{name}.{field}` type changed "
                            f"`{old_entry['fields'][field]}` -> `{new_entry['fields'][field]}`"
                        )
                if old_entry.get("frozen") and not new_entry.get("frozen"):
                    errors.append(f"contracts: `{name}` is no longer frozen")

            elif section == "functions":
                if name == "_values":
                    continue
                old_params = old_entry.get("parameters", {}) or {}
                new_params = new_entry.get("parameters", {}) or {}
                for param in sorted(old_params.keys()):
                    if param not in new_params:
                        errors.append(f"functions: `{name}` parameter `{param}` was removed")
                        continue
                    old_param = old_params[param]
                    new_param = new_params[param]
                    if old_param.get("annotation") != new_param.get("annotation"):
                        errors.append(
                            f"functions: `{name}({param})` annotation changed "
                            f"`{old_param.get('annotation')}` -> `{new_param.get('annotation')}`"
                        )
                    # New required parameters break existing callers.
                for param, data in new_params.items():
                    if param not in old_params and data.get("default") == "<empty>":
                        errors.append(f"functions: `{name}` added new required parameter `{param}`")
                if old_entry.get("return") != new_entry.get("return"):
                    errors.append(
                        f"functions: `{name}` return type changed "
                        f"`{old_entry.get('return')}` -> `{new_entry.get('return')}`"
                    )

            elif section == "classes":
                if old_entry.get("qualname") != new_entry.get("qualname"):
                    errors.append(
                        f"classes: `{name}` qualname changed "
                        f"`{old_entry.get('qualname')}` -> `{new_entry.get('qualname')}`"
                    )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Overwrite the lock file with the current facade state.",
    )
    args = parser.parse_args()

    current = _build_snapshot()

    if args.update:
        _write_lock(current)
        print(f"Lock file updated: {LOCK_FILE}")  # noqa: T201
        return 0

    stored = _load_lock()
    if stored is None:
        _write_lock(current)
        print(  # noqa: T201
            f"Lock file created: {LOCK_FILE}\nCommit this file and run the contract-check on every subsequent change."
        )
        return 0

    errors = _diff_snapshots(stored, current)
    if errors:
        print("Error tracking facade contract-check FAILED:\n", file=sys.stderr)  # noqa: T201
        for message in errors:
            print(f"  - {message}", file=sys.stderr)  # noqa: T201
        print(  # noqa: T201
            "\nIf these changes are intentional, bump the lock file:\n"
            "    python products/error_tracking/backend/facade/_contract_check.py --update\n"
            "and re-run the check.",
            file=sys.stderr,
        )
        return 1

    print("Error tracking facade contract-check passed.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
