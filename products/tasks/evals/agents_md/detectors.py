import re
import ast
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from products.tasks.evals.golden_prs.scoring import DIFF_HEADER, structured_answer

from .claims import Claim

DEFAULT_JUDGE_MODEL = "claude-opus-5"

CODE_FILES = ("*.py", "*.ts", "*.tsx", "*.rs", "*.go")
COMMENT_LINE = re.compile(r"^\s*(#|//|/\*|\*)")
# Pragmas and shebangs are instructions to tools, not comments for readers.
PRAGMA_LINE = re.compile(r"^\s*#\s*(!|ruff:|noqa|type:|mypy:|pragma:|fmt:)|^\s*//\s*(eslint|@ts-|prettier|oxlint)")
INDENTED_IMPORT = re.compile(r"^\s+(import \S|from \S+ import )")
TEST_DEF = re.compile(r"^\s*(async )?def test_")
PARAMETERIZED = re.compile(r"parameterized|test\.each|it\.each|pytest\.mark\.parametrize")
TOP_LEVEL_DESCRIBE = re.compile(r"^describe\(", re.MULTILINE)
TS_FUNCTION_WITHOUT_RETURN_TYPE = re.compile(
    r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w+\s*(<[^>]*>)?\s*\((?:[^()]|\([^()]*\))*\)\s*\{"
    r"|^\s*(export\s+)?const\s+\w+\s*=\s*(async\s*)?(<[^>]*>)?\s*\((?:[^()]|\([^()]*\))*\)\s*=>"
)
MARKDOWN_STRUCTURE = re.compile(r"^\s*([-*+]|\d+\.|#|>|\||```|!\[|\[)")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
SIDE_EFFECT_CALL = re.compile(r"(^|[._])(send|send_mail|delay|apply_async|post|put|patch|delete|request|publish)$")


@dataclass(frozen=True, kw_only=True, slots=True)
class Candidate:
    diff: str
    workdir: Path
    added: dict[str, list[str]]
    added_line_numbers: dict[str, frozenset[int]]
    removed: dict[str, list[str]]
    new_files: frozenset[str]

    @classmethod
    def from_diff(cls, diff: str, workdir: Path) -> "Candidate":
        added: dict[str, list[str]] = {}
        added_line_numbers: dict[str, set[int]] = {}
        removed: dict[str, list[str]] = {}
        new_files: set[str] = set()
        path = ""
        line_number = 0
        for line in diff.splitlines():
            header = DIFF_HEADER.match(line)
            hunk = HUNK_HEADER.match(line)
            if header:
                path = header.group(2)
                added.setdefault(path, [])
                added_line_numbers.setdefault(path, set())
                removed.setdefault(path, [])
            elif hunk:
                line_number = int(hunk.group(1))
            elif line.startswith("new file mode"):
                new_files.add(path)
            elif line.startswith("+") and not line.startswith("+++"):
                added[path].append(line[1:])
                added_line_numbers[path].add(line_number)
                line_number += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed[path].append(line[1:])
            elif line.startswith(" "):
                line_number += 1
        return cls(
            diff=diff,
            workdir=workdir,
            added=added,
            added_line_numbers={path: frozenset(numbers) for path, numbers in added_line_numbers.items()},
            removed=removed,
            new_files=frozenset(new_files),
        )

    def added_in(self, *globs: str) -> list[tuple[str, str]]:
        return [(path, line) for path, lines in self.added.items() if _matches(path, globs) for line in lines]

    def changed_files(self, *globs: str) -> list[str]:
        return [path for path in self.added if _matches(path, globs)]

    def read(self, path: str) -> str:
        target = self.workdir / path
        return target.read_text() if target.is_file() else ""


@dataclass(frozen=True, kw_only=True, slots=True)
class Observation:
    """How often the candidate broke the rule; None when the detector could not tell."""

    violations: float | None
    detail: str = ""


Detector = Callable[..., Observation]


def _matches(path: str, globs: tuple[str, ...]) -> bool:
    return not globs or any(fnmatch(path, glob) for glob in globs)


def _count(hits: list[str], what: str) -> Observation:
    return Observation(
        violations=float(len(hits)), detail=f"{len(hits)} {what}" + (": " + "; ".join(hits[:5]) if hits else "")
    )


def count_added_matching(candidate: Candidate, claim: Claim, *, pattern: str, files: str = "*") -> Observation:
    regex = re.compile(pattern)
    hits = [line.strip() for _, line in candidate.added_in(files) if regex.search(line)]
    return _count(hits, f"added lines match /{pattern}/")


def missing_added_matching(
    candidate: Candidate, claim: Claim, *, pattern: str, files: str = "*", when: str | None = None
) -> Observation:
    lines = [line for _, line in candidate.added_in(files)]
    if when and not any(re.search(when, line) for line in lines):
        return Observation(violations=0.0, detail=f"no added line matches /{when}/, so the rule does not apply")
    if any(re.search(pattern, line) for line in lines):
        return Observation(violations=0.0, detail=f"an added line matches /{pattern}/")
    return Observation(violations=1.0, detail=f"no added line matches /{pattern}/")


def missing_in_file(candidate: Candidate, claim: Claim, *, path: str, pattern: str) -> Observation:
    if re.search(pattern, candidate.read(path), re.DOTALL):
        return Observation(violations=0.0, detail=f"{path} matches /{pattern}/")
    return Observation(violations=1.0, detail=f"{path} does not match /{pattern}/")


def files_added_outside(candidate: Candidate, claim: Claim, *, prefix: str) -> Observation:
    hits = sorted(path for path in candidate.new_files if not path.startswith(prefix))
    return _count(hits, f"new files outside {prefix}")


def changed_files_under(candidate: Candidate, claim: Claim, *, prefix: str) -> Observation:
    """One breach however many files, so a diff that also touches a README does not score worse."""
    hits = sorted(path for path in candidate.added if path.startswith(prefix))
    counted = _count(hits, f"changed files under {prefix}")
    return Observation(violations=min(1.0, counted.violations or 0.0), detail=counted.detail)


def indented_imports(candidate: Candidate, claim: Claim) -> Observation:
    hits = [line.strip() for _, line in candidate.added_in("*.py") if INDENTED_IMPORT.match(line)]
    return _count(hits, "imports inside a function or class")


def comment_lines(candidate: Candidate, claim: Claim) -> Observation:
    hits = [
        line.strip()
        for _, line in candidate.added_in(*CODE_FILES)
        if COMMENT_LINE.match(line) and not PRAGMA_LINE.match(line)
    ]
    return _count(hits, "added comment lines")


EDITED_COMMENT_SIMILARITY = 0.75


def _is_edit_of(line: str, kept: set[str]) -> bool:
    return any(SequenceMatcher(None, line, other).ratio() >= EDITED_COMMENT_SIMILARITY for other in kept)


def removed_comment_lines(candidate: Candidate, claim: Claim) -> Observation:
    """A comment that comes back with a small edit, such as a renamed module path, stays kept."""
    kept = {line.strip() for _, line in candidate.added_in(*CODE_FILES) if COMMENT_LINE.match(line)}
    removed = [
        line.strip()
        for lines in candidate.removed.values()
        for line in lines
        if COMMENT_LINE.match(line) and not _is_edit_of(line.strip(), kept)
    ]
    return _count(removed, "comment lines removed and not added back")


def stdlib_dataclass_decorators(candidate: Candidate, claim: Claim) -> Observation:
    hits = [line.strip() for _, line in candidate.added_in("*.py") if re.match(r"^\s*@dataclass\b", line)]
    return _count(hits, "stdlib @dataclass decorators instead of @frozen")


def ts_functions_without_return_type(candidate: Candidate, claim: Claim) -> Observation:
    hits = [
        line.strip() for _, line in candidate.added_in("*.ts", "*.tsx") if TS_FUNCTION_WITHOUT_RETURN_TYPE.match(line)
    ]
    return _count(hits, "functions without a return type")


def unparameterized_tests(candidate: Candidate, claim: Claim) -> Observation:
    test_globs = ("*test_*.py", "*_test.py", "*.test.ts", "*.test.tsx")
    lines = [line for _, line in candidate.added_in(*test_globs)]
    new_test_files = sorted(path for path in candidate.new_files if _matches(path, test_globs))
    if any(PARAMETERIZED.search(line) for line in lines):
        return Observation(
            violations=float(len(new_test_files)), detail=f"parameterized; new test files: {new_test_files}"
        )
    tests = [line.strip() for line in lines if TEST_DEF.match(line) or re.match(r"^\s*(it|test)\(", line)]
    return Observation(
        violations=float(len(new_test_files) + len(tests)),
        detail=f"{len(tests)} standalone tests, new test files: {new_test_files}",
    )


def extra_top_level_describes(candidate: Candidate, claim: Claim) -> Observation:
    extra = {
        path: len(TOP_LEVEL_DESCRIBE.findall(candidate.read(path))) - 1
        for path in candidate.changed_files("*.test.ts", "*.test.tsx")
    }
    hits = [f"{path} has {count + 1} top-level describes" for path, count in extra.items() if count > 0]
    return Observation(violations=float(sum(max(count, 0) for count in extra.values())), detail="; ".join(hits))


def _prose_outside_fences(lines: list[str]) -> list[str]:
    prose: list[str] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            prose.append(line)
    return prose


def hard_wrapped_markdown(candidate: Candidate, claim: Claim) -> Observation:
    hits = [
        line.strip()
        for path, lines in candidate.added.items()
        if _matches(path, ("*.md",))
        for line in _prose_outside_fences(lines)
        if len(line) > 60 and not MARKDOWN_STRUCTURE.match(line) and re.search(r"[a-z,]$", line.rstrip())
    ]
    return _count(hits, "prose lines that break mid-sentence")


def _parse(candidate: Candidate, path: str) -> ast.Module | None:
    try:
        return ast.parse(candidate.read(path))
    except SyntaxError:
        return None


def _added_defs(candidate: Candidate, path: str, module: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    added = {line.strip() for line in candidate.added.get(path, ())}
    return [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(line.startswith(f"def {node.name}(") or line.startswith(f"async def {node.name}(") for line in added)
    ]


def handle_statement_count(candidate: Candidate, claim: Claim) -> Observation:
    counts: dict[str, int] = {}
    for path in candidate.changed_files("*management/commands/*.py"):
        module = _parse(candidate, path)
        for node in _added_defs(candidate, path, module) if module else ():
            if node.name == "handle":
                counts[path] = sum(1 for child in ast.walk(node) if isinstance(child, ast.stmt)) - 1
    if not counts:
        return Observation(violations=None, detail="no handle() was added")
    return Observation(violations=float(max(counts.values())), detail=f"statements in handle(): {counts}")


def unannotated_defs(candidate: Candidate, claim: Claim) -> Observation:
    hits: list[str] = []
    for path in candidate.changed_files("*.py"):
        module = _parse(candidate, path)
        for node in _added_defs(candidate, path, module) if module else ():
            arguments = [arg for arg in node.args.args + node.args.kwonlyargs if arg.arg not in ("self", "cls")]
            if node.returns is None or any(arg.annotation is None for arg in arguments):
                hits.append(f"{path}:{node.name}")
    return _count(hits, "functions missing an annotation")


def calls_before_definition(candidate: Candidate, claim: Claim) -> Observation:
    hits: list[str] = []
    for path in candidate.new_files:
        module = _parse(candidate, path) if path.endswith(".py") else None
        if module is None:
            continue
        defined = {node.name: node.lineno for node in module.body if isinstance(node, ast.FunctionDef)}
        first_call: dict[str, int] = {}
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in defined:
                first_call[node.func.id] = min(first_call.get(node.func.id, node.lineno), node.lineno)
        hits.extend(f"{path}:{name}" for name, line in first_call.items() if line < defined[name])
    return _count(hits, "functions called before their definition")


def _is_added(candidate: Candidate, path: str, node: ast.stmt | ast.expr) -> bool:
    numbers = candidate.added_line_numbers.get(path, frozenset())
    return any(line in numbers for line in range(node.lineno, (node.end_lineno or node.lineno) + 1))


def side_effects_inside_atomic(candidate: Candidate, claim: Claim) -> Observation:
    """Only the atomic blocks and calls the agent added count, so an old side effect in the file cannot skew the score."""
    atomic_blocks: list[tuple[str, ast.With]] = []
    for path in candidate.changed_files("*.py"):
        module = _parse(candidate, path)
        if module is None:
            continue
        atomic_blocks.extend(
            (path, node)
            for node in ast.walk(module)
            if isinstance(node, ast.With)
            and "atomic" in ast.unparse(node.items[0].context_expr)
            and _is_added(candidate, path, node)
        )
    if not atomic_blocks:
        return Observation(violations=1.0, detail="no added transaction.atomic() block")
    hits = [
        ast.unparse(call.func)
        for path, block in atomic_blocks
        for call in ast.walk(block)
        if isinstance(call, ast.Call)
        and SIDE_EFFECT_CALL.search(ast.unparse(call.func))
        and _is_added(candidate, path, call)
    ]
    return Observation(violations=float(bool(hits)), detail=f"side effects inside atomic: {hits}")


class RuleVerdict(BaseModel):
    violated: bool
    reasoning: str


JUDGE_SYSTEM_PROMPT = """You check whether a code change breaks one rule from a repository's contributor guide.

Answer `violated: true` only when the diff clearly does what the rule forbids, or clearly skips what the rule requires
in a place where the rule applies. Answer `violated: false` when the rule does not apply to this change.
Explain in a few plain sentences that name the lines that decide it."""

MAX_DIFF_CHARS_FOR_JUDGE = 120_000
JUDGE_SAMPLES = 3


def judge(candidate: Candidate, claim: Claim, *, model: str = DEFAULT_JUDGE_MODEL) -> Observation:
    """The share of judge samples that saw a violation, so one odd answer cannot decide a run alone."""
    diff = candidate.diff[:MAX_DIFF_CHARS_FOR_JUDGE]
    request = f"<rule>\n{claim.text}\n</rule>\n\n<task>\n{claim.task}\n</task>\n\n<diff>\n{diff}\n</diff>"
    answers = [structured_answer(model, JUDGE_SYSTEM_PROMPT, request, RuleVerdict) for _ in range(JUDGE_SAMPLES)]
    verdicts = [answer.value for answer in answers if answer.value is not None]
    if not verdicts:
        failures = "; ".join(answer.failure for answer in answers)
        return Observation(violations=None, detail=f"judge failed: {failures}")
    violated = [verdict for verdict in verdicts if verdict.violated]
    majority = violated if len(violated) * 2 >= len(verdicts) else [v for v in verdicts if not v.violated]
    return Observation(
        violations=len(violated) / len(verdicts),
        detail=f"{len(violated)} of {len(verdicts)} samples saw a violation: {majority[0].reasoning}",
    )


DETECTORS: dict[str, Detector] = {
    "count_added_matching": count_added_matching,
    "missing_added_matching": missing_added_matching,
    "missing_in_file": missing_in_file,
    "files_added_outside": files_added_outside,
    "changed_files_under": changed_files_under,
    "indented_imports": indented_imports,
    "comment_lines": comment_lines,
    "removed_comment_lines": removed_comment_lines,
    "stdlib_dataclass_decorators": stdlib_dataclass_decorators,
    "ts_functions_without_return_type": ts_functions_without_return_type,
    "unparameterized_tests": unparameterized_tests,
    "extra_top_level_describes": extra_top_level_describes,
    "hard_wrapped_markdown": hard_wrapped_markdown,
    "handle_statement_count": handle_statement_count,
    "unannotated_defs": unannotated_defs,
    "calls_before_definition": calls_before_definition,
    "side_effects_inside_atomic": side_effects_inside_atomic,
    "judge": judge,
}


@dataclass(frozen=True, kw_only=True, slots=True)
class Detection:
    violations: float | None
    details: tuple[str, ...] = field(default_factory=tuple)


def detect(candidate: Candidate, claim: Claim, judge_model: str = DEFAULT_JUDGE_MODEL) -> Detection:
    """Sum the claim's detectors, so a claim with two rules in one bullet reports one number."""
    if not candidate.diff.strip():
        violations = 0.0 if claim.no_change_is_compliant else None
        return Detection(violations=violations, details=("the agent changed no files",))
    observations: list[Observation] = []
    for spec in claim.detectors:
        params: dict[str, Any] = {key: value for key, value in spec.items() if key != "name"}
        if spec["name"] == "judge":
            params["model"] = judge_model
        observations.append(DETECTORS[spec["name"]](candidate, claim, **params))
    if any(observation.violations is None for observation in observations):
        return Detection(violations=None, details=tuple(o.detail for o in observations))
    total = sum(observation.violations or 0.0 for observation in observations)
    return Detection(violations=total, details=tuple(o.detail for o in observations))
