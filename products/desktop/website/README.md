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

Replace `screenshot.png` with a fresh capture of the running app (any aspect ratio; the page scales it).
If the new image's dimensions differ, update the `width`/`height` on the `<img>` in `index.html` to match, so the layout doesn't jump while it loads.
