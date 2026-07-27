use tokio::sync::watch;

pub async fn wait_for_shutdown(mut shutdown_rx: watch::Receiver<bool>) {
    if *shutdown_rx.borrow() {
        return;
    }

    while shutdown_rx.changed().await.is_ok() {
        if *shutdown_rx.borrow() {
            return;
        }
    }
}
