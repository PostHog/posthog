"""Per-job ``# hogli-lint: <marker> -- <reason>`` comments.

PyYAML drops comments, so a check that lets a job opt out with a reviewed
reason has to read the raw file. The marker must sit in the comment block
directly above the job key, at the job key's indent, and carry a reason.
"""

from __future__ import annotations

import re
from pathlib import Path

JOB_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<job>[A-Za-z0-9_\-]+):\s*$")
COMMENT_RE = re.compile(r"^(?P<indent>\s*)#(?P<body>.*)$")


def exempt_jobs(path: Path, job_names: frozenset[str], marker: str) -> frozenset[str]:
    """Job ids carrying ``marker``, with a reason, in the comments above them."""
    lines = path.read_text(encoding="utf-8").splitlines()
    candidates: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = JOB_KEY_RE.match(line)
        if match is not None and match.group("job") in job_names:
            candidates.append((index, len(match.group("indent")), match.group("job")))
    if not candidates:
        return frozenset()

    exempt: set[str] = set()
    job_indent = min(indent for _, indent, _ in candidates)
    for index, indent, job in candidates:
        if indent != job_indent:
            continue
        for above in reversed(lines[:index]):
            comment = COMMENT_RE.match(above)
            if comment is None or len(comment.group("indent")) != job_indent:
                break
            _, found, reason = comment.group("body").partition(marker)
            if found and reason.strip(" -—:"):
                exempt.add(job)
                break
    return frozenset(exempt)


__all__ = ["exempt_jobs"]
