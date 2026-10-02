# Club Hoguin

A small multiplayer room where hedgehogs hang out while their agents work.
People join from the web, from an iframe embed, or from a Claude Code mod.

## What is in the room

Every object in the room is a PostHog product joke that people can poke:

- **Feature flag lever** turns the lights off and on for everyone.
- **Replay cinema** shows what is playing.
- **Max's desk** tells a joke.
- **Bug jar** catches an error and assigns it to you.
- **Doors A and B** run an A/B test that does not reach significance for a while.
- **Ship it button** counts deploys.

Chat uses only the preset phrases in `src/content.ts`, and the server gives each hedgehog a generated name.
Nobody can type free text, so the room needs no moderation queue.

## Run it locally

```bash
pnpm install
cd products/games/services/club-hoguin
pnpm start
```

Then open <http://localhost:8010>.
Add `?embed=1` to the URL for the embed layout, which drops the header and help text:

```html
<iframe src="http://localhost:8010/?embed=1" width="720" height="520"></iframe>
```

| Variable                  | Default                    | What it does                                 |
| ------------------------- | -------------------------- | -------------------------------------------- |
| `PORT`                    | `8010`                     | The port the server listens on               |
| `HOST`                    | `0.0.0.0`                  | The address the server binds to              |
| `POSTHOG_PROJECT_API_KEY` | not set                    | Sends usage events to PostHog when it is set |
| `POSTHOG_HOST`            | `https://us.i.posthog.com` | The PostHog ingestion host                   |

## The Claude Code mod

The mod in `mod/` needs Claude Code 2.1.287 or later.
Load it for one session with:

```bash
CLUB_HOGUIN_URL=http://localhost:8010 claude --plugin-dir products/games/services/club-hoguin/mod
```

- `/hoguin` opens or closes the club in a pane.
- When Claude works for more than 10 seconds, the pane opens by itself, and it closes when Claude is done.
  `/hoguin auto off` turns this off.
- In the pane, `w` `a` `s` `d` walk, `e` pokes the closest object, and `1` to `9` send a phrase.

The mod sends only "joined", moves, phrases, pokes, and "left" to the server.
It never sends the prompt, the transcript, or anything about the task.

Run the mod checks with `pnpm test:mod`.
The checks need the `claude` CLI, so CI does not run them.

## How it works

The server is one Node process with no runtime dependencies other than the hedgehog sprites from `@posthog/hedgehog-mode`.
It keeps the room in memory, moves each hedgehog one tile per tick along a breadth-first path, and removes a hedgehog after 20 seconds without a request.
Clients poll `GET /api/state`, because a Claude Code mod can make HTTP requests but cannot open a socket.

| Endpoint          | Body            | What it does                                  |
| ----------------- | --------------- | --------------------------------------------- |
| `GET /api/world`  |                 | The map, the objects, and the phrases         |
| `POST /api/join`  | `{ client }`    | Joins the room and returns a token            |
| `GET /api/state`  |                 | The hedgehogs, the feed, and the object state |
| `POST /api/move`  | `{ x, y }`      | Walks to a tile                               |
| `POST /api/say`   | `{ phraseId }`  | Says a preset phrase                          |
| `POST /api/poke`  | `{ objectId? }` | Pokes an object in reach, or the closest one  |
| `POST /api/leave` |                 | Leaves the room                               |

Send the token from `/api/join` in the `x-hoguin-token` header.

The server captures these events when `POSTHOG_PROJECT_API_KEY` is set, with no person profiles:
`club hoguin joined`, `club hoguin phrase said`, `club hoguin object poked`, and `club hoguin left` (with `duration_seconds`).
