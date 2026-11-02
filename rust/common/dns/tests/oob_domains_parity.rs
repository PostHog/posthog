//! The list lives outside this workspace, so point the test at it with `OOB_DOMAINS_JSON`.
//! Otherwise it walks up from the manifest dir looking for the file.

use std::collections::BTreeSet;
use std::path::PathBuf;

use common_dns::oob_domains::OOB_DOMAINS;

const RELATIVE_PATH: &str = "posthog/security/crosslang/oob_domains.json";

fn domains_json() -> PathBuf {
    if let Ok(path) = std::env::var("OOB_DOMAINS_JSON") {
        let path = PathBuf::from(path);
        if path.is_file() {
            return path;
        }
        panic!(
            "OOB_DOMAINS_JSON is set to {}, which is not a file",
            path.display()
        );
    }
    let mut current = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        let candidate = current.join(RELATIVE_PATH);
        if candidate.is_file() {
            return candidate;
        }
        if !current.pop() {
            panic!("Could not locate {RELATIVE_PATH} - set OOB_DOMAINS_JSON");
        }
    }
}

#[test]
fn mirror_matches_the_shared_json() {
    let raw = std::fs::read_to_string(domains_json()).expect("the domain list is readable");
    let parsed: serde_json::Value = serde_json::from_str(&raw).expect("the domain list is json");
    let from_file: BTreeSet<&str> = parsed["domains"]
        .as_array()
        .expect("the domain list holds a domains array")
        .iter()
        .map(|value| value.as_str().expect("every domain is a string"))
        .collect();
    let from_mirror: BTreeSet<&str> = OOB_DOMAINS.iter().copied().collect();

    assert_eq!(
        from_file, from_mirror,
        "OOB_DOMAINS has drifted from {RELATIVE_PATH}. Edit the json first, then the mirror."
    );
}
