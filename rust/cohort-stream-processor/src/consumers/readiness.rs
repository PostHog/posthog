//! The processor's readiness gate, the answer behind `/_ready`.
//!
//! The pod can carry live traffic once three things hold: the filter catalog has loaded, the events
//! consumer has finished boot recovery, and no worker is still rebuilding its eviction queue. A
//! StatefulSet rolling update moves to the next pod as soon as this one reads ready, so an early
//! answer would put two pods into catch-up at once.

use std::fmt;
use std::sync::Arc;

use tokio::sync::{watch, SetOnce};

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
    rebuilding: watch::Sender<usize>,
}

impl BootReadiness {
    pub fn new(catalog: Arc<CatalogHandle>) -> Arc<Self> {
        Arc::new(Self {
            catalog,
            live: SetOnce::new(),
            rebuilding: watch::Sender::new(0),
        })
    }

    pub fn check(&self) -> Result<(), NotReady> {
        if !self.catalog.is_loaded() {
            return Err(NotReady::CatalogNotLoaded);
        }
        if !self.live.initialized() {
            return Err(NotReady::Booting);
        }
        let rebuilding = *self.rebuilding.borrow();
        match rebuilding {
            0 => Ok(()),
            partitions => Err(NotReady::Rebuilding { partitions }),
        }
    }

    /// Boot recovery has ended, so consumers may dispatch. The events consumer calls this once.
    pub(crate) fn mark_live(&self) {
        // Setting it twice is harmless: the gate is open either way.
        let _ = self.live.set(());
    }

    /// Resolve once the catalog has loaded and boot recovery has ended, so no worker a consumer
    /// spawns runs while boot recovery writes to the store.
    pub async fn wait_until_dispatchable(&self) {
        self.catalog.wait_until_loaded().await;
        self.live.wait().await;
    }

    /// Resolve once [`Self::check`] reads ready. Boot registers every worker's rebuild before it
    /// ends, so after that the count only falls.
    pub async fn wait_until_ready(&self) {
        self.wait_until_dispatchable().await;
        self.rebuilding
            .subscribe()
            .wait_for(|&rebuilding| rebuilding == 0)
            .await
            .expect("the sender lives in self, so the channel never closes");
    }

    pub fn rebuild_started(self: &Arc<Self>) -> RebuildGuard {
        self.rebuilding.send_modify(|rebuilding| *rebuilding += 1);
        RebuildGuard(self.clone())
    }
}

/// One eviction-queue rebuild in flight. Dropping it, also by a panic, ends the count.
#[must_use = "the rebuild counts as running until this guard drops"]
pub struct RebuildGuard(Arc<BootReadiness>);

impl Drop for RebuildGuard {
    fn drop(&mut self) {
        self.0.rebuilding.send_modify(|rebuilding| *rebuilding -= 1);
    }
}

#[cfg(test)]
mod tests {
    use std::pin::pin;

    use futures::FutureExt;

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
        let mut ready = pin!(readiness.wait_until_ready());
        assert_eq!(ready.as_mut().now_or_never(), None);

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
        assert_eq!(ready.as_mut().now_or_never(), None);

        let rebuild = tokio::spawn(async move {
            let _guard = panicked;
            panic!("rebuild scan panicked");
        });
        assert!(rebuild.await.unwrap_err().is_panic());
        assert_eq!(readiness.check(), Ok(()));
        assert_eq!(ready.now_or_never(), Some(()));
    }
}
