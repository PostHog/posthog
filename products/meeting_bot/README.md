# Meeting bot

A bot that joins a Google Meet call as a participant, keeps a rolling buffer of what has been said, and
when it hears its trigger phrase treats the rest of the sentence as a question: it queries PostHog, speaks
the answer out loud, and displays it on its video feed.

> Status: demo. It runs end to end, but it is not deployed anywhere and has no Django app, no frontend
> scene, and no tests beyond the trigger-phrase logic.

## How it works

[Recall.ai](https://www.recall.ai) supplies the bot itself. Two of its features carry the whole loop:

- **Real-time transcription.** The bot is created with a `realtime_endpoints` websocket pointed at this
  service, so finalized and partial utterances arrive as they are spoken. That is where the trigger phrase
  is detected and where the rolling buffer comes from.
- **Output media.** The bot's camera is pointed at a webpage this service serves (`public/stage.html`).
  Recall streams that page's audio and video into the call, which means the page _is_ the bot: an
  `<audio>` element on it is the bot's voice, and the rendered page is the bot's video feed. One mechanism
  covers both "speak the answer" and "show it on screen".

```text
Google Meet
   │  speech
   ▼
Recall bot ──── transcript websocket ────▶ meeting-bot
   ▲                                          │ trigger phrase detected
   │                                          ▼
   │                                     Claude + PostHog MCP  (finds the data)
   │                                          │
   │                                          ▼
   │                                     ElevenLabs  (turns the answer into speech)
   │                                          │
   └──── camera + mic = stage.html ◀──────────┘  answer pushed over websocket
```

Answering is deliberately one question at a time, and triggers are ignored while the bot is talking so it
cannot re-trigger on its own answer echoing out of someone's speakers.

## Files

| Path                | What it does                                                               |
| ------------------- | -------------------------------------------------------------------------- |
| `src/server.ts`     | HTTP + both websockets, and the trigger-to-answer orchestration            |
| `src/transcript.ts` | Rolling buffer and fuzzy trigger-phrase detection                          |
| `src/recall.ts`     | Recall.ai bot creation and transcript frame parsing                        |
| `src/agent.ts`      | Claude with the PostHog MCP server attached, returning a structured answer |
| `src/speech.ts`     | ElevenLabs text to speech, held in memory for the stage page to fetch      |
| `src/stage.ts`      | Websocket fan-out to the stage page                                        |
| `public/stage.html` | The bot's video feed and its audio element                                 |

## Setup

You need a Recall.ai API key, an Anthropic API key, a PostHog personal API key with the
[MCP server preset](https://app.posthog.com/settings/user-api-keys?preset=mcp_server), and an ElevenLabs
API key.

**Recall renders the stage page and opens the transcript websocket from its own infrastructure, so both
URLs have to be reachable on the public internet.** For local development, put a tunnel in front of the
service and set `PUBLIC_BASE_URL` to the tunnel's HTTPS origin.

```bash
export PUBLIC_BASE_URL=https://your-tunnel.example.dev
export SHARED_SECRET=$(openssl rand -hex 16)

export RECALL_API_KEY=...
export RECALL_API_BASE=https://us-west-2.recall.ai   # must match your Recall workspace region

export ANTHROPIC_API_KEY=...
export POSTHOG_PERSONAL_API_KEY=phx_...
export ELEVENLABS_API_KEY=...

pnpm --filter @posthog/meeting-bot start
```

Then send the bot into a call:

```bash
pnpm --filter @posthog/meeting-bot join "https://meet.google.com/abc-defg-hij"
```

Or set `MEETING_URL` before starting and it joins on boot. To pull the bot out:
`curl -XPOST localhost:3030/bots/<bot-id>/leave`.

Once it has joined, say:

> "Hey PostHog, what's the DAU for the pricing page this week?"

## Configuration

| Variable                     | Default                       | Notes                                                                                         |
| ---------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------- |
| `PUBLIC_BASE_URL`            | required                      | Public HTTPS origin of this service                                                           |
| `SHARED_SECRET`              | random per run                | Guards the stage page and transcript socket. Set it, or bots from a previous run stop working |
| `PORT`                       | `3030`                        |                                                                                               |
| `RECALL_API_KEY`             | required                      |                                                                                               |
| `RECALL_API_BASE`            | `https://us-west-2.recall.ai` | Recall is region-sharded; there is no global hostname                                         |
| `RECALL_BOT_VARIANT`         | `web_4_core`                  | Larger instance type, which output media needs                                                |
| `RECALL_TRANSCRIPT_PROVIDER` | `recallai_streaming`          | Any streaming provider Recall supports, e.g. `assembly_ai_v3_streaming`                       |
| `BOT_NAME`                   | `PostHog`                     | Name shown in the participant list                                                            |
| `ANTHROPIC_API_KEY`          | required                      |                                                                                               |
| `ANTHROPIC_MODEL`            | `claude-opus-5`               |                                                                                               |
| `ANTHROPIC_REFUSAL_FALLBACK` | `true`                        | Set to `false` if your org does not have the server-side fallback beta                        |
| `POSTHOG_MCP_URL`            | `https://mcp.posthog.com/mcp` |                                                                                               |
| `POSTHOG_PERSONAL_API_KEY`   | required                      | Scopes which project's data the bot can read                                                  |
| `ELEVENLABS_API_KEY`         | required                      |                                                                                               |
| `ELEVENLABS_VOICE_ID`        | `21m00Tcm4TlvDq8ikWAM`        |                                                                                               |
| `ELEVENLABS_MODEL_ID`        | `eleven_flash_v2_5`           | Flash keeps synthesis latency low enough for a live call                                      |
| `TRIGGER_PHRASE`             | `hey posthog`                 | Last word is matched fuzzily; the words before it are the wake word                           |
| `BUFFER_SECONDS`             | `90`                          | How much conversation is passed to the model as context                                       |

## Things to know before demoing

- **Speech to text mangles "PostHog."** It comes back as "post hog", "post hoc", "posthawk" and worse, so
  the brand word is matched by edit distance rather than equality (`src/transcript.ts`). The wake word is
  what prevents the bot from answering every time someone says the product name in conversation.
- **Expect five to fifteen seconds before it starts speaking.** The stage page shows the question and a
  working state as soon as the trigger fires so the feed does not look frozen while Claude queries data.
- **The answer is one round trip, not a conversation.** There is no follow-up handling: each trigger is
  answered independently, with the last 90 seconds of transcript as context.
- **Recall does not transcribe the bot's own audio**, so the bot cannot hear itself directly. It can still
  hear itself through a participant's open microphone, which is why triggers are suppressed during playback.
- **The Recall request body in `src/recall.ts` was written against the published API shape but has not been
  replayed against a live workspace.** The region host, the bot variant and the transcript provider key are
  all environment variables for that reason. If bot creation 400s, that request body is the first place to
  look.

## Possible next steps

- Multi-turn follow-ups, so "and the week before?" works without the trigger phrase.
- Render a real insight instead of a bar chart: the MCP server can return an insight URL, which the stage
  page could screenshot or embed.
- Per-meeting project scoping, so the bot reads the project the meeting is about rather than one fixed
  personal API key.
