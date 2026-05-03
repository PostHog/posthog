---
name: diagnosing-sourcemap-symbolication
description: >
  Help users debug PostHog Error Tracking source map and symbol set setup. Works either from inside a JavaScript or
  TypeScript app repo, or with PostHog MCP access alone when the repo is unavailable. Use when stack traces stay
  minified after source maps are uploaded, PostHog symbol sets show last_used but frames are not readable, chunk IDs
  do not match, "Token not found" appears, uploaded maps look empty, or Vite/Rollup/Webpack/Next/Nuxt sourcemap
  configuration needs troubleshooting.
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
python3 <skill_dir>/scripts/inspect_sourcemaps.py dist
```

Resolve `scripts/inspect_sourcemaps.py` relative to this skill directory. The helper accepts individual JS/map files,
PostHog symbol-data files, directories, and glob patterns.

Look for:

- JS files contain a `chunkId` marker or `_posthogChunkIds` registration.
- `.map` files are valid JSON.
- `.map` files have non-empty `mappings`.
- `.map` files have plausible `sources`; `sourcesContent` is strongly preferred for source context.
- The files inspected locally are the files deployed to production.

If local maps already have empty `mappings` or empty `sources`, fix the build config before debugging PostHog upload.

### Step 2.5 - Smoking gun: empty `mappings`

If `inspect_sourcemaps.py` reports `"empty_mappings": true` on a `.map` file (and `sources_length: 0`,
`names_length: 0`), the bundler emitted a structurally valid but data-less source map. This is the single
strongest signal that the bug is upstream of PostHog upload — the CLI faithfully uploads whatever is on disk.

For Vite/Rollup this can happen when `config.build.sourcemap` was unset and a Vite-internal plugin
(`vite:css-post`, `vite:build-import-analysis`) skipped sourcemap generation during `renderChunk` because it reads
`config.build.sourcemap` directly rather than the Rollup output option. This is reproducible in Vite 7/Rollup builds
with CSS/IIFE/import-analysis paths. Check the build log for:

```text
[plugin vite:css-post] Sourcemap is likely to be incorrect: a plugin (vite:css-post) was used to transform files,
but didn't generate a sourcemap for the transformation
```

Workaround: set `build.sourcemap: 'hidden'` (or `true`) in `vite.config.*`. Hidden maps still get uploaded but are
not advertised via `sourceMappingURL` in the served JS.

For other bundlers, the same class of bug shows up when a transform/plugin returns a sourcemap object with empty
fields instead of `null`. Inspect the local artifact first, before suspecting upload or processing.

### Step 3 - Check symbol sets in PostHog

Look up the symbol set whose `ref` matches the captured frame's `chunk_id`.

If MCP access to the project is available, prefer the dedicated tools:

- `posthog:error-tracking-symbol-sets-list` with `ref=<chunk_id>` returns the matching row.
- `posthog:error-tracking-symbol-sets-retrieve` with the ID returns the same shape (and confirms permissions).
- `posthog:error-tracking-symbol-sets-download-retrieve` returns a one-hour presigned URL pointing at the uploaded
  symbol-data file. Download it immediately; do not echo the URL back unless the user explicitly asks.

If MCP access is not available, the same data is in **Project settings > Error tracking > Symbol sets** in the
PostHog UI.

Interpret the row:

- `ref` must match the captured frame `chunk_id`.
- `last_used` updating means PostHog found and loaded that symbol set. It does not guarantee the frame resolved.
- `has_uploaded_file: false` means the upload did not complete.
- A non-null `failure_reason` means PostHog could not parse or load the uploaded symbol data.

Once downloaded, inspect the file with the helper:

```bash
python3 <skill_dir>/scripts/inspect_sourcemaps.py symbolset.bin
```

The downloaded file is a PostHog symbol-data container (compressed, with embedded minified source plus source map),
not plain JSON; the helper handles both. For compressed v2 containers, install Python `zstandard` in the active
environment if the helper reports it missing.

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

For exact commands, MCP tool usage, and a failure matrix, read
[sourcemap-debugging.md](./references/sourcemap-debugging.md).
