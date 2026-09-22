"""Ratchet on the product-specific path methods in ``frontend/src/lib/api.ts``.

``ApiRequest`` is one class holding every URL in the app, so adding an endpoint
means editing a core file, and the namespace on the ``api`` singleton is one line
further. Products keep doing that even when their Orval client already has the
same endpoint, which puts a single product's URLs and response types in core.

The check is mechanical: resolve the URL each ``ApiRequest`` path method builds,
and compare it with every template the generated clients emit. A match means a
generated twin already exists, so the hand-rolled method is redundant. No
ownership judgment and no allowlist - the generated output decides.

Existing redundancy is grandfathered in a baseline file. The command fails only
on a redundant method that is not in the baseline, which is the case that would
add new debt. A shrinking baseline is the migration's progress metric.

    hogli lint:api-ratchet                    # check against the baseline
    hogli lint:api-ratchet --prune-baseline   # drop stale entries, never add one
    hogli lint:api-ratchet --update-baseline  # rewrite the baseline, new debt included
    hogli lint:api-ratchet --namespaces       # product-owned namespaces, for codegen
    hogli lint:api-ratchet --json             # full report as JSON

``ApiRequest`` builds ``/api/environments/{team_id}/...``, Orval emits
``/api/projects/{project_id}/...``. Those are the same Django routes - the
environments path is a backward-compat alias that codegen skips - so both sides
are normalized onto ``projects`` before comparison.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import click
from hogli.manifest import REPO_ROOT

API_TS: Final = Path("frontend/src/lib/api.ts")
CORE_GENERATED: Final = Path("frontend/src/generated/core/api.ts")
PRODUCT_GENERATED_GLOB: Final = "products/*/frontend/generated/api.ts"

# Stands in for a product in the owner set of a template only the core client emits.
# A core twin is coverage: frontend/src/generated/core/api.ts exists for the endpoints
# no single product owns, so a hand-rolled path method beside one is still redundant.
# It never matches a product directory name, so no product owns such a namespace.
CORE_OWNER: Final = "core"

# Sits next to the file it ratchets, so the person adding a path method sees it.
BASELINE: Final = Path("frontend/src/lib/api-ratchet-baseline.txt")

BASELINE_HEADER: Final = """\
# ApiRequest path methods in frontend/src/lib/api.ts that a generated client
# already covers. Grandfathered debt: the ratchet fails on a redundant method
# that is NOT listed here.
#
# DO NOT EDIT BY HAND. Mechanical output of `hogli lint:api-ratchet
# --update-baseline`. Hand-added entries turn it back into an allowlist.
#
# To drop an entry: migrate the call sites onto the product's generated client
# (see .agents/skills/adopting-generated-api-types/SKILL.md), delete the path
# method and the namespace block, then regenerate this file.
"""

# The chain builders a path method composes its URL from.
_COMPONENT_CALLS: Final = frozenset({"addPathComponent", "addEncodedPathComponent", "withAction"})

# Chain roots that resolve to a literal prefix rather than to another method.
_ROOT_PREFIXES: Final[dict[str, tuple[str, ...]]] = {
    "projects": ("projects",),
    "projectsDetail": ("projects", "{}"),
    "environments": ("environments",),
    "environmentsDetail": ("environments", "{}"),
    "organizations": ("organizations",),
    "organizationsDetail": ("organizations", "{}"),
}

_METHOD_START: Final = re.compile(r"^    public (\w+)\(")
_CHAIN_BASE: Final = re.compile(r"this\.(\w+)\(")
_COMPONENT_CALL: Final = re.compile(r"\.(addPathComponent|addEncodedPathComponent|withAction)\(")
_NAMESPACE_START: Final = re.compile(r"^    (\w+): \{")
_MEMBER_CALL: Final = re.compile(r"\.(\w+)\(")
_GENERATED_URL: Final = re.compile(r"`(/api/[^`]*)`")
_TEMPLATE_HOLE: Final = re.compile(r"\$\{[^}]*\}")


def _read_call_argument(text: str, open_paren: int) -> str:
    """Return the argument text of the call whose ``(`` sits at ``open_paren``."""
    depth = 0
    for index in range(open_paren, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : index]
    return text[open_paren + 1 :]


def _argument_segments(argument: str) -> tuple[str, ...]:
    """Path segments an argument contributes: literals verbatim, anything else a hole."""
    stripped = argument.strip()
    quoted = re.fullmatch(r"""(['"`])(.*)\1""", stripped, re.S)
    if quoted is None or "${" in quoted.group(2):
        return ("{}",)
    # A literal may pack several segments: addPathComponent('stack_frames/batch_get').
    return tuple(part for part in quoted.group(2).split("/") if part)


def _chain_segments(text: str) -> tuple[str, ...]:
    """Path segments every ``addPathComponent``-style call in ``text`` appends, in order."""
    segments: list[str] = []
    for call in _COMPONENT_CALL.finditer(text):
        segments.extend(_argument_segments(_read_call_argument(text, call.end() - 1)))
    return tuple(segments)


@dataclass(frozen=True)
class ReturnStatement:
    """One ``return`` of a path method, with the body text that runs before it."""

    setup: str
    statement: str


def _split_returns(body: str) -> list[ReturnStatement]:
    """Split a method body into one ReturnStatement per ``return``.

    The setup is the same for every branch - it is where a method assigns the
    chain to a local - so each return carries it rather than the branches that
    happen to precede it.
    """
    starts = [match.start() for match in re.finditer(r"\breturn\b", body)]
    if not starts:
        return [ReturnStatement(setup="", statement=body)]
    setup = body[: starts[0]]
    bounds = [*starts, len(body)]
    return [ReturnStatement(setup=setup, statement=body[start:bound]) for start, bound in zip(starts, bounds[1:])]


def normalize_template(segments: tuple[str, ...]) -> tuple[str, ...]:
    """Drop the query-string segment and put the environments alias on projects."""
    kept = tuple(segment for segment in segments if not segment.startswith("?"))
    if kept[:1] == ("environments",):
        return ("projects", *kept[1:])
    return kept


class ApiRequestResolver:
    """Resolves each ``ApiRequest`` path method to the URL templates it builds.

    A method can build more than one URL - ``alerts()`` branches on whether an
    alert id was passed - so each ``return`` statement is resolved on its own,
    against everything the body built before it. Resolving the return statement
    alone loses the chain root of the methods that assign it to a local first
    (``const apiRequest = this.environmentsDetail(teamId)...``).
    """

    def __init__(self, source: str) -> None:
        self._returns: dict[str, list[ReturnStatement]] = {}
        self._cache: dict[str, tuple[tuple[str, ...], ...]] = {}
        self._parse(source)

    def _parse(self, source: str) -> None:
        """Collect the return-statement chunks of every method returning an ApiRequest."""
        lines = source.splitlines()
        index = 0
        while index < len(lines):
            match = _METHOD_START.match(lines[index])
            if match is None:
                index += 1
                continue
            signature: list[str] = []
            while index < len(lines) and not lines[index].rstrip().endswith("{"):
                signature.append(lines[index])
                index += 1
            if index < len(lines):
                signature.append(lines[index])
                index += 1
            body: list[str] = []
            while index < len(lines) and lines[index] != "    }":
                body.append(lines[index])
                index += 1
            if "): ApiRequest {" not in " ".join(signature):
                continue  # a verb (get/create/...), not a path method
            text = "\n".join(body)
            self._returns[match.group(1)] = _split_returns(text)

    def method_names(self) -> frozenset[str]:
        return frozenset(self._returns)

    def templates(self, name: str) -> tuple[tuple[str, ...], ...]:
        """Every URL template ``name`` can build, as segment tuples, or empty if unresolvable."""
        if name in self._cache:
            return self._cache[name]
        self._cache[name] = ()  # cycle guard for the recursive resolve below
        resolved = tuple(
            template
            for statement in self._returns.get(name, [])
            if (template := self._resolve_return(statement)) is not None
        )
        self._cache[name] = resolved
        return resolved

    def _resolve_return(self, statement: ReturnStatement) -> tuple[str, ...] | None:
        base = _CHAIN_BASE.search(statement.statement)
        if base is not None:
            prefix = self._resolve_base(base.group(1))
            return None if prefix is None else (*prefix, *_chain_segments(statement.statement))
        # The return continues a chain the setup built into a local, so the root
        # and the components before the return both come from the setup.
        base = _CHAIN_BASE.search(statement.setup)
        if base is None:
            return None
        prefix = self._resolve_base(base.group(1))
        if prefix is None:
            return None
        return (*prefix, *_chain_segments(statement.setup), *_chain_segments(statement.statement))

    def _resolve_base(self, name: str) -> tuple[str, ...] | None:
        if name in _COMPONENT_CALLS:
            return ()  # the chain starts on `this` itself, e.g. this.addPathComponent('projects')
        if name in _ROOT_PREFIXES:
            return _ROOT_PREFIXES[name]
        if name not in self._returns:
            return None
        templates = self.templates(name)
        return templates[0] if templates else None


class GeneratedTemplates:
    """Every URL template the generated clients emit, with the products emitting it.

    ``product/ts_helpers.py`` parses the same files into a different shape
    (``{p}`` holes, keyed by URL and HTTP method) because it matches a call site
    that carries a verb. Here the verb lives on the namespace, not on the path
    method, so the key is the path alone.
    """

    def __init__(self, repo_root: Path) -> None:
        self.owners: dict[tuple[str, ...], frozenset[str]] = {}
        for path in sorted(repo_root.glob(PRODUCT_GENERATED_GLOB)):
            self._collect(path, path.relative_to(repo_root).parts[1])
        core = repo_root / CORE_GENERATED
        if core.exists():
            self._collect(core, CORE_OWNER)

    def _collect(self, path: Path, owner: str) -> None:
        for url in _GENERATED_URL.findall(path.read_text()):
            raw = tuple(_TEMPLATE_HOLE.sub("{}", url).strip("/").split("/")[1:])
            template = normalize_template(raw)
            if not template:
                continue
            self.owners[template] = self.owners.get(template, frozenset()) | {owner}

    def products_covering(self, template: tuple[str, ...]) -> frozenset[str]:
        """Owners whose generated client emits exactly ``template``, CORE_OWNER included.

        Prefix matching would also fire on a shorter URL that merely sits above a
        generated route (``file_system`` above ``file_system/{}/link``), and those
        are different endpoints, so the match has to be exact.
        """
        return self.owners.get(template, frozenset())


class Ratchet:
    """The report: which path methods are redundant, and which namespaces use them."""

    def __init__(self, repo_root: Path) -> None:
        self._source = (repo_root / API_TS).read_text()
        self._resolver = ApiRequestResolver(self._source)
        self._generated = GeneratedTemplates(repo_root)
        self.redundant: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {}
        for name in sorted(self._resolver.method_names()):
            for template in self._resolver.templates(name):
                normalized = normalize_template(template)
                if len(normalized) < 3:
                    continue  # projects/{} on its own is core plumbing, not a resource
                products = self._generated.products_covering(normalized)
                if products:
                    self.redundant[name] = (normalized, products)
                    break

    def namespaces(self) -> dict[str, frozenset[str]]:
        """Namespaces on the ``api`` singleton that call a redundant path method."""
        owned: dict[str, frozenset[str]] = {}
        for namespace, block in self._namespace_blocks().items():
            products: set[str] = set()
            for call in _MEMBER_CALL.finditer(block):
                entry = self.redundant.get(call.group(1))
                if entry is not None:
                    products |= entry[1]
            if products:
                owned[namespace] = frozenset(products)
        return owned

    def _namespace_blocks(self) -> dict[str, str]:
        lines = self._source.splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith("const api = {")), None)
        if start is None:
            return {}
        blocks: dict[str, str] = {}
        index = start + 1
        while index < len(lines):
            match = _NAMESPACE_START.match(lines[index])
            if match is None:
                index += 1
                continue
            depth, body = 0, []
            while index < len(lines):
                line = lines[index]
                body.append(line)
                depth += line.count("{") - line.count("}")
                index += 1
                if depth <= 0:
                    break
            blocks[match.group(1)] = "\n".join(body)
        return blocks


def read_baseline(repo_root: Path) -> set[str]:
    path = repo_root / BASELINE
    if not path.exists():
        return set()
    return {
        stripped
        for line in path.read_text().splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    }


def write_baseline(repo_root: Path, methods: set[str]) -> None:
    body = "".join(f"{name}\n" for name in sorted(methods))
    (repo_root / BASELINE).write_text(f"{BASELINE_HEADER}\n{body}")


def _report_json(ratchet: Ratchet, new: set[str], stale: set[str]) -> str:
    return json.dumps(
        {
            "redundant": {
                name: {"template": "/".join(template), "products": sorted(products)}
                for name, (template, products) in sorted(ratchet.redundant.items())
            },
            "namespaces": {ns: sorted(products) for ns, products in sorted(ratchet.namespaces().items())},
            "new": sorted(new),
            "stale": sorted(stale),
        },
        indent=2,
    )


@click.command(
    name="lint:api-ratchet",
    help="Block new frontend/src/lib/api.ts path methods that a generated client already covers.",
)
@click.option("--update-baseline", is_flag=True, help="Rewrite the baseline from the current state (it can grow).")
@click.option("--prune-baseline", is_flag=True, help="Drop stale baseline entries. Never adds one.")
@click.option("--namespaces", is_flag=True, help="Print the product-owned api namespaces and their products.")
@click.option("--json", "as_json", is_flag=True, help="Print the full report as JSON.")
def cmd_lint_api_ratchet(update_baseline: bool, prune_baseline: bool, namespaces: bool, as_json: bool) -> None:
    """Fail on a new ApiRequest path method that a generated client already covers."""
    repo_root = Path(REPO_ROOT)
    ratchet = Ratchet(repo_root)
    redundant = set(ratchet.redundant)

    if namespaces:
        for namespace, products in sorted(ratchet.namespaces().items()):
            click.echo(f"{namespace} {','.join(sorted(products))}")
        return

    baseline = read_baseline(repo_root)
    new = redundant - baseline
    stale = baseline - redundant

    if prune_baseline:
        write_baseline(repo_root, baseline - stale)
        click.echo(f"Baseline pruned: {len(stale)} stale entry/entries dropped, {len(baseline - stale)} left.")
        if new:
            click.echo(f"{len(new)} new duplicate(s) stay unlisted, so the check still fails on them.")
        return

    if update_baseline:
        write_baseline(repo_root, redundant)
        click.echo(f"Baseline rewritten: {len(redundant)} redundant path method(s).")
        if new:
            click.echo(
                f"⚠️  This grew the baseline by {len(new)} entry/entries, which grandfathers new debt.\n"
                "    Migrate the call sites instead, or say in the pull request why the entry has to stay."
            )
        return

    if as_json:
        click.echo(_report_json(ratchet, new, stale))
        raise SystemExit(1 if new else 0)

    click.echo(f"ApiRequest path methods with a generated twin: {len(redundant)} ({len(baseline)} in the baseline)")
    if stale:
        click.echo(f"\n⚠️  {len(stale)} stale baseline entry/entries — gone or no longer redundant:")
        for name in sorted(stale):
            click.echo(f"    {name}")
        click.echo("    Run: hogli lint:api-ratchet --update-baseline")
    if new:
        click.echo(f"\n❌ {len(new)} path method(s) duplicate a generated client:")
        for name in sorted(new):
            template, products = ratchet.redundant[name]
            click.echo(f"    {name}  ->  /api/{'/'.join(template)}  (generated in: {', '.join(sorted(products))})")
        click.echo(
            "\nUse the product's generated client from products/<product>/frontend/generated/api.ts instead.\n"
            "Agents: invoke the `adopting-generated-api-types` skill."
        )
        raise SystemExit(1)
    click.echo("✅ No new path methods duplicating a generated client.")
