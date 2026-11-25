# meep-server

This crate provides the HTTP fixture host for the Meep desktop and replica tests. Tests create an isolated SQLite store, serve the fixture on a loopback port, and shut it down at the end of each scenario.

Run the fixture suite from the desktop workspace:

```sh
cargo test --locked -p meep-server
```

The native app uses the PostHog backend. See [local development](../../../README.md) for the launcher.
