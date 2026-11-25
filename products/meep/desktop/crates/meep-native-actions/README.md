# meep-native-actions

Use macOS confirmation dialogs, file and folder pickers, a save panel, text clipboard and selection, application links, calendar creation and reminder creation. Copy the directory into your project. The backend uses View's fixed native adapter. Caller values travel as JSON over stdin.

For an agent or rendered view, translate its tool request to an `Action` in your host. Call `dispatch(backend, &action, authorize)` with an `Arc<dyn DesktopActions>`. The callback receives the typed action. Check the authenticated caller, current grant and any foreground user gesture there. Applications can restrict link schemes or destinations further. File pickers return paths to the trusted host, which decides whether to import a file or issue a scoped reference. The save panel selects a destination for the host to write.

Paste operations share a lock and finish pasteboard restoration when the originating request is cancelled. A concurrent copy keeps the person's newer clipboard content. macOS controls Accessibility and Automation consent for interactions with other apps. Include the Apple Events usage description and the corresponding entitlement when packaging an app that uses Apple Events.

Run `cargo run --example confirm` for a fixture-backed confirmation. Use `SystemActions` for real desktop operations. A host on another platform can supply the same trait.
