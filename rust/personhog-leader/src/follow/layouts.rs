use std::collections::HashMap;
use std::sync::{Mutex, PoisonError};

/// Keeps builds under different changelog configs from overlapping.
///
/// Pending marks are keyed by person, and a mark from another partition replaces the one
/// held. After a partition-count change a person can belong to another partition, so a
/// build of the old layout that marked beside one of the new layout could replace their
/// newer mark with an older one. A build therefore marks nothing while a build under an
/// older config is still in flight, and none starts under a config older than the newest.
#[derive(Default)]
pub struct Layouts {
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    /// The newest config epoch a build was admitted under.
    newest: u64,
    next_id: u64,
    /// The epoch of each build in flight.
    in_flight: HashMap<u64, u64>,
}

/// A build in flight, until dropped.
pub struct Building<'a> {
    layouts: &'a Layouts,
    id: u64,
}

impl Layouts {
    /// Register a build under `epoch`. `None` when a build under a newer config was
    /// already admitted: this one would be of an old layout.
    pub fn admit(&self, epoch: u64) -> Option<Building<'_>> {
        let mut state = self.lock();
        if epoch < state.newest {
            return None;
        }
        state.newest = epoch;
        let id = state.next_id;
        state.next_id += 1;
        state.in_flight.insert(id, epoch);
        Some(Building { layouts: self, id })
    }

    /// Whether a build under a config older than `epoch` is still in flight. A build
    /// under `epoch` waits for it before it marks anything.
    pub fn older_in_flight(&self, epoch: u64) -> bool {
        self.lock().in_flight.values().any(|older| *older < epoch)
    }

    /// Whether a build under a newer config than `epoch` was admitted since.
    pub fn superseded(&self, epoch: u64) -> bool {
        self.newest() > epoch
    }

    /// The newest config epoch a build was admitted under.
    pub fn newest(&self) -> u64 {
        self.lock().newest
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for Building<'_> {
    fn drop(&mut self) {
        self.layouts.lock().in_flight.remove(&self.id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_newer_build_waits_for_older_ones_and_no_older_one_starts_after_it() {
        let layouts = Layouts::default();
        let older = layouts.admit(1).expect("the first build");
        let same = layouts.admit(1).expect("another build of the same layout");

        let newer = layouts.admit(2).expect("a newer layout");
        assert!(layouts.superseded(1));
        assert!(layouts.admit(1).is_none());

        // The newer build waits for every older one, and not for its own layout.
        assert!(layouts.older_in_flight(2));
        drop(older);
        assert!(layouts.older_in_flight(2));
        drop(same);
        assert!(!layouts.older_in_flight(2));

        let beside = layouts.admit(2).expect("another build of the newer layout");
        assert!(!layouts.older_in_flight(2));
        assert!(!layouts.superseded(2));
        drop((newer, beside));
        assert!(layouts.admit(1).is_none());
    }
}
