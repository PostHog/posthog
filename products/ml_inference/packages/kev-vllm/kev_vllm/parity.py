"""Parity between Kev's own inference path and the vLLM port.

    kev-vllm-parity reference --run jaredpalmer/kev-4b --records evals/public-pool-v6/test.jsonl --limit 32 --out ref.jsonl
    kev-vllm-parity local --checkpoint build/kev-4b --reference ref.jsonl --device mps
    kev-vllm-parity compare --base-url http://gpu-box:8000 --reference ref.jsonl

`local` runs the exported checkpoint through transformers on this machine, one row per question exactly as the
vLLM plugin builds them, so an export problem (weight names, dtype, head, tokenizer) shows up before a GPU is rented.
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

from kev_vllm.kev_compat import SystemOneRequest, encode, rows_of, to_answers, to_record

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


def report(pairs: list[tuple[list[float], list[float]]], tolerance: float, extra: dict) -> None:
    """Largest probability difference and argmax flips over (expected, got) pairs; exits non-zero past the tolerance."""
    worst, flips = 0.0, 0
    for expected, got in pairs:
        worst = max(worst, max(abs(a - b) for a, b in zip(expected, got, strict=True)))
        if max(range(len(expected)), key=expected.__getitem__) != max(range(len(got)), key=got.__getitem__):
            flips += 1
    print(json.dumps({"questions": len(pairs), "max_abs_prob_diff": round(worst, 5), "argmax_flips": flips, **extra}, indent=2))
    if worst > tolerance:
        raise SystemExit(f"max |dp| {worst:.4f} exceeds tolerance {tolerance}")


def local(args: argparse.Namespace) -> None:
    import torch
    from safetensors import safe_open
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

    from kev_vllm.decision import PointerReadout, readout_positions

    config = AutoConfig.from_pretrained(args.checkpoint)
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)
    dtype = {"bf16": torch.bfloat16, "fp32": torch.float32}[args.dtype]
    backbone = AutoModelForCausalLM.from_pretrained(args.checkpoint, dtype=dtype).model.to(args.device).eval()
    readout = PointerReadout(config.hidden_size, config.kev_head_dim, temperature=config.kev_temperature)
    with safe_open(str(Path(args.checkpoint) / "model.safetensors"), framework="pt") as f:
        readout.load_state_dict({k[len("head.") :]: f.get_tensor(k) for k in f.keys() if k.startswith("head.")})
    readout.to(args.device)
    pairs, latencies = [], []
    with args.reference.open() as f:
        for line in f:
            ref = json.loads(line)
            record, _ = to_record(SystemOneRequest.model_validate(ref["request"]))
            enc = encode(tokenizer, record, max_state=INFER_MAX_STATE, max_branch=INFER_MAX_BRANCH)
            if len(enc["ids"]) != ref["input_tokens"]:
                raise SystemExit(f"tokenization differs: {len(enc['ids'])} tokens here, {ref['input_tokens']} in the reference")
            state_ids, _, rows = rows_of(enc)
            start = time.time()
            for expected, row in zip(ref["probs"], rows, strict=True):
                ids = state_ids + row["ids"]
                with torch.no_grad():
                    hidden = backbone(input_ids=torch.tensor([ids], device=args.device)).last_hidden_state[0]
                decide, opts = readout_positions(ids, config.kev_box_end_token_id, config.kev_decide_token_id)
                pairs.append((expected, readout.probabilities(hidden, decide, opts).tolist()))
            latencies.append((time.time() - start) * 1000)
            print(f"{len(latencies)} records, {len(pairs)} questions", file=sys.stderr)
    latencies.sort()
    report(pairs, args.tolerance, {"p50_ms": round(latencies[len(latencies) // 2], 1), "dtype": args.dtype, "device": args.device})


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected the URL comes from the --base-url flag
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def served_model(base_url: str) -> str:
    with urllib.request.urlopen(f"{base_url}/v1/models", timeout=30) as resp:
        return json.load(resp)["data"][0]["id"]


def compare(args: argparse.Namespace) -> None:
    model = args.model or served_model(args.base_url)
    pairs, latencies = [], []
    with args.reference.open() as f:
        for line in f:
            ref = json.loads(line)
            start = time.time()
            data = post_json(f"{args.base_url}/pooling", {"model": model, "data": ref["request"]})["data"]
            latencies.append((time.time() - start) * 1000)
            if data["usage"]["input_tokens"] != ref["input_tokens"]:
                raise SystemExit(
                    f"tokenization differs: vLLM counted {data['usage']['input_tokens']} tokens, reference {ref['input_tokens']}"
                )
            pairs.extend(zip(ref["probs"], data["probabilities_raw"], strict=True))
    latencies.sort()
    report(
        pairs,
        args.tolerance,
        {"p50_ms": round(latencies[len(latencies) // 2], 1), "p95_ms": round(latencies[int(len(latencies) * 0.95)], 1)},
    )


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
    loc = sub.add_parser("local")
    loc.add_argument("--checkpoint", type=Path, required=True, help="directory written by kev-vllm-export")
    loc.add_argument("--reference", type=Path, required=True)
    loc.add_argument("--device", default="cpu")
    loc.add_argument("--dtype", choices=["bf16", "fp32"], default="bf16")
    loc.add_argument("--tolerance", type=float, default=0.02)
    loc.set_defaults(func=local)
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
