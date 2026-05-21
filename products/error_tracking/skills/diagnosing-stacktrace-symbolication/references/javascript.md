# JavaScript / TypeScript symbolication reference

Companion to [../SKILL.md](../SKILL.md) for JavaScript and TypeScript web apps. Covers `@posthog/rollup-plugin`,
`@posthog/webpack-plugin`, `@posthog/nextjs-config`, `@posthog/nuxt`, and direct `posthog-cli sourcemap` invocations.

## Step 1 — Build config and packages

Show relevant package versions, using the package manager the repo uses:

```bash
# pnpm
pnpm list @posthog/rollup-plugin @posthog/webpack-plugin @posthog/nextjs-config @posthog/nuxt @posthog/cli vite rollup webpack next nuxt --depth 8

# npm
npm ls @posthog/rollup-plugin @posthog/webpack-plugin @posthog/nextjs-config @posthog/nuxt @posthog/cli vite rollup webpack next nuxt

# yarn (classic)
yarn list --pattern '@posthog/* vite rollup webpack next nuxt' --depth=0

# bun
bun pm ls | grep -E '@posthog/|^├── (vite|rollup|webpack|next|nuxt)@'
```

Use non-zero depth — `@posthog/cli` and Rollup are often transitive dependencies of the build plugin or framework.

Inspect the relevant config files:

- Vite/Rollup: `vite.config.*`, `rollup.config.*`
- Webpack: `webpack.config.*`
- Next.js: `next.config.*`
- Nuxt: `nuxt.config.*`

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

## Step 2 — Local artifacts

List emitted JS and map files:

```bash
find dist -type f \( -name '*.js' -o -name '*.mjs' -o -name '*.cjs' -o -name '*.map' \) -print
```

Inspect with the bundled helper. This is the canonical check — it summarizes JS chunk-id markers and source map
shape (`mappings_length`, `sources_length`, `sources_content_length`, `names_length`):

```bash
python3 <skill_dir>/scripts/inspect_sourcemaps.py dist
```

Resolve `scripts/inspect_sourcemaps.py` relative to the skill directory. It accepts files, directories, and globs.

If the helper isn't accessible (CI runner without Python, etc.), a `jq` one-liner gives a coarse summary of one
source map:

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

For a quick sanity grep on whether chunk IDs landed in the JS:

```bash
rg -n "chunkId=|_posthogChunkIds|sourceMappingURL" dist
```

Expected local artifact shape:

- JS has a `chunkId` marker and `_posthogChunkIds` registration.
- JS has `sourceMappingURL` only when maps are intentionally public. Hidden source maps may omit it.
- Map has non-empty `mappings`.
- Map has non-empty `sources`.
- `sourcesContent` is present when source context should appear in PostHog.

## Smoking gun — empty `mappings`

If `inspect_sourcemaps.py` reports `"empty_mappings": true` on a `.map` file (and `sources_length: 0`,
`names_length: 0`), the bundler emitted a structurally valid but data-less source map. This is the single strongest
signal that the bug is upstream of PostHog upload — the CLI faithfully uploads whatever is on disk.

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

## Inspecting an extracted symbol set

After [Step 3](../SKILL.md#step-3---check-symbol-sets-in-posthog) extracts a JS symbol set with
`posthog-cli symbol-sets extract`, run the helper on the resulting directory:

```bash
python3 <skill_dir>/scripts/inspect_sourcemaps.py ./extracted
```

The helper operates on plain `.js` / `.map` files. If you point it at a raw `.bin` container by mistake, it prints
a redirect error pointing back at `posthog-cli symbol-sets extract`.

## CLI and plugin logging

PostHog build plugins call `posthog-cli sourcemap process`. For direct CLI checks, use environment variables:

```bash
POSTHOG_CLI_HOST="$POSTHOG_HOST" \
POSTHOG_CLI_PROJECT_ID="$POSTHOG_PROJECT_ID" \
POSTHOG_CLI_API_KEY="$POSTHOG_PERSONAL_API_KEY" \
RUST_LOG=posthog_cli=debug \
posthog-cli sourcemap process --directory dist --release-name my-app --release-version 0.0.0
```

For plugin-based builds, set `logLevel: "debug"` inside the same `posthog({ ... })` options object that holds
`personalApiKey`/`projectId` in `vite.config.*` / `webpack.config.*` / framework wrapper.

Useful log facts:

- which files were processed.
- which chunk IDs were injected.
- whether uploads were skipped because content already matched.
- whether changed content was skipped because forced overwrite was not enabled.
- whether a source map was missing, empty, or unparsable.

## JS-specific fixes

In addition to the platform-neutral fixes in [SKILL.md Step 5](../SKILL.md#step-5---fix-the-most-likely-layer):

- Enable production source maps in the bundler (`build.sourcemap: true` or `'hidden'` for Vite/Rollup).
- Move the PostHog plugin later in the plugin order so it sees final emitted JS chunks.
- Remove post-build minification, CDN rewrites, asset transforms, or compression steps that change JS after upload.

## JS-specific failure rows

Add these to the cross-platform matrix in [SKILL.md](../SKILL.md#failure-matrix-cross-platform):

| Evidence                            | Likely cause                                                                                        | Next check                                          |
| ----------------------------------- | --------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Local map has empty `mappings`      | Build chain emitted unusable source map (often Vite `build.sourcemap` unset, see smoking gun above) | Check bundler source map settings and plugin order. |
| Local map valid, uploaded map empty | CLI/plugin processing bug or wrong file selected during upload                                      | Compare helper output before and after upload.      |
| Resolved names but no context       | `sourcesContent` missing or source path unavailable                                                 | Check `sourcesContent` and source paths in the map. |
