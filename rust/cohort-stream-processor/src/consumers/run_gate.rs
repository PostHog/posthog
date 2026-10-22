//! The run catalog gate: seed admission holds a backfill run's seeds until the filter catalog has
//! loaded the cohorts that the run backfills.
//!
//! Django commits a cohort write before it creates the run that backfills it, and the seeder
//! produces seeds only after it reads the run. The catalog reads Postgres on its own schedule, so a
//! run's first seeds can arrive before the catalog holds the run's cohort. A seed applied then either
//! drops, because the catalog does not know its condition hashes, or applies without composing the
//! missing cohort, because other cohorts already use the same hashes. Reconcile walks only the
//! Stage 2 rows that exist, so it would then certify the cohort without the members the seeds missed.
//!
//! A run settles when every active participation is in the catalog at its pinned shape hash for the
//! run's kind, or when a catalog refresh that began after the run's first seed arrived has published.
//! That refresh read Postgres after the run's writes committed, so a cohort it still lacks is deleted,
//! unparseable, or outside the allowlist, and the apply paths decide what happens to its seeds.
//! A settled run is not held again in this process.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use cohort_core::seed::{RunId, ScopeKind};
use metrics::counter;
use sqlx::PgPool;
use tokio::task::{Id as TaskId, JoinError, JoinSet};
use tracing::{info, warn};

use crate::filters::manager::{CatalogHandle, CatalogView, RefreshSeq};
use crate::filters::{CohortId, TeamFilters, TeamId};
use crate::observability::metrics::{
    SEED_RUN_GATE_HOLDS_TOTAL, SEED_RUN_GATE_SETTLED_TOTAL, SEED_RUN_LOOKUPS_TOTAL,
};

/// Upper bound on one participant lookup, above the pool's acquire and statement timeouts.
const LOOKUP_TIMEOUT: Duration = Duration::from_secs(10);

/// Delay before a failed lookup runs again. The run's seeds hold until a lookup succeeds.
const LOOKUP_RETRY_BACKOFF: Duration = Duration::from_secs(5);

/// How long one consume cycle waits for the lookups it started. A run whose cohorts the catalog
/// already holds is then admitted in the cycle that first saw it, without a pause.
const LOOKUP_INLINE_WAIT: Duration = Duration::from_millis(250);

/// Lookups in flight at once, so a burst of new runs takes few connections from the shared pool.
const MAX_LOOKUPS_IN_FLIGHT: usize = 4;

/// Settled runs remembered before the set resets. A forgotten run costs one more lookup when its
/// seeds arrive again.
const MAX_SETTLED_RUNS: usize = 4096;

/// Active participations of a run, read in one statement. An absent run returns no rows, and a run
/// with no active participations returns one row with a `NULL` cohort.
const READ_RUN_PARTICIPANTS: &str = r#"
    SELECT r.backfill_kind, c.cohort_id, c.behavioral_filters_shape_hash, c.person_filters_shape_hash
    FROM cohort_backfill_runs r
    LEFT JOIN cohort_backfill_run_cohorts c ON c.run_id = r.id AND c.superseded_at IS NULL
    WHERE r.id = $1
"#;

/// One cohort a run backfills, with the shape hash the run pinned for its kind.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedCohort {
    cohort_id: CohortId,
    /// `None` when the cohort has no leaves of the run's kind. The catalog omits the hash then too.
    kind_hash: Option<Box<str>>,
}

impl PinnedCohort {
    /// An empty hash reads as `None`, the way Django stores a cohort with no leaves of that kind.
    pub fn new(cohort_id: CohortId, kind_hash: Option<&str>) -> Self {
        Self {
            cohort_id,
            kind_hash: kind_hash.filter(|hash| !hash.is_empty()).map(Box::from),
        }
    }
}

/// The active participations of one run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunParticipants {
    /// `false` when the run's row is absent.
    found: bool,
    /// `None` for a kind this processor does not know. The gate then checks only that each cohort
    /// is in the catalog.
    kind: Option<ScopeKind>,
    cohorts: Vec<PinnedCohort>,
}

impl RunParticipants {
    /// A run that exists. No cohorts means every participation is superseded.
    pub fn new(kind: Option<ScopeKind>, cohorts: Vec<PinnedCohort>) -> Self {
        Self {
            found: true,
            kind,
            cohorts,
        }
    }

    pub fn run_absent() -> Self {
        Self {
            found: false,
            kind: None,
            cohorts: Vec::new(),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum RunLookupError {
    #[error("reading the run's participations failed: {0}")]
    Database(#[from] sqlx::Error),
}

/// Where the gate reads which cohorts a run backfills.
#[async_trait]
pub trait RunParticipantsSource: Send + Sync + 'static {
    async fn participants(&self, run_id: RunId) -> Result<RunParticipants, RunLookupError>;
}

/// Reads the participations from Django's backfill tables through the catalog's pool.
pub struct PgRunParticipants {
    pool: PgPool,
}

impl PgRunParticipants {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[derive(sqlx::FromRow)]
struct ParticipantRow {
    backfill_kind: String,
    cohort_id: Option<i32>,
    behavioral_filters_shape_hash: Option<String>,
    person_filters_shape_hash: Option<String>,
}

#[async_trait]
impl RunParticipantsSource for PgRunParticipants {
    async fn participants(&self, run_id: RunId) -> Result<RunParticipants, RunLookupError> {
        let rows = sqlx::query_as::<_, ParticipantRow>(READ_RUN_PARTICIPANTS)
            .bind(run_id)
            .fetch_all(&self.pool)
            .await?;
        Ok(participants_from_rows(rows))
    }
}

fn participants_from_rows(rows: Vec<ParticipantRow>) -> RunParticipants {
    if rows.is_empty() {
        return RunParticipants::run_absent();
    }
    let kind = rows
        .first()
        .and_then(|row| row.backfill_kind.parse::<ScopeKind>().ok());
    let cohorts = rows
        .into_iter()
        .filter_map(|row| {
            let cohort_id = CohortId(row.cohort_id?);
            let kind_hash = match kind {
                Some(ScopeKind::Behavioral) => row.behavioral_filters_shape_hash,
                Some(ScopeKind::PersonProperty) => row.person_filters_shape_hash,
                None => None,
            };
            Some(PinnedCohort::new(cohort_id, kind_hash.as_deref()))
        })
        .collect();
    RunParticipants::new(kind, cohorts)
}

/// Why the catalog does not yet hold a run's cohorts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CatalogGap {
    TeamAbsent,
    CohortAbsent,
    /// The cohort is loaded, but at another shape hash than the run pinned for its kind.
    DefinitionBehind,
    /// The run's row is absent. A replica that has not yet replicated the run reads the same way,
    /// so this waits for a refresh like any other gap.
    RunAbsent,
}

impl CatalogGap {
    fn as_str(self) -> &'static str {
        match self {
            Self::TeamAbsent => "team_absent",
            Self::CohortAbsent => "cohort_absent",
            Self::DefinitionBehind => "definition_behind",
            Self::RunAbsent => "run_absent",
        }
    }
}

/// Why a run's seeds hold this cycle.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum HoldReason {
    CatalogNotLoaded,
    LookupPending,
    LookupFailed,
    Gap(CatalogGap),
}

impl HoldReason {
    fn as_str(self) -> &'static str {
        match self {
            Self::CatalogNotLoaded => "catalog_not_loaded",
            Self::LookupPending => "lookup_pending",
            Self::LookupFailed => "lookup_failed",
            Self::Gap(gap) => gap.as_str(),
        }
    }
}

/// The first gap between the run's participations and the team's catalog, or `None` when the
/// catalog holds every participation at its pinned definition.
///
/// Django writes a run and its participations in one transaction, so a run that is found with no
/// active participation was superseded, and its seeds have no cohort to wait for. A superseded run's
/// seeds replay after every restart, so holding them would delay each restart by a refresh.
fn catalog_gap(participants: &RunParticipants, team: Option<&TeamFilters>) -> Option<CatalogGap> {
    if !participants.found {
        return Some(CatalogGap::RunAbsent);
    }
    if participants.cohorts.is_empty() {
        return None;
    }
    let Some(team) = team else {
        return Some(CatalogGap::TeamAbsent);
    };
    for pinned in &participants.cohorts {
        if !team.cohorts.contains_key(&pinned.cohort_id) {
            return Some(CatalogGap::CohortAbsent);
        }
        let Some(kind) = participants.kind else {
            continue;
        };
        let current = match kind {
            ScopeKind::Behavioral => team
                .behavioral_shape_hashes
                .get(&pinned.cohort_id)
                .map(|hash| hash.as_str()),
            ScopeKind::PersonProperty => team
                .person_shape_hashes
                .get(&pinned.cohort_id)
                .map(|hash| hash.as_str()),
        };
        if current != pinned.kind_hash.as_deref() {
            return Some(CatalogGap::DefinitionBehind);
        }
    }
    None
}

#[derive(Debug)]
enum LookupFailure {
    Error(RunLookupError),
    TimedOut,
}

#[derive(Debug)]
enum Lookup {
    Queued,
    InFlight,
    Failed { retry_at: Instant },
    Resolved(RunParticipants),
}

#[derive(Debug)]
struct PendingRun {
    team_id: TeamId,
    /// The newest refresh that had begun when the gate first saw a seed of the run. A later refresh
    /// read Postgres after the run's writes committed.
    first_arrival: RefreshSeq,
    lookup: Lookup,
    /// The reason of the first hold, so each run counts one hold and settles as held or not.
    first_hold: Option<HoldReason>,
}

enum Verdict {
    Hold(HoldReason),
    /// `None` when the catalog holds every participation, otherwise the gap a fresh refresh left.
    Settle(Option<CatalogGap>),
}

fn verdict(run: &PendingRun, view: &CatalogView) -> Verdict {
    let CatalogView::Loaded { published, catalog } = view else {
        return Verdict::Hold(HoldReason::CatalogNotLoaded);
    };
    let participants = match &run.lookup {
        Lookup::Resolved(participants) => participants,
        Lookup::Failed { .. } => return Verdict::Hold(HoldReason::LookupFailed),
        Lookup::Queued | Lookup::InFlight => return Verdict::Hold(HoldReason::LookupPending),
    };
    match catalog_gap(participants, catalog.team(run.team_id).map(|team| &**team)) {
        None => Verdict::Settle(None),
        Some(gap) if *published > run.first_arrival => Verdict::Settle(Some(gap)),
        Some(gap) => Verdict::Hold(HoldReason::Gap(gap)),
    }
}

/// Per-run admission state of the seed consumer. Owned by the consume loop, so it needs no lock.
pub(crate) struct RunGate {
    source: Arc<dyn RunParticipantsSource>,
    pending: HashMap<RunId, PendingRun>,
    settled: HashSet<RunId>,
    lookups: JoinSet<Result<RunParticipants, LookupFailure>>,
    lookup_runs: HashMap<TaskId, RunId>,
}

impl RunGate {
    pub(crate) fn new(source: Arc<dyn RunParticipantsSource>) -> Self {
        Self {
            source,
            pending: HashMap::new(),
            settled: HashSet::new(),
            lookups: JoinSet::new(),
            lookup_runs: HashMap::new(),
        }
    }

    /// Track the runs first seen in `fresh`, start the lookups that are due, and wait a short time
    /// for the lookups in flight when this call started any.
    pub(crate) async fn prepare(
        &mut self,
        fresh: impl IntoIterator<Item = (RunId, TeamId)>,
        catalog: &CatalogHandle,
        now: Instant,
    ) {
        self.absorb_finished(now);
        for (run_id, team_id) in fresh {
            self.track(run_id, team_id, catalog);
        }
        if self.start_due_lookups(now) == 0 {
            return;
        }
        let _ = tokio::time::timeout(LOOKUP_INLINE_WAIT, async {
            while let Some(joined) = self.lookups.join_next_with_id().await {
                self.absorb(joined, now);
            }
        })
        .await;
    }

    /// The runs whose seeds must hold this cycle. `observed` names every run with a seed that the
    /// cycle splits, held and fresh. A pending run with no such seed is forgotten, because its seeds
    /// left with a revoked partition and a later redelivery tracks it again.
    pub(crate) fn held_runs(
        &mut self,
        observed: impl IntoIterator<Item = (RunId, TeamId)>,
        catalog: &CatalogHandle,
    ) -> HashSet<RunId> {
        let mut seen: HashSet<RunId> = HashSet::new();
        for (run_id, team_id) in observed {
            if self.settled.contains(&run_id) || !seen.insert(run_id) {
                continue;
            }
            self.track(run_id, team_id, catalog);
        }
        self.pending.retain(|run_id, _| seen.contains(run_id));

        let view = catalog.view();
        let mut held = HashSet::new();
        let mut settling = Vec::new();
        for (&run_id, run) in &mut self.pending {
            match verdict(run, &view) {
                Verdict::Hold(reason) => {
                    if run.first_hold.is_none() {
                        run.first_hold = Some(reason);
                        counter!(SEED_RUN_GATE_HOLDS_TOTAL, "reason" => reason.as_str())
                            .increment(1);
                        info!(
                            run_id = %run_id.0,
                            team_id = run.team_id.0,
                            reason = reason.as_str(),
                            "holding a backfill run's seeds until the filter catalog holds its cohorts",
                        );
                    }
                    held.insert(run_id);
                }
                Verdict::Settle(gap) => settling.push((run_id, gap)),
            }
        }
        for (run_id, gap) in settling {
            let run = self
                .pending
                .remove(&run_id)
                .expect("settling runs come from the pending map");
            record_settled(run_id, &run, gap);
            if self.settled.len() >= MAX_SETTLED_RUNS {
                self.settled.clear();
            }
            self.settled.insert(run_id);
        }
        held
    }

    fn track(&mut self, run_id: RunId, team_id: TeamId, catalog: &CatalogHandle) {
        if self.settled.contains(&run_id) {
            return;
        }
        self.pending.entry(run_id).or_insert_with(|| PendingRun {
            team_id,
            first_arrival: catalog.last_begun(),
            lookup: Lookup::Queued,
            first_hold: None,
        });
    }

    fn start_due_lookups(&mut self, now: Instant) -> usize {
        let mut started = 0;
        for (&run_id, run) in &mut self.pending {
            if self.lookup_runs.len() >= MAX_LOOKUPS_IN_FLIGHT {
                break;
            }
            let due = match run.lookup {
                Lookup::Queued => true,
                Lookup::Failed { retry_at } => now >= retry_at,
                Lookup::InFlight | Lookup::Resolved(_) => false,
            };
            if !due {
                continue;
            }
            let source = self.source.clone();
            let task = self.lookups.spawn(async move {
                match tokio::time::timeout(LOOKUP_TIMEOUT, source.participants(run_id)).await {
                    Ok(Ok(participants)) => Ok(participants),
                    Ok(Err(err)) => Err(LookupFailure::Error(err)),
                    Err(_) => Err(LookupFailure::TimedOut),
                }
            });
            self.lookup_runs.insert(task.id(), run_id);
            run.lookup = Lookup::InFlight;
            started += 1;
        }
        started
    }

    fn absorb_finished(&mut self, now: Instant) {
        while let Some(joined) = self.lookups.try_join_next_with_id() {
            self.absorb(joined, now);
        }
    }

    fn absorb(
        &mut self,
        joined: Result<(TaskId, Result<RunParticipants, LookupFailure>), JoinError>,
        now: Instant,
    ) {
        let (task_id, outcome) = match joined {
            Ok((task_id, outcome)) => (task_id, Some(outcome)),
            Err(err) => (err.id(), None),
        };
        let Some(run_id) = self.lookup_runs.remove(&task_id) else {
            return;
        };
        let result = match &outcome {
            Some(Ok(_)) => "ok",
            Some(Err(LookupFailure::Error(_))) => "error",
            Some(Err(LookupFailure::TimedOut)) => "timeout",
            None => "panic",
        };
        counter!(SEED_RUN_LOOKUPS_TOTAL, "result" => result).increment(1);
        let Some(run) = self.pending.get_mut(&run_id) else {
            return;
        };
        run.lookup = match outcome {
            Some(Ok(participants)) => Lookup::Resolved(participants),
            Some(Err(failure)) => {
                let error = match &failure {
                    LookupFailure::Error(err) => err.to_string(),
                    LookupFailure::TimedOut => format!("timed out after {LOOKUP_TIMEOUT:?}"),
                };
                warn!(
                    run_id = %run_id.0,
                    error,
                    "backfill run participant lookup failed; its seeds hold until a retry succeeds",
                );
                Lookup::Failed {
                    retry_at: now + LOOKUP_RETRY_BACKOFF,
                }
            }
            None => {
                warn!(
                    run_id = %run_id.0,
                    "backfill run participant lookup panicked; its seeds hold until a retry succeeds",
                );
                Lookup::Failed {
                    retry_at: now + LOOKUP_RETRY_BACKOFF,
                }
            }
        };
    }

    #[cfg(test)]
    pub(crate) async fn finish_lookups(&mut self, now: Instant) {
        while let Some(joined) = self.lookups.join_next_with_id().await {
            self.absorb(joined, now);
        }
    }
}

fn record_settled(run_id: RunId, run: &PendingRun, gap: Option<CatalogGap>) {
    let (outcome, reason) = match (gap, run.first_hold) {
        (None, None) => ("loaded", "none"),
        (None, Some(_)) => ("loaded_after_hold", "none"),
        (Some(gap), _) => ("admitted_after_refresh", gap.as_str()),
    };
    counter!(SEED_RUN_GATE_SETTLED_TOTAL, "outcome" => outcome, "reason" => reason).increment(1);
    if let Some(gap) = gap {
        info!(
            run_id = %run_id.0,
            team_id = run.team_id.0,
            gap = gap.as_str(),
            "admitting a backfill run's seeds after a fresh catalog refresh that still lacks one of its cohorts",
        );
    } else if run.first_hold.is_some() {
        info!(
            run_id = %run_id.0,
            team_id = run.team_id.0,
            "the filter catalog now holds a held backfill run's cohorts; admitting its seeds",
        );
    }
}

#[cfg(test)]
pub(crate) mod test_support {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    use super::*;

    /// A participant source with answers set per run. A run without an answer reads as absent.
    #[derive(Default)]
    pub(crate) struct ScriptedParticipants {
        answers: Mutex<HashMap<RunId, Option<RunParticipants>>>,
        calls: AtomicUsize,
    }

    impl ScriptedParticipants {
        pub(crate) fn answer(&self, run_id: RunId, participants: RunParticipants) {
            self.answers
                .lock()
                .unwrap()
                .insert(run_id, Some(participants));
        }

        pub(crate) fn fail(&self, run_id: RunId) {
            self.answers.lock().unwrap().insert(run_id, None);
        }

        pub(crate) fn calls(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl RunParticipantsSource for ScriptedParticipants {
        async fn participants(&self, run_id: RunId) -> Result<RunParticipants, RunLookupError> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            match self.answers.lock().unwrap().get(&run_id) {
                Some(Some(participants)) => Ok(participants.clone()),
                Some(None) => Err(RunLookupError::Database(sqlx::Error::PoolTimedOut)),
                None => Ok(RunParticipants::run_absent()),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::seed::PersonShapeHash;
    use serde_json::json;
    use uuid::Uuid;

    use crate::filters::{FilterCatalog, TeamFiltersBuilder};

    use super::test_support::ScriptedParticipants;
    use super::*;

    const TEAM: TeamId = TeamId(7);
    const RUN: RunId = RunId(Uuid::from_u128(0xB1));
    const EXISTING: CohortId = CohortId(1);
    const NEW: CohortId = CohortId(2);
    const PINNED: &str = "pinned-person-shape";
    const OLDER: &str = "older-person-shape";

    fn person_cohort() -> serde_json::Value {
        json!({ "properties": { "type": "AND", "values": [{
            "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        }]}})
    }

    /// Every cohort uses one condition hash, so a seed of the new cohort's run applies without any
    /// dropped hash while only the existing cohort is loaded.
    fn catalog_with(cohorts: &[(CohortId, &str)]) -> FilterCatalog {
        let mut builder = TeamFiltersBuilder::default();
        for &(cohort_id, shape) in cohorts {
            builder
                .add_cohort(cohort_id, TEAM, &person_cohort())
                .unwrap();
            builder.set_person_shape_hash(cohort_id, PersonShapeHash::parse(shape).unwrap());
        }
        FilterCatalog::from_teams([(TEAM, builder.freeze(UTC))])
    }

    fn new_cohort_run() -> RunParticipants {
        RunParticipants::new(
            Some(ScopeKind::PersonProperty),
            vec![PinnedCohort::new(NEW, Some(PINNED))],
        )
    }

    fn gate_answering(participants: RunParticipants) -> (RunGate, Arc<ScriptedParticipants>) {
        let source = Arc::new(ScriptedParticipants::default());
        source.answer(RUN, participants);
        (RunGate::new(source.clone()), source)
    }

    async fn cycle(gate: &mut RunGate, catalog: &CatalogHandle, now: Instant) -> HashSet<RunId> {
        gate.prepare([(RUN, TEAM)], catalog, now).await;
        gate.finish_lookups(now).await;
        gate.held_runs([(RUN, TEAM)], catalog)
    }

    /// Each case is a catalog or a replica that has not read the run's writes yet. A gate that
    /// looked only for dropped condition hashes would admit the shared-hash and older-definition
    /// cases.
    #[tokio::test]
    async fn a_run_holds_until_the_catalog_holds_its_cohort_at_the_pinned_definition() {
        let cases = [
            ("team absent", FilterCatalog::new(), new_cohort_run()),
            (
                "cohort absent, hashes known",
                catalog_with(&[(EXISTING, PINNED)]),
                new_cohort_run(),
            ),
            (
                "cohort at an older definition",
                catalog_with(&[(EXISTING, PINNED), (NEW, OLDER)]),
                new_cohort_run(),
            ),
            (
                "run not yet on the replica",
                catalog_with(&[(EXISTING, PINNED)]),
                RunParticipants::run_absent(),
            ),
        ];
        for (case, behind, participants) in cases {
            let catalog = CatalogHandle::from_catalog(behind);
            let (mut gate, _) = gate_answering(participants);
            let now = Instant::now();

            assert_eq!(
                cycle(&mut gate, &catalog, now).await,
                HashSet::from([RUN]),
                "{case}"
            );

            catalog.publish(catalog_with(&[(EXISTING, PINNED), (NEW, PINNED)]));
            assert!(cycle(&mut gate, &catalog, now).await.is_empty(), "{case}");
        }
    }

    /// The catalog may begin a refresh before the run's first seed arrives and publish it after.
    /// That refresh may predate the run's writes, so only a later one admits a run whose cohort it
    /// still lacks. A deleted cohort must not hold the partition for longer than that.
    #[tokio::test]
    async fn only_a_refresh_begun_after_the_first_seed_admits_a_run_whose_cohort_stays_absent() {
        let catalog = CatalogHandle::from_catalog(catalog_with(&[(EXISTING, PINNED)]));
        let (mut gate, _) = gate_answering(new_cohort_run());
        let now = Instant::now();
        let in_flight = catalog.begin_refresh();

        assert_eq!(cycle(&mut gate, &catalog, now).await, HashSet::from([RUN]));

        in_flight.publish(catalog_with(&[(EXISTING, PINNED)]));
        assert_eq!(cycle(&mut gate, &catalog, now).await, HashSet::from([RUN]));

        catalog.publish(catalog_with(&[(EXISTING, PINNED)]));
        assert!(cycle(&mut gate, &catalog, now).await.is_empty());
    }

    /// Steady state: a run whose cohorts are loaded never holds, and costs one lookup however many
    /// of its seeds arrive. A superseded run's seeds replay after every restart, so they must not
    /// hold either.
    #[tokio::test]
    async fn a_loaded_or_superseded_run_never_holds_and_is_looked_up_once() {
        let cases = [
            ("cohorts loaded", new_cohort_run()),
            (
                "every participation superseded",
                RunParticipants::new(Some(ScopeKind::PersonProperty), Vec::new()),
            ),
        ];
        for (case, participants) in cases {
            let catalog =
                CatalogHandle::from_catalog(catalog_with(&[(EXISTING, PINNED), (NEW, PINNED)]));
            let (mut gate, source) = gate_answering(participants);
            let now = Instant::now();

            gate.prepare([(RUN, TEAM)], &catalog, now).await;
            assert!(
                gate.held_runs([(RUN, TEAM)], &catalog).is_empty(),
                "{case}: the inline wait lets a fast lookup admit the run in the cycle that first saw it",
            );
            assert!(cycle(&mut gate, &catalog, now).await.is_empty(), "{case}");
            assert_eq!(source.calls(), 1, "{case}");
        }
    }

    /// Without the participations the gate cannot tell whether the catalog is behind, so a failed
    /// lookup holds even after a fresh refresh, and retries after the backoff.
    #[tokio::test]
    async fn a_failed_lookup_holds_past_a_fresh_refresh_until_a_retry_succeeds() {
        let catalog =
            CatalogHandle::from_catalog(catalog_with(&[(EXISTING, PINNED), (NEW, PINNED)]));
        let source = Arc::new(ScriptedParticipants::default());
        source.fail(RUN);
        let mut gate = RunGate::new(source.clone());
        let now = Instant::now();

        assert_eq!(cycle(&mut gate, &catalog, now).await, HashSet::from([RUN]));
        catalog.publish(catalog_with(&[(EXISTING, PINNED), (NEW, PINNED)]));
        assert_eq!(cycle(&mut gate, &catalog, now).await, HashSet::from([RUN]));
        assert_eq!(source.calls(), 1, "no retry before the backoff");

        source.answer(RUN, new_cohort_run());
        let later = now + LOOKUP_RETRY_BACKOFF;
        assert!(cycle(&mut gate, &catalog, later).await.is_empty());
        assert_eq!(source.calls(), 2);
    }

    /// Reading the other kind's hash would hold every run of a mixed cohort for a refresh, and a
    /// run with no active participation must not read as a cohort.
    #[test]
    fn participant_rows_pin_the_hash_of_the_run_kind() {
        let row = |kind: &str, cohort_id: Option<i32>| ParticipantRow {
            backfill_kind: kind.to_string(),
            cohort_id,
            behavioral_filters_shape_hash: Some("behavioral-shape".to_string()),
            person_filters_shape_hash: Some(String::new()),
        };
        let cases = [
            (
                vec![row("behavioral", Some(4))],
                RunParticipants::new(
                    Some(ScopeKind::Behavioral),
                    vec![PinnedCohort::new(CohortId(4), Some("behavioral-shape"))],
                ),
            ),
            (
                vec![row("person_property", Some(4))],
                RunParticipants::new(
                    Some(ScopeKind::PersonProperty),
                    vec![PinnedCohort::new(CohortId(4), None)],
                ),
            ),
            (
                vec![row("a_future_kind", Some(4))],
                RunParticipants::new(None, vec![PinnedCohort::new(CohortId(4), None)]),
            ),
            (
                vec![row("behavioral", None)],
                RunParticipants::new(Some(ScopeKind::Behavioral), Vec::new()),
            ),
            (Vec::new(), RunParticipants::run_absent()),
        ];
        for (rows, expected) in cases {
            assert_eq!(participants_from_rows(rows), expected);
        }
    }

    /// Requires a live Postgres with Django's migrations applied; run with
    /// `cargo test -p cohort-stream-processor -- --ignored`.
    #[tokio::test]
    #[ignore]
    async fn participant_query_runs_against_the_django_schema() {
        let url = std::env::var("DATABASE_URL")
            .unwrap_or_else(|_| "postgres://posthog:posthog@localhost:5432/posthog".to_string());
        let pool =
            common_database::get_pool_with_config(&url, common_database::PoolConfig::default())
                .expect("build the pool");

        let participants = PgRunParticipants::new(pool)
            .participants(RunId(Uuid::new_v4()))
            .await
            .expect("the participant query must match the backfill tables");

        assert_eq!(participants, RunParticipants::run_absent());
    }
}
