# Meep in PostHog

Meep is a native desktop client with an offline SQLite replica. The Meep Django product stores each member's topics, files, views and command receipts in their PostHog project. Topic chat uses PostHog Tasks. The desktop signs in through the browser and keeps its credentials in the macOS Keychain. The stateless `meep-domain` executable applies the same rules as the desktop replica.

## Local development

From the main PostHog checkout in its development environment, enable the Tasks and MCP intents once with `bin/hogli dev:setup` if needed. Start the stack and open the native app.

```sh
bin/hogli start -y -d
bin/hogli wait
sh products/meep/desktop/scripts/local.sh
```

Stack startup initializes the Postgres tables. The launcher builds the stateless domain helper. The native app uses Django at port 8010 and PostHog MCP at port 8787 for local reads. Set `POSTHOG_MCP_URL` for a different MCP endpoint.

Select the local account in the browser. Opening the app again reuses the Keychain session. The region, project and user determine the replica filename. To connect to a deployed version in another region, run `cargo run --locked -p meep -- --posthog us` or `--posthog eu` from `products/meep/desktop`.

Meep starts empty for each project member. Creating a topic starts its mission in PostHog Tasks. The topic conversation can start up to three independent board tasks at once per project member. Each task appears beside the message that started it and in the Tasks tab. Open a task to see its conversation, tool activity, and results, or send a follow-up. Results and questions return to the topic conversation even while the desktop is closed. New topic conversations receive the delegation scope when they start.

The desktop can read project data and approved read-only tools from installed MCP servers when rendering a view. PostHog Tasks handles chat, board work and view authoring. Ask in topic chat for a Scout to investigate something regularly. Its findings are available in chat and its details appear under Routines. Scheduled workflows, external webhook and SaaS delivery, and full run artifact handling are tracked in the [MCP architecture and feature plan](MCP.md).

## Verification

```sh
cargo build --locked --manifest-path products/meep/domain/Cargo.toml
pytest products/meep/backend/tests
sh products/meep/desktop/scripts/check.sh
```
