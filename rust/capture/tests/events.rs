use std::num::NonZeroU32;
use time::Duration;

use crate::common::*;
use anyhow::Result;
use assert_json_diff::assert_json_include;
use capture::limiters::billing::QuotaResource;
use serde_json::json;
use uuid::Uuid;
mod common;

#[tokio::test]
async fn it_captures_one_event() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id
    });

    server.capture_events(&event).await;

    let event = main_topic.next_event()?;
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_captures_a_posthogjs_array() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id1 = random_string("id", 16);
    let distinct_id2 = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event = json!([{
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id1
    },{
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id2
    }]);

    server.capture_events(&event).await;

    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id1
        })
    );
    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id2
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_captures_a_batch() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id1 = random_string("id", 16);
    let distinct_id2 = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event = json!({
        "token": token,
        "batch": [{
            "event": "event1",
            "distinct_id": distinct_id1
        },{
            "event": "event2",
            "distinct_id": distinct_id2
        }]
    });

    server.capture_events(&event).await;

    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id1
        })
    );
    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id2
        })
    );

    Ok(())
}
#[tokio::test]
async fn it_captures_a_historical_batch() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id1 = random_string("id", 16);
    let distinct_id2 = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event = json!({
        "token": token,
        "historical_migration": true,
        "batch": [{
            "event": "event1",
            "distinct_id": distinct_id1
        },{
            "event": "event2",
            "distinct_id": distinct_id2
        }]
    });

    server.capture_events(&event).await;

    assert_json_include!(
        actual: histo_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id1
        })
    );
    assert_json_include!(
        actual: histo_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id2
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_overflows_events_on_burst() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.overflow_enabled = true;
    config.overflow_burst_limit = NonZeroU32::new(2).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(1).unwrap();

    let server = ServerHandle::for_config(config).await;

    let event = json!([{
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event3",
        "distinct_id": distinct_id
    }]);

    server.capture_events(&event).await;

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id)
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id)
    );

    assert_eq!(topic.next_message_key()?, None);

    Ok(())
}

#[tokio::test]
async fn it_does_not_overflow_team_with_different_ids() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let distinct_id2 = random_string("id", 16);

    let topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.overflow_enabled = true;
    config.overflow_burst_limit = NonZeroU32::new(1).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(1).unwrap();

    let server = ServerHandle::for_config(config).await;

    let event = json!([{
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id2
    }]);

    server.capture_events(&event).await;

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id)
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id2)
    );

    Ok(())
}

#[tokio::test]
async fn it_skips_overflows_when_disabled() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.overflow_enabled = false;
    config.overflow_burst_limit = NonZeroU32::new(2).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(1).unwrap();

    let server = ServerHandle::for_config(config).await;

    let event = json!([{
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event3",
        "distinct_id": distinct_id
    }]);

    server.capture_events(&event).await;

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id)
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id)
    );

    // Should have triggered overflow, but has not
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{}:{}", token, distinct_id)
    );
    Ok(())
}

#[tokio::test]
async fn it_trims_distinct_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id1 = random_string("id", 200 - 3);
    let distinct_id2 = random_string("id", 222);
    let (trimmed_distinct_id2, _) = distinct_id2.split_at(200); // works because ascii chars

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event = json!([{
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id1
    },{
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id2
    }]);

    server.capture_events(&event).await;

    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id1
        })
    );
    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": trimmed_distinct_id2
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_applies_billing_limits() -> Result<()> {
    setup_tracing();
    let token1 = random_string("token", 16);
    let token2 = random_string("token", 16);
    let token3 = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;

    // Setup billing limits:
    //   - token1 limit is expired -> accept messages
    //   - token2 limit is active -> drop messages
    //   - token3 is not in redis -> accept by default
    let redis = PrefixedRedis::new().await;
    redis.add_billing_limit(QuotaResource::Events, &token1, Duration::seconds(-60));
    redis.add_billing_limit(QuotaResource::Events, &token2, Duration::seconds(60));

    let mut config = DEFAULT_CONFIG.clone();
    config.redis_key_prefix = redis.key_prefix();
    config.kafka.kafka_topic = topic.topic_name().to_string();
    let server = ServerHandle::for_config(config).await;

    for payload in [
        json!({
            "token": token1,
            "batch": [{"event": "event1","distinct_id": distinct_id}]
        }),
        json!({
            "token": token2,
            "batch": [{"event": "to drop","distinct_id": distinct_id}]
        }),
        json!({
            "token": token3,
            "batch": [{"event": "event1","distinct_id": distinct_id}]
        }),
    ] {
        server.capture_events(&payload).await;
    }

    // Batches 1 and 3 go through, batch 2 is dropped
    assert_json_include!(
        actual: topic.next_event()?,
        expected: json!({
            "token": token1,
            "distinct_id": distinct_id
        })
    );
    assert_json_include!(
        actual: topic.next_event()?,
        expected: json!({
            "token": token3,
            "distinct_id": distinct_id
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_routes_exceptions_and_heapmaps_to_separate_topics() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let uuids: [Uuid; 5] = core::array::from_fn(|_| Uuid::now_v7());

    let main_topic = EphemeralTopic::new().await;
    let warnings_topic = EphemeralTopic::new().await;
    let exceptions_topic = EphemeralTopic::new().await;
    let heatmaps_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = main_topic.topic_name().to_string();
    config.kafka.kafka_client_ingestion_warning_topic = warnings_topic.topic_name().to_string();
    config.kafka.kafka_exceptions_topic = exceptions_topic.topic_name().to_string();
    config.kafka.kafka_heatmaps_topic = heatmaps_topic.topic_name().to_string();

    let server = ServerHandle::for_config(config).await;

    let event = json!([{
        "token": token,
        "event": "$$client_ingestion_warning",
        "uuid": uuids[4],
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event1",
        "uuid": uuids[0],
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "$$heatmap",
        "uuid": uuids[1],
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "$exception",
        "uuid": uuids[2],
        "distinct_id": distinct_id
    },{
        "token": token,
        "event": "event2",
        "uuid": uuids[3],
        "distinct_id": distinct_id
    }]);

    server.capture_events(&event).await;

    // Regular events are pushed to the main analytics topic
    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
        "uuid": uuids[0],
            "distinct_id": distinct_id
        })
    );
    assert_json_include!(
        actual: main_topic.next_event()?,
        expected: json!({
            "token": token,
        "uuid": uuids[3],
            "distinct_id": distinct_id
        })
    );
    main_topic.assert_empty();

    // Special-cased events are pushed to their own topics
    assert_json_include!(
        actual: exceptions_topic.next_event()?,
        expected: json!({
            "token": token,
        "uuid": uuids[2],
            "distinct_id": distinct_id
        })
    );
    exceptions_topic.assert_empty();
    assert_json_include!(
        actual: heatmaps_topic.next_event()?,
        expected: json!({
            "token": token,
        "uuid": uuids[1],
            "distinct_id": distinct_id
        })
    );
    heatmaps_topic.assert_empty();
    assert_json_include!(
        actual: warnings_topic.next_event()?,
        expected: json!({
            "token": token,
        "uuid": uuids[4],
            "distinct_id": distinct_id
        })
    );
    warnings_topic.assert_empty();
    Ok(())
}

#[tokio::test]
async fn it_limits_non_batch_endpoints_to_2mb() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let ok_event = json!({
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id,
        "properties": {
            "big": "a".repeat(2_000_000)
        }
    });

    let nok_event = json!({
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id,
        "properties": {
            "big": "a".repeat(2_100_000)
        }
    });

    // The events are too large to go in kafka, so we get a maximum event size exceeded error, but that's ok, because that's a 400, not a 413
    server
        .capture_events(&ok_event)
        .expect_failure()
        .await
        .assert_status_bad_request();

    server
        .capture_events(&nok_event)
        .expect_failure()
        .await
        .assert_status_payload_too_large();

    Ok(())
}

#[tokio::test]
async fn it_limits_batch_endpoints_to_20mb() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Notably here, rust capture actually handles all endpoints with the same function, so we don't actually
    // need to wrap these events in an array to send them to our batch endpoint
    let ok_event = json!({
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id,
        "properties": {
            "big": "a".repeat(20_000_000)
        }
    });

    let nok_event = json!({
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id,
        "properties": {
            "big": "a".repeat(21_000_000)
        }
    });

    // The events are too large to go in kafka, so we get a maximum event size exceeded error, but that's ok, because that's a 400, not a 413
    server
        .capture_to_batch(&ok_event)
        .expect_failure()
        .await
        .assert_status_bad_request();

    server
        .capture_to_batch(&nok_event)
        .expect_failure()
        .await
        .assert_status_payload_too_large();

    Ok(())
}
