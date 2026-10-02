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

| Variable                  | Default                    | What it does                                 |
| ------------------------- | -------------------------- | -------------------------------------------- |
| `PORT`                    | `8642`                     | The port the server listens on               |
| `HOST`                    | `0.0.0.0`                  | The address the server binds to              |
| `TRUSTED_PROXY_HOPS`      | `0`                        | The number of proxies in front of the server |
| `POSTHOG_PROJECT_API_KEY` | not set                    | Sends usage events to PostHog when it is set |
| `POSTHOG_HOST`            | `https://us.i.posthog.com` | The PostHog ingestion host                   |

The server reads the files in `web/` when it starts, so restart it after you change one.

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

- `/hoguin` opens or closes the club in a pane. The pane draws the town as a map of text characters.
- When Claude works for more than 10 seconds, the pane opens by itself, and it closes when Claude is done.
  `/hoguin auto off` turns this off.
- In the pane, `w` `a` `s` `d` walk, `e` uses the closest object, and `1` to `9` send a phrase.

The mod sends only "joined", moves, phrases, uses, and "left" to the server.
It never sends the prompt, the transcript, or anything about the task.

Run the mod checks with `pnpm test:mod`.
The checks need the `claude` CLI, so CI does not run them.

## How it works

The server is one Node process that keeps the town in memory.
A hedgehog walks at one speed along a path that goes around the pond, the campfire, and the objects.
The server moves every hedgehog 20 times a second and removes a hedgehog after 20 seconds without a request.

Clients poll `GET /api/state`, because a Claude Code mod can make HTTP requests but cannot hold a connection open.
Each hedgehog in the state has its position and the rest of its path, so the web client moves it smoothly between polls.

One network address can have 10 hedgehogs in the town at a time, so one client cannot take every place.
Behind a proxy, every request comes from the address of the proxy.
Set `TRUSTED_PROXY_HOPS` to the number of proxies, and the server reads the client address from `x-forwarded-for`.

| Endpoint          | Body                         | What it does                                            |
| ----------------- | ---------------------------- | ------------------------------------------------------- |
| `GET /api/world`  |                              | The size of the town, the objects, the phrases, the map |
| `POST /api/join`  | `{ client, skin? }`          | Joins the town and returns a token                      |
| `GET /api/state`  |                              | The hedgehogs, the town log, and the object state       |
| `POST /api/move`  | `{ x, y }` or `{ objectId }` | Walks to a point, or walks to an object and uses it     |
| `POST /api/say`   | `{ phraseId }`               | Says a preset phrase                                    |
| `POST /api/emote` | `{ emoteId }`                | Shows a preset emote                                    |
| `POST /api/poke`  | `{ objectId? }`              | Uses an object in reach, or the closest one             |
| `POST /api/leave` |                              | Leaves the town                                         |

Send the token from `/api/join` in the `x-hoguin-token` header.

The server captures these events when `POSTHOG_PROJECT_API_KEY` is set, with no person profiles:
`club hoguin joined`, `club hoguin phrase said`, `club hoguin emote sent`, `club hoguin object poked`, and `club hoguin left` (with `duration_seconds`).
