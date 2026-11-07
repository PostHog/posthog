//! Keeps the error-tracking rule validator's copy of this crate's STL in step with the crate.
//!
//! Run `bin/dump_hogvmrs_stl` to rewrite the snapshot after adding or removing an STL function.

use std::path::PathBuf;

use hogvm::{hog_stl, stl};

const UPDATE_ENV: &str = "UPDATE_STL_SNAPSHOT";

fn snapshot_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../products/error_tracking/backend/hogvm_stl.py")
}

fn render_snapshot() -> String {
    let mut names: Vec<String> = stl()
        .into_iter()
        .map(|(name, _)| name)
        .chain(hog_stl().functions().keys().cloned())
        .collect();
    names.sort();
    names.dedup();

    let entries: String = names
        .iter()
        .map(|name| format!("    \"{name}\",\n"))
        .collect();
    format!("RUST_HOGVM_STL = [\n{entries}]\n")
}

#[test]
fn error_tracking_stl_snapshot_matches_crate() {
    let path = snapshot_path();
    let expected = render_snapshot();

    if std::env::var_os(UPDATE_ENV).is_some() {
        std::fs::write(&path, &expected).expect("write STL snapshot");
        return;
    }

    let committed = std::fs::read_to_string(&path).expect("read STL snapshot");
    assert!(
        committed == expected,
        "{} is out of date with the crate's STL. Run bin/dump_hogvmrs_stl and commit the result.",
        path.display()
    );
}
