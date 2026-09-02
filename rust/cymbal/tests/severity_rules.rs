use chrono::Utc;
use cymbal::{
    issue_resolution::{Issue, IssueStatus},
    modes::processing::{
        rules::severity::{
            try_severity_rules, SeverityRule, MAX_SEVERITY_RULES_PER_TEAM,
            MAX_SEVERITY_RULE_BYTECODE_OPS, MAX_SEVERITY_RULE_EVALUATION_STEPS_PER_EVENT,
            MAX_SEVERITY_RULE_STEPS_PER_RULE,
        },
        ProcessingConfig,
    },
    teams::TeamManager,
    types::ProcessedExceptionProperties,
};
use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

fn bytecode(result: bool) -> Value {
    json!(["_H", 1, if result { 29 } else { 30 }, 38])
}

fn rule(team_id: i32, severity: &str, order_key: i32, bytecode: Value) -> SeverityRule {
    SeverityRule {
        id: Uuid::now_v7(),
        team_id,
        severity: severity.to_string(),
        order_key,
        bytecode,
        created_at: Utc::now(),
        updated_at: Utc::now(),
    }
}

fn issue(team_id: i32) -> Issue {
    Issue {
        id: Uuid::now_v7(),
        team_id,
        status: IssueStatus::Active,
        severity: Some("medium".to_string()),
        name: Some("TypeError".to_string()),
        description: Some("Example".to_string()),
        created_at: Utc::now(),
    }
}

fn properties() -> ProcessedExceptionProperties {
    serde_json::from_value(json!({
        "$exception_list": [{"type": "TypeError", "value": "Example"}],
        "$exception_fingerprint": "fingerprint",
        "$exception_fingerprint_record": [{"type": "manual"}],
        "$exception_issue_id": Uuid::nil(),
        "$exception_handled": false,
        "$exception_types": ["TypeError"],
        "$exception_values": ["Example"],
        "$exception_sources": [],
        "$exception_functions": []
    }))
    .unwrap()
}

async fn insert_rule(db: &PgPool, rule: &SeverityRule, disabled: bool) {
    sqlx::query(
        r#"
        INSERT INTO posthog_errortrackingseverityrule
            (id, team_id, filters, bytecode, severity, order_key, disabled_data, created_at, updated_at)
        VALUES ($1, $2, '{}'::jsonb, $3, $4, $5, $6, $7, $8)
        "#,
    )
    .bind(rule.id)
    .bind(rule.team_id)
    .bind(&rule.bytecode)
    .bind(&rule.severity)
    .bind(rule.order_key)
    .bind(disabled.then(|| json!({"message": "disabled"})))
    .bind(rule.created_at)
    .bind(rule.updated_at)
    .execute(db)
    .await
    .unwrap();
}

#[test]
fn supports_every_issue_severity() {
    let issue = json!({"status": "active", "name": "TypeError", "description": "Example"});
    let properties = serde_json::to_value(properties()).unwrap();

    for severity in ["low", "medium", "high", "critical"] {
        let matched = rule(1, severity, 0, bytecode(true))
            .try_match(&issue, &properties)
            .unwrap()
            .unwrap();
        assert_eq!(matched.to_string(), severity);
    }
}

#[test]
fn rejects_oversized_bytecode() {
    let issue = json!({"status": "active", "name": "TypeError", "description": "Example"});
    let properties = serde_json::to_value(properties()).unwrap();
    let oversized = json!(vec![0; MAX_SEVERITY_RULE_BYTECODE_OPS + 1]);

    let result = rule(1, "high", 0, oversized).try_match(&issue, &properties);

    assert!(result.is_err());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn loads_only_enabled_rules_for_the_requested_team(db: PgPool) {
    let enabled = rule(1, "high", 0, bytecode(true));
    let disabled = rule(1, "critical", 1, bytecode(true));
    let other_team = rule(2, "low", 0, bytecode(true));
    insert_rule(&db, &enabled, false).await;
    insert_rule(&db, &disabled, true).await;
    insert_rule(&db, &other_team, false).await;

    let loaded = SeverityRule::load_for_team(&db, 1).await.unwrap();

    assert_eq!(loaded.len(), 1);
    assert_eq!(loaded[0].id, enabled.id);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn loads_at_most_the_per_team_rule_limit(db: PgPool) {
    for order_key in 0..=MAX_SEVERITY_RULES_PER_TEAM {
        let rule = rule(1, "high", order_key as i32, bytecode(false));
        insert_rule(&db, &rule, false).await;
    }

    let loaded = SeverityRule::load_for_team(&db, 1).await.unwrap();

    assert_eq!(loaded.len(), MAX_SEVERITY_RULES_PER_TEAM);
    assert_eq!(loaded.last().unwrap().order_key, 99);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn first_matching_rule_wins_and_no_match_preserves_fallback(db: PgPool) {
    let config = ProcessingConfig::init_with_defaults().unwrap();
    let manager = TeamManager::new(&config);
    let team_id = 1;
    manager.severity_rules.insert(
        team_id,
        vec![
            rule(team_id, "critical", 0, bytecode(false)),
            rule(team_id, "medium", 2, bytecode(true)),
            rule(team_id, "high", 1, bytecode(true)),
        ],
    );
    let mut conn = db.acquire().await.unwrap();

    let matched = try_severity_rules(&mut conn, &manager, &issue(team_id), &properties())
        .await
        .unwrap();
    assert_eq!(matched.unwrap().to_string(), "high");

    manager
        .severity_rules
        .insert(team_id, vec![rule(team_id, "critical", 0, bytecode(false))]);
    let unmatched = try_severity_rules(&mut conn, &manager, &issue(team_id), &properties())
        .await
        .unwrap();
    assert!(unmatched.is_none());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn exact_order_ties_use_rule_id(db: PgPool) {
    let config = ProcessingConfig::init_with_defaults().unwrap();
    let manager = TeamManager::new(&config);
    let team_id = 1;
    let created_at = Utc::now();
    let mut high_id = rule(team_id, "critical", 0, bytecode(true));
    high_id.id = Uuid::from_u128(u128::MAX);
    high_id.created_at = created_at;
    let mut low_id = rule(team_id, "low", 0, bytecode(true));
    low_id.id = Uuid::from_u128(1);
    low_id.created_at = created_at;
    manager
        .severity_rules
        .insert(team_id, vec![high_id, low_id]);
    let mut conn = db.acquire().await.unwrap();

    let matched = try_severity_rules(&mut conn, &manager, &issue(team_id), &properties())
        .await
        .unwrap();

    assert_eq!(matched.unwrap().to_string(), "low");
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn aggregate_step_budget_stops_evaluating_later_rules(db: PgPool) {
    let config = ProcessingConfig::init_with_defaults().unwrap();
    let manager = TeamManager::new(&config);
    let team_id = 1;
    let rules_to_exhaust_budget =
        MAX_SEVERITY_RULE_EVALUATION_STEPS_PER_EVENT / MAX_SEVERITY_RULE_STEPS_PER_RULE;
    let mut rules = (0..rules_to_exhaust_budget)
        .map(|order_key| rule(team_id, "low", order_key as i32, json!(["_H", 1, 39, -2])))
        .collect::<Vec<_>>();
    rules.push(rule(
        team_id,
        "critical",
        rules_to_exhaust_budget as i32,
        bytecode(true),
    ));
    manager.severity_rules.insert(team_id, rules);
    let mut conn = db.acquire().await.unwrap();

    let matched = try_severity_rules(&mut conn, &manager, &issue(team_id), &properties())
        .await
        .unwrap();

    assert!(matched.is_none());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn invalid_rule_is_disabled_and_later_rule_still_matches(db: PgPool) {
    let config = ProcessingConfig::init_with_defaults().unwrap();
    let manager = TeamManager::new(&config);
    let team_id = 1;
    let invalid = rule(team_id, "low", 0, json!("invalid"));
    insert_rule(&db, &invalid, false).await;
    manager.severity_rules.insert(
        team_id,
        vec![
            invalid.clone(),
            rule(team_id, "critical", 1, bytecode(true)),
        ],
    );
    let mut conn = db.acquire().await.unwrap();

    let matched = try_severity_rules(&mut conn, &manager, &issue(team_id), &properties())
        .await
        .unwrap();

    assert_eq!(matched.unwrap().to_string(), "critical");
    let disabled_data: Option<Value> =
        sqlx::query("SELECT disabled_data FROM posthog_errortrackingseverityrule WHERE id = $1")
            .bind(invalid.id)
            .fetch_one(&db)
            .await
            .unwrap()
            .get("disabled_data");
    assert!(disabled_data.is_some());
    assert!(manager.severity_rules.get(&team_id).is_none());
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn step_exhaustion_skips_without_disabling_rule(db: PgPool) {
    let config = ProcessingConfig::init_with_defaults().unwrap();
    let manager = TeamManager::new(&config);
    let team_id = 1;
    let looping = rule(team_id, "low", 0, json!(["_H", 1, 39, -2]));
    insert_rule(&db, &looping, false).await;
    manager.severity_rules.insert(
        team_id,
        vec![
            looping.clone(),
            rule(team_id, "critical", 1, bytecode(true)),
        ],
    );
    let mut conn = db.acquire().await.unwrap();

    let matched = try_severity_rules(&mut conn, &manager, &issue(team_id), &properties())
        .await
        .unwrap();

    assert_eq!(matched.unwrap().to_string(), "critical");
    let disabled_data: Option<Value> =
        sqlx::query("SELECT disabled_data FROM posthog_errortrackingseverityrule WHERE id = $1")
            .bind(looping.id)
            .fetch_one(&db)
            .await
            .unwrap()
            .get("disabled_data");
    assert!(disabled_data.is_none());
}
