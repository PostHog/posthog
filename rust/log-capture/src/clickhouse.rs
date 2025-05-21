use std::time::Duration;

use anyhow::{Context, Result};

use clickhouse::Client;
use futures::FutureExt;
use tokio::sync::{mpsc, oneshot};
use tracing::info;

use crate::{config::Config, log_record::LogRow};

#[derive(Clone)]
pub struct ClickHouseWriter {
    pub client: Client,
    _sink: mpsc::Sender<InsertTask>,
}

pub struct InsertTask {
    row: LogRow,
    handle: oneshot::Sender<()>,
}

impl ClickHouseWriter {
    pub async fn new(config: &Config) -> Result<Self> {
        let client = Client::default()
            .with_url(config.clickhouse_url.clone())
            .with_database(config.clickhouse_database.clone())
            .with_user(config.clickhouse_user.clone())
            .with_password(config.clickhouse_password.clone())
            .with_option("async_insert", "1")
            .with_option("wait_for_async_insert", "0");

        // Verify connection
        client
            .query("SELECT 1")
            .execute()
            .await
            .context("Failed to connect to ClickHouse")?;

        info!(
            "Successfully connected to ClickHouse at {}",
            config.clickhouse_url
        );

        let (tx, _rx) = mpsc::channel(1000);
        let res = Self { client, _sink: tx };

        //res.insert_loop(rx, config).await?;

        Ok(res)
    }

    pub async fn insert_loop(
        &self,
        mut rx: mpsc::Receiver<InsertTask>,
        config: &Config,
    ) -> Result<()> {
        let period = Duration::from_millis(config.inserter_period_ms);
        let mut inserter = self
            .client
            .inserter("logs")?
            .with_period(Some(period))
            .with_max_rows(config.inserter_max_rows)
            .with_max_bytes(config.inserter_max_bytes);

        let mut time_left = inserter.time_left().expect("Period is set");
        loop {
            let timeout = tokio::time::sleep(time_left).fuse();

            // Race between receiving a row and timing out
            tokio::select! {
                task = rx.recv() => match task {
                    // If we got a row, insert it, then commit
                    Some(task) => {
                        let (row, _handle) = (task.row, task.handle);
                        inserter.write(&row)?;
                        inserter.commit().await?;
                    }
                    // If we got none, break the loop
                    None => break,
                },
                // If we timed out, commit
                _ = timeout => {
                    inserter.commit().await?;
                }
            };

            // Always reset the timer
            time_left = inserter.time_left().expect("Period is set");
        }

        inserter.end().await?;
        Ok(())
    }
}
