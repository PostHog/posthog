use reqwest::StatusCode;

use crate::common::*;
use feature_flags::config::{Config, ServiceMode};

pub mod common;

#[tokio::test]
async fn service_mode_all_serves_all_routes() {
    let config = Config::default_test_config();
    assert_eq!(config.service_mode, ServiceMode::All);

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // /flags should be reachable
    let resp = client
        .get(format!("http://{}/flags", server.addr))
        .send()
        .await
        .unwrap();
    assert_ne!(resp.status(), StatusCode::NOT_FOUND);

    // /decide should be reachable
    let resp = client
        .get(format!("http://{}/decide", server.addr))
        .send()
        .await
        .unwrap();
    assert_ne!(resp.status(), StatusCode::NOT_FOUND);

    // /flags/definitions should be reachable
    let resp = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .send()
        .await
        .unwrap();
    assert_ne!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn service_mode_flags_excludes_definitions() {
    let mut config = Config::default_test_config();
    config.service_mode = ServiceMode::Flags;

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // /flags should be reachable
    let resp = client
        .get(format!("http://{}/flags", server.addr))
        .send()
        .await
        .unwrap();
    assert_ne!(resp.status(), StatusCode::NOT_FOUND);

    // /decide should be reachable
    let resp = client
        .get(format!("http://{}/decide", server.addr))
        .send()
        .await
        .unwrap();
    assert_ne!(resp.status(), StatusCode::NOT_FOUND);

    // /flags/definitions should NOT be reachable
    let resp = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn service_mode_definitions_excludes_flags() {
    let mut config = Config::default_test_config();
    config.service_mode = ServiceMode::Definitions;

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // /flags should NOT be reachable
    let resp = client
        .get(format!("http://{}/flags", server.addr))
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);

    // /decide should NOT be reachable
    let resp = client
        .get(format!("http://{}/decide", server.addr))
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);

    // /flags/definitions should be reachable
    let resp = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .send()
        .await
        .unwrap();
    assert_ne!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn service_mode_health_checks_always_available() {
    for mode in [ServiceMode::All, ServiceMode::Flags, ServiceMode::Definitions] {
        let mut config = Config::default_test_config();
        config.service_mode = mode.clone();

        let server = ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!("http://{}/", server.addr))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            StatusCode::OK,
            "/ should be available in {mode:?} mode"
        );

        let resp = client
            .get(format!("http://{}/_readiness", server.addr))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            StatusCode::OK,
            "/_readiness should be available in {mode:?} mode"
        );

        let resp = client
            .get(format!("http://{}/_liveness", server.addr))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            StatusCode::OK,
            "/_liveness should be available in {mode:?} mode"
        );
    }
}
