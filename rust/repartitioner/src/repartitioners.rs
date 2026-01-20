use anyhow::{Context, Result};
use rdkafka::message::BorrowedHeaders;

/// "propdefs_v1" repartitioning function uses Team ID as the destination
/// partition key, and tries to minimize deserialization overhead to obtain it
pub fn compute_propdefs_v1_key_by_team_id(
    _source_key: Option<&[u8]>,
    _headers: Option<&BorrowedHeaders>,
    payload: Option<&[u8]>,
) -> Result<Vec<u8>> {
    let payload = payload.context("propdefs_v1: message payload is required")?;

    // Parse to generic Value instead of full struct - only parses JSON structure
    let json_value = serde_json::from_slice::<serde_json::Value>(payload)
        .context("propdefs_v1: failed to parse JSON")?;

    // Extract only the team_id field we need
    let team_id: i64 = json_value
        .get("team_id")
        .and_then(|v| v.as_i64())
        .context("propdefs_v1: team_id field missing or invalid")?;

    // Convert to bytes for partition key
    let destination_key = team_id.to_string().into_bytes();

    Ok(destination_key)
}
