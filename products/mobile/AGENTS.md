# PostHog mobile

The app is its own pnpm workspace. Run every command from `products/mobile`.
[README.md](README.md) has setup and the docs index; read it before your first change here.

## Skills

- Invoke `/requesting-mobile-releases` before you create or edit a file under `releases/requests/`, and when a change touches `package.json`, `pnpm-lock.yaml`, `app.config.ts`, `eas.json`, `plugins/`, `targets/`, `modules/` or any `expo-*` or `react-native-*` dependency. It decides whether the change can ship over the air or needs a native release. A merged request publishes without a human gate.
- Invoke `/running-mobile-demo-flows` before you report a change to a screen, navigation, the demo fixtures or a flow as done. CI does not run the simulator flows, so the local run is the only UI check.
