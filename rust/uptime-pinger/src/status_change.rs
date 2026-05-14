use anyhow::Result;
use redis::aio::MultiplexedConnection;
use redis::AsyncCommands;
use uuid::Uuid;

pub const STATUS_UNKNOWN: &str = "unknown";

fn redis_key(monitor_id: Uuid) -> String {
    format!("uptime:monitor_status:{monitor_id}")
}

/// Compare-and-swap the cached "last known status" for a monitor. Returns the previous
/// status (or "unknown" if Redis had no entry). Mirrors the Python `_maybe_emit_status_change`
/// key convention so a flip during the Python → Rust handover doesn't fire a spurious event.
pub async fn swap_status(
    redis: &mut MultiplexedConnection,
    monitor_id: Uuid,
    new_status: &str,
) -> Result<String> {
    let key = redis_key(monitor_id);
    let previous: Option<String> = redis.get(&key).await?;
    let previous = previous.unwrap_or_else(|| STATUS_UNKNOWN.to_string());

    if previous == new_status {
        return Ok(previous);
    }

    let _: () = redis.set(&key, new_status).await?;
    Ok(previous)
}
