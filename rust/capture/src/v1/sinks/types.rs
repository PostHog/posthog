use std::borrow::Cow;
use std::collections::HashMap;
use std::fmt;

use uuid::Uuid;

/// Kafka topic routing for a processed event.
/// `Drop` means the event should not be produced at all.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum Destination {
    #[default]
    AnalyticsMain,
    AnalyticsHistorical,
    Overflow,
    Dlq,
    Custom(String),
    Drop,
}

// ---------------------------------------------------------------------------
// Outcome
// ---------------------------------------------------------------------------

/// What happened when a publish attempt resolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Success,
    Timeout,
    RetriableError,
    FatalError,
}

impl Outcome {
    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Timeout => "timeout",
            Self::RetriableError => "retriable_error",
            Self::FatalError => "fatal_error",
        }
    }
}

// ---------------------------------------------------------------------------
// SinkResult
// ---------------------------------------------------------------------------

/// Backend-agnostic trait for introspecting per-event publish results.
pub trait SinkResult: Send + Sync {
    /// Correlation key -- the originating event's UUID.
    fn key(&self) -> Uuid;

    fn outcome(&self) -> Outcome;

    /// Stable, low-cardinality tag for metrics. None on success.
    fn cause(&self) -> Option<&'static str>;

    /// Rich human-readable error detail for logging. None on success.
    fn detail(&self) -> Option<Cow<'_, str>>;

    /// Time between batch enqueue and this event's ack completion.
    /// None if the event never entered the ack path (immediate error).
    fn elapsed(&self) -> Option<std::time::Duration>;
}

// ---------------------------------------------------------------------------
// BatchSummary
// ---------------------------------------------------------------------------

/// Aggregated stats for a batch of publish results.
pub struct BatchSummary {
    pub total: usize,
    pub succeeded: usize,
    pub retriable: usize,
    pub fatal: usize,
    pub timed_out: usize,
    /// Counts keyed by cause tag (e.g. "queue_full", "timeout").
    pub errors: HashMap<&'static str, usize>,
}

impl BatchSummary {
    pub fn from_results(results: &[Box<dyn SinkResult>]) -> Self {
        let mut succeeded = 0usize;
        let mut retriable = 0usize;
        let mut fatal = 0usize;
        let mut timed_out = 0usize;
        let mut errors: HashMap<&'static str, usize> = HashMap::new();

        for r in results {
            match r.outcome() {
                Outcome::Success => succeeded += 1,
                Outcome::Timeout => {
                    timed_out += 1;
                    if let Some(tag) = r.cause() {
                        *errors.entry(tag).or_default() += 1;
                    }
                }
                Outcome::RetriableError => {
                    retriable += 1;
                    if let Some(tag) = r.cause() {
                        *errors.entry(tag).or_default() += 1;
                    }
                }
                Outcome::FatalError => {
                    fatal += 1;
                    if let Some(tag) = r.cause() {
                        *errors.entry(tag).or_default() += 1;
                    }
                }
            }
        }

        Self {
            total: results.len(),
            succeeded,
            retriable,
            fatal,
            timed_out,
            errors,
        }
    }

    pub fn all_ok(&self) -> bool {
        self.retriable == 0 && self.fatal == 0 && self.timed_out == 0
    }
}

impl fmt::Display for BatchSummary {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{} total, {} ok, {} retriable, {} fatal, {} timed_out",
            self.total, self.succeeded, self.retriable, self.fatal, self.timed_out
        )?;
        if !self.errors.is_empty() {
            let mut pairs: Vec<_> = self.errors.iter().collect();
            pairs.sort_by_key(|(_, count)| std::cmp::Reverse(**count));
            write!(f, " (")?;
            for (i, (tag, count)) in pairs.iter().enumerate() {
                if i > 0 {
                    write!(f, ", ")?;
                }
                write!(f, "{}={}", tag, count)?;
            }
            write!(f, ")")?;
        }
        Ok(())
    }
}
