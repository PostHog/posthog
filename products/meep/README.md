# Meep in PostHog

Meep is a native desktop client with an offline SQLite replica. The Meep Django product stores each member's topics, files, views and command receipts in their PostHog project. Topic chat uses PostHog Tasks. The desktop signs in through the browser and keeps its credentials in the macOS Keychain. The stateless `meep-domain` executable applies the same rules as the desktop replica.

## Local development

Run these commands from the PostHog root in its development environment.

```sh
cargo build --locked --manifest-path products/meep/domain/Cargo.toml
python manage.py migrate
```

Start PostHog from this checkout with the usual local services. The desktop expects local PostHog at port 8010. Topic chat requires Tasks, sandbox workers and PostHog MCP. Open the native app with:

```sh
sh products/meep/desktop/scripts/local.sh
```

Select the local account in the browser. Opening the app again reuses the Keychain session. The region, project and user determine the replica filename. To connect to a deployed version in another region, run `cargo run --locked -p meep -- --posthog us` or `--posthog eu` from `products/meep/desktop`.

Meep starts empty for each project member. Creating a topic starts its mission in PostHog Tasks. Board items run when explicitly started.

The desktop can read project data and approved read-only tools from installed MCP servers when rendering a view. PostHog Tasks handles chat, board work and view authoring. Scheduled routines, webhook and SaaS delivery, Scout sync, and full run artifact handling still require implementation in the PostHog product.

## Verification

```sh
cargo build --locked --manifest-path products/meep/domain/Cargo.toml
pytest products/meep/backend/tests
sh products/meep/desktop/scripts/check.sh
```
