use cymbal::{config::Config, suppression_rules::SuppressionRule, teams::TeamManager};
use serde_json::{json, Value as JsonValue};
use sqlx::{PgPool, Row};
use uuid::Uuid;

fn rule_bytecode() -> JsonValue {
    // return properties.test_value = 'test_value'
    json!([
        "_H",
        1,
        32,
        "test_value",
        32,
        "test_value",
        32,
        "properties",
        1,
        2,
        11,
        38
    ])
}

async fn insert_suppression_rule(db: &PgPool, team_id: i32, bytecode: JsonValue) -> Uuid {
    let id = Uuid::now_v7();
    sqlx::query(
        r#"
            INSERT INTO posthog_errortrackingsuppressionrule
                (id, team_id, order_key, bytecode, filters, sampling_rate, created_at, updated_at)
            VALUES ($1, $2, 0, $3, '{}'::jsonb, 1.0, NOW(), NOW())
        "#,
    )
    .bind(id)
    .bind(team_id)
    .bind(&bytecode)
    .execute(db)
    .await
    .unwrap();
    id
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_suppression_rule_load_and_match(db: PgPool) {
    let team_id = 1;
    let bytecode = rule_bytecode();

    let inserted_id = insert_suppression_rule(&db, team_id, bytecode).await;

    // Load rules from DB
    let rules = SuppressionRule::load_for_team(&db, team_id).await.unwrap();
    assert_eq!(rules.len(), 1);
    assert_eq!(rules[0].id, inserted_id);
    assert_eq!(rules[0].team_id, team_id);

    // Matching props should return true
    let matching_props = json!({"test_value": "test_value"});
    assert!(rules[0].try_match(&matching_props).unwrap());

    // Non-matching props should return false
    let non_matching_props = json!({"test_value": "other_value"});
    assert!(!rules[0].try_match(&non_matching_props).unwrap());

    // Missing property should return false
    let missing_props = json!({"other_key": "test_value"});
    assert!(!rules[0].try_match(&missing_props).unwrap());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_suppression_rule_disable(db: PgPool) {
    let team_id = 1;

    // Insert a rule with invalid bytecode that will cause evaluation to fail
    let invalid_bytecode = json!(["_H", 1, 99]);
    let inserted_id = insert_suppression_rule(&db, team_id, invalid_bytecode).await;

    // Load the rule
    let rules = SuppressionRule::load_for_team(&db, team_id).await.unwrap();
    assert_eq!(rules.len(), 1);

    let rule = &rules[0];

    // try_match should fail on invalid bytecode
    let props = json!({"test_value": "test_value"});
    assert!(rule.try_match(&props).is_err());

    // Disable the rule
    let error_message = "bytecode evaluation failed".to_string();
    rule.disable(&db, error_message.clone(), props.clone())
        .await
        .unwrap();

    // Verify the rule is no longer returned by load_for_team (disabled_data IS NOT NULL)
    let rules_after = SuppressionRule::load_for_team(&db, team_id).await.unwrap();
    assert!(rules_after.is_empty());

    // Verify the disabled_data was actually set in the DB
    let row = sqlx::query(
        r#"
            SELECT disabled_data
            FROM posthog_errortrackingsuppressionrule
            WHERE id = $1
        "#,
    )
    .bind(inserted_id)
    .fetch_one(&db)
    .await
    .unwrap();

    let disabled_data: JsonValue = row.get("disabled_data");
    assert_eq!(disabled_data["message"], error_message);
    assert_eq!(disabled_data["props"], props);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_suppression_rule_cache(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let team_manager = TeamManager::new(&config);
    let team_id = 1;

    // Insert a rule into the DB
    insert_suppression_rule(&db, team_id, rule_bytecode()).await;

    // First call should miss the cache and load from DB
    let rules = team_manager
        .get_suppression_rules(&db, team_id)
        .await
        .unwrap();
    assert_eq!(rules.len(), 1);

    // Insert another rule into the DB
    insert_suppression_rule(&db, team_id, rule_bytecode()).await;

    // Second call should hit the cache and still return only 1 rule
    let cached_rules = team_manager
        .get_suppression_rules(&db, team_id)
        .await
        .unwrap();
    assert_eq!(cached_rules.len(), 1);

    // Invalidate the cache for this team
    team_manager.suppression_rules.invalidate(&team_id);

    // Next call should miss the cache and load from DB, returning 2 rules
    let refreshed_rules = team_manager
        .get_suppression_rules(&db, team_id)
        .await
        .unwrap();
    assert_eq!(refreshed_rules.len(), 2);
}
