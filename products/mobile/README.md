# PostHog mobile

A standalone Expo + React Native app for iOS and Android, named **PostHog** on the stores.
It is a quick-triage companion to the PostHog home page:
open your latest reports, hand them to the PostHog agent, answer its questions,
review the PR it opens, reassign, resolve, dismiss, mark read, or chat with PostHog AI about a report.

Demo mode renders the whole design from fixture data with no network.
Signed in, the same screens read the PostHog API.

This directory is its own pnpm workspace with its own lockfile.
The repo root workspace excludes it, so run everything from here.

## Run it

```sh
cd products/mobile
pnpm install          # Node 24.13.0 (see .node-version), pnpm 10
pnpm ios              # build the dev client, open it in the iOS simulator and start Metro
pnpm web              # Expo web in the browser, used for render checks; copies CanvasKit to public/ first
pnpm android          # build the dev client and open it in an Android emulator
pnpm start            # Metro only, for a dev client that is already installed
```

`pnpm ios` needs Xcode with an iOS simulator runtime, and CocoaPods.
The first build takes about 10 minutes. Later builds reuse the Xcode cache.
If another Metro already uses port 8081, run `pnpm ios --port 8181`.
If the app says it cannot load the project from your network address, see [Troubleshooting](docs/TESTING.md#troubleshooting).

### Demo mode

Demo mode shows fixture reports and needs no PostHog account or network.
It is available in every build, including preview and store builds, so app reviewers can try the app without an account.
To start it, tap **Try the demo** on the sign-in screen. This is the only way to start demo mode in a release build.
To leave it, tap **Exit demo** in Settings.
The app saves demo mode on the device, so a demo session continues after the app relaunches.

Development bundles (`__DEV__`), including local Metro sessions, also have a demo mode toggle in Settings.
To start a development bundle in demo mode, set `EXPO_PUBLIC_DEMO_MODE=1` when you start Metro:

```sh
EXPO_PUBLIC_DEMO_MODE=1 pnpm ios
EXPO_PUBLIC_DEMO_MODE=1 pnpm web
```

The flag sets only the first value. The app saves demo mode on the device, so after you leave demo mode in Settings the flag has no effect until you reinstall the app.
Metro inlines `EXPO_PUBLIC_*` values when it bundles, so restart Metro with `--clear` after you change one.

Deep links open screens directly, for example in the simulator:

```sh
xcrun simctl openurl booted "posthog://inbox"
xcrun simctl openurl booted "posthog://report/demo-report-load-time"
```

A build made with `APP_VARIANT=development` or `preview` uses the `posthog-dev://` or `posthog-preview://` scheme instead.

### Environment variables

| Variable | Use |
| --- | --- |
| `EXPO_PUBLIC_POSTHOG_KEY` | Project API key for the app's own usage analytics. Analytics are off when it is not set. |
| `EXPO_PUBLIC_POSTHOG_HOST` | Host for those analytics, for example `https://us.i.posthog.com`. |
| `EXPO_PUBLIC_DEMO_MODE` | `1` starts a development bundle in demo mode. Release bundles ignore it, so **Try the demo** is the only way into demo mode there. |
| `EXPO_PUBLIC_SIGNUP_LINK` | `0` hides the "Create an account" link on the sign-in screen, for store builds where a link out to sign-up is not allowed. The `production` profile in `eas.json` and `pnpm update:production` set it, so store builds hide the link. |
| `APP_VARIANT` | Build-time only: `development`, `preview` or `production` (the default). It sets the app name, bundle id, URL scheme, App Group and icon, so the variants install side by side. `eas.json` sets it per profile. See [RELEASING.md](docs/RELEASING.md#build-variants). |
| `GOOGLE_SERVICES_JSON` | Build-time only: path to the Firebase `google-services.json` that Android push needs. On EAS it is a file variable; locally, a `google-services.json` in this directory is used instead. See [PUSH.md](docs/PUSH.md#credentials). |

For local runs, put them in `.env.local` (git ignores it). Expo loads it when Metro starts.
A local run without `APP_VARIANT` builds the store identity, but the app treats any Metro bundle as a development build: it shows the environment ribbon and the Settings Environment group, and accepts `http://localhost`.
EAS builds and updates read them from the EAS environment of their profile, see [RELEASING.md](docs/RELEASING.md#one-time-setup).

## Check

```sh
pnpm typecheck        # tsc --noEmit
pnpm lint             # biome check .   (pnpm fix to apply fixes)
pnpm test             # jest (jest-expo preset)
npx expo-doctor
```

## Assets

The app icon, adaptive icon, favicon and the iOS 26 `app.icon` bundle are copies of the
PostHog Desktop mobile host's logomark assets.
`splash-icon.png` is the gradient logomark from [brand.posthog.com](https://brand.posthog.com/logo),
rendered from `frontend/src/assets/posthog-icon.svg` with `rsvg-convert -w 1040`.
The in-app logomark and landscape lockup (`src/ui/icons/PostHogLogomark.tsx`, `PostHogLogo.tsx`)
are the same brand geometry ported to `react-native-svg`.
`icon-dev.png`, `icon-preview.png` and their `adaptive-icon-*` copies add a DEV or PREVIEW band to the icon.
Regenerate them after an icon change with `uv run --with pillow python scripts/make_variant_icons.py`.

## Docs

- [Architecture](docs/ARCHITECTURE.md): directory map, data flow, module boundaries, hook surface
- [Design](docs/DESIGN.md): tokens, component inventory, how handoff CSS values map to React Native
- [Decisions](docs/DECISIONS.md): choices the build contract left open
- [Gaps](docs/GAPS.md): known gaps and local-only behavior
- [API](docs/API.md), [Push](docs/PUSH.md)
- [Releasing](docs/RELEASING.md): local standalone phone installs, EAS builds, TestFlight and the Play internal track
- [OTA updates](docs/OTA.md): update channels, runtime version, rollbacks
- [CI](docs/CI.md): the Mobile CI and Mobile Build workflows
- [Testing](docs/TESTING.md): the demo walkthrough on the iOS simulator with Argent
