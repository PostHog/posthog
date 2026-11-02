//! Port of `results.ts`.

use std::fmt;
use std::sync::Arc;

use crate::context::PipelineWarning;
use crate::side_effects::SideEffect;

/// Mirrors the Node `PipelineResultType` enum, including its numeric values.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PipelineResultType {
    Ok = 0,
    Dlq = 1,
    Drop = 2,
    Redirect = 3,
    Timeout = 4,
}

impl PipelineResultType {
    /// The lowercase label the Node metrics use (`PipelineResultType[type].toLowerCase()`).
    pub fn as_label(&self) -> &'static str {
        match self {
            PipelineResultType::Ok => "ok",
            PipelineResultType::Dlq => "dlq",
            PipelineResultType::Drop => "drop",
            PipelineResultType::Redirect => "redirect",
            PipelineResultType::Timeout => "timeout",
        }
    }
}

#[derive(Debug, Clone)]
pub enum NonOk {
    Dlq {
        reason: String,
        error: Option<Arc<anyhow::Error>>,
    },
    Drop {
        reason: String,
    },
    Redirect {
        reason: String,
        output: String,
        preserve_key: bool,
        await_ack: bool,
    },
    /// The budget cut the element off. Its message is not acked, so its source redelivers it.
    Timeout {
        reason: String,
    },
}

impl NonOk {
    pub fn reason(&self) -> &str {
        match self {
            NonOk::Dlq { reason, .. }
            | NonOk::Drop { reason }
            | NonOk::Redirect { reason, .. }
            | NonOk::Timeout { reason } => reason,
        }
    }

    pub fn result_type(&self) -> PipelineResultType {
        match self {
            NonOk::Dlq { .. } => PipelineResultType::Dlq,
            NonOk::Drop { .. } => PipelineResultType::Drop,
            NonOk::Redirect { .. } => PipelineResultType::Redirect,
            NonOk::Timeout { .. } => PipelineResultType::Timeout,
        }
    }
}

#[derive(Debug, Clone)]
pub enum Outcome<T> {
    Ok(T),
    NonOk(NonOk),
}

impl<T> Outcome<T> {
    pub fn is_ok(&self) -> bool {
        matches!(self, Outcome::Ok(_))
    }

    pub fn result_type(&self) -> PipelineResultType {
        match self {
            Outcome::Ok(_) => PipelineResultType::Ok,
            Outcome::NonOk(n) => n.result_type(),
        }
    }

    pub fn value(&self) -> Option<&T> {
        match self {
            Outcome::Ok(v) => Some(v),
            Outcome::NonOk(_) => None,
        }
    }

    pub fn into_value(self) -> Option<T> {
        match self {
            Outcome::Ok(v) => Some(v),
            Outcome::NonOk(_) => None,
        }
    }

    pub fn non_ok(&self) -> Option<&NonOk> {
        match self {
            Outcome::Ok(_) => None,
            Outcome::NonOk(n) => Some(n),
        }
    }

    pub fn reason(&self) -> Option<&str> {
        self.non_ok().map(|n| n.reason())
    }

    pub fn map<U>(self, f: impl FnOnce(T) -> U) -> Outcome<U> {
        match self {
            Outcome::Ok(v) => Outcome::Ok(f(v)),
            Outcome::NonOk(n) => Outcome::NonOk(n),
        }
    }
}

/// In Node the result keeps its own copy of the side effects after the pipeline merges
/// them into the context. A `SideEffect` here is a task handle and cannot be copied, so
/// the pipeline moves them into the context instead.
pub struct PipelineResult<T> {
    pub outcome: Outcome<T>,
    pub side_effects: Vec<SideEffect>,
    pub warnings: Vec<PipelineWarning>,
}

impl<T: fmt::Debug> fmt::Debug for PipelineResult<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PipelineResult")
            .field("outcome", &self.outcome)
            .field("side_effects", &self.side_effects.len())
            .field("warnings", &self.warnings)
            .finish()
    }
}

impl<T> PipelineResult<T> {
    pub fn new(outcome: Outcome<T>) -> Self {
        Self {
            outcome,
            side_effects: Vec::new(),
            warnings: Vec::new(),
        }
    }

    pub fn with_side_effects(mut self, side_effects: Vec<SideEffect>) -> Self {
        self.side_effects.extend(side_effects);
        self
    }

    pub fn with_side_effect(mut self, side_effect: SideEffect) -> Self {
        self.side_effects.push(side_effect);
        self
    }

    pub fn with_warnings(mut self, warnings: Vec<PipelineWarning>) -> Self {
        self.warnings.extend(warnings);
        self
    }

    pub fn with_warning(mut self, warning: PipelineWarning) -> Self {
        self.warnings.push(warning);
        self
    }

    pub fn is_ok(&self) -> bool {
        self.outcome.is_ok()
    }

    pub fn result_type(&self) -> PipelineResultType {
        self.outcome.result_type()
    }

    pub fn value(&self) -> Option<&T> {
        self.outcome.value()
    }
}

pub fn ok<T>(value: T) -> PipelineResult<T> {
    PipelineResult::new(Outcome::Ok(value))
}

/// `dlq(reason, error?)`. Node defaults a missing error to `new Error(reason)` at DLQ time.
pub fn dlq<T>(reason: impl Into<String>, error: Option<anyhow::Error>) -> PipelineResult<T> {
    PipelineResult::new(Outcome::NonOk(NonOk::Dlq {
        reason: reason.into(),
        error: error.map(Arc::new),
    }))
}

pub fn drop<T>(reason: impl Into<String>) -> PipelineResult<T> {
    PipelineResult::new(Outcome::NonOk(NonOk::Drop {
        reason: reason.into(),
    }))
}

pub fn timeout<T>(reason: impl Into<String>) -> PipelineResult<T> {
    PipelineResult::new(Outcome::NonOk(NonOk::Timeout {
        reason: reason.into(),
    }))
}

/// `redirect(reason, output)` with the Node defaults `preserveKey = true`, `awaitAck = true`.
pub fn redirect<T>(reason: impl Into<String>, output: impl Into<String>) -> PipelineResult<T> {
    redirect_with(reason, output, true, true)
}

pub fn redirect_with<T>(
    reason: impl Into<String>,
    output: impl Into<String>,
    preserve_key: bool,
    await_ack: bool,
) -> PipelineResult<T> {
    PipelineResult::new(Outcome::NonOk(NonOk::Redirect {
        reason: reason.into(),
        output: output.into(),
        preserve_key,
        await_ack,
    }))
}
