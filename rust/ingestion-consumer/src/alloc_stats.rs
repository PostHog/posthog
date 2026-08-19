//! Export jemalloc's allocator counters as Prometheus gauges.
//!
//! RSS alone cannot say whether the process is holding live data or whether
//! jemalloc is sitting on pages it has already freed. `resident - allocated`
//! separates the two: the gap is allocator retention (dirty pages kept for
//! reuse, plus fragmentation), while `allocated` is what the program actually
//! holds. Without it, every RSS swing looks like a leak.
//!
//! Only compiled where jemalloc is the global allocator — see
//! `common_alloc::DefaultAllocator`, which falls back to the system allocator
//! on msvc.

use std::time::Duration;

use metrics::gauge;
use tikv_jemalloc_ctl::{epoch, stats};
use tracing::warn;

/// Bytes handed out by the allocator and not yet freed — the program's live
/// footprint.
const ALLOCATED_BYTES: &str = "jemalloc_allocated_bytes";

/// Bytes in pages jemalloc has allocated to its arenas. Exceeds
/// `allocated_bytes` by the current fragmentation.
const ACTIVE_BYTES: &str = "jemalloc_active_bytes";

/// Bytes mapped and physically backed, including jemalloc's own overhead. The
/// allocator's share of process RSS.
const RESIDENT_BYTES: &str = "jemalloc_resident_bytes";

/// Bytes of address space mapped by the allocator, backed or not.
const MAPPED_BYTES: &str = "jemalloc_mapped_bytes";

/// Bytes of address space retained after being freed back — unmapped in effect,
/// but held for reuse rather than returned to the OS. Counts against virtual
/// size, not RSS.
const RETAINED_BYTES: &str = "jemalloc_retained_bytes";

/// Bytes jemalloc spends on its own bookkeeping.
const METADATA_BYTES: &str = "jemalloc_metadata_bytes";

/// How often the gauges are refreshed. Each refresh advances jemalloc's epoch,
/// which recomputes the cached counters — cheap, but not free, so keep it in
/// the same range as the Prometheus scrape interval.
const REFRESH_INTERVAL: Duration = Duration::from_secs(15);

/// Spawn the background task that refreshes the gauges until the process exits.
pub fn spawn_reporter() {
    tokio::spawn(async {
        let mut ticker = tokio::time::interval(REFRESH_INTERVAL);
        loop {
            ticker.tick().await;
            if let Err(err) = report_once() {
                warn!(error = %err, "Failed to read jemalloc stats");
            }
        }
    });
}

/// Advance jemalloc's epoch (its stats are cached until asked to refresh), then
/// publish the refreshed counters.
fn report_once() -> Result<(), tikv_jemalloc_ctl::Error> {
    epoch::advance()?;

    gauge!(ALLOCATED_BYTES).set(stats::allocated::read()? as f64);
    gauge!(ACTIVE_BYTES).set(stats::active::read()? as f64);
    gauge!(RESIDENT_BYTES).set(stats::resident::read()? as f64);
    gauge!(MAPPED_BYTES).set(stats::mapped::read()? as f64);
    gauge!(RETAINED_BYTES).set(stats::retained::read()? as f64);
    gauge!(METADATA_BYTES).set(stats::metadata::read()? as f64);

    Ok(())
}
