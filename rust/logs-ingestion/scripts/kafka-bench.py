#!/usr/bin/env python3
"""Benchmarks three logs ingestion shapes on one Kafka topic per workload:

  node      the Node consumer (framework pipeline) on its own Kafka consumer
  rust      the Rust consumer loop of rust/logs-ingestion
  split       rust/ingestion-consumer dispatching over gRPC to the Rust logs worker
  split-gzip  the same with the consumer's default gzip of each frame

Every shape gets the same messages, in-memory dependencies and discarded outputs.
The measured span runs from the first message handed to the pipeline to the last one it
finished, so process start and the group join stay out. CPU and RSS are sampled from
/proc for every process of a shape over that span.

Needs Kafka on localhost:9092, Redis on 127.0.0.1:6379, and release builds of
logs-ingestion-kafka-bench and ingestion-consumer.

  kafka-bench.py <workloads_dir> <out_dir> [--passes N] [--rounds N] [--partitions N]
                 [--cpus 1-3] [--shapes node,rust,split,split-gzip] [--workloads a,b]
"""

import os
import sys
import json
import time
import signal
import argparse
import threading
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RELEASE = REPO / "rust" / "target" / "release"
BENCH = str(RELEASE / "logs-ingestion-kafka-bench")
CONSUMER = str(RELEASE / "ingestion-consumer")
BROKERS = "localhost:9092"
TICKS_PER_S = os.sysconf("SC_CLK_TCK")
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024


def descendants(root: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry}/stat").read_text()
        except OSError:
            continue
        parent = int(stat.rsplit(")", 1)[1].split()[1])
        children.setdefault(parent, []).append(int(entry))
    found, queue = [], [root]
    while queue:
        pid = queue.pop()
        found.append(pid)
        queue.extend(children.get(pid, []))
    return found


class Sampler(threading.Thread):
    """Samples CPU ticks and RSS of each root process and its descendants."""

    def __init__(self, roots: dict[str, int]):
        super().__init__(daemon=True)
        self.roots = roots
        self.samples: dict[str, list[tuple[float, float, float]]] = {name: [] for name in roots}
        self.stopped = threading.Event()

    def run(self) -> None:
        # A child that exits takes its ticks out of /proc, so each pid's last reading is kept.
        last_ticks: dict[str, dict[int, float]] = {name: {} for name in self.roots}
        while not self.stopped.is_set():
            now = time.time()
            for name, root in self.roots.items():
                rss_kb = 0.0
                for pid in descendants(root):
                    try:
                        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                    except OSError:
                        continue
                    last_ticks[name][pid] = float(fields[11]) + float(fields[12])
                    rss_kb += float(fields[21]) * PAGE_KB
                self.samples[name].append((now, sum(last_ticks[name].values()), rss_kb))
            time.sleep(0.02)

    def cpu_ms(self, name: str, start: float, end: float) -> float:
        def ticks_at(moment: float) -> float:
            before = [s for s in self.samples[name] if s[0] <= moment]
            after = [s for s in self.samples[name] if s[0] > moment]
            if not before:
                return after[0][1]
            if not after:
                return before[-1][1]
            (t0, c0, _), (t1, c1, _) = before[-1], after[0]
            return c0 + (c1 - c0) * (moment - t0) / (t1 - t0)

        return (ticks_at(end) - ticks_at(start)) * 1000 / TICKS_PER_S

    def peak_rss_mb(self, name: str) -> float:
        return max((s[2] for s in self.samples[name]), default=0.0) / 1024


def lag(topic: str, group: str) -> int:
    out = subprocess.run([BENCH, "lag", BROKERS, topic, group], capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def wait_for(path: Path, processes: list[subprocess.Popen], timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text())
        for process in processes:
            if process.poll() not in (None, 0):
                raise RuntimeError(f"{process.args[0]} exited with {process.returncode}")
        time.sleep(0.05)
    raise TimeoutError(f"no result in {timeout_s}s")


def stop(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def run_shape(shape: str, workload: Path, topic: str, expected: int, args, log_dir: Path, tag: str) -> dict:
    group = f"bench-{tag}"
    result_path = log_dir / f"{tag}.window.json"
    result_path.unlink(missing_ok=True)
    pin = ["taskset", "-c", args.cpus]
    batch_env = {"CONSUMER_BATCH_SIZE": str(args.batch_size)}

    def spawn(name: str, command: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.Popen:
        log = open(log_dir / f"{tag}.{name}.log", "w")
        return subprocess.Popen(
            pin + command, env={**os.environ, **env}, cwd=cwd, stdout=log, stderr=log, start_new_session=True
        )

    processes: dict[str, subprocess.Popen] = {}
    if shape == "node":
        processes["node"] = spawn(
            "node",
            [
                "node_modules/.bin/tsx",
                "--tsconfig",
                "tsconfig.json",
                "src/logs/benchmarks/logs-kafka-bench.ts",
                str(workload),
                topic,
                group,
                str(expected),
                str(result_path),
            ],
            {
                **batch_env,
                "CONSUMER_MAX_BACKGROUND_TASKS": str(args.concurrency),
                "CONSUMER_USE_V2": "true",
                "KAFKA_CONSUMER_METADATA_BROKER_LIST": BROKERS,
                "KAFKA_HOSTS": BROKERS,
                "DATABASE_URL": "postgres://bench:bench@127.0.0.1:1/unused",
                "LOG_LEVEL": "warn",
                "NODE_ENV": "production",
            },
            cwd=REPO / "nodejs",
        )
    elif shape == "rust":
        processes["rust"] = spawn(
            "rust",
            [BENCH, "monolith", str(workload), BROKERS, topic, group, str(expected), str(result_path)],
            {**batch_env, "CONSUMER_MAX_BACKGROUND_TASKS": str(args.concurrency)},
        )
    elif shape in ("split", "split-gzip"):
        http_port, grpc_port = 9101, 9201
        processes["worker"] = spawn(
            "worker",
            [BENCH, "worker", str(workload), str(http_port), str(grpc_port), str(expected), str(result_path)],
            {"INGESTION_WORKER_CONCURRENT_BATCHES": str(args.concurrency)},
        )
        time.sleep(1)
        processes["consumer"] = spawn(
            "consumer",
            [CONSUMER],
            {
                **batch_env,
                "HOSTNAME": "bench",
                "KAFKA_HOSTS": BROKERS,
                "INGESTION_CONSUMER_GROUP_ID": group,
                "INGESTION_CONSUMER_CONSUME_TOPIC": topic,
                "KAFKA_CONSUMER_AUTO_OFFSET_RESET": "earliest",
                "CONSUMER_BINARY_VALUES": "true",
                "INGESTION_TRANSPORT_GZIP": "true" if shape == "split-gzip" else "false",
                "WORKER_ADDRESSES": f"http://127.0.0.1:{http_port}",
                "INGESTION_WORKER_GRPC_PORT": str(grpc_port),
                "INGESTION_WORKER_CONCURRENT_BATCHES": str(args.concurrency),
                "INGESTION_PACK_TARGET_EVENTS": str(args.batch_size),
                "CONSUMER_PARTITION_BUDGET_EVENTS": "20000",
                "CONSUMER_PARTITION_BUDGET_BYTES": str(256 * 1024 * 1024),
                "CONSUMER_IN_FLIGHT_EVENTS": "40000",
                "CONSUMER_IN_FLIGHT_BYTES": str(512 * 1024 * 1024),
                "BIND_PORT": "9301",
                "CONTINUOUS_PROFILING_ENABLED": "false",
            },
        )
    else:
        raise ValueError(shape)

    sampler = Sampler({name: process.pid for name, process in processes.items()})
    sampler.start()
    try:
        window = wait_for(result_path, list(processes.values()), args.timeout)
        # The split consumer commits on its own interval after the worker's last ack.
        deadline = time.time() + 30
        remaining = lag(topic, group)
        while remaining != 0 and time.time() < deadline and shape.startswith("split"):
            time.sleep(0.25)
            remaining = lag(topic, group)
    finally:
        sampler.stopped.set()
        sampler.join()
        stop(list(processes.values()))
    if not shape.startswith("split"):
        remaining = lag(topic, group)

    start, end = window["first_ms"] / 1000, window["last_ms"] / 1000
    cpu = {name: sampler.cpu_ms(name, start, end) for name in processes}
    return {
        "shape": shape,
        "workload": workload.stem,
        "messages": window["messages"],
        "batches": window["batches"],
        "wall_ms": window["last_ms"] - window["first_ms"],
        "cpu_ms": cpu,
        "cpu_ms_total": sum(cpu.values()),
        # Includes process start, as a check that little work falls before the measured span.
        "cpu_ms_from_start": {name: sampler.cpu_ms(name, 0, end) for name in processes},
        "peak_rss_mb": {name: sampler.peak_rss_mb(name) for name in processes},
        "uncommitted_after": remaining,
    }


def median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workloads_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--passes", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--partitions", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--cpus", default="1-3")
    parser.add_argument("--shapes", default="node,rust,split,split-gzip")
    parser.add_argument("--workloads", default="")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--topic-prefix", default="logs-bench")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wanted = [w for w in args.workloads.split(",") if w]
    workloads = [p for p in sorted(args.workloads_dir.glob("*.json")) if not wanted or p.stem in wanted]
    results = []
    for workload in workloads:
        topic = f"{args.topic_prefix}-{workload.stem}-p{args.partitions}-x{args.passes}"
        totals_path = args.out_dir / f"{topic}.produced.json"
        if not totals_path.exists():
            produced = subprocess.run(
                [BENCH, "produce", str(workload), BROKERS, topic, str(args.partitions), str(args.passes)],
                capture_output=True,
                text=True,
                check=True,
            )
            totals_path.write_text(produced.stdout)
        totals = json.loads(totals_path.read_text())
        for round_index in range(1, args.rounds + 1):
            # Shapes alternate within a round, so a noisy stretch skews one sample of each.
            for shape in args.shapes.split(","):
                tag = f"{workload.stem}-{shape}-c{args.concurrency}-r{round_index}-{int(time.time())}"
                result = run_shape(shape, workload, topic, totals["messages"], args, args.out_dir, tag)
                result.update(
                    records=totals["records"],
                    input_bytes=totals["input_bytes"],
                    round=round_index,
                    concurrency=args.concurrency,
                    batch_size=args.batch_size,
                )
                results.append(result)
                seconds = result["wall_ms"] / 1000
                sys.stdout.write(
                    f"{tag}: {totals['records'] / seconds:,.0f} records/s, "
                    f"{result['cpu_ms_total'] / totals['records'] * 1000:.2f} CPU ms per 1k records, "
                    f"uncommitted {result['uncommitted_after']}\n"
                )
                sys.stdout.flush()
                (args.out_dir / "results.jsonl").open("a").write(json.dumps(result) + "\n")

    lines = [
        f"Median of {args.rounds} rounds. {args.partitions} partitions, batch size {args.batch_size}, "
        f"{args.concurrency} concurrent batches, shapes pinned to CPUs {args.cpus}.",
        "",
        "| workload | shape | records/s | MB/s in | CPU ms / 1k records | CPU split | cores used | peak RSS MB | vs node |",
        "|---|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    for workload in workloads:
        rows = {}
        for shape in args.shapes.split(","):
            runs = [r for r in results if r["workload"] == workload.stem and r["shape"] == shape]
            if runs:
                rows[shape] = sorted(runs, key=lambda r: r["wall_ms"])[len(runs) // 2]
        for shape, r in rows.items():
            seconds = r["wall_ms"] / 1000
            rate = r["records"] / seconds
            base = rows.get("node")
            speedup = f"{rate / (base['records'] / (base['wall_ms'] / 1000)):.2f}x" if base else ""
            split = ", ".join(f"{name} {ms / r['records'] * 1000:.2f}" for name, ms in r["cpu_ms"].items())
            lines.append(
                f"| {workload.stem} | {shape} | {rate:,.0f} | {r['input_bytes'] / 1048576 / seconds:.1f} | "
                f"{r['cpu_ms_total'] / r['records'] * 1000:.2f} | {split} | {r['cpu_ms_total'] / r['wall_ms']:.2f} | "
                f"{sum(r['peak_rss_mb'].values()):.0f} | {speedup} |"
            )
    report = "\n".join(lines) + "\n"
    (args.out_dir / "results.md").write_text(report)
    sys.stdout.write(report)


if __name__ == "__main__":
    main()
