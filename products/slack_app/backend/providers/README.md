# Chat providers

The slack_app product is growing into a multi-provider chat product: the same agent loop that answers Slack mentions today should be reachable from other chat surfaces (Telegram is the first planned addition, with a central PostHog-owned bot). This package is phase 1 of that plan — a pure refactor that names the seams a second provider will plug into, with Slack as the only implementation and zero behavior change.

## What's abstracted (the minimal loop)

Only the minimal conversation loop is behind the seam: inbound message → webhook signature validation → user resolution → thread-context collection → task creation → text reply in the same conversation, plus routing task-lifecycle output back into the originating thread.

- `base.ChatProvider` — the provider interface: `validate_webhook`, `region_claims_secret`, `find_linked_user`, `get_user_email`, `post_message`, `add_reaction`, `collect_thread_messages`. One instance is bound to one `Integration` row (a workspace credential).
- `base.ConversationRef` — provider-neutral conversation identity (`channel_id` + `thread_id`; for Slack that's channel + `thread_ts`).
- `base.ChatThreadHandler` — a `Protocol` mirroring `SlackThreadHandler`'s public surface, used by the tasks product to post run updates back into the thread. It's a Protocol (not a base class) so `slack_thread.py` needs no providers import: the registry imports the implementation, never the reverse.
- `slack.SlackChatProvider` — pure delegation onto the existing Slack modules. No behavior lives here.
- `registry` — explicit kind → provider dict, plus `thread_handler_from_context`, which dispatches a serialized thread context (`{"provider": ..., ...}`) to the right handler. A missing `provider` key means Slack: every context persisted before the key existed is Slack's, and that default must survive.

Cross-region routing has a provider-neutral claims endpoint: `/chat/<provider>/workspace/claims/` (see `services/region_auth.py` and `services/region_claims.py`). Both Cloud regions share a per-provider secret; probes are signed with neutral `X-PostHog-Region-*` HMAC headers. The Slack provider also still accepts the legacy `/slack/workspace/claims/` route and Slack-style headers, so regions can deploy independently.

## What's deliberately NOT abstracted

Interactive elements (repo picker, buttons, modals), App Home, settings surfaces, onboarding, link unfurling, slash and rules commands, the per-conversation queue workflow, the inbound routing pipeline, task-description building, and `SlackThreadTaskMapping` (with its Slack-side call sites) all stay Slack-private. Abstract them only when a second provider actually needs the capability.

The inbound webhook views also stay per-provider: the envelope layer (Slack's `url_verification` challenge, retry headers, 3-second ack budget) is where providers differ most, so each provider gets its own view in `posthog/urls.py` rather than a generic dispatcher.

## Phase 2 contract: `InboundMessage`

Phase 1 keeps the raw Slack event dict flowing into the pinned Temporal workflow inputs, so no canonical inbound type exists yet. When a second provider lands, its webhook view should parse its payload into something like:

```python
@dataclass(frozen=True)
class InboundMessage:
    conversation: ConversationRef
    message_id: str
    sender_id: str          # provider-native user id
    text: str
    is_untagged_thread_reply: bool
    raw: dict[str, Any]     # provider payload, for provider-private paths
```

and drive a provider-neutral routing pipeline with it. Don't introduce this type before that pipeline exists — it would be dead code.

## Adding a provider (checklist, annotated with where Telegram landed)

1. Implement `ChatProvider` in `providers/<name>.py`, delegating to provider-specific service modules; register it in `registry._PROVIDERS`. _Telegram: `providers/telegram.py`, delegating to `services/telegram_api.py` (hand-rolled Bot API client) and `services/telegram_link.py`._
2. Add the webhook view (`/<name>/event-callback` in `posthog/urls.py`) doing signature validation via the provider class, plus the provider's secret to `region_auth.region_claims_secret` and its kinds to `region_claims._PROVIDER_CLAIM_KINDS`. _Telegram: `views/telegram_events.py`; secrets are the `TELEGRAM_APP_BOT_TOKEN` / `TELEGRAM_APP_WEBHOOK_SECRET` instance settings, and the webhook secret doubles as the region-claims secret._
3. Identity linking: add the provider kind to `UserIntegration.IntegrationKind` and build a linking flow; reuse `_pick_accessible_linked_user` in `services/slack_user_oauth.py`. _Telegram: no email and a 64-char `/start` payload limit, so linking rides one-shot cache-backed codes (`services/telegram_link.py`) minted by the login-gated `views/telegram_link.py` views._
4. Conversation binding: decide how a chat maps to an `Integration` row. _Telegram: every chat (DM or group) binds to exactly one team via `kind="telegram"`, `integration_id=chat_id`; DMs bind on `/start` redemption, groups on `/connect <code>` with a minter-match guard (the pasted command is visible to the whole group, so the code alone must not suffice)._
5. Thread mapping: add a provider-specific mapping table (thread → task run); fan the run-keyed lookups in the tasks product out across provider mappings, and stamp `"provider": "<name>"` into serialized thread contexts so `thread_handler_from_context` can dispatch. _Telegram: `TelegramChatTaskMapping` (one row per originating message); fan-outs live in `slack_relay/activities.py`, `facade/api.py` (relay gate), and `living_artifacts.py` (artifacts refused — no delivery adapter)._
6. Temporal: new workflow + activities with provider-specific registered names; reuse the workflow's structure, not its registrations. _Telegram: `posthog/temporal/ai/telegram_app/` (`telegram-app-mention-processing`), registered on `TASKS_TASK_QUEUE`._
7. Cross-product access goes through `facade/api.py` — extend the facade, don't import product internals from outside.

## Telegram v1 scope and setup

Deliberate scope cuts, matching the minimal loop: no inline keyboards or interactivity (unresolvable repo cascades get an ask-for-explicit-repo reply instead of a picker), no untagged follow-ups (one task per originating message), terminal-updates-only output (progress and status-stream handler methods are no-ops), and plain-text relay (no MarkdownV2 escaping — a mis-escaped entity drops the whole message).

Operational setup: create the bot with BotFather, provision `TELEGRAM_APP_BOT_TOKEN` and `TELEGRAM_APP_WEBHOOK_SECRET` identically in both Cloud regions (Telegram delivers all updates to one URL; the receiving region proxies to the owning one via the claims probe), then run `python manage.py setup_telegram_webhook` (use `--url` for an ngrok tunnel in dev). BotFather group privacy mode can stay ON — mentions and replies to the bot are still delivered, which is the entire group surface. The mention path is additionally gated by the `telegram-app` feature flag.

## Splitting / deploy sequencing

This package landed as one PR in four commits (claims receiver, provider seam, thread handler, claims sender flip + docs). If the sender-flip commit is ever split out or reverted independently: the receiver dual-accepts legacy Slack headers indefinitely, so any deploy order is safe; the sender flip only requires the receiver commit to be live in both US and EU. During a normal same-PR rollout, a region that deploys first probes the other region's not-yet-existing `/chat/slack/...` route, the probe returns `None`, and the existing optimistic-proxy fallback applies — the same outcome as any transient probe failure.
