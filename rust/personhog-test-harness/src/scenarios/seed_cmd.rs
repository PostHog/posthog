use anyhow::{Context, Result};
use sqlx::postgres::PgPool;

use crate::cli::{CleanupArgs, SeedArgs};
use crate::seed;

pub async fn run(args: SeedArgs) -> Result<()> {
    let pool = PgPool::connect(&args.persons_db_url)
        .await
        .context("connecting to persons DB")?;

    let ids = seed::seed_persons(&pool, args.team_id, args.count).await?;

    println!("Seeded {} persons for team {}", ids.len(), args.team_id);
    println!();
    println!(
        "  --team-id {} --person-ids {}",
        args.team_id,
        ids.iter().map(i64::to_string).collect::<Vec<_>>().join(",")
    );
    Ok(())
}

pub async fn run_cleanup(args: CleanupArgs) -> Result<()> {
    let pool = PgPool::connect(&args.persons_db_url)
        .await
        .context("connecting to persons DB")?;

    let persons = seed::cleanup_team(&pool, args.team_id).await?;
    println!("Deleted {persons} persons for team {}", args.team_id);
    Ok(())
}
