//! The `backfill` storage mode: the writer reads the backfill topic next to the changelog in its
//! own consumer group and writes SlateDB only. It exists for the one-time load and goes away with
//! the mode after cutover.

use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::gauge;
use personhog_coordination::changelog::{
    watch_changelog_config_loop, CHANGELOG_RECONCILE_INTERVAL,
};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::ChangelogConfig;
use tokio_util::sync::CancellationToken;

use crate::kafka::{PersonConsumer, Source};

const PACE_INTERVAL: Duration = Duration::from_secs(5);
const METADATA_TIMEOUT: Duration = Duration::from_secs(10);

/// A backfill-topic partition writes the shards of the changelog partition with the same number.
/// The range assignor gives both partitions to the same pod.
#[derive(Clone, Debug)]
pub struct BackfillTopic {
    pub topic: Arc<str>,
    pub changelog: Arc<str>,
}

impl BackfillTopic {
    pub fn is_backfill(&self, source: &Source) -> bool {
        *source.topic == *self.topic
    }

    fn owner(&self, source: &Source) -> Source {
        if self.is_backfill(source) {
            Source {
                topic: Arc::clone(&self.changelog),
                partition: source.partition,
            }
        } else {
            source.clone()
        }
    }
}

/// The changelog partition whose shards a row writes; a changelog row owns itself.
pub fn owner(backfill: Option<&BackfillTopic>, source: &Source) -> Source {
    backfill.map_or_else(|| source.clone(), |backfill| backfill.owner(source))
}

/// Pauses the backfill topic while the changelog lags, so live records keep flowing.
pub fn spawn_pacing(consumer: Arc<PersonConsumer>, max_live_lag: i64) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(PACE_INTERVAL);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            ticker.tick().await;
            let consumer = Arc::clone(&consumer);
            let paced = tokio::task::spawn_blocking(move || {
                consumer.pace_backfill(max_live_lag, METADATA_TIMEOUT)
            })
            .await;
            match paced {
                Ok(Ok(pace)) => {
                    gauge!("personhog_writer_backfill_live_lag").set(pace.live_lag as f64);
                    gauge!("personhog_writer_backfill_paused").set(if pace.paused {
                        1.0
                    } else {
                        0.0
                    });
                }
                Ok(Err(e)) => tracing::warn!(error = %e, "backfill pacing failed"),
                Err(e) => tracing::warn!(error = %e, "backfill pacing panicked"),
            }
        }
    });
}

/// A migration's drain waits on the writer group alone, so a backfill writer stops instead of following it.
pub fn stop_on_migration(store: Arc<PersonhogStore>, loaded: ChangelogConfig, handle: Handle) {
    tokio::spawn(async move {
        let _guard = handle.process_scope();
        let cancel = CancellationToken::new();
        let initial_topic = loaded.topic.clone();
        let watch = watch_changelog_config_loop(
            store,
            loaded,
            CHANGELOG_RECONCILE_INTERVAL,
            cancel.clone(),
            move |next| {
                if next.topic == initial_topic && next.draining.is_empty() {
                    ControlFlow::Continue(())
                } else {
                    ControlFlow::Break(())
                }
            },
        );
        tokio::select! {
            _ = handle.shutdown_signal() => cancel.cancel(),
            _ = watch => handle.signal_failure(
                "a changelog migration started; the backfill writer stops".to_string(),
            ),
        }
    });
}
