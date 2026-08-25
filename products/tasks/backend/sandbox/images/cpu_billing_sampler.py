#!/usr/bin/env python3

import os
import sys
import time
from pathlib import Path

CPU_STAT_PATH = Path("/sys/fs/cgroup/cpu.stat")
CPUACCT_USAGE_PATH = Path("/sys/fs/cgroup/cpuacct/cpuacct.usage")


def read_cpu_usage_usec() -> int:
    if CPU_STAT_PATH.exists():
        for line in CPU_STAT_PATH.read_text().splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            key, value = parts
            if key == "usage_usec":
                return int(value)
    if CPUACCT_USAGE_PATH.exists():
        return int(CPUACCT_USAGE_PATH.read_text()) // 1000
    raise RuntimeError("usage_usec missing")


def write_state(path: Path, billed_usec: int, cpu_usec: int, time_ns: int) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(f"{billed_usec} {cpu_usec} {time_ns}")
    os.replace(temporary_path, path)


def billed_interval_usec(
    request_cores: float, previous_cpu: int, current_cpu: int, previous_time: int, current_time: int
) -> int:
    actual_usec = current_cpu - previous_cpu
    floor_usec = round(request_cores * (current_time - previous_time) / 1000)
    return max(actual_usec, floor_usec)


def run(path: Path, request_cores: float) -> None:
    previous_cpu = read_cpu_usage_usec()
    previous_time = time.time_ns()
    billed_usec = 0
    write_state(path, billed_usec, previous_cpu, previous_time)

    while True:
        time.sleep(2)
        current_cpu = read_cpu_usage_usec()
        current_time = time.time_ns()
        billed_usec += billed_interval_usec(request_cores, previous_cpu, current_cpu, previous_time, current_time)
        write_state(path, billed_usec, current_cpu, current_time)
        previous_cpu = current_cpu
        previous_time = current_time


if __name__ == "__main__":
    run(Path(sys.argv[1]), float(sys.argv[2]))
