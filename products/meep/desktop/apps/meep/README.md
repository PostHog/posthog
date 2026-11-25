# Meep

A native Mac workspace for the things you look after. Sign in to PostHog, give a topic a mission, and ask its agent to add relevant PostHog objects to Context. The inbox holds agent-authored reports; questions stay in task conversations. Open **Needs you** to review work that needs your decision.

```sh
cargo build -p meep-server
cargo run -p meep
```

The app starts the server on loopback when needed. Leave the server running when you close the window. For a release build, run `sh scripts/meep.sh`. For a hosted server, export its device credential as `MEEP_DEVICE_TOKEN` and run `cargo run -p meep -- --server https://your-host`. The app saves the credential in the macOS Keychain. Unset the variable for subsequent launches, or supply a replacement token to rotate it. On the first launch after upgrading from token-based replica filenames, use the original server URL and token so the app can adopt the existing outbox. The local replica lives at `~/Library/Application Support/Meep/replica.sqlite`. Hosted devices use a separate replica beside it.

Choose US or EU in Settings and sign in using the browser. The server receives its own credentials for background work. Signing out removes the app's Keychain copy. Choose **+ → Topic** and set a mission. A topic is one agent: you land in its chat, setup runs as the first turn, and you keep talking to the same agent in the same conversation. The Overview on the right lists Needs you, Tasks, Inbox, Files, Routines, Mission, Goals, Facts, Linked and Rules; open any of them and the breadcrumb takes you back. Tasks are side work only: for you, for the agent to pick up later, or for a sub-agent when the work is completely separate. Ask in chat for the PostHog objects you want to add as passive context. Adding Context does not create a watch or routine. When you explicitly request monitoring, native insight and flag watches can poll through MCP. Connected services can use an approved read-only listing tool or receive events from a configured PostHog workflow. Push-only sources show the source kind and key to use in the workflow. [Workflow setup and payload](../../crates/meep-connectors/configuration.md)

Use ⌘K to search, ⌘N for a new topic, j/k or ↑/↓ to move through items, and ⌘[ to go back. Drag a task to change its column. Drag a topic to a section heading and double-click a section name to rename it. Workflow switches sync to the bound PostHog flow, including changes made offline.

For development with hot reloading, run `sh scripts/dev.sh`. Saved edits to render code apply to the open window; press `r` in its terminal after structural changes. It needs the Dioxus CLI 0.7 (`cargo install dioxus-cli --version "^0.7"`). Add `--local` to use local PostHog, described below.

Run `cargo test -p meep` for the interaction tests. To save light and dark native screen previews, set `MEEP_PREVIEW_DIR` to an output directory and run `cargo test -p meep --features ui-previews --test previews`. The preview test uses a temporary replica and loopback services. To review a change across every page at once, run `sh scripts/screens.sh [name]`: it renders the key screens into `.scratch/screens/<name>/` and stitches a light and a dark collage (needs `ffmpeg`).

A US installation can use a provisioned PostHog OAuth app by placing its public client ID in `~/Library/Application Support/Meep/posthog-us-client-id`. Register `http://127.0.0.1:43180/callback` under Redirect URIs. Other installations use dynamic registration. Both use the same OAuth scopes. Agent tools and explicitly configured workflow callbacks need a reachable public address for the Meep server.

To record a demo while you keep using the machine, build with `cargo build -p meep --bin meep --features demo-driver` and start the app with `MEEP_DEMO_SOCKET=/short/path.sock` and `GPUI_DRAW_WHEN_HIDDEN=1`. The app then replays input from that Unix socket into its own window, one JSON object per line (`{"op":"move","x":..,"y":..}`, `down`, `up`, `scroll`, `text`, `key`; positions are window points), draws a cursor where the replayed pointer is, keeps drawing while other windows cover it, and does not take focus when it starts. Record the window with any capture that reads a covered window's contents; ScreenCaptureKit only delivers frames while the window is composited.

To try the agent against a local PostHog, start PostHog yourself at `http://localhost:8010` with Tasks, sandboxes and its MCP server at `http://localhost:8787/mcp`, then run:

```sh
sh scripts/local.sh            # build and open the app
sh scripts/local.sh --hot      # the same, with hot reloading
sh scripts/local.sh --reset    # start clean: no topics, sign in again
```

Choose **Local** when signing in. The script keeps Meep's data in `$MEEP_DEV_DIR` (default `.local/meep-dev`), separate from the standard app, including its replica, OAuth registration and Keychain credentials. On first run it registers Meep's OAuth application with that PostHog (`scripts/posthog-local-app.sh`). PostHog's sandboxes must reach Meep for topic tools and workflow callbacks, so the script also gives Meep a public address: `MEEP_PUBLIC_BASE_URL` if you set one, otherwise a cloudflared quick tunnel it starts (`brew install cloudflared`). A quick tunnel's address changes when it restarts; the script then restarts Meep's server so it uses the new one. The isolated server listens on `127.0.0.1:47951`; set `MEEP_DEV_PORT` to change it.

For agent runs to succeed, the local PostHog also needs what PostHog Tasks needs: sandboxes (`SANDBOX_PROVIDER=docker`), an organization whose plan includes PostHog Code, and model access through the AI gateway. Meep cannot set these up; a run that fails on them shows PostHog's error in the chat.

`scripts/posthog-local-app.sh --verify /path/to/posthog` also marks the OAuth application verified through that PostHog checkout's `manage.py shell`, which removes the "Unverified application" warning from the consent screen. Run it again after the app requests new scopes, then sign in again.

The ignored `local_posthog_browser_sign_in_registers_with_the_real_server` test exercises real sign-in and account registration against a running local server on port 47951. Set `MEEP_LIVE_SERVER_DATA` to its server data directory, `MEEP_LIVE_OAUTH_CLIENT_ID_FILE` to the local OAuth client's public ID file, and `MEEP_LIVE_OAUTH_HELPER` to an executable that authorizes the URL in `MEEP_LIVE_AUTHORIZE_URL` for a fixture user and follows its loopback callback. The helper must keep credentials private. Run the test with `cargo test -p meep local_posthog_browser_sign_in_registers_with_the_real_server -- --ignored`. This test registers the fixture account with that server.
