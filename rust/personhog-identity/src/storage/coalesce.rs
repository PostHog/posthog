use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, LazyLock};
use std::time::Duration;

use async_trait::async_trait;
use tokio::sync::mpsc::error::TrySendError;
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::time::Instant;

use personhog_common::grpc::{CLIENT_NAME, METHOD_NAME};

use crate::storage::error::{StorageError, StorageResult};
use crate::storage::types::{AttachOutcome, DistinctIdMapping, Person, PersonStub, StubOutcome};
use crate::storage::IdentityStorage;

const CALLERS_PER_BATCH: &str = "personhog_identity_stub_create_callers_per_batch";
const QUEUE_WAIT: &str = "personhog_identity_stub_create_queue_wait_ms";
const BATCH_RERUNS: &str = "personhog_identity_stub_create_batch_reruns_total";
const REJECTED: &str = "personhog_identity_stub_create_rejected_total";

static BATCH_CLIENT: LazyLock<Arc<str>> = LazyLock::new(|| Arc::from("batched"));
static BATCH_METHOD: LazyLock<Arc<str>> = LazyLock::new(|| Arc::from("StubCreateBatch"));

type Reply = oneshot::Sender<StorageResult<Vec<StubOutcome>>>;
type Queue = Arc<Mutex<mpsc::Receiver<Pending>>>;

struct Pending {
    stubs: Vec<PersonStub>,
    enqueued_at: Instant,
    reply: Reply,
    // Set once, by the worker that starts the call or by the caller that
    // stops waiting for it, so a started call is never abandoned.
    claimed: Arc<AtomicBool>,
}

#[derive(Clone, Copy, Debug)]
pub struct CoalesceSettings {
    pub workers: usize,
    pub max_batch_distinct_ids: usize,
    pub max_queued_calls: usize,
    pub max_queue_wait: Duration,
}

pub struct CoalescingIdentityStorage {
    inner: Arc<dyn IdentityStorage>,
    queue: mpsc::Sender<Pending>,
    max_queue_wait: Duration,
}

impl CoalescingIdentityStorage {
    pub fn spawn(inner: Arc<dyn IdentityStorage>, settings: CoalesceSettings) -> Self {
        let (queue, receiver) = mpsc::channel(settings.max_queued_calls.max(1));
        let receiver: Queue = Arc::new(Mutex::new(receiver));
        for _ in 0..settings.workers.max(1) {
            tokio::spawn(run_worker(
                inner.clone(),
                receiver.clone(),
                settings.max_batch_distinct_ids.max(1),
            ));
        }
        Self {
            inner,
            queue,
            max_queue_wait: settings.max_queue_wait,
        }
    }
}

fn count_rejected(reason: &'static str) {
    common_metrics::inc(REJECTED, &[("reason".to_string(), reason.to_string())], 1);
}

#[async_trait]
impl IdentityStorage for CoalescingIdentityStorage {
    async fn resolve_distinct_ids(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), Person>> {
        self.inner.resolve_distinct_ids(keys).await
    }

    async fn resolve_person_ids(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), i64>> {
        self.inner.resolve_person_ids(keys).await
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        limit_per_person: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        self.inner
            .get_distinct_ids_for_persons(team_id, person_ids, limit_per_person)
            .await
    }

    async fn create_person_stubs(&self, stubs: &[PersonStub]) -> StorageResult<Vec<StubOutcome>> {
        if stubs.is_empty() {
            return Ok(Vec::new());
        }
        let (reply, mut outcome) = oneshot::channel();
        let claimed = Arc::new(AtomicBool::new(false));
        let enqueued_at = Instant::now();
        let pending = Pending {
            stubs: stubs.to_vec(),
            enqueued_at,
            reply,
            claimed: claimed.clone(),
        };
        match self.queue.try_send(pending) {
            Ok(()) => {}
            // The same answer a heavy-pool acquire timeout gives, so the
            // caller retries on another pod.
            Err(TrySendError::Full(_)) => {
                count_rejected("queue_full");
                return Err(StorageError::PoolExhausted);
            }
            Err(TrySendError::Closed(_)) => {
                return Err(StorageError::Connection(
                    "stub-create workers have stopped".to_string(),
                ));
            }
        }
        tokio::select! {
            result = &mut outcome => return batch_outcome(result),
            _ = tokio::time::sleep_until(enqueued_at + self.max_queue_wait) => {}
        }
        if !claimed.swap(true, Ordering::AcqRel) {
            count_rejected("queue_wait");
            return Err(StorageError::PoolExhausted);
        }
        batch_outcome(outcome.await)
    }

    async fn attach_distinct_ids(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<HashMap<String, AttachOutcome>> {
        self.inner
            .attach_distinct_ids(team_id, person_id, distinct_ids)
            .await
    }
}

fn batch_outcome(
    result: Result<StorageResult<Vec<StubOutcome>>, oneshot::error::RecvError>,
) -> StorageResult<Vec<StubOutcome>> {
    result.unwrap_or_else(|_| {
        Err(StorageError::Query(
            "stub-create batch ended without an outcome".to_string(),
        ))
    })
}

struct Batch {
    pending: Vec<Pending>,
    distinct_ids: HashSet<(i64, String)>,
}

impl Batch {
    fn new(first: Pending) -> Self {
        let keys = distinct_id_keys(&first.stubs);
        let mut batch = Self {
            pending: Vec::new(),
            distinct_ids: HashSet::new(),
        };
        batch.push(first, keys);
        batch
    }

    fn try_add(&mut self, pending: Pending, max_distinct_ids: usize) -> Result<(), Pending> {
        let keys = distinct_id_keys(&pending.stubs);
        if self.distinct_ids.len() + keys.len() > max_distinct_ids {
            return Err(pending);
        }
        if keys.iter().any(|key| self.distinct_ids.contains(key)) {
            return Err(pending);
        }
        self.push(pending, keys);
        Ok(())
    }

    fn push(&mut self, pending: Pending, keys: Vec<(i64, String)>) {
        self.distinct_ids.extend(keys);
        self.pending.push(pending);
    }
}

fn distinct_id_keys(stubs: &[PersonStub]) -> Vec<(i64, String)> {
    stubs
        .iter()
        .flat_map(|stub| {
            std::iter::once(&stub.distinct_id)
                .chain(&stub.extra_distinct_ids)
                .map(|distinct_id| (stub.team_id, distinct_id.clone()))
        })
        .collect()
}

async fn run_worker(inner: Arc<dyn IdentityStorage>, queue: Queue, max_batch_distinct_ids: usize) {
    let mut carried: Option<Pending> = None;
    loop {
        let batch = match carried.take() {
            Some(first) => {
                let mut batch = Batch::new(first);
                // An idle worker holds the lock while it waits for a call, so
                // waiting here would stall the carried call until an unrelated
                // call arrives. A carried call runs alone when the lock is busy.
                if let Ok(mut receiver) = queue.try_lock() {
                    carried = fill(&mut receiver, &mut batch, max_batch_distinct_ids);
                }
                batch
            }
            None => {
                let mut receiver = queue.lock().await;
                let Some(first) = receiver.recv().await else {
                    return;
                };
                let mut batch = Batch::new(first);
                carried = fill(&mut receiver, &mut batch, max_batch_distinct_ids);
                batch
            }
        };
        // A separate task, so that a panic fails only this batch's callers
        // and the worker keeps running.
        if let Err(e) = tokio::spawn(run_batch(inner.clone(), batch)).await {
            tracing::error!(error = %e, "stub-create batch task failed");
        }
    }
}

fn fill(
    receiver: &mut mpsc::Receiver<Pending>,
    batch: &mut Batch,
    max_batch_distinct_ids: usize,
) -> Option<Pending> {
    while batch.distinct_ids.len() < max_batch_distinct_ids {
        let Ok(next) = receiver.try_recv() else {
            return None;
        };
        if next.reply.is_closed() {
            continue;
        }
        if let Err(rejected) = batch.try_add(next, max_batch_distinct_ids) {
            return Some(rejected);
        }
    }
    None
}

async fn run_batch(inner: Arc<dyn IdentityStorage>, batch: Batch) {
    let started = Instant::now();
    let mut callers: Vec<Pending> = Vec::with_capacity(batch.pending.len());
    for pending in batch.pending {
        if pending.reply.is_closed() || pending.claimed.swap(true, Ordering::AcqRel) {
            continue;
        }
        let waited = started.duration_since(pending.enqueued_at);
        common_metrics::histogram(QUEUE_WAIT, &[], waited.as_secs_f64() * 1000.0);
        callers.push(pending);
    }
    if callers.is_empty() {
        return;
    }
    common_metrics::histogram(CALLERS_PER_BATCH, &[], callers.len() as f64);

    let stubs: Vec<PersonStub> = callers
        .iter()
        .flat_map(|pending| pending.stubs.iter().cloned())
        .collect();
    match create_with_batch_labels(&*inner, &stubs).await {
        Ok(outcomes) => {
            let mut outcomes = outcomes.into_iter();
            for pending in callers {
                let mine = outcomes.by_ref().take(pending.stubs.len()).collect();
                pending.reply.send(Ok(mine)).ok();
            }
        }
        Err(e) if callers.len() > 1 && fails_one_call(&e) => {
            // One call's rows can fail the shared transaction (a statement or
            // lock timeout, a rejected row); a rerun keeps that to its own call.
            common_metrics::inc(
                BATCH_RERUNS,
                &[("error_type".to_string(), e.error_type().to_string())],
                1,
            );
            tracing::warn!(
                error = %e,
                callers = callers.len(),
                "Coalesced stub-create transaction failed; rerunning each call alone"
            );
            for pending in callers {
                if pending.reply.is_closed() {
                    continue;
                }
                let result = create_with_batch_labels(&*inner, &pending.stubs).await;
                pending.reply.send(result).ok();
            }
        }
        Err(e) => {
            for pending in callers {
                pending.reply.send(Err(e.clone())).ok();
            }
        }
    }
}

fn fails_one_call(error: &StorageError) -> bool {
    matches!(error, StorageError::Query(_) | StorageError::Timeout { .. })
}

async fn create_with_batch_labels(
    inner: &dyn IdentityStorage,
    stubs: &[PersonStub],
) -> StorageResult<Vec<StubOutcome>> {
    let outcomes = CLIENT_NAME
        .scope(
            BATCH_CLIENT.clone(),
            METHOD_NAME.scope(BATCH_METHOD.clone(), inner.create_person_stubs(stubs)),
        )
        .await?;
    if outcomes.len() != stubs.len() {
        return Err(StorageError::Query(format!(
            "stub creation returned {} outcomes for {} stubs",
            outcomes.len(),
            stubs.len()
        )));
    }
    Ok(outcomes)
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use rstest::rstest;
    use uuid::Uuid;

    use personhog_common::persons::person_uuid;

    use super::*;

    fn stub(team_id: i64, distinct_id: &str, extras: &[&str]) -> PersonStub {
        PersonStub {
            team_id,
            distinct_id: distinct_id.to_string(),
            extra_distinct_ids: extras.iter().map(|e| e.to_string()).collect(),
            created_at: Utc::now(),
            is_identified: false,
        }
    }

    fn pending(stubs: Vec<PersonStub>) -> Pending {
        let (reply, _) = oneshot::channel();
        Pending {
            stubs,
            enqueued_at: Instant::now(),
            reply,
            claimed: Arc::new(AtomicBool::new(false)),
        }
    }

    #[rstest]
    #[case::disjoint(vec![stub(1, "a", &[])], vec![stub(1, "b", &[])], 50, true)]
    #[case::same_distinct_id_in_another_team(
        vec![stub(1, "a", &[])],
        vec![stub(2, "a", &[])],
        50,
        true
    )]
    #[case::same_primary(vec![stub(1, "a", &[])], vec![stub(1, "a", &[])], 50, false)]
    #[case::primary_is_an_extra_in_the_batch(
        vec![stub(1, "a", &["b"])],
        vec![stub(1, "b", &[])],
        50,
        false
    )]
    #[case::extra_is_a_primary_in_the_batch(
        vec![stub(1, "a", &[])],
        vec![stub(1, "b", &["a"])],
        50,
        false
    )]
    #[case::extras_go_over_the_cap(
        vec![stub(1, "a", &[])],
        vec![stub(1, "b", &["c"])],
        2,
        false
    )]
    fn a_call_joins_a_batch_only_when_disjoint_and_under_the_cap(
        #[case] in_batch: Vec<PersonStub>,
        #[case] candidate: Vec<PersonStub>,
        #[case] max_distinct_ids: usize,
        #[case] joins: bool,
    ) {
        let mut batch = Batch::new(pending(in_batch));

        assert_eq!(
            batch.try_add(pending(candidate), max_distinct_ids).is_ok(),
            joins
        );
    }

    enum Poison {
        Error(&'static str),
        Panic(&'static str),
    }

    struct ScriptedStorage {
        calls: std::sync::Mutex<Vec<Vec<String>>>,
        gate: std::sync::Mutex<Option<(oneshot::Sender<()>, oneshot::Receiver<()>)>>,
        poison: Option<Poison>,
    }

    impl ScriptedStorage {
        fn new(poison: Option<Poison>) -> Arc<Self> {
            Arc::new(Self {
                calls: std::sync::Mutex::new(Vec::new()),
                gate: std::sync::Mutex::new(None),
                poison,
            })
        }

        fn gated(
            poison: Option<Poison>,
        ) -> (Arc<Self>, oneshot::Receiver<()>, oneshot::Sender<()>) {
            let (started_tx, started_rx) = oneshot::channel();
            let (release_tx, release_rx) = oneshot::channel();
            let storage = Arc::new(Self {
                calls: std::sync::Mutex::new(Vec::new()),
                gate: std::sync::Mutex::new(Some((started_tx, release_rx))),
                poison,
            });
            (storage, started_rx, release_tx)
        }

        fn primary_ids_per_call(&self) -> Vec<Vec<String>> {
            self.calls.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl IdentityStorage for ScriptedStorage {
        async fn resolve_distinct_ids(
            &self,
            _keys: &[(i64, String)],
        ) -> StorageResult<HashMap<(i64, String), Person>> {
            unimplemented!()
        }

        async fn resolve_person_ids(
            &self,
            _keys: &[(i64, String)],
        ) -> StorageResult<HashMap<(i64, String), i64>> {
            unimplemented!()
        }

        async fn get_distinct_ids_for_persons(
            &self,
            _team_id: i64,
            _person_ids: &[i64],
            _limit_per_person: Option<i64>,
        ) -> StorageResult<Vec<DistinctIdMapping>> {
            unimplemented!()
        }

        async fn create_person_stubs(
            &self,
            stubs: &[PersonStub],
        ) -> StorageResult<Vec<StubOutcome>> {
            self.calls
                .lock()
                .unwrap()
                .push(stubs.iter().map(|s| s.distinct_id.clone()).collect());
            let gate = self.gate.lock().unwrap().take();
            if let Some((started, release)) = gate {
                started.send(()).unwrap();
                release.await.unwrap();
            }
            let carries = |poisoned: &str| stubs.iter().any(|s| s.distinct_id == poisoned);
            match self.poison {
                Some(Poison::Error(poisoned)) if carries(poisoned) => {
                    return Err(StorageError::Query("deadlock detected".to_string()));
                }
                Some(Poison::Panic(poisoned)) if carries(poisoned) => {
                    panic!("scripted panic");
                }
                _ => {}
            }
            Ok(stubs
                .iter()
                .map(|s| StubOutcome::Committed {
                    person: Person {
                        id: 1,
                        uuid: person_uuid(s.team_id, &s.distinct_id),
                        team_id: s.team_id,
                        properties: None,
                        created_at: s.created_at,
                        version: Some(0),
                        is_identified: s.is_identified,
                        is_user_id: None,
                        last_seen_at: None,
                    },
                    created: true,
                })
                .collect())
        }

        async fn attach_distinct_ids(
            &self,
            _team_id: i64,
            _person_id: i64,
            _distinct_ids: &[String],
        ) -> StorageResult<HashMap<String, AttachOutcome>> {
            unimplemented!()
        }
    }

    fn settings(workers: usize) -> CoalesceSettings {
        CoalesceSettings {
            workers,
            max_batch_distinct_ids: 50,
            max_queued_calls: 100,
            max_queue_wait: Duration::from_secs(60),
        }
    }

    fn uuids(result: &StorageResult<Vec<StubOutcome>>) -> Vec<Uuid> {
        result
            .as_ref()
            .expect("call should succeed")
            .iter()
            .map(|outcome| match outcome {
                StubOutcome::Committed { person, .. } => person.uuid,
                StubOutcome::LostRace => panic!("unexpected lost race"),
            })
            .collect()
    }

    async fn run_behind_a_busy_worker(
        storage: &CoalescingIdentityStorage,
        started_rx: oneshot::Receiver<()>,
        release_tx: oneshot::Sender<()>,
        first: &[PersonStub],
        queued: &[Vec<PersonStub>],
    ) -> Vec<StorageResult<Vec<StubOutcome>>> {
        let mut calls = vec![storage.create_person_stubs(first)];
        assert!(futures::poll!(&mut calls[0]).is_pending());
        started_rx.await.unwrap();
        for stubs in queued {
            let mut call = storage.create_person_stubs(stubs);
            assert!(futures::poll!(&mut call).is_pending());
            calls.push(call);
        }
        release_tx.send(()).unwrap();
        futures::future::join_all(calls).await
    }

    #[tokio::test]
    async fn calls_queued_behind_a_busy_worker_share_one_transaction() {
        let (inner, started_rx, release_tx) = ScriptedStorage::gated(None);
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), settings(1));
        let queued = vec![
            vec![stub(1, "b", &[]), stub(1, "b2", &[])],
            vec![stub(1, "c", &[])],
        ];

        let results = run_behind_a_busy_worker(
            &storage,
            started_rx,
            release_tx,
            &[stub(1, "a", &[])],
            &queued,
        )
        .await;

        assert_eq!(
            inner.primary_ids_per_call(),
            vec![vec!["a"], vec!["b", "b2", "c"]]
        );
        assert_eq!(
            results.iter().map(uuids).collect::<Vec<_>>(),
            vec![
                vec![person_uuid(1, "a")],
                vec![person_uuid(1, "b"), person_uuid(1, "b2")],
                vec![person_uuid(1, "c")],
            ]
        );
    }

    #[tokio::test]
    async fn a_failed_batch_reruns_each_call_alone() {
        let (inner, started_rx, release_tx) =
            ScriptedStorage::gated(Some(Poison::Error("poisoned")));
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), settings(1));
        let queued = vec![
            vec![stub(1, "b", &[])],
            vec![stub(1, "poisoned", &[])],
            vec![stub(1, "c", &[])],
        ];

        let results = run_behind_a_busy_worker(
            &storage,
            started_rx,
            release_tx,
            &[stub(1, "a", &[])],
            &queued,
        )
        .await;

        assert_eq!(
            inner.primary_ids_per_call(),
            vec![
                vec!["a"],
                vec!["b", "poisoned", "c"],
                vec!["b"],
                vec!["poisoned"],
                vec!["c"],
            ]
        );
        assert_eq!(uuids(&results[1]), vec![person_uuid(1, "b")]);
        assert!(matches!(results[2], Err(StorageError::Query(_))));
        assert_eq!(uuids(&results[3]), vec![person_uuid(1, "c")]);
    }

    #[tokio::test]
    async fn a_panicking_batch_fails_its_callers_and_the_worker_keeps_running() {
        let inner = ScriptedStorage::new(Some(Poison::Panic("boom")));
        let storage = CoalescingIdentityStorage::spawn(inner, settings(1));

        let panicked = storage.create_person_stubs(&[stub(1, "boom", &[])]).await;
        let after = storage.create_person_stubs(&[stub(1, "a", &[])]).await;

        assert!(matches!(panicked, Err(StorageError::Query(_))));
        assert_eq!(uuids(&after), vec![person_uuid(1, "a")]);
    }

    // The paused clock makes the timeout fire as soon as every task is idle,
    // so a stalled call fails the test at once instead of hanging it.
    #[tokio::test(start_paused = true)]
    async fn a_carried_call_runs_while_another_worker_waits_for_calls() {
        let (inner, started_rx, release_tx) = ScriptedStorage::gated(None);
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), settings(2));
        let same_key = vec![stub(1, "a", &[])];

        let mut first = storage.create_person_stubs(&same_key);
        let mut second = storage.create_person_stubs(&same_key);
        assert!(futures::poll!(&mut first).is_pending());
        assert!(futures::poll!(&mut second).is_pending());
        started_rx.await.unwrap();
        release_tx.send(()).unwrap();

        let second = tokio::time::timeout(std::time::Duration::from_secs(1), second).await;
        assert!(
            second.is_ok(),
            "the carried call stalled behind the idle worker"
        );
        first.await.unwrap();
        assert_eq!(inner.primary_ids_per_call(), vec![vec!["a"], vec!["a"]]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_full_queue_refuses_new_calls_at_once() {
        let (inner, started_rx, release_tx) = ScriptedStorage::gated(None);
        let storage = CoalescingIdentityStorage::spawn(
            inner.clone(),
            CoalesceSettings {
                max_queued_calls: 1,
                ..settings(1)
            },
        );
        let (a, b, c) = (
            vec![stub(1, "a", &[])],
            vec![stub(1, "b", &[])],
            vec![stub(1, "c", &[])],
        );

        let mut running = storage.create_person_stubs(&a);
        assert!(futures::poll!(&mut running).is_pending());
        started_rx.await.unwrap();
        let mut queued = storage.create_person_stubs(&b);
        assert!(futures::poll!(&mut queued).is_pending());
        let refused =
            tokio::time::timeout(Duration::from_secs(1), storage.create_person_stubs(&c)).await;
        release_tx.send(()).unwrap();

        assert!(matches!(refused, Ok(Err(StorageError::PoolExhausted))));
        assert_eq!(uuids(&queued.await), vec![person_uuid(1, "b")]);
        running.await.unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn a_call_that_waits_past_the_queue_timeout_is_refused_without_running() {
        let (inner, started_rx, release_tx) = ScriptedStorage::gated(None);
        let storage = CoalescingIdentityStorage::spawn(
            inner.clone(),
            CoalesceSettings {
                max_queue_wait: Duration::from_secs(1),
                ..settings(1)
            },
        );
        let (a, b) = (vec![stub(1, "a", &[])], vec![stub(1, "b", &[])]);

        let mut running = storage.create_person_stubs(&a);
        assert!(futures::poll!(&mut running).is_pending());
        started_rx.await.unwrap();
        let mut expired = storage.create_person_stubs(&b);
        assert!(futures::poll!(&mut expired).is_pending());
        tokio::time::advance(Duration::from_secs(2)).await;
        let refused = tokio::time::timeout(Duration::from_secs(60), expired).await;
        release_tx.send(()).unwrap();

        assert!(matches!(refused, Ok(Err(StorageError::PoolExhausted))));
        running.await.unwrap();
        assert_eq!(inner.primary_ids_per_call(), vec![vec!["a"]]);
    }
}
