"""Derive Django-semantic dependency edges from runtime introspection.

Snob builds its dependency graph from Python imports. A Django project also wires
components together through framework conventions that no import expresses: URL
routing resolves a request path to a view, `AppConfig.ready()` connects signal
receivers to sender models, and `_meta` holds the relation metadata the ORM acts on.
A test that drives a view over HTTP, or a model save that fires a receiver in another
app, therefore has a real dependency with no import edge behind it.

This module asks Django itself for those relationships after `django.setup()` and
writes them out as edges between repository files.
`tools/snob_backend_test_selection_shadow.py` reads the output with `--django-edges`.

Three extractors, each deterministic:

`urls`     Walks the URL resolver, then resolves the URL literals found in test files
           against that same resolver. Produces view file -> test file edges.
`signals`  Reads the receiver list of every connected `Signal`, resolving senders to
           model files and receivers to their own files. Produces sender file <->
           receiver file edges.
`models`   Reads `_meta.get_fields()` for relation targets. Produces model file ->
           related model file edges.

`urls` costs far more than the other two, because forcing the URL conf imports every
view module and each literal is resolved against the whole pattern list.

Usage:
    python tools/django_edges/extract.py --out django_edges.json
    python tools/django_edges/extract.py --out fixture_edges.json \
        --root tools/django_edges/fixture --settings settings --source-roots .
"""

from __future__ import annotations

import os
import ast
import sys
import json
import time
import inspect
import weakref
import argparse
import warnings
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.urls.resolvers import URLResolver

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from posthog.dataclasses import frozen  # noqa: E402

DEFAULT_SOURCE_ROOTS = ("posthog", "ee", "products", "common", "dags")
EXTRACTOR_NAMES = ("signals", "models", "urls")

# Values substituted for f-string interpolations in a test's URL literal. The resolver
# only needs a path that matches a route regex, so any value that fits the usual
# converters will do; the hint is the trailing attribute or variable name.
PLACEHOLDER_BY_HINT = {
    "team": "1",
    "team_id": "1",
    "project": "1",
    "project_id": "1",
    "organization": "018eb2c4-0000-0000-0000-000000000000",
    "organization_id": "018eb2c4-0000-0000-0000-000000000000",
    "id": "1",
    "pk": "1",
    "uuid": "018eb2c4-0000-0000-0000-000000000000",
}
DEFAULT_PLACEHOLDER = "1"

SAMPLE_SIZE = 40

CATCH_ALL_PROBES = (
    "/api/snob-probe-no-such-route/",
    "/api/projects/1/snob-probe-no-such-route/",
    "/snob-probe-no-such-route/",
)


@frozen
class UrlEdges:
    """Production files reached by test files through URL dispatch."""

    view_file_to_tests: dict[str, list[str]]
    route_count: int
    resolved_literals: int
    unresolved_literals: list[str]
    catch_all_literals: list[str]
    resolver_seconds: float
    test_scan_seconds: float


@frozen
class SignalEdges:
    """Sender model files and receiver files, in both directions."""

    neighbors: dict[str, list[str]]
    signal_count: int
    receiver_count: int
    pair_count: int
    global_receiver_files: list[str]
    seconds: float


@frozen
class ModelEdges:
    """Model files and the files of the models they have relations to."""

    neighbors: dict[str, list[str]]
    model_count: int
    relation_count: int
    seconds: float


@frozen
class DjangoEdges:
    """Everything one introspection run found, plus what it cost."""

    setup_seconds: float
    urls: UrlEdges | None = None
    signals: SignalEdges | None = None
    models: ModelEdges | None = None

    def as_json(self) -> dict[str, Any]:
        """The shape the selector reads: three edge maps, plus stats for the write-up."""
        return {
            "view_file_to_tests": self.urls.view_file_to_tests if self.urls else {},
            "signal_neighbors": self.signals.neighbors if self.signals else {},
            "model_neighbors": self.models.neighbors if self.models else {},
            "stats": {
                "setup_seconds": round(self.setup_seconds, 2),
                # The literal lists are diagnostics, not edges, so keep a sample rather
                # than thousands of strings in every artifact.
                "urls": asdict(self.urls)
                | {
                    "view_file_to_tests": None,
                    "unresolved_literals": self.urls.unresolved_literals[:SAMPLE_SIZE],
                    "unresolved_literal_count": len(self.urls.unresolved_literals),
                    "catch_all_literals": self.urls.catch_all_literals[:SAMPLE_SIZE],
                    "catch_all_literal_count": len(self.urls.catch_all_literals),
                }
                if self.urls
                else None,
                "signals": asdict(self.signals) | {"neighbors": None} if self.signals else None,
                "models": asdict(self.models) | {"neighbors": None} if self.models else None,
                "total_seconds": round(self.total_seconds(), 2),
            },
        }

    def total_seconds(self) -> float:
        parts = [self.setup_seconds]
        if self.urls:
            parts += [self.urls.resolver_seconds, self.urls.test_scan_seconds]
        if self.signals:
            parts.append(self.signals.seconds)
        if self.models:
            parts.append(self.models.seconds)
        return sum(parts)


class DjangoEdgeExtractor:
    """Reads Django's own metadata for dependency edges between repository files.

    `root` is the directory paths are reported relative to, and `source_roots` are the
    top-level directories inside it whose files count as project code — an object
    defined in site-packages produces no edge.
    """

    def __init__(self, root: Path, source_roots: tuple[str, ...]) -> None:
        self.root = root.resolve()
        self.source_roots = source_roots

    def repo_relative(self, path: str | None) -> str | None:
        if not path:
            return None
        try:
            relative = Path(path).resolve().relative_to(self.root)
        except (ValueError, OSError):
            return None
        if "." in self.source_roots or (relative.parts and relative.parts[0] in self.source_roots):
            return str(PurePosixPath(relative))
        return None

    def file_of(self, obj: Any) -> str | None:
        try:
            return self.repo_relative(inspect.getfile(obj))
        except (TypeError, OSError):
            module = sys.modules.get(getattr(obj, "__module__", "") or "")
            return self.repo_relative(getattr(module, "__file__", None))

    def _python_files(self, pattern: str) -> list[str]:
        files: set[str] = set()
        for source_root in self.source_roots:
            base = self.root / source_root
            if not base.exists():
                continue
            for path in base.rglob(pattern):
                if "__pycache__" not in path.parts:
                    files.add(str(path.relative_to(self.root)))
        return sorted(files)

    def test_files(self) -> list[str]:
        return self._python_files("test_*.py")

    def parse(self, path: str) -> ast.AST | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                return ast.parse((self.root / path).read_text(), filename=path)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return None

    def _iter_patterns(self, resolver: URLResolver, urlconf_file: str | None = None) -> Any:
        """Every route in the tree, with the file of the URLconf that declares it.

        The declaring file matters on its own: a product registers its routes in
        `routes.py`, and editing that file changes which view serves a path without
        touching either the view or any test.
        """
        from django.urls.resolvers import (
            URLPattern,
            URLResolver as Nested,
        )

        owner = self._urlconf_file(resolver) or urlconf_file
        for pattern in resolver.url_patterns:
            if isinstance(pattern, Nested):
                yield from self._iter_patterns(pattern, owner)
            elif isinstance(pattern, URLPattern):
                yield pattern, owner

    def _urlconf_file(self, resolver: URLResolver) -> str | None:
        module = getattr(resolver, "urlconf_module", None)
        if module is None or isinstance(module, list):
            # A router's `.urls` is a plain list, so the declaring file is the parent's.
            return None
        return self.repo_relative(getattr(module, "__file__", None))

    def view_files(self, callback: Any) -> set[str]:
        """Files that define the view behind a route.

        A DRF router builds its callbacks with `as_view()`, so the interesting file is
        the one holding the class, not the generated closure. Both `cls` (DRF) and
        `view_class` (Django's own class-based views) point back at it.
        """
        files: set[str] = set()
        view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
        for candidate in (view_class, callback):
            if candidate is None:
                continue
            file = self.file_of(candidate)
            if file:
                files.add(file)
        return files

    def url_literals(self, tree: ast.AST) -> set[str]:
        """URL paths a test file names, with f-string interpolations filled in.

        A test writes `f"/api/projects/{self.team.id}/insights/"`, and the resolver
        needs a concrete path, so each interpolation becomes a placeholder picked from
        the interpolated expression's name.
        """

        def placeholder_for(node: ast.expr) -> str:
            name = ""
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            return PLACEHOLDER_BY_HINT.get(name.lower(), DEFAULT_PLACEHOLDER)

        candidates: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if self._looks_like_url(node.value):
                    candidates.add(node.value)
            elif isinstance(node, ast.JoinedStr):
                parts: list[str] = []
                for value in node.values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        parts.append(value.value)
                    elif isinstance(value, ast.FormattedValue):
                        parts.append(placeholder_for(value.value))
                joined = "".join(parts)
                if self._looks_like_url(joined):
                    candidates.add(joined)
        return candidates

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        """A literal worth handing to the resolver.

        Tests are full of strings that start with a slash and are not request paths —
        regexes, file paths, protocol-relative URLs in security fixtures. They all
        land on the catch-all view, so filtering them here only saves resolver work.
        """
        return (
            value.startswith("/")
            and not value.startswith("//")
            and " " not in value
            and "\n" not in value
            and any(character.isalpha() for character in value)
        )

    @staticmethod
    def reverse_names(tree: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            if called != "reverse" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
        return names

    @staticmethod
    def _resolve_variants(url: str) -> list[str]:
        cleaned = url.split("?", 1)[0].split("#", 1)[0]
        if not cleaned.startswith("/"):
            cleaned = "/" + cleaned
        if cleaned.endswith("/"):
            return [cleaned, cleaned.rstrip("/")]
        return [cleaned, cleaned + "/"]

    def _catch_all_callbacks(self, resolver: URLResolver) -> set[int]:
        """Views that answer any unmatched path.

        A project with an API 404 handler and a single-page-app fallback resolves every
        probe path, so without this every unroutable literal in a test would look like
        an edge to whichever module holds the fallback.
        """
        from django.urls.exceptions import Resolver404

        callbacks: set[int] = set()
        for probe in CATCH_ALL_PROBES:
            try:
                match = resolver.resolve(probe)
            except Resolver404:
                continue
            callbacks.add(id(match.func))
        return callbacks

    def extract_urls(self) -> UrlEdges:
        from django.urls import get_resolver, reverse
        from django.urls.exceptions import NoReverseMatch, Resolver404

        started = time.time()
        resolver = get_resolver()
        urlconf_by_callback: dict[int, set[str]] = defaultdict(set)
        route_count = 0
        for pattern, urlconf_file in self._iter_patterns(resolver):
            route_count += 1
            if urlconf_file:
                urlconf_by_callback[id(pattern.callback)].add(urlconf_file)
        catch_all = self._catch_all_callbacks(resolver)
        resolver_seconds = time.time() - started

        started = time.time()
        view_to_tests: dict[str, set[str]] = defaultdict(set)
        unresolved: set[str] = set()
        caught: set[str] = set()
        resolved = 0
        resolution_cache: dict[str, Any] = {}

        def resolve_once(url: str) -> Any:
            if url in resolution_cache:
                return resolution_cache[url]
            match = None
            for variant in self._resolve_variants(url):
                try:
                    match = resolver.resolve(variant)
                    break
                except Resolver404:
                    continue
            resolution_cache[url] = match
            return match

        for test_path in self.test_files():
            tree = self.parse(test_path)
            if tree is None:
                continue
            urls = self.url_literals(tree)
            for name in self.reverse_names(tree):
                try:
                    urls.add(reverse(name))
                except (NoReverseMatch, ValueError):
                    continue
            for url in urls:
                match = resolve_once(url)
                if match is None:
                    unresolved.add(url)
                    continue
                if id(match.func) in catch_all:
                    caught.add(url)
                    continue
                resolved += 1
                for file in self.view_files(match.func) | urlconf_by_callback.get(id(match.func), set()):
                    view_to_tests[file].add(test_path)

        return UrlEdges(
            view_file_to_tests={view: sorted(tests) for view, tests in sorted(view_to_tests.items())},
            route_count=route_count,
            resolved_literals=resolved,
            unresolved_literals=sorted(unresolved),
            catch_all_literals=sorted(caught),
            resolver_seconds=round(resolver_seconds, 2),
            test_scan_seconds=round(time.time() - started, 2),
        )

    def extract_signals(self) -> SignalEdges:
        from django.apps import apps
        from django.dispatch import Signal

        started = time.time()
        models_by_id = {id(model): model for model in apps.get_models(include_auto_created=True)}

        signals_by_id: dict[int, Signal] = {}
        for module in list(sys.modules.values()):
            try:
                members = vars(module)
            except TypeError:
                # A module entry can be None, which `vars` rejects.
                continue
            for value in list(members.values()):
                if isinstance(value, Signal):
                    signals_by_id.setdefault(id(value), value)

        neighbors: dict[str, set[str]] = defaultdict(set)
        pair_count = 0
        receiver_count = 0
        global_receiver_files: set[str] = set()
        for signal in signals_by_id.values():
            for entry in list(signal.receivers):
                lookup_key, receiver = entry[0], entry[1]
                resolved = receiver() if isinstance(receiver, weakref.ReferenceType) else receiver
                if resolved is None:
                    continue
                receiver_count += 1
                receiver_file = self.file_of(resolved)
                if receiver_file is None:
                    continue
                sender = models_by_id.get(lookup_key[1])
                if sender is None:
                    # A receiver connected without a sender runs for every model, so
                    # there is no one file to draw an edge to.
                    global_receiver_files.add(receiver_file)
                    continue
                sender_file = self.file_of(sender)
                if sender_file is None or sender_file == receiver_file:
                    continue
                neighbors[sender_file].add(receiver_file)
                neighbors[receiver_file].add(sender_file)
                pair_count += 1

        return SignalEdges(
            neighbors={source: sorted(targets) for source, targets in sorted(neighbors.items())},
            signal_count=len(signals_by_id),
            receiver_count=receiver_count,
            pair_count=pair_count,
            global_receiver_files=sorted(global_receiver_files),
            seconds=round(time.time() - started, 2),
        )

    def extract_models(self) -> ModelEdges:
        from django.apps import apps

        started = time.time()
        models = apps.get_models(include_auto_created=True)
        neighbors: dict[str, set[str]] = defaultdict(set)
        relation_count = 0
        for model in models:
            model_file = self.file_of(model)
            if model_file is None:
                continue
            for model_field in model._meta.get_fields():
                if not getattr(model_field, "is_relation", False) or model_field.related_model is None:
                    continue
                related_file = self.file_of(model_field.related_model)
                if related_file is None or related_file == model_file:
                    continue
                neighbors[model_file].add(related_file)
                relation_count += 1

        return ModelEdges(
            neighbors={source: sorted(targets) for source, targets in sorted(neighbors.items())},
            model_count=len(models),
            relation_count=relation_count,
            seconds=round(time.time() - started, 2),
        )


def build_edges(root: Path, settings_module: str, source_roots: tuple[str, ...], extractors: set[str]) -> DjangoEdges:
    # Assignment, not setdefault: a shell that already exports DJANGO_SETTINGS_MODULE
    # would otherwise silently set up a different project than `--settings` names.
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    os.environ.setdefault("TEST", "1")
    sys.path.insert(0, str(root.resolve()))

    import django

    started = time.time()
    django.setup()
    setup_seconds = time.time() - started

    extractor = DjangoEdgeExtractor(root=root, source_roots=source_roots)
    # Signals first: the URL extractor imports every view module, which connects more
    # receivers, so measuring the cheap extractor afterwards would overstate its cost.
    signals = extractor.extract_signals() if "signals" in extractors else None
    models = extractor.extract_models() if "models" in extractors else None
    urls = extractor.extract_urls() if "urls" in extractors else None
    return DjangoEdges(setup_seconds=round(setup_seconds, 2), urls=urls, signals=signals, models=models)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Write the edge JSON here")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Project root paths are reported relative to")
    parser.add_argument("--settings", default="posthog.settings", help="DJANGO_SETTINGS_MODULE to set up")
    parser.add_argument(
        "--source-roots",
        default=",".join(DEFAULT_SOURCE_ROOTS),
        help="Comma-separated top-level directories inside --root that hold project code ('.' for all)",
    )
    parser.add_argument(
        "--extractors",
        default=",".join(EXTRACTOR_NAMES),
        help=f"Comma-separated subset of {','.join(EXTRACTOR_NAMES)}",
    )
    args = parser.parse_args()

    extractors = {name.strip() for name in args.extractors.split(",") if name.strip()}
    unknown = extractors - set(EXTRACTOR_NAMES)
    if unknown:
        parser.error(f"unknown extractors: {sorted(unknown)}")
    source_roots = tuple(name.strip() for name in args.source_roots.split(",") if name.strip())

    edges = build_edges(Path(args.root), args.settings, source_roots, extractors)
    payload = edges.as_json()
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    sys.stderr.write(json.dumps(payload["stats"], sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
