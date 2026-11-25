# meep-script

Copy this directory into a Rust project to validate and execute JavaScript views without starting GPUI. The default native feature includes QuickJS. The engine, SDK, element contract, datasets, scenes, block document and example scripts travel together.

Run `cargo run --example check -- path/to/view.js` to validate a script. With no argument it validates the bundled notes example. Use `meep_script::script::validate` on edits and installs and `meep_script::script::Engine` to run a saved view. Disable default features for the pure data models or enable `browser` on wasm for trusted script previews.
