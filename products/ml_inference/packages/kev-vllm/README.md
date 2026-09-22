# kev-vllm

Serves [Kev](https://github.com/jaredpalmer/kev) decision models on vLLM. Kev is Qwen3.5 plus a LoRA and a pointer head: one `state`, several typed questions, a calibrated probability per question, no generated text. The serving design around it is documented internally.

Three parts:

- `kev_vllm.model`: `KevForDecision`, a vLLM pooling model on the stock Qwen3.5 class. Its pooler reads the option-end and decide token hidden states of each row and applies the head, so vLLM batches rows across requests.
- `kev_vllm.io_processor`: a vLLM IO-processor plugin that accepts a TypeSafe `/v1/systemone` request on the `/pooling` endpoint, encodes it exactly as Kev does (one causal row per question), and returns Kev's answer shape plus `probabilities_raw`.
- `kev_vllm.export`, `kev_vllm.upload`, `kev_vllm.parity`: turn a Kev checkpoint into a vLLM-loadable directory, publish it to an S3 bucket, and check the served probabilities against Kev's own path.

`kev_vllm/kev_compat.py` is vendored from Kev (Apache-2.0) because the `kev` package pins a torch version vLLM cannot use.

## Export a checkpoint

```bash
uv run --extra export kev-vllm-export --run jaredpalmer/kev-4b --out build/kev-4b
```

Downloads the base model and adapter, merges the LoRA in fp32 the way `kev.serve` does, casts to bf16, and writes `config.json`, `model.safetensors`, the tokenizer, and `manifest.json` with every hash. About 16 GB of RAM and 20 GB of disk.

## Publish it

```bash
uv run kev-vllm-upload --src build/kev-4b --bucket <bucket>
```

Writes to `s3://<bucket>/posthog/kev-4b-vllm/<kev Hub revision>/` and a `checksums.tsv` under `_provenance/`, the layout the bucket uses for mirrored model weights. It refuses a prefix that already has content, so a new export is a new version. Credentials come from the ambient AWS chain or `--profile`; the bucket from `--bucket` or `KEV_VLLM_BUCKET`.

When the export sits on a GPU box with a fast pipe and no AWS credentials, `bin/upload_via_box.py` publishes it from there: this machine creates the multipart upload, presigns one URL per part and per small file, the box PUTs them in parallel over ssh-delivered URLs, and this machine completes the upload and writes the provenance file. The 8.4 GB Kev-4B checkpoint took 37 seconds from a Lambda instance. The URLs must be SigV4; SigV2 signs the content type and fails with `SignatureDoesNotMatch`.

```bash
uv run python bin/upload_via_box.py --host ubuntu@<ip> --key ~/.ssh/<key> --remote-src /home/ubuntu/kev-vllm/build/kev-4b --bucket <bucket>
```

## Serve

On a CUDA box with the `serve` extra installed (`uv sync --extra serve`), the entry points register the model class and the IO processor on import:

```bash
VLLM_USE_V2_MODEL_RUNNER=0 vllm serve /models/kev-4b --served-model-name kev-4b --mamba-ssm-cache-dtype float32 --port 8000
```

`VLLM_USE_V2_MODEL_RUNNER=0` is required on vLLM 0.29: its new model runner does not run the `plugin` pooling task that IO processors use.

`config.json` names the IO processor (`io_processor_plugin: "kev"`), so no extra flag is needed. Then:

```bash
curl -s localhost:8000/pooling -H 'content-type: application/json' -d '{"model": "kev-4b", "data": {"state": "It has been two weeks and the refund has not arrived.", "questions": {"refund": {"type": "noul", "instructions": "Is the customer asking about a refund?"}}}}'
```

The answer is under `data.answers`, in Kev's format, with `data.probabilities_raw` alongside for parity checks.

Prefix caching is off for this model: vLLM does not enable it for pooling models on hybrid backbones, so every row recomputes its state. Batching across rows and requests still applies.

## GPU smoke test

`bin/gpu-smoke.sh` does the whole loop on a fresh CUDA box: installs the `serve` environment, fetches and checksums the checkpoint, starts the server, sends one request, and runs the parity comparison.

```bash
CHECKPOINT=s3://<bucket>/posthog/kev-4b-vllm/<version> REFERENCE=reference-fp32.jsonl bin/gpu-smoke.sh
```

## Parity

```bash
uv run --extra export kev-vllm-parity reference --run jaredpalmer/kev-4b --records <kev repo>/evals/public-pool-v6/test.jsonl --limit 32 --out ref.jsonl
uv run kev-vllm-parity compare --base-url http://<gpu box>:8000 --reference ref.jsonl
```

The comparison fails above a 0.02 maximum probability difference, just past Kev's own measured bf16-versus-fp32 gap of 0.017.

`local` runs the exported directory through transformers on this machine instead of a server, which checks the export itself before any GPU is involved. Measured 2026-09-21 for `jaredpalmer/kev-4b` at Hub revision `485ace87`, 32 records from `evals/public-pool-v6/test.jsonl` (one 77-way choice each, median 762 tokens), against Kev's fp32 path on the same Mac:

| Export check                    | Max probability difference | Argmax flips                                         |
| ------------------------------- | -------------------------- | ---------------------------------------------------- |
| fp32 weights                    | 0.0043                     | 0                                                    |
| bf16 weights (what vLLM serves) | 0.0111                     | 1, on a record whose top two options differ by 0.005 |

Measured 2026-09-22 on a Lambda 2x H100 SXM instance (one GPU used), vLLM 0.29.0, V1 model runner, `--mamba-ssm-cache-dtype float32`, same 32 records through the served `/pooling` endpoint:

| Served on H100                                                       | Value                                                                                               |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Max probability difference vs Kev fp32                               | 0.0092                                                                                              |
| Argmax flips                                                         | 0                                                                                                   |
| p50 latency, one request at a time (783 tokens, one 77-way question) | 64 ms                                                                                               |
| Throughput at concurrency 32 and above                               | 88 requests/s, about 69k prefill tokens/s                                                           |
| Prefix cache reads                                                   | 0 (the plugin task skips the cache, and vLLM would not serve one for a hybrid pooling model anyway) |
| Engine start after weights are on disk                               | 31 s                                                                                                |

`bin/load_test.py` produced the throughput row: a closed loop of N workers over the parity records, stdlib only.

## Tests

```bash
uv run --group dev pytest
```

These run on a CPU without vLLM: the row layout, the readout math, and the request-to-answer mapping. The vLLM classes are exercised by the parity run on a GPU. This package is not part of the monorepo's uv workspace or its CI test matrix.
