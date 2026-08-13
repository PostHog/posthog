//! Test double for [`crate::WarningEmitter`], available to downstream crates'
//! dev-tests (which is why this module is not `#[cfg(test)]`-gated).

use std::sync::Mutex;
use std::time::Duration;

use serde_json::{Map, Value};

use crate::registry::WarningType;
use crate::{WarningEmitter, WarningSource};

/// One captured [`WarningEmitter::emit`] call.
#[derive(Debug, Clone, PartialEq)]
pub struct EmittedWarning {
    pub token: String,
    pub source: WarningSource,
    pub warning: WarningType,
    pub extra_details: Map<String, Value>,
    pub count: u64,
}

/// Emitter that records every call for assertions. No throttling, no I/O.
#[derive(Default)]
pub struct CollectingEmitter {
    emitted: Mutex<Vec<EmittedWarning>>,
}

impl CollectingEmitter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn emitted(&self) -> Vec<EmittedWarning> {
        self.emitted.lock().expect("emitter mutex poisoned").clone()
    }
}

impl WarningEmitter for CollectingEmitter {
    fn emit(
        &self,
        token: String,
        source: WarningSource,
        warning: WarningType,
        extra_details: Map<String, Value>,
        count: u64,
    ) {
        self.emitted
            .lock()
            .expect("emitter mutex poisoned")
            .push(EmittedWarning {
                token,
                source,
                warning,
                extra_details,
                count,
            });
    }

    fn flush(&self, _timeout: Duration) {}
}
