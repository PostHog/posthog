use std::collections::HashMap;
use std::ops::Add;
use std::sync::{Arc, RwLock};

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use std::time::Duration;
use tokio::runtime;
use tokio::sync::mpsc;
use tracing::{info, warn};

/// Health reporting for components of the service.
///
/// The capture server contains several asynchronous loops, and
/// the process can only be trusted with user data if all the
/// loops are properly running and reporting.
///
/// HealthRegistry allows an arbitrary number of components to
/// be registered and report their health. The process' health
/// status is the combination of these individual health status:
///   - if any component is unhealthy, the process is unhealthy
///   - if all components recently reported healthy, the process is healthy
///   - if a component failed to report healthy for its defined deadline,
///     it is considered unhealthy, and the check fails.
///
/// Trying to merge the k8s concepts of liveness and readiness in
/// a single state is full of foot-guns, so HealthRegistry does not
/// try to do it. Each probe should have its separate instance of
/// the registry to avoid confusions.

#[derive(Default, Debug)]
pub struct HealthStatus {
    /// The overall status: true of all components are healthy
    pub healthy: bool,
    /// Current status of each registered component, for display
    pub components: HashMap<String, ComponentStatus>,
}
impl IntoResponse for HealthStatus {
    /// Computes the axum status code based on the overall health status,
    /// and prints each component status in the body for debugging.
    fn into_response(self) -> Response {
        let body = format!("{self:?}");
        match self.healthy {
            true => (StatusCode::OK, body),
            false => (StatusCode::INTERNAL_SERVER_ERROR, body),
        }
        .into_response()
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum ComponentStatus {
    /// Automatically set when a component is newly registered
    Starting,
    /// Recently reported healthy, will need to report again before the date
    HealthyUntil(time::OffsetDateTime),
    /// Reported unhealthy
    Unhealthy,
    /// Automatically set when the HealthyUntil deadline is reached
    Stalled,
}

impl ComponentStatus {
    /// Returns true if the component is currently healthy (i.e., has a valid HealthyUntil status)
    pub fn is_healthy(&self) -> bool {
        match self {
            ComponentStatus::HealthyUntil(until) => until.gt(&time::OffsetDateTime::now_utc()),
            _ => false,
        }
    }
}

struct HealthMessage {
    component: String,
    status: ComponentStatus,
}

#[derive(Clone)]
pub struct HealthHandle {
    component: String,
    deadline: Duration,
    sender: mpsc::Sender<HealthMessage>,
}

impl HealthHandle {
    /// Asynchronously report healthy, returns when the message is queued.
    /// Must be called more frequently than the configured deadline.
    pub async fn report_healthy(&self) {
        self.report_status(ComponentStatus::HealthyUntil(
            time::OffsetDateTime::now_utc().add(self.deadline),
        ))
        .await
    }

    /// Asynchronously report component status, returns when the message is queued.
    pub async fn report_status(&self, status: ComponentStatus) {
        let message = HealthMessage {
            component: self.component.clone(),
            status,
        };
        if let Err(err) = self.sender.send(message).await {
            warn!("failed to report heath status: {}", err)
        }
    }

    /// Synchronously report as healthy, returns when the message is queued.
    /// Must be called more frequently than the configured deadline.
    pub fn report_healthy_blocking(&self) {
        self.report_status_blocking(ComponentStatus::HealthyUntil(
            time::OffsetDateTime::now_utc().add(self.deadline),
        ))
    }

    /// Synchronously report component status, returns when the message is queued.
    pub fn report_status_blocking(&self, status: ComponentStatus) {
        let message = HealthMessage {
            component: self.component.clone(),
            status,
        };
        // Don't panic if we're called from within an async context,
        // just spawn instead
        if let Ok(h) = runtime::Handle::try_current() {
            let m = self.clone();
            h.spawn(async move { m.report_status(message.status).await });
        } else if let Err(err) = self.sender.blocking_send(message) {
            warn!("failed to report heath status: {}", err)
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum HealthStrategy {
    /// All components must be healthy for the registry to be healthy
    All,
    /// At least one component must be healthy for the registry to be healthy
    Any,
}

impl std::str::FromStr for HealthStrategy {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "all" => Ok(HealthStrategy::All),
            "any" => Ok(HealthStrategy::Any),
            _ => Err(format!("Unknown Health Strategy: {s}, must be ALL or ANY")),
        }
    }
}

#[derive(Clone)]
pub struct HealthRegistry {
    name: String,
    strategy: HealthStrategy,
    components: Arc<RwLock<HashMap<String, ComponentStatus>>>,
    sender: mpsc::Sender<HealthMessage>,
}

impl HealthRegistry {
    pub fn new(name: &str) -> Self {
        Self::new_with_strategy(name, HealthStrategy::All)
    }

    pub fn new_with_strategy(name: &str, strategy: HealthStrategy) -> Self {
        let (tx, mut rx) = mpsc::channel::<HealthMessage>(16);
        let registry = Self {
            name: name.to_owned(),
            strategy,
            components: Default::default(),
            sender: tx,
        };

        let components = registry.components.clone();
        tokio::spawn(async move {
            while let Some(message) = rx.recv().await {
                if let Ok(mut map) = components.write() {
                    _ = map.insert(message.component, message.status);
                } else {
                    // Poisoned mutex: Just warn, the probes will fail and the process restart
                    warn!("poisoned HeathRegistry mutex")
                }
            }
        });

        registry
    }

    /// Registers a new component in the registry. The returned handle should be passed
    /// to the component, to allow it to frequently report its health status.
    pub async fn register<D>(&self, component: String, deadline: D) -> HealthHandle
    where
        // HACK: to let callers user time::Duration or std::time::Duration (and therefore chrono::Duration),
        // since apparently we use all three
        D: TryInto<Duration>,
    {
        let Ok(deadline) = deadline.try_into() else {
            // TODO - I should return an error here, but I don't want to refactor everything that uses this right now
            panic!("invalid deadline")
        };
        let handle = HealthHandle {
            component,
            deadline,
            sender: self.sender.clone(),
        };
        handle.report_status(ComponentStatus::Starting).await;
        handle
    }

    /// Returns the overall process status, computed from the status of all the components
    /// currently registered. Can be used as an axum handler.
    pub fn get_status(&self) -> HealthStatus {
        let components = self
            .components
            .read()
            .expect("poisoned HeathRegistry mutex");

        let result = HealthStatus {
            // unhealthy if no component has registered yet or if we're using the "Any" strategy
            // "All" defaults to true and is set to false if any healthcheck fails
            // "Any" defaults to false and is set to true if any healthcheck passes
            healthy: !components.is_empty() && self.strategy == HealthStrategy::All,
            components: Default::default(),
        };
        let now = time::OffsetDateTime::now_utc();

        let result = components
            .iter()
            .fold(result, |mut result, (name, status)| {
                match status {
                    ComponentStatus::HealthyUntil(until) => {
                        if until.gt(&now) {
                            if self.strategy == HealthStrategy::Any {
                                result.healthy = true;
                            }
                            _ = result.components.insert(name.clone(), status.clone())
                        } else {
                            if self.strategy == HealthStrategy::All {
                                result.healthy = false;
                            }
                            _ = result
                                .components
                                .insert(name.clone(), ComponentStatus::Stalled)
                        }
                    }
                    _ => {
                        if self.strategy == HealthStrategy::All {
                            result.healthy = false;
                        }
                        _ = result.components.insert(name.clone(), status.clone())
                    }
                }
                result
            });
        match result.healthy {
            true => info!("{} health check ok", self.name),
            false => warn!("{} health check failed: {:?}", self.name, result.components),
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use crate::{ComponentStatus, HealthRegistry, HealthStatus, HealthStrategy};
    use axum::http::StatusCode;
    use axum::response::IntoResponse;
    use std::ops::{Add, Sub};
    use time::{Duration, OffsetDateTime};

    async fn assert_or_retry<F>(check: F)
    where
        F: Fn() -> bool,
    {
        assert_or_retry_for_duration(check, Duration::seconds(5)).await
    }

    async fn assert_or_retry_for_duration<F>(check: F, timeout: Duration)
    where
        F: Fn() -> bool,
    {
        let deadline = OffsetDateTime::now_utc().add(timeout);
        while !check() && OffsetDateTime::now_utc().lt(&deadline) {
            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        }
        assert!(check())
    }
    #[tokio::test]
    async fn defaults_to_unhealthy() {
        let registry = HealthRegistry::new("liveness");
        assert!(!registry.get_status().healthy);
    }

    #[tokio::test]
    async fn one_component() {
        let registry = HealthRegistry::new("liveness");

        // New components are registered in Starting
        let handle = registry
            .register("one".to_string(), Duration::seconds(30))
            .await;
        assert_or_retry(|| registry.get_status().components.len() == 1).await;
        let mut status = registry.get_status();
        assert!(!status.healthy);
        assert_eq!(
            status.components.get("one"),
            Some(&ComponentStatus::Starting)
        );

        // Status goes healthy once the component reports
        handle.report_healthy().await;
        assert_or_retry(|| registry.get_status().healthy).await;
        status = registry.get_status();
        assert_eq!(status.components.len(), 1);

        // Status goes unhealthy if the components says so
        handle.report_status(ComponentStatus::Unhealthy).await;
        assert_or_retry(|| !registry.get_status().healthy).await;
        status = registry.get_status();
        assert_eq!(status.components.len(), 1);
        assert_eq!(
            status.components.get("one"),
            Some(&ComponentStatus::Unhealthy)
        );
    }

    #[tokio::test]
    async fn staleness_check() {
        let registry = HealthRegistry::new("liveness");
        let handle = registry
            .register("one".to_string(), Duration::seconds(30))
            .await;

        // Status goes healthy once the component reports
        handle.report_healthy().await;
        assert_or_retry(|| registry.get_status().healthy).await;
        let mut status = registry.get_status();
        assert_eq!(status.components.len(), 1);

        // If the component's ping is too old, it is considered stalled and the healthcheck fails
        // FIXME: we should mock the time instead
        handle
            .report_status(ComponentStatus::HealthyUntil(
                OffsetDateTime::now_utc().sub(Duration::seconds(1)),
            ))
            .await;
        assert_or_retry(|| !registry.get_status().healthy).await;
        status = registry.get_status();
        assert_eq!(status.components.len(), 1);
        assert_eq!(
            status.components.get("one"),
            Some(&ComponentStatus::Stalled)
        );
    }

    #[tokio::test]
    async fn several_components() {
        let registry = HealthRegistry::new("liveness");
        let handle1 = registry
            .register("one".to_string(), Duration::seconds(30))
            .await;
        let handle2 = registry
            .register("two".to_string(), Duration::seconds(30))
            .await;
        assert_or_retry(|| registry.get_status().components.len() == 2).await;

        // First component going healthy is not enough
        handle1.report_healthy().await;
        assert_or_retry(|| {
            registry.get_status().components.get("one").unwrap() != &ComponentStatus::Starting
        })
        .await;
        assert!(!registry.get_status().healthy);

        // Second component going healthy brings the health to green
        handle2.report_healthy().await;
        assert_or_retry(|| {
            registry.get_status().components.get("two").unwrap() != &ComponentStatus::Starting
        })
        .await;
        assert!(registry.get_status().healthy);

        // First component going unhealthy takes down the health to red
        handle1.report_status(ComponentStatus::Unhealthy).await;
        assert_or_retry(|| !registry.get_status().healthy).await;

        // First component recovering returns the health to green
        handle1.report_healthy().await;
        assert_or_retry(|| registry.get_status().healthy).await;

        // Second component going unhealthy takes down the health to red
        handle2.report_status(ComponentStatus::Unhealthy).await;
        assert_or_retry(|| !registry.get_status().healthy).await;
    }

    #[tokio::test]
    async fn into_response() {
        let nok = HealthStatus::default().into_response();
        assert_eq!(nok.status(), StatusCode::INTERNAL_SERVER_ERROR);

        let ok = HealthStatus {
            healthy: true,
            components: Default::default(),
        }
        .into_response();
        assert_eq!(ok.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn any_strategy() {
        let registry = HealthRegistry::new_with_strategy("liveness", HealthStrategy::Any);
        let handle1 = registry
            .register("one".to_string(), Duration::seconds(30))
            .await;
        let handle2 = registry
            .register("two".to_string(), Duration::seconds(30))
            .await;
        assert_or_retry(|| registry.get_status().components.len() == 2).await;

        // Initially unhealthy with Any strategy
        assert!(!registry.get_status().healthy);

        // First component going healthy is enough in Any strategy
        handle1.report_healthy().await;
        assert_or_retry(|| registry.get_status().healthy).await;

        // Still healthy even if second component is unhealthy
        handle2.report_status(ComponentStatus::Unhealthy).await;
        assert_or_retry(|| registry.get_status().healthy).await;

        // Becomes unhealthy only when all components are unhealthy
        handle1.report_status(ComponentStatus::Unhealthy).await;
        assert_or_retry(|| !registry.get_status().healthy).await;
    }

    #[tokio::test]
    async fn health_strategy_from_str() {
        assert_eq!(
            "ALL".parse::<HealthStrategy>().unwrap(),
            HealthStrategy::All
        );
        assert_eq!(
            "ANY".parse::<HealthStrategy>().unwrap(),
            HealthStrategy::Any
        );
        assert_eq!(
            "all".parse::<HealthStrategy>().unwrap(),
            HealthStrategy::All
        );
        assert_eq!(
            "any".parse::<HealthStrategy>().unwrap(),
            HealthStrategy::Any
        );
        assert!("invalid".parse::<HealthStrategy>().is_err());
    }
}
