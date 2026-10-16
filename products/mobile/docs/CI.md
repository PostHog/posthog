# CI

Two GitHub Actions workflows cover the app. Both work inside `products/mobile` and never install the repo root workspace.

## Mobile CI

`.github/workflows/mobile-ci.yml` runs on pull requests and on pushes to `master` that change `products/mobile/**`, the Signals generated API schemas, or the workflow file.
Markdown changes alone do not start it.

One job runs these steps, the same commands you run locally:

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm test --ci
```

Write `pnpm test --ci`, not `pnpm test -- --ci`. pnpm forwards the `--`, and Jest then reads `--ci` as a test path pattern.

Details:

- The checkout includes `products/signals/frontend/generated/api.schemas.ts` for the PR checks response type. It is a type-only import, so native builds still upload only `products/mobile`.
- pnpm comes from `packageManager` in `products/mobile/package.json`, not from the repo root.
- Node comes from `products/mobile/.node-version`. Keep it equal to the repo's `.nvmrc` and to `node` in `eas.json`.
- The pnpm store cache is keyed on `products/mobile/pnpm-lock.yaml`. Pull requests only restore it. Pushes to `master` save it.
- A newer push to the same pull request cancels the older run.
- The check is not required by branch protection.
  It uses trigger paths, so most pull requests never start it.
  A required check must report on every pull request, so making it required needs a `changes` job instead of trigger paths.
  See `/authoring-ci-workflows`.

## Mobile Build

`.github/workflows/mobile-build.yml` queues an EAS build. It runs only when someone starts it from the Actions tab.

| Input | Values | Default |
| --- | --- | --- |
| `profile` | `development`, `preview`, `production` | `preview` |
| `platform` | `all`, `ios`, `android` | `all` |
| `submit` | Submit to TestFlight and the Play internal track when the build finishes | off |

- The job runs `scripts/eas-build.sh` with `--no-wait`, so it ends once EAS has the upload. Follow the build on the EAS project page.
- `submit` works only for the `production` profile and only from `master`. Other combinations fail before any upload.
- With `submit`, EAS submits each build after it finishes (`--auto-submit`).
- The build message is `<branch>@<commit>`, because EAS cannot read git when it uploads only this directory.
- eas-cli is pinned in the workflow. Raise it on purpose, after reading its changelog.
- It needs the `EXPO_TOKEN` repository secret. Store keys stay on EAS.

No workflow publishes over-the-air updates. Publish them from your machine, see [OTA.md](OTA.md).

## Check workflow changes

From the main checkout:

```sh
hogli lint:workflows
actionlint -config-file .github/actionlint.yaml .github/workflows/mobile-ci.yml .github/workflows/mobile-build.yml
```
