# kev-vllm

Serves [Kev](https://github.com/jaredpalmer/kev) decision models on vLLM. Kev is Qwen3.5 plus a LoRA and a pointer head: one `state`, several typed questions, a calibrated probability per question, no generated text. The design behind this package is the ML inference RFC in the internal requests-for-comments repo (PR 1277).

Three parts:

- `kev_vllm.model`: `KevForDecision`, a vLLM pooling model on the stock Qwen3.5 class. Its pooler reads the option-end and decide token hidden states of each row and applies the head, so vLLM batches rows across requests.
- `kev_vllm.io_processor`: a vLLM IO-processor plugin that accepts a TypeSafe `/v1/systemone` request on the `/pooling` endpoint, encodes it exactly as Kev does (one causal row per question), and returns Kev's answer shape plus `probabilities_raw`.
- `kev_vllm.export`, `kev_vllm.checkpoint`, `kev_vllm.parity`: turn a Kev checkpoint into a vLLM-loadable directory, verify one against its manifest, and check an export against Kev's own path on this machine.

Publishing a version, measuring parity against a served model, load testing and the evals live in the MLHog repo under `models/kev`. This package downloads weights and runs inference; it never writes to a bucket.

`kev_vllm/kev_compat.py` is vendored from Kev (Apache-2.0) because the `kev` package pins a torch version vLLM cannot use.

## Export a checkpoint

```bash
uv run --extra export kev-vllm-export --run jaredpalmer/kev-4b --out build/kev-4b
```

Downloads the base model and adapter, merges the LoRA in fp32 the way `kev.serve` does, casts to bf16, and writes `config.json`, `model.safetensors`, the tokenizer, and `manifest.json` with every hash. About 16 GB of RAM and 20 GB of disk.

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

## Container image

`Dockerfile` builds the serving image: the official `vllm/vllm-openai:v0.29.0` image with this package installed on top, so the entry points register the model class and the IO processor at import. Weights stay out of the image. `.github/workflows/cd-ml-inference-decision-image.yml` builds it for amd64 on every master push that touches the package and publishes it as `posthog-ml-inference-decision` to ECR and GHCR; add the `build-ml-inference-image` label to a PR to build it early and push it to GHCR alone, tagged `pr-<number>`.

The entrypoint (`bin/serve.sh`, installed as `kev-vllm-serve`) checks the checkpoint at `MODEL_DIR` against its `manifest.json` and starts `vllm serve` with the flags the parity run used. It binds loopback by default, because TLS and the per-instance bearer terminate in a proxy on the same host, so a GPU host runs it with the host network and the checkpoint mounted:

```bash
docker run --rm --gpus all --network host --ipc host \
  -v /srv/models/kev-4b:/models/kev-4b:ro \
  ghcr.io/posthog/posthog-ml-inference-decision:sha-<commit>@sha256:<digest>
```

The container serves as an unprivileged user (uid 10001), so the mounted checkpoint must be world-readable and outside a home directory. `HOST=0.0.0.0` exposes the port directly for a bring-up box behind a firewall or tunnel. `MODEL_NAME`, `PORT`, `MAX_MODEL_LEN` and `GPU_MEMORY_UTILIZATION` override the defaults, and any extra arguments go to `vllm serve`. `kev-vllm-checkpoint verify <dir>` is the same manifest check on its own.

## Parity

```bash
uv run kev-vllm-parity local --checkpoint build/kev-4b --reference ref.jsonl --device mps
```

`local` runs the exported directory through transformers on this machine, which checks the export itself before any GPU is involved. The reference file is Kev's own full-precision output for the same records, written by MLHog's `models/kev/parity.py reference`; the same script's `compare` posts the records to a served model. Both fail above a 0.02 maximum probability difference, just past Kev's own measured bf16-versus-fp32 gap of 0.017. Measured 2026-09-21 for `jaredpalmer/kev-4b` at Hub revision `485ace87`, 32 records from `evals/public-pool-v6/test.jsonl` (one 77-way choice each, median 762 tokens), against Kev's fp32 path on the same Mac:

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

MLHog's `models/kev/load_generator.py` produced the throughput row: a closed loop of N workers over the parity records.

## Date facts

Kev cannot subtract dates, so its author ships an opt-in preprocessor that appends the day count between any two absolute dates in the state ("July 4, 2026 is 8 days after June 26, 2026."). `kev_compat.with_date_facts` is that function, made idempotent so a client that already applied it is not doubled up, and the IO processor applies it to every request when the server runs with `KEV_DATE_FACTS=1`. It is off by default so the served numbers match Kev's published ones.

## Evals

The eval runner that scores a served model on Kev's labelled suites, with and without date facts, lives in the MLHog repository under `models/kev/`, next to the other model work. Measured there on 2026-09-22 against this server on an H100: date facts move the deadline questions of Kev's transfer-v4 development split from 0.60 to 0.85 and change nothing else by more than half a point.

## Tests

```bash
uv run --group dev pytest
```

These run on a CPU without vLLM: the row layout, the readout math, and the request-to-answer mapping. The vLLM classes are exercised by the parity run on a GPU. This package is its own uv project, outside the monorepo's workspace and root pytest: production installs it with `--no-deps` into the vLLM image, so its runtime pins are vLLM's, and the export environment's torch conflicts with the monorepo's. CI runs these tests and ruff from `.github/workflows/ci-ml-inference.yml` with this package's lock.
