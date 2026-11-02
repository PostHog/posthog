//! Port of `pipeline.interface.ts` and `chunk-pipeline.interface.ts` (the data types).

use std::ops::{Deref, DerefMut};
use std::sync::Arc;

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

use crate::budget::BatchBudget;
use crate::results::{NonOk, Outcome, PipelineResult};
use crate::side_effects::SideEffect;

/// The details of a warning. Keys keep insertion order, as a JavaScript object does, and
/// `insert` of a present key keeps its place.
pub type WarningDetails = IndexMap<String, serde_json::Value>;

/// Port of `IngestionWarning`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PipelineWarning {
    #[serde(rename = "type")]
    pub warning_type: String,
    pub details: WarningDetails,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pipeline_step: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
    #[serde(default)]
    pub always_send: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
}

impl PipelineWarning {
    /// Takes the keys of `details` in the order of its map. A `json!` object has sorted
    /// keys unless the build enables serde_json's `preserve_order`, so use `with_detail`
    /// where the key order of the message matters.
    pub fn new(warning_type: impl Into<String>, details: serde_json::Value) -> Self {
        Self {
            warning_type: warning_type.into(),
            details: match details {
                serde_json::Value::Object(map) => map.into_iter().collect(),
                _ => WarningDetails::new(),
            },
            pipeline_step: None,
            key: None,
            always_send: false,
            source: None,
        }
    }

    /// Appends a detail, or replaces the value of a present key in its place.
    pub fn with_detail(
        mut self,
        key: impl Into<String>,
        value: impl Into<serde_json::Value>,
    ) -> Self {
        self.details.insert(key.into(), value.into());
        self
    }
}

/// Port of `PipelineContext<C>`. Node spreads the user context `C` into the same object
/// as the framework fields. Here `C` lives in `data`, and `Deref` exposes its fields.
///
/// `message_id` is part of `BatchingContext` in Node. It lives here so that the
/// batching pipeline does not change the context type.
pub struct PipelineContext<C> {
    pub data: C,
    pub last_step: Option<Arc<str>>,
    pub debug_context: Option<serde_json::Value>,
    /// Absent outside a fed batch.
    pub budget: Option<BatchBudget>,
    pub message_id: Option<u64>,
    /// Work that outlives the step, drained with the batch. A side effect should not fail.
    pub side_effects: Vec<SideEffect>,
    pub warnings: Vec<PipelineWarning>,
}

impl<C> PipelineContext<C> {
    pub fn new(data: C) -> Self {
        Self {
            data,
            last_step: None,
            debug_context: None,
            budget: None,
            message_id: None,
            side_effects: Vec::new(),
            warnings: Vec::new(),
        }
    }

    pub fn last_step(&self) -> Option<&str> {
        self.last_step.as_deref()
    }

    /// Replaces the user context and keeps the framework fields.
    pub fn map_data<D>(self, f: impl FnOnce(C) -> D) -> PipelineContext<D> {
        PipelineContext {
            data: f(self.data),
            last_step: self.last_step,
            debug_context: self.debug_context,
            budget: self.budget,
            message_id: self.message_id,
            side_effects: self.side_effects,
            warnings: self.warnings,
        }
    }

    /// Records a finished step: sets `last_step` and moves in the step's side effects and warnings.
    pub(crate) fn absorb_step<T>(
        &mut self,
        step_name: &Arc<str>,
        result: PipelineResult<T>,
    ) -> Outcome<T> {
        self.last_step = Some(step_name.clone());
        self.side_effects.extend(result.side_effects);
        self.warnings.extend(result.warnings);
        result.outcome
    }
}

impl<C: Default> Default for PipelineContext<C> {
    fn default() -> Self {
        Self::new(C::default())
    }
}

impl<C> Deref for PipelineContext<C> {
    type Target = C;
    fn deref(&self) -> &C {
        &self.data
    }
}

impl<C> DerefMut for PipelineContext<C> {
    fn deref_mut(&mut self) -> &mut C {
        &mut self.data
    }
}

impl<C: std::fmt::Debug> std::fmt::Debug for PipelineContext<C> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PipelineContext")
            .field("data", &self.data)
            .field("last_step", &self.last_step)
            .field("message_id", &self.message_id)
            .field("side_effects", &self.side_effects.len())
            .field("warnings", &self.warnings)
            .finish()
    }
}

/// Port of `PipelineResultWithContext<T, C>`.
#[derive(Debug)]
pub struct ResultWithContext<T, C> {
    pub result: Outcome<T>,
    pub context: PipelineContext<C>,
}

impl<T, C> ResultWithContext<T, C> {
    pub fn is_ok(&self) -> bool {
        self.result.is_ok()
    }

    pub fn value(&self) -> Option<&T> {
        self.result.value()
    }

    /// Splits an OK result into its feedable form, or returns the non-OK outcome.
    // The split moves the context by value on every step; boxing the error side would
    // allocate for each non-OK result.
    #[allow(clippy::result_large_err)]
    pub fn into_ok(self) -> Result<OkResultWithContext<T, C>, (NonOk, PipelineContext<C>)> {
        match self.result {
            Outcome::Ok(value) => Ok(OkResultWithContext {
                value,
                context: self.context,
            }),
            Outcome::NonOk(non_ok) => Err((non_ok, self.context)),
        }
    }

    pub(crate) fn non_ok<U>(non_ok: NonOk, context: PipelineContext<C>) -> ResultWithContext<U, C> {
        ResultWithContext {
            result: Outcome::NonOk(non_ok),
            context,
        }
    }
}

/// Port of `OkResultWithContext<T, C>`: the only shape that can be fed into a pipeline.
#[derive(Debug)]
pub struct OkResultWithContext<T, C> {
    pub value: T,
    pub context: PipelineContext<C>,
}

impl<T, C> OkResultWithContext<T, C> {
    pub fn into_result(self) -> ResultWithContext<T, C> {
        ResultWithContext {
            result: Outcome::Ok(self.value),
            context: self.context,
        }
    }
}

/// Port of `createOkContext(value, partialContext)`.
pub fn create_ok_context<T, C>(value: T, data: C) -> OkResultWithContext<T, C> {
    OkResultWithContext {
        value,
        context: PipelineContext::new(data),
    }
}

/// A chunk of results, as `next()` returns it.
pub type ChunkResults<T, C> = Vec<ResultWithContext<T, C>>;
