# kev-vllm

Serves PostHog's decision models on vLLM: one `state`, several typed questions, a calibrated probability per question, no generated text. The model in production is [JevK5](https://github.com/allebee/jevk5) v0.2, Qwen3.5-4B with a merged LoRA that reads each answer from the answer letters' next-token logits. The package started with [Kev](https://github.com/jaredpalmer/kev), Qwen3.5 plus a LoRA and a pointer head, and still serves it. A checkpoint's `config.json` picks the model class (`architectures`) and the IO processor (`io_processor_plugin`).

- `kev_vllm.jevk5`, `kev_vllm.jevk5_model`, `kev_vllm.jevk5_io_processor`: JevK5's prompt and readout, ported from its runtime; `JevK5ForDecision`, a pooling model that returns the letter logits at the last token; and the IO processor that turns a TypeSafe `/v1/systemone` request into one prompt per question and the logits back into answers.
- `kev_vllm.model`, `kev_vllm.io_processor`: `KevForDecision` and Kev's IO processor, which encodes a request exactly as Kev does (one causal row per question) and applies the pointer head.
- `kev_vllm.jevk5_export`, `kev_vllm.export`, `kev_vllm.checkpoint`, `kev_vllm.parity`: turn a Hub checkpoint into a directory the image serves, verify one against its manifest, and check a Kev export against Kev's own path on this machine.

Both IO processors return the same answer shape, so the AI gateway and Django see one contract. Publishing a version, measuring parity against a served model, load testing and the evals live in the MLHog repo under `models/kev`. This package downloads weights and runs inference; it never writes to a bucket.

`kev_vllm/kev_compat.py` is vendored from Kev (Apache-2.0) because the `kev` package pins a torch version vLLM cannot use.

## Export a checkpoint

```bash
uv run jevk5-vllm-export --revision 27d2d6b8d4714807f6293b0623bd7370b27e42f8 --out build/jevk5-4b
```

Downloads JevK5 at a pinned Hub commit, checks every LFS file against the sha256 the Hub records, adds the `jevk5_*` fields and the model class to `config.json`, and writes `manifest.json`. The weights are copied unchanged in bf16; a GPU without bf16, such as a T4, casts them to fp16 at load (`DTYPE=float16`). It needs no GPU and no extra.

```bash
uv run --extra export kev-vllm-export --run jaredpalmer/kev-4b --out build/kev-4b
```

For Kev, `kev-vllm-export` downloads the base model and adapter, merges the LoRA in fp32 the way `kev.serve` does, casts to bf16, and writes `config.json`, `model.safetensors`, the tokenizer, and `manifest.json` with every hash. About 16 GB of RAM and 20 GB of disk.

## Serve

On a CUDA box with the `serve` extra installed (`uv sync --extra serve`), the entry points register the model classes and the IO processors on import:

```bash
VLLM_USE_V2_MODEL_RUNNER=0 vllm serve build/jevk5-4b --served-model-name jevk5-0.2 --mamba-ssm-cache-dtype float32 --port 8000
```

`VLLM_USE_V2_MODEL_RUNNER=0` is required on vLLM 0.29: its new model runner does not run the `plugin` pooling task that IO processors use.

`config.json` names the IO processor (`io_processor_plugin: "jevk5"`, or `"kev"` for Kev), so no extra flag is needed. Then:

```bash
curl -s localhost:8000/pooling -H 'content-type: application/json' -d '{"model": "jevk5-0.2", "data": {"state": "It has been two weeks and the refund has not arrived.", "questions": {"refund": {"type": "noul", "instructions": "Is the customer asking about a refund?"}}}}'
```

The answer is under `data.answers`, in Kev's format for either model, with `data.probabilities_raw` alongside for parity checks. JevK5 takes at most 16 options per question and 16,384 tokens per prompt, and refuses more.

The AI gateway states the day counts between the dates in a state when a request sets `date_facts` (PostHog/ai-gateway#505), before any host sees it, so this plugin does no date preprocessing of its own.

### Batching

vLLM's scheduler is the request pool, so this package adds none of its own. Each question becomes its own engine request, and every request waits in the engine's in-memory queue. At each step, the scheduler packs waiting rows from all callers into one forward pass, up to `--max-num-batched-tokens` tokens, and splits a row longer than the remainder across steps (chunked prefill). A row is prefill only: it finishes in the step that computes its last token, and it frees its slot in that step. A burst of requests therefore becomes a few full steps, not one step per request.

- No state persists between requests. vLLM's KV and Mamba caches hold only the rows in flight. Prefix caching is off for both models, because vLLM does not enable it for pooling models on hybrid backbones. So each row computes its state again, including the rows of one request that share it.
- `JevK5ForDecision` reads the answer from each row's last token only. A chunked row holds no hidden states between steps, and each step's readout is one matmul for all its rows.
- The token budget does not change throughput. A single row already keeps the GPU's compute busy, so larger steps only make each row wait longer. The entrypoint keeps vLLM's default budget.
- vLLM's queue has no limit by default. When the queue is longer than the gateway's timeout, every request in it fails. `--max-num-queued-tokens` makes vLLM answer 503 when the prefill backlog is full, so a caller can retry elsewhere without delay. Set it to the prefill throughput multiplied by the longest wait you accept.

### Load test on an L4

Measured 2026-09-24 on one L4 (EC2 gr6.4xlarge), vLLM 0.29.0, JevK5 at revision `27d2d6b8` in bf16. The requests are JevBench's public items: 70% one question on a short state (median 178 tokens), 20% one question on a long state (median 1,313 tokens), and 10% three questions on one short state. Closed-loop saturation:

| Token budget              | Prefill tokens/s | p90 latency at 32 concurrent |
| ------------------------- | ---------------- | ---------------------------- |
| 2,048 (vLLM's L4 default) | 6,000 to 6,100   | 2.9 s                        |
| 8,192                     | 5,700 to 5,800   | 3.6 s                        |
| 16,384                    | 5,900 to 6,000   | not measured                 |

A request alone gets about 4,600 tokens/s, and short and long rows saturate at the same rate. The GPU runs at its 72 W power cap during saturation. The readout on the last token matches `AllPool`'s to a median 0.0016 (maximum 0.022, which is inside JevK5's own bf16 noise), at the same throughput.

Open loop at a Poisson arrival rate, with a 10 s client timeout as the gateway uses. "OK" is the answers per second that arrive within the timeout:

| Queue limit  | Offered load  | OK     | Rejected with 503 | Timed out | p99 of answers |
| ------------ | ------------- | ------ | ----------------- | --------- | -------------- |
| none         | 0.9x capacity | 11.4/s | 0%                | 0%        | 3.0 s          |
| none         | 1.3x          | 7.8/s  | 0%                | 47%       | 10.0 s         |
| none         | 2.0x          | 3.3/s  | 0%                | 86%       | 9.9 s          |
| 5,815 (1 s)  | 0.9x          | 10.5/s | 11%               | 0%        | 1.2 s          |
| 11,630 (2 s) | 0.9x          | 11.4/s | 4%                | 0%        | 2.0 s          |
| 23,260 (4 s) | 0.9x          | 11.9/s | 0%                | 0%        | 3.8 s          |
| 23,260 (4 s) | 1.3x          | 13.1/s | 19%               | 0%        | 4.9 s          |
| 23,260 (4 s) | 2.0x          | 12.9/s | 49%               | 0%        | 5.2 s          |

Without a limit, overload makes the wait longer than the timeout, and the box answers less than a third of its capacity. With a limit, it keeps answering at capacity and rejects the rest at once. The entrypoint's default on an L4 is about four seconds of its throughput. At that limit, the box rejects nothing below capacity, and the slowest answers under overload arrive in about half the gateway's wait. A T4 serves JevK5 at about 1,270 tokens/s, a fifth of an L4. Kev, on the same backbone, served about 69,000 on an H100. The entrypoint sizes the limit for a T4 as well, and any other GPU needs it set.

## Container image

`Dockerfile` builds the serving image, which is the whole serving box: the official `vllm/vllm-openai:v0.29.0` image with this package installed on top, Caddy for the bearer check, and s5cmd to fetch the weights. `.github/workflows/cd-ml-inference-decision-image.yml` builds it for amd64 on every master push that touches the package and publishes it as `posthog-ml-inference-decision` to ECR and GHCR; add the `build-ml-inference-image` label to a PR to build it early and push it to GHCR alone, tagged `pr-<number>`.

The entrypoint (`bin/serve.sh`) fetches the checkpoint from `MODEL_URI` into `MODEL_DIR` unless one already matches its manifest there, checks it, runs `vllm serve` on loopback, and runs Caddy on `PORT` in front of it. Caddy answers 401 without `Authorization: Bearer $DECISION_BEARER` and exposes only `/pooling`, `/health` and `/metrics`. If either process exits, the container exits with a failure status, even when the process itself exited cleanly, so a host runs it under a restart policy (`always` or `on-failure`):

```bash
docker run -d --restart always --gpus all --network host --shm-size 8g \
  -v ml-models:/models \
  -e MODEL_URI=s3://<base-models bucket>/posthog/jevk5-4b-vllm/<version>/ \
  -e DECISION_BEARER \
  ghcr.io/posthog/posthog-ml-inference-decision@sha256:<digest>
```

- The host network lets s5cmd read the instance role's credentials from the metadata service, and Caddy listens on the host's `PORT`. Keep the port closed to the network and reach it over the tailnet.
- The named volume keeps the weights and the compile caches (`/models/cache`, or `CACHE_DIR`) across containers, so only the first container on a host pays the full compile. Docker creates the volume owned by the serving user (uid 10001). A host directory, or a volume created by an image without the cache directory, must be writable by that user. If the cache directory is not writable, the entrypoint says so and keeps the caches in the container.
- `DTYPE=float16` on GPUs without bf16. `MODEL_NAME` (the served name the gateway asks for, default `jevk5-0.2`), `MAX_MODEL_LEN`, `GPU_MEMORY_UTILIZATION`, `PORT` and `VLLM_PORT` override the defaults; extra arguments go to `vllm serve`.
- `MAX_NUM_QUEUED_TOKENS` is vLLM's backlog limit. Unset, the entrypoint uses about four seconds of the GPU's measured prefill, which exists for an L4 and a T4 (see [Load test on an L4](#load-test-on-an-l4)). On any other GPU the container refuses to start until it is set.
- The image sets `GLOO_SOCKET_IFNAME=lo`. vLLM otherwise resolves the host name at start-up and fails with "File name too long" where a VPC's DHCP domain makes it 64 characters.

`kev-vllm-checkpoint verify <dir>` is the manifest check on its own.

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

### JevK5

Measured 2026-09-24 on an L4 (EC2 g6.xlarge), vLLM 0.29.0, JevK5 at revision `27d2d6b8`: 294 questions, being JevBench's public sets, 28 of its hard states cut to about 1,300 tokens, and 35 invented edge cases. The reference is JevK5's own runtime (`jevk5` 0.2.0, transformers 5.17) on the same GPU, with its bf16 backbone and the answer read out again in fp32.

| Compared                                          | Max probability difference | Median | Argmax flips                                  |
| ------------------------------------------------- | -------------------------- | ------ | --------------------------------------------- |
| Runtime's fp32 readout vs this image (bf16)       | 0.046                      | 0.0025 | 1, where the top two were 0.019 apart         |
| Runtime's fp32 readout vs its own default readout | 0.059                      | 0.0036 | 4, where the top two were 0.024 apart or less |
| Runtime's default readout vs `--quantization fp8` | 0.41                       | 0.014  | at least 5, one with the top two 0.08 apart   |

The image is as close to the runtime's fp32 readout as the runtime's own default output is, so it serves JevK5 within the model's rounding noise. fp8 answers about 30% faster, but it moves answers far past that noise, so the image serves bf16. One short question (about 190 tokens) takes 51 ms at the median when it is alone on the GPU. The throughput under load is in [Load test on an L4](#load-test-on-an-l4).

## Evals

The eval runner that scores a served model on labelled suites lives in the MLHog repository under `models/kev/`, next to the other model work.

## Tests

```bash
uv run --group dev pytest
```

These run on a CPU without vLLM: the row layout, the readout math, and the request-to-answer mapping. The vLLM classes are exercised by the parity run on a GPU. This package is its own uv project, outside the monorepo's workspace and root pytest: production installs it with `--no-deps` into the vLLM image, so its runtime pins are vLLM's, and the export environment's torch conflicts with the monorepo's. CI runs these tests and ruff from `.github/workflows/ci-ml-inference.yml` with this package's lock.
