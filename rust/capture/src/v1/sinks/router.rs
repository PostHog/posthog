//! The v1 produce router: `CAPTURE_V1_SINKS` names resolved to shared
//! outputs surfaces at boot.

use std::collections::HashMap;
use std::sync::Arc;

use crate::v1::sinks::SinkName;

/// Converged v1 produce router: `CAPTURE_V1_SINKS` names resolved to shared
/// [`Outputs`](crate::outputs::Outputs) surfaces at boot. The v1 request path
/// publishes through the default surface exactly like every other ingress —
/// fallback/split/dynamic policies compose here the same way. Supersedes
/// [`Router`] (which carries the legacy v1 sink stack until it is deleted).
pub struct OutputsRouter {
    default: SinkName,
    surfaces: HashMap<SinkName, Arc<dyn crate::outputs::Outputs>>,
}

impl OutputsRouter {
    pub fn new(
        default: SinkName,
        surfaces: HashMap<SinkName, Arc<dyn crate::outputs::Outputs>>,
    ) -> Self {
        Self { default, surfaces }
    }

    pub fn default_surface(&self) -> &Arc<dyn crate::outputs::Outputs> {
        self.surfaces
            .get(&self.default)
            .expect("default sink always present (validated at boot)")
    }

    pub fn available_sinks(&self) -> Vec<SinkName> {
        self.surfaces.keys().copied().collect()
    }

    /// Flush every surface before shutdown.
    pub fn flush(&self) -> anyhow::Result<()> {
        for (name, surface) in &self.surfaces {
            surface
                .flush()
                .map_err(|e| anyhow::anyhow!("flush of v1 sink '{name}' failed: {e:#}"))?;
        }
        Ok(())
    }
}
