//! The schema.org JSON-LD that posthog-js sends as a `$json_ld` custom event, which labels a page for evaluations.

use serde_json::Value;

use super::events::{text, DataFields};
use super::rrweb::CUSTOM;

pub const JSON_LD_EVENT_TAG: &str = "$json_ld";
/// Root types a block or session row keeps. A row with this many has this many types or more.
pub const MAX_JSON_LD_ROOT_TYPES: usize = 64;
// The limits of posthog-js's `json-ld.ts` and the replay anonymizer's `json_ld.rs`, which a payload from another
// client need not keep.
const MAX_JSON_LD_LENGTH: usize = 100_000;
const MAX_JSON_LD_TYPE_LENGTH: usize = 100;
const MAX_JSON_LD_TYPES: usize = 20;

pub fn is_json_ld_event(inner: &[u8], kind: Option<u8>, data: &DataFields) -> bool {
    kind == Some(CUSTOM) && text(inner, data.tag).as_deref() == Some(JSON_LD_EVENT_TAG)
}

/// The index stores these unsealed, so a type must have the anonymizer's shape of a schema.org term, which keeps free
/// text such as an email out.
pub fn root_types(inner: &[u8], data: &DataFields) -> Vec<String> {
    let Some((start, end)) = data.payload else {
        return Vec::new();
    };
    if end - start > MAX_JSON_LD_LENGTH {
        return Vec::new();
    }
    let Ok(payload) = serde_json::from_slice::<Value>(&inner[start..end]) else {
        return Vec::new();
    };
    let mut types = Vec::new();
    collect_root_types(&payload, &mut types);
    types
}

fn collect_root_types(value: &Value, types: &mut Vec<String>) {
    match value {
        Value::Array(roots) => {
            for root in roots {
                collect_root_types(root, types);
            }
        }
        Value::Object(root) => {
            match root.get("@type") {
                Some(Value::String(name)) => add_type(name, types),
                Some(Value::Array(names)) => {
                    for name in names.iter().filter_map(Value::as_str) {
                        add_type(name, types);
                    }
                }
                _ => {}
            }
            if let Some(graph) = root.get("@graph") {
                collect_root_types(graph, types);
            }
        }
        _ => {}
    }
}

fn add_type(name: &str, types: &mut Vec<String>) {
    let name = name
        .strip_prefix("https://schema.org/")
        .or_else(|| name.strip_prefix("http://schema.org/"))
        .unwrap_or(name);
    if types.len() < MAX_JSON_LD_TYPES && is_schema_term(name) && !types.iter().any(|t| t == name) {
        types.push(name.to_owned());
    }
}

fn is_schema_term(name: &str) -> bool {
    name.len() <= MAX_JSON_LD_TYPE_LENGTH
        && name.bytes().all(|byte| byte.is_ascii_alphanumeric())
        && name.bytes().any(|byte| byte.is_ascii_alphabetic())
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::scan::message::read_message;

    fn root_types_of(payload: serde_json::Value) -> Vec<String> {
        let items =
            json!([{"type": 5, "timestamp": 1, "data": {"tag": "$json_ld", "payload": payload}}]);
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": "s", "$snapshot_items": items}});
        let message = read_message(
            json!({"distinct_id": "d", "data": inner.to_string()})
                .to_string()
                .into_bytes(),
        )
        .unwrap();
        let event = &message.events[0];
        let data = DataFields::read(&message.inner, event);
        assert!(is_json_ld_event(&message.inner, event.kind, &data));
        root_types(&message.inner, &data)
    }

    fn names(list: &[&str]) -> Vec<String> {
        list.iter().map(|name| (*name).to_owned()).collect()
    }

    #[test]
    fn reads_the_types_of_the_roots_and_their_graph_as_schema_terms() {
        let cases = [
            (
                json!({"@context": "https://schema.org", "@type": "Product", "brand": {"@type": "Brand"}}),
                names(&["Product"]),
            ),
            (
                json!([{"@type": "https://schema.org/WebSite"}, {"@type": ["Organization", "Corporation", "Organization"]}]),
                names(&["WebSite", "Organization", "Corporation"]),
            ),
            (
                json!({"@graph": [{"@type": "BreadcrumbList"}, {"@type": "WebPage"}]}),
                names(&["BreadcrumbList", "WebPage"]),
            ),
            (
                json!([{"@type": "someone@example.com"}, {"@type": "Two words"}, {"@type": "123"}, {"@type": 7}]),
                names(&[]),
            ),
            (
                json!({"@type": "A".repeat(MAX_JSON_LD_TYPE_LENGTH + 1)}),
                vec![],
            ),
            (
                json!({"@type": (0..MAX_JSON_LD_TYPES + 5).map(|i| format!("Type{i}")).collect::<Vec<_>>()}),
                (0..MAX_JSON_LD_TYPES).map(|i| format!("Type{i}")).collect(),
            ),
            (
                json!({"name": "x".repeat(MAX_JSON_LD_LENGTH), "@type": "Product"}),
                vec![],
            ),
        ];
        for (payload, expected) in cases {
            assert_eq!(root_types_of(payload.clone()), expected, "{payload}");
        }
    }
}
