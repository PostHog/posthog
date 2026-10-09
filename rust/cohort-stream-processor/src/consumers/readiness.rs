//! The processor's readiness gate, the answer behind `/_ready`.
//!
//! The pod can carry live traffic once three things hold: the filter catalog has loaded, the events
//! consumer has finished boot recovery, and no worker is still rebuilding its eviction queue. A
//! StatefulSet rolling update moves to the next pod as soon as this one reads ready, so an early
//! answer would put two pods into catch-up at once.

use std::fmt;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use tokio::sync::SetOnce;

use crate::filters::manager::CatalogHandle;

/// Why the processor cannot carry live traffic yet. `Display` is the `/_ready` 503 body.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotReady {
    CatalogNotLoaded,
    Booting,
    Rebuilding { partitions: usize },
}

impl fmt::Display for NotReady {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CatalogNotLoaded => f.write_str("filter catalog not loaded"),
            Self::Booting => f.write_str("events consumer boot recovery in progress"),
            Self::Rebuilding { partitions } => {
                write!(
                    f,
                    "eviction queue rebuild in progress on {partitions} partitions"
                )
            }
        }
    }
}

pub struct BootReadiness {
    catalog: Arc<CatalogHandle>,
    live: SetOnce<()>,
    rebuilding: AtomicUsize,
}

impl BootReadiness {
    pub fn new(catalog: Arc<CatalogHandle>) -> Arc<Self> {
        Arc::new(Self {
            catalog,
            live: SetOnce::new(),
            rebuilding: AtomicUsize::new(0),
        })
    }

    pub fn check(&self) -> Result<(), NotReady> {
        if !self.catalog.is_loaded() {
            return Err(NotReady::CatalogNotLoaded);
        }
        if !self.live.initialized() {
            return Err(NotReady::Booting);
        }
        match self.rebuilding.load(Ordering::Acquire) {
            0 => Ok(()),
            partitions => Err(NotReady::Rebuilding { partitions }),
        }
    }

    /// Boot recovery has ended, so consumers may dispatch. The events consumer calls this once.
    pub(crate) fn mark_live(&self) {
        // Setting it twice is harmless: the gate is open either way.
        let _ = self.live.set(());
    }

    /// Resolve once boot recovery has ended; immediate if it already has.
    pub async fn wait_until_live(&self) {
        self.live.wait().await;
    }

    pub fn rebuild_started(self: &Arc<Self>) -> RebuildGuard {
        self.rebuilding.fetch_add(1, Ordering::AcqRel);
        RebuildGuard(self.clone())
    }
}

/// One eviction-queue rebuild in flight. Dropping it, also by a panic, ends the count.
#[must_use = "the rebuild counts as running until this guard drops"]
pub struct RebuildGuard(Arc<BootReadiness>);

impl Drop for RebuildGuard {
    fn drop(&mut self) {
        self.0.rebuilding.fetch_sub(1, Ordering::AcqRel);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::filters::FilterCatalog;

    #[test]
    fn an_unloaded_catalog_keeps_the_gate_closed_even_after_boot() {
        let readiness = BootReadiness::new(Arc::new(CatalogHandle::new()));
        readiness.mark_live();

        assert_eq!(readiness.check(), Err(NotReady::CatalogNotLoaded));
    }

    #[tokio::test]
    async fn the_gate_opens_only_after_boot_and_every_rebuild_including_a_panicked_one() {
        let readiness =
            BootReadiness::new(Arc::new(CatalogHandle::from_catalog(FilterCatalog::new())));
        assert_eq!(readiness.check(), Err(NotReady::Booting));

        let finished = readiness.rebuild_started();
        let panicked = readiness.rebuild_started();
        readiness.mark_live();
        assert_eq!(
            readiness.check(),
            Err(NotReady::Rebuilding { partitions: 2 })
        );

        drop(finished);
        assert_eq!(
            readiness.check(),
            Err(NotReady::Rebuilding { partitions: 1 })
        );

        let rebuild = tokio::spawn(async move {
            let _guard = panicked;
            panic!("rebuild scan panicked");
        });
        assert!(rebuild.await.unwrap_err().is_panic());
        assert_eq!(readiness.check(), Ok(()));
    }
}
