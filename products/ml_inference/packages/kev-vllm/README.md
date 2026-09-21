# kev-vllm

Serves [Kev](https://github.com/jaredpalmer/kev) decision models on vLLM. Kev is Qwen3.5 plus a LoRA and a pointer head: one `state`, several typed questions, a calibrated probability per question, no generated text. The design behind this package is in [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).

Three parts:

- `kev_vllm.model`: `KevForDecision`, a vLLM pooling model on the stock Qwen3.5 class. Its pooler reads the option-end and decide token hidden states of each row and applies the head, so vLLM batches rows across requests.
- `kev_vllm.io_processor`: a vLLM IO-processor plugin that accepts a TypeSafe `/v1/systemone` request on the `/pooling` endpoint, encodes it exactly as Kev does (one causal row per question), and returns Kev's answer shape plus `probabilities_raw`.
- `kev_vllm.export`, `kev_vllm.upload`, `kev_vllm.parity`: turn a Kev checkpoint into a vLLM-loadable directory, publish it to the ML training account's base-models bucket, and check the served probabilities against Kev's own path.

`kev_vllm/kev_compat.py` is vendored from Kev (Apache-2.0) because the `kev` package pins a torch version vLLM cannot use.

## Export a checkpoint

```bash
uv run --extra export kev-vllm-export --run jaredpalmer/kev-4b --out build/kev-4b
```

Downloads the base model and adapter, merges the LoRA in fp32 the way `kev.serve` does, casts to bf16, and writes `config.json`, `model.safetensors`, the tokenizer, and `manifest.json` with every hash. About 16 GB of RAM and 20 GB of disk.

## Publish it

```bash
uv run kev-vllm-upload --src build/kev-4b --profile ml-prod-us-write
```

Writes to `s3://posthog-ml-training-prod-us-east-1-base-models/posthog/kev-4b-vllm/<kev Hub revision>/` and a `checksums.tsv` under `_provenance/`. It refuses a prefix that already has content, so a new export is a new version. The profile needs write access to the ML training account.

## Serve

On a CUDA box with the `serve` extra installed (`uv sync --extra serve`), the entry points register the model class and the IO processor on import:

```bash
vllm serve /models/kev-4b --served-model-name kev-4b --mamba-ssm-cache-dtype float32 --port 8000
```

`config.json` names the IO processor (`io_processor_plugin: "kev"`), so no extra flag is needed. Then:

```bash
curl -s localhost:8000/pooling -H 'content-type: application/json' -d '{"model": "kev-4b", "data": {"state": "It has been two weeks and the refund has not arrived.", "questions": {"refund": {"type": "noul", "instructions": "Is the customer asking about a refund?"}}}}'
```

The answer is under `data.answers`, in Kev's format, with `data.probabilities_raw` alongside for parity checks.

Prefix caching is off for this model: vLLM does not enable it for pooling models on hybrid backbones, so every row recomputes its state. Batching across rows and requests still applies.

## GPU smoke test

`bin/gpu-smoke.sh` does the whole loop on a fresh CUDA box: installs the `serve` environment, fetches and checksums the checkpoint, starts the server, sends one request, and runs the parity comparison.

```bash
CHECKPOINT=s3://posthog-ml-training-prod-us-east-1-base-models/posthog/kev-4b-vllm/<version> REFERENCE=reference-fp32.jsonl bin/gpu-smoke.sh
```

## Parity

```bash
uv run --extra export kev-vllm-parity reference --run jaredpalmer/kev-4b --records <kev repo>/evals/public-pool-v6/test.jsonl --limit 32 --out ref.jsonl
uv run kev-vllm-parity compare --base-url http://<gpu box>:8000 --reference ref.jsonl
```

The comparison fails above a 0.02 maximum probability difference, just past Kev's own measured bf16-versus-fp32 gap of 0.017.

## Tests

```bash
uv run --group dev pytest
```

These run on a CPU without vLLM: the row layout, the readout math, and the request-to-answer mapping. The vLLM classes are exercised by the parity run on a GPU. This package is not part of the monorepo's uv workspace or its CI test matrix.
