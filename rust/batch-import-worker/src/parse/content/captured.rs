use anyhow::Error;
use chrono::Utc;
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use uuid::Uuid;

use super::TransformContext;

pub fn captured_parse_fn(
    context: TransformContext,
    event_transform: impl Fn(RawEvent) -> Result<Option<RawEvent>, Error>,
) -> impl Fn(RawEvent) -> Result<Option<InternallyCapturedEvent>, Error> {
    move |raw| {
        let Some(raw) = event_transform(raw)? else {
            return Ok(None);
        };
        let Some(distinct_id) = raw.extract_distinct_id() else {
            return Err(Error::msg("No distinct_id found"));
        };
        // We'll respect the events uuid if ones set
        let uuid = raw.uuid.unwrap_or_else(Uuid::now_v7);
        // Grab the events timestamp, or make one up
        let timestamp = get_timestamp(&raw);

        let inner = CapturedEvent {
            uuid,
            distinct_id,
            ip: "127.0.0.1".to_string(),
            data: serde_json::to_string(&raw)?,
            now: timestamp,
            sent_at: None, // We don't know when it was sent at, since it's a historical import
            token: context.token.clone(),
            is_cookieless_mode: false,
        };

        Ok(Some(InternallyCapturedEvent {
            team_id: context.team_id,
            inner,
        }))
    }
}

// We use the events timestamp value, if it has one, otherwise we use the current time
fn get_timestamp(event: &RawEvent) -> String {
    match &event.timestamp {
        Some(timestamp) => timestamp.clone(),
        None => Utc::now().to_rfc3339(),
    }
}
