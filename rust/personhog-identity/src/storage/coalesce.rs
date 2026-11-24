use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, LazyLock};
use std::time::Duration;

use async_trait::async_trait;
use futures::future::join_all;
use tokio::sync::mpsc::error::TrySendError;
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::time::Instant;

use personhog_common::grpc::{CLIENT_NAME, METHOD_NAME};

use crate::storage::error::{StorageError, StorageResult};
use crate::storage::types::{
    AttachOutcome, DistinctIdMapping, Person, PersonAttach, PersonStub, StubOutcome,
};
use crate::storage::IdentityStorage;

static BATCH_CLIENT: LazyLock<Arc<str>> = LazyLock::new(|| Arc::from("batched"));

#[async_trait]
trait CoalescedWrite: Send + Sync + 'static {
    type Item: Clone + Send + Sync + 'static;
    type Outcome: Send + 'static;

    const NAME: &'static str;
    const CALLERS_PER_BATCH: &'static str;
    const QUEUE_WAIT: &'static str;
    const BATCH_RERUNS: &'static str;
    const REJECTED: &'static str;

    fn batch_method() -> Arc<str>;

    fn distinct_id_keys(items: &[Self::Item]) -> Vec<(i64, String)>;

    async fn write(
        inner: &dyn IdentityStorage,
        items: &[Self::Item],
    ) -> StorageResult<Vec<Self::Outcome>>;
}

struct StubCreates;

#[async_trait]
impl CoalescedWrite for StubCreates {
    type Item = PersonStub;
    type Outcome = StubOutcome;

    const NAME: &'static str = "stub-create";
    const CALLERS_PER_BATCH: &'static str = "personhog_identity_stub_create_callers_per_batch";
    const QUEUE_WAIT: &'static str = "personhog_identity_stub_create_queue_wait_ms";
    const BATCH_RERUNS: &'static str = "personhog_identity_stub_create_batch_reruns_total";
    const REJECTED: &'static str = "personhog_identity_stub_create_rejected_total";

    fn batch_method() -> Arc<str> {
        static METHOD: LazyLock<Arc<str>> = LazyLock::new(|| Arc::from("StubCreateBatch"));
        METHOD.clone()
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

    async fn write(
        inner: &dyn IdentityStorage,
        stubs: &[PersonStub],
    ) -> StorageResult<Vec<StubOutcome>> {
        inner.create_person_stubs(stubs).await
    }
}

struct Attaches;

#[async_trait]
impl CoalescedWrite for Attaches {
    type Item = PersonAttach;
    type Outcome = HashMap<String, AttachOutcome>;

    const NAME: &'static str = "attach";
    const CALLERS_PER_BATCH: &'static str = "personhog_identity_attach_callers_per_batch";
    const QUEUE_WAIT: &'static str = "personhog_identity_attach_queue_wait_ms";
    const BATCH_RERUNS: &'static str = "personhog_identity_attach_batch_reruns_total";
    const REJECTED: &'static str = "personhog_identity_attach_rejected_total";

    fn batch_method() -> Arc<str> {
        static METHOD: LazyLock<Arc<str>> = LazyLock::new(|| Arc::from("AttachBatch"));
        METHOD.clone()
    }

    fn distinct_id_keys(attaches: &[PersonAttach]) -> Vec<(i64, String)> {
        attaches
            .iter()
            .flat_map(|attach| {
                attach
                    .distinct_ids
                    .iter()
                    .map(|distinct_id| (attach.team_id, distinct_id.clone()))
            })
            .collect()
    }

    async fn write(
        inner: &dyn IdentityStorage,
        attaches: &[PersonAttach],
    ) -> StorageResult<Vec<HashMap<String, AttachOutcome>>> {
        inner.attach_distinct_ids_batch(attaches).await
    }
}

type Reply<W> = oneshot::Sender<StorageResult<Vec<<W as CoalescedWrite>::Outcome>>>;
type Queue<W> = Arc<Mutex<mpsc::Receiver<Pending<W>>>>;

struct Pending<W: CoalescedWrite> {
    items: Vec<W::Item>,
    enqueued_at: Instant,
    reply: Reply<W>,
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
    pub batch_wait: Duration,
}

struct Coalescer<W: CoalescedWrite> {
    queue: mpsc::Sender<Pending<W>>,
    max_queue_wait: Duration,
}

impl<W: CoalescedWrite> Coalescer<W> {
    fn spawn(inner: Arc<dyn IdentityStorage>, settings: CoalesceSettings) -> Self {
        let (queue, receiver) = mpsc::channel(settings.max_queued_calls.max(1));
        let receiver: Queue<W> = Arc::new(Mutex::new(receiver));
        for _ in 0..settings.workers.max(1) {
            tokio::spawn(run_worker::<W>(
                inner.clone(),
                receiver.clone(),
                settings.max_batch_distinct_ids.max(1),
                settings.batch_wait,
            ));
        }
        Self {
            queue,
            max_queue_wait: settings.max_queue_wait,
        }
    }

    async fn call(&self, items: Vec<W::Item>) -> StorageResult<Vec<W::Outcome>> {
        let (reply, mut outcome) = oneshot::channel();
        let claimed = Arc::new(AtomicBool::new(false));
        let enqueued_at = Instant::now();
        let pending = Pending::<W> {
            items,
            enqueued_at,
            reply,
            claimed: claimed.clone(),
        };
        match self.queue.try_send(pending) {
            Ok(()) => {}
            // The same answer a heavy-pool acquire timeout gives, so the
            // caller retries on another pod.
            Err(TrySendError::Full(_)) => {
                count_rejected::<W>("queue_full");
                return Err(StorageError::PoolExhausted);
            }
            Err(TrySendError::Closed(_)) => {
                return Err(StorageError::Connection(format!(
                    "{} workers have stopped",
                    W::NAME
                )));
            }
        }
        tokio::select! {
            result = &mut outcome => return batch_outcome::<W>(result),
            _ = tokio::time::sleep_until(enqueued_at + self.max_queue_wait) => {}
        }
        if !claimed.swap(true, Ordering::AcqRel) {
            count_rejected::<W>("queue_wait");
            return Err(StorageError::PoolExhausted);
        }
        batch_outcome::<W>(outcome.await)
    }
}

pub struct CoalescingIdentityStorage {
    inner: Arc<dyn IdentityStorage>,
    stub_creates: Option<Coalescer<StubCreates>>,
    attaches: Option<Coalescer<Attaches>>,
}

impl CoalescingIdentityStorage {
    pub fn spawn(
        inner: Arc<dyn IdentityStorage>,
        stub_creates: Option<CoalesceSettings>,
        attaches: Option<CoalesceSettings>,
    ) -> Self {
        Self {
            stub_creates: stub_creates.map(|settings| Coalescer::spawn(inner.clone(), settings)),
            attaches: attaches.map(|settings| Coalescer::spawn(inner.clone(), settings)),
            inner,
        }
    }
}

fn count_rejected<W: CoalescedWrite>(reason: &'static str) {
    common_metrics::inc(
        W::REJECTED,
        &[("reason".to_string(), reason.to_string())],
        1,
    );
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
        match &self.stub_creates {
            Some(coalescer) => coalescer.call(stubs.to_vec()).await,
            None => self.inner.create_person_stubs(stubs).await,
        }
    }

    async fn attach_distinct_ids(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<HashMap<String, AttachOutcome>> {
        if distinct_ids.is_empty() {
            return Ok(HashMap::new());
        }
        let Some(coalescer) = &self.attaches else {
            return self
                .inner
                .attach_distinct_ids(team_id, person_id, distinct_ids)
                .await;
        };
        let attach = PersonAttach {
            team_id,
            person_id,
            distinct_ids: distinct_ids.to_vec(),
        };
        coalescer
            .call(vec![attach])
            .await?
            .pop()
            .ok_or_else(|| StorageError::Query("attach batch returned no outcome".to_string()))
    }

    async fn attach_distinct_ids_batch(
        &self,
        attaches: &[PersonAttach],
    ) -> StorageResult<Vec<HashMap<String, AttachOutcome>>> {
        self.inner.attach_distinct_ids_batch(attaches).await
    }
}

fn batch_outcome<W: CoalescedWrite>(
    result: Result<StorageResult<Vec<W::Outcome>>, oneshot::error::RecvError>,
) -> StorageResult<Vec<W::Outcome>> {
    result.unwrap_or_else(|_| {
        Err(StorageError::Query(format!(
            "{} batch ended without an outcome",
            W::NAME
        )))
    })
}

struct Batch<W: CoalescedWrite> {
    pending: Vec<Pending<W>>,
    distinct_ids: HashSet<(i64, String)>,
}

impl<W: CoalescedWrite> Batch<W> {
    fn new(first: Pending<W>) -> Self {
        let keys = W::distinct_id_keys(&first.items);
        let mut batch = Self {
            pending: Vec::new(),
            distinct_ids: HashSet::new(),
        };
        batch.push(first, keys);
        batch
    }

    fn try_add(&mut self, pending: Pending<W>, max_distinct_ids: usize) -> Result<(), Pending<W>> {
        let keys = W::distinct_id_keys(&pending.items);
        if self.distinct_ids.len() + keys.len() > max_distinct_ids {
            return Err(pending);
        }
        if keys.iter().any(|key| self.distinct_ids.contains(key)) {
            return Err(pending);
        }
        self.push(pending, keys);
        Ok(())
    }

    fn push(&mut self, pending: Pending<W>, keys: Vec<(i64, String)>) {
        self.distinct_ids.extend(keys);
        self.pending.push(pending);
    }
}

async fn run_worker<W: CoalescedWrite>(
    inner: Arc<dyn IdentityStorage>,
    queue: Queue<W>,
    max_batch_distinct_ids: usize,
    batch_wait: Duration,
) {
    let mut carried: Option<Pending<W>> = None;
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
                // The wait counts from when the first call was queued, so a
                // call that already waited behind a busy worker is not
                // delayed a second time.
                let deadline = first.enqueued_at + batch_wait;
                let mut batch = Batch::new(first);
                carried = fill(&mut receiver, &mut batch, max_batch_distinct_ids);
                while carried.is_none() && batch.distinct_ids.len() < max_batch_distinct_ids {
                    let Ok(Some(next)) = tokio::time::timeout_at(deadline, receiver.recv()).await
                    else {
                        break;
                    };
                    if next.reply.is_closed() {
                        continue;
                    }
                    carried = batch.try_add(next, max_batch_distinct_ids).err();
                }
                batch
            }
        };
        // A separate task, so that a panic fails only this batch's callers
        // and the worker keeps running.
        if let Err(e) = tokio::spawn(run_batch(inner.clone(), batch)).await {
            tracing::error!(error = %e, "{} batch task failed", W::NAME);
        }
    }
}

fn fill<W: CoalescedWrite>(
    receiver: &mut mpsc::Receiver<Pending<W>>,
    batch: &mut Batch<W>,
    max_batch_distinct_ids: usize,
) -> Option<Pending<W>> {
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

async fn run_batch<W: CoalescedWrite>(inner: Arc<dyn IdentityStorage>, batch: Batch<W>) {
    let started = Instant::now();
    let mut callers: Vec<Pending<W>> = Vec::with_capacity(batch.pending.len());
    for pending in batch.pending {
        if pending.reply.is_closed() || pending.claimed.swap(true, Ordering::AcqRel) {
            continue;
        }
        let waited = started.duration_since(pending.enqueued_at);
        common_metrics::histogram(W::QUEUE_WAIT, &[], waited.as_secs_f64() * 1000.0);
        callers.push(pending);
    }
    if callers.is_empty() {
        return;
    }
    common_metrics::histogram(W::CALLERS_PER_BATCH, &[], callers.len() as f64);

    let items: Vec<W::Item> = callers
        .iter()
        .flat_map(|pending| pending.items.iter().cloned())
        .collect();
    match write_with_batch_labels::<W>(&*inner, &items).await {
        Ok(outcomes) => {
            let mut outcomes = outcomes.into_iter();
            for pending in callers {
                let mine = outcomes.by_ref().take(pending.items.len()).collect();
                pending.reply.send(Ok(mine)).ok();
            }
        }
        Err(e) if callers.len() > 1 && fails_one_call(&e) => {
            // One call's rows can fail the shared transaction (a statement or
            // lock timeout, a rejected row); a rerun keeps that to its own call.
            common_metrics::inc(
                W::BATCH_RERUNS,
                &[("error_type".to_string(), e.error_type().to_string())],
                1,
            );
            tracing::warn!(
                error = %e,
                callers = callers.len(),
                "Coalesced {} transaction failed; rerunning each call alone",
                W::NAME
            );
            let reruns = callers
                .into_iter()
                .filter(|pending| !pending.reply.is_closed())
                .map(|pending| {
                    let inner = &*inner;
                    async move {
                        let result = write_with_batch_labels::<W>(inner, &pending.items).await;
                        pending.reply.send(result).ok();
                    }
                });
            join_all(reruns).await;
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

async fn write_with_batch_labels<W: CoalescedWrite>(
    inner: &dyn IdentityStorage,
    items: &[W::Item],
) -> StorageResult<Vec<W::Outcome>> {
    let outcomes = CLIENT_NAME
        .scope(
            BATCH_CLIENT.clone(),
            METHOD_NAME.scope(W::batch_method(), W::write(inner, items)),
        )
        .await?;
    if outcomes.len() != items.len() {
        return Err(StorageError::Query(format!(
            "{} returned {} outcomes for {} items",
            W::NAME,
            outcomes.len(),
            items.len()
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

    fn pending(stubs: Vec<PersonStub>) -> Pending<StubCreates> {
        let (reply, _) = oneshot::channel();
        Pending {
            items: stubs,
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
        held: std::sync::Mutex<Option<(&'static str, oneshot::Receiver<()>)>>,
    }

    impl ScriptedStorage {
        fn new(poison: Option<Poison>) -> Arc<Self> {
            Arc::new(Self {
                calls: std::sync::Mutex::new(Vec::new()),
                gate: std::sync::Mutex::new(None),
                poison,
                held: std::sync::Mutex::new(None),
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
                held: std::sync::Mutex::new(None),
            });
            (storage, started_rx, release_tx)
        }

        fn hold_lone(&self, distinct_id: &'static str) -> oneshot::Sender<()> {
            let (release_tx, release_rx) = oneshot::channel();
            *self.held.lock().unwrap() = Some((distinct_id, release_rx));
            release_tx
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
            let held = {
                let mut held = self.held.lock().unwrap();
                match held.as_ref() {
                    Some((id, _)) if stubs.len() == 1 && stubs[0].distinct_id == *id => held.take(),
                    _ => None,
                }
            };
            if let Some((_, release)) = held {
                release.await.unwrap();
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

        async fn attach_distinct_ids_batch(
            &self,
            attaches: &[PersonAttach],
        ) -> StorageResult<Vec<HashMap<String, AttachOutcome>>> {
            self.calls.lock().unwrap().push(
                attaches
                    .iter()
                    .flat_map(|a| a.distinct_ids.iter().cloned())
                    .collect(),
            );
            let gate = self.gate.lock().unwrap().take();
            if let Some((started, release)) = gate {
                started.send(()).unwrap();
                release.await.unwrap();
            }
            Ok(attaches
                .iter()
                .map(|a| {
                    a.distinct_ids
                        .iter()
                        .map(|d| {
                            let owner = AttachOutcome::AlreadyMapped {
                                person_id: a.person_id,
                            };
                            (d.clone(), owner)
                        })
                        .collect()
                })
                .collect())
        }
    }

    fn settings(workers: usize) -> CoalesceSettings {
        CoalesceSettings {
            workers,
            max_batch_distinct_ids: 50,
            max_queued_calls: 100,
            max_queue_wait: Duration::from_secs(60),
            batch_wait: Duration::ZERO,
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
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), Some(settings(1)), None);
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

    fn owners(result: &StorageResult<HashMap<String, AttachOutcome>>) -> Vec<(String, i64)> {
        let mut owners: Vec<(String, i64)> = result
            .as_ref()
            .expect("call should succeed")
            .iter()
            .map(|(distinct_id, outcome)| match outcome {
                AttachOutcome::AlreadyMapped { person_id } => (distinct_id.clone(), *person_id),
                AttachOutcome::Attached { .. } => panic!("the scripted storage never attaches"),
            })
            .collect();
        owners.sort();
        owners
    }

    #[tokio::test]
    async fn attaches_queued_behind_a_busy_worker_share_one_statement() {
        let (inner, started_rx, release_tx) = ScriptedStorage::gated(None);
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), None, Some(settings(1)));
        let ids = |ids: &[&str]| ids.iter().map(|d| d.to_string()).collect::<Vec<_>>();
        let first = ids(&["a"]);
        let queued = [
            (20, ids(&["b", "b2"])),
            (30, ids(&["c"])),
            (40, ids(&["b"])),
        ];

        let mut running = storage.attach_distinct_ids(1, 10, &first);
        assert!(futures::poll!(&mut running).is_pending());
        started_rx.await.unwrap();
        let mut calls = Vec::new();
        for (person_id, distinct_ids) in &queued {
            let mut call = storage.attach_distinct_ids(1, *person_id, distinct_ids);
            assert!(futures::poll!(&mut call).is_pending());
            calls.push(call);
        }
        release_tx.send(()).unwrap();
        let results = futures::future::join_all(calls).await;

        assert_eq!(owners(&running.await), vec![("a".to_string(), 10)]);
        assert_eq!(
            inner.primary_ids_per_call(),
            vec![vec!["a"], vec!["b", "b2", "c"], vec!["b"]]
        );
        assert_eq!(
            results.iter().map(owners).collect::<Vec<_>>(),
            vec![
                vec![("b".to_string(), 20), ("b2".to_string(), 20)],
                vec![("c".to_string(), 30)],
                vec![("b".to_string(), 40)],
            ]
        );
    }

    #[tokio::test]
    async fn a_failed_batch_reruns_each_call_alone() {
        let (inner, started_rx, release_tx) =
            ScriptedStorage::gated(Some(Poison::Error("poisoned")));
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), Some(settings(1)), None);
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

    #[tokio::test(start_paused = true)]
    async fn a_rerun_that_blocks_does_not_hold_back_the_other_reruns() {
        let (inner, started_rx, release_tx) =
            ScriptedStorage::gated(Some(Poison::Error("poisoned")));
        let unblock = inner.hold_lone("held");
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), Some(settings(1)), None);
        let (first, held, poisoned, free) = (
            vec![stub(1, "a", &[])],
            vec![stub(1, "held", &[])],
            vec![stub(1, "poisoned", &[])],
            vec![stub(1, "free", &[])],
        );

        let mut running = storage.create_person_stubs(&first);
        assert!(futures::poll!(&mut running).is_pending());
        started_rx.await.unwrap();
        let mut blocked = storage.create_person_stubs(&held);
        let mut failing = storage.create_person_stubs(&poisoned);
        let mut healthy = storage.create_person_stubs(&free);
        assert!(futures::poll!(&mut blocked).is_pending());
        assert!(futures::poll!(&mut failing).is_pending());
        assert!(futures::poll!(&mut healthy).is_pending());
        release_tx.send(()).unwrap();
        running.await.unwrap();

        let healthy = tokio::time::timeout(Duration::from_secs(1), healthy).await;
        assert_eq!(
            uuids(&healthy.expect("the healthy rerun waited behind the held one")),
            vec![person_uuid(1, "free")]
        );
        assert!(matches!(failing.await, Err(StorageError::Query(_))));
        unblock.send(()).unwrap();
        assert_eq!(uuids(&blocked.await), vec![person_uuid(1, "held")]);
    }

    #[tokio::test]
    async fn a_panicking_batch_fails_its_callers_and_the_worker_keeps_running() {
        let inner = ScriptedStorage::new(Some(Poison::Panic("boom")));
        let storage = CoalescingIdentityStorage::spawn(inner, Some(settings(1)), None);

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
        let storage = CoalescingIdentityStorage::spawn(inner.clone(), Some(settings(2)), None);
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

    #[rstest]
    #[case::inside_the_wait(Duration::from_millis(5), vec![vec!["a", "b"]])]
    #[case::after_the_wait(Duration::from_millis(30), vec![vec!["a"], vec!["b"]])]
    #[tokio::test(start_paused = true)]
    async fn an_idle_worker_waits_for_calls_to_share_its_transaction(
        #[case] gap: Duration,
        #[case] transactions: Vec<Vec<&'static str>>,
    ) {
        let inner = ScriptedStorage::new(None);
        let storage = CoalescingIdentityStorage::spawn(
            inner.clone(),
            Some(CoalesceSettings {
                batch_wait: Duration::from_millis(20),
                ..settings(1)
            }),
            None,
        );
        let (a, b) = (vec![stub(1, "a", &[])], vec![stub(1, "b", &[])]);

        let mut first = storage.create_person_stubs(&a);
        assert!(futures::poll!(&mut first).is_pending());
        tokio::time::sleep(gap).await;
        let (first, second) = tokio::join!(first, storage.create_person_stubs(&b));

        assert_eq!(inner.primary_ids_per_call(), transactions);
        assert_eq!(uuids(&first), vec![person_uuid(1, "a")]);
        assert_eq!(uuids(&second), vec![person_uuid(1, "b")]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_full_queue_refuses_new_calls_at_once() {
        let (inner, started_rx, release_tx) = ScriptedStorage::gated(None);
        let storage = CoalescingIdentityStorage::spawn(
            inner.clone(),
            Some(CoalesceSettings {
                max_queued_calls: 1,
                ..settings(1)
            }),
            None,
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
            Some(CoalesceSettings {
                max_queue_wait: Duration::from_secs(1),
                ..settings(1)
            }),
            None,
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
