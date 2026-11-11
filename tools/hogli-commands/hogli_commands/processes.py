from __future__ import annotations

import subprocess
from collections.abc import Sequence


def process_cwds(pids: Sequence[int]) -> dict[int, str]:
    """Map each pid to its working directory via a single lsof call.

    ``-a`` ANDs the ``-p`` (pid set) and ``-d cwd`` (fd) selectors; without it
    lsof ORs them and reports *every* process's cwd — slow (a full-system scan
    per pid) and wrong (attributing the first process's cwd to the queried pid).
    ``-Fpn`` emits pid/name fields so each cwd attributes back to its pid; with
    ``-d cwd`` each process yields exactly one name line.
    """
    if not pids:
        return {}

    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", ",".join(str(pid) for pid in pids), "-d", "cwd", "-Fpn"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {}

    # lsof exits non-zero when any queried pid has vanished, but still emits valid
    # records for the survivors — parse whatever stdout we got.
    cwds: dict[int, str] = {}
    current: int | None = None
    for line in result.stdout.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            current = int(value) if value.isdigit() else None
        elif tag == "n" and current is not None:
            cwds[current] = value
    return cwds
