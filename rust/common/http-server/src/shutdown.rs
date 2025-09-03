use tokio::signal;

/// Creates a future that completes when a graceful shutdown signal is received
///
/// This function listens for SIGTERM and SIGINT signals and returns a future
/// that completes when either signal is received. This is commonly used with
/// HTTP servers to implement graceful shutdown.
///
/// # Examples
///
/// ```no_run
/// use http_server::graceful_shutdown;
///
/// # async fn example() -> Result<(), Box<dyn std::error::Error>> {
/// // With axum (requires axum dependency):
/// // Server::bind(&addr)
/// //     .serve(app.into_make_service())
/// //     .with_graceful_shutdown(graceful_shutdown())
/// //     .await?;
///
/// // Or with any other server that accepts a shutdown future
/// # Ok(())
/// # }
/// ```
///
/// # Platform Support
///
/// This function is Unix-specific and will panic on non-Unix platforms.
/// On Unix systems, it listens for:
/// - SIGTERM (termination signal, typically sent by process managers)
/// - SIGINT (interrupt signal, typically Ctrl+C)
pub async fn graceful_shutdown() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");

    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn test_graceful_shutdown_timeout() {
        // Test that graceful_shutdown doesn't complete immediately
        // We can't easily test signal reception in unit tests, but we can verify
        // that the function doesn't complete on its own
        let result = timeout(Duration::from_millis(100), graceful_shutdown()).await;

        // Should timeout because no signal was sent
        assert!(
            result.is_err(),
            "graceful_shutdown should not complete without a signal"
        );
    }
}
