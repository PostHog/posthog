//! Adds `repo_path` to in-app frames: the file's path in the release repository, so the issue page
//! can link a frame straight to the file. The matching runs in `cymbal-path-resolution`
//! (`crate::modes::path_resolution`); this side picks a path per frame, calls the service, and
//! caches the answers that do not depend on the rest of the exception.
//!
//! Path resolution is best effort. A timeout, an error or an unavailable service leaves frames
//! without a path, and never fails or retries the batch.

pub mod answer_cache;
pub mod best_path;
pub mod client;
pub mod operator;
pub mod raw_paths;

pub use operator::{RepoPathContext, RepoPathResolver};
pub use raw_paths::RawPaths;
