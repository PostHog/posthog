# CI

Three GitHub Actions workflows cover the app. They install the independent `products/mobile` workspace.

## Mobile CI

`.github/workflows/mobile-ci.yml` is a reusable workflow. `pr-housekeeping.yml` calls it on every pull request, and `mobile-release.yml` calls it for each release commit.
Direct pushes to `master` that match the workflow's paths only install dependencies and warm the pnpm store cache. They do not repeat validation.

A `changes` job reads the pull request diff and selects the mobile checks.

| Changed files                                                         | Mobile checks                            |
| --------------------------------------------------------------------- | ---------------------------------------- |
| `products/mobile/**` (Markdown excluded) or `mobile-ci.yml`           | Typecheck, lint, Jest and release checks |
| Generated Signals or Error Tracking API types, with no mobile changes | Typecheck                                |
| Neither group                                                         | Status report only                       |

The generated API files are type-only imports in the app, so typechecking checks compatibility without repeating runtime tests.
Changes in both groups run the full suite. Release commits also run the full suite.
The `Mobile CI Pass` job reports a verdict on every run, so it can be a required branch-protection check.
A trigger-level `paths:` filter cannot do this: a required check that never dispatches leaves the pull request waiting for a status that never arrives. See `/authoring-ci-workflows`.

The full check job runs these steps, using the same commands you run locally:

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

- The checkout includes the mobile app and its imported generated Signals and Error Tracking API types. Keep new runtime dependencies inside the mobile workspace.
- pnpm comes from `packageManager` in `products/mobile/package.json`, not from the repo root.
- Node comes from `products/mobile/.node-version`. Keep it equal to the repo's `.nvmrc` and to `node` in `eas.json`.
- The pnpm store cache is keyed on `products/mobile/pnpm-lock.yaml`. Pull requests only restore it. Pushes to `master` save it.
- Generated API type changes do not trigger a separate cache-warming run on `master`; they do not change the mobile dependencies.
- Change detection uses the existing paths-filter GitHub App. Both reusable-workflow callers pass `GH_APP_POSTHOG_PATHS_FILTER_PRIVATE_KEY` by name. The workflow creates a token with pull-request read access only for same-repository PRs; fork and Dependabot PRs use `GITHUB_TOKEN` because they do not receive the app secret. No credential value belongs in the repository.
- A newer push to the same pull request cancels the older run.
- Push runs use a separate concurrency group for each commit, so a later release cannot replace an earlier pending validation run. Publication stays serialized; see [release ordering and retries](RELEASING.md#receipts-ordering-and-retries).
- After this workflow reaches `master`, ask a repository administrator through `@PostHog/team-devex` to add `mobile-ci / Mobile CI Pass` to the `master` ruleset's required status checks with GitHub Actions as its source. Keep the other required checks. YAML comments do not configure repository rules.
- The release workflow calls Mobile CI on the merged commit. A push has no pull request diff to filter, so the checks always run there.

`@cvolzer3` owns both mobile app trees and all mobile workflow files in `CODEOWNERS`, including release requests, release tooling and the public OTA certificate.

The simulator demo flows do not run in CI. Run them locally before you merge a change to a screen. See [TESTING.md](TESTING.md#demo-flows-before-you-merge) and the `/running-mobile-demo-flows` skill.

## Mobile Build

`.github/workflows/mobile-build.yml` queues an EAS build. It runs only when someone starts it from the Actions tab on `master`; other refs are skipped before checkout or credentials. The `mobile-build` environment must also allow only `master`.

| Input      | Values                   | Default   |
| ---------- | ------------------------ | --------- |
| `profile`  | `development`, `preview` | `preview` |
| `platform` | `all`, `ios`, `android`  | `all`     |

- The job runs `scripts/eas-build.sh` with `--no-wait`, so it ends once EAS has the upload. Follow the build on the EAS project page.
- This workflow makes internal builds only. Store submission is owned by Mobile Release.
- The build message is `<branch>@<commit>`, because EAS cannot read git when it uploads only this directory.
- eas-cli is pinned in the workflow. Raise it on purpose, after reading its changelog.
- It needs a dedicated `MOBILE_BUILD_EXPO_TOKEN` secret only in the `mobile-build` environment. Store keys stay on EAS. See the protected environment setup in [RELEASING.md](RELEASING.md#one-time-hosted-release-setup).

## Mobile Release

`.github/workflows/mobile-release.yml` starts when a push to `master` adds a release request under `products/mobile/releases/requests/`. A normal app merge without a request does not publish anything. PR runs never publish.

The request selects `native` or `ota`, names the app/runtime version, describes the changes, and identifies the preceding completed release. Requests are append-only; each release push adds exactly one. Use `pnpm release:request` to prepare the file, then include it in the app PR. See [RELEASING.md](RELEASING.md) for commands and first-release setup.

After the required checks pass and an authorized `mobile-production` reviewer approves the deployment, the hosted publish job uses the exact tested commit:

- **Native:** verify a higher app/runtime version, build both platforms, wait for successful builds, and submit those exact build IDs to TestFlight and Play internal testing. Public-store promotion remains manual.
- **OTA:** verify the runtime and native fingerprints against the last completed native release, sign and upload to an unlinked staging branch, and sign the promotion of that exact update group to the production channel. The native receipt pins the signing certificate as well as native compatibility.

The `mobile-production` environment must require reviewer Chris Volzer (`@cvolzer3`), allow self-review, disable administrator bypass and allow only `master`; these settings are configured by an administrator outside the workflow. It holds `MOBILE_PRODUCTION_EXPO_TOKEN` and `MOBILE_OTA_SIGNING_KEY`, with no repository/organization secret fallback. The private OTA key is available only to the OTA publish step, after dependency installation; native builds need only the checked-in public certificate. A durable release receipt prevents a completed request from publishing twice. Interrupted publication requires reconciliation rather than blindly retrying; the request's predecessor prevents a later release from silently overtaking a missing one. See the release guide for recovery.

Production build/submit/OTA package commands now direct developers to this request flow. No active release request is included with the automation itself.

Complete the [mobile app release checks](../../../docs/internal/mobile-release-checks.md) before sharing builds or promoting an internal build publicly. Hosted checks and the local demo flows do not verify real sign-in, push delivery or physical-device behavior.

## Check workflow changes

From the main checkout:

```sh
hogli lint:workflows
actionlint -config-file .github/actionlint.yaml .github/workflows/mobile-ci.yml .github/workflows/mobile-build.yml .github/workflows/mobile-release.yml
```
