# ML inference

Design notes for serving PostHog-owned ML models on PostHog-operated GPUs.
Status: draft, 2026-09-21. Nothing in this document is built yet.

The first model is a [Kev](https://github.com/jaredpalmer/kev) decision model.
The architecture must also fit later models, larger traffic, and the in-house Glaucon encoder.

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
This is why the design keeps the state cache on the GPU pod and puts affinity routing in front of it, instead of a shared KV database.

## 2. Targets and constraints

- **Traffic.** Jev's published per-key rate limit is 1,200 requests per minute (20 rps) with 70 to 500 ms end-to-end latency. Design for tens of rps on day one and thousands of rps at 100x, with no component whose cost grows faster than linearly with traffic.
- **Latency.** p50 under 100 ms for a five-question request with a warm state, p99 under 500 ms, measured at the public edge.
- **Data residency.** `state` is customer data. PostHog runs a US and an EU cloud, and the AI gateway already runs in both. Every GPU pool, cache, and log is per region. US only until an EU pool is needed, and the EU pool is the same manifests on the EU cluster.
- **Privacy.** States are never logged or persisted by the inference path. Cache keys are hashes. Caches are memory-only on the pod that computed them.
- **No hand-run steps.** Nodes, pods, and weights arrive through the same IaC and deploy pipeline as every other production service. A rented box with a bootstrap script is a development tool, never a production dependency.
- **Model portability.** Kev first, but the serving stack must fit an embedding model or a classifier later, including Glaucon.

## 3. What already exists, and what it decides

Three pieces of PostHog infrastructure settle most of the open questions.

### The AI gateway already is the inference gateway

[`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway) is a Go service in front of every LLM call PostHog resells or self-hosts.
On the hot path it does everything this design needs from a gateway, without touching Django:

- Auth resolves a project secret key (`phs_`) or OAuth token (`pha_`) to a team and scope with one read from the hypercache mirror (Valkey hot, S3 cold). Scopes and entitlement are managed in Django and projected into the mirror.
- Spend is admitted against a prepaid wallet in the gateway's own Postgres ledger, with per-team hard caps and per-attribution soft budgets in Valkey.
- Every request lands an `$ai_generation` event on the existing Kafka topic, which is where usage and billing are read from.
- Self-hosted models are first-class. A canonical id under the `posthog` namespace (`posthog/zai-org/glm-5.2`) maps to one or more "served hosts", each a `kind` (the serving stack, which fixes the auth scheme and model names) plus a base URL and a roster. Per-host circuit breakers, health scores, and weighted failover already exist. Two kinds are wired today: a vLLM OpenAI-compatible endpoint on Modal, and Baseten.
- It runs on the production EKS clusters in both regions through the golden chart, autoscaled on in-flight requests, behind Contour.

So the gateway question has one answer: Kev is a new served-host kind on the AI gateway, under a canonical id such as `posthog/jaredpalmer/kev-4b`.
Django keeps what it has: key management, scopes, wallet administration, and usage views.
What the gateway does not have yet, and this work adds:

1. **A new request shape.** The gateway dispatches Anthropic Messages, OpenAI Chat Completions, and OpenAI Responses. Kev's `/v1/systemone` is a fourth shape: its own codec, its own token counting for admission (input tokens only, output is zero), and a response that is probabilities rather than a stream.
2. **A `kev` host kind** with its auth scheme and model name map, the same shape as the existing vLLM kind.
3. **Per-token pricing with zero output cost**, which the catalog already supports for served models.
4. **Affinity routing below the host.** The gateway routes to a host, and a host is one base URL. A Kubernetes Service behind that URL spreads requests across pods at random, which defeats a per-pod state cache. Section 6 covers where the affinity router goes.

### GPUs are Karpenter node pools on the production cluster

The AI research team's direction for PostHog's own inference is Karpenter GPU node pools on the production EKS clusters, not a third-party GPU provider.
That resolves the network, bootstrap, credential, and provider questions at once:

- **Network.** Gateway and GPU pods are in one cluster and one VPC. There is no cross-network hop, no mesh, no peering. A NetworkPolicy limits the pods' ingress to the gateway. Tailscale stays what it is today: access for people and CI, never a request path. VPC peering is the right tool only if GPU capacity ever lands in a separate AWS account, and the repo already has that pattern.
- **Bootstrap.** Nothing is run by hand. The golden chart already renders a per-app Karpenter `NodePool` and `EC2NodeClass` from values, on Bottlerocket. A GPU pool is those values plus the Bottlerocket NVIDIA AMI variant and the NVIDIA device plugin as a cluster add-on. None of that exists in the cluster today: no GPU node pool, no device plugin. That is the first infrastructure PR.
- **Credentials.** Pods get an IRSA role. No per-rental keys, no secrets on nodes.
- **Instance types.** The team's stated inference GPU is the L40S, which is the `g6e` family on AWS: 48 GB per GPU, plenty for Kev-4B or 9B with a large state cache. `p5` (H100) is the step up when a single pool needs more prefill throughput per dollar. `p6` (B200) is available when it matters.
- **Autoscaling.** Karpenter scales nodes on pending pods; the deployment scales pods on queue wait time and GPU utilization. Node boot plus weight load is minutes, so keep a floor of two pods per region and scale on a trend.

Two other homes for GPU capacity exist and each has a defined role:

| Capacity               | Role                                                                                                                                                                                                                       | Why not production                                                                                                                                                  |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Modal (serverless GPU) | Already wired into the gateway as a served-host kind in both regions, running vLLM for GLM and Kimi. A production stopgap if the node pool lands slowly, and a way to test the gateway integration before the pool exists. | The deployment is not in any repo this document could find, so it is not IaC today, and one experiment in July recorded it returning 503s under a nine-way fan-out. |
| Lambda (rented boxes)  | Development and load testing. Lambda has a Germany region and a managed Kubernetes offering, and the team already uses it for ad hoc work.                                                                                 | Outside our VPC, so every production concern (network, credentials, IaC) has to be rebuilt for it.                                                                  |
| Thunder Compute        | Cheap development boxes only.                                                                                                                                                                                              | The GPU is attached over TCP rather than PCIe, which hurts host-to-device copies and small-batch latency.                                                           |

### Weights live in the ML training account

The ML training AWS account already has a base-models bucket, described in its own Terraform as a mirror of third-party foundation-model weights for training and inference, laid out as `<vendor>/<model>/`.
Kev's merged checkpoints go there, immutable and versioned.
Production pods read it through a cross-account bucket-policy grant to the pod's IRSA role, which is the pattern the training-data bucket already uses for prod roles.

## 4. Topology

```text
 client (SDK / HTTP)
   |  Bearer phs_...  POST /v1/systemone   model: posthog/jaredpalmer/kev-4b
   v
 AI gateway  (production EKS, per region, existing service)
   |- resolve key -> team, scopes            (hypercache mirror)
   |- admit against wallet, caps, budgets    (Postgres ledger + Valkey)
   |- result cache: hash(model, state, question) -> probabilities   (Valkey, new)
   |- pick served host for the canonical     (breakers, health, weights)
   |- emit $ai_generation on close           (Kafka)
   v   in-cluster, NetworkPolicy
 kev router  (small Deployment, new)
   |- tokenize state, hash the tokens
   |- rendezvous-hash the state hash over ready pods; fall back to least-loaded
   v
 kev pods  (Deployment on the GPU node pool, one GPU each)
   |- vLLM with the Kev pooling model plugin (end state) or the HF runner (bring-up)
   |- GPU prefix cache over state hashes, host DRAM spill
   |- /healthz /metrics
```

The router exists only because the gateway routes to one URL per host and the state cache is per pod.
It is stateless apart from the pod list it watches through the Kubernetes API.
If the gateway later learns pod-level affinity for served hosts, the router folds into it.

## 5. Engine: vLLM is the end state

The team's serving direction is the vLLM stack, with SGLang as the comparison point, and the gateway already fronts vLLM endpoints.
So the engine choice is vLLM, and the work is making Kev, and later Glaucon, run inside it rather than building a runner beside it.

- **Bring-up.** Kev's own FastAPI server, single request at a time, on one GPU pod. Enough to wire the gateway kind, the codec, pricing, and the parity harness against known-good probabilities. Not a serving design.
- **End state.** Kev as an out-of-tree vLLM pooling model. The base model already exists in vLLM (`Qwen3_5ForCausalLM`). The port is a merged checkpoint export, a plugin class that adds a pooler reading the option end and decide token positions and applying the pointer head, per-question row expansion before the request enters vLLM, calibration temperature as post-processing, and a parity harness with Kev's own bf16 versus fp32 gap (0.017 max on 24 records) as the bar. One to two engineer weeks for a working port, then a similar amount for parity, cache tuning, and load testing. Pin the vLLM version and re-run parity on every bump, because out-of-tree models track internal APIs.
- **Glaucon** follows the same route as a second out-of-tree pooling model. Its custom FlexAttention masks are the part that needs design work inside vLLM's attention layer, and that is a question to settle before its training recipe hardens further.

Two vLLM caveats, checked 2026-09-21, decide how much of Kev's state reuse survives the port:

- vLLM's prefix cache for GDN hybrids works at a 528-token block granularity (`--mamba-cache-mode align`). A state under 528 tokens never hits, and a 772-token state reuses 528 tokens and recomputes 244. The finer `all` mode is an unmerged PR that costs 28 to 40% throughput and stores the GDN state in bf16 unless forced to fp32, which makes cold and warm answers differ slightly. See [vllm#40696](https://github.com/vllm-project/vllm/issues/40696) and [vllm#26807](https://github.com/vllm-project/vllm/pull/26807).
- vLLM enables prefix caching for pooling models only when the pooler reads the last token. Kev's pooler reads several positions, all in the question suffix after the state, so the cache can apply in principle, but the pooling path needs that case handled.

Kev's own cache is exact, whole-state, any length, fp32 for the GDN part.
If PostHog's real states are mostly under 528 tokens, the vLLM port needs either the `all` mode to land upstream or a whole-state cache kept by the plugin itself.
That is the first measurement to take.

### Batching

State of the art for LLMs is continuous batching with chunked prefill and prefill/decode disaggregation.
Almost all of it exists to interleave decode steps, and Kev has none.
What Kev needs is what vLLM's pooling path already does for embedding models: dynamic batching of variable-length prefill-only rows, packed with varlen kernels, bounded by a token budget, with a millisecond-scale wait window.
The queue lives inside the engine on the pod, never in a broker: the batch window is single-digit milliseconds and a broker adds a round trip each way.
A pod over its bound answers 503 with `Retry-After`, and the router retries once on another pod, then sheds.

## 6. Caches

Three caches with three different homes. Only one holds tensors.

| Cache               | Key                                                  | Value                                       | Home                                                       | Why here                                                                                                                         |
| ------------------- | ---------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Result cache        | `hash(model_version, state_tokens, question_tokens)` | probabilities, a few hundred bytes          | Valkey, in the gateway, per region                         | Exact-match hits skip the GPU entirely. Kev is deterministic, so this is safe. Cheap enough to keep for hours.                   |
| GPU prefix cache    | `hash(model_version, state_tokens)`                  | attention KV + DeltaNet state, 50 to 75 MiB | GPU memory on the pod, LRU                                 | An L40S has ~35 GB free after Kev-4B weights: several hundred hot states per pod. A hit turns a 15 ms prefill into a ~1 ms copy. |
| Host prefix tier    | same                                                 | same                                        | Pod DRAM, spill from GPU                                   | PCIe copy is ~1 to 2 ms. Thousands more states per pod. LMCache's CPU backend, once on vLLM.                                     |
| Shared prefix store | same                                                 | same                                        | Not built. LMCache or Mooncake over RDMA if ever justified | Only pays off with RDMA-class fabric and states near the 8k cap.                                                                 |

Not in the table: DynamoDB, Postgres, and Valkey as a KV tensor store.
A 60 MiB value at hundreds of hits per second is multiple GB/s of network to save a 15 ms recompute that the fetch would take as long as.
The state-of-the-art systems (LMCache tiers, Mooncake's KV pool, Dynamo's KV block manager) agree on the shape: tensors stay next to the GPU, and only the index of who holds what is shared.

The per-pod cache only hits if the same state lands on the same pod, which is the router's job: rendezvous hashing on the state hash over ready pods, least-loaded fallback when the affine pod is over capacity.
Dynamo's KV-aware router and llm-d's endpoint picker do the same at fleet scale with a shared KV index, which we skip because our prefixes are not worth fetching remotely.
Model version is in every key, so a rollout invalidates nothing explicitly.

## 7. Observability and SLOs

Per request at the gateway: team, model version, state tokens, question count, result-cache hit, prefix-cache hit (reported back by the pod), pod, queue wait, model time, total time.
These ride on the `$ai_generation` event the gateway already emits.
No state text anywhere in logs or events.

Pod metrics through the existing Prometheus stack: batch size and token count histograms, queue wait, prefix cache hit ratio and occupancy, GPU utilization, 503 count.
Team is never a label on a pod metric; it lives in the usage event only.

SLOs are per region: availability, p50 and p99 total time for warm and cold state, and result-cache hit ratio as a leading indicator of cost.

## 8. Phases

1. **Gateway integration on borrowed GPUs.** The `kev` host kind, the `/v1/systemone` shape, pricing, and the result cache in the gateway. Kev's stock server as the host, on a Lambda dev box or a Modal function. Internal callers only. Measure state lengths and cache hit ratios on real PostHog use cases.
2. **GPU node pool.** Bottlerocket NVIDIA `EC2NodeClass`, a `g6e` NodePool through the golden chart, the NVIDIA device plugin add-on, IRSA and the base-models bucket grant, the Kev pod image through the normal ECR and state-update pipeline. Kev's stock server as the pod for now. Retire the borrowed GPUs.
3. **vLLM port and router.** The pooling model plugin, the parity harness, the affinity router, the host DRAM tier. Open to customers behind a project secret key scope.
4. **Glaucon** as the second pooling model on the same pool.

A bulk or offline lane is out of scope. If one is wanted later, it is a Temporal workflow calling the same gateway, and nothing here has to change for it.

## 9. Open questions

- What is the real hit ratio of the result cache and the prefix cache on PostHog's own use cases (replay, tickets, error groups)? This decides pod count more than anything else.
- What share of PostHog's states are under 528 tokens? That decides whether the vLLM port can rely on upstream prefix caching or needs its own whole-state cache.
- Does the gateway grow pod-level affinity for served hosts, or does the router stay a separate Deployment?
- Is Kev-0.8B accurate enough for the high-volume use cases? It changes the throughput math by about 5x.
- What does SGLang's hybrid GDN prefix cache do at the same granularity? Its radix cache is token-exact for attention layers; the GDN checkpoint interval is the number to check.
- How do Glaucon's FlexAttention masks map onto vLLM's attention layer? Worth settling before the recipe hardens.

## Sources

- Kev: [repository](https://github.com/jaredpalmer/kev), `kev/serve.py` (prefix cache, single-request lock), `kev/model.py` (row construction, pointer head).
- Jev: [Introducing System One models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [TypeSafe System One docs](https://docs.typesafe.ai/concepts/system-one).
- Qwen3.5-4B config: [Hugging Face](https://huggingface.co/Qwen/Qwen3.5-4B/raw/main/config.json). Hybrid attention background: [Raschka, Hybrid Attention](https://sebastianraschka.com/llm-architecture-gallery/hybrid-attention/).
- AI gateway: [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway), `docs/product.md` and `docs/openweight-models.md`.
- vLLM: [pooling models](https://docs.vllm.ai/en/latest/models/pooling_models.html), [V1 feature matrix](https://docs.vllm.ai/en/latest/usage/v1_guide.html), [out-of-tree model registration](https://docs.vllm.ai/en/latest/contributing/model/registration.html).
- KV cache tiers: [LMCache](https://github.com/lmcache/lmcache), [Mooncake](https://arxiv.org/pdf/2407.00079).
- Routing and batching: [NVIDIA Dynamo KV-aware routing](https://docs.nvidia.com/dynamo/latest/user-guides/kv-cache-aware-routing), [Baseten on KV-aware routing](https://www.baseten.co/blog/how-baseten-achieved-2x-faster-inference-with-nvidia-dynamo/).
- Providers: [Lambda On-Demand Cloud overview and regions](https://docs.lambda.ai/public-cloud/on-demand/), [How Thunder Compute works (GPU over TCP)](https://www.thundercompute.com/blog/how-thunder-compute-works-gpu-over-tcp).
