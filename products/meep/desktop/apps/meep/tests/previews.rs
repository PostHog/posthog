//! AppKit requires the native screenshot renderer on the process main thread.
#[allow(dead_code, unused_imports)]
#[path = "../src/main.rs"]
mod topics;

fn main() -> anyhow::Result<()> {
    topics::tests::previews::preview_main_screens()
}
