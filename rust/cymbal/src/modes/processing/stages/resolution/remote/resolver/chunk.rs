//! Build remote routing keys. Work is submitted per exception; this module
//! keeps only the routing-key helpers shared with the pool.

use crate::{
    langs::native::DebugImage,
    types::{
        exception_event::{ExceptionEvent, Parsed},
        Exception,
    },
};

/// Return one routing key per exception in event order.
pub(super) fn routing_keys_for_event(evt: &ExceptionEvent<Parsed>) -> Vec<String> {
    evt.exception_list
        .iter()
        .map(|exception| routing_key_for_exception(evt.team_id(), exception, evt.debug_images()))
        .collect()
}

fn routing_key_for_exception(
    team_id: i32,
    exception: &Exception,
    debug_images: &[DebugImage],
) -> String {
    exception
        .get_raw_frame()
        .iter()
        .find_map(|frame| frame.symbol_set_ref(debug_images))
        .map(|symbol_set_ref| format!("team:{team_id}:symbol:{symbol_set_ref}"))
        .unwrap_or_else(|| team_routing_key(team_id))
}

fn team_routing_key(team_id: i32) -> String {
    format!("team:{team_id}")
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use serde_json::json;
    use uuid::Uuid;

    use super::*;
    use crate::types::event::AnyEvent;

    fn event(properties: serde_json::Value) -> ExceptionEvent<Parsed> {
        AnyEvent {
            uuid: Uuid::now_v7(),
            event: "$exception".to_string(),
            team_id: 7,
            timestamp: String::new(),
            properties,
            others: HashMap::new(),
        }
        .try_into()
        .expect("valid exception properties")
    }

    #[test]
    fn routing_key_uses_first_symbol_set_ref() {
        let evt = event(json!({
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
        }));
        assert_eq!(routing_keys_for_event(&evt), vec!["team:7:symbol:chunk-a"]);
    }

    #[test]
    fn routing_key_falls_back_to_team_without_symbol_set_ref() {
        let evt = event(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom"
            }]
        }));
        assert_eq!(routing_keys_for_event(&evt), vec!["team:7"]);
    }

    #[test]
    fn routing_keys_are_per_exception() {
        let evt = event(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom-a",
                "stacktrace": {
                    "type": "raw",
                    "frames": [{
                        "platform": "web:javascript",
                        "filename": "https://example.com/app-a.js",
                        "function": "minified",
                        "lineno": 1,
                        "colno": 2,
                        "chunk_id": "chunk-a"
                    }]
                }
            }, {
                "type": "Error",
                "value": "boom-b",
                "stacktrace": {
                    "type": "raw",
                    "frames": [{
                        "platform": "web:javascript",
                        "filename": "https://example.com/app-b.js",
                        "function": "minified",
                        "lineno": 1,
                        "colno": 2,
                        "chunk_id": "chunk-b"
                    }]
                }
            }, {
                "type": "Error",
                "value": "boom-c"
            }]
        }));

        assert_eq!(
            routing_keys_for_event(&evt),
            vec!["team:7:symbol:chunk-a", "team:7:symbol:chunk-b", "team:7",]
        );
    }
}
