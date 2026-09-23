"""Export a Kev checkpoint (Hub id or run directory) as a vLLM-loadable directory.

    kev-vllm-export --run jaredpalmer/kev-4b --out build/kev-4b

Loads the checkpoint exactly the way `kev.serve` does (fp32 backbone, LoRA merged in fp32, head and calibration
temperature from `head.pt`), casts the backbone to bf16, and writes:

    config.json         text-only Qwen3.5 config, architectures=["KevForDecision"], plus the kev_* fields
    model.safetensors   backbone under `model.*` (bf16), pointer head under `head.*` (fp32)
    tokenizer files     the base model's tokenizer, as the checkpoint pins it
    manifest.json       what went in: run, Hub revision, base revision, adapter and head hashes, file hashes

Needs the `export` extra (the `kev` package and its pinned torch), so run it in its own environment:
`uv run --extra export kev-vllm-export ...`.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import torch

from kev_vllm import __version__
from kev_vllm.kev_compat import KEV_SOURCE_COMMIT, SPECIAL

ARCHITECTURE = "KevForDecision"
IO_PROCESSOR_PLUGIN = "kev"
DTYPES = {"bf16": torch.bfloat16, "fp32": torch.float32}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hub_revision(resolved_path: str) -> str | None:
    """The commit a Hub snapshot was downloaded at: `.../snapshots/<sha>` in the HF cache. None for a local run."""
    path = Path(resolved_path)
    return path.name if path.parent.name == "snapshots" else None


def export(run: str, out: Path, dtype: torch.dtype) -> dict:
    from kev.checkpoint import Checkpoint, LoadOptions

    checkpoint = Checkpoint(run)
    meta = checkpoint.meta
    if meta.option_isolation:
        raise ValueError("option isolation needs the packed mask and is not available on the row form vLLM runs")
    tokenizer, model = checkpoint.load("cpu", LoadOptions(dtype=None, merge=True))
    if not model.hybrid:
        raise ValueError("only Qwen3.5 hybrid backbones are supported; the packed-mask form is not ported")
    backbone = model.lm
    config = backbone.config.to_dict()
    config.update(
        {
            "architectures": [ARCHITECTURE],
            "tie_word_embeddings": True,
            "dtype": "bfloat16" if dtype is torch.bfloat16 else "float32",
            "io_processor_plugin": IO_PROCESSOR_PLUGIN,
            "kev_head_dim": meta.head_dim,
            "kev_temperature": float(model.head.temperature),
            "kev_special_tokens": SPECIAL,
            "kev_box_end_token_id": tokenizer.convert_tokens_to_ids(SPECIAL[3]),
            "kev_decide_token_id": tokenizer.convert_tokens_to_ids(SPECIAL[4]),
            "kev_base": meta.base,
            "kev_base_revision": meta.base_revision,
        }
    )
    out.mkdir(parents=True, exist_ok=True)

    from safetensors.torch import save_file

    state = {f"model.{name}": tensor.to(dtype).contiguous() for name, tensor in backbone.state_dict().items()}
    state.update({f"head.{name}": tensor.float().contiguous() for name, tensor in model.head.state_dict().items()})
    save_file(state, str(out / "model.safetensors"), metadata={"format": "pt"})
    del state
    (out / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    tokenizer.save_pretrained(out)

    manifest = {
        "architecture": ARCHITECTURE,
        "kev_run": checkpoint.requested,
        "kev_hub_revision": hub_revision(checkpoint.path),
        "kev_source_commit": KEV_SOURCE_COMMIT,
        "kev_vllm_version": __version__,
        "base": meta.base,
        "base_revision": meta.base_revision,
        "lora_rank": meta.lora,
        "head_dim": meta.head_dim,
        "temperature": float(model.head.temperature),
        "weights_dtype": "bfloat16" if dtype is torch.bfloat16 else "float32",
        "adapter_sha256": sha256_of(checkpoint.file("adapter_model.safetensors")),
        "head_sha256": sha256_of(checkpoint.file("head.pt")),
        "exported_at": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "files": {},
    }
    for path in sorted(p for p in out.iterdir() if p.is_file() and p.name != "manifest.json"):
        manifest["files"][path.name] = {"sha256": sha256_of(path), "size_bytes": path.stat().st_size}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify(out: Path) -> None:
    """The exported directory must load as a config transformers knows and as a safetensors file vLLM can read."""
    from safetensors import safe_open
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(out)
    if config.architectures != [ARCHITECTURE]:
        raise ValueError(f"config.json architectures is {config.architectures}")
    with safe_open(str(out / "model.safetensors"), framework="pt") as f:
        keys = list(f.keys())
    head = [k for k in keys if k.startswith("head.")]
    if sorted(head) != ["head.k.bias", "head.k.weight", "head.q.bias", "head.q.weight"]:
        raise ValueError(f"unexpected head tensors: {head}")
    print(f"ok: {len(keys)} tensors, model_type={config.model_type}, {len(config.layer_types)} layers")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", default="jaredpalmer/kev-4b", help="Hub id (optionally @revision) or a local run directory")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dtype", choices=DTYPES, default="bf16")
    args = parser.parse_args()
    manifest = export(args.run, args.out, DTYPES[args.dtype])
    verify(args.out)
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
