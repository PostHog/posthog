"""Product modules that outside suites run without an import edge.

An Isolated product skips the full Django suite when a change touches only files outside its
`backend:contract-check` inputs (products/architecture.md § What makes the skip sound). tach and
import-linter prove that no outside code imports past the facade. These channels run a product module
in an outside suite with no import, so those checks cannot see them:

- A signal receiver on a sender the product does not own. It runs inside the save and delete paths
  of every suite that writes the sender.
- A test outside the product that names a product module by its dotted path, which is how a patch
  target is written. The test depends on the names in that module and runs the code around them.
- A module that core loads by name through `load_product_modules(...)`, such as
  `integration_usages` or `data_freshness`. Core imports it for every product that has one.
- `backend/apps.py` and the product modules it imports. Django runs the AppConfig in every process,
  and a callback that ready() registers runs wherever its hook fires.
- A module that registers into another boundary's `register_*` hook, and the module that defines
  what it registers. The hook owner calls it in its own suites.
- A module that core settings name by dotted path, such as a middleware. It runs on every request.

This module finds the module files each channel reaches. It reads source and never imports it.
isolation.py accepts these files as contract-check inputs, and the lint fails while one is unwatched.
"""

from __future__ import annotations

import re
import ast
import functools
from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from posthog.dataclasses import frozen

from .ast_helpers import ast_parse_safe, decorator_name, import_from_module, product_app_labels
from .paths import FIRST_PARTY_ROOTS

_SKIPPED_DIRS: frozenset[str] = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"})

# Matches the string literal, not the patch call, so a `MODULE = "products.x.backend.mod"` constant
# that an f-string extends later counts too. A long target split by implicit concatenation
# ("products.x.backend.a." "b.name") puts a quote break next to a dot.
_QUOTE_BREAK = rb"""(?:["']\s*["'])?"""
_PRODUCT_MODULE_STRING_RE = re.compile(
    rb"""["']products\.([A-Za-z0-9_]+)\.(backend(?:""" + _QUOTE_BREAK + rb"\." + _QUOTE_BREAK + rb"[A-Za-z0-9_]+)+)"
)
_QUOTES_AND_SPACE_RE = re.compile(rb"""["'\s]""")

_ARCHITECTURE_SECTION = "products/architecture.md § What makes the skip sound"


class ChannelKind(StrEnum):
    FOREIGN_RECEIVER = "foreign-receiver"
    OUTSIDE_TEST = "outside-test"
    DISCOVERED_BY_NAME = "discovered-by-name"
    APP_SETUP = "app-setup"
    HOOK_CALLBACK = "hook-callback"
    SETTINGS_PATH = "settings-path"


@frozen
class ChannelModule:
    """A product module file that an outside suite runs without an import edge."""

    path: str  # relative to the product directory, e.g. "backend/apps.py"
    kind: ChannelKind
    source: str  # the foreign sender or hook as the source spells it, or the repo path that names the module


@frozen
class _NamedModule:
    product: str
    path: str
    named_by: str  # repo path of the file that names the module


@frozen
class _ModuleNames:
    """What the names in one scanned module refer to."""

    module: str
    imported: Mapping[str, str]  # each imported name and the qualified name it refers to
    defined: frozenset[str]


def _is_test_path(parts: Sequence[str]) -> bool:
    name = parts[-1]
    if "test" in parts or "tests" in parts:
        return True
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _module_file(root: Path, parts: Sequence[str]) -> str | None:
    """The longest prefix of a dotted path that names a module file under `root`.

    ['backend', 'delivery', 'email', 'send'] -> 'backend/delivery/email.py' when that file exists.
    A package resolves to its __init__.py."""
    for end in range(len(parts), 0, -1):
        stem = "/".join(parts[:end])
        if (root / f"{stem}.py").is_file():
            return f"{stem}.py"
        if (root / stem / "__init__.py").is_file():
            return f"{stem}/__init__.py"
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


# ---------------------------------------------------------------------------
# Channel 1: receivers on a sender the product does not own
# ---------------------------------------------------------------------------


@functools.cache
def _app_labels(products_dir: Path) -> Mapping[str, str]:
    return product_app_labels(products_dir)


def _module_names(tree: ast.Module, module: str, is_package: bool) -> _ModuleNames:
    """Read every import in the module, function-local ones too, because an AppConfig.ready()
    imports its receivers and senders inside the method."""
    package = module if is_package else module.rpartition(".")[0]
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imported[alias.asname] = alias.name
                else:
                    root = alias.name.partition(".")[0]
                    imported[root] = root
        elif isinstance(node, ast.ImportFrom):
            source = import_from_module(node, package)
            if source is None:
                continue
            for alias in node.names:
                imported[alias.asname or alias.name] = f"{source}.{alias.name}"
    defined = frozenset(
        node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return _ModuleNames(module=module, imported=imported, defined=defined)


def _qualified_name(node: ast.expr, names: _ModuleNames) -> str | None:
    """The qualified name an expression refers to, or None when the source does not name it
    statically (a loop variable, a call, a subscript)."""
    dotted = _dotted_name(node)
    if dotted is None:
        return None
    root, _, rest = dotted.partition(".")
    if root in names.defined:
        base = f"{names.module}.{root}"
    elif root in names.imported:
        base = names.imported[root]
    else:
        return None
    return f"{base}.{rest}" if rest else base


def _sender_is_own(sender: ast.expr, product: str, names: _ModuleNames, products_dir: Path) -> bool:
    """Whether the sender is a model of the product itself.

    Fails closed: a sender the source does not name statically counts as foreign. A string sender
    is an "app_label.Model" reference, so its owner is the product whose AppConfig declares that
    label. settings.AUTH_USER_MODEL and get_user_model() resolve to core, so they are foreign too."""
    if isinstance(sender, ast.Constant) and isinstance(sender.value, str):
        label = sender.value.partition(".")[0]
        return _app_labels(products_dir).get(label) == product
    qualified = _qualified_name(sender, names)
    return qualified is not None and qualified.startswith(f"products.{product}.")


def _receiver_sites(tree: ast.Module) -> Iterator[tuple[ast.expr, ast.expr | None]]:
    """(sender, receiver function) for every receiver connected with a sender.

    The function is None for `@receiver(...)`, because the decorated function sits in the scanned
    module itself. For `signal.connect(fn, sender=X)` it is the expression that names `fn`."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = decorator_name(node)
        if name not in ("receiver", "connect"):
            continue
        sender = _keyword(node, "sender")
        if sender is None:
            continue
        if name == "receiver":
            yield sender, None
            continue
        function = node.args[0] if node.args else _keyword(node, "receiver")
        yield sender, function


def _module_source(repo_root: Path, qualified: str) -> tuple[Path, str] | None:
    """The file that defines a qualified function name, and the function's name."""
    module, _, function = qualified.rpartition(".")
    stem = repo_root / module.replace(".", "/")
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate, function
    return None


@functools.cache
def _forwards_to_connect(path: Path, function: str) -> bool:
    """Whether a top-level function passes its first parameter on to a `.connect(...)` call.

    A product exposes a signal on its own model through such a hook (`connect_task_run_post_save`)
    so that consumers never name the sender. The receiver still runs in the sender's save path."""
    tree = ast_parse_safe(path)
    if tree is None:
        return False
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != function:
            continue
        params = [*node.args.posonlyargs, *node.args.args]
        if not params:
            return False
        first = params[0].arg
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            if call.func.attr != "connect":
                continue
            target = call.args[0] if call.args else _keyword(call, "receiver")
            if isinstance(target, ast.Name) and target.id == first:
                return True
    return False


def _hook_sites(
    tree: ast.Module, product: str, names: _ModuleNames, repo_root: Path
) -> Iterator[tuple[str, ast.expr | None]]:
    """(hook name, receiver function) for every call to another boundary's signal hook."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified_name(node.func, names)
        if qualified is None or qualified.startswith(f"products.{product}."):
            continue
        source = _module_source(repo_root, qualified)
        if source is None or not _forwards_to_connect(*source):
            continue
        yield qualified, node.args[0] if node.args else _keyword(node, "receiver")


def _function_module(function: ast.expr, product_dir: Path, names: _ModuleNames) -> str | None:
    """The product module file that defines a connected receiver function, when the source names it."""
    prefix = f"products.{product_dir.name}."
    qualified = _qualified_name(function, names)
    if qualified is None or not qualified.startswith(prefix):
        return None
    return _module_file(product_dir, qualified.removeprefix(prefix).split("."))


def _iter_backend_modules(product_dir: Path) -> Iterator[tuple[str, Path]]:
    """(product-relative path, file) for every non-test, non-migration module under backend/."""
    for path in sorted((product_dir / "backend").rglob("*.py")):
        parts = path.relative_to(product_dir).parts
        if _is_test_path(parts) or "migrations" in parts or _SKIPPED_DIRS.intersection(parts):
            continue
        yield "/".join(parts), path


@frozen
class _ParsedModule:
    rel_path: str
    tree: ast.Module
    names: _ModuleNames


def _parsed_backend_modules(product_dir: Path, needles: Sequence[bytes]) -> Iterator[_ParsedModule]:
    """Parse the backend modules whose source holds one of the needles. The byte test skips the
    parse for the many modules that cannot match."""
    for rel_path, path in _iter_backend_modules(product_dir):
        source = path.read_bytes()
        if not any(needle in source for needle in needles):
            continue
        tree = ast_parse_safe(path)
        if tree is None:
            continue
        module_parts = ["products", product_dir.name, *rel_path.removesuffix(".py").split("/")]
        is_package = module_parts[-1] == "__init__"
        if is_package:
            module_parts.pop()
        yield _ParsedModule(rel_path=rel_path, tree=tree, names=_module_names(tree, ".".join(module_parts), is_package))


def foreign_receiver_modules(product_dir: Path) -> list[ChannelModule]:
    """The modules of a product that connect a receiver on a foreign sender, and the modules that
    define those receiver functions. Both run inside the sender's save and delete paths.

    A receiver connects either with `sender=` or through another boundary's signal hook."""
    product = product_dir.name
    repo_root = product_dir.parent.parent
    found: list[ChannelModule] = []
    for parsed in _parsed_backend_modules(product_dir, (b"sender", b"connect")):
        rel_path, tree, names = parsed.rel_path, parsed.tree, parsed.names
        sites: list[tuple[str, ast.expr | None]] = [
            (ast.unparse(sender), function)
            for sender, function in _receiver_sites(tree)
            if not _sender_is_own(sender, product, names, product_dir.parent)
        ]
        sites += _hook_sites(tree, product, names, repo_root)
        for spelled, function in sites:
            found.append(ChannelModule(path=rel_path, kind=ChannelKind.FOREIGN_RECEIVER, source=spelled))
            function_module = _function_module(function, product_dir, names) if function is not None else None
            if function_module is not None and function_module != rel_path:
                found.append(ChannelModule(path=function_module, kind=ChannelKind.FOREIGN_RECEIVER, source=spelled))
    return found


# ---------------------------------------------------------------------------
# Channel 2: product modules that tests outside the product name by dotted path
# ---------------------------------------------------------------------------


def _iter_test_files(repo_root: Path) -> Iterator[tuple[tuple[str, ...], Path]]:
    for root in FIRST_PARTY_ROOTS:
        top = repo_root / root
        if not top.is_dir():
            continue
        for directory, dirnames, filenames in top.walk():
            dirnames[:] = [d for d in dirnames if d not in _SKIPPED_DIRS]
            directory_parts = directory.relative_to(repo_root).parts
            for filename in filenames:
                parts = (*directory_parts, filename)
                if filename.endswith(".py") and _is_test_path(parts):
                    yield parts, directory / filename


@functools.cache
def _outside_test_names(repo_root: Path) -> tuple[_NamedModule, ...]:
    """Every product module that a test outside that product names by dotted path.

    Scans the whole repository once per process, because product:lint asks for every product.
    Reads bytes with one regular expression and parses no file, so the scan stays cheap."""
    found: set[_NamedModule] = set()
    for parts, path in _iter_test_files(repo_root):
        for match in _PRODUCT_MODULE_STRING_RE.finditer(path.read_bytes()):
            product = match.group(1).decode()
            if parts[:2] == ("products", product):
                continue
            dotted = _QUOTES_AND_SPACE_RE.sub(b"", match.group(2)).decode()
            module = _module_file(repo_root / "products" / product, dotted.split("."))
            if module is not None:
                found.add(_NamedModule(product=product, path=module, named_by="/".join(parts)))
    return tuple(found)


def outside_named_modules(product: str, repo_root: Path) -> list[ChannelModule]:
    return [
        ChannelModule(path=named.path, kind=ChannelKind.OUTSIDE_TEST, source=named.named_by)
        for named in _outside_test_names(repo_root)
        if named.product == product
    ]


# ---------------------------------------------------------------------------
# Channel 3: product modules that core loads by name
# ---------------------------------------------------------------------------

_LOADER = "load_product_modules"
UNRESOLVED_SUBMODULE_PREFIX = "<unresolved load_product_modules name at "


@frozen
class _LoadedName:
    submodule: str | None  # None when the call passes a name the scan cannot read
    caller: str  # repo path and line of the load_product_modules call


def _module_string_constants(tree: ast.Module) -> Mapping[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _loaded_submodule(argument: ast.expr, constants: Mapping[str, str]) -> str | None:
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    if isinstance(argument, ast.Name):
        return constants.get(argument.id)
    return None


def _iter_source_files(repo_root: Path) -> Iterator[tuple[tuple[str, ...], Path]]:
    for root in FIRST_PARTY_ROOTS:
        top = repo_root / root
        if not top.is_dir():
            continue
        for directory, dirnames, filenames in top.walk():
            dirnames[:] = [d for d in dirnames if d not in _SKIPPED_DIRS]
            directory_parts = directory.relative_to(repo_root).parts
            for filename in filenames:
                parts = (*directory_parts, filename)
                if filename.endswith(".py") and not _is_test_path(parts):
                    yield parts, directory / filename


@functools.cache
def _loaded_names(repo_root: Path) -> tuple[_LoadedName, ...]:
    """Every submodule name that production code passes to load_product_modules.

    core imports `<product app>.<name>` for every product that has one, so no import edge names
    the product module. Scans the repository once per process."""
    found: set[_LoadedName] = set()
    loader = _LOADER.encode()
    for parts, path in _iter_source_files(repo_root):
        if loader not in path.read_bytes():
            continue
        tree = ast_parse_safe(path)
        if tree is None:
            continue
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and decorator_name(node) == _LOADER and node.args):
                continue
            caller = f"{'/'.join(parts)}:{node.lineno}"
            found.add(_LoadedName(submodule=_loaded_submodule(node.args[0], constants), caller=caller))
    return tuple(sorted(found, key=lambda n: n.caller))


def _exact_module_file(root: Path, parts: Sequence[str]) -> str | None:
    """The module file for exactly this dotted path under `root`, or None. Unlike _module_file it
    never falls back to a parent package: load_product_modules skips a product without the module."""
    stem = "/".join(parts)
    if (root / f"{stem}.py").is_file():
        return f"{stem}.py"
    if (root / stem / "__init__.py").is_file():
        return f"{stem}/__init__.py"
    return None


def discovered_modules(product_dir: Path, repo_root: Path) -> list[ChannelModule]:
    """The product modules core loads by name. A name the scan cannot read fails closed: it
    becomes a placeholder module that no input can watch, so the lint asks for a readable name."""
    found: list[ChannelModule] = []
    for loaded in _loaded_names(repo_root):
        if loaded.submodule is None:
            path = f"{UNRESOLVED_SUBMODULE_PREFIX}{loaded.caller}>"
            found.append(ChannelModule(path=path, kind=ChannelKind.DISCOVERED_BY_NAME, source=loaded.caller))
            continue
        module = _exact_module_file(product_dir, ["backend", *loaded.submodule.split(".")])
        if module is not None:
            found.append(ChannelModule(path=module, kind=ChannelKind.DISCOVERED_BY_NAME, source=loaded.caller))
    return found


# ---------------------------------------------------------------------------
# Channel 4: the AppConfig module and the product modules it imports
# ---------------------------------------------------------------------------

_APPS_MODULE = "backend/apps.py"


def _is_type_checking_block(node: ast.AST) -> bool:
    return isinstance(node, ast.If) and _dotted_name(node.test) in ("TYPE_CHECKING", "typing.TYPE_CHECKING")


def _runtime_imports(nodes: Iterable[ast.AST]) -> Iterator[ast.Import | ast.ImportFrom]:
    """Every import that can run, function-local ones too. An `if TYPE_CHECKING:` body never runs."""
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif _is_type_checking_block(node):
            yield from _runtime_imports(node.orelse)
        else:
            yield from _runtime_imports(ast.iter_child_nodes(node))


def _imported_product_modules(tree: ast.Module, product_dir: Path, package: str) -> set[str]:
    prefix = f"products.{product_dir.name}."
    found: set[str] = set()
    for node in _runtime_imports(tree.body):
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        else:
            source = import_from_module(node, package)
            if source is None:
                continue
            targets = [f"{source}.{alias.name}" for alias in node.names]
        for target in targets:
            if not target.startswith(prefix):
                continue
            module = _module_file(product_dir, target.removeprefix(prefix).split("."))
            if module is not None:
                found.add(module)
    return found


def app_setup_modules(product_dir: Path) -> list[ChannelModule]:
    """backend/apps.py and every product module it imports.

    Django imports the AppConfig and runs ready() in every process, so every suite runs this code.
    An import inside a callback that ready() registers counts too, because the callback runs that
    module wherever the hook fires."""
    path = product_dir / _APPS_MODULE
    if not path.is_file():
        return []
    found = [ChannelModule(path=_APPS_MODULE, kind=ChannelKind.APP_SETUP, source=_APPS_MODULE)]
    tree = ast_parse_safe(path)
    if tree is None:
        return found
    package = f"products.{product_dir.name}.backend"
    for module in sorted(_imported_product_modules(tree, product_dir, package) - {_APPS_MODULE}):
        found.append(ChannelModule(path=module, kind=ChannelKind.APP_SETUP, source=_APPS_MODULE))
    return found


# ---------------------------------------------------------------------------
# Channel 5: registrations into another boundary's hook
# ---------------------------------------------------------------------------

_HOOK_PREFIX = "register_"
_FIRST_PARTY_PREFIXES: tuple[str, ...] = tuple(f"{root}." for root in FIRST_PARTY_ROOTS)


def _foreign_hook_calls(tree: ast.Module, product: str, names: _ModuleNames) -> Iterator[tuple[str, list[ast.expr]]]:
    """(hook, arguments) for every call to a `register_*` function that core or another product owns."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified_name(node.func, names)
        if qualified is None or not qualified.startswith(_FIRST_PARTY_PREFIXES):
            continue
        if qualified.startswith(f"products.{product}."):
            continue
        if not qualified.rpartition(".")[2].startswith(_HOOK_PREFIX):
            continue
        yield qualified, [*node.args, *(keyword.value for keyword in node.keywords)]


def hook_callback_modules(product_dir: Path) -> list[ChannelModule]:
    """The modules of a product that register into another boundary's hook, and the modules that
    define what they register. The hook owner calls the registered code in its own suites."""
    found: list[ChannelModule] = []
    for parsed in _parsed_backend_modules(product_dir, (_HOOK_PREFIX.encode(),)):
        for hook, arguments in _foreign_hook_calls(parsed.tree, product_dir.name, parsed.names):
            found.append(ChannelModule(path=parsed.rel_path, kind=ChannelKind.HOOK_CALLBACK, source=hook))
            for argument in arguments:
                module = _function_module(argument, product_dir, parsed.names)
                if module is not None and module != parsed.rel_path:
                    found.append(ChannelModule(path=module, kind=ChannelKind.HOOK_CALLBACK, source=hook))
    return found


# ---------------------------------------------------------------------------
# Channel 6: product modules that core settings name by dotted path
# ---------------------------------------------------------------------------

_SETTINGS_DIR = "posthog/settings"


@functools.cache
def _settings_names(repo_root: Path) -> tuple[_NamedModule, ...]:
    """Every product module a settings file names, such as a middleware in MIDDLEWARE."""
    found: set[_NamedModule] = set()
    for path in sorted((repo_root / _SETTINGS_DIR).rglob("*.py")):
        named_by = path.relative_to(repo_root).as_posix()
        for match in _PRODUCT_MODULE_STRING_RE.finditer(path.read_bytes()):
            product = match.group(1).decode()
            dotted = _QUOTES_AND_SPACE_RE.sub(b"", match.group(2)).decode()
            module = _module_file(repo_root / "products" / product, dotted.split("."))
            if module is not None:
                found.add(_NamedModule(product=product, path=module, named_by=named_by))
    return tuple(found)


def settings_named_modules(product: str, repo_root: Path) -> list[ChannelModule]:
    return [
        ChannelModule(path=named.path, kind=ChannelKind.SETTINGS_PATH, source=named.named_by)
        for named in _settings_names(repo_root)
        if named.product == product
    ]


def find_channel_modules(product_dir: Path, repo_root: Path) -> tuple[ChannelModule, ...]:
    found = (
        set(foreign_receiver_modules(product_dir))
        | set(outside_named_modules(product_dir.name, repo_root))
        | set(discovered_modules(product_dir, repo_root))
        | set(app_setup_modules(product_dir))
        | set(hook_callback_modules(product_dir))
        | set(settings_named_modules(product_dir.name, repo_root))
    )
    return tuple(sorted(found, key=lambda c: (c.path, c.kind, c.source)))


def _first_few(values: Sequence[str], limit: int = 3) -> str:
    shown = ", ".join(values[:limit])
    rest = len(values) - limit
    return f"{shown} and {rest} more" if rest > 0 else shown


def unwatched_channel_issue(path: str, channels: Sequence[ChannelModule]) -> str:
    """The lint issue for one module file the contract-check inputs do not watch."""
    if path.startswith(UNRESOLVED_SUBMODULE_PREFIX):
        return (
            f"{channels[0].source} passes load_product_modules a name the lint cannot read, so it cannot tell "
            "which product modules core loads. Pass a string literal or a module-level string constant "
            f"({_ARCHITECTURE_SECTION})"
        )
    senders = sorted({c.source for c in channels if c.kind is ChannelKind.FOREIGN_RECEIVER})
    tests = sorted({c.source for c in channels if c.kind is ChannelKind.OUTSIDE_TEST})
    loaders = sorted({c.source for c in channels if c.kind is ChannelKind.DISCOVERED_BY_NAME})
    app_setup = any(c.kind is ChannelKind.APP_SETUP for c in channels)
    hooks = sorted({c.source for c in channels if c.kind is ChannelKind.HOOK_CALLBACK})
    settings_files = sorted({c.source for c in channels if c.kind is ChannelKind.SETTINGS_PATH})
    reasons: list[str] = []
    moves: list[str] = []
    if senders:
        reasons.append(f"it holds a receiver on a sender the product does not own ({_first_few(senders)})")
        moves.append("flip the receiver direction")
    if tests:
        reasons.append(f"tests outside the product name it by dotted path, as patch targets do ({_first_few(tests)})")
        moves.append("move the test into the owning product")
    if loaders:
        reasons.append(f"core loads it by name through load_product_modules ({_first_few(loaders)})")
    if app_setup:
        reasons.append("Django runs it at setup in every process, as backend/apps.py or a module it imports")
    if hooks:
        reasons.append(f"it registers into a hook of core or another product, or is registered ({_first_few(hooks)})")
    if settings_files:
        reasons.append(f"core settings name it by dotted path ({_first_few(settings_files)})")
    remedy = f" or {' and '.join(moves)}" if moves else ""
    return (
        f"{path} runs in other suites without an import edge: {'; '.join(reasons)}. The "
        "backend:contract-check inputs do not watch it, so a change to it skips those suites. "
        f'Add "{path}" to the inputs in turbo.json{remedy} ({_ARCHITECTURE_SECTION})'
    )
