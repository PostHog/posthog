// The native workspace includes vendored GPUI sources and scripts evaluated by macOS Automation.
export default {
    '{*.rs,Cargo.toml}': () => 'cargo fmt --all -- --check',
}
