# PostHog mobile

The app is its own pnpm workspace. Run every command from `products/mobile`.
[README.md](README.md) has setup and the docs index; read it before your first change here.

## Skills

- Invoke `/requesting-mobile-releases` before you create or edit a file under `releases/requests/`, and when a change touches `package.json`, `pnpm-lock.yaml`, `app.config.ts`, `eas.json`, `plugins/`, `targets/`, `modules/` or any `expo-*` or `react-native-*` dependency. It decides whether the change can ship over the air or needs a native release. A merged request publishes without a human gate.
- Invoke `/running-mobile-demo-flows` before you report a change to a screen, navigation, the demo fixtures or a flow as done. CI does not run the simulator flows, so the local run is the only UI check.

## Pull request screenshots

Every PR touching `products/mobile/` must include before-and-after screenshots from **both iOS and Android** if it changes frontend or user-facing behavior.
An iOS simulator or an Android emulator qualifies for its platform, as does a physical device.
This includes layout, styling, copy, navigation, interactions, and loading, empty, or error states.
Capture both platforms even when the intended change is platform-specific, so reviewers can check the other platform for regressions.
PRs with no frontend or user-facing impact should explain why screenshots do not apply.

1. Run the base revision on each device and capture the affected screens and states before the change.
2. Run the proposed revision on the same devices and capture the same screens and states, with matching data and orientation.
   For a new screen, capture the existing entry point or flow as the before state.
3. Attach the screenshot pairs to the PR description, labeled **iOS before**, **iOS after**, **Android before**, and **Android after**.
   Record the model, OS version, screen size, and whether each capture used a physical device, simulator, or emulator.
4. Prefer repeating the comparison on multiple screen sizes per platform, including smaller and larger phones where available.
   Record the sizes tested so reviewers can see the coverage.

Capture the native app on the selected device, simulator, or emulator. Web previews can supplement the native screenshots.
A recording may supplement the screenshot pairs to show an interaction.
Before uploading screenshots, read the [repository PR guidance](../../AGENTS.md#pr-descriptions) for public asset requirements.
Use demo or invented data.

If either platform's screenshots are unavailable, state the missing coverage in the PR and arrange device testing before marking it ready for review.
