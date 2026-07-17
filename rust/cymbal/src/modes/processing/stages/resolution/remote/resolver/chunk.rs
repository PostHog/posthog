//! Build remote routing keys. Work is submitted per exception; this module
//! keeps only the routing-key helpers shared with the pool.

use crate::{
    langs::native::DebugImage,
    types::{exception_properties::ExceptionProperties, Exception},
};

/// Return one routing key per exception in event order.
pub(super) fn routing_keys_for_event(evt: &ExceptionProperties) -> Vec<String> {
    evt.exception_list
        .iter()
        .map(|exception| {
            routing_key_for_exception(evt.team_id, exception, evt.debug_images.as_ref())
        })
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
    use serde_json::json;

    use super::*;

    #[test]
    fn routing_key_uses_first_symbol_set_ref() {
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
        assert_eq!(routing_keys_for_event(&evt), vec!["team:7:symbol:chunk-a"]);
    }

    #[test]
    fn routing_key_falls_back_to_team_without_symbol_set_ref() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom"
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 7;
        assert_eq!(routing_keys_for_event(&evt), vec!["team:7"]);
    }

    #[test]
    fn routing_keys_are_per_exception() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
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
        }))
        .expect("valid exception properties");
        evt.team_id = 7;

        assert_eq!(
            routing_keys_for_event(&evt),
            vec!["team:7:symbol:chunk-a", "team:7:symbol:chunk-b", "team:7",]
        );
    }
}
