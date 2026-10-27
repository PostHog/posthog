# CI

Three GitHub Actions workflows cover the app. They install the independent `products/mobile` workspace.

## Mobile CI

`.github/workflows/mobile-ci.yml` is a reusable workflow. `pr-housekeeping.yml` calls it on every pull request, and it also runs on pushes to `master` that change `products/mobile/**` or the workflow file.

A `changes` job reads the pull request diff. When nothing under `products/mobile/**` (Markdown excluded), the generated Signals API types, or the workflow changed, the check job is skipped and the run ends in seconds.
The `Mobile CI Pass` job reports a verdict on every run, so it can be a required branch-protection check.
A trigger-level `paths:` filter cannot do this: a required check that never dispatches leaves the pull request waiting for a status that never arrives. See `/authoring-ci-workflows`.

The check job runs these steps, the same commands you run locally:

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm test --ci
pnpm release:check
pnpm release:test
```

Write `pnpm test --ci`, not `pnpm test -- --ci`. pnpm forwards the `--`, and Jest then reads `--ci` as a test path pattern.

### Formatting

Mobile uses Biome for JavaScript, TypeScript, JSON and CSS, following the desktop and agent workspaces. `pnpm lint` checks formatting and lint rules; `pnpm fix` applies fixes. The root `.oxfmtrc.json` excludes these mobile file types so the two formatters do not rewrite the same files.

Markdown, MDX, SCSS and YAML use the repository's Oxfmt configuration. The shared `pnpm-lock.yaml` ignore pattern already excludes the mobile lockfile. From the repository root, run `bin/hogli format:markdown products/mobile/docs/CI.md` to format a mobile Markdown file.

### CI configuration

Details:

- The checkout includes the mobile app and its existing generated Signals API types. Keep new runtime dependencies inside the mobile workspace.
- pnpm comes from `packageManager` in `products/mobile/package.json`, not from the repo root.
- Node comes from `products/mobile/.node-version`. Keep it equal to the repo's `.nvmrc` and to `node` in `eas.json`.
- The pnpm store cache is keyed on `products/mobile/pnpm-lock.yaml`. Pull requests only restore it. Pushes to `master` save it.
- A newer push to the same pull request cancels the older run.
- The required check is `Mobile CI Pass`. The parent job id in `pr-housekeeping.yml` prefixes the check-run name, so the `master` ruleset lists it as `mobile-ci / Mobile CI Pass`. Confirm the exact name on a run before you add it.
- The release workflow calls Mobile CI on the merged commit. A push has no pull request diff to filter, so the checks always run there.

The simulator demo flows do not run in CI. Run them locally before you merge a change to a screen. See [TESTING.md](TESTING.md#demo-flows-before-you-merge) and the `/running-mobile-demo-flows` skill.

## Mobile Build

`.github/workflows/mobile-build.yml` queues an EAS build. It runs only when someone starts it from the Actions tab.

| Input      | Values                   | Default   |
| ---------- | ------------------------ | --------- |
| `profile`  | `development`, `preview` | `preview` |
| `platform` | `all`, `ios`, `android`  | `all`     |

- The job runs `scripts/eas-build.sh` with `--no-wait`, so it ends once EAS has the upload. Follow the build on the EAS project page.
- This workflow makes internal builds only. Store submission is owned by Mobile Release.
- The build message is `<branch>@<commit>`, because EAS cannot read git when it uploads only this directory.
- eas-cli is pinned in the workflow. Raise it on purpose, after reading its changelog.
- It needs an `EXPO_TOKEN` Actions secret available to the repository. Store keys stay on EAS.

## Mobile Release

`.github/workflows/mobile-release.yml` starts when a push to `master` adds a release request under `products/mobile/releases/requests/`. A normal app merge without a request does not publish anything. PR runs never publish.

The request selects `native` or `ota`, names the app/runtime version, describes the changes, and identifies the preceding completed release. Requests are append-only; each release push adds exactly one. Use `pnpm release:request` to prepare the file, then include it in the app PR. See [RELEASING.md](RELEASING.md) for commands and first-release setup.

After the required checks pass, the hosted publish job uses the exact tested commit:

- **Native:** verify a higher app/runtime version, build both platforms, wait for successful builds, and submit those exact build IDs to TestFlight and Play internal testing. Public-store promotion remains manual.
- **OTA:** verify the runtime and native fingerprints against the last completed native release, upload to an unlinked staging branch, and promote that exact update group to the production channel.

The `mobile-production` environment and Expo credentials govern publication. A durable release receipt prevents a completed request from publishing twice. Interrupted publication requires reconciliation rather than blindly retrying; the request's predecessor prevents a later release from silently overtaking a missing one. See the release guide for recovery.

Production build/submit/OTA package commands now direct developers to this request flow. No active release request is included with the automation itself.

Complete the [mobile app release checks](../../../docs/internal/mobile-release-checks.md) before sharing builds or promoting an internal build publicly. Hosted checks and the local demo flows do not verify real sign-in, push delivery or physical-device behavior.

## Check workflow changes

From the main checkout:

```sh
hogli lint:workflows
actionlint -config-file .github/actionlint.yaml .github/workflows/mobile-ci.yml .github/workflows/mobile-build.yml .github/workflows/mobile-release.yml
```
