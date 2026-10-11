# Terminal game relay

A standalone WebSocket service for Doom in the PostHog terminal. One browser still
runs `doom -server -deathmatch`; the others use `doom -connect <room>`. The service
forwards packets between that host and its players. It runs no Doom process,
opens no outbound connections, and accepts no destination URLs or IP addresses.

## Deploy on a VPS

Point a hostname at the VPS, install Docker Compose, and copy this directory there.
Allow incoming TCP 80 and 443. The relay's port 8080 stays inside the Docker network.
Caddy obtains and renews the TLS certificate.

Create a `.env` file with mode 0600 (keep it out of Git):

```dotenv
RELAY_HOST=relay.example.com
RELAY_ALLOWED_ORIGINS=https://us.posthog.com
RELAY_SIGNING_KEYS=<a-new-random-key-of-at-least-32-characters>
```

Generate the signing key with `openssl rand -hex 32`. Use a separate key per
environment. For rotation, put the new key first and the previous key second,
comma-separated; tokens are minted with the first key and verified against both.
Restart the service after changing keys. Removing an old key and restarting also
disconnects clients using it. Never give signing keys to players.

```sh
docker compose up -d --build
docker compose exec relay python relay.py token --scope playtest --ttl 3600
```

The second command prints a temporary access token. Give participants tokens for
the same scope; scopes isolate rooms from one another. A token grants hosting and
joining within that scope until expiry, up to two hours. Active connections also
expire, so choose a lifetime long enough for the match. Issuance is operator-only;
there is no public token endpoint or integration with PostHog authentication yet.

Set `TERMINAL_NETPLAY_RELAY_URL=wss://relay.example.com/netplay` on the PostHog
deployment and reload the page. This allows that exact WebSocket endpoint through
the browser's Content Security Policy. It does not provision a relay or credentials.
The default is blank, so no extra endpoint is allowed until configured.

## Configure each terminal

Run `ph netplay configure --json -`, paste the following JSON with a temporary
token, press Enter, then Ctrl+D. Input to this command is not a shell history entry,
but is visible on screen; use a private terminal.

```json
{ "url": "wss://relay.example.com/netplay", "token": "temporary-access-token" }
```

Alternatively, use `ph netplay configure --json @/tmp/relay.json` and remove the
temporary file afterward. Do not save credentials under `/posthog`.

`ph netplay status` reports the mode without printing credentials.
`ph netplay clear` restores direct WebRTC for the next game. Configuration lasts
only for this terminal session; changing it does not interrupt the current game.
Both players must configure the same relay before launching Doom. One hosts and
shares its room code, then presses Space when everyone joins. Keep the host tab
open; stopping that terminal or closing the tab disconnects its players.

## Limits and tradeoffs

- Four players per room, two rooms per token scope, 32 rooms and 128 connections
  per process. Disconnected player slots are not reused; start a new room.
- Authentication within five seconds, a bounded global handshake rate, explicit
  browser Origin allowlist, and tokens sent in the first frame rather than URLs.
- Packets at most 1501 bytes, 128 packets/second and 64 KiB/second per connection
  with bounded bursts. Slow recipients time out rather than accumulate queues.
- The host cannot send outside its room; players can only send to their host.
  These limits constrain abuse but do not make the public endpoint immune to DoS.
- Rooms live in one process. Do not run multiple workers or replicas behind a
  load balancer. Restarting the service ends matches. No game traffic is stored.
- WebSockets use TCP: packet loss can delay subsequent packets. This is a
  connectivity fallback for networks that block peer-to-peer traffic.

## Local checks

From the PostHog repository root:

```sh
.codex/with-flox python -m unittest discover -s services/terminal-relay -p 'test_*.py'
.codex/with-flox hogli test frontend/src/scenes/terminal/terminalRelay.test.ts
```

For local browser testing, run the service on port 8080 with
`RELAY_ALLOWED_ORIGINS=http://localhost:8010` and a local-only signing key.
Set PostHog's `TERMINAL_NETPLAY_RELAY_URL=ws://localhost:8080/netplay` before starting
the dev stack. Plain WebSocket URLs are accepted only for loopback development;
production needs `wss://`.
