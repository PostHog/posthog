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

use super::Emitter;

pub struct KafkaEmitter {
    state: EmitterState,
    topic: String,
    send_rate: u64, // Messages sent per second
    last_send_finished_time: Option<Instant>,
}

enum EmitterState {
    Idle(TransactionalProducer),
    Transition,
    Writing {
        txn: KafkaTransaction,
        start: Instant,
        count: AtomicUsize,
    },
}

// TODO - this interface kinda sucks - really the emitter should be using typestate or
// something internally, but the trait interface isn't well designed to allow for that
impl EmitterState {
    fn begin(&mut self) -> Result<(), Error> {
        let taken = std::mem::replace(self, Self::Transition);
        match taken {
            Self::Idle(producer) => {
                let transaction = producer.begin()?;
                *self = Self::Writing {
                    txn: transaction,
                    start: Instant::now(),
                    count: AtomicUsize::new(0),
                };
                Ok(())
            }
            _ => {
                *self = taken;
                Err(Error::msg("Invalid state transition"))
            }
        }
    }

    fn commit(&mut self) -> Result<(usize, Instant), Error> {
        let taken = std::mem::replace(self, Self::Transition);
        match taken {
            Self::Writing { txn, count, start } => {
                let producer = txn.commit()?;
                *self = Self::Idle(producer);
                Ok((count.load(Ordering::SeqCst), start))
            }
            _ => {
                *self = taken;
                Err(Error::msg("Invalid state transition"))
            }
        }
    }
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

        let state = EmitterState::Idle(producer);

        Ok(Self {
            state,
            topic: emitter_config.topic,
            send_rate: emitter_config.send_rate,
            last_send_finished_time: None,
        })
    }

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

#[async_trait]
impl Emitter for KafkaEmitter {
    async fn begin_write(&mut self) -> Result<(), Error> {
        self.state.begin()
    }

    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        let EmitterState::Writing { txn, count, .. } = &self.state else {
            return Err(Error::msg("Cannot emit in a non-writing state"));
        };

        txn.send_keyed_iter_to_kafka(&self.topic, |e| Some(e.inner.key()), data.iter())
            .await?;

        count.fetch_add(data.len(), Ordering::SeqCst);

        Ok(())
    }

    async fn commit_write(&mut self) -> Result<(), Error> {
        let (count, start) = self.state.commit()?;
        let min_duration = self.get_min_txn_duration(count, start);
        let txn_elapsed = start.elapsed();
        let to_sleep = min_duration.saturating_sub(txn_elapsed);
        info!(
            "sent {} messages in {:?}, minimum send duration is {:?}, sleeping for {:?}",
            count, txn_elapsed, min_duration, to_sleep
        );
        tokio::time::sleep(to_sleep).await;
        self.last_send_finished_time = Some(Instant::now());
        Ok(())
    }
}
