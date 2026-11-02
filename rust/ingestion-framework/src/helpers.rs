//! Port of `helpers.ts`.

use std::collections::BTreeMap;

use serde_json::json;

use crate::context::{OkResultWithContext, PipelineContext};
use crate::outputs::{HasMessage, KafkaMessage};

// The headers a responder needs to write an event restriction for a poison message.
// distinct_id and session_id are customer-controlled and stay out.
const LOGGED_HEADERS: [&str; 3] = ["token", "event", "uuid"];

pub fn create_kafka_debug_context(message: &KafkaMessage) -> serde_json::Value {
    let headers: serde_json::Map<String, serde_json::Value> = message
        .headers
        .iter()
        .filter(|(key, _)| LOGGED_HEADERS.contains(&key.as_str()))
        .filter_map(|(key, value)| {
            value
                .as_ref()
                .map(|v| (key.clone(), json!(String::from_utf8_lossy(v))))
        })
        .collect();
    json!({
        "topic": message.topic,
        "partition": message.partition,
        "offset": message.offset,
        "headers": headers,
    })
}

pub fn compact_offset_ranges(offsets: &[i64]) -> String {
    let mut sorted: Vec<i64> = offsets.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    let mut ranges = Vec::new();
    let mut iter = sorted.into_iter();
    let Some(mut start) = iter.next() else {
        return String::new();
    };
    let mut end = start;
    let fmt = |s: i64, e: i64| {
        if s == e {
            s.to_string()
        } else {
            format!("{s}-{e}")
        }
    };
    for offset in iter {
        if offset == end + 1 {
            end = offset;
        } else {
            ranges.push(fmt(start, end));
            start = offset;
            end = offset;
        }
    }
    ranges.push(fmt(start, end));
    ranges.join(",")
}

pub fn aggregate_kafka_debug_contexts(debug_contexts: &[serde_json::Value]) -> serde_json::Value {
    let mut by_partition: BTreeMap<String, Vec<i64>> = BTreeMap::new();
    let mut order: Vec<String> = Vec::new();
    for context in debug_contexts {
        let key = format!(
            "{}[{}]",
            context["topic"].as_str().unwrap_or("undefined"),
            context["partition"].as_i64().unwrap_or_default()
        );
        if !by_partition.contains_key(&key) {
            order.push(key.clone());
        }
        by_partition
            .entry(key)
            .or_default()
            .push(context["offset"].as_i64().unwrap_or_default());
    }
    json!({
        "count": debug_contexts.len(),
        "offsets": order
            .iter()
            .map(|key| format!("{key}:{}", compact_offset_ranges(&by_partition[key])))
            .collect::<Vec<_>>(),
    })
}

#[derive(Debug, Clone)]
pub struct MessageContext {
    pub message: KafkaMessage,
}

impl HasMessage for MessageContext {
    fn message(&self) -> &KafkaMessage {
        &self.message
    }
}

/// Port of `createBatch`. The value is a copy of the context, as in Node, where it is `{ message }` too.
pub fn create_batch(
    messages: Vec<KafkaMessage>,
) -> Vec<OkResultWithContext<MessageContext, MessageContext>> {
    messages
        .into_iter()
        .map(|message| {
            let debug = create_kafka_debug_context(&message);
            let mut context = PipelineContext::new(MessageContext {
                message: message.clone(),
            });
            context.debug_context = Some(debug);
            OkResultWithContext {
                value: MessageContext { message },
                context,
            }
        })
        .collect()
}
