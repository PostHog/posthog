use std::sync::Arc;
use std::time::{Duration, Instant};

use cymbal_proto::cymbal::path_resolution::v1::{ListState, Outcome, ResolvePathsRequest};
use serde_json::Value;
use tokio::sync::Semaphore;

use crate::core::repo_slug::{is_full_commit_sha, is_valid_repo_path, parse_repo_slug};
use crate::error::UnhandledError;
use crate::frames::releases::ReleaseRecord;
use crate::metric_consts::{
    REPO_PATH_FRAMES, REPO_PATH_REQUEST_SECONDS, REPO_PATH_RESOLVER_OPERATOR,
};
use crate::stages::pipeline::HandledError;
use crate::types::exception_event::{ExceptionEvent, Parsed};
use crate::types::operator::{OperatorResult, ValueOperator};
use crate::types::{ExceptionList, Stacktrace};

use super::answer_cache::AnswerCache;
use super::best_path::best_path;
use super::client::{LookupError, PathLookup};

pub const MAX_PATHS_PER_EVENT: usize = 100;

pub struct RepoPathContext {
    pub lookup: Arc<dyn PathLookup>,
    pub answers: AnswerCache,
    pub in_flight: Arc<Semaphore>,
    pub deadline: Duration,
}

#[derive(Clone)]
pub struct RepoPathResolver;

impl ValueOperator for RepoPathResolver {
    type Context = Option<Arc<RepoPathContext>>;
    type Item = ExceptionEvent<Parsed>;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        REPO_PATH_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionEvent<Parsed>,
        ctx: Option<Arc<RepoPathContext>>,
    ) -> OperatorResult<Self> {
        // A client can send a stack that is already resolved, with any `repo_path` on its frames.
        // The issue page trusts `repo_path` to read files from the repository, so only the match
        // below may set it.
        clear_repo_paths(evt.exception_list_mut());
        if let Some(ctx) = ctx {
            ctx.add_repo_paths(&mut evt).await;
        }
        Ok(Ok(evt))
    }
}

fn clear_repo_paths(exceptions: &mut ExceptionList) {
    for exception in exceptions.iter_mut() {
        if let Some(Stacktrace::Resolved { frames }) = &mut exception.stack {
            for frame in frames {
                frame.repo_path = None;
            }
        }
    }
}

struct Target {
    exception: usize,
    frame: usize,
    path: String,
}

struct ReleaseRepo {
    slug: String,
    commit: String,
}

impl RepoPathContext {
    pub async fn add_repo_paths(&self, evt: &mut ExceptionEvent<Parsed>) {
        let targets = targets(evt.exception_list());
        if targets.is_empty() {
            return;
        }
        let repo = match evt.event_release() {
            None => return record(&targets, "no_release"),
            Some(release) => match release_repo(release) {
                Some(repo) => repo,
                None => return record(&targets, "invalid"),
            },
        };

        let team_id = evt.team_id();
        let cached: Vec<Option<Option<String>>> = targets
            .iter()
            .map(|target| {
                self.answers
                    .get(team_id, &repo.slug, &repo.commit, &target.path)
            })
            .collect();
        let answers = if cached.iter().all(Option::is_some) {
            record(&targets, "cached");
            cached.into_iter().map(Option::flatten).collect()
        } else {
            // Every path goes in the request, cached or not: sure answers are what let the
            // service choose between shared file names for the other frames.
            self.request(team_id, &repo, &targets).await
        };

        for (target, answer) in targets.iter().zip(answers) {
            if let Some(Stacktrace::Resolved { frames }) =
                &mut evt.exception_list_mut()[target.exception].stack
            {
                frames[target.frame].repo_path = answer;
            }
        }
    }

    async fn request(
        &self,
        team_id: i32,
        repo: &ReleaseRepo,
        targets: &[Target],
    ) -> Vec<Option<String>> {
        let unanswered = vec![None; targets.len()];
        let started = Instant::now();
        let deadline = started + self.deadline;
        // The deadline also bounds the wait for a slot, so a busy pod adds at most one deadline.
        let Ok(Ok(_permit)) =
            tokio::time::timeout(self.deadline, self.in_flight.clone().acquire_owned()).await
        else {
            record(targets, "timeout");
            return unanswered;
        };

        let request = ResolvePathsRequest {
            team_id: i64::from(team_id),
            repo: repo.slug.clone(),
            commit: repo.commit.clone(),
            paths: targets.iter().map(|target| target.path.clone()).collect(),
        };
        let result = self.lookup.resolve_paths(request, deadline).await;
        metrics::histogram!(REPO_PATH_REQUEST_SECONDS).record(started.elapsed().as_secs_f64());

        let response = match result {
            Ok(response) => response,
            Err(LookupError::Timeout) => {
                record(targets, "timeout");
                return unanswered;
            }
            Err(_) => {
                record(targets, "error");
                return unanswered;
            }
        };
        match ListState::try_from(response.list_state) {
            Ok(ListState::Loaded) if response.results.len() == targets.len() => {}
            // The list is written after the release is created, so a missing list may appear soon:
            // nothing is cached.
            Ok(ListState::Missing) => {
                record(targets, "no_list");
                return unanswered;
            }
            _ => {
                record(targets, "error");
                return unanswered;
            }
        }

        targets
            .iter()
            .zip(response.results)
            .map(|(target, result)| {
                let repo_path = Some(result.repo_path).filter(|path| is_valid_repo_path(path));
                let (label, answer) = match Outcome::try_from(result.outcome) {
                    Ok(Outcome::Sure) if repo_path.is_some() => ("sure", repo_path),
                    Ok(Outcome::Support) if repo_path.is_some() => ("support", repo_path),
                    Ok(Outcome::Tie) => ("tie", None),
                    Ok(Outcome::NoMatch) => ("no_match", None),
                    _ => ("invalid", None),
                };
                if matches!(label, "sure" | "no_match") {
                    self.answers.insert(
                        team_id,
                        &repo.slug,
                        &repo.commit,
                        &target.path,
                        answer.clone(),
                    );
                }
                metrics::counter!(REPO_PATH_FRAMES, "outcome" => label).increment(1);
                answer
            })
            .collect()
    }
}

fn targets(exceptions: &ExceptionList) -> Vec<Target> {
    let mut targets = Vec::new();
    for (exception_index, exception) in exceptions.iter().enumerate() {
        let Some(Stacktrace::Resolved { frames }) = &exception.stack else {
            continue;
        };
        for (frame_index, frame) in frames.iter().enumerate() {
            if targets.len() == MAX_PATHS_PER_EVENT {
                return targets;
            }
            if !frame.in_app {
                continue;
            }
            if let Some(path) = best_path(frame) {
                targets.push(Target {
                    exception: exception_index,
                    frame: frame_index,
                    path,
                });
            }
        }
    }
    targets
}

fn release_repo(release: &ReleaseRecord) -> Option<ReleaseRepo> {
    let git = release.metadata.as_ref()?.get("git")?;
    let slug = parse_repo_slug(git.get("remote_url").and_then(Value::as_str)?)?;
    let commit = git
        .get("commit_id")
        .and_then(Value::as_str)?
        .trim()
        .to_ascii_lowercase();
    is_full_commit_sha(&commit).then_some(ReleaseRepo { slug, commit })
}

fn record(targets: &[Target], outcome: &'static str) {
    metrics::counter!(REPO_PATH_FRAMES, "outcome" => outcome).increment(targets.len() as u64);
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use async_trait::async_trait;
    use chrono::Utc;
    use cymbal_proto::cymbal::path_resolution::v1::{PathResult, ResolvePathsResponse};
    use serde_json::json;
    use tonic::Code;
    use uuid::Uuid;

    use super::*;
    use crate::frames::Frame;
    use crate::types::event::AnyEvent;
    use crate::types::Exception;

    const COMMIT: &str = "0123456789abcdef0123456789abcdef01234567";

    type Reply = fn(&ResolvePathsRequest) -> Result<ResolvePathsResponse, LookupError>;

    struct FakeLookup {
        requests: Mutex<Vec<Vec<String>>>,
        reply: Reply,
    }

    #[async_trait]
    impl PathLookup for FakeLookup {
        async fn resolve_paths(
            &self,
            request: ResolvePathsRequest,
            _deadline: Instant,
        ) -> Result<ResolvePathsResponse, LookupError> {
            self.requests.lock().unwrap().push(request.paths.clone());
            (self.reply)(&request)
        }
    }

    /// Answers like the service would for a monorepo with `apps/web` and `apps/admin`.
    fn service_answers(request: &ResolvePathsRequest) -> Result<ResolvePathsResponse, LookupError> {
        let result = |outcome: Outcome, path: &str| PathResult {
            outcome: outcome as i32,
            repo_path: path.to_string(),
        };
        let results = request
            .paths
            .iter()
            .map(|path| match path.as_str() {
                "webpack://acme-web/./src/checkout/cart.ts" => {
                    result(Outcome::Sure, "apps/web/src/checkout/cart.ts")
                }
                "webpack://acme-web/./src/index.tsx" => {
                    result(Outcome::Support, "apps/web/src/index.tsx")
                }
                "webpack://acme-web/./src/shared.ts" => result(Outcome::Tie, ""),
                _ => result(Outcome::NoMatch, ""),
            })
            .collect();
        Ok(ResolvePathsResponse {
            list_state: ListState::Loaded as i32,
            results,
        })
    }

    fn context(reply: Reply) -> (RepoPathContext, Arc<FakeLookup>) {
        let lookup = Arc::new(FakeLookup {
            requests: Mutex::new(Vec::new()),
            reply,
        });
        let context = RepoPathContext {
            lookup: lookup.clone(),
            answers: AnswerCache::new(1000, Duration::from_secs(60)),
            in_flight: Arc::new(Semaphore::new(4)),
            deadline: Duration::from_secs(1),
        };
        (context, lookup)
    }

    fn frame(source: &str, in_app: bool) -> Frame {
        serde_json::from_value(json!({
            "raw_id": "abc/0",
            "mangled_name": "run",
            "in_app": in_app,
            "resolved": true,
            "lang": "javascript",
            "source": source,
        }))
        .unwrap()
    }

    fn release(remote_url: &str, commit: &str) -> ReleaseRecord {
        ReleaseRecord {
            id: Uuid::now_v7(),
            team_id: 7,
            hash_id: "shop-1".to_string(),
            created_at: Utc::now(),
            version: "1".to_string(),
            project: "shop".to_string(),
            metadata: Some(json!({"git": {"remote_url": remote_url, "commit_id": commit}})),
        }
    }

    fn event(sources: &[&str], release: Option<ReleaseRecord>) -> ExceptionEvent<Parsed> {
        let mut evt: ExceptionEvent<Parsed> = AnyEvent {
            uuid: Uuid::now_v7(),
            event: "$exception".to_string(),
            team_id: 7,
            timestamp: String::new(),
            properties: json!({"$exception_list": [{"type": "TypeError", "value": "boom"}]}),
            others: Default::default(),
        }
        .try_into()
        .unwrap();
        let mut frames: Vec<Frame> = sources.iter().map(|source| frame(source, true)).collect();
        frames.push(frame(
            "webpack://acme-web/./node_modules/react/index.js",
            false,
        ));
        evt.replace_exception_list(
            vec![Exception {
                exception_id: None,
                exception_type: "TypeError".to_string(),
                exception_message: "boom".to_string(),
                mechanism: None,
                module: None,
                thread_id: None,
                stack: Some(Stacktrace::Resolved { frames }),
            }]
            .into(),
        );
        evt.set_event_release(release);
        evt
    }

    fn github_release() -> Option<ReleaseRecord> {
        Some(release("git@github.com:acme/shop.git", COMMIT))
    }

    fn repo_paths(evt: &ExceptionEvent<Parsed>) -> Vec<Option<&str>> {
        let Some(Stacktrace::Resolved { frames }) = &evt.exception_list()[0].stack else {
            unreachable!()
        };
        frames
            .iter()
            .map(|frame| frame.repo_path.as_deref())
            .collect()
    }

    #[tokio::test]
    async fn writes_answers_and_caches_only_the_context_free_ones() {
        let (ctx, lookup) = context(service_answers);
        let sure = "webpack://acme-web/./src/checkout/cart.ts";
        let support = "webpack://acme-web/./src/index.tsx";
        let tie = "webpack://acme-web/./src/shared.ts";
        let none = "webpack://acme-web/./src/gone.ts";

        let mut first = event(&[sure, support, tie, none], github_release());
        ctx.add_repo_paths(&mut first).await;
        assert_eq!(
            repo_paths(&first),
            vec![
                Some("apps/web/src/checkout/cart.ts"),
                Some("apps/web/src/index.tsx"),
                None,
                None,
                None,
            ]
        );
        // The frame that is not in-app is never sent.
        assert_eq!(
            lookup.requests.lock().unwrap().as_slice(),
            &[vec![
                sure.to_string(),
                support.to_string(),
                tie.to_string(),
                none.to_string()
            ]]
        );

        let mut all_cached = event(&[sure, none], github_release());
        ctx.add_repo_paths(&mut all_cached).await;
        assert_eq!(
            repo_paths(&all_cached),
            vec![Some("apps/web/src/checkout/cart.ts"), None, None]
        );
        assert_eq!(lookup.requests.lock().unwrap().len(), 1);

        let mut needs_support = event(&[sure, support], github_release());
        ctx.add_repo_paths(&mut needs_support).await;
        assert_eq!(lookup.requests.lock().unwrap().len(), 2);
        assert_eq!(
            lookup.requests.lock().unwrap()[1],
            vec![sure.to_string(), support.to_string()]
        );
    }

    #[tokio::test]
    async fn failures_leave_frames_without_a_path_and_cache_nothing() {
        let replies: [(&str, Reply); 4] = [
            ("timeout", |_| Err(LookupError::Timeout)),
            ("no pods", |_| Err(LookupError::NoPods)),
            ("unauthenticated", |_| {
                Err(LookupError::Failed(Code::Unauthenticated))
            }),
            ("missing list", |_| {
                Ok(ResolvePathsResponse {
                    list_state: ListState::Missing as i32,
                    results: Vec::new(),
                })
            }),
        ];
        for (name, reply) in replies {
            let (ctx, lookup) = context(reply);
            for _ in 0..2 {
                let mut evt = event(
                    &["webpack://acme-web/./src/checkout/cart.ts"],
                    github_release(),
                );
                ctx.add_repo_paths(&mut evt).await;
                assert_eq!(repo_paths(&evt), vec![None, None], "{name}");
            }
            assert_eq!(lookup.requests.lock().unwrap().len(), 2, "{name}");
        }
    }

    #[tokio::test]
    async fn drops_a_repo_path_that_the_client_sent() {
        let mut evt = event(&["webpack://acme-web/./src/checkout/cart.ts"], None);
        if let Some(Stacktrace::Resolved { frames }) = &mut evt.exception_list_mut()[0].stack {
            frames[0].repo_path = Some("config/production.env".to_string());
        }

        let Ok(evt) = RepoPathResolver.execute_value(evt, None).await.unwrap() else {
            panic!("the operator never rejects an event");
        };

        assert_eq!(repo_paths(&evt), vec![None, None]);
    }

    #[tokio::test]
    async fn skips_events_without_a_usable_release() {
        let releases = [
            None,
            Some(release("https://github.com/acme/shop.git", "0123abc")),
            Some(release("file:///srv/git/shop.git", COMMIT)),
        ];
        for release in releases {
            let (ctx, lookup) = context(service_answers);
            let mut evt = event(&["webpack://acme-web/./src/checkout/cart.ts"], release);
            ctx.add_repo_paths(&mut evt).await;
            assert_eq!(repo_paths(&evt), vec![None, None]);
            assert!(lookup.requests.lock().unwrap().is_empty());
        }
    }
}
