use std::sync::Arc;
use std::time::Instant;

use cymbal_proto::cymbal::path_resolution::v1::path_resolution_server::PathResolution;
use cymbal_proto::cymbal::path_resolution::v1::{
    ListState, Outcome, PathResult, ResolvePathsRequest, ResolvePathsResponse,
};
use tonic::{Request, Response, Status};

use crate::core::metric_consts::{
    PATH_RESOLUTION_PATHS, PATH_RESOLUTION_REQUESTS, PATH_RESOLUTION_REQUEST_SECONDS,
};
use crate::core::repo_slug::{is_full_commit_sha, is_valid_repo_slug};

use super::list_store::{ListKey, ListLookup, ListStore};
use super::matching::{resolve_paths, PathOutcome};

pub const MAX_PATHS: usize = 100;
pub const MAX_PATH_CHARS: usize = 1024;

pub struct PathResolutionService {
    store: Arc<ListStore>,
}

impl PathResolutionService {
    pub fn new(store: Arc<ListStore>) -> Self {
        Self { store }
    }
}

#[tonic::async_trait]
impl PathResolution for PathResolutionService {
    async fn resolve_paths(
        &self,
        request: Request<ResolvePathsRequest>,
    ) -> Result<Response<ResolvePathsResponse>, Status> {
        let started = Instant::now();
        let request = request.into_inner();
        validate(&request)?;

        let key = ListKey {
            team_id: request.team_id,
            repo: request.repo,
            commit: request.commit,
        };
        let (list_state, outcomes) = match self.store.get(&key).await {
            ListLookup::Loaded(index) => (
                ListState::Loaded,
                resolve_paths(&request.paths, index.as_ref()),
            ),
            ListLookup::Missing => (
                ListState::Missing,
                vec![PathOutcome::NoMatch; request.paths.len()],
            ),
            ListLookup::Error => (
                ListState::Error,
                vec![PathOutcome::NoMatch; request.paths.len()],
            ),
        };

        let results = outcomes.into_iter().map(to_result).collect();
        metrics::counter!(PATH_RESOLUTION_REQUESTS, "list_state" => list_state_label(list_state))
            .increment(1);
        metrics::histogram!(PATH_RESOLUTION_REQUEST_SECONDS)
            .record(started.elapsed().as_secs_f64());
        Ok(Response::new(ResolvePathsResponse {
            list_state: list_state as i32,
            results,
        }))
    }
}

#[allow(clippy::result_large_err)]
fn validate(request: &ResolvePathsRequest) -> Result<(), Status> {
    if request.team_id <= 0 {
        return Err(Status::invalid_argument("team_id must be positive"));
    }
    if !is_valid_repo_slug(&request.repo) {
        return Err(Status::invalid_argument("repo is not a valid repo slug"));
    }
    if !is_full_commit_sha(&request.commit) {
        return Err(Status::invalid_argument(
            "commit must be a 40-character lowercase SHA",
        ));
    }
    if request.paths.len() > MAX_PATHS {
        return Err(Status::invalid_argument(format!(
            "at most {MAX_PATHS} paths are allowed"
        )));
    }
    if request
        .paths
        .iter()
        .any(|path| path.chars().count() > MAX_PATH_CHARS)
    {
        return Err(Status::invalid_argument(format!(
            "a path is longer than {MAX_PATH_CHARS} characters"
        )));
    }
    Ok(())
}

fn to_result(outcome: PathOutcome) -> PathResult {
    let (outcome, repo_path, label) = match outcome {
        PathOutcome::Sure(path) => (Outcome::Sure, path, "sure"),
        PathOutcome::Support(path) => (Outcome::Support, path, "support"),
        PathOutcome::Tie => (Outcome::Tie, String::new(), "tie"),
        PathOutcome::NoMatch => (Outcome::NoMatch, String::new(), "no_match"),
    };
    metrics::counter!(PATH_RESOLUTION_PATHS, "outcome" => label).increment(1);
    PathResult {
        outcome: outcome as i32,
        repo_path,
    }
}

fn list_state_label(state: ListState) -> &'static str {
    match state {
        ListState::Unspecified => "unspecified",
        ListState::Loaded => "loaded",
        ListState::Missing => "missing",
        ListState::Error => "error",
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use async_trait::async_trait;
    use bytes::Bytes;
    use tonic::Code;

    use super::super::list_store::ListStoreConfig;
    use super::*;
    use crate::core::error::UnhandledError;
    use crate::core::symbolication::symbol_store::BlobClient;

    const COMMIT: &str = "0123456789abcdef0123456789abcdef01234567";
    const REPO: &str = "github.com/acme/shop";

    enum Stored {
        List(&'static str),
        Nothing,
        Failing,
    }

    struct OneObject(Stored);

    #[async_trait]
    impl BlobClient for OneObject {
        async fn get(&self, _bucket: &str, _key: &str) -> Result<Option<Bytes>, UnhandledError> {
            match self.0 {
                Stored::List(text) => Ok(Some(Bytes::from(
                    zstd::encode_all(text.as_bytes(), 3).unwrap(),
                ))),
                Stored::Nothing => Ok(None),
                Stored::Failing => Err(UnhandledError::Other("object storage is down".to_string())),
            }
        }

        async fn put(&self, _bucket: &str, _key: &str, _data: Bytes) -> Result<(), UnhandledError> {
            unimplemented!()
        }

        async fn delete(&self, _bucket: &str, _key: &str) -> Result<(), UnhandledError> {
            unimplemented!()
        }

        async fn ping_bucket(&self, _bucket: &str) -> Result<(), UnhandledError> {
            Ok(())
        }
    }

    fn service(stored: Stored) -> PathResolutionService {
        let config = ListStoreConfig {
            bucket: "posthog".to_string(),
            folder: "repo_paths".to_string(),
            cache_bytes: 1 << 20,
            negative_ttl: Duration::from_secs(60),
            max_decompressed_bytes: 1 << 20,
            load_timeout: Duration::from_secs(5),
        };
        PathResolutionService::new(ListStore::new(Arc::new(OneObject(stored)), config))
    }

    fn request(paths: Vec<String>) -> Request<ResolvePathsRequest> {
        Request::new(ResolvePathsRequest {
            team_id: 7,
            repo: REPO.to_string(),
            commit: COMMIT.to_string(),
            paths,
        })
    }

    #[tokio::test]
    async fn answers_in_request_order_with_the_list_state() {
        let paths = vec![
            "/app/missing.py".to_string(),
            "/app/acme_api/views.py".to_string(),
            "../../src/index.tsx".to_string(),
        ];
        let cases = [
            (
                Stored::List("services/api/acme_api/views.py\napps/web/src/index.tsx\napps/admin/src/index.tsx"),
                ListState::Loaded,
                vec![
                    (Outcome::NoMatch, ""),
                    (Outcome::Sure, "services/api/acme_api/views.py"),
                    (Outcome::Tie, ""),
                ],
            ),
            (Stored::Nothing, ListState::Missing, vec![(Outcome::NoMatch, ""); 3]),
            (Stored::Failing, ListState::Error, vec![(Outcome::NoMatch, ""); 3]),
        ];

        for (stored, list_state, expected) in cases {
            let response = service(stored)
                .resolve_paths(request(paths.clone()))
                .await
                .unwrap()
                .into_inner();

            assert_eq!(response.list_state, list_state as i32);
            let results: Vec<(i32, &str)> = response
                .results
                .iter()
                .map(|result| (result.outcome, result.repo_path.as_str()))
                .collect();
            let expected: Vec<(i32, &str)> = expected
                .into_iter()
                .map(|(outcome, path)| (outcome as i32, path))
                .collect();
            assert_eq!(results, expected, "{list_state:?}");
        }
    }

    #[tokio::test]
    async fn rejects_invalid_requests() {
        let too_many = vec!["a.py".to_string(); MAX_PATHS + 1];
        let too_long = vec!["a/".repeat(MAX_PATH_CHARS)];
        let cases: Vec<ResolvePathsRequest> = vec![
            ResolvePathsRequest {
                team_id: 7,
                repo: REPO.into(),
                commit: COMMIT.into(),
                paths: too_many,
            },
            ResolvePathsRequest {
                team_id: 7,
                repo: REPO.into(),
                commit: COMMIT.into(),
                paths: too_long,
            },
            ResolvePathsRequest {
                team_id: 7,
                repo: "github.com/acme".into(),
                commit: COMMIT.into(),
                paths: vec![],
            },
            ResolvePathsRequest {
                team_id: 7,
                repo: REPO.into(),
                commit: "0123abc".into(),
                paths: vec![],
            },
            ResolvePathsRequest {
                team_id: 0,
                repo: REPO.into(),
                commit: COMMIT.into(),
                paths: vec![],
            },
        ];

        for case in cases {
            let status = service(Stored::Nothing)
                .resolve_paths(Request::new(case))
                .await
                .unwrap_err();
            assert_eq!(status.code(), Code::InvalidArgument);
        }
    }
}
