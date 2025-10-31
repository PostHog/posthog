use futures_util::StreamExt;
use std::{collections::HashMap, sync::Arc};
use tokio::sync::RwLock;
use tracing::{error, info, warn};

use super::types::FeatureFlagEvent;

type ClientSender = tokio::sync::mpsc::UnboundedSender<FeatureFlagEvent>;

/// Manages Redis Pub/Sub subscription for SSE feature flag updates.
///
/// This manager uses a single global Redis subscription for ALL teams:
/// - One Redis connection per pod (subscribes to "feature_flags:updates")
/// - Tracks active SSE clients by team_id
/// - Filters and broadcasts only to clients whose team matches the event
/// - Much more scalable than per-team subscriptions
pub struct SseRedisSubscriptionManager {
    /// Maps team_id -> set of client senders
    connections: Arc<RwLock<HashMap<i32, Vec<ClientSender>>>>,
    /// Global subscription task handle (only one for all teams)
    subscription_task: Arc<RwLock<Option<tokio::task::JoinHandle<()>>>>,
    /// Redis URL for creating pub/sub connections
    redis_url: String,
}

impl SseRedisSubscriptionManager {
    pub fn new(redis_url: String) -> Self {
        Self {
            connections: Arc::new(RwLock::new(HashMap::new())),
            subscription_task: Arc::new(RwLock::new(None)),
            redis_url,
        }
    }

    /// Subscribe a new client to feature flag updates for a team.
    pub async fn subscribe(&self, team_id: i32, sender: ClientSender) -> Result<(), anyhow::Error> {
        let mut connections = self.connections.write().await;
        let clients = connections.entry(team_id).or_default();
        clients.push(sender);
        let client_count = clients.len();
        let total_clients: usize = connections.values().map(|v| v.len()).sum();

        info!(
            "Added SSE client for team {}. Team clients: {}, Total clients: {}",
            team_id, client_count, total_clients
        );

        // If this is the first client overall, start the global Redis subscriber
        if total_clients == 1 {
            drop(connections); // Release lock before spawning task

            info!("Starting global Redis subscriber (first SSE client connected)");
            let task = self.spawn_global_redis_subscriber().await;

            let mut task_handle = self.subscription_task.write().await;
            *task_handle = Some(task);
        }

        Ok(())
    }

    /// Spawn a background task that subscribes to the global Redis channel for ALL teams.
    async fn spawn_global_redis_subscriber(&self) -> tokio::task::JoinHandle<()> {
        let connections = self.connections.clone();
        let redis_url = self.redis_url.clone();

        tokio::spawn(async move {
            let channel = "feature_flags:updates";

            info!(
                "Attempting to subscribe to global Redis channel: {}",
                channel
            );

            // Create a new Redis client and pub/sub connection
            let redis_client = match redis::Client::open(redis_url.as_str()) {
                Ok(client) => client,
                Err(e) => {
                    error!("Failed to create Redis client: {}", e);
                    return;
                }
            };

            let conn = match redis_client.get_async_connection().await {
                Ok(c) => c,
                Err(e) => {
                    error!("Failed to get async connection: {}", e);
                    return;
                }
            };

            let mut pubsub_conn = conn.into_pubsub();

            // Subscribe to the global channel
            if let Err(e) = pubsub_conn.subscribe(channel).await {
                error!("Failed to subscribe to {}: {}", channel, e);
                return;
            }

            info!(
                "Successfully subscribed to global Redis channel: {}",
                channel
            );

            // Listen for messages
            let mut pubsub_stream = pubsub_conn.on_message();
            loop {
                match pubsub_stream.next().await {
                    Some(msg) => {
                        // Parse the message payload
                        match msg.get_payload::<String>() {
                            Ok(payload) => {
                                print!("# message {payload}");

                                match serde_json::from_str::<FeatureFlagEvent>(&payload) {
                                    Ok(event) => {
                                        // Extract team_id from event data
                                        if let Some(team_id) =
                                            event.data.get("team_id").and_then(|v| v.as_i64())
                                        {
                                            let team_id = team_id as i32;

                                            // Only broadcast to clients for this team
                                            Self::broadcast_to_clients(
                                                team_id,
                                                event,
                                                &connections,
                                            )
                                            .await;
                                        } else {
                                            warn!("Received event without team_id: {:?}", event);
                                        }
                                    }
                                    Err(e) => {
                                        warn!("Failed to parse event: {}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                warn!("Failed to get payload: {}", e);
                            }
                        }
                    }
                    None => {
                        info!("Pub/sub stream ended");
                        break;
                    }
                }

                // Check if we still have any clients
                let conns = connections.read().await;
                if conns.is_empty() {
                    drop(conns);
                    info!("No more SSE clients, stopping global subscriber");
                    break;
                }
            }

            // Drop the stream before unsubscribing
            drop(pubsub_stream);

            // Unsubscribe
            if let Err(e) = pubsub_conn.unsubscribe(channel).await {
                error!("Failed to unsubscribe from {}: {}", channel, e);
            }

            info!("Global Redis subscriber stopped");
        })
    }

    /// Broadcast an event to all local SSE clients for a team.
    async fn broadcast_to_clients(
        team_id: i32,
        event: FeatureFlagEvent,
        connections: &Arc<RwLock<HashMap<i32, Vec<ClientSender>>>>,
    ) {
        let mut conns = connections.write().await;

        if let Some(clients) = conns.get_mut(&team_id) {
            info!(
                "Broadcasting {} event to {} clients for team {}",
                event.event_type,
                clients.len(),
                team_id
            );

            // Send to all clients and track which ones failed
            let mut dead_indices = Vec::new();

            for (idx, client) in clients.iter().enumerate() {
                if let Err(e) = client.send(event.clone()) {
                    warn!(
                        "Failed to send to client {} for team {}: {}",
                        idx, team_id, e
                    );
                    dead_indices.push(idx);
                }
            }

            // Remove dead clients (in reverse order to maintain indices)
            for idx in dead_indices.into_iter().rev() {
                clients.swap_remove(idx);
            }

            // If no clients left, remove the team entry
            if clients.is_empty() {
                conns.remove(&team_id);
                info!("Removed last client for team {}", team_id);
            }
        }
    }

    /// Get statistics about active connections and the global subscriber.
    pub async fn stats(&self) -> HashMap<String, serde_json::Value> {
        let connections = self.connections.read().await;
        let task = self.subscription_task.read().await;

        let total_clients: usize = connections.values().map(|v| v.len()).sum();
        let team_stats: HashMap<i32, usize> = connections
            .iter()
            .map(|(team_id, clients)| (*team_id, clients.len()))
            .collect();

        HashMap::from([
            (
                "total_teams".to_string(),
                serde_json::json!(connections.len()),
            ),
            (
                "total_clients".to_string(),
                serde_json::json!(total_clients),
            ),
            (
                "global_subscriber_active".to_string(),
                serde_json::json!(task.is_some()),
            ),
            ("teams".to_string(), serde_json::json!(team_stats)),
        ])
    }
}
