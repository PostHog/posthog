# Sourcemap debugging reference

Use these commands from the app repo being debugged. Adjust `dist` to the build output directory for the framework.

## Package and config checks

Show relevant package versions:

```bash
pnpm list @posthog/rollup-plugin @posthog/webpack-plugin @posthog/nextjs-config @posthog/nuxt @posthog/cli vite rollup webpack next nuxt --depth 0
```

If the repo uses npm or yarn, use the matching command:

```bash
npm ls @posthog/rollup-plugin @posthog/webpack-plugin @posthog/nextjs-config @posthog/nuxt @posthog/cli vite rollup webpack next nuxt --depth=0
```

Search for PostHog upload config:

```bash
rg -n "posthog|sourcemap|sourceMap|deleteAfterUpload|releaseName|releaseVersion|projectId|envId" .
```

For Vite/Rollup, confirm source map generation is enabled for production builds. Hidden maps are fine for upload:

```ts
build: {
  sourcemap: "hidden",
}
```

## Local artifact checks

List emitted JS and map files:

```bash
find dist -type f \( -name '*.js' -o -name '*.mjs' -o -name '*.cjs' -o -name '*.map' \) -print
```

Inspect local artifacts with the bundled helper:

```bash
python3 scripts/inspect_sourcemaps.py dist/**/*.js dist/**/*.js.map
```

Resolve `scripts/inspect_sourcemaps.py` relative to this skill directory.

Quick `jq` summary for one source map:

```bash
jq '{
  version,
  file,
  chunk_id,
  sourceRoot,
  mappingsLength: (.mappings | length),
  sourcesLength: (.sources | length),
  sourcesContentLength: (.sourcesContent | length),
  namesLength: (.names | length),
  firstSources: .sources[0:5]
}' dist/assets/app.js.map
```

Search for injected PostHog chunk IDs:

```bash
rg -n "chunkId=|_posthogChunkIds|sourceMappingURL" dist
```

Expected local artifact shape:

- JS has a `chunkId` marker or `_posthogChunkIds` registration.
- JS has `sourceMappingURL` only when maps are intentionally public. Hidden source maps may omit it.
- Map has non-empty `mappings`.
- Map has non-empty `sources`.
- `sourcesContent` is present when source context should appear in PostHog.

## CLI and plugin logging

PostHog build plugins call `posthog-cli sourcemap process`. For direct CLI checks, use environment variables:

```bash
POSTHOG_CLI_HOST="$POSTHOG_HOST" \
POSTHOG_CLI_PROJECT_ID="$POSTHOG_PROJECT_ID" \
POSTHOG_CLI_API_KEY="$POSTHOG_PERSONAL_API_KEY" \
RUST_LOG=posthog_cli=debug \
posthog-cli sourcemap process --directory dist --release-name my-app --release-version 0.0.0
```

For plugin-based builds, set `logLevel: "debug"` in the PostHog plugin config when available.

Useful log facts:

- which files were processed.
- which chunk IDs were injected.
- whether uploads were skipped because content already matched.
- whether changed content was skipped because forced overwrite was not enabled.
- whether a source map was missing, empty, or unparsable.

## Symbol set API checks

The PostHog UI is usually enough: **Project settings > Error tracking > Symbol sets**. Use the API when you need a
scriptable check or want to download the uploaded object.

List a symbol set by chunk ID:

```bash
curl -sS \
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
  "$POSTHOG_HOST/api/projects/$POSTHOG_PROJECT_ID/error_tracking/symbol_sets/?ref=$CHUNK_ID" \
  | jq
```

Download uploaded symbol data:

```bash
curl -sS \
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
  "$POSTHOG_HOST/api/projects/$POSTHOG_PROJECT_ID/error_tracking/symbol_sets/$SYMBOL_SET_ID/download/" \
  | jq -r .url
```

Inspect the downloaded file:

```bash
python3 scripts/inspect_sourcemaps.py symbolset.bin
```

Symbol set fields to check:

- `ref`: should equal the captured frame `chunk_id`.
- `storage_ptr`: empty means there is no uploaded object.
- `content_hash`: empty often means pending or incomplete upload.
- `last_used`: updated when PostHog loads the symbol set, not when symbolication succeeds.
- `failure_reason`: cached parse/load failure if present.
- `release`: useful for grouping, but JavaScript frame lookup primarily needs the chunk ID.

## Captured frame checks

From an affected PostHog error event, collect one minified application frame:

- `filename`
- `line` or `lineno`
- `column` or `colno`
- `function`
- `chunk_id`
- any `resolve_failure`, especially `Token not found`

The frame `filename` should match the deployed JS URL. The `chunk_id` should match the symbol set `ref`. The generated
line and column should point into the same JS file that was uploaded with the map.

## Failure matrix

| Evidence                                | Likely cause                                                            | Next check                                                            |
| --------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------- |
| No `chunk_id` on frames                 | Chunk ID injection missing or SDK frame parser did not map the filename | Inspect deployed JS and raw frame filenames.                          |
| Symbol set row missing                  | Upload went to another PostHog project/host or skipped this asset       | Compare plugin `projectId`, `host`, and chunk ID.                     |
| Symbol set has no uploaded object       | Upload did not finish                                                   | Check build logs and API response.                                    |
| Local map has empty `mappings`          | Build chain emitted unusable source map                                 | Check bundler source map settings and plugins.                        |
| Local map valid, uploaded map empty     | CLI/plugin processing bug or wrong file selected during upload          | Compare helper output before and after upload.                        |
| Uploaded map valid, deployed JS differs | Deployment/CDN/post-build transform changed JS after upload             | Compare deployed JS bytes to local build output.                      |
| `Token not found`                       | Frame line/column has no token in the uploaded map                      | Verify generated line/column, deployed JS identity, and map coverage. |
| Resolved names but no context           | `sourcesContent` missing or source path unavailable                     | Check `sourcesContent` and source paths in the map.                   |
