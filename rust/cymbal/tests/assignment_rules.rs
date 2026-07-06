use chrono::Utc;
use cymbal::{
    issue_resolution::{Issue, IssueStatus},
    modes::processing::rules::assignment::AssignmentRule,
    modes::processing::ProcessingConfig,
    stages::linking::issue::process_assignment,
    teams::TeamManager,
    types::exception_properties::ExceptionProperties,
};
use serde_json::{json, Value as JsonValue};
use sqlx::PgPool;
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

fn get_test_rule() -> AssignmentRule {
    AssignmentRule {
        id: Uuid::new_v4(),
        team_id: 1,
        user_id: Some(1), // This rule assigns the issue to user with ID 1
        role_id: None,
        order_key: 1,
        bytecode: rule_bytecode(),
        created_at: Utc::now(),
        updated_at: Utc::now(),
    }
}

fn test_props() -> ExceptionProperties {
    // process_assignment calls to_output(), which requires the materialized
    // search fields to be present, so seed them (empty, since exception_list is empty).
    serde_json::from_value(json!({
        "$exception_list": [],
        "$exception_types": [],
        "$exception_values": [],
        "$exception_sources": [],
        "$exception_functions": [],
        "$exception_handled": false,
        "$exception_fingerprint": "test value",
        "$exception_proposed_fingerprint": "test value",
        "test_value": "test_value",
    }))
    .unwrap()
}

fn test_issue() -> Issue {
    Issue {
        id: Uuid::now_v7(),
        team_id: 1,
        status: IssueStatus::Active,
        name: None,
        description: None,
        created_at: Utc::now(),
    }
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_assignment_processing(db: PgPool) {
    let config = ProcessingConfig::init_with_defaults().unwrap();

    let test_team_id = 1;
    let test_props = test_props();

    let issue = test_issue();

    let rule = get_test_rule();
    let team_manager = TeamManager::new(&config);
    // Insert the rule, so we skip the DB lookup
    team_manager
        .assignment_rules
        .insert(test_team_id, vec![rule]);

    let mut conn = db.acquire().await.unwrap();

    let res = process_assignment(&mut conn, &team_manager, &issue, &test_props)
        .await
        .unwrap();

    // The assignment returned is the one from the rule
    assert!(res.is_some());
    let res = res.unwrap();
    assert_eq!(res.user_id, Some(1));

    let existing = res;

    // Now, do the assignment again, but this time assigning a different user. The original assignment should be
    // returned, since we want to respect existing assignments when processing exceptions, and we're re-using the
    // issue
    let mut rule = get_test_rule();
    rule.user_id = Some(2);

    team_manager
        .assignment_rules
        .insert(test_team_id, vec![rule]);

    let res = process_assignment(&mut conn, &team_manager, &issue, &test_props)
        .await
        .unwrap();

    assert!(res.is_some());
    let res = res.unwrap();
    assert_eq!(res.user_id, existing.user_id);
    assert_eq!(res.role_id, existing.role_id);
}
