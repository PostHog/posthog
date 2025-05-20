use anyhow::Result;
use links::{
    config::Config,
    redirect::redis_utils::RedisRedirectKeyPrefix,
    utils::test_utils::{
        insert_new_link_in_pg, insert_new_team_in_pg, setup_pg_client, setup_redis_client,
    },
};

use crate::helpers::*;
use links::types::LinksRedisItem;

pub mod helpers;

#[tokio::test]
async fn should_return_200_for_liveness_check() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;

    let response = client
        .get(format!("http://{}/_liveness", server_handle.addr))
        .send()
        .await?;

    assert_eq!(response.status(), 200);

    Ok(())
}

#[tokio::test]
async fn should_return_200_for_readiness_check() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;

    let response = client
        .get(format!("http://{}/_readiness", server_handle.addr))
        .send()
        .await?;

    assert_eq!(response.status(), 200);

    Ok(())
}

#[tokio::test]
async fn should_return_404_for_nonexistent_internal_link() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!("http://{}/nonexistent_key", server_handle.addr))
        .send()
        .await?;

    assert_eq!(response.status(), 404);

    Ok(())
}

#[tokio::test]
async fn should_return_404_for_nonexistent_external_link() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!("http://{}/ph/nonexistent_key", server_handle.addr))
        .send()
        .await?;

    assert_eq!(response.status(), 404);

    Ok(())
}

#[tokio::test]
async fn should_return_redis_stored_internal_link() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let redis_client = setup_redis_client(None).await;
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    // Store a link in Redis
    let short_code = "test_code";
    let domain = "example.com";
    let expected_url = format!("https://{}", domain);

    let item = LinksRedisItem {
        url: domain.to_string(),
        team_id: None,
    };
    redis_client
        .set_nx_ex(
            RedisRedirectKeyPrefix::Internal
                .get_redis_key_for_url(&server_handle.addr.to_string(), short_code),
            serde_json::to_string(&item).unwrap(),
            3600,
        )
        .await
        .expect("Failed to set link in Redis");

    // Redirect to the stored link
    let response = client
        .get(format!("http://{}/{}", server_handle.addr, short_code))
        .send()
        .await?;

    println!("Response: {:?}", response);
    assert_eq!(response.status(), 302);
    assert_eq!(response.headers().get("Location").unwrap(), &expected_url);

    Ok(())
}

#[tokio::test]
async fn should_return_database_stored_internal_link() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    // Store a link in the database
    let short_code = "test_code";
    let domain = "example.com";
    let expected_url = format!("https://{}", domain);
    let db_client = setup_pg_client(None).await;

    let team = insert_new_team_in_pg(db_client.clone(), None).await?;
    insert_new_link_in_pg(
        db_client.clone(),
        &server_handle.addr.to_string(),
        short_code,
        domain,
        team.id,
    )
    .await?;

    // Redirect to the stored link
    let response = client
        .get(format!("http://{}/{}", server_handle.addr, short_code))
        .send()
        .await?;

    assert_eq!(response.status(), 302);
    assert_eq!(response.headers().get("Location").unwrap(), &expected_url);

    Ok(())
}

#[tokio::test]
async fn should_return_redis_stored_external_link() -> Result<()> {
    let config = Config::default_for_test();
    let server_handle = ServerHandle::for_config(config).await;
    let redis_client = setup_redis_client(None).await;
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    // Store a link in Redis
    let short_code = "test_code";
    let domain = "example.com";
    let expected_url = format!("https://{}", domain);

    let item = LinksRedisItem {
        url: domain.to_string(),
        team_id: None,
    };
    redis_client
        .set_nx_ex(
            RedisRedirectKeyPrefix::External
                .get_redis_key_for_url(&server_handle.addr.to_string(), short_code),
            serde_json::to_string(&item).unwrap(),
            3600,
        )
        .await
        .expect("Failed to set link in Redis");

    // Redirect to the stored link
    let response = client
        .get(format!("http://{}/ph/{}", server_handle.addr, short_code))
        .send()
        .await?;

    assert_eq!(response.status(), 302);
    assert_eq!(response.headers().get("Location").unwrap(), &expected_url);

    Ok(())
}
