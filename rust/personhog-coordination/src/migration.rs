//! The changelog migration driver: one CAS-guarded reconcile pass over `migrations/current`.

use std::collections::{HashMap, HashSet};
use std::time::Duration;

use metrics::{counter, gauge};

use crate::error::Result;
use crate::protocol::drain_satisfied;
use crate::protocol::migration::{
    fleet_quiet, migration_unsealed, migration_unsettled, plan_freeze, plan_resume,
};
use crate::store::PersonhogStore;
use crate::strategy::{AssignmentStrategy, Member, PlacementPolicy};
use crate::types::{
    AssignmentPrecondition, Generation, HandoffPhase, HandoffReplacement, HandoffState,
    MigrationPhase, MigrationRequest, MigrationState, PodStatus, RegisteredPod,
};
use crate::util;

const PHASES: [MigrationPhase; 7] = [
    MigrationPhase::Freezing,
    MigrationPhase::Draining,
    MigrationPhase::Sealing,
    MigrationPhase::Resuming,
    MigrationPhase::Complete,
    MigrationPhase::Cancelling,
    MigrationPhase::Cancelled,
];

pub fn phase_label(phase: MigrationPhase) -> &'static str {
    match phase {
        MigrationPhase::Freezing => "freezing",
        MigrationPhase::Draining => "draining",
        MigrationPhase::Sealing => "sealing",
        MigrationPhase::Resuming => "resuming",
        MigrationPhase::Complete => "complete",
        MigrationPhase::Cancelling => "cancelling",
        MigrationPhase::Cancelled => "cancelled",
    }
}

/// Clears the phase gauge when a coordinator's migration loop ends, so a
/// coordinator that lost leadership stops reporting the saga.
pub(crate) struct PhaseGauge;

impl Drop for PhaseGauge {
    fn drop(&mut self) {
        record_phase(None);
    }
}

/// Registers each phase's transition counter at zero, so the first saga a
/// coordinator drives shows up under `increase()`.
pub fn register_transition_metrics() {
    for phase in PHASES {
        counter!("personhog_migration_transitions_total", "to" => phase_label(phase)).increment(0);
    }
}

pub fn record_phase(current: Option<MigrationPhase>) {
    for phase in PHASES {
        gauge!("personhog_migration_phase", "phase" => phase_label(phase))
            .set(if current == Some(phase) { 1.0 } else { 0.0 });
    }
}

struct Pass<'a> {
    store: &'a PersonhogStore,
    pods: &'a [RegisteredPod],
    max_txn_ops: usize,
    migration: &'a MigrationState,
    mod_revision: i64,
    /// The live config's epoch, which every record this pass writes carries.
    epoch: u64,
}

impl Pass<'_> {
    fn registered(&self, pod: &str) -> bool {
        self.pods.iter().any(|p| p.pod_name == pod)
    }

    fn address_of(&self, pod: &str) -> Option<String> {
        self.pods
            .iter()
            .find(|p| p.pod_name == pod)
            .and_then(|p| p.advertise_address.clone())
    }

    /// Apply this pass's plan on the record it read. False when a successor moved
    /// the record, in which case nothing landed and the pass must stop.
    async fn apply(
        &self,
        creations: &[HandoffState],
        replacements: &[HandoffReplacement],
        preconditions: &[AssignmentPrecondition],
        freeze_quorum: Option<(&str, &[String])>,
    ) -> Result<bool> {
        let application = self
            .store
            .apply_migration_plan(
                self.mod_revision,
                creations,
                replacements,
                preconditions,
                freeze_quorum,
                self.max_txn_ops,
            )
            .await?;
        if application.stood_down.is_empty() {
            return Ok(true);
        }
        tracing::warn!(
            migration = %self.migration.id,
            phase = ?self.migration.phase,
            stood_down = application.stood_down.len(),
            "the saga record moved under this pass; its plan stood down"
        );
        Ok(false)
    }

    async fn held(&self) -> Result<Vec<(HandoffState, i64)>> {
        let handoffs = self.store.list_handoffs_with_mod_revisions().await?;
        Ok(handoffs
            .into_iter()
            .filter(|(h, _)| h.held_by.as_deref() == Some(&self.migration.id))
            .collect())
    }

    async fn advance(&self, next: MigrationPhase) -> Result<bool> {
        let advanced = self
            .store
            .cas_migration_phase(&self.migration.id, self.mod_revision, next)
            .await?;
        if advanced {
            counter!("personhog_migration_transitions_total", "to" => phase_label(next))
                .increment(1);
            tracing::info!(migration = %self.migration.id, from = ?self.migration.phase, to = ?next, "migration advanced");
        }
        Ok(advanced)
    }

    async fn cancel(&self, reason: &'static str) -> Result<()> {
        if self
            .store
            .cancel_migration(&self.migration.id, self.mod_revision, reason)
            .await?
        {
            tracing::error!(migration = %self.migration.id, phase = ?self.migration.phase, reason, blocking = ?self.migration.blocking, "cancelled migration");
        }
        Ok(())
    }

    async fn block(&self, blocking: Vec<String>) -> Result<()> {
        if self.migration.blocking != blocking {
            tracing::info!(migration = %self.migration.id, phase = ?self.migration.phase, ?blocking, "migration waiting");
            self.store
                .set_migration_blocking(self.mod_revision, blocking)
                .await?;
        }
        Ok(())
    }

    async fn gate(&self, blocking: Vec<String>, next: MigrationPhase) -> Result<()> {
        if blocking.is_empty() {
            self.advance(next).await?;
            Ok(())
        } else {
            self.block(blocking).await
        }
    }

    async fn archive(&self, final_phase: MigrationPhase) -> Result<()> {
        if self
            .store
            .archive_migration(self.migration, self.mod_revision, final_phase)
            .await?
        {
            counter!("personhog_migration_transitions_total", "to" => phase_label(final_phase))
                .increment(1);
            // Counted here, once, whoever cancelled: the driver or an operator.
            if final_phase == MigrationPhase::Cancelled {
                let reason = self.migration.cancel_reason.as_deref().unwrap_or("unknown");
                counter!("personhog_migration_cancelled_total", "reason" => reason.to_string())
                    .increment(1);
            }
            record_phase(None);
            tracing::info!(migration = %self.migration.id, phase = ?final_phase, "migration archived");
        }
        Ok(())
    }

    /// A hold: the partition stays with its owner, frozen and drained, until resume.
    fn hold(&self, partition: u32, owner: &str, quorum_id: &str) -> HandoffState {
        HandoffState {
            held_by: Some(self.migration.id.clone()),
            ..self.fresh(partition, Some(owner), owner, Some(quorum_id))
        }
    }

    /// A restart over the new changelog starts at Warming: it is frozen and drained already.
    fn restart(&self, partition: u32, owner: &str) -> HandoffState {
        HandoffState {
            phase: HandoffPhase::Warming,
            freeze_quorum: Some(Vec::new()),
            ..self.fresh(partition, Some(owner), owner, None)
        }
    }

    /// A cancelled hold ends as Complete, keeping the partition with its holder.
    fn reaffirm(&self, partition: u32, owner: &str) -> HandoffState {
        HandoffState {
            phase: HandoffPhase::Complete,
            freeze_quorum: Some(Vec::new()),
            ..self.fresh(partition, None, owner, None)
        }
    }

    /// A partition the grow created, placed with no prior owner.
    fn place(&self, partition: u32, owner: &str, quorum_id: &str) -> HandoffState {
        self.fresh(partition, None, owner, Some(quorum_id))
    }

    /// A Freezing record under the live config's epoch.
    fn fresh(
        &self,
        partition: u32,
        old_owner: Option<&str>,
        owner: &str,
        quorum_id: Option<&str>,
    ) -> HandoffState {
        let now_ms = util::now_millis();
        HandoffState {
            partition,
            old_owner: old_owner.map(str::to_string),
            new_owner: owner.to_string(),
            new_owner_address: self.address_of(owner),
            phase: HandoffPhase::Freezing,
            started_at: now_ms / 1000,
            handoff_id: util::new_handoff_id(),
            freeze_quorum: None,
            freeze_quorum_ref: quorum_id.map(str::to_string),
            created_at_ms: now_ms,
            phase_entered_at_ms: now_ms,
            held_by: None,
            config_epoch: self.epoch,
        }
    }

    async fn router_quorum(&self) -> Result<Vec<String>> {
        let routers = self.store.list_routers().await?;
        Ok(routers.into_iter().map(|r| r.router_name).collect())
    }

    async fn freeze(&self) -> Result<()> {
        let handoffs = self.store.list_handoffs().await?;
        let assignments = self.store.list_assignments_with_mod_revisions().await?;
        let states: Vec<_> = assignments.iter().map(|(a, _)| a.clone()).collect();
        let registered: HashSet<&str> = self.pods.iter().map(|p| p.pod_name.as_str()).collect();
        let plan = plan_freeze(
            self.migration.from.partitions,
            &states,
            &handoffs,
            &registered,
        );
        if let Some((partition, handoff_id)) = plan.stray_handoff {
            tracing::error!(migration = %self.migration.id, partition, handoff_id, "an ordinary handoff exists during the freeze; the quiet start should have ruled it out");
            return self.cancel("handoff_during_freeze").await;
        }
        if let Some((partition, holder)) = plan.holder_died {
            tracing::error!(migration = %self.migration.id, partition, holder, "the holder is not registered");
            return self.cancel("holder_died").await;
        }
        let revisions: HashMap<u32, i64> = assignments
            .iter()
            .map(|(a, rev)| (a.partition, *rev))
            .collect();
        let quorum = self.router_quorum().await?;
        let quorum_id = util::new_handoff_id();
        let mut creations = Vec::new();
        let mut preconditions = Vec::new();
        for (partition, owner) in &plan.holds {
            creations.push(self.hold(*partition, owner, &quorum_id));
            preconditions.push(AssignmentPrecondition::UnchangedSince {
                partition: *partition,
                mod_revision: revisions[partition],
            });
        }
        if !creations.is_empty() {
            tracing::info!(migration = %self.migration.id, holds = creations.len(), "holding partitions");
            if !self
                .apply(&creations, &[], &preconditions, Some((&quorum_id, &quorum)))
                .await?
            {
                return Ok(());
            }
        }
        self.gate(plan.blocking, MigrationPhase::Draining).await
    }

    async fn drain(&self) -> Result<()> {
        let mut blocking = Vec::new();
        for (held, _) in self.held().await? {
            if !self.registered(&held.new_owner) {
                tracing::error!(migration = %self.migration.id, partition = held.partition, holder = %held.new_owner, "the holder is not registered");
                return self.cancel("holder_died").await;
            }
            if held.phase == HandoffPhase::Freezing {
                blocking.push(format!("partition {}: freeze quorum", held.partition));
                continue;
            }
            let acks = self.store.list_drained_acks(held.partition).await?;
            if !drain_satisfied(self.pods, &acks, &held) {
                blocking.push(format!("partition {}: drain", held.partition));
            }
        }
        self.gate(blocking, MigrationPhase::Sealing).await
    }

    /// Every live leader seals orphaned partitions too, so a dead holder never blocks.
    async fn seal(&self) -> Result<()> {
        let acks = self.store.list_seal_acks().await?;
        let blocking: Vec<String> =
            migration_unsealed(&acks, &self.migration.id, self.migration.from.partitions)
                .into_iter()
                .map(|p| format!("partition {p}: not sealed"))
                .collect();
        if !blocking.is_empty() {
            return self.block(blocking).await;
        }
        let Some((config, config_mod_revision)) =
            self.store.get_changelog_config_with_mod_revision().await?
        else {
            return self.block(vec!["config vanished".to_string()]).await;
        };
        if self
            .store
            .flip_changelog(
                self.migration,
                self.mod_revision,
                &config,
                config_mod_revision,
            )
            .await?
        {
            counter!("personhog_migration_transitions_total", "to" => phase_label(MigrationPhase::Resuming))
                .increment(1);
            tracing::info!(
                migration = %self.migration.id,
                topic = %self.migration.to.topic,
                partitions = self.migration.to.partitions,
                epoch = config.epoch + 1,
                "changelog flipped"
            );
        }
        Ok(())
    }

    async fn resume(&self, strategy: &dyn AssignmentStrategy, members: &[Member]) -> Result<()> {
        let held = self.held().await?;
        let to = self.migration.to.partitions;
        if !held.is_empty() {
            let assignments = self.store.list_assignments_with_mod_revisions().await?;
            let handoffs = self.store.list_handoffs().await?;
            let states: Vec<_> = assignments.iter().map(|(a, _)| a.clone()).collect();
            let holds: Vec<(u32, String)> = held
                .iter()
                .map(|(h, _)| (h.partition, h.new_owner.clone()))
                .collect();
            let registered: HashSet<&str> = self.pods.iter().map(|p| p.pod_name.as_str()).collect();
            let plan = plan_resume(
                strategy,
                members,
                to,
                &holds,
                &states,
                &handoffs,
                &registered,
            );

            let held_revisions: HashMap<u32, i64> =
                held.iter().map(|(h, rev)| (h.partition, *rev)).collect();
            let assignment_revisions: HashMap<u32, i64> = assignments
                .iter()
                .map(|(a, rev)| (a.partition, *rev))
                .collect();
            for partition in &plan.dissolve {
                self.store
                    .dissolve_partition(*partition, held_revisions[partition])
                    .await?;
            }
            for partition in &plan.abandon {
                self.store
                    .delete_handoff_and_acks_if_unchanged(*partition, held_revisions[partition])
                    .await?;
            }
            let mut preconditions = Vec::new();
            let mut replacements = Vec::new();
            for (partition, holder) in &plan.restart {
                replacements.push(HandoffReplacement {
                    handoff: self.restart(*partition, holder),
                    expected_mod_revision: held_revisions[partition],
                });
                preconditions.push(match assignment_revisions.get(partition) {
                    Some(&mod_revision) => AssignmentPrecondition::UnchangedSince {
                        partition: *partition,
                        mod_revision,
                    },
                    None => AssignmentPrecondition::Absent {
                        partition: *partition,
                    },
                });
            }
            let quorum = self.router_quorum().await?;
            let quorum_id = util::new_handoff_id();
            let mut creations = Vec::new();
            for (partition, owner) in &plan.place {
                creations.push(self.place(*partition, owner, &quorum_id));
                preconditions.push(AssignmentPrecondition::Absent {
                    partition: *partition,
                });
            }
            if !replacements.is_empty() || !creations.is_empty() {
                tracing::info!(migration = %self.migration.id, restarts = replacements.len(), fresh = creations.len(), "restarting partitions over the new changelog");
                if !self
                    .apply(
                        &creations,
                        &replacements,
                        &preconditions,
                        Some((&quorum_id, &quorum)),
                    )
                    .await?
                {
                    return Ok(());
                }
            }
            let blocking = held
                .iter()
                .map(|(h, _)| format!("partition {}: restarting", h.partition))
                .collect();
            return self.block(blocking).await;
        }
        let handoffs = self.store.list_handoffs().await?;
        let assignments = self.store.list_assignments().await?;
        let registered: HashSet<&str> = self.pods.iter().map(|p| p.pod_name.as_str()).collect();
        let unsettled = migration_unsettled(&assignments, &handoffs, &registered, to);
        if unsettled.is_empty() {
            return self.archive(MigrationPhase::Complete).await;
        }
        self.block(
            unsettled
                .into_iter()
                .map(|p| format!("partition {p}: not settled"))
                .collect(),
        )
        .await
    }

    async fn unwind(&self) -> Result<()> {
        let held = self.held().await?;
        if held.is_empty() {
            return self.archive(MigrationPhase::Cancelled).await;
        }
        let mut replacements = Vec::new();
        for (h, rev) in held {
            if !self.registered(&h.new_owner) {
                self.store
                    .delete_handoff_and_acks_if_unchanged(h.partition, rev)
                    .await?;
                continue;
            }
            replacements.push(HandoffReplacement {
                handoff: self.reaffirm(h.partition, &h.new_owner),
                expected_mod_revision: rev,
            });
        }
        if !replacements.is_empty() {
            self.apply(&[], &replacements, &[], None).await?;
        }
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn reconcile(
    store: &PersonhogStore,
    strategy: &dyn AssignmentStrategy,
    members: &[Member],
    pods: &[RegisteredPod],
    pre_flip_deadline: Duration,
    max_txn_ops: usize,
    migration: MigrationState,
    mod_revision: i64,
) -> Result<()> {
    record_phase(Some(migration.phase));
    let Some(config) = store.get_changelog_config().await? else {
        tracing::error!(migration = %migration.id, "config/changelog is missing; the saga waits");
        return Ok(());
    };
    let pass = Pass {
        store,
        pods,
        max_txn_ops,
        migration: &migration,
        mod_revision,
        epoch: config.epoch,
    };
    let cancellable = migration
        .phase
        .may_transition_to(MigrationPhase::Cancelling);
    let age_ms = util::now_millis().saturating_sub(migration.created_at_ms);
    if cancellable && age_ms > pre_flip_deadline.as_millis() as i64 {
        return pass.cancel("pre_flip_deadline").await;
    }
    match migration.phase {
        MigrationPhase::Freezing => pass.freeze().await,
        MigrationPhase::Draining => pass.drain().await,
        MigrationPhase::Sealing => pass.seal().await,
        MigrationPhase::Resuming => pass.resume(strategy, members).await,
        MigrationPhase::Cancelling => pass.unwind().await,
        // A live record in a terminal phase is an archive that did not finish.
        MigrationPhase::Complete | MigrationPhase::Cancelled => pass.archive(migration.phase).await,
    }
}

/// A request older than this is rejected rather than started, so a saga only
/// begins while whoever asked for it is plausibly still watching.
pub const REQUEST_EXPIRY: Duration = Duration::from_secs(300);

/// Why a request may not begin, checked at the moment it would start.
async fn admission_refusal(
    store: &PersonhogStore,
    request: &MigrationRequest,
    members: &[Member],
) -> Result<Option<&'static str>> {
    let reason = match store.get_changelog_config().await? {
        None => Some("config_not_seeded"),
        Some(live) if live.target() != request.from => Some("from_is_not_the_live_config"),
        _ if request.to.topic == request.from.topic => Some("same_topic"),
        _ if members
            .iter()
            .any(|m| m.policy != PlacementPolicy::Active { cap: None }) =>
        {
            Some("rollout_in_progress")
        }
        _ => None,
    };
    if reason.is_some() {
        return Ok(reason);
    }
    let history = store.list_migration_history().await?;
    Ok(history
        .iter()
        .any(|h| h.from.topic == request.to.topic && h.phase == MigrationPhase::Complete)
        .then_some("topic_already_retired"))
}

/// What the coordinator's retire pass did.
pub enum Retirement {
    /// A generation left the config; the next pass sees the new config.
    Retired,
    /// Generations still draining, each with the groups that have not reported it.
    Waiting(Vec<String>),
    /// Nothing drains.
    Clear,
}

/// Retires the oldest draining generation once every gated group has reported
/// it drained. Runs only while no saga exists; the retire's transaction requires that too.
pub async fn retire_drained(store: &PersonhogStore) -> Result<Retirement> {
    let Some((config, mod_revision)) = store.get_changelog_config_with_mod_revision().await? else {
        return Ok(Retirement::Clear);
    };
    let reports = store.list_drain_reports().await?;
    // A topic never returns to the config once it leaves `draining`, so a report
    // for any other topic is late and safe to drop.
    let stale: HashSet<&str> = reports
        .iter()
        .map(|r| r.topic.as_str())
        .filter(|topic| config.draining.iter().all(|g| g.topic != *topic))
        .collect();
    for topic in stale {
        store.delete_drain_reports_for(topic).await?;
        counter!("personhog_changelog_drain_reports_swept_total").increment(1);
    }

    let mut generations = config.draining.clone();
    generations.sort_by_key(|g| g.epoch);
    let missing: Vec<(&Generation, Vec<&str>)> = generations
        .iter()
        .map(|generation| {
            let groups = config
                .gated_groups()
                .filter(|group| {
                    !reports
                        .iter()
                        .any(|r| r.topic == generation.topic && r.group == *group)
                })
                .collect();
            (generation, groups)
        })
        .collect();
    // Set on every pass between sagas; during a saga nothing can retire.
    gauge!("personhog_changelog_retire_waiting_groups").set(
        missing
            .iter()
            .map(|(_, groups)| groups.len())
            .sum::<usize>() as f64,
    );

    if let Some((generation, _)) = missing.iter().find(|(_, groups)| groups.is_empty()) {
        if store
            .retire_changelog_topic(&config, mod_revision, &generation.topic)
            .await?
        {
            counter!("personhog_changelog_retires_total", "trigger" => "auto").increment(1);
            tracing::info!(
                topic = %generation.topic,
                groups = ?config.gated_groups().collect::<Vec<_>>(),
                "retired a drained changelog generation"
            );
        }
        return Ok(Retirement::Retired);
    }
    let waiting: Vec<String> = missing
        .iter()
        .map(|(generation, groups)| {
            format!(
                "{}: waiting on drain reports from {}",
                generation.topic,
                groups.join(", ")
            )
        })
        .collect();
    Ok(if waiting.is_empty() {
        Retirement::Clear
    } else {
        Retirement::Waiting(waiting)
    })
}

/// Registers the retire metrics at zero, so the first retire shows as an increase.
pub fn register_retire_metrics() {
    counter!("personhog_changelog_retires_total", "trigger" => "auto").increment(0);
    counter!("personhog_changelog_drain_reports_swept_total").increment(0);
    gauge!("personhog_changelog_retire_waiting_groups").set(0.0);
}

/// The only way a saga starts: it waits, holding nothing, until no generation
/// drains and the fleet is quiet, then starts in a transaction that proves no
/// handoff appeared meanwhile.
pub async fn consider_request(
    store: &PersonhogStore,
    members: &[Member],
    pods: &[RegisteredPod],
    request: MigrationRequest,
    mod_revision: i64,
    draining: Vec<String>,
) -> Result<()> {
    let now_ms = util::now_millis();
    // The expiry runs on the coordinator's clock, from its first sighting.
    let Some(seen_at_ms) = request.seen_at_ms else {
        let seen = MigrationRequest {
            seen_at_ms: Some(now_ms),
            ..request
        };
        store.update_migration_request(&seen, mod_revision).await?;
        return Ok(());
    };
    let refusal = if now_ms.saturating_sub(seen_at_ms) > REQUEST_EXPIRY.as_millis() as i64 {
        Some("request_expired")
    } else {
        admission_refusal(store, &request, members).await?
    };
    if let Some(reason) = refusal {
        if store
            .reject_migration_request(&request, mod_revision, reason)
            .await?
        {
            counter!("personhog_migration_requests_rejected_total", "reason" => reason)
                .increment(1);
            tracing::warn!(migration = %request.id, reason, "migration request rejected");
        }
        return Ok(());
    }
    // The protocol is checked with at most one draining generation.
    if !draining.is_empty() {
        if draining != request.waiting {
            tracing::info!(migration = %request.id, waiting = ?draining, "migration waiting for a generation to retire");
            let waiting = MigrationRequest {
                waiting: draining,
                ..request
            };
            store
                .update_migration_request(&waiting, mod_revision)
                .await?;
        }
        return Ok(());
    }
    let (handoffs, quiet_at) = store.list_handoffs_with_revision().await?;
    let assignments = store.list_assignments().await?;
    let ready: HashSet<&str> = pods
        .iter()
        .filter(|p| p.status == PodStatus::Ready)
        .map(|p| p.pod_name.as_str())
        .collect();
    let waiting = fleet_quiet(request.from.partitions, &assignments, &handoffs, &ready);
    if !waiting.is_empty() {
        if waiting != request.waiting {
            tracing::info!(migration = %request.id, ?waiting, "migration waiting for a quiet fleet");
            let waiting = MigrationRequest { waiting, ..request };
            store
                .update_migration_request(&waiting, mod_revision)
                .await?;
        }
        return Ok(());
    }
    if store
        .start_migration(mod_revision, quiet_at, &request.start(now_ms))
        .await?
    {
        counter!("personhog_migration_transitions_total", "to" => "freezing").increment(1);
        tracing::info!(migration = %request.id, waited_ms = now_ms - seen_at_ms, "migration started");
    }
    Ok(())
}
