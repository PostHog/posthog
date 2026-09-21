# ML inference

Design notes for serving PostHog-owned ML models on PostHog-operated GPUs.
Status: draft, 2026-09-21. Nothing in this document is built yet.

The first model is a [Kev](https://github.com/jaredpalmer/kev) decision model.
The architecture must also fit later models, larger traffic, and other GPU providers.

## 1. The workload

Kev is a "System One" decision model in the style of [TypeSafe's Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev).
A request carries one `state` (free text, or an object that is flattened to labeled text) and a set of `questions`.
Each question is a yes/no (`noul`), a multiple choice (`choice`), or a rating scale (`score`).
The response is a calibrated probability distribution per question.
There is no generated text.

Kev is Qwen3.5 plus a rank-16 LoRA and a small pointer head.
The pointer head scores the hidden state of each option token against the hidden state of the question's decide token, then takes a softmax.
Three sizes exist: 0.8B, 4B, and 9B parameters, all bf16, all fit on one GPU.

Four properties of this workload decide most of the architecture below.

1. **Prefill only.** One forward pass answers every question. There is no decode loop, so the request is compute-bound and its duration is known before it starts (it is a function of token count). Most LLM serving machinery exists for the decode loop and does not apply here.
2. **Deterministic.** The same model version, state, and question always return the same probabilities. Calibration temperature is a post-processing step. Exact-match result caching is safe and cheap.
3. **Shared state prefix.** All questions in a request share the state. Across requests, the same state is often asked new questions (a session, a ticket, an error group). The state prefix is the expensive part, so caching it is the main throughput lever.
4. **Hybrid architecture.** Qwen3.5 interleaves Gated DeltaNet (linear attention) layers with full attention layers, 3:1. DeltaNet layers keep a fixed-size recurrent state per sequence and ignore attention masks. Kev therefore runs each question as its own row `state + question` instead of one masked row, and "the KV cache" for a state is two different things: a per-token KV cache for the 8 attention layers, and a fixed-size recurrent state for the 24 DeltaNet layers.

### Size of a cached state (Kev-4B, bf16, from the Qwen3.5-4B config)

| Component                                       | Per layer                     | Layers | For a 772-token state |
| ----------------------------------------------- | ----------------------------- | ------ | --------------------- |
| Attention KV (4 KV heads x 256 dim x K and V)   | 4 KiB per token               | 8      | 24 MiB                |
| DeltaNet recurrent state (32 heads x 128 x 128) | 1 MiB (2 MiB if kept in fp32) | 24     | 24 to 48 MiB          |
| Conv state                                      | ~64 KiB                       | 24     | ~1.5 MiB              |
| **Total**                                       |                               |        | **~50 to 75 MiB**     |

The attention part grows linearly with state length (256 MiB at Kev's 8,192-token state cap).
The DeltaNet part is constant.
Kev-9B is roughly double. Measure before relying on these numbers.

### Cost to rebuild versus cost to move a state (H100, estimates dated 2026-09-21)

| Action                                                                 | Estimate                          |
| ---------------------------------------------------------------------- | --------------------------------- |
| Recompute a 772-token prefix on Kev-4B (6 TFLOP at 30-50% utilization) | 12 to 20 ms, more at batch size 1 |
| Copy 60 MiB from host DRAM over PCIe Gen5                              | 1 to 2 ms                         |
| Fetch 60 MiB over 100 GbE                                              | 5 to 6 ms                         |
| Fetch 60 MiB over 10 GbE                                               | ~50 ms                            |

Fetching a state from another machine over ordinary Ethernet costs about as much as recomputing it.
A remote KV store only pays off with RDMA-class networking or states near the 8k cap.
This is why the design keeps the state cache on the GPU node and puts affinity routing in front of it, instead of a shared KV database.

## 2. Targets and constraints

- **Traffic.** Jev's published per-key rate limit is 1,200 requests per minute (20 rps) with 70 to 500 ms end-to-end latency. Design for tens of rps on day one and thousands of rps at 100x, with no component whose cost grows faster than linearly with traffic.
- **Latency.** p50 under 100 ms for a five-question request with a warm state, p99 under 500 ms, measured at the public edge.
- **Data residency.** `state` is customer data. PostHog runs a US and an EU cloud. Every GPU pool, cache, and log is per region. EU states never reach a US GPU.
- **Privacy.** States are never logged or persisted by the inference path. Cache keys are hashes. Caches are memory-only on the node that computed them.
- **Provider portability.** Lambda and Thunder Compute first, but nothing in the request path may depend on either. A GPU node is a replaceable box that runs one container.
- **Model portability.** Kev first, but the node contract (health, capacity, model version, `/v1/systemone`) must fit an embedding model or a classifier later.

## 3. Topology: where auth and business logic live

Three options were considered.

| Option                     | Request path                                                     | Verdict                                                                                                                                                                                                                |
| -------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A. Django first            | client -> Django (auth, rate limit, usage) -> GPU node           | Rejected. Every inference holds a Django worker open across a cross-provider hop. Django becomes the bottleneck at 100x, and its p50 alone is a large share of the latency budget.                                     |
| B. Logic on the GPU node   | client -> GPU node (auth, rate limit) -> Django for keys         | Rejected. A rented box at a third-party provider would hold Postgres or Redis credentials for the whole cloud. Blast radius is the whole cloud. Nodes also stop being stateless and replaceable.                       |
| C. Inference gateway first | client -> gateway (auth, rate limit, usage, routing) -> GPU node | **Chosen.** Same shape as the existing AI gateway: `products/ai_gateway` exposes no per-team resource, a project secret API key with a gateway scope reaches the gateway directly, and usage is read back from events. |

The gateway is a small stateless service in our own cloud (one deployment per region), not on the GPU provider.
It is the only component that holds credentials.

```text
 client (SDK / HTTP)
   |  Bearer phs_...  POST /v1/systemone
   v
 inference gateway  (PostHog VPC, per region, stateless, N replicas)
   |- validate project secret API key + scope       (Postgres via cached key lookup)
   |- rate limit per team, per key, per model       (Redis token buckets)
   |- result cache: hash(model, state, question)    (Redis, tiny values)
   |- normalize + tokenize state, hash the tokens
   |- state-affinity routing to a GPU node          (rendezvous hash over healthy nodes)
   |- emit usage event (team, model, tokens, ms)    (Kafka, same path as the AI gateway)
   v   mTLS over a private link
 GPU node pool  (Lambda / Thunder / later AWS, one container per GPU)
   |- dynamic batcher (in-process queue, ms window)
   |- GPU prefix cache  (HBM, LRU over state hashes)
   |- host DRAM prefix tier (spill from HBM)
   |- model runner (Kev weights + pointer head)
```

Django's job is what it already does: manage project secret API keys and scopes, hold per-team configuration (enabled models, quotas), and show usage.
The gateway reads that through the same key-validation path the AI gateway uses.
Per [`.agents/security.md`](../../.agents/security.md), gateway-to-node calls use a scoped JWT with the team and model in the claims, never `INTERNAL_API_SECRET`.
The node verifies the JWT and nothing else.

## 4. The GPU node

### Engine

Kev's own server is FastAPI plus HF `transformers` with a threading lock and one request at a time.
That is the starting point, not the destination.

- **Phase 1.** Keep the HF model and pointer head. Replace the server with a batching runner: one process per GPU, an asyncio front, a single model thread that drains a bounded queue. This is a few hundred lines and gets us to a correct multi-tenant node fast.
- **Phase 2.** Port Kev to a vLLM pooling model with a custom head. vLLM already runs Qwen3.5's hybrid layout with CUDA graphs, varlen packing, continuous batching, Prometheus metrics, and the LMCache and Dynamo integrations. Writing that ourselves is a bad trade once traffic is real. Two caveats decide when phase 2 pays off, both checked 2026-09-21:
  - vLLM's prefix cache for GDN hybrids works at a 528-token block granularity (`--mamba-cache-mode align`). A state shorter than 528 tokens never hits, and a 772-token state reuses 528 tokens and recomputes 244. The finer `all` mode is an unmerged PR that costs 28 to 40% throughput and stores the GDN state in bf16 unless forced to fp32, which makes cold and warm answers differ slightly. See [vllm#40696](https://github.com/vllm-project/vllm/issues/40696) and [vllm#26807](https://github.com/vllm-project/vllm/pull/26807).
  - vLLM enables prefix caching for pooling models only when the pooler reads the last token. Kev's head reads hidden states at every option end token and at the decide token, so the port needs a custom pooler that pools a set of positions, and those positions must all sit in the question suffix, after the cached state prefix, for the cache to apply.

  Kev's own cache is exact, whole-state, any length, fp32 for the GDN part. Phase 1 keeps that. Phase 2 is worth it when batching and packing gains outweigh the coarser state cache, which the phase 1 measurements decide.

### Port effort, HF to vLLM

The base model already exists in vLLM (`Qwen3_5ForCausalLM`). The port is:

1. Export Kev as a plain Qwen3.5 checkpoint with the LoRA merged in fp32 and cast to bf16, which is what Kev already does at load time.
2. An out-of-tree model class registered through vLLM's plugin entry point, subclassing the Qwen3.5 model and adding a pooler that finds the option end and decide token ids in the flattened `input_ids`, applies `k(h_opts) @ q(h_decide) * scale`, and returns one softmax per question.
3. Row expansion (one row per question, state plus question) done by the node before the request enters vLLM, so all rows of one request land in the same batch and share the state prefix blocks.
4. Calibration temperature as post-processing at the node.
5. A parity harness that compares probabilities against the HF path on a fixed record set. The bar is Kev's own bf16 versus fp32 gap (0.017 max on 24 records).

Estimate: one to two engineer weeks for a working port, then a similar amount for parity, cache tuning, and load testing. The ongoing cost is that an out-of-tree subclass tracks vLLM's internal model API, which changes between releases, so pin the version and re-run parity on every bump.

The node contract must not change between the phases: same `/v1/systemone`, `/healthz`, `/capacity`, `/metrics`.

### Batching

State of the art for LLMs is continuous (iteration-level) batching with chunked prefill, optionally with prefill and decode on different GPUs (vLLM, SGLang, TensorRT-LLM, NVIDIA Dynamo).
Almost all of it exists to interleave decode steps.
Kev has no decode steps.
Its batching problem is the one embedding servers and classifiers have: dynamic batching of variable-length prefill-only rows, which text-embeddings-inference and vLLM's pooling path already do well.

The batcher on the node:

1. Accepts requests into a bounded in-process queue. Bound is by token count, not request count, because cost is tokens.
2. Forms a batch when either the batch reaches its token budget or the oldest request has waited the window (start at 2 to 5 ms, tune from p99 and GPU utilization).
3. Packs rows with variable-length kernels (`flash-linear-attention` supports `cu_seqlens`, and per-sequence `initial_state` for DeltaNet). Padding is the fallback, not the plan.
4. Groups rows that share a state hash so one prefix cache entry feeds all of them, and orders a cache miss before the rows that will hit it.
5. Returns 503 with `Retry-After` when the queue is over its bound. The gateway then retries on another node or sheds load. The queue never grows unbounded.

### Where the queue lives

In process, on the GPU node.
Not in Redis, not in Kafka.
The batch window is single-digit milliseconds and a broker adds a network round trip on both the request and the response.
A broker also makes the response path a second hop with correlation state, which is the thing that breaks under load.

A broker is right for the other lane: bulk, offline decisions over many rows (the map-reduce use case).
That lane is a separate endpoint that writes work to Kafka or a Temporal workflow, calls the same gateway with a low-priority header, and lands results in ClickHouse or object storage.
The node batcher gives low-priority rows the leftover token budget, so bulk work fills idle GPU time without hurting online p99.

## 5. Caches

There are three caches with three different homes. Only one of them holds tensors.

| Cache               | Key                                                  | Value                                       | Home                                                               | Why here                                                                                                                         |
| ------------------- | ---------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Result cache        | `hash(model_version, state_tokens, question_tokens)` | probabilities, a few hundred bytes          | Redis, per region                                                  | Exact-match hits skip the GPU entirely. Kev is deterministic, so this is safe. Cheap enough to keep for hours.                   |
| GPU prefix cache    | `hash(model_version, state_tokens)`                  | attention KV + DeltaNet state, 50 to 75 MiB | GPU HBM on the node, LRU                                           | An H100 has ~60 GB free after Kev-4B weights: about a thousand hot states per node. Hit turns a 15 ms prefill into a ~1 ms copy. |
| Host prefix tier    | same                                                 | same                                        | Node DRAM (Lambda H100 boxes carry hundreds of GB), spill from HBM | PCIe copy is ~1 to 2 ms. Several thousand more states per node.                                                                  |
| Shared prefix store | same                                                 | same                                        | Not built. LMCache or Mooncake over NIXL/RDMA if ever justified    | Only pays off with RDMA-class fabric inside one provider and states near the 8k cap. Never across providers.                     |

What is deliberately not in the table: DynamoDB, Postgres, and Redis as a KV tensor store.
A 60 MiB value at hundreds of hits per second is multiple GB/s of network, all of it to save a 15 ms recompute that the fetch would take as long as.
Postgres additionally has no reason to hold cache data at all.
The state-of-the-art systems (LMCache tiers: GPU, CPU DRAM, local NVMe, then remote; Mooncake's disaggregated KV pool; Dynamo's KV block manager) all agree on the shape: tensors stay as close to the GPU as possible, and only the _index_ of who holds what is shared.

### Making the GPU cache hit

A per-node cache only hits if the same state lands on the same node.
The gateway routes by state hash with rendezvous hashing over the healthy node set, and falls back to least-loaded when the affine node is over capacity.
That is what Dynamo's KV-aware router and llm-d's endpoint picker do at fleet scale; the difference is they also read a shared KV index because their prefixes are worth fetching remotely. Ours are not, so the index is unnecessary.

Eviction is LRU by state hash, with a minimum state length to be worth caching (Kev uses 384 tokens).
Model version is part of every key, so a rollout invalidates nothing explicitly: old entries age out.

## 6. Nodes, providers, and the network

A node is one container per GPU with a fixed contract:

- `GET /healthz` returns model name, model version, GPU, queue depth, token budget in flight.
- `POST /v1/systemone` with a scoped JWT.
- `GET /metrics` in Prometheus format.

The gateway keeps the node set in Redis with heartbeats.
A node registers itself on boot with its region, provider, model, and capacity, and is dropped after missed heartbeats.
That registry is the provider abstraction: Lambda, Thunder, and later AWS `g6e`/`p5`, GCP, CoreWeave, or a serverless provider all appear as nodes with a `provider` label and nothing else provider-specific in the request path.

Provider notes as of 2026-09-21:

- **Lambda** sells on-demand and reserved instances with GPUs on PCIe or SXM, multi-node clusters, a Managed Kubernetes offering with the NVIDIA GPU Operator preinstalled, per-instance firewall rules, networked persistent storage, and an API for launching instances. It works for both dev and the first production pools. Its [region list](https://docs.lambda.ai/public-cloud/on-demand/) has one EU region, `europe-central-1` in Germany, alongside nine US regions and four in Asia and the Middle East. Check which GPU types the German region actually stocks before planning an EU pool on it. On-demand H100 inventory is reported to run out at peak times, so a production pool needs reserved capacity, not on-demand.
- **Thunder Compute** attaches the GPU to the VM over TCP rather than PCIe. That is how it undercuts on price. It also means host-to-device copies and small-batch latency are worse than on a real PCIe box, which hurts exactly the host DRAM tier and the low-latency path above. Fine for development and load testing of the batcher. Measure before serving production from it.

Network between the gateway and nodes: a WireGuard or Tailscale mesh per region, or provider VPC peering where it exists, with mTLS on top.
Nodes expose the inference port only on the mesh interface.
Nodes hold no PostHog credentials, only the JWT verification key.

Autoscaling is by queue wait time and GPU utilization, with a floor of two nodes per region.
Boot time of a node (image pull plus ~8 to 18 GB of weights) is minutes, so scale on a trend, keep headroom, and never scale to zero on the online lane.

## 7. Observability and SLOs

Per request at the gateway: team, model version, state tokens, question count, result-cache hit, prefix-cache hit (reported back by the node), node, queue wait, model time, total time.
No state text anywhere in logs or events.

Node metrics: batch size and token count histograms, queue wait, prefix cache hit ratio and occupancy for HBM and DRAM, GPU utilization, 503 count.
Team is never a label on a node metric (unbounded cardinality); it lives in the usage event only.

SLOs are per region: availability, p50 and p99 total time for warm and cold state, and result-cache hit ratio as a leading indicator of cost.

## 8. Phases

1. **Single node, real traffic shape.** Kev-4B, the phase 1 batcher, one Lambda or Thunder box, gateway with key validation and a result cache, internal callers only. Measure everything in the tables above.
2. **Pool per region.** Node registry, affinity routing, host DRAM tier, autoscaling, EU pool. Open to customers behind a project secret API key scope.
3. **Engine swap.** vLLM pooling model port, keeping the node contract. Adopt LMCache only if measurements from phase 2 show remote prefix reuse would pay.
4. **Bulk lane.** Offline endpoint on Kafka or Temporal with low-priority scheduling on the same nodes.

## 9. Open questions

- What is the real hit ratio of the result cache and the prefix cache on PostHog's own use cases (replay, tickets, error groups)? This decides node count more than anything else.
- Does an EU GPU pool exist at either provider, or does EU need a different provider from day one?
- Does vLLM's 528-token block granularity for GDN state caching lose more than the batching gains recover on PostHog's real state lengths? If most states are under 528 tokens, phase 2 needs either the `all` cache mode to land upstream or our own state cache in front of vLLM.
- What does SGLang's hybrid GDN prefix cache do at the same granularity? Its radix cache is token-exact for attention layers; the GDN checkpoint interval is the number to check.
- Is Kev-0.8B accurate enough for the high-volume PostHog use cases? It changes the throughput math by about 5x.
- Should the gateway be a new service or a route family on the Go AI gateway (`PostHog/ai-gateway`)? The auth, rate limiting, and usage emission are the same code.

## Sources

- Kev: [repository](https://github.com/jaredpalmer/kev), `kev/serve.py` (prefix cache, single-request lock), `kev/model.py` (row construction, pointer head).
- Jev: [Introducing System One models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [TypeSafe System One docs](https://docs.typesafe.ai/concepts/system-one).
- Qwen3.5-4B config: [Hugging Face](https://huggingface.co/Qwen/Qwen3.5-4B/raw/main/config.json). Hybrid attention background: [Raschka, Hybrid Attention](https://sebastianraschka.com/llm-architecture-gallery/hybrid-attention/).
- vLLM: [pooling models](https://docs.vllm.ai/en/latest/models/pooling_models.html), [V1 feature matrix](https://docs.vllm.ai/en/latest/usage/v1_guide.html), [out-of-tree model registration](https://docs.vllm.ai/en/latest/contributing/model/registration.html).
- Lambda: [On-Demand Cloud overview and regions](https://docs.lambda.ai/public-cloud/on-demand/), [Managed Kubernetes](https://docs.lambda.ai/managed-kubernetes/).
- KV cache tiers: [LMCache](https://github.com/lmcache/lmcache), [Mooncake](https://arxiv.org/pdf/2407.00079).
- Routing and batching: [NVIDIA Dynamo KV-aware routing](https://docs.nvidia.com/dynamo/latest/user-guides/kv-cache-aware-routing), [Baseten on KV-aware routing](https://www.baseten.co/blog/how-baseten-achieved-2x-faster-inference-with-nvidia-dynamo/).
- Providers: [How Thunder Compute works (GPU over TCP)](https://www.thundercompute.com/blog/how-thunder-compute-works-gpu-over-tcp), [Thunder Compute vs Lambda](https://www.thundercompute.com/blog/thunder-compute-lambda-labs-gpu-cloud).
