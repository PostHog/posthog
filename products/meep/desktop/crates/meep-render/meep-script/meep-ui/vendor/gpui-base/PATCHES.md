GPUI Base 0.9.0, from crates.io (Apache-2.0).

One behavior change, in `src/text/inline.rs` and `src/text/inline_flow.rs`:
a selection in a wrapped paragraph fills the line's band and covers a code
span's box padding on each side it reaches. Upstream highlights each
fragment's glyphs only, at the fragment's own line height, so a selection
broke around inline code: the box's padding stayed unselected and the code's
highlight was shorter than the prose's. The `chat-select-code` preview states
show it.

`Cargo.lock`, `Cargo.toml.orig` and `.cargo_vcs_info.json` are omitted.
Everything else is as published.
