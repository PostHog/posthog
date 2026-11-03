use std::ops::{Deref, DerefMut};
use std::sync::Arc;

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

use crate::budget::BatchBudget;
use crate::results::{NonOk, Outcome, PipelineResult};
use crate::side_effects::SideEffect;

/// Keys keep insertion order, as in a JavaScript object, and re-inserting a key keeps its place.
pub type WarningDetails = IndexMap<String, serde_json::Value>;

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
    /// A `json!` object has sorted keys without serde_json's `preserve_order`, so use `with_detail` where key order matters.
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

    pub fn with_detail(
        mut self,
        key: impl Into<String>,
        value: impl Into<serde_json::Value>,
    ) -> Self {
        self.details.insert(key.into(), value.into());
        self
    }
}

/// Node spreads `C` into the context. Here `C` lives in `data` behind `Deref`, and `message_id` lives here so batching keeps the type.
pub struct PipelineContext<C> {
    pub data: C,
    pub last_step: Option<Arc<str>>,
    pub debug_context: Option<serde_json::Value>,
    pub budget: Option<BatchBudget>,
    pub message_id: Option<u64>,
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

    // Boxing the error side would allocate for each non-OK result on every step.
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

pub fn create_ok_context<T, C>(value: T, data: C) -> OkResultWithContext<T, C> {
    OkResultWithContext {
        value,
        context: PipelineContext::new(data),
    }
}

pub type ChunkResults<T, C> = Vec<ResultWithContext<T, C>>;
