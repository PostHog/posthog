# Club Hoguin

A small multiplayer town where hedgehogs hang out while their agents work.
People join from the web, from an iframe embed, or from a Claude Code mod.

## What is in Hog Town

Hog Town is a snowy town square drawn in 3D with `three`, and the hedgehogs are the sprites from `@posthog/hedgehog-mode`.
Every building is a PostHog product joke that a hedgehog can use:

- **Feature flag lighthouse**: the lever flips night-mode for everyone.
- **Replay cinema**: starts a session replay on the big screen.
- **Experiments lab**: walk through door A or door B to vote. The scoreboard shows when the result is significant.
- **Max's desk**: Max tells a joke.
- **Bug jar**: catches a bug and puts it in the jar.
- **Ship it button**: launches the rocket and counts the deploy.

Chat uses only the preset phrases and emotes in `src/content.ts`, and the server gives each hedgehog a generated name.
Nobody can type free text, so the town needs no moderation queue.

## Run it locally

```bash
pnpm install
cd products/games/services/club-hoguin
pnpm start
```

Then open <http://localhost:8642>.
Add `?embed=1` to the URL for the embed layout, which fills the frame and drops the page header:

```html
<iframe src="http://localhost:8642/?embed=1" width="720" height="520"></iframe>
```

| Variable                      | Default                    | What it does                                 |
| ----------------------------- | -------------------------- | -------------------------------------------- |
| `PORT`                        | `8642`                     | The port the server listens on               |
| `HOST`                        | `0.0.0.0`                  | The address the server binds to              |
| `TRUSTED_PROXY_HOPS`          | `0`                        | The number of proxies in front of the server |
| `CLUB_HOGUIN_POSTHOG_API_KEY` | not set                    | Sends usage events to PostHog when it is set |
| `CLUB_HOGUIN_POSTHOG_HOST`    | `https://us.i.posthog.com` | The PostHog ingestion host                   |

The server reads the files in `web/` when it starts, so restart it after you change one.

## Run it in a container

Build the image from the repo root, because pnpm needs the workspace lockfile:

```bash
docker build -f products/games/services/club-hoguin/Dockerfile -t posthog-club-hoguin .
docker run -p 8642:8642 posthog-club-hoguin
```

The container runs as the `node` user, answers `GET /healthz`, and stops within a few seconds of `SIGTERM`.
The town lives in the memory of one process, so run one container, and expect a restart to empty the town.

## How to play

- Click the snow to walk there, or use the arrow keys.
- Click a building to walk to it and use it, or stand next to it and press `E`.
- Press `1` to `9` to say a phrase, or open **Say**. The round buttons send an emote.
- **Change hog** picks another hedgehog.

## The Claude Code mod

The mod in `mod/` needs Claude Code 2.1.287 or later.
Load it for one session with:

```bash
CLUB_HOGUIN_URL=http://localhost:8642 claude --plugin-dir products/games/services/club-hoguin/mod
```

- `/hoguin` opens or closes the club in a pane. In a terminal that can draw pictures (Ghostty, kitty, iTerm2, WezTerm) the pane shows a picture of the town. `/hoguin map` switches to a map of text characters, and `/hoguin picture` back.
- `/hoguin web` opens the club in your browser.
- When Claude works for more than 10 seconds, the pane opens by itself, and it closes when Claude is done.
  `/hoguin auto off` turns this off.
- In the pane, `w` `a` `s` `d` walk, `e` uses the closest object, and `1` to `9` send a phrase.

The mod sends only "joined", moves, phrases, uses, and "left" to the server.
It never sends the prompt, the transcript, or anything about the task.

The mod finds the club through the PostHog MCP server when one is connected: it calls the `club-hoguin-open` tool, which returns the address the server is configured with (`CLUB_HOGUIN_URL` in `services/mcp`).
Claude Code asks once for permission to let the mod call that tool.
`CLUB_HOGUIN_URL` in the environment of `claude` wins, and without either the mod uses `http://localhost:8642`.

Run the mod checks with `pnpm test:mod`.
The checks need the `claude` CLI, so CI does not run them.

## How it works

The server is one Node process that keeps the town in memory.
A hedgehog walks at one speed along a path that goes around the pond, the campfire, and the objects.
The server moves every hedgehog 20 times a second and removes a hedgehog after 20 seconds without a request.

Every change in the town is an event with a number: a hedgehog joins, leaves, starts a walk, says a phrase, sends an emote, or uses an object.
A client takes one snapshot and then only the events after the last number it saw, so the traffic grows with what people do, not with the number of players.
The web client reads the events from `GET /api/stream`, a server-sent event stream.
The Claude Code mod polls `GET /api/events?since=N`, because a mod cannot hold a connection open.
A walk event carries the path and the start time, and every client works out where the hedgehog is from those, with the same calculation as the server (`src/walk.ts`, `web/walk.js`, `mod/hooks/walk.js`).
The pane picture comes from `GET /api/frame.png`, which the server paints from the sprite sheet without an image library (`src/frame.ts`, `src/png.ts`).

One network address can have 10 hedgehogs in the town at a time, so one client cannot take every place.
One address can send 300 requests a second. After that the server answers `429` until the address slows down.
Behind a proxy, every request comes from the address of the proxy.
Set `TRUSTED_PROXY_HOPS` to the number of proxies, and the server reads the client address from `x-forwarded-for`.

| Endpoint             | Body                         | What it does                                                               |
| -------------------- | ---------------------------- | -------------------------------------------------------------------------- |
| `GET /api/world`     |                              | The size of the town, the objects, the phrases, the map                    |
| `POST /api/join`     | `{ client, skin? }`          | Joins the town and returns a token                                         |
| `GET /api/state`     |                              | A snapshot: the hedgehogs, the town log, the objects, and the event number |
| `GET /api/events`    | `?since=N`                   | The events after N, or a snapshot when they are gone                       |
| `GET /api/stream`    | `?token=…&since=N`           | The same, as a server-sent event stream                                    |
| `GET /api/frame.png` |                              | The town as a picture (`.b64` for the base64 text)                         |
| `POST /api/move`     | `{ x, y }` or `{ objectId }` | Walks to a point, or walks to an object and uses it                        |
| `POST /api/say`      | `{ phraseId }`               | Says a preset phrase                                                       |
| `POST /api/emote`    | `{ emoteId }`                | Shows a preset emote                                                       |
| `POST /api/poke`     | `{ objectId? }`              | Uses an object in reach, or the closest one                                |
| `POST /api/leave`    |                              | Leaves the town                                                            |

Send the token from `/api/join` in the `x-hoguin-token` header.

The server captures these events when `CLUB_HOGUIN_POSTHOG_API_KEY` is set, with no person profiles:
`club hoguin joined`, `club hoguin phrase said`, `club hoguin emote sent`, `club hoguin object poked`, and `club hoguin left` (with `duration_seconds`).
