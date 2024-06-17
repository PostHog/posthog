use anyhow::Error;
use sqlx::query;
use std::{fs, process::Command};
use serde_json::json;
use std::sync::Arc;

use crate::{
    database::{PgClient, Client as DatabaseClientTrait}, flag_definitions::{self, FeatureFlag}, redis::{Client as RedisClientTrait, RedisClient}, team::{self, Team}
};
use rand::{distributions::Alphanumeric, Rng};

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}{}", prefix, suffix)
}

pub async fn insert_new_team_in_redis(client: Arc<RedisClient>) -> Result<Team, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };

    let serialized_team = serde_json::to_string(&team)?;
    client
        .set(
            format!(
                "{}{}",
                team::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await?;

    Ok(team)
}

pub async fn insert_flags_for_team_in_redis(
    client: Arc<RedisClient>,
    team_id: i64,
    json_value: Option<String>,
) -> Result<(), Error> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": team_id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ]
                    },
                ],
            },
        }])
        .to_string(),
    };

    client
        .set(
            format!("{}{}", flag_definitions::TEAM_FLAGS_CACHE_PREFIX, team_id),
            payload,
        )
        .await?;

    Ok(())
}

pub fn setup_redis_client(url: Option<String>) -> Arc<RedisClient> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url).expect("Failed to create redis client");
    Arc::new(client)
}

pub fn create_flag_from_json(json_value: Option<String>) -> Vec<FeatureFlag> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": 1,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ],
                        "rollout_percentage": 50,
                    },
                ],
            },
        }])
        .to_string(),
    };

    let flags: Vec<FeatureFlag> =
        serde_json::from_str(&payload).expect("Failed to parse data to flags list");
    flags
}


pub async fn setup_pg_client(url: Option<String>) -> Arc<PgClient> {
    let pg_url = match url {
        Some(value) => value,
        None => "postgres://posthog:posthog@localhost:5432/test_posthog".to_string(),
    };
    let client = PgClient::new(pg_url).await.expect("Failed to create pg client");
    Arc::new(client)
}

/// Run the Python migration script
pub fn run_database_migrations() -> anyhow::Result<()> {
    // TODO: Make this more efficient by skipping migrations if they have already been run.
    // TODO: Potentially create a separate db, test_posthog_rs, and use here.
    // TODO: Running this in every test is too slow, can I create some setup where this runs only once, and all tests run after?
    // Seems doable easily in CI, how about local dev? Potentially just make it a manual step for now.
    // "Make sure db exists first by running this fn", and then tests will work.....


    let home_directory = fs::canonicalize("../../").expect("Failed to get home directory");
    let output = Command::new("python")
        .current_dir(home_directory)
        .arg("manage.py")
        .arg("migrate")
        .env("DEBUG", "1")
        .env("DATABASE_URL", "postgres://posthog:posthog@localhost:5432/test_posthog")
        .output()
        .expect("Failed to execute migration script");

    if !output.status.success() {
        eprintln!("Migration script failed: {}", String::from_utf8_lossy(&output.stderr));
        return Err(anyhow::anyhow!("Migration script execution failed"));
    }

    println!("Migration script output: {}", String::from_utf8_lossy(&output.stdout));

    Ok(())
}

pub async fn insert_new_team_in_pg(client: Arc<PgClient>) -> Result<Team, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        "INSERT INTO posthog_team (id, name, api_token) VALUES ($1, $2, $3)"
    ).bind(team.id).bind(&team.name).bind(&team.api_token).execute(&mut *conn).await?;
    
    assert_eq!(res.rows_affected(), 1);

    Ok(team)
}