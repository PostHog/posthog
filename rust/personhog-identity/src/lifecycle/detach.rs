use std::future::Future;
use std::sync::Arc;

use personhog_common::grpc::{
    current_caller_tag, current_client_name, current_method_name, CALLER_TAG, CLIENT_NAME,
    METHOD_NAME,
};
use tokio::sync::Semaphore;
use tokio::task::JoinError;
use tokio_util::task::TaskTracker;
use tracing::Instrument;

const DRIVES_TOTAL: &str = "personhog_lifecycle_detached_drives_total";
const DRIVES_IN_FLIGHT: &str = "personhog_lifecycle_detached_drives_in_flight";

#[derive(Clone)]
pub struct DetachedDrives {
    tracker: TaskTracker,
    permits: Arc<Semaphore>,
}

struct InFlight;

impl InFlight {
    fn new() -> Self {
        metrics::gauge!(DRIVES_IN_FLIGHT).increment(1.0);
        Self
    }
}

impl Drop for InFlight {
    fn drop(&mut self) {
        metrics::gauge!(DRIVES_IN_FLIGHT).decrement(1.0);
    }
}

impl DetachedDrives {
    pub fn new(limit: usize) -> Self {
        Self {
            tracker: TaskTracker::new(),
            permits: Arc::new(Semaphore::new(limit)),
        }
    }

    pub async fn run<F, T>(&self, drive: F) -> Result<T, JoinError>
    where
        F: Future<Output = T> + Send + 'static,
        T: Send + 'static,
    {
        let Ok(permit) = self.permits.clone().try_acquire_owned() else {
            common_metrics::inc(
                DRIVES_TOTAL,
                &[("mode".to_string(), "inline".to_string())],
                1,
            );
            return Ok(drive.await);
        };
        common_metrics::inc(
            DRIVES_TOTAL,
            &[("mode".to_string(), "detached".to_string())],
            1,
        );
        let in_flight = InFlight::new();
        let task = async move {
            let _permit = permit;
            let _in_flight = in_flight;
            drive.await
        };
        let task = CLIENT_NAME.scope(
            current_client_name(),
            CALLER_TAG.scope(
                current_caller_tag(),
                METHOD_NAME.scope(current_method_name(), task),
            ),
        );
        self.tracker
            .spawn(task.instrument(tracing::Span::current()))
            .await
    }

    pub fn in_flight(&self) -> usize {
        self.tracker.len()
    }

    pub fn free_slots(&self) -> usize {
        self.permits.available_permits()
    }

    pub async fn shutdown(&self) {
        self.tracker.close();
        self.tracker.wait().await;
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use tokio::sync::oneshot;
    use tokio::time::timeout;

    use super::DetachedDrives;
    use personhog_common::grpc::{
        current_client_name, current_method_name, CLIENT_NAME, METHOD_NAME,
    };

    fn flag_after(
        flag: &Arc<AtomicBool>,
        delay: Duration,
    ) -> impl std::future::Future<Output = ()> {
        let flag = flag.clone();
        async move {
            tokio::time::sleep(delay).await;
            flag.store(true, Ordering::SeqCst);
        }
    }

    async fn wait_for(flag: &AtomicBool) -> bool {
        for _ in 0..200 {
            if flag.load(Ordering::SeqCst) {
                return true;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        false
    }

    #[tokio::test]
    async fn a_dropped_caller_leaves_the_drive_running() {
        let drives = DetachedDrives::new(4);
        let done = Arc::new(AtomicBool::new(false));

        let dropped = timeout(
            Duration::from_millis(1),
            drives.run(flag_after(&done, Duration::from_millis(50))),
        )
        .await;
        assert!(
            dropped.is_err(),
            "the caller gave up before the drive finished"
        );
        assert_eq!(drives.in_flight(), 1);

        assert!(
            wait_for(&done).await,
            "the drive finished without its caller"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
        assert_eq!(drives.in_flight(), 0);
        assert_eq!(drives.free_slots(), 4);
    }

    #[tokio::test]
    async fn a_drive_past_the_cap_runs_inline_and_dies_with_its_caller() {
        let drives = DetachedDrives::new(1);
        let (release, held) = oneshot::channel::<()>();
        let first = Arc::new(AtomicBool::new(false));
        let first_flag = first.clone();
        let hung_up = timeout(
            Duration::from_millis(1),
            drives.run(async move {
                let _ = held.await;
                first_flag.store(true, Ordering::SeqCst);
            }),
        )
        .await;
        assert!(hung_up.is_err());
        assert_eq!(drives.free_slots(), 0);

        let second = Arc::new(AtomicBool::new(false));
        let dropped = timeout(
            Duration::from_millis(1),
            drives.run(flag_after(&second, Duration::from_millis(20))),
        )
        .await;
        assert!(dropped.is_err());
        tokio::time::sleep(Duration::from_millis(60)).await;
        assert!(
            !second.load(Ordering::SeqCst),
            "an inline drive stops when its caller drops"
        );

        release.send(()).expect("the first drive is still waiting");
        assert!(wait_for(&first).await);
        assert_eq!(drives.free_slots(), 1);
    }

    #[tokio::test]
    async fn a_detached_drive_keeps_the_requests_metric_attribution() {
        let drives = DetachedDrives::new(4);
        let seen = CLIENT_NAME
            .scope(
                Arc::from("router"),
                METHOD_NAME.scope(
                    Arc::from("MergePersons"),
                    drives.run(async { (current_client_name(), current_method_name()) }),
                ),
            )
            .await
            .expect("the drive joins");
        assert_eq!(&*seen.0, "router");
        assert_eq!(&*seen.1, "MergePersons");
    }

    #[tokio::test]
    async fn a_limit_of_zero_never_detaches() {
        let drives = DetachedDrives::new(0);
        let value = drives
            .run(async { 7 })
            .await
            .expect("inline drives cannot fail to join");
        assert_eq!(value, 7);
        assert_eq!(drives.in_flight(), 0);
    }

    #[tokio::test]
    async fn a_panicking_drive_surfaces_as_an_error_and_frees_its_slot() {
        let drives = DetachedDrives::new(1);
        let err = drives
            .run(async { panic!("step blew up") })
            .await
            .expect_err("the panic reaches the caller");
        assert!(err.is_panic());
        assert_eq!(drives.free_slots(), 1);

        let value = drives
            .run(async { 3 })
            .await
            .expect("the slot is usable again");
        assert_eq!(value, 3);
    }

    #[tokio::test]
    async fn shutdown_waits_for_detached_drives_to_finish() {
        let drives = DetachedDrives::new(4);
        let done = Arc::new(AtomicBool::new(false));
        let hung_up = timeout(
            Duration::from_millis(1),
            drives.run(flag_after(&done, Duration::from_millis(50))),
        )
        .await;
        assert!(hung_up.is_err());

        drives.shutdown().await;
        assert!(
            done.load(Ordering::SeqCst),
            "shutdown returned before the drive finished"
        );
        assert_eq!(drives.in_flight(), 0);
    }

    #[tokio::test]
    async fn a_drive_started_while_shutdown_is_draining_is_waited_for_too() {
        let drives = DetachedDrives::new(4);
        let first = Arc::new(AtomicBool::new(false));
        let second = Arc::new(AtomicBool::new(false));
        let hung_up = timeout(
            Duration::from_millis(1),
            drives.run(flag_after(&first, Duration::from_millis(80))),
        )
        .await;
        assert!(hung_up.is_err());

        let shutdown = {
            let drives = drives.clone();
            tokio::spawn(async move { drives.shutdown().await })
        };
        tokio::task::yield_now().await;
        let hung_up = timeout(
            Duration::from_millis(1),
            drives.run(flag_after(&second, Duration::from_millis(40))),
        )
        .await;
        assert!(hung_up.is_err());

        shutdown.await.expect("shutdown task completes");
        assert!(first.load(Ordering::SeqCst));
        assert!(second.load(Ordering::SeqCst));
        assert_eq!(drives.in_flight(), 0);
    }
}
