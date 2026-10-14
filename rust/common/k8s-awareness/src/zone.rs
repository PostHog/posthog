use k8s_openapi::api::core::v1::Node;
use kube::api::Api;
use kube::Client;

pub const ZONE_LABEL: &str = "topology.kubernetes.io/zone";

/// Read `node_name`'s zone label. `None` when the node has no zone label.
pub async fn node_zone(client: &Client, node_name: &str) -> Result<Option<String>, kube::Error> {
    let nodes: Api<Node> = Api::all(client.clone());
    let node = nodes.get(node_name).await?;
    Ok(node
        .metadata
        .labels
        .as_ref()
        .and_then(|labels| labels.get(ZONE_LABEL))
        .cloned())
}
