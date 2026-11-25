# meep-posthog

A host chooses a PostHog origin and project and supplies the access token for each request. The `api` module is always available, including with default features disabled. Enable additional Cargo features to use the corresponding modules.

| Feature | What it provides |
| --- | --- |
| `oauth` | Public client registration, browser sign-in with PKCE, loopback callbacks and in-memory token refresh. |
| `tasks` | Create tasks, post discussion replies, control agent runs, upload staged or run-scoped attachments and read session logs. |
| `chat` | Decode paginated task logs into turns, tool calls and permission requests. Enables `tasks` and uses `meep-protocol`. |
| `mcp` | Discover and invoke connected installations through `Gateway`. Use `McpClient` to initialize an OAuth-authenticated streamable HTTP session with PostHog’s own MCP server, list tools and call them. |
| `workflows` | Dispatch a bound flow, check an invocation’s status and list recent runs. Reuse the same operation key when retrying a dispatch. |

## Bind a collection

This example constructs a Tasks endpoint for a fixture project. Construction validates the project and collection locally. The host can then use the endpoint’s `get` or `post` methods with a current access token.

```rust
use meep_posthog::api::ProjectEndpoint;

# fn main() -> anyhow::Result<()> {
let origin = "http://127.0.0.1:8000";
let _tasks = ProjectEndpoint::new(origin, 7, "tasks")?;
assert!(ProjectEndpoint::new(origin, 7, "../tasks").is_err());
# Ok(())
# }
```
