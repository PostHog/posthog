//! `personhog-writer properties get`: one person's record in SlateDB next to its Postgres row,
//! judged the way the verifier judges them. For comparing a person the verifier reported.

use common_database::{get_pool_with_config, PoolConfig};
use serde_json::json;

use crate::backfill::cli::limits;
use crate::backfill::scanner::Scanned;
use crate::backfill::verify::{judge, Live};
use crate::config::Config;

#[derive(clap::Args)]
pub struct Properties {
    #[command(subcommand)]
    command: Command,
}

#[derive(clap::Subcommand)]
enum Command {
    /// Prints the record SlateDB holds and the Postgres row, with the verifier's verdict.
    Get(GetArgs),
}

#[derive(clap::Args)]
struct GetArgs {
    #[arg(long)]
    team: i64,
    #[arg(long)]
    person: i64,
}

pub async fn run(
    properties: Properties,
    config: &Config,
) -> Result<(), Box<dyn std::error::Error>> {
    match properties.command {
        Command::Get(args) => get(config, args).await,
    }
}

async fn get(config: &Config, args: GetArgs) -> Result<(), Box<dyn std::error::Error>> {
    let reader = personhog_property_store::PropertyReader::new(
        &config.property_store,
        personhog_property_store::reader_object_store(&config.property_store)?,
    );
    let stored = reader.get_fresh(args.team, args.person).await;
    reader.close().await;
    let stored = stored?;

    let pool = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 1,
            pool_name: Some("personhog-writer-properties".to_string()),
            statement_timeout_ms: Some(10_000),
            ..Default::default()
        },
    )?;
    let row = Live::new(pool, &config.pg_target_table, limits(config))?
        .row(args.team, args.person)
        .await?;

    let document = |bytes: &[u8]| {
        serde_json::from_slice::<serde_json::Value>(bytes)
            .unwrap_or_else(|_| json!(String::from_utf8_lossy(bytes)))
    };
    let (postgres, verdict) = match row {
        Some(Scanned::Record(row) | Scanned::Trimmed(row)) => (
            json!({
                "version": row.version,
                "deleted": row.deleted,
                "created_at": row.created_at,
                "properties": document(&row.properties),
            }),
            judge(&row, stored.as_ref()).label(),
        ),
        Some(Scanned::Reject { reason, .. }) => (json!({ "rejected": reason }), "rejected"),
        None => (serde_json::Value::Null, "no_row"),
    };
    let slatedb = stored.map(|s| {
        json!({
            "version": s.version,
            "deleted": s.deleted,
            "created_at": s.created_at,
            "properties": document(&s.properties),
        })
    });
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "team_id": args.team,
            "person_id": args.person,
            "postgres": postgres,
            "slatedb": slatedb,
            "verdict": verdict,
        }))?
    );
    Ok(())
}
