use anyhow::Result;
use links::config::Config;

use crate::helpers::*;

pub mod helpers;

#[tokio::test]
async fn should_return_404_for_nonexistent_link() -> Result<()> {
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
