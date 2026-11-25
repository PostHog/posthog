# Desktop examples

Open the shell from the repository root.

```sh
cargo run --locked -p meep-examples
```

The sidebar holds workspace pages. **Settings** at the bottom, or **⌘,**, opens preferences in the same window. **Back to workspace** or **Escape** returns to the current page. Narrow windows use the titlebar sidebar button to show the navigation. Open a single example with `--open` and `--standalone`. For example, this opens the MCP setup flow on its own.

```sh
cargo run --locked -p meep-examples -- --open tools --standalone
```

| Example | Entry | Try it | Implementation |
| --- | --- | --- | --- |
| Shell | No arguments | Switch pages, narrow the window and open the sidebar. Visit Settings and return to a draft. | [Native host](src/main.rs) using `meep-shell` and `meep-ui` |
| Settings | `--open settings` | Rename the workspace. Save and check the window title in Mission Control. | [Settings form](src/preferences.rs) using `meep-ui` and `meep-store` |
| Appearance | `--open appearance` | Choose Graphite. Navigate to another page, then return and select Use system. | [Palette previews](../../crates/meep-render/meep-script/meep-ui/src/appearance.rs), [nine presets](../../crates/meep-render/meep-script/meep-ui/src/palettes.rs) and the shell appearance bridge |
| Personalization | `--open personalization` | Choose a start page. With a data file, relaunch without `--open` to use it. | [Host preferences](src/preferences.rs) |
| Tasks | `--open tasks` | Create a task, add a discussion reply and refresh to read it back over HTTP. | [Task view](views/tasks.js) and `meep_posthog::tasks` |
| Views | `--open views` | Mark articles read, filter to Unread, then restore them from All articles. | [Reading list](views/reading.js) using `meep-script` and `meep-render` |
| Document | `--open document` | Edit the field notes, toggle a checklist item or type `/h2` on an empty line to insert a heading. | [Document](views/document.js) using the native `BlockEditor` and the Markdown converters |
| Tools | `--open tools` | Connect the Reading library template, discover its advertised tool and run it to list collections. | [Tool view](views/tools.js) and `meep_posthog::mcp` |
| Storage | `--open storage` | Save and delete a note. Reopen the same data file to verify persistence. | [Notes](views/storage.js) using `meep-store` |
| Workflows | `--open workflows` | Refresh a keyed dataset, inspect the run and edit its steps. Switch data sources with `--workflow-backend local\|posthog-fixture` or load an authored definition with `--workflow-file PATH`. | [Workflow](views/run-history.json) · [Host bindings](../../docs/workflows.md) |

## State and services

The default workspace uses SQLite in memory. Supply an example-owned path to retain settings and notes across launches.

```sh
cargo run --locked -p meep-examples -- --data ./example.sqlite --open personalization
cargo run --locked -p meep-examples -- --data ./example.sqlite
```

The Tasks and Tools examples start an ephemeral HTTP project on loopback on first use. They use the production Rust clients for their requests and keep the example project in memory. Task runs with a model and real tool authorization require the live service.

## Compose another application

Mount a script with `meep_render::mount`, a `ViewContext`, and an implementation of `ViewHost`. Each example script names its own operations. The reading list needs no external source. The notes view expects `notes.list`, `notes.save` and `notes.remove`. Each host receives just its own services. A different application can keep a view and substitute a database, task provider or tool registry. The [source adapters](src/service.rs) and [loopback fixture](src/fixture.rs) live in the example package. The reusable crates have no dependency on this gallery.

A native-only host can use the [shell](../../crates/meep-shell/) and [widgets](../../crates/meep-render/meep-script/meep-ui/) directly. The settings and appearance examples take this path. Implement `workspace::WorkspaceHost` to supply app and settings destinations and render their contents. Call `workspace::install_menus` once and open each window with `workspace::open_window` to configure the native material. The host owns its pages, serialized preferences and services. Script drafts stay with their mounted page for the lifetime of the window.

## Other runnable crate examples

| Command | Demonstration |
| --- | --- |
| `cargo run --locked -p meep-render --example counter` | Minimal native host with a single script and source |
| `cargo run --locked -p meep-workflows --example in_memory` | Successful, denied and cancelled runs using an in-memory workflow host |
| `cargo run --locked -p meep-desktop --example window_lease` | Claim, contention and release for a temporary Unix workspace |
| `cargo run --locked -p meep-ipc --example roundtrip` | Authenticated Unix socket request using a protocol record and a private temporary directory |

### A workflow calls a native capability

`cargo run --locked -p meep-examples --example workflow_alert` runs a real workflow with a `notify` step against an in-memory notification center. Its host checks a per-caller grant, supplies the namespace and resolves the notification title from workflow input. The example exercises both denied and granted runs. Substituting `SystemNotifications` at the composition point submits to Notification Center from an authorized Mac bundle.
