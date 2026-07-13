use std::sync::Arc;

use crate::integrations::IntegrationService;

/// Shared, cheaply-clonable application state (injected into handlers via `.with_state`).
#[derive(Clone)]
pub struct AppState {
    pub service: Arc<IntegrationService>,
    /// JWT verification secrets, newest first (primary + fallbacks). Empty => reject all requests.
    pub jwt_secrets: Arc<Vec<String>>,
    pub max_batch_size: usize,
}
