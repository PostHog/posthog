//! Trigger ingestion (plan §2.7): two sources, one sink, one consistency rule.
//!
//! The **sweep** ([`sweep`]) is the correctness backbone — it polls the
//! authoritative `{cache_key}:etag` keys on a fixed cadence. The **hints**
//! ([`hints`]) path is the latency fast path — a pub/sub wake-up confirmed against
//! Redis before it is announced. Both feed [`apply_observation`], which drives the
//! [`TopicRegistry`] state machine and records the trigger truth-table metric.
//!
//! The consistency rule: **all trigger reads go to each tier's primary endpoint**
//! (plan §2.7). Because ETags are unordered content hashes, mixing replica reads
//! would reintroduce `Known(new) → Known(old)` flapping; the primary orders
//! `SET etag` before its `PUBLISH`, so a hint can never arrive before its etag is
//! readable.

pub mod hints;
pub mod sweep;

use std::collections::HashMap;
use std::sync::Arc;

use common_hypercache::HyperCacheReader;

use crate::domain::{CacheKind, Observation, Topic};
use crate::metrics;
use crate::registry::{ApplyOutcome, TopicRegistry};

/// Which trigger source produced an observation — the `source` metric label.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TriggerSource {
    Sweep,
    Hint,
}

impl TriggerSource {
    fn as_str(self) -> &'static str {
        match self {
            TriggerSource::Sweep => metrics::SOURCE_SWEEP,
            TriggerSource::Hint => metrics::SOURCE_HINT,
        }
    }
}

/// One Redis tier the gateway triggers against.
///
/// In shared-only mode a single tier hosts both kinds (and both ready channels);
/// in two-tier mode each kind lives on its own tier. `readers` holds the
/// primary-pinned [`HyperCacheReader`] per kind on this tier, so both the sweep
/// and the hint confirm-read use exactly the reader (and key layout) the rest of
/// the fleet does.
#[derive(Clone)]
pub struct Tier {
    pub name: &'static str,
    pub kinds: Vec<CacheKind>,
    /// This tier's primary URL, for the hints pub/sub subscriber connection.
    pub pubsub_url: String,
    pub readers: HashMap<CacheKind, Arc<HyperCacheReader>>,
}

/// Apply one observation to the registry and record its resolved outcome (plan
/// §2.10). The single sink both trigger sources funnel through.
pub fn apply_observation(
    registry: &TopicRegistry,
    topic: Topic,
    obs: Observation,
    source: TriggerSource,
) -> ApplyOutcome {
    let outcome = registry.apply(topic, obs);
    metrics::observation(topic.kind, source.as_str(), classify(obs, outcome));
    outcome
}

/// Record a decode failure **without** touching the state machine — a corrupt
/// Redis value or malformed hint must never enter the version state (plan §2.7).
pub fn record_decode_error(kind: CacheKind, source: TriggerSource) {
    metrics::observation(kind, source.as_str(), "decode_error");
}

/// Resolve the `outcome` metric label from the observation and the registry's
/// [`ApplyOutcome`].
///
/// A `Present` that changed state is `changed`; one that matched is `unchanged`
/// (the spurious-rebuild suppression signal). An `Absent` that changed state to
/// `Missing` is `absent` (the cache just disappeared); a steady `Missing → Missing`
/// is `unchanged`, so a persistently-missing cache is not re-counted as `absent`
/// every tick.
fn classify(obs: Observation, outcome: ApplyOutcome) -> &'static str {
    match outcome {
        ApplyOutcome::NoSubscribers => "no_subscribers",
        ApplyOutcome::Unchanged => "unchanged",
        ApplyOutcome::Changed => match obs {
            Observation::Present(_) => "changed",
            Observation::Absent => "absent",
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::Etag;
    use std::str::FromStr;

    fn etag() -> Etag {
        Etag::from_str("0123456789abcdef").expect("valid etag")
    }

    #[test]
    fn classify_covers_the_outcome_label_space() {
        assert_eq!(
            classify(Observation::Present(etag()), ApplyOutcome::Changed),
            "changed"
        );
        assert_eq!(
            classify(Observation::Present(etag()), ApplyOutcome::Unchanged),
            "unchanged"
        );
        // A transition to Missing is "absent"; a steady Missing is "unchanged".
        assert_eq!(
            classify(Observation::Absent, ApplyOutcome::Changed),
            "absent"
        );
        assert_eq!(
            classify(Observation::Absent, ApplyOutcome::Unchanged),
            "unchanged"
        );
        assert_eq!(
            classify(Observation::Absent, ApplyOutcome::NoSubscribers),
            "no_subscribers"
        );
    }
}
