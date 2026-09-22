"""Ratchet on the product-specific path methods in ``frontend/src/lib/api.ts``.

``ApiRequest`` is one class holding every URL in the app, so adding an endpoint
means editing a core file, and the namespace on the ``api`` singleton is one line
further. Products keep doing that even when their Orval client already has the
same endpoint, which puts a single product's URLs and response types in core.

The check is mechanical: resolve the URL each ``ApiRequest`` path method builds,
and compare it with every template the generated clients emit. A match means a
generated twin already exists, so the hand-rolled method is redundant. No
ownership judgment and no allowlist - the generated output decides.

The unit is the path, not the operation. A path method carries no HTTP verb, since
the verb lives on the ``api`` namespace that calls it, so a match says the route is
generated and not that every operation on it is. The namespace side of that is
resolved per member in ``product/ts_helpers.py``, which checks the verb too.

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

# The scoping prefixes a path method starts from. They are plumbing, not endpoints, so a
# method that resolves to one of them is not a duplicate of anything. Every other short
# template is fair game: the generated clients really do emit /api/billing/activate/.
PLUMBING_TEMPLATES: Final = frozenset({("projects",), ("projects", "{}"), ("organizations",), ("organizations", "{}")})

# Sits next to the file it ratchets, so the person adding a path method sees it.
BASELINE: Final = Path("frontend/src/lib/api-ratchet-baseline.txt")

BASELINE_HEADER: Final = """\
# ApiRequest path methods in frontend/src/lib/api.ts that a generated client
# already covers, each with the route it duplicates. Grandfathered debt: the
# ratchet fails on a redundant method and route pair that is NOT listed here.
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
_CHAINED_CALL: Final = re.compile(r"\.(\w+)\(")
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
    """Path segments an argument contributes.

    A quoted string can pack several segments, and a template literal can mix them
    with interpolations: ``addPathComponent(`${issueId}/similar_issues`)`` is the
    detail route plus a literal action, not one opaque hole.
    """
    stripped = argument.strip()
    quoted = re.fullmatch(r"""(['"`])(.*)\1""", stripped, re.S)
    if quoted is None:
        return ("{}",)
    return tuple("{}" if "${" in part else part for part in quoted.group(2).split("/") if part)


@dataclass(frozen=True)
class RedundantMethod:
    """A path method and one generated route it duplicates."""

    name: str
    template: tuple[str, ...]
    products: frozenset[str]

    @property
    def entry(self) -> str:
        """The baseline line for this pair."""
        return f"{self.name} {'/'.join(self.template)}"


@dataclass(frozen=True)
class ReturnStatement:
    """One ``return`` of a path method, with the statements that run before it."""

    setup: str
    statement: str


def _split_returns(body: str) -> list[ReturnStatement]:
    """Split a method body into one ReturnStatement per ``return``.

    The setup of a return is every statement before it that is not itself an earlier
    return expression, so a chain the body mutates between two returns reaches the
    later one, while a branch that already returned contributes nothing.
    """
    starts = [match.start() for match in re.finditer(r"\breturn\b", body)]
    if not starts:
        return [ReturnStatement(setup="", statement=body)]
    bounds = [*starts, len(body)]
    chunks = [body[start:bound] for start, bound in zip(starts, bounds[1:])]
    expressions = [_return_expression(chunk) for chunk in chunks]
    returns: list[ReturnStatement] = []
    for index, expression in enumerate(expressions):
        trailing = "".join(earlier[len(expressions[position]) :] for position, earlier in enumerate(chunks[:index]))
        returns.append(ReturnStatement(setup=body[: starts[0]] + trailing, statement=expression))
    return returns


def _ternary_branches(expression: str) -> list[str]:
    """The branches of a ternary, or the expression itself when there is no ternary.

    A ternary return builds two different URLs, and reading the calls of both branches
    as one chain produces a template that neither branch builds.
    """
    depth = 0
    quote = ""
    question = -1
    for index, char in enumerate(expression):
        if quote:
            quote = "" if char == quote else quote
            continue
        if char in "\"'`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif depth != 0:
            continue
        elif char == "?" and question < 0 and expression[index + 1 : index + 2] not in {".", "?"}:
            question = index
        elif char == ":" and question >= 0:
            return [expression[question + 1 : index], expression[index + 1 :]]
    return [expression]


def _return_expression(chunk: str) -> str:
    """The returned expression alone, without the statements that follow it.

    A chain or a ternary can span lines, so a continuation line is one that opens the
    expression further, starts with the next call in the chain, or starts with a
    ternary arm.
    """
    lines = chunk.splitlines(keepends=True)
    taken = [lines[0]]
    for line in lines[1:]:
        text = "".join(taken)
        if text.count("(") > text.count(")") or line.lstrip().startswith((".", "?", ":")):
            taken.append(line)
            continue
        break
    return "".join(taken)


def _after_base(text: str, base: re.Match[str]) -> str:
    """The chain text after its root call.

    A root that is itself a component builder, `this.addPathComponent('projects')`,
    keeps its own argument, so the scan starts before it rather than after it.
    """
    return text if base.group(1) in _COMPONENT_CALLS else text[base.end() :]


def normalize_template(segments: tuple[str, ...]) -> tuple[str, ...]:
    """Drop the query string, put the environments alias on projects, @current on a hole."""
    kept = tuple("{}" if segment == "@current" else segment for segment in segments if not segment.startswith("?"))
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
        """Every URL template ``name`` can build, as segment tuples, empty if unresolvable."""
        if name in self._cache:
            return self._cache[name]
        self._cache[name] = ()  # cycle guard for the recursive resolve below
        resolved: list[tuple[str, ...]] = []
        for statement in self._returns.get(name, []):
            resolved.extend(self._resolve_return(statement))
        self._cache[name] = tuple(dict.fromkeys(resolved))
        return self._cache[name]

    def _resolve_return(self, statement: ReturnStatement) -> list[tuple[str, ...]]:
        """Every template one return can build, across its ternary and base branches."""
        branches = _ternary_branches(statement.statement)
        if len(branches) > 1:
            resolved: list[tuple[str, ...]] = []
            for branch in branches:
                resolved.extend(self._resolve_return(ReturnStatement(setup=statement.setup, statement=branch)))
            return resolved
        return self._resolve_chain(statement)

    def _resolve_chain(self, statement: ReturnStatement) -> list[tuple[str, ...]]:
        base = _CHAIN_BASE.search(statement.statement)
        if base is not None:
            prefixes = self._base_prefixes(base.group(1))
            tail = self._appended_segments(_after_base(statement.statement, base))
            return [(*prefix, *tail) for prefix in prefixes]
        # The return continues a chain the setup built into a local, so the root and
        # the components before the return both come from the setup.
        base = _CHAIN_BASE.search(statement.setup)
        if base is None:
            return []
        prefixes = self._base_prefixes(base.group(1))
        tail = self._appended_segments(_after_base(statement.setup, base)) + self._appended_segments(
            statement.statement
        )
        return [(*prefix, *tail) for prefix in prefixes]

    def _base_prefixes(self, name: str) -> list[tuple[str, ...]]:
        """Every prefix the chain root can stand for. A branching root has several."""
        if name in _COMPONENT_CALLS:
            return [()]  # the chain starts on `this` itself, e.g. this.addPathComponent('projects')
        if name in _ROOT_PREFIXES:
            return [_ROOT_PREFIXES[name]]
        if name not in self._returns:
            return []
        return list(self.templates(name))

    def _appended_segments(self, text: str, seen: frozenset[str] = frozenset()) -> tuple[str, ...]:
        """The segments a chain appends, expanding the path helpers it calls.

        A chain can pass through another path method: `organizations().current()`
        appends `@current` through `current()`, and reading only the component
        builders drops it.
        """
        segments: list[str] = []
        for call in _CHAINED_CALL.finditer(text):
            name = call.group(1)
            if name in _COMPONENT_CALLS:
                segments.extend(_argument_segments(_read_call_argument(text, call.end() - 1)))
            elif name in self._returns and name not in seen:
                segments.extend(self._helper_appends(name, seen | {name}))
        return tuple(segments)

    def _helper_appends(self, name: str, seen: frozenset[str]) -> tuple[str, ...]:
        """What a path method appends when it is chained onto an existing request."""
        statements = self._returns.get(name, [])
        if not statements:
            return ()
        statement = statements[0]
        base = _CHAIN_BASE.search(statement.statement)
        body = _after_base(statement.statement, base) if base is not None else statement.statement
        return self._appended_segments(body, seen)


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
        # Every branch of a method that matches, not only the first: a method that
        # builds both a collection and a detail route duplicates two generated routes,
        # and grandfathering one of them would leave the other unguarded.
        self.redundant: list[RedundantMethod] = []
        for name in sorted(self._resolver.method_names()):
            for template in self._resolver.templates(name):
                normalized = normalize_template(template)
                if normalized in PLUMBING_TEMPLATES:
                    continue
                products = self._generated.products_covering(normalized)
                if products:
                    self.redundant.append(RedundantMethod(name=name, template=normalized, products=products))

    def products_by_method(self) -> dict[str, frozenset[str]]:
        """The products covering each redundant method, across all of its routes."""
        products: dict[str, frozenset[str]] = {}
        for entry in self.redundant:
            products[entry.name] = products.get(entry.name, frozenset()) | entry.products
        return products

    def namespaces(self) -> dict[str, frozenset[str]]:
        """Namespaces on the ``api`` singleton that call a redundant path method."""
        owned: dict[str, frozenset[str]] = {}
        for namespace, block in self._namespace_blocks().items():
            products: set[str] = set()
            by_method = self.products_by_method()
            for call in _MEMBER_CALL.finditer(block):
                products |= by_method.get(call.group(1), frozenset())
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
            "redundant": [
                {"method": entry.name, "template": "/".join(entry.template), "products": sorted(entry.products)}
                for entry in sorted(ratchet.redundant, key=lambda item: item.entry)
            ],
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
    redundant = {entry.entry for entry in ratchet.redundant}

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
        for entry in sorted(stale):
            click.echo(f"    {entry}")
        click.echo("    Run: hogli lint:api-ratchet --prune-baseline")
    if new:
        click.echo(f"\n❌ {len(new)} path method(s) duplicate a generated client:")
        for entry in sorted(ratchet.redundant, key=lambda item: item.entry):
            if entry.entry not in new:
                continue
            click.echo(
                f"    {entry.name}  ->  /api/{'/'.join(entry.template)}"
                f"  (generated in: {', '.join(sorted(entry.products))})"
            )
        click.echo(
            "\nUse the product's generated client from products/<product>/frontend/generated/api.ts instead.\n"
            "The match is on the route, so check the operation you need is generated as well:\n"
            "if it is not, annotate the viewset and run `hogli build:openapi` before migrating.\n"
            "Agents: invoke the `adopting-generated-api-types` skill."
        )
        raise SystemExit(1)
    click.echo("✅ No new path methods duplicating a generated client.")
