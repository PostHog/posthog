"""Closed-loop load test against a running server: N workers each send requests back to back.

    python bin/load_generator.py --base-url http://localhost:8000 --records build/parity-records.jsonl --concurrency 1 8 32 64

Records are /v1/systemone requests (one per line). Prints requests per second and latency percentiles per
concurrency level. Stdlib only, so it runs with any environment on the box.
"""

import argparse
import json
import statistics
import threading
import time
import urllib.request
from pathlib import Path


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected the URL comes from the --base-url flag
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def run_level(base_url: str, model: str, requests: list[dict], concurrency: int, total: int) -> dict:
    latencies: list[float] = []
    lock = threading.Lock()
    counter = {"next": 0}

    def worker() -> None:
        while True:
            with lock:
                i = counter["next"]
                if i >= total:
                    return
                counter["next"] += 1
            payload = {"model": model, "data": requests[i % len(requests)]}
            start = time.perf_counter()
            post(f"{base_url}/pooling", payload)
            elapsed = (time.perf_counter() - start) * 1000
            with lock:
                latencies.append(elapsed)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    wall = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - wall
    latencies.sort()
    return {
        "concurrency": concurrency,
        "requests": total,
        "rps": round(total / wall, 1),
        "p50_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 1),
        "max_ms": round(latencies[-1], 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="kev-4b")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 8, 32, 64])
    parser.add_argument("--requests-per-level", type=int, default=256)
    args = parser.parse_args()
    requests = [json.loads(line) for line in args.records.open() if line.strip()]
    tokens = None
    for level in args.concurrency:
        result = run_level(args.base_url, args.model, requests, level, args.requests_per_level)
        if tokens is None:
            tokens = post(f"{args.base_url}/pooling", {"model": args.model, "data": requests[0]})["data"]["usage"]["input_tokens"]
        result["input_tokens_first_record"] = tokens
        print(json.dumps(result))


if __name__ == "__main__":
    main()
