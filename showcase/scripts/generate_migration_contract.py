#!/usr/bin/env python3
# ruff: noqa: T201
"""
showcase/scripts/generate_migration_contract.py
Utility script to scan all historical migrations in the repository via Python AST
and freeze their internal application references into migration_contract.json.
"""

import ast
import hashlib
import importlib
import inspect
import json
import os
import sys
from pathlib import Path


def generate_migration_contract(repo_root: Path = Path(".")) -> dict:
    repo_root = repo_root.resolve()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    os.environ.setdefault("SECRET_KEY", "showcase_test_secret_key")
    os.environ.setdefault("DEBUG", "1")
    os.environ.setdefault("TEST", "1")

    import django

    django.setup()

    migration_files = [
        f for f in repo_root.glob("**/migrations/*.py") if "site-packages" not in str(f) and ".venv" not in str(f)
    ]

    raw_imports = {}

    for mf in sorted(migration_files):
        rel_path = str(mf.relative_to(repo_root))
        try:
            content = mf.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=rel_path)
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("posthog") or mod.startswith("products") or mod.startswith("ee"):
                    if "migrations" in mod:
                        continue
                    for alias in node.names:
                        sym = alias.name
                        raw_imports.setdefault(mod, {}).setdefault(sym, set()).add(rel_path)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if (name.startswith("posthog") or name.startswith("products") or name.startswith("ee")) and "migrations" not in name:
                        raw_imports.setdefault(name, {}).setdefault("*", set()).add(rel_path)

    contract = {}

    for mod_name in sorted(raw_imports.keys()):
        syms = raw_imports[mod_name]
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            print(f"Warning: unable to import module {mod_name}: {e}", file=sys.stderr)
            continue

        contract[mod_name] = {}
        for sym_name in sorted(syms.keys()):
            entry = {"files": sorted(syms[sym_name])}
            if sym_name == "*":
                entry["kind"] = "module"
            elif hasattr(mod, sym_name):
                target = getattr(mod, sym_name)
                if inspect.isfunction(target):
                    entry["kind"] = "function"
                    try:
                        sig = inspect.signature(target)
                        entry["params"] = list(sig.parameters.keys())
                        entry["bytecode_hash"] = hashlib.sha256(target.__code__.co_code).hexdigest()
                    except Exception:
                        pass
                elif inspect.isclass(target):
                    entry["kind"] = "class"
                elif inspect.ismodule(target):
                    entry["kind"] = "module"
                else:
                    entry["kind"] = "constant"
            else:
                entry["kind"] = "missing"
            contract[mod_name][sym_name] = entry

    return contract


def main():
    repo_root = Path(__file__).resolve().parent.parent.parent
    contract = generate_migration_contract(repo_root)
    output_path = repo_root / "showcase" / "contracts" / "migration_contract.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    num_symbols = sum(len(syms) for syms in contract.values())
    print(f"✓ Successfully generated {output_path} with {len(contract)} modules and {num_symbols} symbols.")


if __name__ == "__main__":
    main()
