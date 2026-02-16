pub(crate) const METRIC_SHUTDOWN_INITIATED: &str = "lifecycle_shutdown_initiated_total";
pub(crate) const METRIC_SHUTDOWN_COMPLETED: &str = "lifecycle_shutdown_completed_total";
pub(crate) const METRIC_COMPONENT_SHUTDOWN_DURATION: &str =
    "lifecycle_component_shutdown_duration_seconds";
pub(crate) const METRIC_COMPONENT_SHUTDOWN_RESULT: &str =
    "lifecycle_component_shutdown_result_total";
pub(crate) const METRIC_COMPONENT_HEALTHY: &str = "lifecycle_component_healthy";

pub(crate) fn emit_shutdown_initiated(app: &str, trigger_component: &str, trigger_reason: &str) {
    metrics::counter!(
        METRIC_SHUTDOWN_INITIATED,
        "app" => app.to_string(),
        "trigger_component" => trigger_component.to_string(),
        "trigger_reason" => trigger_reason.to_string()
    )
    .increment(1);
}

pub(crate) fn emit_shutdown_completed(app: &str, clean: bool) {
    metrics::counter!(
        METRIC_SHUTDOWN_COMPLETED,
        "app" => app.to_string(),
        "clean" => clean.to_string()
    )
    .increment(1);
}

pub(crate) fn emit_component_shutdown_duration(
    app: &str,
    component: &str,
    result: &str,
    duration_secs: f64,
) {
    metrics::histogram!(
        METRIC_COMPONENT_SHUTDOWN_DURATION,
        "app" => app.to_string(),
        "component" => component.to_string(),
        "result" => result.to_string()
    )
    .record(duration_secs);
}

pub(crate) fn emit_component_shutdown_result(app: &str, component: &str, result: &str) {
    metrics::counter!(
        METRIC_COMPONENT_SHUTDOWN_RESULT,
        "app" => app.to_string(),
        "component" => component.to_string(),
        "result" => result.to_string()
    )
    .increment(1);
}

pub(crate) fn emit_component_healthy(app: &str, component: &str, healthy: bool) {
    metrics::gauge!(
        METRIC_COMPONENT_HEALTHY,
        "app" => app.to_string(),
        "component" => component.to_string()
    )
    .set(if healthy { 1.0 } else { 0.0 });
}
