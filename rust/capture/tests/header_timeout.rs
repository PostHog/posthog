use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

#[path = "common/utils.rs"]
mod test_utils;
use test_utils::{setup_tracing, DEFAULT_CONFIG};

use capture::server::serve;
use tokio::net::TcpListener;
use tokio::sync::Notify;

use std::sync::Arc;

async fn start_server_with_header_timeout(
    timeout_ms: Option<u64>,
) -> (std::net::SocketAddr, Arc<Notify>) {
    let mut config = DEFAULT_CONFIG.clone();
    config.http1_header_read_timeout_ms = timeout_ms;

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let notify = Arc::new(Notify::new());
    let shutdown = notify.clone();

    tokio::spawn(
        async move { serve(config, listener, async move { notify.notified().await }).await },
    );

    // Give server time to start
    tokio::time::sleep(Duration::from_millis(50)).await;

    (addr, shutdown)
}

#[tokio::test]
async fn test_header_read_timeout_closes_connection() {
    setup_tracing();

    // Start server with 500ms header read timeout
    let (addr, _shutdown) = start_server_with_header_timeout(Some(500)).await;

    // Connect and send partial headers (slow loris style)
    let mut stream = TcpStream::connect(addr).await.unwrap();

    // Send just the request line, no complete headers
    stream.write_all(b"GET / HTTP/1.1\r\n").await.unwrap();
    // Don't send the final \r\n to complete headers - this simulates slow loris

    // Wait for longer than the timeout
    tokio::time::sleep(Duration::from_millis(700)).await;

    // Try to read - connection should be closed by server due to timeout
    let mut buf = [0u8; 1024];
    let result = stream.read(&mut buf).await;

    match result {
        Ok(0) => {
            // Connection closed cleanly - expected behavior
        }
        Ok(n) => {
            // Got some response - check if it's an error response
            let response = String::from_utf8_lossy(&buf[..n]);
            // Server might send an error before closing
            assert!(
                response.contains("408") || response.contains("400") || n == 0,
                "Expected connection close or error, got: {response}",
            );
        }
        Err(_) => {
            // Connection error - also acceptable as it means connection was closed
        }
    }
}

#[tokio::test]
async fn test_complete_headers_within_timeout_succeeds() {
    setup_tracing();

    // Start server with 2 second header read timeout
    let (addr, _shutdown) = start_server_with_header_timeout(Some(2000)).await;

    // Connect and send complete headers quickly
    let mut stream = TcpStream::connect(addr).await.unwrap();

    // Send complete request with headers
    stream
        .write_all(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        .await
        .unwrap();

    // Read response - should get a successful response
    let mut buf = [0u8; 1024];
    let result = tokio::time::timeout(Duration::from_secs(3), stream.read(&mut buf)).await;

    match result {
        Ok(Ok(n)) => {
            assert!(n > 0, "Connection closed unexpectedly");
            let response = String::from_utf8_lossy(&buf[..n]);
            // Should get HTTP 200 response for the index route
            assert!(
                response.contains("HTTP/1.1 200") || response.contains("capture"),
                "Expected success response, got: {response}",
            );
        }
        Ok(Err(e)) => {
            panic!("Read error: {e}");
        }
        Err(_) => {
            panic!("Read timed out - server didn't respond");
        }
    }
}

#[tokio::test]
async fn test_disabled_header_timeout_allows_slow_headers() {
    setup_tracing();

    // Start server with header timeout disabled (None)
    let (addr, _shutdown) = start_server_with_header_timeout(None).await;

    // Connect and send partial headers
    let mut stream = TcpStream::connect(addr).await.unwrap();

    // Send partial headers
    stream.write_all(b"GET / HTTP/1.1\r\n").await.unwrap();

    // Wait 500ms (would have timed out if enabled with 500ms timeout)
    tokio::time::sleep(Duration::from_millis(500)).await;

    // Now complete the headers
    stream.write_all(b"Host: localhost\r\n\r\n").await.unwrap();

    // Read response - should still work since timeout was disabled
    let mut buf = [0u8; 1024];
    let result = tokio::time::timeout(Duration::from_secs(3), stream.read(&mut buf)).await;

    match result {
        Ok(Ok(n)) => {
            assert!(
                n > 0,
                "Connection closed unexpectedly - timeout should have been disabled"
            );
            let response = String::from_utf8_lossy(&buf[..n]);
            // Should get HTTP 200 response
            assert!(
                response.contains("HTTP/1.1 200") || response.contains("capture"),
                "Expected success response, got: {response}",
            );
        }
        Ok(Err(e)) => {
            panic!("Read error: {e}");
        }
        Err(_) => {
            panic!("Read timed out");
        }
    }
}
