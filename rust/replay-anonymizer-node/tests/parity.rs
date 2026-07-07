//! Reads the shared JSON fixtures (also consumed by the TS Jest suite) and asserts the Rust scrubbers
//! match. Keeping one fixture set means a change must keep both implementations in agreement.

use std::path::Path;
use std::time::Instant;

use replay_anonymizer_node::allow_lists::AllowLists;
use replay_anonymizer_node::{
    anonymize_event_str, anonymize_message, context::Ctx, text::scrub_text, url::scrub_url_opts,
};
use serde_json::Value;

fn fixtures(name: &str) -> Vec<Value> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name);
    let data = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path:?}: {e}"));
    serde_json::from_str(&data).unwrap_or_else(|e| panic!("parse {path:?}: {e}"))
}

fn allow_of(case: &Value) -> AllowLists {
    let allow = &case["allow"];
    let strings = |key: &str| -> Vec<String> {
        allow[key]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default()
    };
    AllowLists::new(strings("text"), strings("url"))
}

#[test]
fn text_fixtures() {
    for case in fixtures("text.json") {
        let allow = allow_of(&case);
        let input = case["input"].as_str().unwrap();
        let expected = case["expected"].as_str().unwrap();
        let actual = scrub_text(&allow, input).unwrap_or_else(|| input.to_string());
        assert_eq!(actual, expected, "text case: {}", case["name"]);
    }
}

#[test]
fn url_fixtures() {
    for case in fixtures("url.json") {
        let allow = allow_of(&case);
        let input = case["input"].as_str().unwrap();
        let expected = case["expected"].as_str().unwrap();
        let collapse_host = case["collapseHost"].as_bool().unwrap_or(false);
        let first_party_hosts: Vec<String> = case["firstPartyHosts"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        let ctx = Ctx::with_first_party_hosts(&allow, first_party_hosts);
        let actual =
            scrub_url_opts(&ctx, input, collapse_host).unwrap_or_else(|| input.to_string());
        assert_eq!(actual, expected, "url case: {}", case["name"]);
    }
}

#[test]
fn event_fixtures() {
    for case in fixtures("events.json") {
        let allow = allow_of(&case);
        let event_json = serde_json::to_string(&case["event"]).unwrap();
        let scrubbed = anonymize_event_str(&allow, &event_json)
            .expect("anonymize should not fail on fixtures");
        let actual: Value = serde_json::from_str(&scrubbed).unwrap();
        assert_eq!(actual, case["expected"], "event case: {}", case["name"]);
    }
}

#[test]
fn message_fixtures() {
    // Full `{ windowId: Event[] }` messages (not single events) — exercises the whole-message walk:
    // multiple windows, mixed/interleaved event types, malformed events, and the unchanged-message path.
    for case in fixtures("messages.json") {
        let allow = allow_of(&case);
        let message_json = serde_json::to_string(&case["message"]).unwrap();
        let mut bytes = message_json.into_bytes();
        let scrubbed =
            anonymize_message(&allow, &mut bytes).expect("anonymize should not fail on fixtures");
        // `None` = nothing changed, so the caller keeps the original message.
        let actual: Value = match scrubbed {
            Some(s) => serde_json::from_str(&s).unwrap(),
            None => case["message"].clone(),
        };
        assert_eq!(actual, case["expected"], "message case: {}", case["name"]);
    }
}

#[test]
fn pathologically_deep_json_fails_closed_without_crashing() {
    // Untrusted rrweb could nest deep enough to overflow the walker's stack; the depth guard must
    // reject it as an error (message dropped) rather than recursing into a crash.
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    let mut deep = String::from("{\"w\":");
    deep.push_str(&"[".repeat(4000));
    deep.push_str(&"]".repeat(4000));
    deep.push('}');
    let mut bytes = deep.into_bytes();
    assert!(anonymize_message(&allow, &mut bytes).is_err());
}

#[test]
fn email_redaction_is_linear() {
    // A backtracking email regex is O(n^2) here (~seconds at this size); the linear scanner is ~ms.
    let run = "A1b2C3d4".repeat((256 * 1024) / 8);
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    let start = Instant::now();
    let out = scrub_text(&allow, &run);
    assert!(
        out.is_some(),
        "an unbroken non-allowlisted run should be redacted"
    );
    assert!(
        start.elapsed().as_millis() < 2000,
        "email/text scrub should be linear, took {:?}",
        start.elapsed()
    );
}

#[test]
fn email_scanner_worst_case_is_linear() {
    // The exact incident shape: a long unbroken local part + `@` + a long domain that never forms a
    // valid `.TLD` is what made the old email regex backtrack quadratically (minutes per event). The
    // hand-rolled scanner expands around each `@` once with disjoint domain scans, so a 256 KB
    // `@`-bearing run must still finish in milliseconds. `email_redaction_is_linear` has no `@`, so it
    // only covers the tokenizer — this covers the email scanner itself.
    let local = "a".repeat(128 * 1024);
    let domain = "1".repeat(128 * 1024); // all digits: can never satisfy `.` + >=2 letters
    let input = format!("{local}@{domain}");
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    let start = Instant::now();
    let _ = scrub_text(&allow, &input);
    assert!(
        start.elapsed().as_millis() < 2000,
        "email scanner should be linear on an @-bearing run, took {:?}",
        start.elapsed()
    );
}
