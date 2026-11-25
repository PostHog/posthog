# meep-ai

Ask PostHog System One for calibrated decisions and use chat completions for writing. Supply a PostHog project secret (`phs_`) or OAuth credential (`pha_`) with the literal scope `llm_gateway:read`. A host can implement `TokenSource` to refresh OAuth credentials.

The default US origin is `https://ai-gateway.us.posthog.com`. Set `Config::base_url` for another deployment. Remote servers require HTTPS. Loopback development servers may use HTTP. The EU origin `https://ai-gateway.eu.posthog.com` is unverified. The decision and writing models default to `posthog/hogference/jevk5-fp8-0.2` and `openai/gpt-5.4-mini`. Both are configurable.

```no_run
use meep_ai::{Config, Gateway, Message, Role};
use std::sync::Arc;

# #[tokio::main(flavor = "current_thread")]
# async fn main() -> Result<(), Box<dyn std::error::Error>> {
let token = std::env::var("POSTHOG_TOKEN")?;
let gateway = Gateway::new(Config::default(), Arc::new(token))?;
let message = Message { role: Role::User, content: std::env::var("TOPIC_NOTE")? };
println!("{}", gateway.write("Summarize this note.", &[message], 128).await?);
# Ok(())
# }
```
