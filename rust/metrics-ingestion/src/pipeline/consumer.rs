use std::sync::{Arc, Mutex};

use futures::future::BoxFuture;
use futures::FutureExt;
use ingestion_framework::errors::shared_error;
use ingestion_framework::{
    before_batch_step, create_ok_context, new_batching_pipeline, passthrough_after_batch_step,
    per_element, BatchingPipeline, BatchingPipelineOptions, IngestionOutputs, KafkaMessage,
    PipelineConfig, PromiseScheduler, SideEffect, SideEffectHandlingConfig, SideEffectScheduler,
};
use logs_ingestion::pipeline::app_metrics::AppMetricsAggregator;
use logs_ingestion::pipeline::{QuotaLimiting, TeamManager, UsageRecordBatch};
use logs_ingestion::rate_limiter::{Clock, KeyRoot, TokenBucketRedis};

use super::config::MetricsLimiterConfig;
use super::rate_limiter::MetricsRateLimiter;
use super::steps::{
    create_prepare_metrics_message_step, create_produce_metrics_step,
    create_rate_limit_metrics_step,
};
use super::types::{MetricsMessageContext, MetricsPipelineInput};
use super::unknown_tokens::UnknownTokens;
use super::usage::{emit_metrics_usage, MetricsUsageAccumulator, MetricsUsageBatchContext};

pub type BackgroundTask = BoxFuture<'static, anyhow::Result<()>>;

/// The caller passes the token-bucket transport, the key root and the clock, so tests can pin all three.
#[derive(Clone)]
pub struct MetricsPipelineConsumerDeps {
    pub team_manager: Arc<dyn TeamManager>,
    pub quota_limiting: Arc<dyn QuotaLimiting>,
    pub outputs: Arc<dyn IngestionOutputs>,
    pub usage_batch: Arc<dyn UsageRecordBatch>,
    pub token_bucket_redis: Arc<dyn TokenBucketRedis>,
    pub key_root: KeyRoot,
    /// Epoch milliseconds. Everything that reads `Date.now()` in Node reads this.
    pub clock: Clock,
    /// Node's `isDevEnv()`, which maps the `phc_local` token to team 1.
    pub dev_env: bool,
    /// Shadow mode only, so a comparator can find the input message. Node never writes `source_offset`.
    pub source_offset_header: bool,
    /// `None` in shadow mode, because the set lives in production Redis.
    pub unknown_tokens: Option<Arc<dyn UnknownTokens>>,
}

pub struct MetricsPipelineContext {
    pub deps: MetricsPipelineConsumerDeps,
    pub rate_limiter: MetricsRateLimiter,
}

type MetricsPipeline = BatchingPipeline<
    MetricsPipelineInput,
    (),
    MetricsMessageContext,
    MetricsMessageContext,
    MetricsUsageBatchContext,
    (),
>;

fn create_metrics_ingestion_pipeline(
    context: Arc<MetricsPipelineContext>,
    scheduler: Arc<dyn SideEffectScheduler>,
) -> MetricsPipeline {
    let result_config = PipelineConfig {
        outputs: context.deps.outputs.clone(),
        scheduler: scheduler.clone(),
        reject_on_dlq_failure: true,
    };
    new_batching_pipeline(
        |before| {
            before.pipe(before_batch_step("metricsUsageBeforeBatchStep", |_| {
                MetricsUsageBatchContext::default()
            }))
        },
        move |batch| {
            batch
                .message_aware(|b| {
                    b.pipe_chunk(per_element(
                        create_prepare_metrics_message_step(context.clone()),
                        None,
                    ))
                    .pipe_chunk(create_rate_limit_metrics_step(context.clone()))
                    .pipe_chunk(per_element(create_produce_metrics_step(context), None))
                })
                .handle_results(result_config)
                .handle_side_effects(
                    scheduler,
                    SideEffectHandlingConfig {
                        await_side_effects: false,
                    },
                )
        },
        |after| after.pipe(passthrough_after_batch_step("keepMetricsUsageStep")),
        BatchingPipelineOptions {
            concurrent_batches: 1,
        },
    )
}

/// `FailureLatchingPromiseScheduler`. The first failed side effect stays latched, so every later
/// background task fails and no offset is stored for its batch or a later one.
#[derive(Clone, Default)]
pub struct FailureLatchingScheduler {
    inner: PromiseScheduler,
    failure: Arc<Mutex<Option<Arc<anyhow::Error>>>>,
}

impl SideEffectScheduler for FailureLatchingScheduler {
    fn schedule(&self, side_effect: SideEffect) {
        let failure = self.failure.clone();
        self.inner.schedule(SideEffect::spawn(async move {
            side_effect.wait().await.map_err(|error| {
                let error = Arc::new(error);
                failure.lock().unwrap().get_or_insert_with(|| error.clone());
                shared_error(error)
            })
        }));
    }
}

impl FailureLatchingScheduler {
    pub async fn wait_for_all_or_fail(&self) -> anyhow::Result<()> {
        self.inner.wait_for_all().await?;
        match self.failure.lock().unwrap().as_ref() {
            Some(error) => Err(shared_error(error.clone())),
            None => Ok(()),
        }
    }

    pub async fn wait_for_all_settled(&self) {
        self.inner.wait_for_all_settled().await;
    }
}

pub struct MetricsPipelineConsumer {
    context: Arc<MetricsPipelineContext>,
    /// One for the consumer, as in Node, so a background task also waits for side effects of a later batch.
    scheduler: FailureLatchingScheduler,
}

impl MetricsPipelineConsumer {
    pub const NAME: &'static str = "MetricsIngestionConsumer";

    pub fn new(config: MetricsLimiterConfig, deps: MetricsPipelineConsumerDeps) -> Self {
        let rate_limiter = MetricsRateLimiter::new(
            config,
            deps.token_bucket_redis.clone(),
            deps.key_root,
            deps.clock.clone(),
        );
        Self {
            context: Arc::new(MetricsPipelineContext { deps, rate_limiter }),
            scheduler: FailureLatchingScheduler::default(),
        }
    }

    /// `runMetricsIngestionPipeline`. The pipeline is built per batch, so a batch that failed leaves no state behind.
    async fn run_pipeline(
        &self,
        messages: Vec<KafkaMessage>,
    ) -> anyhow::Result<MetricsUsageAccumulator> {
        if messages.is_empty() {
            return Ok(MetricsUsageAccumulator::default());
        }
        let scheduler: Arc<dyn SideEffectScheduler> = Arc::new(self.scheduler.clone());
        let pipeline = create_metrics_ingestion_pipeline(self.context.clone(), scheduler.clone());
        let elements = messages
            .into_iter()
            .map(|message| {
                let message = Arc::new(message);
                create_ok_context(
                    MetricsPipelineInput {
                        message: message.clone(),
                    },
                    MetricsMessageContext { message },
                )
            })
            .collect();
        let fed = pipeline.feed(elements, (), None).await?;
        if let ingestion_framework::FeedResult::Rejected { kind, reason } = fed {
            anyhow::bail!("metrics ingestion pipeline rejected feed: {kind:?} ({reason})");
        }
        let mut usage = MetricsUsageAccumulator::default();
        while let Some(batch) = pipeline.next().await? {
            for side_effect in batch.side_effects {
                scheduler.schedule(side_effect);
            }
            usage = std::mem::take(&mut *batch.batch_context.usage.lock().unwrap());
        }
        Ok(usage)
    }

    /// `handleKafkaBatch`. A failed batch replays, so usage is emitted only after all of its writes succeed.
    pub async fn handle_kafka_batch(
        &self,
        messages: Vec<KafkaMessage>,
    ) -> anyhow::Result<BackgroundTask> {
        let size = messages.len();
        let usage = match self.run_pipeline(messages).await {
            Ok(usage) => usage,
            Err(error) => {
                tracing::error!(error = %error, size, "{} - batch processing failed", Self::NAME);
                // A rejected side effect must not replace the batch error.
                self.scheduler.wait_for_all_settled().await;
                return Err(error);
            }
        };
        let scheduler = self.scheduler.clone();
        let context = self.context.clone();
        Ok(async move {
            scheduler.wait_for_all_or_fail().await?;
            let deps = &context.deps;
            let team_ids: Vec<i64> = usage
                .entries()
                .iter()
                .filter(|(_, stats)| stats.records_allowed > 0.0)
                .map(|(team_id, _)| *team_id)
                .collect();
            deps.team_manager.set_teams_ingested_data(&team_ids).await?;
            let aggregator = AppMetricsAggregator::new(deps.outputs.clone(), deps.clock.clone());
            emit_metrics_usage(&aggregator, deps.usage_batch.as_ref(), &usage).await;
            Ok(())
        }
        .boxed())
    }

    pub async fn stop(&self) {
        self.scheduler.wait_for_all_settled().await;
    }
}
