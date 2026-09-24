"""Export JevK5 from the Hugging Face Hub as a directory the serving image loads.

    jevk5-vllm-export --revision 27d2d6b8d4714807f6293b0623bd7370b27e42f8 --out build/jevk5-4b

JevK5's weights are already a merged, text-only Qwen3.5 checkpoint, so they are copied unchanged. The export pins a
Hub commit, checks every LFS file against the sha256 the Hub records, and points config.json at this package's model
class and IO processor:

    config.json         JevK5's config with architectures=["JevK5ForDecision"] and the jevk5_* fields
    model.safetensors   JevK5's weights, unchanged (bf16; `--dtype float16` casts them at load on GPUs without bf16)
    tokenizer files     as JevK5 ships them, including chat_template.jinja
    manifest.json       source repo and revision, file hashes

Needs only the base dependencies, so it runs on a machine without a GPU.
"""

import argparse
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download
from transformers import AutoTokenizer

from kev_vllm import __version__
from kev_vllm.checkpoint import sha256_of
from kev_vllm.jevk5 import letter_token_ids

SOURCE_REPO = "alibiserikbay/JevK5"
ARCHITECTURE = "JevK5ForDecision"
IO_PROCESSOR_PLUGIN = "jevk5"
FILES = [
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "generation_config.json",
    "jevk5_config.json",
    "README.md",
]


def export(repo: str, revision: str, out: Path) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("pin a full 40-character commit, not a branch or tag")
    out.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo, revision=revision, allow_patterns=FILES, local_dir=out)
    # The Hub client's download bookkeeping; an uploader copying the directory must not publish it.
    shutil.rmtree(out / ".cache", ignore_errors=True)

    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    for sibling in info.siblings or []:
        if sibling.rfilename in FILES and sibling.lfs is not None:
            if sha256_of(out / sibling.rfilename) != sibling.lfs.sha256:
                raise ValueError(f"{sibling.rfilename} does not match the sha256 the Hub records at {revision}")

    config = json.loads((out / "config.json").read_text())
    if config.get("architectures") != ["Qwen3_5ForCausalLM"]:
        raise ValueError(f"expected a text-only Qwen3.5 causal LM, got {config.get('architectures')}")
    temperature = json.loads((out / "jevk5_config.json").read_text())["temperature"]
    config.update(
        {
            "architectures": [ARCHITECTURE],
            "io_processor_plugin": IO_PROCESSOR_PLUGIN,
            "jevk5_temperature": float(temperature),
            "jevk5_letter_token_ids": letter_token_ids(AutoTokenizer.from_pretrained(out)),
            "jevk5_source": {"repo": repo, "revision": revision},
        }
    )
    (out / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    manifest = {
        "model": "jevk5",
        "source_repo": repo,
        "source_revision": revision,
        "kev_vllm_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": {},
    }
    for name in FILES:
        path = out / name
        manifest["files"][name] = {"sha256": sha256_of(path), "size_bytes": path.stat().st_size}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=SOURCE_REPO)
    parser.add_argument("--revision", required=True, help="full Hub commit sha")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = export(args.repo, args.revision, args.out)
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
