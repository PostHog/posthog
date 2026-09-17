use anyhow::Result;
use capture_load_gen::reset::reset_team_on_pool;
use capture_load_gen::verify::Verifier;
use sqlx::{PgPool, Row};

const TEAM: i64 = 5163;
const TMP_PERSON: &str = "personhog_person_tmp";
const TMP_PDI: &str = "personhog_persondistinctid_tmp";

async fn create_schema(pool: &PgPool) -> Result<()> {
    for stmt in [
        "CREATE TABLE posthog_person (id bigint, team_id bigint, uuid text, \
         properties jsonb, is_identified boolean, is_deleted boolean, \
         created_at timestamptz, PRIMARY KEY (team_id, id))",
        "CREATE TABLE posthog_persondistinctid (id bigint PRIMARY KEY, team_id bigint, \
         distinct_id text, person_id bigint, is_deleted boolean)",
        "CREATE TABLE personhog_person_tmp (LIKE posthog_person INCLUDING ALL)",
        "CREATE TABLE personhog_persondistinctid_tmp (LIKE posthog_persondistinctid INCLUDING ALL)",
    ] {
        sqlx::query(stmt).execute(pool).await?;
    }
    Ok(())
}

async fn insert_person(
    pool: &PgPool,
    table: &str,
    team: i64,
    id: i64,
    identified: bool,
) -> Result<()> {
    sqlx::query(&format!(
        "INSERT INTO {table} (id, team_id, uuid, properties, is_identified, is_deleted, created_at) \
         VALUES ($1, $2, $3, '{{}}'::jsonb, $4, false, to_timestamp(1700000000))"
    ))
    .bind(id)
    .bind(team)
    .bind(format!("uuid-{id}"))
    .bind(identified)
    .execute(pool)
    .await?;
    Ok(())
}

async fn insert_pdi(
    pool: &PgPool,
    table: &str,
    team: i64,
    id: i64,
    distinct_id: &str,
    person_id: i64,
) -> Result<()> {
    sqlx::query(&format!(
        "INSERT INTO {table} (id, team_id, distinct_id, person_id, is_deleted) \
         VALUES ($1, $2, $3, $4, false)"
    ))
    .bind(id)
    .bind(team)
    .bind(distinct_id)
    .bind(person_id)
    .execute(pool)
    .await?;
    Ok(())
}

async fn seed_leg(
    pool: &PgPool,
    person_table: &str,
    pdi_table: &str,
    team: i64,
    id: i64,
    distinct_id: &str,
) -> Result<()> {
    insert_person(pool, person_table, team, id, true).await?;
    insert_pdi(pool, pdi_table, team, id, distinct_id, id).await
}

async fn count_for_team(pool: &PgPool, table: &str, team: i64) -> Result<i64> {
    let row = sqlx::query(&format!(
        "SELECT count(*) AS n FROM {table} WHERE team_id = $1"
    ))
    .bind(team)
    .fetch_one(pool)
    .await?;
    Ok(row.get::<i64, _>("n"))
}

fn verifier(pool: &PgPool) -> Verifier {
    Verifier::from_pool(pool.clone(), TEAM, TMP_PERSON.into(), TMP_PDI.into())
}

#[sqlx::test]
async fn identical_graphs_report_no_mismatch(pool: PgPool) -> Result<()> {
    create_schema(&pool).await?;
    for (id, d) in [(1, "a"), (2, "b"), (3, "c")] {
        seed_leg(
            &pool,
            "posthog_person",
            "posthog_persondistinctid",
            TEAM,
            id,
            d,
        )
        .await?;
        seed_leg(&pool, TMP_PERSON, TMP_PDI, TEAM, id, d).await?;
    }
    let counts = verifier(&pool).sweep().await?;
    assert_eq!(counts.mismatched, 0);
    assert_eq!(counts.main, 3);
    assert_eq!(counts.cohort, 3);
    Ok(())
}

#[sqlx::test]
async fn a_person_missing_from_shadow_is_reported(pool: PgPool) -> Result<()> {
    create_schema(&pool).await?;
    seed_leg(
        &pool,
        "posthog_person",
        "posthog_persondistinctid",
        TEAM,
        1,
        "a",
    )
    .await?;
    let counts = verifier(&pool).sweep().await?;
    assert_eq!(counts.mismatched, 1);
    assert_eq!(counts.missing_shadow, 1);
    Ok(())
}

#[sqlx::test]
async fn sub_millisecond_created_at_is_not_a_divergence(pool: PgPool) -> Result<()> {
    create_schema(&pool).await?;
    // Authoritative keeps microseconds; the writer stores the same instant at
    // millisecond resolution. They must compare equal.
    sqlx::query(
        "INSERT INTO posthog_person (id, team_id, uuid, properties, is_identified, is_deleted, created_at) \
         VALUES (1, $1, 'u', '{}'::jsonb, true, false, '2023-11-14 22:13:20.123456+00')",
    )
    .bind(TEAM)
    .execute(&pool)
    .await?;
    insert_pdi(&pool, "posthog_persondistinctid", TEAM, 1, "a", 1).await?;
    sqlx::query(
        "INSERT INTO personhog_person_tmp (id, team_id, uuid, properties, is_identified, is_deleted, created_at) \
         VALUES (1, $1, 'u', '{}'::jsonb, true, false, '2023-11-14 22:13:20.123+00')",
    )
    .bind(TEAM)
    .execute(&pool)
    .await?;
    insert_pdi(&pool, TMP_PDI, TEAM, 1, "a", 1).await?;
    let counts = verifier(&pool).sweep().await?;
    assert_eq!(counts.created_at, 0, "sub-ms difference must not be drift");
    assert_eq!(counts.mismatched, 0);
    Ok(())
}

#[sqlx::test]
async fn a_dangling_id_does_not_hide_other_drift(pool: PgPool) -> Result<()> {
    create_schema(&pool).await?;
    // A shadow distinct id whose person is absent yields no join row.
    insert_pdi(&pool, TMP_PDI, TEAM, 10, "a", 999).await?;
    // A real divergence must still be counted alongside it.
    seed_leg(
        &pool,
        "posthog_person",
        "posthog_persondistinctid",
        TEAM,
        2,
        "b",
    )
    .await?;
    let counts = verifier(&pool).sweep().await?;
    assert_eq!(
        counts.missing_shadow, 1,
        "the divergence must still be found"
    );
    Ok(())
}

#[sqlx::test]
async fn reset_clears_the_team_and_leaves_others(pool: PgPool) -> Result<()> {
    create_schema(&pool).await?;
    for id in 1..=5 {
        let d = format!("d{id}");
        seed_leg(
            &pool,
            "posthog_person",
            "posthog_persondistinctid",
            TEAM,
            id,
            &d,
        )
        .await?;
        seed_leg(&pool, TMP_PERSON, TMP_PDI, TEAM, id, &d).await?;
    }
    // Another team, including a person whose id collides with this team's
    // cohort (person id is unique only per team), must survive the reset.
    seed_leg(
        &pool,
        "posthog_person",
        "posthog_persondistinctid",
        999,
        100,
        "z",
    )
    .await?;
    seed_leg(&pool, TMP_PERSON, TMP_PDI, 999, 100, "z").await?;
    insert_person(&pool, "posthog_person", 999, 1, true).await?;
    insert_person(&pool, TMP_PERSON, 999, 1, true).await?;

    reset_team_on_pool(&pool, TEAM, TMP_PERSON, TMP_PDI, 2).await?;

    for table in [
        "posthog_person",
        "posthog_persondistinctid",
        TMP_PERSON,
        TMP_PDI,
    ] {
        assert_eq!(
            count_for_team(&pool, table, TEAM).await?,
            0,
            "{table} not cleared"
        );
    }
    assert_eq!(
        count_for_team(&pool, "posthog_person", 999).await?,
        2,
        "other team wiped"
    );
    assert_eq!(
        count_for_team(&pool, TMP_PERSON, 999).await?,
        2,
        "other team's tmp wiped"
    );
    Ok(())
}
