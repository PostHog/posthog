use base64::Engine;
use uuid::Uuid;

use crate::{Client, CustomRedisError};

const DEFAULT_QUEUE: &str = "celery";

/// Build a Celery v2 protocol message envelope as a JSON string.
///
/// This produces the exact format that Kombu (Celery's transport layer) expects
/// when consuming from a Redis list: a JSON object with base64-encoded body,
/// headers carrying task metadata, and properties for routing.
pub fn build_celery_message(
    task_name: &str,
    args: &serde_json::Value,
    kwargs: &serde_json::Value,
) -> String {
    let task_id = Uuid::new_v4().to_string();
    let delivery_tag = Uuid::new_v4().to_string();

    build_celery_message_with_id(task_name, args, kwargs, &task_id, &delivery_tag)
}

/// Same as `build_celery_message` but with explicit IDs for deterministic testing.
fn build_celery_message_with_id(
    task_name: &str,
    args: &serde_json::Value,
    kwargs: &serde_json::Value,
    task_id: &str,
    delivery_tag: &str,
) -> String {
    let body_json = serde_json::json!([
        args,
        kwargs,
        {"callbacks": null, "errbacks": null, "chain": null, "chord": null}
    ]);
    let body_b64 =
        base64::engine::general_purpose::STANDARD.encode(body_json.to_string().as_bytes());

    let message = serde_json::json!({
        "body": body_b64,
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "headers": {
            "lang": "py",
            "task": task_name,
            "id": task_id,
            "shadow": null,
            "eta": null,
            "expires": null,
            "group": null,
            "retries": 0,
            "timelimit": [null, null],
            "root_id": task_id,
            "parent_id": null,
            "origin": "posthog-rust",
            "ignore_result": true,
        },
        "properties": {
            "correlation_id": task_id,
            "reply_to": "",
            "delivery_mode": 2,
            "delivery_info": {"exchange": "", "routing_key": DEFAULT_QUEUE},
            "priority": 0,
            "body_encoding": "base64",
            "delivery_tag": delivery_tag,
        }
    });

    message.to_string()
}

/// Push a Celery task message onto the broker queue via LPUSH.
///
/// The Celery worker consumes from the tail (BRPOP), so LPUSH gives FIFO ordering.
pub async fn send_celery_task(
    client: &dyn Client,
    task_name: &str,
    args: &serde_json::Value,
    kwargs: &serde_json::Value,
) -> Result<(), CustomRedisError> {
    let message = build_celery_message(task_name, args, kwargs);
    client.lpush(DEFAULT_QUEUE.to_string(), message).await
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decode_body(message: &serde_json::Value) -> serde_json::Value {
        let body_b64 = message["body"].as_str().unwrap();
        let body_bytes = base64::engine::general_purpose::STANDARD
            .decode(body_b64)
            .unwrap();
        serde_json::from_slice(&body_bytes).unwrap()
    }

    #[test]
    fn test_body_encodes_args_kwargs_and_embed() {
        let msg = build_celery_message_with_id(
            "myapp.tasks.add",
            &serde_json::json!([1, 2]),
            &serde_json::json!({"team_id": 42}),
            "test-id",
            "test-tag",
        );
        let parsed: serde_json::Value = serde_json::from_str(&msg).unwrap();
        let body = decode_body(&parsed);

        assert_eq!(body[0], serde_json::json!([1, 2]));
        assert_eq!(body[1], serde_json::json!({"team_id": 42}));
        assert_eq!(
            body[2],
            serde_json::json!({"callbacks": null, "errbacks": null, "chain": null, "chord": null})
        );
    }

    #[test]
    fn test_headers_carry_task_metadata() {
        let msg = build_celery_message_with_id(
            "posthog.tasks.calculate.run",
            &serde_json::json!([]),
            &serde_json::json!({}),
            "abc-123",
            "tag-456",
        );
        let parsed: serde_json::Value = serde_json::from_str(&msg).unwrap();
        let headers = &parsed["headers"];

        assert_eq!(headers["task"], "posthog.tasks.calculate.run");
        assert_eq!(headers["id"], "abc-123");
        assert_eq!(headers["root_id"], "abc-123");
        assert_eq!(headers["parent_id"], serde_json::Value::Null);
        assert_eq!(headers["lang"], "py");
        assert_eq!(headers["retries"], 0);
        assert_eq!(headers["ignore_result"], true);
    }

    #[test]
    fn test_properties_route_to_celery_queue() {
        let msg = build_celery_message_with_id(
            "myapp.tasks.add",
            &serde_json::json!([]),
            &serde_json::json!({}),
            "abc-123",
            "tag-456",
        );
        let parsed: serde_json::Value = serde_json::from_str(&msg).unwrap();
        let props = &parsed["properties"];

        assert_eq!(props["correlation_id"], "abc-123");
        assert_eq!(props["delivery_tag"], "tag-456");
        assert_eq!(props["delivery_mode"], 2);
        assert_eq!(props["body_encoding"], "base64");
        assert_eq!(props["priority"], 0);
        assert_eq!(props["delivery_info"]["routing_key"], "celery");
        assert_eq!(props["delivery_info"]["exchange"], "");
    }

    #[test]
    fn test_envelope_content_type_fields() {
        let msg = build_celery_message_with_id(
            "t",
            &serde_json::json!([]),
            &serde_json::json!({}),
            "id",
            "tag",
        );
        let parsed: serde_json::Value = serde_json::from_str(&msg).unwrap();

        assert_eq!(parsed["content-type"], "application/json");
        assert_eq!(parsed["content-encoding"], "utf-8");
    }

    #[test]
    fn test_build_celery_message_generates_unique_ids() {
        let msg1 = build_celery_message("t", &serde_json::json!([]), &serde_json::json!({}));
        let msg2 = build_celery_message("t", &serde_json::json!([]), &serde_json::json!({}));

        let p1: serde_json::Value = serde_json::from_str(&msg1).unwrap();
        let p2: serde_json::Value = serde_json::from_str(&msg2).unwrap();

        assert_ne!(p1["headers"]["id"], p2["headers"]["id"]);
        assert_ne!(
            p1["properties"]["delivery_tag"],
            p2["properties"]["delivery_tag"]
        );
    }

    #[test]
    fn test_send_celery_task_lpushes_to_celery_queue() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mock = crate::MockRedisClient::new();
            send_celery_task(
                &mock,
                "posthog.tasks.do_thing",
                &serde_json::json!([1]),
                &serde_json::json!({"key": "val"}),
            )
            .await
            .unwrap();

            let calls = mock.get_calls();
            assert_eq!(calls.len(), 1);
            assert_eq!(calls[0].op, "lpush");
            assert_eq!(calls[0].key, "celery");
        });
    }

}
