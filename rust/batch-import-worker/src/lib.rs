use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};

use health::HealthHandle;

pub mod config;
pub mod context;
pub mod emit;
pub mod error;
pub mod extractor;
pub mod job;
pub mod parse;
pub mod source;

// During job init, we can hang for a long time initialising sinks or sources, so we kick off a task to
// report that we're alive while we do it.
pub fn spawn_liveness_loop(liveness: Arc<HealthHandle>) -> Arc<AtomicBool> {
    let run = Arc::new(AtomicBool::new(true));
    let liveness = liveness.clone();
    let run_weak = Arc::downgrade(&run); // Use a weak so if the returned arc is dropped the task will exit
    tokio::task::spawn(async move {
        let Some(flag) = run_weak.upgrade() else {
            return;
        };
        while flag.load(Ordering::Relaxed) {
            liveness.report_healthy().await;
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });
    run
}
