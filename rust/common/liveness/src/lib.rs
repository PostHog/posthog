//! Sync liveness reporting for components that must signal "I'm alive" from sync contexts
//! (e.g. rdkafka stats callbacks). Both health::HealthHandle and lifecycle::Handle implement this.

pub trait SyncLivenessReporter: Send + Sync {
    fn report_healthy(&self);
    fn report_unhealthy(&self);
}
