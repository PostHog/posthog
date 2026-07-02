//! Direct coverage for the canonical value printer's string escaping (`print.rs`), which renders
//! Hog string literals the way the reference VMs do for `sql`/`print` output. Pure and known-answer,
//! so it pins the escaping rules without standing up a VM heap.

use hogvm::escape_string;

#[test]
fn escapes_quotes_backslashes_and_control_chars() {
    let cases: &[(&str, &str)] = &[
        ("hi", "'hi'"),
        ("", "''"),
        ("it's", r"'it\'s'"),
        (r"a\b", r"'a\\b'"),
        ("line\nbreak", r"'line\nbreak'"),
        ("tab\there", r"'tab\there'"),
        ("carriage\rreturn", r"'carriage\rreturn'"),
        ("null\0byte", r"'null\0byte'"),
        // Non-control Unicode passes through untouched, only wrapped in quotes.
        ("café 🦔", "'café 🦔'"),
    ];
    for (input, expected) in cases {
        assert_eq!(escape_string(input), *expected, "escape_string({input:?})");
    }
}
