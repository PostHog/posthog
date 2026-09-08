# Message to PostHog DevEx Team: Architecture & Showcase of Ideas

**Audience:** PostHog DevEx & Infrastructure Team  
**Context:** Exploratory prototypes under `showcase/` targeting CI, merge queue, and container bottlenecks.

---

Hey DevEx team 👋,

We put together an exploratory showcase under `showcase/` prototyping three high-leverage architectural ideas to tackle monorepo CI and merge queue bottlenecks:

### 1. Layer-Decoupled Container Builds (25m → 1.3s PR builds)

- **Root cause:** In upstream `Dockerfile`, declaring `ARG COMMIT_HASH` before copying `/python-runtime` busts the 2.5 GB runtime cache on every commit.
- **Idea:** Decouple layers by volatility (`showcase/Dockerfile.v2`) and introduce a 4-layer OCI model (`build-container-layered`). On code-only PRs, Layers 1–3 (OS, Python runtime, static assets) remain 100% cached.
- **Result:** Synthesizes only a 44 MB app delta in **1.30s** via multi-threaded zstd (99.2% registry bandwidth reduction, zero K8s node re-pulls), while standard Docker BuildKit builds drop to **~5–8s** for backend commits.

### 2. Static AST & DAG Merge Queue Gate (22m → 4.2s)

- **Root cause:** Trunk queue runs a 22-minute sequential migration replay against scratch Postgres to verify graph consistency.
- **Idea:** An in-memory topological DAG traversal of all 2,395 migrations paired with static AST signature hashing (`migration_contract.json`) across 624 historical symbols.
- **Result:** Evaluates branch reachability, leaf validity (81 leaves), and sibling collisions (<1 µs set intersection) in **4.24s with zero database connections**.

### 3. Eliminating Docker Service Overhead in CI (~50% Job Speedup)

- **Root cause:** In upstream CI matrix jobs ([`.github/workflows/ci-backend.yml`](../.github/workflows/ci-backend.yml)), every runner pays an unavoidable **80s to 100s Docker setup tax** before tests even start. Verified from real PostHog production CI (PR [#95897](https://github.com/PostHog/posthog/pull/95897), Run [`34257945157`](https://github.com/PostHog/posthog/actions/runs/34257945157)):
  - [`Start services` (Step 5)](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546873#step:5:1): **5s**
  - [`Wait for Docker services` (Step 17)](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546873#step:17:1): **25s – 30s**
  - [`Prime test_posthog` (Step 19)](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546873#step:19:1): **38s – 45s**
  - [`Register Temporal search attributes` (Step 21)](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546873#step:21:1): **13s – 15s**
  - Cache miss penalty ([`Migrate from scratch`](https://github.com/PostHog/posthog/blob/master/.github/workflows/ci-backend.yml#L921-L941)): **+17m – 22m** per runner.
- **Idea:** Replace Docker Compose with in-process, rootless `enve` services on ephemeral tmpfs (`/dev/shm`): Postgres (`schema-latest.sql.gz` restores all 2,699 migrations in 1.6s; RAM-cloned workers in <200ms), ClickHouse 26.7, Redis, SeaweedFS S3, and Tansu (pure-Rust Kafka in <20MB RSS, <15ms boot). Entire test stack ready in **~2.8s total**.
- **Result:**
  - Fast suites (e.g. [[`ai-gateway, replay`](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546873)]): Total job drops from 186s (3m 06s) to **~45s (75% faster / 4.1x)**.
  - Medium suites (e.g. [[`tasks 3/5`](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546465)], [[`batch-exports 9/10`](https://github.com/PostHog/posthog/actions/runs/34257945157/job/102169546193)]): Drops from 320s (5m 20s) to **~145s (2m 25s, 54% faster, saving ~2 minutes per runner)**.
  - Fleet impact: Across 25 parallel matrix jobs per PR, Docker spinup burns **~36.7 runner-minutes per run** that can be eliminated. Total tier footprint: **~500–670 MB RSS** (vs. 4–8 GB for Docker Compose). 100% of the monorepo backend matrix (**all 5 shards**) validated on 6 workers. Run `showcase/scripts/compare_ci_overhead.sh` to reproduce.

### 4. AI Agent Developer Experience (`enve handbook` & `enve schema`)

- Type-safe declarative blueprints and environment contracts for developers and AI agents alike. Run `enve handbook` for zero-daemon invariants or `enve schema` to introspect `#DevEnvironment` and `#Service` blueprints directly.

---

Everything is runnable locally on Linux and macOS:

```bash
just -f showcase/Justfile showcase-all
just -f showcase/Justfile compare-ci-overhead
```

Full technical breakdowns and tradeoff analysis are documented in `showcase/README.md`. Would love your thoughts and feedback on these concepts!
