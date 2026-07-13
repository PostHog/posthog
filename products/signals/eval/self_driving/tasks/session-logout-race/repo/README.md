# Acme Portal

Customer-facing account portal. Deliberately framework-free: a small
module-level session store, a fetch-based API client, and DOM-rendering UI
modules.

## Running

```bash
npm install
npm start
# static server on http://localhost:4800
```

## Layout

- `src/state/session.js` - session store (login, logout, refresh); single source of truth for the signed-in user
- `src/api/client.js` - fetch wrapper + auth token handling
- `src/analytics.js` - PostHog capture (plain HTTP, no SDK)
- `src/ui/header.js` - account header (name, avatar, log out button)
- `src/ui/app.js` - boot: initial refresh, periodic session refresh, render

The session store keeps the current user fresh by re-fetching `/api/me` on
boot and every 60 seconds, so plan changes and renames show up without a
reload.
