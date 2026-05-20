---
name: diagnosing-stacktrace-symbolication
description: >
  Help users debug PostHog Error Tracking stack-trace symbolication for any supported platform — JavaScript/TypeScript
  web, React Native (Hermes), Android (Proguard / R8), or iOS / macOS (dSYM). The PostHog symbol-set lookup flow is
  universal across platforms; build-tool and artifact details live in per-platform references (JavaScript is fleshed
  out, others come as we encounter them). Use when stack frames stay minified or obfuscated after symbols are
  uploaded, PostHog symbol sets show last_used but frames are not readable, chunk IDs or dSYM UUIDs do not match,
  "Token not found" appears, uploaded source maps / dSYMs / Proguard mappings look empty, or bundler /
  symbol-upload configuration needs troubleshooting.
---

# Diagnosing stack-trace symbolication

Symbolication is the cross-platform name for what JavaScript source-map lookup, Hermes function-offset resolution,
Proguard / R8 demangling, and dSYM address-to-line lookup all do — turn a minified or obfuscated frame back into a
readable file, function, and line.

Work through the user's build and PostHog symbol sets as one pipeline: build config -> generated symbol artifacts
(JavaScript source maps, Hermes maps, Proguard mappings, or dSYM bundles) -> uploaded symbol set in PostHog ->
captured error frame. Most failures become obvious once those four pieces are checked in order.

## Platforms

| Platform                    | Symbol-data type | Reference                                   |
| --------------------------- | ---------------- | ------------------------------------------- |
| JavaScript / TypeScript web | source-and-map   | [javascript.md](./references/javascript.md) |
| React Native (Hermes)       | hermes           | _coming soon_                               |
| Android (Proguard / R8)     | proguard         | _coming soon_                               |
| iOS / macOS (dSYM)          | apple-dsym       | _coming soon_                               |

Step 3 of the workflow (symbol-set lookup in PostHog) is identical across platforms — `posthog-cli symbol-sets
extract` handles all four container types. Steps 1, 2, and the platform-specific failure modes live in the
per-platform reference.

## Workflow

### Step 1 - Find how symbol data is produced and uploaded

Look at the app repo's build scripts and PostHog upload config. Confirm which PostHog package handles the upload
(`@posthog/rollup-plugin`, `@posthog/webpack-plugin`, `@posthog/nextjs-config`, `@posthog/nuxt`, or direct
`posthog-cli`) and which directory or asset it processes. See the platform reference for build-tool-specific
config inspection.

For debugging, prefer a build where symbol artifacts remain on disk after upload so you can compare local
artifacts against what PostHog received. JavaScript example with the Vite plugin (the platform reference covers
the equivalent setting for other build tools):

```ts
sourcemaps: {
  enabled: true,
  deleteAfterUpload: false,
}
```

### Step 2 - Build and inspect local artifacts

Run the production build that uploads symbols, then inspect the emitted files locally. The exact files and helper
invocation differ per platform — see the platform reference for the helper command, expected file shape, and common
build-time pitfalls (notably empty-mappings false positives that look like upload bugs but are actually bundler
config issues).

If local artifacts already look wrong, fix the build before debugging the PostHog upload.

### Step 3 - Check symbol sets in PostHog

Look up the symbol set whose `ref` matches the captured frame's `chunk_id` using the dedicated MCP tools — they
handle auth, project scoping, and pagination automatically:

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

The downloaded file is a PostHog symbol-data container (compressed Rust-encoded payload), not plain JSON. Extract
it with `posthog-cli`:

```bash
posthog-cli symbol-sets extract symbolset.bin -o ./extracted
# or, without installing globally:
#   npx @posthog/cli symbol-sets extract symbolset.bin -o ./extracted
#   bunx @posthog/cli symbol-sets extract symbolset.bin -o ./extracted
```

`posthog-cli symbol-sets extract` handles all four symbol-set types (source-and-map, hermes, proguard, dSYM) and
writes the extracted files into the output directory. Once extracted, summarize using the platform reference's
helper.

### Step 4 - Compare local, uploaded, and served files

Use the failure location to decide what to compare:

- Local artifact empty and uploaded artifact empty: build tool emitted unusable symbols.
- Local artifact valid but uploaded artifact empty: upload processing selected or packed the wrong data.
- Uploaded artifact valid but production stack stays minified or obfuscated: compare deployed binary bytes to the
  binary that was uploaded with the symbols.
- `Token not found`: PostHog loaded the symbol data but the captured generated position did not match any token in
  the uploaded artifact. Usually points to a changed binary after upload, wrong line / column capture (JavaScript)
  or wrong frame offset (Hermes / dSYM), or a symbol-coverage bug.

### Step 5 - Fix the most likely layer

Platform-neutral fixes:

- Upload symbols after the final build output exists, not before a later step rewrites it.
- Use the latest PostHog build plugin and `posthog-cli`.
- Re-upload changed assets intentionally when the same `ref` was previously uploaded with different content.
- Remove deployment-time transforms (CDN minify, edge rewrites, compression) that change the served binary after
  upload.

Platform-specific fixes live in the platform reference.

## Captured frame checks

From an affected PostHog error event, collect one minified application frame:

- `filename`
- `line` or `lineno`
- `column` or `colno`
- `function`
- `chunk_id` (or platform-equivalent symbol-set ref)
- any `resolve_failure`, especially `Token not found`

The frame `filename` should match the deployed binary URL. The `chunk_id` should match the symbol set `ref`. The
captured generated position should point into the same binary that was uploaded with the symbol data.

## Failure matrix (cross-platform)

| Evidence                                         | Likely cause                                                            | Next check                                                                    |
| ------------------------------------------------ | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| No `chunk_id` on frames                          | Chunk ID injection missing or SDK frame parser did not map the filename | Inspect deployed binary and raw frame filenames.                              |
| Symbol set row missing                           | Upload went to another PostHog project/host or skipped this asset       | Compare plugin `projectId`, `host`, and `ref`.                                |
| `has_uploaded_file: false`                       | Upload did not finish                                                   | Check build logs; compare `posthog-cli` output to the symbol set row.         |
| Non-null `failure_reason`                        | PostHog could not parse the uploaded symbol data                        | Download via Step 3 and inspect the extracted contents.                       |
| Uploaded artifact valid, deployed binary differs | Deployment/CDN/post-build transform changed the binary after upload     | Compare deployed bytes to local build output.                                 |
| `Token not found`                                | Captured position has no token in the uploaded symbol data              | Verify captured position, deployed binary identity, and symbol-data coverage. |

Platform-specific failure modes (empty `mappings`, missing `sourcesContent`, Hermes function-offset mismatch,
Proguard class-name drift, dSYM UUID mismatch) live in the platform reference.
