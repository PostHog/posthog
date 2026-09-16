import re
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
class GrepLine:
    path: str
    line_number: int
    content: str


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

    def grep(self, patterns: Sequence[str], *, excludes: Iterable[str] = DEFAULT_EXCLUDES) -> list[GrepLine]:
        if not patterns:
            return []
        args = ["grep", "-n", "-I", "-w", "-F"]
        for pattern in patterns:
            args += ["-e", pattern]
        args += ["--", "."]
        args += [f":(exclude,glob){glob}" for glob in excludes]
        lines: list[GrepLine] = []
        for raw in self._git(*args).splitlines():
            path, _, rest = raw.partition(":")
            number, _, content = rest.partition(":")
            if not number.isdigit():
                continue
            lines.append(GrepLine(path=path, line_number=int(number), content=content))
        return lines

    def references_many(
        self, patterns_by_key: dict[str, Sequence[str]], *, excludes: Iterable[str] = DEFAULT_EXCLUDES
    ) -> dict[str, ReferenceCount]:
        all_patterns = sorted({p for patterns in patterns_by_key.values() for p in patterns})
        lines = self.grep(all_patterns, excludes=excludes)
        files_by_key: dict[str, set[str]] = {key: set() for key in patterns_by_key}
        totals: dict[str, int] = dict.fromkeys(patterns_by_key, 0)
        for line in lines:
            for key, patterns in patterns_by_key.items():
                if any(_contains_word(line.content, pattern) for pattern in patterns):
                    files_by_key[key].add(line.path)
                    totals[key] += 1
        return {
            key: ReferenceCount(files=tuple(sorted(files_by_key[key])), total=totals[key]) for key in patterns_by_key
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


def _contains_word(haystack: str, needle: str) -> bool:
    start = 0
    while (index := haystack.find(needle, start)) != -1:
        before = haystack[index - 1] if index else ""
        after = haystack[index + len(needle) : index + len(needle) + 1]
        starts_clean = not (_WORD.match(needle[0]) and _WORD.match(before))
        ends_clean = not (_WORD.match(needle[-1]) and _WORD.match(after))
        if starts_clean and ends_clean:
            return True
        start = index + 1
    return False
