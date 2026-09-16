import re
import shutil
import tempfile
import subprocess
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from posthog.dataclasses import frozen

FLAG_CONSTANTS_PATH = "frontend/src/lib/constants.tsx"
SWEEP_FILE_THRESHOLD = 200

DEFAULT_EXCLUDES: tuple[str, ...] = (
    "**/__snapshots__/**",
    "**/*.snap",
    "**/generated/**",
    "**/node_modules/**",
    "**/*.lock",
    "**/pnpm-lock.yaml",
    "**/migrations/**",
    FLAG_CONSTANTS_PATH,
)

_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|test_[^/]*|[^/]*[._]test\.[a-z]+|[^/]*\.spec\.[a-z]+|conftest\.py)(/|$)"
)
_FLAG_ENTRY = re.compile(r"^\s+([A-Z][A-Z0-9_]*):\s*'([^']+)'")
_WORD = re.compile(r"\w")


def is_test_path(path: str) -> bool:
    return _TEST_PATH.search(path) is not None


@frozen
class CommitStamp:
    sha: str
    committed_at: datetime
    author_email: str
    subject: str


@frozen
class ReferenceCount:
    files: tuple[str, ...]
    total: int

    @property
    def code_files(self) -> tuple[str, ...]:
        return tuple(f for f in self.files if not is_test_path(f))


@frozen
class Match:
    path: str
    line_number: int
    text: str


class RepoIndex:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=False)
        if result.returncode not in (0, 1):
            raise RuntimeError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
        return result.stdout

    def head_sha(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def frontend_flag_keys(self) -> dict[str, str]:
        path = self.root / FLAG_CONSTANTS_PATH
        keys: dict[str, str] = {}
        inside = False
        for line in path.read_text().splitlines():
            if line.startswith("export const FEATURE_FLAGS"):
                inside = True
                continue
            if not inside:
                continue
            if line.startswith("}"):
                break
            match = _FLAG_ENTRY.match(line)
            if match:
                keys[match.group(1)] = match.group(2)
        return keys

    def find_literals(
        self, literals: Sequence[str], *, whole_words: bool, excludes: Iterable[str] = DEFAULT_EXCLUDES
    ) -> list[Match]:
        if not literals:
            return []
        rg = shutil.which("rg")
        if rg is None:
            raise RuntimeError("ripgrep (rg) is required for reference scans")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("\n".join(literals) + "\n")
            pattern_file = handle.name
        args = [rg, "-n", "-o", "-F", "--no-messages", "-f", pattern_file]
        if whole_words:
            args.append("-w")
        for glob in excludes:
            args += ["--glob", f"!{glob}"]
        try:
            result = subprocess.run(args, cwd=self.root, capture_output=True, text=True, check=False)
        finally:
            Path(pattern_file).unlink(missing_ok=True)
        if result.returncode not in (0, 1):
            raise RuntimeError(f"rg failed: {result.stderr.strip()}")
        matches: list[Match] = []
        for raw in result.stdout.splitlines():
            path, _, rest = raw.partition(":")
            number, _, text = rest.partition(":")
            if not (number.isascii() and number.isdigit()):
                continue
            matches.append(Match(path=path, line_number=int(number), text=text))
        return matches

    def references_many(
        self, literals_by_key: dict[str, Sequence[str]], *, excludes: Iterable[str] = DEFAULT_EXCLUDES
    ) -> dict[str, ReferenceCount]:
        key_by_literal = {literal: key for key, literals in literals_by_key.items() for literal in literals}
        words = sorted(literal for literal in key_by_literal if _is_word(literal))
        others = sorted(literal for literal in key_by_literal if not _is_word(literal))
        matches = self.find_literals(words, whole_words=True, excludes=excludes)
        matches += self.find_literals(others, whole_words=False, excludes=excludes)
        files_by_key: dict[str, set[str]] = {key: set() for key in literals_by_key}
        totals: dict[str, int] = dict.fromkeys(literals_by_key, 0)
        for match in matches:
            key = key_by_literal.get(match.text)
            if key is None:
                continue
            files_by_key[key].add(match.path)
            totals[key] += 1
        return {
            key: ReferenceCount(files=tuple(sorted(files_by_key[key])), total=totals[key]) for key in literals_by_key
        }

    def last_real_commit(self, path: str, *, limit: int = 30) -> CommitStamp | None:
        raw = self._git("log", f"-n{limit}", "--format=%H%x09%cI%x09%ae%x09%s", "--", path)
        for line in raw.splitlines():
            sha, committed_at, email, subject = line.split("\t", 3)
            if self._files_in_commit(sha) >= SWEEP_FILE_THRESHOLD:
                continue
            return CommitStamp(
                sha=sha, committed_at=datetime.fromisoformat(committed_at), author_email=email, subject=subject
            )
        return None

    def _files_in_commit(self, sha: str) -> int:
        return len(self._git("show", "--format=", "--name-only", sha).splitlines())

    def list_directories(self, path: str) -> list[str]:
        base = self.root / path if path else self.root
        return sorted(
            entry.name
            for entry in base.iterdir()
            if entry.is_dir() and not entry.name.startswith(".") and entry.name not in _SKIP_DIRS
        )

    def tracked_line_count(self, path: str) -> int:
        files = [f for f in self._git("ls-files", "--", path).splitlines() if f]
        total = 0
        for file in files:
            try:
                with open(self.root / file, "rb") as handle:
                    total += sum(1 for _ in handle)
            except (OSError, UnicodeDecodeError):
                continue
        return total


_SKIP_DIRS = frozenset({"node_modules", "__pycache__", "generated", "migrations", "__snapshots__", "dist", "build"})


def _is_word(literal: str) -> bool:
    return bool(literal) and _WORD.match(literal[0]) is not None and _WORD.match(literal[-1]) is not None
