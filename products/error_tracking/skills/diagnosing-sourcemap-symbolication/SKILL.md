---
name: diagnosing-sourcemap-symbolication
description: >
  Help users debug their own PostHog Error Tracking source map and symbol set setup from inside a JavaScript or
  TypeScript app repo. Use when stack traces stay minified after source maps are uploaded, PostHog symbol sets show
  last_used but frames are not readable, chunk IDs do not match, "Token not found" appears, uploaded maps look empty,
  or Vite/Rollup/Webpack/Next/Nuxt sourcemap configuration needs troubleshooting.
---

# Diagnosing sourcemap symbolication

Work through the user's app build and PostHog symbol sets as one pipeline: build config -> generated JS and `.map`
files -> uploaded symbol set -> captured error frame. Most failures become obvious once those four pieces are checked
in order.

## Workflow

### Step 1 - Find how source maps are produced and uploaded

Start in the app repo. Inspect `package.json` scripts and the relevant build config:

- Vite/Rollup: `vite.config.*`, `rollup.config.*`
- Webpack: `webpack.config.*`
- Next.js: `next.config.*`
- Nuxt: `nuxt.config.*`

Check which PostHog package uploads maps (`@posthog/rollup-plugin`, `@posthog/webpack-plugin`,
`@posthog/nextjs-config`, `@posthog/nuxt`, or direct `posthog-cli`) and which directory it processes. Confirm the
configured `projectId`, `host`, release fields, and `deleteAfterUpload` behavior.

For debugging, prefer a build where maps remain on disk:

```ts
sourcemaps: {
  enabled: true,
  deleteAfterUpload: false,
}
```

### Step 2 - Build and inspect local artifacts

Run the same production build that uploads maps. Use the repo's package manager and existing scripts.

Then inspect the generated files:

```bash
python3 scripts/inspect_sourcemaps.py dist/**/*.js dist/**/*.js.map
```

Resolve `scripts/inspect_sourcemaps.py` relative to this skill directory.

Look for:

- JS files contain a `chunkId` marker or `_posthogChunkIds` registration.
- `.map` files are valid JSON.
- `.map` files have non-empty `mappings`.
- `.map` files have plausible `sources`; `sourcesContent` is strongly preferred for source context.
- The files inspected locally are the files deployed to production.

If local maps already have empty `mappings` or empty `sources`, fix the build config before debugging PostHog upload.

### Step 3 - Check symbol sets in PostHog

Open **Project settings > Error tracking > Symbol sets** in PostHog. Find the symbol set whose `ref` matches the frame's
`chunk_id`.

Interpret the row:

- `ref` must match the captured frame `chunk_id`.
- `last_used` updating means PostHog found and loaded that symbol set. It does not guarantee the frame resolved.
- no uploaded file or missing content hash means the upload did not complete.
- a cached failure reason means PostHog could not parse or load the uploaded symbol data.

If the UI offers a source map download, download it and inspect it with the helper:

```bash
python3 scripts/inspect_sourcemaps.py symbolset.bin
```

The downloaded file may be a PostHog symbol-data container, not plain JSON; the helper handles both.

### Step 4 - Compare local, uploaded, and served files

Use the failure location to decide what to compare:

- Local map empty and uploaded map empty: build tool emitted an unusable map.
- Local map valid but uploaded map empty: upload processing selected or packed the wrong data.
- Uploaded map valid but production stack stays minified: compare deployed JS bytes to the JS that was uploaded with the
  map.
- `Token not found`: PostHog loaded the map, but the captured generated line/column did not match any token in that map.
  This usually points to changed JS after upload, wrong line/column capture, or a source-map coverage bug.

### Step 5 - Fix the most likely layer

Common fixes:

- Enable production source maps in the bundler (`build.sourcemap: true` or `hidden` for Vite/Rollup).
- Move the PostHog plugin later so it sees final emitted JS chunks.
- Remove post-build minification, CDN rewrites, asset transforms, or compression steps that change JS after upload.
- Upload after the final build output exists, not before a later build step rewrites it.
- Use the latest PostHog build plugin and `posthog-cli`.
- Re-upload changed assets intentionally when the same `chunk_id` was previously uploaded with different content.

## Reference

For exact commands, API checks, and a failure matrix, read
[sourcemap-debugging.md](./references/sourcemap-debugging.md).
