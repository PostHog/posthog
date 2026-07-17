# posthogondesktop.com

The landing page for the PostHog desktop fork.
A single static `index.html` with two local assets (`screenshot.png`, `icon.png`) — no build step, no dependencies.

## Deploying to Cloudflare Pages

Point a Cloudflare Pages project at this repo's `desktop` branch (on the fork) with:

- **Build command:** none (leave empty)
- **Build output directory:** `products/desktop/website`

Then add `posthogondesktop.com` as a custom domain in the Pages project.

## Download buttons

The buttons link to GitHub's "latest release" redirect on the fork:

- `https://github.com/mariusandra/posthog/releases/latest/download/PostHog-Desktop-macos-arm64.dmg`
- `https://github.com/mariusandra/posthog/releases/latest/download/PostHog-Desktop-windows-x64-setup.exe`

`desktop-release.yml` publishes each release under exactly these version-less asset names, so the links always resolve to the newest build without touching this page.

## Updating the screenshot

The hero is theme-aware: `screenshot1.png` (light) shows in light mode, `screenshot2.png` (dark) in dark mode, via a `<picture>` element that follows the viewer's `prefers-color-scheme`.
Both ship with their own window chrome and a baked shadow on a transparent margin, so the page frames them with no border or card.
Replace either with a fresh capture (any aspect ratio; the page scales it). Keep the two at the same dimensions, and if they differ from the current 1529×995, update the `width`/`height` on the `<img>` in `index.html` so the layout doesn't jump while it loads.
