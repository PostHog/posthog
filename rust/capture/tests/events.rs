use std::num::NonZeroU32;
use std::time::Duration as StdDuration;
use time::Duration;

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use assert_json_diff::assert_json_include;
use chrono::Utc;
use limiters::redis::QuotaResource;
use reqwest::StatusCode;
use serde_json::json;
use uuid::Uuid;

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
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

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
async fn it_drops_performance_events() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let dropped_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let retained_one = json!({
        "token": token,
        "event": "some_event",
        "distinct_id": distinct_id
    });
    // we should be filtering these out prior to publishing to ingest topic
    let should_drop = json!({
        "token": token,
        "event": "$performance_event",
        "distinct_id": dropped_id
    });
    let retained_two = json!({
        "token": token,
        "event": "some_other_event",
        "distinct_id": distinct_id
    });

    let res = server.capture_events(retained_one.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());
    // silently ignored if the filtering of unsupported event types results in an empty payload
    let res = server.capture_events(should_drop.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());
    let res = server.capture_events(retained_two.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let got = main_topic.next_event()?;
    assert_json_include!(
        actual: got,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );

    // the next event in the topic should be retained_two
    // since we filtered out should_drop (w/dropped_id)
    let got = main_topic.next_event()?;
    assert_json_include!(
        actual: got,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_drops_events_if_dropper_enabled() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let dropped_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;
    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = main_topic.topic_name().to_string();
    config.kafka.kafka_historical_topic = histo_topic.topic_name().to_string();
    config.kafka.kafka_overflow_topic = overflow_topic.topic_name().to_string();
    config.drop_events_by_token_distinct_id = Some(format!("{token}:{dropped_id}"));
    let server = ServerHandle::for_config(config).await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id
    });

    let dropped = json!({
        "token": token,
        "event": "testing",
        "distinct_id": dropped_id
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());
    let res = server.capture_events(dropped.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let event = main_topic.next_event()?;
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );

    // Next event we get is identical to the first, because the dropped event is not captured
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
async fn it_redacts_ip_address_of_capture_internal_events() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event = json!({
        "token": token,
        "event": "test_event_from_capture_internal",
        "distinct_id": distinct_id,
        "properties": {
            "capture_internal": true
        }
    });
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let event = main_topic.next_event()?;
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id,
            "ip": "127.0.0.1",
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
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

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
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

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
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

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
async fn it_overflows_events_on_specified_keys() -> Result<()> {
    setup_tracing();

    // token only will be limited by candidate list
    let token1 = String::from("token1");
    let distinct_id1 = String::from("user1");

    // token:distinct_id will be limited by candidate list
    let token2 = String::from("token2");
    let distinct_id2 = String::from("user2");
    let key2 = format!("{token2}:{distinct_id2}");

    // won't be limited other than by burst/rate-limits
    let token3 = String::from("token3");
    let distinct_id3 = String::from("user3");

    let topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    // this is the candidate list of tokens/event keys to reroute on sight
    config.ingestion_force_overflow_by_token_distinct_id = Some(format!("{token1},{key2}"));
    config.kafka.kafka_hosts = "localhost:9092".to_string();
    config.kafka.kafka_producer_linger_ms = 0; // Send messages immediately
    config.kafka.kafka_message_timeout_ms = 10000; // 10s timeout
    config.kafka.kafka_producer_max_retries = 3;
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_overflow_topic = overflow_topic.topic_name().to_string();
    config.overflow_enabled = true;
    config.overflow_burst_limit = NonZeroU32::new(10).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(10).unwrap();

    let server = ServerHandle::for_config(config).await;

    let batch_1 = json!([
    // all events with token1 should be in overflow
    {
        "token": token1,
        "event": "event1",
        "distinct_id": distinct_id1,
    },
    {
        "token": token1,
        "event": "event2",
        "distinct_id": distinct_id2,
    }]);

    let batch_2 = json!([
    // only events with token2:distinct_id2 should be in overflow
    {
        "token": token2,
        "event": "event3",
        "distinct_id": distinct_id2,
    },
    {
        "token": token2,
        "event": "event4",
        "distinct_id": distinct_id1,
    }]);

    let batch_3 = json!([
    // all events for token3 and token3:distinct_id3 should be in main topic
    {
        "token": token3,
        "event": "event5",
        "distinct_id": distinct_id1,
    },
    {
        "token": token3,
        "event": "event6",
        "distinct_id": distinct_id2,
    },
    {
        "token": token3,
        "event": "event7",
        "distinct_id": distinct_id3,
    }]);

    let res = server.capture_events(batch_1.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let res = server.capture_events(batch_2.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let res = server.capture_events(batch_3.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // main toppic results
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token2}:{distinct_id1}")
    );
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id1}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id2}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id3}")
    );

    topic.assert_empty();

    // Expected events should be in overflow topic, but have no
    // message key as overflow events are round-robined
    assert_json_include!(
        actual: overflow_topic.next_event()?,
        expected: json!({
            "token": token1,
            "distinct_id": distinct_id1,
        })
    );

    assert_json_include!(
        actual: overflow_topic.next_event()?,
        expected: json!({
            "token": token1,
            "distinct_id": distinct_id2,
        })
    );

    assert_json_include!(
        actual: overflow_topic.next_event()?,
        expected: json!({
            "token": token2,
            "distinct_id": distinct_id2,
        })
    );

    overflow_topic.assert_empty();

    Ok(())
}

#[tokio::test]
async fn it_overflows_events_on_specified_keys_preserving_locality() -> Result<()> {
    setup_tracing();

    // token only will be limited by candidate list
    let token1 = String::from("token1");
    let distinct_id1 = String::from("user1");

    // token:distinct_id will be limited by candidate list
    let token2 = String::from("token2");
    let distinct_id2 = String::from("user2");
    let key2 = format!("{token2}:{distinct_id2}");

    // won't be limited other than by burst/rate-limits
    let token3 = String::from("token3");
    let distinct_id3 = String::from("user3");

    let topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    // this is the candidate list of tokens/event keys to reroute on sight
    config.ingestion_force_overflow_by_token_distinct_id = Some(format!("{token1},{key2}"));
    config.kafka.kafka_hosts = "localhost:9092".to_string();
    config.kafka.kafka_producer_linger_ms = 0; // Send messages immediately
    config.kafka.kafka_message_timeout_ms = 10000; // 10s timeout
    config.kafka.kafka_producer_max_retries = 3;
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_overflow_topic = overflow_topic.topic_name().to_string();
    config.overflow_enabled = true;
    config.overflow_preserve_partition_locality = true;
    config.overflow_burst_limit = NonZeroU32::new(10).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(10).unwrap();

    let server = ServerHandle::for_config(config).await;

    let batch_1 = json!([
    // all events with token1 should be in overflow
    {
        "token": token1,
        "event": "event1",
        "distinct_id": distinct_id1,
    },
    {
        "token": token1,
        "event": "event2",
        "distinct_id": distinct_id2,
    }]);

    let batch_2 = json!([
    // only events with token2:distinct_id2 should be in overflow
    {
        "token": token2,
        "event": "event3",
        "distinct_id": distinct_id2,
    },
    {
        "token": token2,
        "event": "event4",
        "distinct_id": distinct_id1,
    }]);

    let batch_3 = json!([
    // all events for token3 and token3:distinct_id3 should be in main topic
    {
        "token": token3,
        "event": "event5",
        "distinct_id": distinct_id1,
    },
    {
        "token": token3,
        "event": "event6",
        "distinct_id": distinct_id2,
    },
    {
        "token": token3,
        "event": "event7",
        "distinct_id": distinct_id3,
    }]);

    let res = server.capture_events(batch_1.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let res = server.capture_events(batch_2.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let res = server.capture_events(batch_3.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // main topic results
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token2}:{distinct_id1}")
    );
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id1}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id2}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id3}")
    );

    topic.assert_empty();

    // Expected events should be in overflow topic, but should
    // retain original partition keys, so fetch-by-key works here
    assert_eq!(
        overflow_topic.next_message_key()?.unwrap(),
        format!("{token1}:{distinct_id1}")
    );

    assert_eq!(
        overflow_topic.next_message_key()?.unwrap(),
        format!("{token1}:{distinct_id2}")
    );

    assert_eq!(
        overflow_topic.next_message_key()?.unwrap(),
        format!("{token2}:{distinct_id2}")
    );

    overflow_topic.assert_empty();

    Ok(())
}

#[tokio::test]
async fn it_reroutes_to_historical_on_specified_keys() -> Result<()> {
    setup_tracing();

    // token only will be limited by candidate list
    let token1 = String::from("token1");
    let distinct_id1 = String::from("user1");

    // token:distinct_id will be limited by candidate list
    let token2 = String::from("token2");
    let distinct_id2 = String::from("user2");
    let key2 = format!("{token2}:{distinct_id2}");

    // won't be limited other than by burst/rate-limits
    let token3 = String::from("token3");
    let distinct_id3 = String::from("user3");

    let topic = EphemeralTopic::new().await;
    let historical_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();

    // enable historical rerouting but focus this test on token1, key2
    config.enable_historical_rerouting = true;
    config.historical_rerouting_threshold_days = 30_i64; // 30 days won't interfere w/test!
    config.historical_tokens_keys = Some(format!("{token1},{key2}"));

    config.kafka.kafka_hosts = "localhost:9092".to_string();
    config.kafka.kafka_producer_linger_ms = 0; // Send messages immediately
    config.kafka.kafka_message_timeout_ms = 10000; // 10s timeout
    config.kafka.kafka_producer_max_retries = 3;
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_historical_topic = historical_topic.topic_name().to_string();
    config.overflow_enabled = false;
    config.overflow_burst_limit = NonZeroU32::new(10).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(10).unwrap();

    let server = ServerHandle::for_config(config).await;

    let batch_1 = json!([
    // all events with token1 should be in overflow
    {
        "token": token1,
        "event": "event1",
        "distinct_id": distinct_id1,
    },
    {
        "token": token1,
        "event": "event2",
        "distinct_id": distinct_id2,
    }]);

    let batch_2 = json!([
    // only events with token2:distinct_id2 should be in overflow
    {
        "token": token2,
        "event": "event3",
        "distinct_id": distinct_id2,
    },
    {
        "token": token2,
        "event": "event4",
        "distinct_id": distinct_id1,
    }]);

    let batch_3 = json!([
    // all events for token3 and token3:distinct_id3 should be in main topic
    {
        "token": token3,
        "event": "event5",
        "distinct_id": distinct_id1,
    },
    {
        "token": token3,
        "event": "event6",
        "distinct_id": distinct_id2,
    },
    {
        "token": token3,
        "event": "event7",
        "distinct_id": distinct_id3,
    }]);

    let res = server.capture_events(batch_1.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let res = server.capture_events(batch_2.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let res = server.capture_events(batch_3.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // main toppic results
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token2}:{distinct_id1}")
    );
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id1}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id2}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id3}")
    );

    topic.assert_empty();

    // Expected events should be in historical topic
    assert_json_include!(
        actual: historical_topic.next_event()?,
        expected: json!({
            "token": token1,
            "distinct_id": distinct_id1,
        })
    );

    assert_json_include!(
        actual: historical_topic.next_event()?,
        expected: json!({
            "token": token1,
            "distinct_id": distinct_id2,
        })
    );

    assert_json_include!(
        actual: historical_topic.next_event()?,
        expected: json!({
            "token": token2,
            "distinct_id": distinct_id2,
        })
    );

    historical_topic.assert_empty();

    Ok(())
}

#[tokio::test]
async fn it_reroutes_to_historical_on_event_timestamp() -> Result<()> {
    setup_tracing();

    // token only will be limited by candidate list
    let token1 = String::from("token1");
    let distinct_id1 = String::from("user1");

    // token:distinct_id will be limited by candidate list
    let token2 = String::from("token2");
    let distinct_id2 = String::from("user2");

    // won't be limited other than by burst/rate-limits
    let token3 = String::from("token3");
    let distinct_id3 = String::from("user3");

    let topic = EphemeralTopic::new().await;
    let historical_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();

    // enable historical rerouting for events w/timestamp older than 1 day
    config.enable_historical_rerouting = true;
    config.historical_rerouting_threshold_days = 1_i64;
    config.historical_tokens_keys = None;

    config.kafka.kafka_hosts = "localhost:9092".to_string();
    config.kafka.kafka_producer_linger_ms = 0; // Send messages immediately
    config.kafka.kafka_message_timeout_ms = 10000; // 10s timeout
    config.kafka.kafka_producer_max_retries = 3;
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_historical_topic = historical_topic.topic_name().to_string();
    config.overflow_enabled = false;
    config.overflow_burst_limit = NonZeroU32::new(10).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(10).unwrap();

    let server = ServerHandle::for_config(config).await;

    let stale_timestamp = Utc::now().checked_sub_days(chrono::Days::new(1)).unwrap();

    let events = vec![
        json!([{
            "token": token1,
            "event": "event1",
            "timestamp": Utc::now().to_rfc3339(),
            "distinct_id": distinct_id1,
        }]),
        json!([{
            "token": token2,
            "event": "event2",
            "timestamp": stale_timestamp.to_rfc3339(),
            "distinct_id": distinct_id2,
        }]),
        json!([{
            "token": token3,
            "event": "event3",
            // missing stamp won't trigger historical reroute
            "distinct_id": distinct_id3,
        }]),
    ];

    for event in events {
        let res = server.capture_events(event.to_string()).await;
        assert_eq!(StatusCode::OK, res.status());
    }

    // main toppic results
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token1}:{distinct_id1}")
    );
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token3}:{distinct_id3}")
    );

    topic.assert_empty();

    // Expected events should be in historical topic
    assert_json_include!(
        actual: historical_topic.next_event()?,
        expected: json!({
            "token": token2,
            "distinct_id": distinct_id2,
        })
    );

    historical_topic.assert_empty();

    Ok(())
}

#[tokio::test]
async fn it_overflows_events_on_burst() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_hosts = "localhost:9092".to_string();
    config.kafka.kafka_producer_linger_ms = 0; // Send messages immediately
    config.kafka.kafka_message_timeout_ms = 10000; // 10s timeout
    config.kafka.kafka_producer_max_retries = 3;
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_overflow_topic = overflow_topic.topic_name().to_string();
    config.overflow_enabled = true;
    config.overflow_burst_limit = NonZeroU32::new(2).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(1).unwrap();

    let server = ServerHandle::for_config(config).await;

    let events = json!([{
        "token": token,
        "event": "event1",
        "distinct_id": distinct_id,
    },{
        "token": token,
        "event": "event2",
        "distinct_id": distinct_id,
    },
    {
        "token": token,
        "event": "event3_to_overflow",
        "distinct_id": distinct_id,
    }]);

    let res = server.capture_events(events.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // First two events should go to main topic
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id}")
    );

    topic.assert_empty();

    // Third event should be in overflow topic, but has no
    // message key as overflow locality is off for this test
    assert_json_include!(
        actual: overflow_topic.next_event()?,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id,
        })
    );

    overflow_topic.assert_empty();

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

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id2}")
    );

    Ok(())
}

#[tokio::test]
async fn it_skips_overflows_when_disabled() -> Result<()> {
    setup_tracing();

    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_overflow_topic = overflow_topic.topic_name().to_string();
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

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id}")
    );

    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id}")
    );

    // Should have triggered overflow, but has not
    assert_eq!(
        topic.next_message_key()?.unwrap(),
        format!("{token}:{distinct_id}")
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
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

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
async fn it_replaces_null_chars_in_distinct_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test cases with null bytes in different positions
    let test_cases = [
        ("user123\0\0\0id", "user123\u{FFFD}\u{FFFD}\u{FFFD}id"), // nulls in middle
        ("\0\0user123", "\u{FFFD}\u{FFFD}user123"),               // nulls at beginning
        ("user123\0\0", "user123\u{FFFD}\u{FFFD}"),               // nulls at end
        ("\0user\0id\0", "\u{FFFD}user\u{FFFD}id\u{FFFD}"),       // nulls scattered
    ];

    for (input_id, expected_id) in test_cases {
        let event = json!({
            "token": token,
            "event": "testing",
            "distinct_id": input_id
        });
        let res = server.capture_events(event.to_string()).await;
        assert_eq!(StatusCode::OK, res.status());

        let event = main_topic.next_event()?;
        assert_json_include!(
            actual: event,
            expected: json!({
                "token": token,
                "distinct_id": expected_id
            })
        );
    }

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
        let res = server.capture_events(payload.to_string()).await;
        assert_eq!(StatusCode::OK, res.status());
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

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

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

    let res = server.capture_events(ok_event.to_string()).await;
    assert_eq!(StatusCode::PAYLOAD_TOO_LARGE, res.status());

    let res = server.capture_events(nok_event.to_string()).await;
    assert_eq!(StatusCode::PAYLOAD_TOO_LARGE, res.status());

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

    let res = server.capture_to_batch(ok_event.to_string()).await;
    assert_eq!(StatusCode::PAYLOAD_TOO_LARGE, res.status());
    let res = server.capture_to_batch(nok_event.to_string()).await;
    assert_eq!(StatusCode::PAYLOAD_TOO_LARGE, res.status());

    Ok(())
}

#[tokio::test]
async fn it_returns_200() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event_payload = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id
    })
    .to_string();

    let client = reqwest::Client::builder()
        .timeout(StdDuration::from_millis(3000))
        .build()
        .unwrap();
    let timestamp = Utc::now().timestamp_millis();
    let url = format!(
        "http://{:?}/i/v0/e/?_={}&ver=1.240.6",
        server.addr, timestamp
    );
    let res = client
        .post(url)
        .body(event_payload)
        .send()
        .await
        .expect("failed to send request");
    assert_eq!(
        StatusCode::OK,
        res.status(),
        "error response: {}",
        res.text().await.unwrap()
    );

    Ok(())
}

#[tokio::test]
async fn it_returns_204_when_beacon_is_1() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    let event_payload = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id
    })
    .to_string();

    let client = reqwest::Client::builder()
        .timeout(StdDuration::from_millis(3000))
        .build()
        .unwrap();
    let timestamp = Utc::now().timestamp_millis();
    let url = format!(
        "http://{:?}/i/v0/e/?_={}&ver=1.240.6&beacon=1",
        server.addr, timestamp
    );
    let res = client
        .post(url)
        .body(event_payload)
        .send()
        .await
        .expect("failed to send request");
    assert_eq!(
        StatusCode::NO_CONTENT,
        res.status(),
        "error response: {}",
        res.text().await.unwrap()
    );

    Ok(())
}
