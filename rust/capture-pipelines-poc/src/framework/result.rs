//! Verdict vocabulary: the per-event decision every step returns.
//!
//! The framework core is built around one uniform result type, [`StepResult`], and
//! a per-pipeline set of redirect targets, [`Outputs`]. These mirror the Node
//! ingestion framework's `ok | drop | dlq | redirect` semantics, but the redirect
//! target set is part of the pipeline's *type* rather than a runtime string — so a
//! pipeline that can redirect to an unconfigured output fails to compile (see
//! [`OutputRegistry::check`](crate::framework::outputs::OutputRegistry::check)).

use std::fmt;

/// The set of redirect targets a pipeline can produce, defined per pipeline as a
/// plain `enum`.
///
/// [`NoOutputs`] is the uninhabited implementation for steps that never redirect —
/// the type-level equivalent of "this step's redirect set is empty".
///
/// `ALL` lets output wiring iterate every variant at startup without reflection;
/// for the POC a hand-written const slice is plenty (a derive macro would generate
/// it in the real framework).
pub trait Outputs: Copy + Eq + fmt::Debug + 'static {
    /// Every variant of this output set. Used by
    /// [`OutputRegistry::check`](crate::framework::outputs::OutputRegistry::check) to
    /// prove every redirect target has a configured topic.
    const ALL: &'static [Self];

    /// Stable name used as a metric label and registry key.
    fn name(&self) -> &'static str;
}

/// The uninhabited output set: a step declaring `type Outputs = NoOutputs` can never
/// emit a [`StepResult::Redirect`]. Because it has no values, it lifts into *any*
/// other output set for free (see
/// [`IntoOutputs`](crate::framework::chain::IntoOutputs)).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum NoOutputs {}

impl Outputs for NoOutputs {
    const ALL: &'static [Self] = &[];

    fn name(&self) -> &'static str {
        // Unreachable: `NoOutputs` has no inhabitants.
        match *self {}
    }
}

/// The per-event decision returned by a step.
///
/// - `Continue(T)` — the (possibly type-changed) event proceeds to the next step.
/// - `Drop` — the event is discarded; no produce, just a counter + debug log.
/// - `Dlq` — the event is routed to the dead-letter topic with provenance headers.
/// - `Redirect` — the event is produced to one of the pipeline's typed `Outputs`
///   (e.g. an overflow topic), optionally preserving the partition key.
///
/// `reason` fields are `&'static str` so they can be used directly as low-cardinality
/// metric labels, matching the Node framework's `details` vocabulary.
pub enum StepResult<T, O: Outputs> {
    /// Event proceeds, carrying its (possibly enriched) state `T`.
    Continue(T),
    /// Event discarded. `reason` becomes the `drop_cause` metric label.
    Drop {
        /// Low-cardinality, static reason for the drop.
        reason: &'static str,
    },
    /// Event routed to the dead-letter queue. `reason` becomes the `dlq_reason` label.
    Dlq {
        /// Low-cardinality, static reason for dead-lettering.
        reason: &'static str,
    },
    /// Event redirected to a typed output (overflow, custom topic, ...).
    Redirect {
        /// Which of the pipeline's outputs to produce to.
        output: O,
        /// Preserve the Kafka partition key (else round-robin via a null key).
        preserve_key: bool,
    },
}

impl<T, O: Outputs> StepResult<T, O> {
    /// The coarse verdict category, for observers and metrics (see [`VerdictKind`]).
    pub fn kind(&self) -> VerdictKind {
        match self {
            StepResult::Continue(_) => VerdictKind::Continue,
            StepResult::Drop { .. } => VerdictKind::Drop,
            StepResult::Dlq { .. } => VerdictKind::Dlq,
            StepResult::Redirect { .. } => VerdictKind::Redirect,
        }
    }

    /// `true` if the event proceeds to the next step.
    pub fn is_continue(&self) -> bool {
        matches!(self, StepResult::Continue(_))
    }

    /// The event state if this is a `Continue`, else `None`.
    pub fn continued(self) -> Option<T> {
        match self {
            StepResult::Continue(t) => Some(t),
            _ => None,
        }
    }
}

/// The coarse verdict category — what an observer or metric sees, without the payload.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum VerdictKind {
    /// Event proceeds.
    Continue,
    /// Event discarded.
    Drop,
    /// Event dead-lettered.
    Dlq,
    /// Event redirected to a typed output.
    Redirect,
}

impl VerdictKind {
    /// Stable metric-label name for this verdict.
    pub fn as_str(&self) -> &'static str {
        match self {
            VerdictKind::Continue => "continue",
            VerdictKind::Drop => "drop",
            VerdictKind::Dlq => "dlq",
            VerdictKind::Redirect => "redirect",
        }
    }
}
