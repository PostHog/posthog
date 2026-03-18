use serde_json::Value;

/// A classifier checks a single span attribute and maps its value to a PostHog
/// event name. Classifiers are tried in order; the first match wins.
struct EventClassifier {
    attr_key: &'static str,
    classify: fn(&str) -> &'static str,
}

fn classify_gen_ai_operation(op: &str) -> &'static str {
    match op {
        "chat" => "$ai_generation",
        "embeddings" => "$ai_embedding",
        _ => "$ai_span",
    }
}

fn classify_vercel_ai_operation(op_id: &str) -> &'static str {
    match op_id {
        s if s.ends_with(".doGenerate") || s.ends_with(".doStream") => "$ai_generation",
        s if s == "ai.embed.doEmbed" || s == "ai.embedMany.doEmbed" => "$ai_embedding",
        _ => "$ai_span",
    }
}

const EVENT_CLASSIFIERS: &[EventClassifier] = &[
    EventClassifier {
        attr_key: "gen_ai.operation.name",
        classify: classify_gen_ai_operation,
    },
    EventClassifier {
        attr_key: "ai.operationId",
        classify: classify_vercel_ai_operation,
    },
];

pub fn get_event_name(attrs: &serde_json::Map<String, Value>) -> &'static str {
    for c in EVENT_CLASSIFIERS {
        if let Some(value) = attrs.get(c.attr_key).and_then(|v| v.as_str()) {
            return (c.classify)(value);
        }
    }
    "$ai_span"
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attrs_with(key: &str, value: &str) -> serde_json::Map<String, Value> {
        let mut map = serde_json::Map::new();
        map.insert(key.to_string(), Value::String(value.to_string()));
        map
    }

    #[test]
    fn test_from_gen_ai_operation_name() {
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.operation.name", "chat")),
            "$ai_generation"
        );
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.operation.name", "embeddings")),
            "$ai_embedding"
        );
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.operation.name", "unknown")),
            "$ai_span"
        );
        assert_eq!(get_event_name(&serde_json::Map::new()), "$ai_span");
    }

    #[test]
    fn test_from_vercel_ai_operation_id() {
        for (op_id, expected) in [
            ("ai.generateText.doGenerate", "$ai_generation"),
            ("ai.streamText.doStream", "$ai_generation"),
            ("ai.generateObject.doGenerate", "$ai_generation"),
            ("ai.streamObject.doStream", "$ai_generation"),
            ("ai.embed.doEmbed", "$ai_embedding"),
            ("ai.embedMany.doEmbed", "$ai_embedding"),
            ("ai.toolCall", "$ai_span"),
            ("ai.generateText", "$ai_span"),
            ("ai.streamText", "$ai_span"),
        ] {
            assert_eq!(
                get_event_name(&attrs_with("ai.operationId", op_id)),
                expected,
                "ai.operationId={op_id}"
            );
        }
    }

    #[test]
    fn test_gen_ai_operation_name_takes_precedence() {
        let mut attrs = serde_json::Map::new();
        attrs.insert(
            "gen_ai.operation.name".to_string(),
            Value::String("chat".to_string()),
        );
        attrs.insert(
            "ai.operationId".to_string(),
            Value::String("ai.toolCall".to_string()),
        );
        assert_eq!(get_event_name(&attrs), "$ai_generation");
    }
}
