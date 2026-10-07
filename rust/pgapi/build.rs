//! Emits `PGAPI_BUILD_HASH`, a hash of this crate's sources and the workspace lockfile, so the
//! binary can tell browsers which build they are talking to. No revision id reaches the image
//! build, and hashing the executable at runtime trips a security lint, so the sources stand in.

use std::hash::{DefaultHasher, Hash, Hasher};
use std::path::Path;

fn hash_dir(dir: &Path, h: &mut DefaultHasher) {
    let mut entries: Vec<_> = std::fs::read_dir(dir)
        .expect("crate source directory is readable")
        .map(|e| e.expect("directory entry is readable").path())
        .collect();
    entries.sort();
    for path in entries {
        if path.is_dir() {
            hash_dir(&path, h);
        } else {
            path.to_string_lossy().hash(h);
            std::fs::read(&path)
                .expect("source file is readable")
                .hash(h);
        }
    }
}

fn main() {
    let mut h = DefaultHasher::new();
    hash_dir(Path::new("src"), &mut h);
    if let Ok(lock) = std::fs::read("../Cargo.lock") {
        lock.hash(&mut h);
    }
    println!("cargo:rustc-env=PGAPI_BUILD_HASH={:016x}", h.finish());
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rerun-if-changed=../Cargo.lock");
}
