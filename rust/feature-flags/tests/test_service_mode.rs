use reqwest::StatusCode;

use crate::common::*;
use feature_flags::config::{Config, ServiceMode};

pub mod common;

#[tokio::test]
async fn service_mode_route_availability() {
    let cases: &[(ServiceMode, &[(&str, bool)])] = &[
        (
            ServiceMode::All,
            &[
                ("/flags", true),
                ("/decide", true),
                ("/flags/definitions", true),
            ],
        ),
        (
            ServiceMode::Flags,
            &[
                ("/flags", true),
                ("/decide", true),
                ("/flags/definitions", false),
            ],
        ),
        (
            ServiceMode::Definitions,
            &[
                ("/flags", false),
                ("/decide", false),
                ("/flags/definitions", true),
            ],
        ),
    ];

    for (mode, expectations) in cases {
        let mut config = Config::default_test_config();
        config.service_mode = mode.clone();
        let server = ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        for &(path, reachable) in *expectations {
            let resp = client
                .get(format!("http://{}{}", server.addr, path))
                .send()
                .await
                .unwrap();
            if reachable {
                assert_ne!(
                    resp.status(),
                    StatusCode::NOT_FOUND,
                    "{path} should be reachable in {mode:?} mode",
                );
            } else {
                assert_eq!(
                    resp.status(),
                    StatusCode::NOT_FOUND,
                    "{path} should NOT be reachable in {mode:?} mode",
                );
            }
        }
    }
}

#[tokio::test]
async fn service_mode_health_checks_always_available() {
    for mode in [
        ServiceMode::All,
        ServiceMode::Flags,
        ServiceMode::Definitions,
    ] {
        let mut config = Config::default_test_config();
        config.service_mode = mode.clone();

        let server = ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        for path in ["/", "/_readiness", "/_liveness", "/_startup"] {
            let resp = client
                .get(format!("http://{}{path}", server.addr))
                .send()
                .await
                .unwrap();
            assert_ne!(
                resp.status(),
                StatusCode::NOT_FOUND,
                "{path} should be available in {mode:?} mode"
            );
        }
    }
}
