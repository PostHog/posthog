//! The migration saga's actions: the coordinator's driver passes and the leaders' seal duty.

use super::*;

impl HandoffModel {
    fn held_handoffs(state: &SystemState) -> Vec<(Partition, Handoff)> {
        state
            .handoffs
            .iter()
            .filter(|(_, h)| h.held)
            .map(|(p, h)| (*p, h.clone()))
            .collect()
    }

    pub(super) fn set_phase(state: &mut SystemState, next: MigrationPhase) {
        let migration = state.migration.as_mut().expect("a migration is in flight");
        assert!(
            migration.phase.may_transition_to(next),
            "{:?} -> {next:?}",
            migration.phase
        );
        migration.phase = next;
    }

    fn insert_handoff(state: &mut SystemState, p: Partition, handoff: Handoff) {
        Self::clear_acks(state, p);
        state.handoffs.insert(p, handoff);
    }

    /// `migration::reconcile`, one pass.
    pub(super) fn migrate_drive(&self, last: &SystemState) -> Option<SystemState> {
        let migration = last.migration?;
        mutate(last, |state| match migration.phase {
            MigrationPhase::Freezing => self.drive_freeze(state, migration),
            MigrationPhase::Draining => self.drive_drain(state, migration),
            MigrationPhase::Sealing => Self::drive_seal(state, migration),
            MigrationPhase::Resuming => self.drive_resume(state, migration),
            MigrationPhase::Cancelling => Self::drive_unwind(state, migration),
            MigrationPhase::Complete | MigrationPhase::Cancelled => {
                state.migration = None;
            }
        })
    }

    /// `Pass::freeze`, through the production `plan_freeze`.
    fn drive_freeze(&self, state: &mut SystemState, migration: Migration) {
        let from = migration.from;
        let handoffs: Vec<HandoffState> = state
            .handoffs
            .iter()
            .map(|(p, h)| production_handoff(*p, h))
            .collect();
        let registered = Self::registered_names(state);
        let registered: HashSet<&str> = registered.iter().map(String::as_str).collect();
        let plan = plan_freeze(
            from.partitions as u32,
            &production_assignments(state),
            &handoffs,
            &registered,
        );
        if self.freeze_checks_strays && plan.stray_handoff.is_some() {
            Self::set_phase(state, MigrationPhase::Cancelling);
            return;
        }
        if plan.holder_died.is_some() {
            Self::set_phase(state, MigrationPhase::Cancelling);
            return;
        }
        let quorum = Self::quorum_snapshot(state);
        for (p, owner) in plan.holds {
            let id = state.next_handoff_id;
            state.next_handoff_id += 1;
            let owner = pod_id(&owner);
            state.handoffs.insert(
                p as Partition,
                Handoff {
                    id,
                    old_owner: Some(owner),
                    new_owner: owner,
                    phase: Phase::Freezing,
                    quorum: quorum.clone(),
                    held: true,
                    config_epoch: from.epoch,
                },
            );
        }
        if plan.blocking.is_empty() {
            Self::set_phase(state, MigrationPhase::Draining);
        }
    }

    /// `Pass::drain`: every hold drained, else a dead holder cancels.
    fn drive_drain(&self, state: &mut SystemState, _migration: Migration) {
        let registered = production_registered(state);
        let mut blocked = false;
        for (p, h) in Self::held_handoffs(state) {
            if !state.pods[&h.new_owner].registered {
                Self::set_phase(state, MigrationPhase::Cancelling);
                return;
            }
            if h.phase == Phase::Freezing {
                blocked = true;
                continue;
            }
            let acks = self.production_drained_acks(state, p);
            blocked |= !drain_satisfied(&registered, &acks, &production_handoff(p, &h));
        }
        if !blocked {
            Self::set_phase(state, MigrationPhase::Sealing);
        }
    }

    /// `Pass::seal`: the flip once every old partition is sealed, as one transaction.
    fn drive_seal(state: &mut SystemState, migration: Migration) {
        let acks = production_seal_acks(state);
        if !migration_unsealed(&acks, MIGRATION_ID, migration.from.partitions as u32).is_empty() {
            return;
        }
        let next = Generation {
            partitions: migration.to,
            epoch: state.config.live.epoch + 1,
        };
        for p in 0..next.partitions {
            state.changelogs.entry((next.epoch, p)).or_default();
        }
        state.config = Config {
            live: next,
            draining: Some(migration.from),
        };
        state.seal_overdue = false;
        Self::set_phase(state, MigrationPhase::Resuming);
    }

    /// `Pass::resume`: holds become restarts at Warming, shrunk partitions
    /// dissolve, grown ones are placed; then Complete once settled.
    fn drive_resume(&self, state: &mut SystemState, migration: Migration) {
        let to = migration.to;
        let epoch = state.config.live.epoch;
        let held = Self::held_handoffs(state);
        if !held.is_empty() {
            let holds: Vec<(u32, String)> = held
                .iter()
                .map(|(p, h)| (*p as u32, pod_name(h.new_owner)))
                .collect();
            let handoffs: Vec<HandoffState> = state
                .handoffs
                .iter()
                .map(|(p, h)| production_handoff(*p, h))
                .collect();
            let names = Self::registered_names(state);
            let registered: HashSet<&str> = names.iter().map(String::as_str).collect();
            let plan = plan_resume(
                &StickyBalancedStrategy,
                &self.planner_members(state),
                to as u32,
                &holds,
                &production_assignments(state),
                &handoffs,
                &registered,
            );
            for p in plan.dissolve {
                let p = p as Partition;
                Self::clear_acks(state, p);
                state.handoffs.remove(&p);
                state.assignments.remove(&p);
            }
            for p in plan.abandon {
                let p = p as Partition;
                Self::clear_acks(state, p);
                state.handoffs.remove(&p);
            }
            for (p, holder) in plan.restart {
                let id = state.next_handoff_id;
                state.next_handoff_id += 1;
                let holder = pod_id(&holder);
                Self::insert_handoff(
                    state,
                    p as Partition,
                    Handoff {
                        id,
                        old_owner: Some(holder),
                        new_owner: holder,
                        phase: Phase::Warming,
                        quorum: BTreeSet::new(),
                        held: false,
                        config_epoch: epoch,
                    },
                );
            }
            let quorum = Self::quorum_snapshot(state);
            for (p, owner) in plan.place {
                let id = state.next_handoff_id;
                state.next_handoff_id += 1;
                state.handoffs.insert(
                    p as Partition,
                    Handoff {
                        id,
                        old_owner: None,
                        new_owner: pod_id(&owner),
                        phase: Phase::Freezing,
                        quorum: quorum.clone(),
                        held: false,
                        config_epoch: epoch,
                    },
                );
            }
            return;
        }
        let handoffs: Vec<HandoffState> = state
            .handoffs
            .iter()
            .map(|(p, h)| production_handoff(*p, h))
            .collect();
        let registered = Self::registered_names(state);
        let registered: HashSet<&str> = registered.iter().map(String::as_str).collect();
        let unsettled = migration_unsettled(
            &production_assignments(state),
            &handoffs,
            &registered,
            to as u32,
        );
        if unsettled.is_empty() {
            state.migration = None;
            state.seal_acks.clear();
            state.migration_completed = true;
        }
    }

    /// `Pass::unwind`: each hold becomes a Complete reaffirm, then the record is archived.
    fn drive_unwind(state: &mut SystemState, migration: Migration) {
        let held = Self::held_handoffs(state);
        if held.is_empty() {
            state.migration = None;
            state.seal_acks.clear();
            state.migration_cancelled = true;
            return;
        }
        for (p, h) in held {
            if !state.pods[&h.new_owner].registered {
                Self::clear_acks(state, p);
                state.handoffs.remove(&p);
                continue;
            }
            let id = state.next_handoff_id;
            state.next_handoff_id += 1;
            Self::insert_handoff(
                state,
                p,
                Handoff {
                    id,
                    old_owner: None,
                    new_owner: h.new_owner,
                    phase: Phase::Complete,
                    quorum: BTreeSet::new(),
                    held: false,
                    config_epoch: migration.from.epoch,
                },
            );
        }
    }

    /// `SealDuty::tick`: seal every target not yet sealed, then rewrite the ack.
    pub(super) fn seal_tick(&self, last: &SystemState, x: PodId) -> Option<SystemState> {
        let migration = last.migration?;
        let from = migration.from;
        let targets: Vec<Partition> = match self.seal_rule {
            SealRule::Assignment => {
                let registered = Self::registered_names(last);
                let registered: HashSet<&str> = registered.iter().map(String::as_str).collect();
                seal_targets(
                    &pod_name(x),
                    MIGRATION_ID,
                    from.partitions as u32,
                    &production_assignments(last),
                    &registered,
                    &production_seal_acks(last),
                    last.seal_overdue,
                )
                .into_iter()
                .map(|p| p as Partition)
                .collect()
            }
            SealRule::Residency => (0..from.partitions)
                .filter(|p| {
                    let orphaned = last
                        .assignments
                        .get(p)
                        .is_none_or(|owner| !last.pods[owner].registered);
                    last.pods[&x].warmed.contains_key(p) || orphaned
                })
                .collect(),
        };
        let pod = &last.pods[&x];
        let newly: Vec<Partition> = targets
            .iter()
            .copied()
            .filter(|p| !pod.sealed.contains(p))
            .collect();
        // `SealDuty::tick`: everything this pod sealed stays reported.
        let acked: BTreeSet<Partition> = pod.sealed.iter().chain(newly.iter()).copied().collect();
        let unloaded = newly.iter().any(|p| !pod.warmed.contains_key(p));
        mutate(last, |state| {
            for p in &newly {
                // `init_transactions` by the sealer, then its producer is dropped.
                state
                    .changelogs
                    .get_mut(&(from.epoch, *p))
                    .unwrap()
                    .epoch_holder = None;
                state.pods.get_mut(&x).unwrap().sealed.insert(*p);
            }
            if unloaded {
                state.sealed_without_warm = true;
            }
            state.seal_acks.insert(x, acked);
        })
    }
}
