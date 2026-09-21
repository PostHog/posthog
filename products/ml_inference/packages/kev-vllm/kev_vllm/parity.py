"""Parity between Kev's own inference path and the vLLM port.

    kev-vllm-parity reference --run jaredpalmer/kev-4b --records evals/public-pool-v6/test.jsonl --limit 32 --out ref.jsonl
    kev-vllm-parity compare --base-url http://gpu-box:8000 --reference ref.jsonl

`reference` needs the `export` extra (it runs `kev` itself) and writes one line per record with the full-precision
probabilities. `compare` posts the same records to a vLLM server running this plugin and reports the largest
probability difference and any argmax flip. Kev's own bf16-versus-fp32 gap is 0.017 on its development rows, which
is the bar a bf16 vLLM deployment has to meet.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from kev_vllm.kev_compat import SystemOneRequest, to_answers, to_record

INFER_MAX_STATE, INFER_MAX_BRANCH = 8192, 8192


def read_requests(path: Path, limit: int | None) -> list[dict]:
    requests = []
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            requests.append(SystemOneRequest.model_validate(json.loads(line)).model_dump())
            if limit and len(requests) >= limit:
                break
    return requests


def reference(args: argparse.Namespace) -> None:
    from kev.checkpoint import Checkpoint, LoadOptions
    from kev.device import default_device, sync

    device = args.device or default_device()
    tokenizer, model = Checkpoint(args.run).load(device, LoadOptions.from_env())
    requests = read_requests(args.records, args.limit)
    with args.out.open("w") as out:
        for i, request in enumerate(requests):
            record, meta = to_record(SystemOneRequest.model_validate(request))
            enc = model.encode(tokenizer, record, max_state=INFER_MAX_STATE, max_branch=INFER_MAX_BRANCH)
            sync(device)
            start = time.time()
            probs = [p.tolist() for p in model.probs(enc)]
            sync(device)
            out.write(
                json.dumps(
                    {
                        "request": request,
                        "probs": probs,
                        "answers": to_answers(probs, meta),
                        "input_tokens": len(enc["ids"]),
                        "latency_ms": round((time.time() - start) * 1000, 1),
                    }
                )
                + "\n"
            )
            print(f"{i + 1}/{len(requests)} {len(enc['ids'])} tokens {(time.time() - start) * 1000:.0f} ms", file=sys.stderr)


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def served_model(base_url: str) -> str:
    with urllib.request.urlopen(f"{base_url}/v1/models", timeout=30) as resp:
        return json.load(resp)["data"][0]["id"]


def compare(args: argparse.Namespace) -> None:
    model = args.model or served_model(args.base_url)
    worst, flips, n_questions, latencies = 0.0, 0, 0, []
    with args.reference.open() as f:
        for line in f:
            ref = json.loads(line)
            start = time.time()
            data = post_json(f"{args.base_url}/pooling", {"model": model, "data": ref["request"]})["data"]
            latencies.append((time.time() - start) * 1000)
            for expected, got in zip(ref["probs"], data["probabilities_raw"], strict=True):
                n_questions += 1
                diff = max(abs(a - b) for a, b in zip(expected, got, strict=True))
                worst = max(worst, diff)
                if max(range(len(expected)), key=expected.__getitem__) != max(range(len(got)), key=got.__getitem__):
                    flips += 1
            if data["usage"]["input_tokens"] != ref["input_tokens"]:
                raise SystemExit(
                    f"tokenization differs: vLLM counted {data['usage']['input_tokens']} tokens, reference {ref['input_tokens']}"
                )
    latencies.sort()
    print(
        json.dumps(
            {
                "questions": n_questions,
                "max_abs_prob_diff": round(worst, 5),
                "argmax_flips": flips,
                "p50_ms": round(latencies[len(latencies) // 2], 1),
                "p95_ms": round(latencies[int(len(latencies) * 0.95)], 1),
            },
            indent=2,
        )
    )
    if worst > args.tolerance:
        raise SystemExit(f"max |dp| {worst:.4f} exceeds tolerance {args.tolerance}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ref = sub.add_parser("reference")
    ref.add_argument("--run", default="jaredpalmer/kev-4b")
    ref.add_argument("--records", type=Path, required=True, help="jsonl of /v1/systemone requests, for example a Kev eval split")
    ref.add_argument("--limit", type=int, default=32)
    ref.add_argument("--device", default=None)
    ref.add_argument("--out", type=Path, required=True)
    ref.set_defaults(func=reference)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--base-url", required=True)
    cmp_.add_argument("--reference", type=Path, required=True)
    cmp_.add_argument("--model", default=None)
    cmp_.add_argument("--tolerance", type=float, default=0.02)
    cmp_.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
