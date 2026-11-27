use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use futures::FutureExt;
use ingestion_framework::KafkaMessage;
use logs_ingestion::js::json_parse;
use logs_ingestion::pipeline::scenario::PinnedClock;
use logs_ingestion::rate_limiter::{LuaScript, ScriptCall, ScriptReply, TokenBucketRedis};
use logs_ingestion::service::config::ConsumerLoopConfig;
use logs_ingestion::service::consumer_loop::{
    run_consumer_loop, BackgroundTask, BatchProcessor, BatchSource, OffsetsToStore,
};
use metrics_ingestion::pipeline::scenario::scenario_parts;
use metrics_ingestion::pipeline::MetricsPipelineConsumer;
use tokio::sync::Notify;

struct NoRedis;

#[async_trait]
impl TokenBucketRedis for NoRedis {
    async fn eval_pipeline(
        &self,
        _script: &LuaScript,
        _calls: &[ScriptCall],
    ) -> Result<Vec<ScriptReply>, String> {
        panic!("rate limiting is disabled in this scenario")
    }
}

struct FakeSource {
    batches: VecDeque<Vec<KafkaMessage>>,
    stored: Arc<Mutex<Vec<OffsetsToStore>>>,
}

#[async_trait]
impl BatchSource for FakeSource {
    async fn next_batch(
        &mut self,
        _max: usize,
        timeout: Duration,
    ) -> anyhow::Result<Vec<KafkaMessage>> {
        match self.batches.pop_front() {
            Some(batch) => Ok(batch),
            None => {
                tokio::time::sleep(timeout).await;
                Ok(vec![])
            }
        }
    }
    fn store_offsets(&mut self, offsets: &OffsetsToStore, _epochs: &[u64]) -> anyhow::Result<()> {
        self.stored.lock().unwrap().push(offsets.clone());
        Ok(())
    }
    fn commit(&mut self) -> anyhow::Result<()> {
        Ok(())
    }
}

/// Runs the second batch's background task to the end before the first one starts waiting.
struct SecondTaskFirst {
    consumer: MetricsPipelineConsumer,
    batches_seen: Mutex<u32>,
    second_done: Arc<Notify>,
}

#[async_trait]
impl BatchProcessor for SecondTaskFirst {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        let task = self.consumer.handle_kafka_batch(messages).await?;
        let first = {
            let mut seen = self.batches_seen.lock().unwrap();
            *seen += 1;
            *seen == 1
        };
        let gate = self.second_done.clone();
        Ok(Some(if first {
            async move {
                gate.notified().await;
                task.await
            }
            .boxed()
        } else {
            async move {
                let result = task.await;
                gate.notify_one();
                result
            }
            .boxed()
        }))
    }
}

fn message(token: &str, offset: i64) -> KafkaMessage {
    KafkaMessage {
        topic: "metrics_ingestion".into(),
        partition: 0,
        offset,
        value: Some(format!("packet {offset}").into_bytes().into()),
        headers: vec![
            ("token".into(), Some(token.as_bytes().to_vec())),
            ("bytes_uncompressed".into(), Some(b"100".to_vec())),
        ],
        ..Default::default()
    }
}

#[tokio::test]
async fn a_failed_dlq_write_keeps_its_batch_offsets_unstored_when_a_later_task_waits_first() {
    let scenario = json_parse(
        r#"{
            "config": {"METRICS_LIMITER_ENABLED_TEAMS": ""},
            "teams": [{"id": 1, "api_token": "token-a"}, {"id": 2, "api_token": "token-b"}],
            "produce_faults": [
                {"output": "metrics", "team_id": "1", "times": 1,
                 "error": {"kind": "message_size_too_large", "message": "too large"}},
                {"output": "dlq", "times": 1, "error": {"kind": "error", "message": "dlq down"}}
            ]
        }"#,
    )
    .unwrap();
    let parts = scenario_parts(&scenario, Arc::new(NoRedis), PinnedClock::new(0.0).clock());
    let processor = SecondTaskFirst {
        consumer: MetricsPipelineConsumer::new(parts.config, parts.deps),
        batches_seen: Mutex::new(0),
        second_done: Arc::new(Notify::new()),
    };
    let stored = Arc::new(Mutex::new(Vec::new()));
    let mut source = FakeSource {
        batches: vec![vec![message("token-a", 0)], vec![message("token-b", 1)]].into(),
        stored: stored.clone(),
    };
    let config = ConsumerLoopConfig {
        batch_size: 10,
        batch_timeout: Duration::from_millis(1),
        max_background_tasks: 2,
        background_task_timeout: Duration::from_secs(5),
    };
    let result = tokio::time::timeout(
        Duration::from_secs(10),
        run_consumer_loop(
            &mut source,
            &processor,
            &config,
            futures::future::pending(),
            &|| {},
        ),
    )
    .await
    .expect("the failed task ends the loop");
    assert_eq!(result.unwrap_err().to_string(), "dlq down");
    assert_eq!(*stored.lock().unwrap(), Vec::<OffsetsToStore>::new());
}
