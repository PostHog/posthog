//! Publishes at zero the counters a bounded validation run is gated on. Depends on the metric
//! manifest plus the three modules that own the label vocabularies being primed.
//!
//! A counter that never fired is absent from `/metrics`, not zero, so a gate phrased "this stayed
//! at zero" cannot separate a clean run from a broken exporter, a renamed label, or a code path
//! that was never reached. Priming turns that reading into a provable one.
//!
//! Only counters a run is read against get primed, and each is primed across its whole label
//! vocabulary rather than the one value a gate names — a `reason` or `class` panel that breaks
//! them out should show every value it can ever show. That does put a flat zero line on those
//! panels for values production never produces.
//!
//! The two `seeder_shadow_compare_*` counters solve the same problem without priming, which is why
//! they are absent here. Their `team_id` label has no value until a chunk is scanned.
//! `seeder_shadow_compare_total` then publishes one of a closed `result` vocabulary per chunk, so
//! a clean run makes the family present, and `seeder_shadow_compare_legacy_skipped_total` is
//! incremented by zero on every path that reaches it.

use cohort_core::hogvm::VmErrorClass;
use metrics::counter;

use crate::clickhouse::ScanSkipReason;
use crate::observability::metrics::{CHUNKS_POISONED, EVENTS_SKIPPED, HOGVM_ERRORS};
use crate::store::runs::RunKind;

/// Register every label value of the gated counters at zero. Call once, after the recorder is
/// installed; without a recorder every call is a no-op.
pub fn prime_zero_series() {
    for reason in ScanSkipReason::ALL {
        counter!(EVENTS_SKIPPED, "reason" => reason.as_str()).increment(0);
    }
    for class in VmErrorClass::ALL {
        counter!(HOGVM_ERRORS, "class" => class.as_str()).increment(0);
    }
    for kind in RunKind::ALL {
        counter!(CHUNKS_POISONED, "kind" => kind.as_str()).increment(0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Renders through a real recorder rather than asserting on the loops above: whether a counter
    /// touched only with a zero increment appears in the export at all is the exporter's behavior,
    /// and that behavior is the whole point of the call.
    #[test]
    fn the_gated_counters_render_at_zero_before_anything_fires() {
        let recorder = metrics_exporter_prometheus::PrometheusBuilder::new().build_recorder();
        let handle = recorder.handle();
        metrics::with_local_recorder(&recorder, prime_zero_series);
        let rendered = handle.render();

        // The three readings a validation run is gated on: malformed blobs skipped, HogVM aborts
        // on an unresolvable reference, and chunks dead-lettered at the attempt cap.
        for series in [
            format!("{EVENTS_SKIPPED}{{reason=\"globals_parse_error\"}} 0"),
            format!("{HOGVM_ERRORS}{{class=\"unknown_ref\"}} 0"),
            format!("{CHUNKS_POISONED}{{kind=\"behavioral\"}} 0"),
        ] {
            assert!(
                rendered.contains(&series),
                "{series} is absent from the export:\n{rendered}"
            );
        }
    }
}
