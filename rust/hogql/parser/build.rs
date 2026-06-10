// Tell macOS's linker to defer libpython symbols to load time. PyO3's
// `extension-module` feature suppresses the libpython link, but on macOS the
// linker still needs `-undefined dynamic_lookup` to accept the unresolved
// symbols when producing a `cdylib`. `maturin` adds this implicitly when it
// builds the wheel, but a plain `cargo build -p hogql_parser_rs` on
// macOS doesn't go through maturin, so we add it here too.
fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-link-arg=-undefined");
        println!("cargo:rustc-link-arg=dynamic_lookup");
    }
}
