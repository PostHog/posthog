use std::time::Duration;

use moka::sync::Cache;

/// Answers that depend only on the path and the commit: a sure match (`Some`) or no match (`None`).
/// Answers chosen by the other frames of a request (support, tie) must never be stored here.
#[derive(Clone)]
pub struct AnswerCache {
    answers: Cache<String, Option<String>>,
}

impl AnswerCache {
    pub fn new(max_entries: u64, ttl: Duration) -> Self {
        Self {
            answers: Cache::builder()
                .max_capacity(max_entries)
                .time_to_live(ttl)
                .build(),
        }
    }

    /// `None` when unknown, `Some(None)` for a known non-match.
    pub fn get(
        &self,
        team_id: i32,
        repo: &str,
        commit: &str,
        path: &str,
    ) -> Option<Option<String>> {
        self.answers.get(&key(team_id, repo, commit, path))
    }

    pub fn insert(
        &self,
        team_id: i32,
        repo: &str,
        commit: &str,
        path: &str,
        answer: Option<String>,
    ) {
        self.answers
            .insert(key(team_id, repo, commit, path), answer);
    }
}

fn key(team_id: i32, repo: &str, commit: &str, path: &str) -> String {
    format!("{team_id}\0{repo}\0{commit}\0{path}")
}
