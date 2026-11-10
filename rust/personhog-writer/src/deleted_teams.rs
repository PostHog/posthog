//! Every tick, each team listed in `personhog_deleted_teams` has its keys deleted from the owned
//! shards, so a record that arrives late for a deleted team is erased on the next tick.

use std::sync::Arc;
use std::time::Duration;

use metrics::{counter, gauge};
use personhog_property_store::PropertyWriter;
use sqlx::PgPool;

const TICK: Duration = Duration::from_secs(60);

pub async fn deleted_teams(pool: &PgPool) -> Result<Vec<i64>, sqlx::Error> {
    let teams: Vec<i32> =
        sqlx::query_scalar("SELECT team_id FROM personhog_deleted_teams ORDER BY team_id")
            .fetch_all(pool)
            .await?;
    Ok(teams.into_iter().map(i64::from).collect())
}

pub async fn erase_listed(pool: &PgPool, writer: &PropertyWriter) -> Result<usize, sqlx::Error> {
    let teams = deleted_teams(pool).await?;
    gauge!("personhog_writer_deleted_teams").set(teams.len() as f64);
    let mut erased = 0;
    for team_id in teams {
        match writer.erase_team(team_id).await {
            Ok(keys) => {
                erased += keys;
                counter!("personhog_writer_team_erasures_total", "outcome" => "ok").increment(1);
            }
            Err(e) => {
                counter!("personhog_writer_team_erasures_total", "outcome" => "failed")
                    .increment(1);
                tracing::warn!(team_id, error = %e, "erasing a deleted team failed; retrying next tick");
            }
        }
    }
    Ok(erased)
}

pub fn spawn(pool: PgPool, writer: Arc<PropertyWriter>) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(TICK);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            ticker.tick().await;
            if let Err(e) = erase_listed(&pool, &writer).await {
                counter!("personhog_writer_team_erasures_total", "outcome" => "list_failed")
                    .increment(1);
                tracing::warn!(error = %e, "listing deleted teams failed; retrying next tick");
            }
        }
    });
}
