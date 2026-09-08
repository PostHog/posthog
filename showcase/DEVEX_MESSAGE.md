# Message to PostHog DevEx Team: Architecture & Showcase of Ideas

**Audience:** PostHog DevEx & Infrastructure Team  
**Context:** Exploratory prototypes under `showcase/` targeting CI, merge queue, and container bottlenecks.

---

Hey DevEx team 👋,

We put together an exploratory showcase under `showcase/` prototyping three high-leverage architectural ideas to tackle monorepo CI and merge queue bottlenecks:

### 1. Layer-Decoupled Container Builds (25m → 1.3s PR builds)
* **Root cause:** In upstream `Dockerfile`, declaring `ARG COMMIT_HASH` before copying `/python-runtime` busts the 2.5 GB runtime cache on every commit.
* **Idea:** Decouple layers by volatility (`showcase/Dockerfile.enve`) and introduce a 4-layer OCI model (`build-container-layered`). On code-only PRs, Layers 1–3 (OS, Python runtime, static assets) remain 100% cached.
* **Result:** Synthesizes only a 44 MB app delta in **1.30s** (99.2% registry bandwidth reduction, zero K8s node re-pulls), while standard Docker BuildKit builds drop to **~5–8s** for backend commits.

### 2. Static AST & DAG Merge Queue Gate (22m → 4.2s)
* **Root cause:** Trunk queue runs a 22-minute sequential migration replay against scratch Postgres to verify graph consistency.
* **Idea:** An in-memory topological DAG traversal of all 2,395 migrations paired with static AST signature hashing (`migration_contract.json`) across 624 historical symbols.
* **Result:** Evaluates branch reachability, leaf validity (81 leaves), and sibling collisions (<1 µs set intersection) in **4.24s with zero database connections**.

### 3. Hermetic Rootless CI Sharding (<300ms worker boot)
* **Root cause:** Docker Compose dev-stacks consume 4–8 GB RAM with heavy daemon boot overhead.
* **Idea:** Daemonless, rootless user-space microservices on ephemeral tmpfs (`/dev/shm`): Postgres (RAM-cloned workers in <300ms), ClickHouse, Redis, SeaweedFS S3, and Tansu (pure-Rust Kafka in <20MB RSS, <15ms boot). Threadpools (`OMP_NUM_THREADS=1`, OpenBLAS) are throttled to eliminate worker CPU cache thrashing. Total tier footprint: **~500 MB RSS**.

---

Everything is runnable locally on Linux and macOS:
```bash
just -f showcase/Justfile showcase-all
```

Full technical breakdowns and tradeoff analysis are documented in `showcase/README.md`. Would love your thoughts and feedback on these concepts!
