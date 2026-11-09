//! Service-membership watching via EndpointSlices.
//!
//! Watches the EndpointSlices of one Service and publishes the set of ready
//! endpoint IPs on a `tokio::sync::watch` channel whenever membership changes.
//! This is the single shared implementation of a pattern that previously lived
//! as diverging copies in personhog-router and ingestion-consumer; consumers
//! subscribe and map IPs onto whatever they balance over (worker URLs, tonic
//! endpoints, peer rings).
//!
//! Semantics:
//! - An endpoint counts as ready when `conditions.ready` is true or absent
//!   (the K8s spec treats a nil ready field as "assume ready"); unready
//!   endpoints and unparseable addresses are skipped.
//! - State is aggregated per slice, so one slice changing doesn't clobber
//!   addresses contributed by another.
//! - On a watcher re-list (`Init`), the last published set keeps serving until
//!   `InitDone`, so subscribers never observe a transient empty set.
//! - When the watch stream ends, the watcher re-lists after a short backoff
//!   instead of dying — a frozen membership set is worse than a stale one.

use std::collections::{HashMap, HashSet};
use std::net::IpAddr;
use std::sync::Arc;
use std::time::Duration;

use futures::StreamExt;
use k8s_openapi::api::discovery::v1::EndpointSlice;
use kube::api::Api;
use kube::runtime::watcher::{self, Config as WatcherConfig, Event};
use kube::Client;
use metrics::counter;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

/// Pause before re-listing after the watcher stream closes, so a persistently
/// failing watcher degrades to a slow retry rather than a hot loop.
const WATCHER_RESTART_BACKOFF: Duration = Duration::from_secs(1);

/// Watch `service_name`'s EndpointSlices in `namespace`, publishing the ready
/// endpoint IPs on every membership change until `cancel` fires.
///
/// The receiver's initial value is the empty set, meaning "not yet known":
/// subscribers driven by `changed()` only observe real publishes, so they
/// never act on the placeholder.
pub fn watch_service_members(
    client: Client,
    namespace: String,
    service_name: String,
    cancel: CancellationToken,
) -> (watch::Receiver<HashSet<IpAddr>>, JoinHandle<()>) {
    let (tx, rx) = watch::channel(HashSet::new());
    let handle = tokio::spawn(async move {
        run(client, namespace, service_name, tx, cancel).await;
    });
    (rx, handle)
}

async fn run(
    client: Client,
    namespace: String,
    service_name: String,
    tx: watch::Sender<HashSet<IpAddr>>,
    cancel: CancellationToken,
) {
    let api: Api<EndpointSlice> = Api::namespaced(client, &namespace);
    let label_selector = format!("kubernetes.io/service-name={service_name}");
    let service_label: Arc<str> = Arc::from(service_name.as_str());

    info!(
        service = %service_name,
        namespace = %namespace,
        "starting EndpointSlice membership watch"
    );

    // Ready addresses per slice name. Kept across watcher restarts: a fresh
    // watcher re-lists from `Init`, which clears and repopulates it.
    let mut slices: HashMap<String, HashSet<IpAddr>> = HashMap::new();

    // The `kube` watcher reconnects internally on errors, so a `None` only
    // surfaces when the stream is definitively closed. Re-enter the watcher
    // rather than leaving the membership frozen until the pod restarts.
    loop {
        let config = WatcherConfig::default().labels(&label_selector);
        let stream = watcher::watcher(api.clone(), config);
        tokio::pin!(stream);

        loop {
            tokio::select! {
                _ = cancel.cancelled() => {
                    info!(service = %service_name, "EndpointSlice membership watch cancelled");
                    return;
                }
                item = stream.next() => {
                    match item {
                        Some(Ok(event)) => {
                            if let Some(desired) = apply_event(event, &mut slices) {
                                // Don't wake subscribers for no-op reconciles.
                                tx.send_if_modified(|current| {
                                    if *current == desired {
                                        false
                                    } else {
                                        *current = desired;
                                        true
                                    }
                                });
                            }
                        }
                        Some(Err(e)) => {
                            warn!(error = %e, service = %service_name, "EndpointSlice watcher error, stream will retry");
                            counter!(
                                "k8s_awareness_endpoint_watch_errors_total",
                                "service" => Arc::clone(&service_label),
                            )
                            .increment(1);
                        }
                        None => {
                            warn!(service = %service_name, "EndpointSlice watcher stream ended, restarting");
                            counter!(
                                "k8s_awareness_endpoint_watch_restarts_total",
                                "service" => Arc::clone(&service_label),
                            )
                            .increment(1);
                            break;
                        }
                    }
                }
            }
        }

        tokio::select! {
            _ = cancel.cancelled() => {
                info!(service = %service_name, "EndpointSlice membership watch cancelled");
                return;
            }
            _ = tokio::time::sleep(WATCHER_RESTART_BACKOFF) => {}
        }
    }
}

/// Parse an EndpointSlice into the set of ready endpoint IPs.
fn extract_ready_ips(slice: &EndpointSlice) -> HashSet<IpAddr> {
    let mut addrs = HashSet::new();
    for endpoint in slice.endpoints.iter() {
        let ready = endpoint
            .conditions
            .as_ref()
            .and_then(|c| c.ready)
            .unwrap_or(true);
        if !ready {
            continue;
        }
        for addr_str in &endpoint.addresses {
            if let Ok(ip) = addr_str.parse::<IpAddr>() {
                addrs.insert(ip);
            }
        }
    }
    addrs
}

fn slice_key(slice: &EndpointSlice) -> String {
    slice
        .metadata
        .name
        .clone()
        .or_else(|| slice.metadata.uid.clone())
        .unwrap_or_else(|| "unknown".to_string())
}

/// Apply a watch event to the per-slice state, returning the desired member
/// set to publish — or `None` when no update is due (the `Init` re-list start,
/// where the last published set keeps serving until `InitDone`).
fn apply_event(
    event: Event<EndpointSlice>,
    slices: &mut HashMap<String, HashSet<IpAddr>>,
) -> Option<HashSet<IpAddr>> {
    match event {
        Event::Apply(slice) | Event::InitApply(slice) => {
            slices.insert(slice_key(&slice), extract_ready_ips(&slice));
        }
        Event::Delete(slice) => {
            slices.remove(&slice_key(&slice));
        }
        Event::Init => {
            slices.clear();
            return None;
        }
        Event::InitDone => {}
    }

    Some(slices.values().flatten().copied().collect())
}

#[cfg(test)]
mod tests {
    use k8s_openapi::api::discovery::v1::{Endpoint as K8sEndpoint, EndpointConditions};
    use k8s_openapi::apimachinery::pkg::apis::meta::v1::ObjectMeta;

    use super::*;

    fn ip(s: &str) -> IpAddr {
        s.parse().unwrap()
    }

    fn endpoint(addresses: &[&str], ready: Option<bool>) -> K8sEndpoint {
        K8sEndpoint {
            addresses: addresses.iter().map(|s| s.to_string()).collect(),
            conditions: ready.map(|r| EndpointConditions {
                ready: Some(r),
                ..Default::default()
            }),
            ..Default::default()
        }
    }

    fn slice(name: &str, endpoints: Vec<K8sEndpoint>) -> EndpointSlice {
        EndpointSlice {
            metadata: ObjectMeta {
                name: Some(name.to_string()),
                ..Default::default()
            },
            address_type: "IPv4".to_string(),
            endpoints,
            ports: None,
        }
    }

    #[test]
    fn test_extract_ready_ips_ready_semantics() {
        // ready=true and absent conditions are in; ready=false and garbage
        // addresses are out. Conditions present with nil ready also count as
        // ready, per the K8s spec.
        let s = slice(
            "s1",
            vec![
                endpoint(&["10.0.0.1"], Some(true)),
                endpoint(&["10.0.0.2"], Some(false)),
                endpoint(&["10.0.0.3"], None),
                endpoint(&["not-an-ip"], Some(true)),
                K8sEndpoint {
                    addresses: vec!["10.0.0.4".to_string()],
                    conditions: Some(EndpointConditions::default()),
                    ..Default::default()
                },
            ],
        );
        assert_eq!(
            extract_ready_ips(&s),
            HashSet::from([ip("10.0.0.1"), ip("10.0.0.3"), ip("10.0.0.4")])
        );
    }

    #[test]
    fn test_apply_event_aggregates_across_slices() {
        let mut slices = HashMap::new();

        let desired = apply_event(
            Event::Apply(slice("s1", vec![endpoint(&["10.0.0.1"], Some(true))])),
            &mut slices,
        )
        .unwrap();
        assert_eq!(desired, HashSet::from([ip("10.0.0.1")]));

        let desired = apply_event(
            Event::Apply(slice("s2", vec![endpoint(&["10.0.0.2"], Some(true))])),
            &mut slices,
        )
        .unwrap();
        assert_eq!(desired, HashSet::from([ip("10.0.0.1"), ip("10.0.0.2")]));

        // Deleting one slice must not clobber the other slice's addresses.
        let desired = apply_event(Event::Delete(slice("s1", vec![])), &mut slices).unwrap();
        assert_eq!(desired, HashSet::from([ip("10.0.0.2")]));
    }

    #[test]
    fn test_apply_event_relist_keeps_serving_until_init_done() {
        let mut slices = HashMap::new();
        apply_event(
            Event::Apply(slice("s1", vec![endpoint(&["10.0.0.1"], Some(true))])),
            &mut slices,
        );

        // Init returns None — the last published set keeps serving through the
        // re-list, so subscribers never observe a transient empty set.
        assert!(apply_event(Event::Init, &mut slices).is_none());
        assert!(slices.is_empty());

        // Re-list finds a different pod; InitDone applies the new set.
        apply_event(
            Event::InitApply(slice("s1", vec![endpoint(&["10.0.0.9"], Some(true))])),
            &mut slices,
        );
        let desired = apply_event(Event::InitDone, &mut slices).unwrap();
        assert_eq!(desired, HashSet::from([ip("10.0.0.9")]));
    }
}
