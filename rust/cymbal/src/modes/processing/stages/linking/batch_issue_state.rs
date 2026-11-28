use std::{
    cmp::Ordering,
    collections::HashMap,
    future::Future,
    sync::{Arc, Mutex},
};

use moka::future::{Cache, CacheBuilder};
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    issue_resolution::{Issue, IssueStatus},
};

/// The newest copy of each issue that one batch has written.
///
/// Events of a fingerprint share the issue loaded once for the batch, and the batch's release writes
/// move that issue on. This type owns those moves:
///
/// - `current` returns the newest copy this batch wrote, or the loaded copy before any write.
/// - `apply_write` runs a write at most once per issue and release. Concurrent callers of the same
///   pair share one write. A failed write is not remembered, so the next caller retries it.
/// - A write that finishes late never replaces a newer copy. Copies are ordered by the latest
///   release they record, which ingestion only moves forward, and on the same release by the reopen,
///   which ingestion never undoes.
/// - Every caller gets `current` once the write is done, not the copy that write returned, so no
///   caller reads a copy that another write of the batch has already superseded.
#[derive(Clone)]
pub struct BatchIssueState {
    writes: Cache<(Uuid, Option<Uuid>), ()>,
    newest: Arc<Mutex<HashMap<Uuid, Issue>>>,
}

impl Default for BatchIssueState {
    fn default() -> Self {
        Self {
            writes: CacheBuilder::new(10_000).build(),
            newest: Default::default(),
        }
    }
}

impl BatchIssueState {
    pub fn current(&self, loaded: Issue) -> Issue {
        self.newest
            .lock()
            .expect("batch issue state mutex poisoned")
            .get(&loaded.id)
            .cloned()
            .unwrap_or(loaded)
    }

    pub async fn apply_write<W, F>(
        &self,
        issue: Issue,
        release_id: Option<Uuid>,
        write: W,
    ) -> Result<Issue, UnhandledError>
    where
        W: FnOnce(Issue) -> F,
        F: Future<Output = Result<Issue, UnhandledError>>,
    {
        let issue_id = issue.id;
        let state = self.clone();
        self.writes
            .try_get_with((issue_id, release_id), async move {
                let written = write(issue).await?;
                state.record(written);
                Ok::<(), UnhandledError>(())
            })
            .await
            .map_err(|e: Arc<UnhandledError>| UnhandledError::Other(e.to_string()))?;
        Ok(self
            .newest
            .lock()
            .expect("batch issue state mutex poisoned")
            .get(&issue_id)
            .cloned()
            .expect("a finished write records its issue"))
    }

    fn record(&self, written: Issue) {
        let mut newest = self
            .newest
            .lock()
            .expect("batch issue state mutex poisoned");
        match newest.get(&written.id) {
            Some(known) if !supersedes(&written, known) => {}
            _ => {
                newest.insert(written.id, written);
            }
        }
    }
}

fn supersedes(candidate: &Issue, known: &Issue) -> bool {
    match candidate
        .latest_release_created_at
        .cmp(&known.latest_release_created_at)
    {
        Ordering::Greater => true,
        Ordering::Less => false,
        Ordering::Equal => {
            candidate.status == IssueStatus::Active && known.status != IssueStatus::Active
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering as AtomicOrdering};

    use chrono::{DateTime, TimeZone, Utc};
    use tokio::sync::oneshot;

    use super::*;

    fn issue(id: Uuid, status: IssueStatus, release_day: Option<u32>) -> Issue {
        let release_created_at: Option<DateTime<Utc>> =
            release_day.map(|day| Utc.with_ymd_and_hms(2026, 3, day, 12, 0, 0).unwrap());
        Issue {
            id,
            team_id: 1,
            status,
            severity: None,
            name: None,
            description: None,
            created_at: Utc.with_ymd_and_hms(2026, 3, 1, 0, 0, 0).unwrap(),
            resolved_until: None,
            latest_release_id: release_day.map(|_| Uuid::now_v7()),
            latest_release_created_at: release_created_at,
        }
    }

    #[tokio::test]
    async fn a_write_that_finishes_late_never_replaces_a_newer_copy() {
        let id = Uuid::now_v7();
        let loaded = issue(id, IssueStatus::Resolved, Some(1));
        for older_finishes_last in [true, false] {
            let state = BatchIssueState::default();
            let (finish_older, older_may_finish) = oneshot::channel::<()>();
            let older = state.apply_write(loaded.clone(), Some(Uuid::now_v7()), |_| async move {
                older_may_finish.await.unwrap();
                Ok(issue(id, IssueStatus::Active, Some(2)))
            });
            let newer = state.apply_write(loaded.clone(), Some(Uuid::now_v7()), |_| async {
                Ok(issue(id, IssueStatus::Active, Some(3)))
            });
            let (older, newer) = if older_finishes_last {
                let newer = newer.await.unwrap();
                finish_older.send(()).unwrap();
                (older.await.unwrap(), newer)
            } else {
                finish_older.send(()).unwrap();
                let older = older.await.unwrap();
                (older, newer.await.unwrap())
            };

            let day = |issue: &Issue| issue.latest_release_created_at;
            let latest = Some(Utc.with_ymd_and_hms(2026, 3, 3, 12, 0, 0).unwrap());
            assert_eq!(day(&state.current(loaded.clone())), latest);
            assert_eq!(day(&newer), latest);
            if older_finishes_last {
                // The caller of the older write gets the newer copy, not the one its write returned.
                assert_eq!(day(&older), latest);
            }
        }
    }

    #[test]
    fn on_the_same_release_a_reopen_wins_in_either_order() {
        let id = Uuid::now_v7();
        for reopen_first in [true, false] {
            let state = BatchIssueState::default();
            let copies = [
                issue(id, IssueStatus::Active, Some(2)),
                issue(id, IssueStatus::Resolved, Some(2)),
            ];
            let order = if reopen_first { [0, 1] } else { [1, 0] };
            for index in order {
                state.record(copies[index].clone());
            }
            assert_eq!(
                state
                    .current(issue(id, IssueStatus::Resolved, Some(1)))
                    .status,
                IssueStatus::Active
            );
        }
    }

    #[tokio::test]
    async fn callers_of_one_write_share_it_and_a_failed_write_is_retried() {
        let id = Uuid::now_v7();
        let release_id = Some(Uuid::now_v7());
        let loaded = issue(id, IssueStatus::Resolved, Some(1));
        let state = BatchIssueState::default();
        let runs = Arc::new(AtomicUsize::new(0));
        let write = |runs: Arc<AtomicUsize>, fail: bool| {
            move |_: Issue| async move {
                runs.fetch_add(1, AtomicOrdering::SeqCst);
                if fail {
                    Err(UnhandledError::Other("write failed".to_string()))
                } else {
                    Ok(issue(id, IssueStatus::Active, Some(2)))
                }
            }
        };

        let failed = state
            .apply_write(loaded.clone(), release_id, write(runs.clone(), true))
            .await;
        let (first, second) = tokio::join!(
            state.apply_write(loaded.clone(), release_id, write(runs.clone(), false)),
            state.apply_write(loaded.clone(), release_id, write(runs.clone(), false)),
        );

        assert!(failed.is_err());
        assert_eq!(first.unwrap().status, IssueStatus::Active);
        assert_eq!(second.unwrap().status, IssueStatus::Active);
        assert_eq!(runs.load(AtomicOrdering::SeqCst), 2);
    }
}
