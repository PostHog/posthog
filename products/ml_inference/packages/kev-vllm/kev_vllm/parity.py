"""Check an exported checkpoint against Kev's own inference path, on this machine, before any GPU is rented.

    kev-vllm-parity local --checkpoint build/kev-4b --reference ref.jsonl --device mps

`local` runs the exported directory through transformers, one row per question exactly as the vLLM plugin builds
them, so an export problem (weight names, dtype, head, tokenizer) shows up here. The reference file comes from the
MLHog repo's `models/kev/parity.py reference`, which runs `kev` itself at full precision; the same repo's `compare`
posts the records to a served model. Kev's own bf16-versus-fp32 gap is 0.017 on its development rows, which is the
bar a bf16 deployment has to meet.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from kev_vllm.kev_compat import SystemOneRequest, encode, rows_of, to_record

INFER_MAX_STATE, INFER_MAX_BRANCH = 8192, 8192


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    loc = sub.add_parser("local")
    loc.add_argument("--checkpoint", type=Path, required=True, help="directory written by kev-vllm-export")
    loc.add_argument("--reference", type=Path, required=True)
    loc.add_argument("--device", default="cpu")
    loc.add_argument("--dtype", choices=["bf16", "fp32"], default="bf16")
    loc.add_argument("--tolerance", type=float, default=0.02)
    loc.set_defaults(func=local)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
