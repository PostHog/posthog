use serde_json::Value;

/// Configuration for a single supported AI provider. Adding a new provider
/// means adding one entry here — both the namespace prefix (for broad span
/// acceptance) and the classifier (for specific event type mapping) live
/// together, so they can't get out of sync.
pub struct SupportedProvider {
    /// Accept any span whose attribute key starts with one of these prefixes.
    prefixes: &'static [&'static str],
    /// Maps a span's attributes to a PostHog event type.
    pub classify: fn(&serde_json::Map<String, Value>) -> &'static str,
}

/// Looks up `key` in `attrs` as a string value and passes it to `classify`.
/// Falls back to `$ai_span` if the key is missing or the value isn't a string.
fn classify_by_key(
    attrs: &serde_json::Map<String, Value>,
    key: &str,
    classify: fn(&str) -> &'static str,
) -> &'static str {
    attrs
        .get(key)
        .and_then(|v| v.as_str())
        .map(classify)
        .unwrap_or("$ai_span")
}

/// OpenAI-style semantic conventions (`gen_ai.*`).
const GEN_AI: SupportedProvider = SupportedProvider {
    prefixes: &["gen_ai."],
    classify: |attrs| {
        classify_by_key(attrs, "gen_ai.operation.name", |op| match op {
            "chat" => "$ai_generation",
            "embeddings" => "$ai_embedding",
            _ => "$ai_span",
        })
    },
};

/// Vercel AI SDK (`ai.*`).
const VERCEL_AI: SupportedProvider = SupportedProvider {
    prefixes: &["ai."],
    classify: |attrs| {
        classify_by_key(attrs, "ai.operationId", |op_id| match op_id {
            s if s.ends_with(".doGenerate") || s.ends_with(".doStream") => "$ai_generation",
            s if s == "ai.embed.doEmbed" || s == "ai.embedMany.doEmbed" => "$ai_embedding",
            _ => "$ai_span",
        })
    },
};

/// Traceloop OpenLLMetry SDK (`traceloop.*`). The classifier key
/// (`llm.request.type`) doesn't share the `traceloop.` prefix, so both
/// prefixes are needed to catch all Traceloop spans.
const TRACELOOP: SupportedProvider = SupportedProvider {
    prefixes: &["traceloop.", "llm.request.type"],
    classify: |attrs| {
        classify_by_key(
            attrs,
            "llm.request.type",
            |request_type| match request_type {
                "chat" | "completion" => "$ai_generation",
                "embedding" | "embeddings" => "$ai_embedding",
                _ => "$ai_span",
            },
        )
    },
};

/// Pydantic AI SDK (`pydantic_ai.*`). No specific event types — all spans
/// default to `$ai_span`.
const PYDANTIC_AI: SupportedProvider = SupportedProvider {
    prefixes: &["pydantic_ai."],
    classify: |_| "$ai_span",
};

/// Providers are matched in order — first prefix match wins. More specific
/// matchers must come before less specific ones to avoid shadowing. For example,
/// Vercel AI spans carry both `ai.*` and `gen_ai.*` attributes; if GEN_AI were
/// checked first it would match on `gen_ai.*` but fail to classify (Vercel AI
/// doesn't set `gen_ai.operation.name`), shadowing the VERCEL_AI classifier.
const SUPPORTED_PROVIDERS: &[SupportedProvider] = &[
    // 1. Framework-specific — dedicated SDKs with their own attribute namespaces
    VERCEL_AI,
    PYDANTIC_AI,
    // 2. Spec variations — alternative telemetry standards with distinct classification keys
    TRACELOOP,
    // 3. Generic catch-all — standard OpenTelemetry semantic conventions (gen_ai.*)
    GEN_AI,
];

/// Returns the matching provider for raw protobuf attributes, based on prefix
/// matching. Used as a lightweight pre-filter to avoid converting irrelevant
/// spans into JSON.
pub fn get_provider_raw(
    attrs: &[opentelemetry_proto::tonic::common::v1::KeyValue],
) -> Option<&'static SupportedProvider> {
    SUPPORTED_PROVIDERS.iter().find(|p| {
        attrs
            .iter()
            .any(|kv| p.prefixes.iter().any(|prefix| kv.key.starts_with(prefix)))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attrs_with(key: &str, value: &str) -> serde_json::Map<String, Value> {
        let mut map = serde_json::Map::new();
        map.insert(key.to_string(), Value::String(value.to_string()));
        map
    }

    fn get_event_name(attrs: &serde_json::Map<String, Value>) -> Option<&'static str> {
        SUPPORTED_PROVIDERS
            .iter()
            .find(|p| {
                attrs
                    .keys()
                    .any(|key| p.prefixes.iter().any(|prefix| key.starts_with(prefix)))
            })
            .map(|p| (p.classify)(attrs))
    }

    #[test]
    fn test_from_gen_ai_operation_name() {
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.operation.name", "chat")),
            Some("$ai_generation")
        );
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.operation.name", "embeddings")),
            Some("$ai_embedding")
        );
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.operation.name", "unknown")),
            Some("$ai_span")
        );
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
                Some(expected),
                "ai.operationId={op_id}"
            );
        }
    }

    #[test]
    fn test_from_traceloop_request_type() {
        for (request_type, expected) in [
            ("chat", "$ai_generation"),
            ("completion", "$ai_generation"),
            ("embedding", "$ai_embedding"),
            ("embeddings", "$ai_embedding"),
            ("rerank", "$ai_span"),
            ("unknown", "$ai_span"),
        ] {
            assert_eq!(
                get_event_name(&attrs_with("llm.request.type", request_type)),
                Some(expected),
                "llm.request.type={request_type}"
            );
        }
    }

    #[test]
    fn test_vercel_ai_takes_precedence_over_gen_ai() {
        // Vercel AI spans carry both ai.* and gen_ai.* attributes. The
        // SDK-specific VERCEL_AI provider should match first.
        let mut attrs = serde_json::Map::new();
        attrs.insert(
            "gen_ai.operation.name".to_string(),
            Value::String("chat".to_string()),
        );
        attrs.insert(
            "ai.operationId".to_string(),
            Value::String("ai.toolCall".to_string()),
        );
        assert_eq!(get_event_name(&attrs), Some("$ai_span"));
    }

    #[test]
    fn test_vercel_ai_do_generate_with_gen_ai_attrs() {
        // Real-world scenario: Vercel AI .doGenerate spans carry gen_ai.*
        // attributes (e.g. gen_ai.request.model) but not gen_ai.operation.name.
        // VERCEL_AI must match first and classify via ai.operationId.
        let mut attrs = serde_json::Map::new();
        attrs.insert(
            "gen_ai.request.model".to_string(),
            Value::String("gpt-4".to_string()),
        );
        attrs.insert(
            "ai.operationId".to_string(),
            Value::String("ai.generateText.doGenerate".to_string()),
        );
        assert_eq!(get_event_name(&attrs), Some("$ai_generation"));
    }

    #[test]
    fn test_supported_provider_prefix_defaults_to_ai_span() {
        assert_eq!(
            get_event_name(&attrs_with("gen_ai.request.model", "gpt-4")),
            Some("$ai_span")
        );
        assert_eq!(
            get_event_name(&attrs_with("pydantic_ai.agent_name", "my-agent")),
            Some("$ai_span")
        );
        assert_eq!(
            get_event_name(&attrs_with("traceloop.workflow.name", "my-workflow")),
            Some("$ai_span")
        );
    }

    #[test]
    fn test_traceloop_span_with_only_llm_request_type() {
        // Traceloop spans may carry only `llm.request.type` without any
        // `traceloop.*` prefixed attribute. The dual-prefix design ensures
        // these are still accepted and classified correctly.
        assert_eq!(
            get_event_name(&attrs_with("llm.request.type", "chat")),
            Some("$ai_generation")
        );
        assert_eq!(
            get_event_name(&attrs_with("llm.request.type", "embedding")),
            Some("$ai_embedding")
        );
    }

    #[test]
    fn test_unsupported_provider_returns_none() {
        assert_eq!(
            get_event_name(&attrs_with("logfire.msg", "running 1 tool")),
            None
        );
    }

    #[test]
    fn test_irrelevant_span_returns_none() {
        assert_eq!(
            get_event_name(&attrs_with("http.request.method", "POST")),
            None
        );
        assert_eq!(get_event_name(&serde_json::Map::new()), None);
        assert_eq!(
            get_event_name(&attrs_with("langchain.chain.name", "my-chain")),
            None
        );
    }
}
