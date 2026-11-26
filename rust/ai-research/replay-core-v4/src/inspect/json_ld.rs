//! The schema.org JSON-LD that posthog-js sends as a `$json_ld` custom event, which labels a page for evaluations.

use std::collections::HashSet;
use std::sync::LazyLock;

use serde_json::{Map, Value};

use super::events::{text, DataFields};
use super::rrweb::CUSTOM;

pub const JSON_LD_EVENT_TAG: &str = "$json_ld";
/// Root types a block or session row keeps. A row with this many has this many types or more.
pub const MAX_JSON_LD_ROOT_TYPES: usize = 64;
// The limits of posthog-js's `json-ld.ts` and the replay anonymizer's `json_ld.rs`, which a payload from another
// client need not keep.
const MAX_JSON_LD_LENGTH: usize = 100_000;
const MAX_JSON_LD_TYPES: usize = 20;

static KNOWN_TYPES: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    include_str!("../json_ld_types.txt")
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .collect()
});

pub fn is_json_ld_event(inner: &[u8], kind: Option<u8>, data: &DataFields) -> bool {
    kind == Some(CUSTOM) && text(inner, data.tag).as_deref() == Some(JSON_LD_EVENT_TAG)
}

/// The recorder reads the payload before any scrub, so it takes types only from a payload the anonymizer would keep,
/// whose every root names the schema.org context, and only types in `json_ld_types.txt`.
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
    let Some(roots) = schema_roots(&payload) else {
        return Vec::new();
    };
    let mut types = Vec::new();
    for root in roots {
        add_entity_types(root, &mut types);
        match root.get("@graph") {
            Some(Value::Array(items)) => {
                for item in items.iter().filter_map(Value::as_object) {
                    add_entity_types(item, &mut types);
                }
            }
            Some(Value::Object(item)) => add_entity_types(item, &mut types),
            _ => {}
        }
    }
    types
}

fn schema_roots(payload: &Value) -> Option<Vec<&Map<String, Value>>> {
    let roots: Vec<_> = match payload {
        Value::Array(items) if !items.is_empty() => {
            items.iter().map(Value::as_object).collect::<Option<_>>()?
        }
        Value::Object(root) => vec![root],
        _ => return None,
    };
    roots
        .iter()
        .all(|root| root.get("@context").is_some_and(is_schema_context))
        .then_some(roots)
}

fn is_schema_context(value: &Value) -> bool {
    matches!(
        value.as_str(),
        Some(
            "https://schema.org"
                | "https://schema.org/"
                | "http://schema.org"
                | "http://schema.org/"
        )
    )
}

fn add_entity_types(entity: &Map<String, Value>, types: &mut Vec<String>) {
    let names: Vec<&str> = match entity.get("@type") {
        Some(Value::String(name)) => vec![name],
        Some(Value::Array(names)) => names.iter().filter_map(Value::as_str).collect(),
        _ => return,
    };
    let mut seen = HashSet::new();
    let known = names
        .into_iter()
        .map(|name| {
            name.strip_prefix("https://schema.org/")
                .or_else(|| name.strip_prefix("http://schema.org/"))
                .unwrap_or(name)
        })
        .filter(|name| KNOWN_TYPES.contains(name) && seen.insert(*name))
        .take(MAX_JSON_LD_TYPES);
    for name in known {
        if !types.iter().any(|t| t == name) {
            types.push(name.to_owned());
        }
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::scan::message::read_message;

    fn root_types_of(payload: Value) -> Vec<String> {
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

    #[test]
    fn reads_the_known_types_of_schema_roots_and_their_graph() {
        let schema = "https://schema.org";
        let cases: [(Value, &[&str]); 9] = [
            (
                json!({"@context": schema, "@type": "Product", "brand": {"@type": "Brand"}}),
                &["Product"],
            ),
            (
                json!([{"@context": schema, "@type": "https://schema.org/WebSite"}, {"@context": "http://schema.org/", "@type": ["Organization", "Corporation", "Organization"]}]),
                &["WebSite", "Organization", "Corporation"],
            ),
            (
                json!({"@context": schema, "@graph": [{"@type": "BreadcrumbList"}, {"@type": "WebPage"}, "someone@example.com"]}),
                &["BreadcrumbList", "WebPage"],
            ),
            (
                json!({"@context": schema, "@graph": [{"@type": "JaneDoe1984"}, {"@type": "someone@example.com"}, {"@type": "PrivateType"}, {"@type": 7}]}),
                &[],
            ),
            (
                json!({"@context": "https://example.com", "@type": "Product"}),
                &[],
            ),
            (json!({"@type": "Product"}), &[]),
            (
                json!([{"@context": schema, "@type": "Product"}, {"@context": "https://example.com", "@type": "Organization"}]),
                &[],
            ),
            (json!([[{"@context": schema, "@type": "Product"}]]), &[]),
            (
                json!({"@context": schema, "name": "x".repeat(MAX_JSON_LD_LENGTH), "@type": "Product"}),
                &[],
            ),
        ];
        for (payload, expected) in cases {
            assert_eq!(root_types_of(payload.clone()), expected, "{payload}");
        }
    }

    #[test]
    fn keeps_at_most_the_contracts_type_count_of_one_entity() {
        let mut names: Vec<&str> = KNOWN_TYPES.iter().copied().collect();
        names.sort_unstable();
        let types = root_types_of(
            json!({"@context": "https://schema.org", "@type": names, "@graph": [{"@type": names[MAX_JSON_LD_TYPES]}]}),
        );
        assert_eq!(types, names[..=MAX_JSON_LD_TYPES]);
    }

    #[test]
    fn knows_the_types_of_the_shared_json_ld_contract() {
        let contract: Value = serde_json::from_str(include_str!(
            "../../../../replay-anonymizer/tests/fixtures/json-ld-sanitization-v1.json"
        ))
        .unwrap();
        assert_eq!(contract["limits"]["maxTypes"], MAX_JSON_LD_TYPES);
        assert_eq!(contract["limits"]["maxSourceLength"], MAX_JSON_LD_LENGTH);
        let mut listed: Vec<&str> = contract["typeSets"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|set| set["name"] != "unsupported type")
            .flat_map(|set| set["types"].as_array().unwrap())
            .map(|name| name.as_str().unwrap())
            .collect();
        listed.sort_unstable();
        listed.dedup();
        let mut known: Vec<&str> = KNOWN_TYPES.iter().copied().collect();
        known.sort_unstable();
        assert_eq!(known, listed);
    }
}
