use anyhow::Result;
use reqwest::{Method, StatusCode};

use crate::common::*;
use feature_flags::config::DEFAULT_TEST_CONFIG;

pub mod common;

#[tokio::test]
async fn it_handles_http_methods_correctly() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();
    let base_url = format!("http://{}/flags", server.addr);

    // Test OPTIONS method - should return 204 with Allow header
    let options_response = client.request(Method::OPTIONS, &base_url).send().await?;

    // The CORS middleware handles OPTIONS requests and returns 200 OK
    assert_eq!(options_response.status(), StatusCode::OK);

    // CORS middleware uses access-control-allow-methods header
    let allow_header = options_response
        .headers()
        .get("access-control-allow-methods");
    assert!(allow_header.is_some());
    let allow_value = allow_header.unwrap().to_str().unwrap();
    assert!(allow_value.contains("GET"));
    assert!(allow_value.contains("POST"));
    assert!(allow_value.contains("OPTIONS"));
    assert!(allow_value.contains("HEAD"));

    // Test HEAD method - should return headers without body
    let head_response = client.request(Method::HEAD, &base_url).send().await?;

    assert_eq!(head_response.status(), StatusCode::OK);
    let content_type = head_response.headers().get("content-type");
    assert!(content_type.is_some());
    assert_eq!(content_type.unwrap().to_str().unwrap(), "application/json");

    // HEAD response should have empty body
    let body = head_response.text().await?;
    assert!(body.is_empty());

    // Test unsupported method (PUT) - should return 405 Method Not Allowed
    let put_response = client.request(Method::PUT, &base_url).send().await?;

    assert_eq!(put_response.status(), StatusCode::METHOD_NOT_ALLOWED);
    let allow_header = put_response.headers().get("allow");
    assert!(allow_header.is_some());
    let allow_value = allow_header.unwrap().to_str().unwrap();
    assert!(allow_value.contains("GET"));
    assert!(allow_value.contains("POST"));
    assert!(allow_value.contains("OPTIONS"));
    assert!(allow_value.contains("HEAD"));

    // Test DELETE method - should also return 405 Method Not Allowed
    let delete_response = client.request(Method::DELETE, &base_url).send().await?;

    assert_eq!(delete_response.status(), StatusCode::METHOD_NOT_ALLOWED);

    // Test PATCH method - should also return 405 Method Not Allowed
    let patch_response = client.request(Method::PATCH, &base_url).send().await?;

    assert_eq!(patch_response.status(), StatusCode::METHOD_NOT_ALLOWED);

    Ok(())
}
