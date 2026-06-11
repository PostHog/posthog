//! Group remote events by routing key. Work is submitted per exception; this
//! module keeps only the routing-key helpers shared with the pool.

use std::collections::BTreeMap;

use crate::types::exception_properties::ExceptionProperties;

use super::RemoteEvent;

/// Group events by their per-team routing key. `BTreeMap` keeps the key
/// iteration order deterministic.
pub(super) fn group_events_by_key(events: Vec<RemoteEvent>) -> BTreeMap<String, Vec<RemoteEvent>> {
    let mut by_key: BTreeMap<String, Vec<RemoteEvent>> = BTreeMap::new();
    for event in events {
        by_key
            .entry(routing_key_for_event(&event.evt))
            .or_default()
            .push(event);
    }
    by_key
}

fn routing_key_for_event(evt: &ExceptionProperties) -> String {
    // Per-team routing: every exception of an event hashes to the same pod
    // via rendezvous selection in `EndpointPool::select_for_key`. One team's
    // bursts land on one preferred pod. Overload spillover is driven by
    // per-item outcomes from the resolver.
    format!("team:{}", evt.team_id)
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    #[test]
    fn routing_key_is_per_team_regardless_of_exception_internals() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom",
                "stacktrace": {
                    "type": "raw",
                    "frames": [{
                        "platform": "web:javascript",
                        "filename": "https://example.com/app.js",
                        "function": "minified",
                        "lineno": 1,
                        "colno": 2,
                        "chunk_id": "chunk-a"
                    }]
                }
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 7;
        assert_eq!(routing_key_for_event(&evt), "team:7");
    }

    #[test]
    fn group_events_by_key_separates_events_by_team() {
        let events = vec![
            fake_remote_event(1, 0, 1),
            fake_remote_event(2, 1, 1),
            fake_remote_event(1, 2, 1),
            fake_remote_event(2, 3, 1),
        ];
        let grouped = group_events_by_key(events);
        let keys: Vec<&String> = grouped.keys().collect();
        assert_eq!(keys, vec!["team:1", "team:2"]);
        assert_eq!(grouped["team:1"].len(), 2);
        assert_eq!(grouped["team:2"].len(), 2);
    }

    fn fake_remote_event(team_id: i32, batch_index: usize, n_exceptions: usize) -> RemoteEvent {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": (0..n_exceptions)
                .map(|i| json!({
                    "type": "Error",
                    "value": format!("boom-{i}"),
                }))
                .collect::<Vec<_>>()
        }))
        .expect("valid exception properties");
        evt.team_id = team_id;
        evt.uuid = Uuid::from_u128(0xABCD_0000_0000_0000 ^ (batch_index as u128));

        let exception_jsons = evt
            .exception_list
            .iter()
            .map(|exc| serde_json::to_vec(exc).expect("serialize exception"))
            .collect();
        RemoteEvent {
            batch_index,
            evt,
            exception_jsons,
            metadata: Vec::new(),
        }
    }
}
