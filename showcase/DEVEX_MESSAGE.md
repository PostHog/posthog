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

### 3. Hermetic Rootless CI Sharding & Test Matrix (100% Shards Validated)

- **Root cause:** Docker Compose dev-stacks consume 4–8 GB RAM with heavy daemon boot overhead; concurrent worker migrations stall runs.
- **Idea:** Daemonless, rootless user-space microservices on ephemeral tmpfs (`/dev/shm`): Postgres (`schema-latest.sql.gz` restores all 2,699 migrations in 1.6s; RAM-cloned workers in <200ms), ClickHouse 26.7, Redis, SeaweedFS S3, and Tansu (pure-Rust Kafka in <20MB RSS, <15ms boot).
- **Result:** 100% of the monorepo backend matrix (**all 5 shards**) validated on 6 workers with fail-fast mechanics. Total tier footprint: **~500–670 MB RSS**.

### 4. AI Agent Developer Experience (`enve handbook` & `enve schema`)

- Type-safe declarative blueprints and environment contracts for developers and AI agents alike. Run `enve handbook` for zero-daemon invariants or `enve schema` to introspect `#DevEnvironment` and `#Service` blueprints directly.

---

Everything is runnable locally on Linux and macOS:

```bash
just -f showcase/Justfile showcase-all
```

Full technical breakdowns and tradeoff analysis are documented in `showcase/README.md`. Would love your thoughts and feedback on these concepts!
