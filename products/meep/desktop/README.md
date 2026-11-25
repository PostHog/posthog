# Meep

Meep is a collection of Rust libraries for native desktop applications. A host can compose the shell and renderer with its own storage, agents and connectors, or use the supplied PostHog adapters.

## Run the desktop examples

```sh
cargo run --locked -p meep-examples
cargo run --locked -p meep-examples -- --open tools --standalone
```

The gallery includes the native shell, settings, appearance, personalization, a task discussion, a rendered reading list, an editable Markdown document, MCP setup, local notes and a workflow. It starts with isolated state and needs no account. [Examples and composition guide](examples/desktop/)

An agent-authored workflow can supply the data for a view through a host-selected backend. [Workflow composition and PostHog bindings](docs/workflows.md)

## Choose the pieces your host needs

| Package | Responsibility | First-party dependencies |
| --- | --- | --- |
| [meep-ui](crates/meep-render/meep-script/meep-ui/) | Semantic theme, typography, controls, settings forms, composer and layouts. Disable default features for headless theme tokens. | None |
| [meep-shell](crates/meep-shell/) | Native glass window, workspace and Settings navigation, palette picker, View session pane, topic chat transcript and composer, and agent/model picker | meep-ui, meep-protocol |
| [meep-script](crates/meep-render/meep-script/) | JavaScript engine, validation, datasets, scene models and authoring contract | meep-ui with toolkit features disabled |
| [meep-render](crates/meep-render/) | Mount a script in a GPUI window. The host implements the operations scripts can request. | meep-ui, meep-script, meep-workflows, meep-workflow-ui (feature-dependent) |
| [meep-workflows](crates/meep-render/meep-workflows/) | Workflow definitions and an optional interpreter. The host supplies persistence and external effects. | None |
| [meep-workflow-ui](crates/meep-render/meep-workflow-ui/) | Native step outline, timings, visual form and JSON or expression editor | meep-ui, meep-workflows (native editor) |
| [meep-ingest](crates/meep-ingest/) | Normalize connector events, group messages, route watches and deduplicate replays | meep-topic, meep-store |
| [meep-engine](crates/meep-engine/) | Run topic inboxes, task workers and workflows, persist changes and search across topics | meep-ai, meep-topic, meep-ingest, meep-policy, meep-wire, meep-connections, meep-store |
| [meep-store](crates/meep-store/) | Typed, revisioned SQLite records and atomic transactions on a host-owned connection | None |
| [meep-protocol](crates/meep-protocol/) | Serializable agent session and transcript records | None |
| [meep-notifications](crates/meep-notifications/) | Scoped system notification delivery, scheduling, cancellation and an in-memory backend | None |
| [meep-posthog](crates/meep-posthog/) | Project-scoped HTTP (`api`, always available) with optional `oauth`, `tasks`, `chat`, `mcp` and `workflows` features | meep-protocol (`chat`) |

Use a Cargo path dependency or pin a Git dependency to a commit in this repository. When copying files, keep each package's path dependency layout. Copying `crates/meep-render/` includes its script engine, workflow runner, widgets and assets. For the shell, copy its dependency directories too. The PostHog adapters can run in a headless host.

```toml
[dependencies]
meep-ui = { path = "../meep/crates/meep-render/meep-script/meep-ui" }
meep-posthog = { path = "../meep/crates/meep-posthog", features = ["tasks"] }

```

**Agent chat.** Use `meep_posthog::chat` for incremental session-log decoding without GPUI. It exposes turns, tool and thinking blocks, outstanding permissions, turn boundaries and the runtime’s configuration choices. A desktop host can render those records with `meep-shell` and send commands through `meep_posthog::tasks`. To reuse View’s composer picker, supply agent groups and acknowledged model and effort values to `meep_shell::model_picker::ModelPicker`. The widget emits model, effort and refresh events. The host owns the catalogue and execution backend.

**Generated views.** Supply `meep_render::sdk::ViewHost` and mount a validated script in a GPUI window. The host maps permitted requests to its chosen connectors. For PostHog-connected servers, use the installation ID, upstream tool name and argument schema returned by the MCP adapter. The server evaluates the signed-in user's grants on every call. A different renderer can consume script output directly. A host that builds its UI in Rust can use just the widgets.

**Settings and offline data.** UI controls edit application-owned values. The host can persist settings, drafts and metadata transactionally with `meep-store`. Each application owns its schema and decisions about remote conflicts and deletions. Offline synchronization still requires a server API, an outbox and a conflict policy.

## Development

Run `sh scripts/check.sh` to check formatting, run Clippy and execute the workspace tests. Use `sh scripts/clean.sh` to clear disposable files in `.scratch/` or `sh scripts/clean.sh --build` to also remove compiled Cargo profiles.

The design system, desktop components and renderer are copied from [View at 49510b5](https://github.com/puemos/view/tree/49510b5a6a3573c404fb49e09acab466baa0b73d). Third-party assets and GPUI packages retain their upstream names and notices. See the [asset notices](notices/).
