use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

use anyhow::Error;
use async_trait::async_trait;
use common_kafka::transaction::{KafkaTransaction, TransactionalProducer};
use common_types::InternallyCapturedEvent;
use tracing::info;

use crate::{context::AppContext, job::config::KafkaEmitterConfig};

use super::{Emitter, Transaction};

pub struct KafkaEmitter {
    producer: TransactionalProducer,
    topic: String,
    send_rate: u64, // Messages sent per second
    last_send_finished_time: Option<Instant>,
}

pub struct KafkaEmitterTransaction<'a> {
    inner: KafkaTransaction<'a>,
    topic: &'a str,
    last_send_finished_time: Option<Instant>,
    send_rate: u64,
    start: Instant,
    count: AtomicUsize,
}

impl KafkaEmitter {
    pub async fn new(
        emitter_config: KafkaEmitterConfig,
        transactional_id: &str, // Kafka transactional ID
        context: Arc<AppContext>,
    ) -> Result<Self, Error> {
        let producer = TransactionalProducer::from_config(
            &context.config.kafka,
            transactional_id,
            Duration::from_secs(emitter_config.transaction_timeout_seconds),
        )?;

        Ok(Self {
            producer,
            topic: emitter_config.topic,
            send_rate: emitter_config.send_rate,
            last_send_finished_time: None,
        })
    }
}

#[async_trait]
impl Emitter for KafkaEmitter {
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error> {
        let txn = self.producer.begin()?;
        Ok(Box::new(KafkaEmitterTransaction {
            inner: txn,
            start: Instant::now(),
            topic: &self.topic,
            last_send_finished_time: self.last_send_finished_time,
            send_rate: self.send_rate,
            count: AtomicUsize::new(0),
        }))
    }
}

#[async_trait]
impl<'a> Transaction<'a> for KafkaEmitterTransaction<'a> {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        self.inner
            .send_keyed_iter_to_kafka(&self.topic, |e| Some(e.inner.key()), data.iter())
            .await?;

        self.count.fetch_add(data.len(), Ordering::SeqCst);

        Ok(())
    }

    async fn commit_write(self: Box<Self>) -> Result<(), Error> {
        let unboxed = *self;
        let count = unboxed.count.load(Ordering::SeqCst);
        let min_duration = unboxed.get_min_txn_duration(count, unboxed.start);
        let txn_elapsed = unboxed.start.elapsed();
        let to_sleep = min_duration.saturating_sub(txn_elapsed);
        info!(
            "sent {} messages in {:?}, minimum send duration is {:?}, sleeping for {:?}",
            count, txn_elapsed, min_duration, to_sleep
        );
        tokio::time::sleep(to_sleep).await;
        unboxed.inner.commit()?;
        Ok(())
    }
}

impl<'a> KafkaEmitterTransaction<'a> {
    fn get_min_txn_duration(&self, txn_count: usize, txn_start: Instant) -> Duration {
        // Get how long the send must take if this is the first send
        let send_rate = self.send_rate as f64;
        let batch_size = txn_count as f64;
        let mut min_duration = Duration::from_secs_f64(batch_size / send_rate);

        // If we've sent before, and there's a gap between the last send and now, we can subtract that
        // from the minimum duration, since it's a period we spent not-sending
        if let Some(instant) = self.last_send_finished_time {
            let gap = txn_start - instant;
            min_duration = min_duration.saturating_sub(gap);
        }
        min_duration
    }
}
