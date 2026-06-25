mod common;

use common::TestContext;
use personhog_replica::storage::postgres::ConsistencyLevel;
use personhog_replica::storage::GroupKey;
use rand::Rng;
use rstest::rstest;
use uuid::Uuid;

#[tokio::test]
async fn test_get_person_by_id() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("test_user@example.com", None)
        .await
        .expect("Failed to insert person");

    let result = ctx
        .storage
        .get_person_by_id(ctx.team_id, person.id)
        .await
        .expect("Failed to get person");

    assert!(result.is_some());
    let fetched = result.unwrap();
    assert_eq!(fetched.id, person.id);
    assert_eq!(fetched.uuid, person.uuid);
    assert_eq!(fetched.team_id, ctx.team_id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_person_by_id_not_found() {
    let ctx = TestContext::new().await;

    let result = ctx
        .storage
        .get_person_by_id(ctx.team_id, 999999999)
        .await
        .expect("Failed to query");

    assert!(result.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_person_by_uuid() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("uuid_test@example.com", None)
        .await
        .expect("Failed to insert person");

    let result = ctx
        .storage
        .get_person_by_uuid(ctx.team_id, person.uuid)
        .await
        .expect("Failed to get person");

    assert!(result.is_some());
    let fetched = result.unwrap();
    assert_eq!(fetched.id, person.id);
    assert_eq!(fetched.uuid, person.uuid);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_ids() {
    let ctx = TestContext::new().await;

    let person1 = ctx
        .insert_person("batch_user1@example.com", None)
        .await
        .expect("Failed to insert person 1");
    let person2 = ctx
        .insert_person("batch_user2@example.com", None)
        .await
        .expect("Failed to insert person 2");

    let result = ctx
        .storage
        .get_persons_by_ids(ctx.team_id, &[person1.id, person2.id, 999999999], true)
        .await
        .expect("Failed to get persons");

    assert_eq!(result.len(), 2);
    let ids: Vec<i64> = result.iter().map(|p| p.id).collect();
    assert!(ids.contains(&person1.id));
    assert!(ids.contains(&person2.id));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_person_by_distinct_id() {
    let ctx = TestContext::new().await;
    let distinct_id = "distinct_test_user@example.com";
    let person = ctx
        .insert_person(distinct_id, None)
        .await
        .expect("Failed to insert person");

    let result = ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, distinct_id)
        .await
        .expect("Failed to get person");

    assert!(result.is_some());
    let fetched = result.unwrap();
    assert_eq!(fetched.id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_distinct_ids_for_person() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("distinct_id_1", None)
        .await
        .expect("Failed to insert person");

    let result = ctx
        .storage
        .get_distinct_ids_for_person(ctx.team_id, person.id, ConsistencyLevel::Eventual, None)
        .await
        .expect("Failed to get distinct IDs");

    assert_eq!(result.len(), 1);
    assert_eq!(result[0].distinct_id, "distinct_id_1");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group() {
    let ctx = TestContext::new().await;

    let properties = serde_json::json!({"name": "Test Company", "industry": "tech"});
    let group = ctx
        .insert_group(0, "company_123", Some(properties.clone()))
        .await
        .expect("Failed to insert group");

    let result = ctx
        .storage
        .get_group(
            ctx.team_id,
            group.group_type_index,
            &group.group_key,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get group");

    assert!(result.is_some());
    let fetched = result.unwrap();
    assert_eq!(fetched.group_key, "company_123");
    assert_eq!(fetched.group_type_index, 0);
    let fetched_props: serde_json::Value =
        serde_json::from_str(fetched.group_properties.as_deref().unwrap()).unwrap();
    assert_eq!(fetched_props, properties);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_type_mappings() {
    let ctx = TestContext::new().await;

    ctx.insert_standard_group_type_mappings()
        .await
        .expect("Failed to insert group type mappings");

    let result = ctx
        .storage
        .get_group_type_mappings_by_team_id(ctx.team_id, ConsistencyLevel::Eventual)
        .await
        .expect("Failed to get group type mappings");

    assert_eq!(result.len(), 5);

    let group_types: Vec<&str> = result.iter().map(|m| m.group_type.as_str()).collect();
    assert!(group_types.contains(&"project"));
    assert!(group_types.contains(&"organization"));

    ctx.cleanup().await.ok();
}

#[rstest]
#[case::no_mappings(&[], None)]
#[case::one_mapping(&[("organization", 0)], Some(1))]
#[case::three_mappings(&[("organization", 0), ("project", 1), ("instance", 2)], Some(3))]
#[tokio::test]
async fn test_count_group_type_mappings(
    #[case] mappings: &[(&str, i32)],
    #[case] expected_count: Option<i64>,
) {
    let ctx = TestContext::new().await;

    for (group_type, index) in mappings {
        ctx.insert_group_type_mapping(group_type, *index)
            .await
            .expect("Failed to insert mapping");
    }

    let result = ctx
        .storage
        .count_group_type_mappings(ConsistencyLevel::Eventual)
        .await
        .expect("Failed to count group type mappings");

    let entry = result.iter().find(|(tid, _)| *tid == ctx.team_id);
    match expected_count {
        Some(count) => assert_eq!(entry, Some(&(ctx.team_id, count))),
        None => assert!(entry.is_none()),
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_count_group_type_mappings_multiple_teams() {
    let ctx1 = TestContext::new().await;
    let ctx2 = TestContext::new().await;

    ctx1.insert_group_type_mapping("org", 0)
        .await
        .expect("Failed to insert mapping");
    ctx2.insert_group_type_mapping("company", 0)
        .await
        .expect("Failed to insert mapping");
    ctx2.insert_group_type_mapping("project", 1)
        .await
        .expect("Failed to insert mapping");

    let result = ctx1
        .storage
        .count_group_type_mappings(ConsistencyLevel::Eventual)
        .await
        .expect("Failed to count group type mappings");

    let entry1 = result.iter().find(|(tid, _)| *tid == ctx1.team_id);
    let entry2 = result.iter().find(|(tid, _)| *tid == ctx2.team_id);
    assert_eq!(entry1, Some(&(ctx1.team_id, 1)));
    assert_eq!(entry2, Some(&(ctx2.team_id, 2)));

    ctx1.cleanup().await.ok();
    ctx2.cleanup().await.ok();
}

#[tokio::test]
async fn test_count_group_type_mappings_ordered_by_team_id() {
    let ctx = TestContext::new().await;

    ctx.insert_group_type_mapping("org", 0)
        .await
        .expect("Failed to insert mapping");

    let result = ctx
        .storage
        .count_group_type_mappings(ConsistencyLevel::Eventual)
        .await
        .expect("Failed to count group type mappings");

    let team_ids: Vec<i64> = result.iter().map(|(tid, _)| *tid).collect();
    let mut sorted = team_ids.clone();
    sorted.sort();
    assert_eq!(team_ids, sorted);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_check_cohort_membership() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("cohort_user@example.com", None)
        .await
        .expect("Failed to insert person");

    let cohort_id_1: i64 = 1001;
    let cohort_id_2: i64 = 1002;

    ctx.add_person_to_cohort(person.id, cohort_id_1)
        .await
        .expect("Failed to add person to cohort");

    let result = ctx
        .storage
        .check_cohort_membership(
            person.id,
            &[cohort_id_1, cohort_id_2],
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to check cohort membership");

    assert_eq!(result.len(), 2);
    let membership_1 = result.iter().find(|m| m.cohort_id == cohort_id_1).unwrap();
    let membership_2 = result.iter().find(|m| m.cohort_id == cohort_id_2).unwrap();
    assert!(membership_1.is_member);
    assert!(!membership_2.is_member);

    ctx.cleanup().await.ok();
}

async fn cohort_row_count(pool: &sqlx::PgPool, cohort_id: i64, person_ids: &[i64]) -> i64 {
    sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM posthog_cohortpeople WHERE cohort_id = $1 AND person_id = ANY($2)",
    )
    .bind(cohort_id)
    .bind(person_ids)
    .fetch_one(pool)
    .await
    .expect("count cohort rows")
}

// Idempotency across the concurrent chunked insert: a re-send of the full list (the retry /
// partial-failure recovery case) must skip already-present members and never duplicate rows.
#[rstest]
#[case::all_new(0, 120)]
#[case::retry_after_partial(70, 50)]
#[case::full_retry(120, 0)]
#[tokio::test]
async fn test_insert_cohort_members_idempotent(
    #[case] prior: usize,
    #[case] expected_inserted: i64,
) {
    let ctx = TestContext::new().await;
    let cohort_id: i64 = 7700;

    // 120 persons exercises the concurrent chunk path (bulk_chunk_size = 50 → 3 chunks).
    let mut person_ids = Vec::new();
    for i in 0..120 {
        let p = ctx
            .insert_person(&format!("cohort_insert_{i}@example.com"), None)
            .await
            .expect("insert person");
        person_ids.push(p.id);
    }

    // Seed `prior` members to simulate a prior partial commit that a retry re-sends in full.
    for &pid in &person_ids[..prior] {
        ctx.add_person_to_cohort(pid, cohort_id)
            .await
            .expect("seed prior members");
    }

    let inserted = ctx
        .storage
        .insert_cohort_members(cohort_id, &person_ids, Some(1))
        .await
        .expect("insert cohort members");

    // Only the not-yet-present members are inserted; NOT EXISTS skips the rest.
    assert_eq!(inserted, expected_inserted);
    // Exactly one row per person — no duplicates, regardless of prior state or chunk fan-out.
    assert_eq!(
        cohort_row_count(&ctx.pool, cohort_id, &person_ids).await,
        120
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_clears_cohort_memberships() {
    // posthog_cohortpeople has no FK to posthog_person (no DB cascade), so the
    // per-person DeletePersons path must clear memberships itself.
    let ctx = TestContext::new().await;
    let cohort_id: i64 = 8800;
    let person = ctx
        .insert_person("cohort_delete@example.com", None)
        .await
        .expect("insert person");
    ctx.add_person_to_cohort(person.id, cohort_id)
        .await
        .expect("add person to cohort");
    assert_eq!(
        cohort_row_count(&ctx.pool, cohort_id, &[person.id]).await,
        1
    );

    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[person.uuid])
        .await
        .expect("delete persons");

    assert_eq!(deleted, 1);
    assert_eq!(
        cohort_row_count(&ctx.pool, cohort_id, &[person.id]).await,
        0
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_batch_for_team_leaves_cohort_memberships() {
    // The team-teardown path clears cohortpeople separately, by cohort, before
    // deleting persons — so delete_persons_batch_for_team must NOT touch it.
    let ctx = TestContext::new().await;
    let cohort_id: i64 = 8801;
    let person = ctx
        .insert_person("cohort_batch_delete@example.com", None)
        .await
        .expect("insert person");
    ctx.add_person_to_cohort(person.id, cohort_id)
        .await
        .expect("add person to cohort");
    assert_eq!(
        cohort_row_count(&ctx.pool, cohort_id, &[person.id]).await,
        1
    );

    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 1000)
        .await
        .expect("delete persons batch for team");

    assert_eq!(deleted, 1);
    // Intentionally still present — the batch path leaves cohortpeople for the
    // by-cohort sweep in the team-teardown orchestration.
    assert_eq!(
        cohort_row_count(&ctx.pool, cohort_id, &[person.id]).await,
        1
    );

    // The person is gone, so the standard cleanup (which scopes by team's persons)
    // won't reach this now-orphaned row; remove it explicitly.
    sqlx::query("DELETE FROM posthog_cohortpeople WHERE cohort_id = $1 AND person_id = $2")
        .bind(cohort_id)
        .bind(person.id)
        .execute(&ctx.pool)
        .await
        .ok();
    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_person_properties() {
    let ctx = TestContext::new().await;

    let properties = serde_json::json!({
        "email": "props_test@example.com",
        "name": "Test User",
        "plan": "enterprise"
    });

    let person = ctx
        .insert_person("props_user", Some(properties.clone()))
        .await
        .expect("Failed to insert person");

    let result = ctx
        .storage
        .get_person_by_id(ctx.team_id, person.id)
        .await
        .expect("Failed to get person");

    assert!(result.is_some());
    let fetched = result.unwrap();
    let props: serde_json::Value =
        serde_json::from_str(fetched.properties.as_deref().unwrap()).unwrap();
    assert_eq!(props["email"], "props_test@example.com");
    assert_eq!(props["plan"], "enterprise");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_uuids() {
    let ctx = TestContext::new().await;

    let person1 = ctx
        .insert_person("uuid_batch_1@example.com", None)
        .await
        .expect("Failed to insert person 1");
    let person2 = ctx
        .insert_person("uuid_batch_2@example.com", None)
        .await
        .expect("Failed to insert person 2");

    let nonexistent_uuid = uuid::Uuid::now_v7();

    let result = ctx
        .storage
        .get_persons_by_uuids(
            ctx.team_id,
            &[person1.uuid, person2.uuid, nonexistent_uuid],
            true,
        )
        .await
        .expect("Failed to get persons by uuids");

    assert_eq!(result.len(), 2);
    let uuids: Vec<uuid::Uuid> = result.iter().map(|p| p.uuid).collect();
    assert!(uuids.contains(&person1.uuid));
    assert!(uuids.contains(&person2.uuid));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_distinct_ids_for_persons() {
    let ctx = TestContext::new().await;

    let person1 = ctx
        .insert_person("person1_did", None)
        .await
        .expect("Failed to insert person 1");
    let person2 = ctx
        .insert_person("person2_did", None)
        .await
        .expect("Failed to insert person 2");

    // Add additional distinct IDs to person1
    ctx.add_distinct_id_to_person(person1.id, "person1_did_2")
        .await
        .expect("Failed to add distinct id");

    let result = ctx
        .storage
        .get_distinct_ids_for_persons(
            ctx.team_id,
            &[person1.id, person2.id],
            ConsistencyLevel::Eventual,
            None,
        )
        .await
        .expect("Failed to get distinct ids for persons");

    assert_eq!(result.len(), 3);

    let person1_dids: Vec<&str> = result
        .iter()
        .filter(|m| m.person_id == person1.id)
        .map(|m| m.distinct_id.as_str())
        .collect();
    assert_eq!(person1_dids.len(), 2);
    assert!(person1_dids.contains(&"person1_did"));
    assert!(person1_dids.contains(&"person1_did_2"));

    let person2_dids: Vec<&str> = result
        .iter()
        .filter(|m| m.person_id == person2.id)
        .map(|m| m.distinct_id.as_str())
        .collect();
    assert_eq!(person2_dids.len(), 1);
    assert!(person2_dids.contains(&"person2_did"));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_groups_batch() {
    let ctx = TestContext::new().await;

    ctx.insert_group(0, "company_a", None)
        .await
        .expect("Failed to insert group");
    ctx.insert_group(1, "org_b", None)
        .await
        .expect("Failed to insert group");

    let keys = vec![
        GroupKey {
            team_id: ctx.team_id,
            group_type_index: 0,
            group_key: "company_a".to_string(),
        },
        GroupKey {
            team_id: ctx.team_id,
            group_type_index: 1,
            group_key: "org_b".to_string(),
        },
        GroupKey {
            team_id: ctx.team_id,
            group_type_index: 2,
            group_key: "nonexistent".to_string(),
        },
    ];

    let result = ctx
        .storage
        .get_groups_batch(&keys, ConsistencyLevel::Eventual, true)
        .await
        .expect("Failed to get groups batch");

    assert_eq!(result.len(), 2);
    let group_keys: Vec<&str> = result.iter().map(|(k, _)| k.group_key.as_str()).collect();
    assert!(group_keys.contains(&"company_a"));
    assert!(group_keys.contains(&"org_b"));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_type_mappings_by_team_ids() {
    let ctx = TestContext::new().await;

    ctx.insert_group_type_mapping("company", 0)
        .await
        .expect("Failed to insert mapping");
    ctx.insert_group_type_mapping("project", 1)
        .await
        .expect("Failed to insert mapping");

    let result = ctx
        .storage
        .get_group_type_mappings_by_team_ids(&[ctx.team_id], ConsistencyLevel::Eventual)
        .await
        .expect("Failed to get mappings by team ids");

    assert_eq!(result.len(), 2);
    let group_types: Vec<&str> = result.iter().map(|m| m.group_type.as_str()).collect();
    assert!(group_types.contains(&"company"));
    assert!(group_types.contains(&"project"));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_id() {
    let ctx = TestContext::new().await;

    // Note: insert_group_type_mapping uses team_id as project_id
    ctx.insert_group_type_mapping("workspace", 0)
        .await
        .expect("Failed to insert mapping");
    ctx.insert_group_type_mapping("department", 1)
        .await
        .expect("Failed to insert mapping");

    let result = ctx
        .storage
        .get_group_type_mappings_by_project_id(ctx.team_id, ConsistencyLevel::Eventual)
        .await
        .expect("Failed to get mappings by project id");

    assert_eq!(result.len(), 2);
    let group_types: Vec<&str> = result.iter().map(|m| m.group_type.as_str()).collect();
    assert!(group_types.contains(&"workspace"));
    assert!(group_types.contains(&"department"));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_group_type_mappings_by_project_ids() {
    let ctx = TestContext::new().await;

    ctx.insert_group_type_mapping("team", 0)
        .await
        .expect("Failed to insert mapping");

    let result = ctx
        .storage
        .get_group_type_mappings_by_project_ids(&[ctx.team_id], ConsistencyLevel::Eventual)
        .await
        .expect("Failed to get mappings by project ids");

    assert_eq!(result.len(), 1);
    assert_eq!(result[0].group_type, "team");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_hash_key_override_context_with_overrides() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("hash_override_user", None)
        .await
        .expect("Failed to insert person");

    ctx.insert_hash_key_override(person.id, "beta-feature", "override_hash_1")
        .await
        .expect("Failed to insert hash key override");
    ctx.insert_hash_key_override(person.id, "new-ui", "override_hash_2")
        .await
        .expect("Failed to insert hash key override");

    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &["hash_override_user".to_string(), "nonexistent".to_string()],
            false,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context");

    assert_eq!(result.len(), 1);
    let person_result = &result[0];
    assert_eq!(person_result.person_id, person.id);
    assert_eq!(person_result.distinct_id, "hash_override_user");
    assert_eq!(person_result.overrides.len(), 2);
    assert_eq!(person_result.existing_feature_flag_keys.len(), 2);

    let override_keys: Vec<&str> = person_result
        .overrides
        .iter()
        .map(|o| o.feature_flag_key.as_str())
        .collect();
    assert!(override_keys.contains(&"beta-feature"));
    assert!(override_keys.contains(&"new-ui"));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_hash_key_override_context_no_overrides() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("user_no_overrides", None)
        .await
        .expect("Failed to insert person");

    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &["user_no_overrides".to_string()],
            false,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context");

    assert_eq!(result.len(), 1);
    let person_result = &result[0];
    assert_eq!(person_result.person_id, person.id);
    assert!(person_result.overrides.is_empty());
    assert!(person_result.existing_feature_flag_keys.is_empty());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_hash_key_override_context_with_check_person_exists() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("existing_person_user", None)
        .await
        .expect("Failed to insert person");

    ctx.insert_hash_key_override(person.id, "feature-x", "hash_x")
        .await
        .expect("Failed to insert override");
    ctx.insert_hash_key_override(person.id, "feature-y", "hash_y")
        .await
        .expect("Failed to insert override");

    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &["existing_person_user".to_string()],
            true,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context with person check");

    assert_eq!(result.len(), 1);
    let person_result = &result[0];
    assert_eq!(person_result.person_id, person.id);
    assert_eq!(person_result.existing_feature_flag_keys.len(), 2);
    assert!(person_result
        .existing_feature_flag_keys
        .contains(&"feature-x".to_string()));
    assert!(person_result
        .existing_feature_flag_keys
        .contains(&"feature-y".to_string()));

    ctx.cleanup().await.ok();
}

// ============================================================
// Upsert hash key overrides tests
// ============================================================

#[tokio::test]
async fn test_upsert_hash_key_overrides_single_override() {
    let ctx = TestContext::new().await;

    ctx.insert_person("upsert_single_user", None)
        .await
        .expect("Failed to insert person");

    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(
            ctx.team_id,
            &["upsert_single_user".to_string()],
            &["test-flag".to_string()],
            "my_hash_key",
        )
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(inserted_count, 1);

    // Verify the override was inserted with the correct hash_key
    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &["upsert_single_user".to_string()],
            false,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context");

    assert_eq!(result.len(), 1);
    assert_eq!(result[0].overrides.len(), 1);
    assert_eq!(result[0].overrides[0].feature_flag_key, "test-flag");
    assert_eq!(result[0].overrides[0].hash_key, "my_hash_key");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_multiple_distinct_ids_and_flags() {
    let ctx = TestContext::new().await;

    let person1 = ctx
        .insert_person("upsert_multi_user1", None)
        .await
        .expect("Failed to insert person 1");
    let person2 = ctx
        .insert_person("upsert_multi_user2", None)
        .await
        .expect("Failed to insert person 2");

    // Two distinct_ids × two flag keys = 4 overrides
    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(
            ctx.team_id,
            &[
                "upsert_multi_user1".to_string(),
                "upsert_multi_user2".to_string(),
            ],
            &["flag-a".to_string(), "flag-b".to_string()],
            "shared_anon_id",
        )
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(inserted_count, 4);

    // Verify all overrides have the same hash_key
    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &[
                "upsert_multi_user1".to_string(),
                "upsert_multi_user2".to_string(),
            ],
            false,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context");

    assert_eq!(result.len(), 2);

    for person_result in &result {
        assert_eq!(person_result.overrides.len(), 2);
        for override_entry in &person_result.overrides {
            assert_eq!(override_entry.hash_key, "shared_anon_id");
        }
    }

    // Each person should have 2 overrides (one per flag key)
    let person1_result = result.iter().find(|r| r.person_id == person1.id).unwrap();
    assert_eq!(person1_result.overrides.len(), 2);

    let person2_result = result.iter().find(|r| r.person_id == person2.id).unwrap();
    assert_eq!(person2_result.overrides.len(), 2);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_empty_distinct_ids_returns_zero() {
    let ctx = TestContext::new().await;

    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(
            ctx.team_id,
            &[],
            &["some-flag".to_string()],
            "unused_hash_key",
        )
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(inserted_count, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_empty_flag_keys_returns_zero() {
    let ctx = TestContext::new().await;

    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(
            ctx.team_id,
            &["some-distinct-id".to_string()],
            &[],
            "unused_hash_key",
        )
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(inserted_count, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_on_conflict_do_nothing() {
    let ctx = TestContext::new().await;

    ctx.insert_person("upsert_conflict_user", None)
        .await
        .expect("Failed to insert person");

    let distinct_ids = ["upsert_conflict_user".to_string()];
    let flag_keys = ["conflict-flag".to_string()];

    // First insert
    let first_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &distinct_ids, &flag_keys, "first_hash")
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(first_count, 1);

    // Second insert with same distinct_id and feature_flag_key should do nothing
    // (ON CONFLICT DO NOTHING)
    let second_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &distinct_ids, &flag_keys, "second_hash")
        .await
        .expect("Failed to upsert hash key overrides");

    // No new rows inserted due to conflict
    assert_eq!(second_count, 0);

    // Verify the original hash_key is preserved (not updated)
    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &["upsert_conflict_user".to_string()],
            false,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context");

    assert_eq!(result.len(), 1);
    assert_eq!(result[0].overrides.len(), 1);
    assert_eq!(result[0].overrides[0].hash_key, "first_hash");

    ctx.cleanup().await.ok();
}

// ============================================================
// Delete hash key overrides by teams tests
// ============================================================

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_single_team() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("delete_test_user", None)
        .await
        .expect("Failed to insert person");

    // Insert some overrides
    ctx.insert_hash_key_override(person.id, "flag-1", "hash_1")
        .await
        .unwrap();
    ctx.insert_hash_key_override(person.id, "flag-2", "hash_2")
        .await
        .unwrap();

    // Delete by team
    let deleted_count = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[ctx.team_id], 1000)
        .await
        .expect("Failed to delete hash key overrides");

    assert_eq!(deleted_count, 2);

    // Verify they're gone
    let result = ctx
        .storage
        .get_hash_key_override_context(
            ctx.team_id,
            &["delete_test_user".to_string()],
            false,
            ConsistencyLevel::Eventual,
        )
        .await
        .expect("Failed to get hash key override context");

    assert_eq!(result.len(), 1);
    assert!(result[0].overrides.is_empty());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_empty_returns_zero() {
    let ctx = TestContext::new().await;

    let deleted_count = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[], 1000)
        .await
        .expect("Failed to delete hash key overrides");

    assert_eq!(deleted_count, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_nonexistent_team() {
    let ctx = TestContext::new().await;

    let deleted_count = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[999999999], 1000)
        .await
        .expect("Failed to delete hash key overrides");

    assert_eq!(deleted_count, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_bounded_by_batch_size() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("bounded_del_user", None)
        .await
        .expect("Failed to insert person");
    for i in 0..5 {
        ctx.insert_hash_key_override(person.id, &format!("flag-{i}"), "hash")
            .await
            .unwrap();
    }

    // batch_size=2 deletes 2 of the 5, then the loop drains the rest.
    let deleted = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[ctx.team_id], 2)
        .await
        .expect("Failed to delete hash key overrides");
    assert_eq!(deleted, 2);

    let deleted = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[ctx.team_id], 2)
        .await
        .expect("Failed to delete hash key overrides");
    assert_eq!(deleted, 2);

    let deleted = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[ctx.team_id], 2)
        .await
        .expect("Failed to delete hash key overrides");
    assert_eq!(deleted, 1);

    let deleted = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[ctx.team_id], 2)
        .await
        .expect("Failed to delete hash key overrides");
    assert_eq!(deleted, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_hash_key_overrides_by_teams_zero_batch_size() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("zero_batch_user", None)
        .await
        .expect("Failed to insert person");
    ctx.insert_hash_key_override(person.id, "flag-1", "hash")
        .await
        .unwrap();

    let deleted = ctx
        .storage
        .delete_hash_key_overrides_by_teams(&[ctx.team_id], 0)
        .await
        .expect("Failed to delete hash key overrides");
    assert_eq!(deleted, 0);

    ctx.cleanup().await.ok();
}

// ============================================================
// Delete persons batch for team tests
// ============================================================

#[tokio::test]
async fn test_delete_persons_batch_for_team() {
    let ctx = TestContext::new().await;

    let p1 = ctx.insert_person("batch_del_1", None).await.unwrap();
    let p2 = ctx.insert_person("batch_del_2", None).await.unwrap();
    let p3 = ctx.insert_person("batch_del_3", None).await.unwrap();

    // Delete batch_size=2 — should delete 2 of the 3 persons
    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 2)
        .await
        .expect("Failed to delete persons batch");

    assert_eq!(deleted, 2);

    // Second call — should delete the remaining 1
    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 2)
        .await
        .expect("Failed to delete persons batch");

    assert_eq!(deleted, 1);

    // Third call — nothing left
    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 2)
        .await
        .expect("Failed to delete persons batch");

    assert_eq!(deleted, 0);

    // Verify all persons are gone
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p1.id)
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p2.id)
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p3.id)
        .await
        .unwrap()
        .is_none());

    // Verify distinct IDs are gone too
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "batch_del_1")
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "batch_del_2")
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "batch_del_3")
        .await
        .unwrap()
        .is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_batch_for_team_empty() {
    let ctx = TestContext::new().await;

    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 1000)
        .await
        .expect("Failed to delete persons batch");

    assert_eq!(deleted, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_batch_for_team_cross_team_isolation() {
    let ctx = TestContext::new().await;

    let _p1 = ctx.insert_person("team_a_person", None).await.unwrap();

    // Insert a person in a different team directly via SQL
    let other_team_id = ctx.team_id + 1;
    let other_person_id: i64 = rand::thread_rng().gen_range(1_000_000..100_000_000);
    sqlx::query(
        r#"INSERT INTO posthog_person
        (id, uuid, team_id, properties, properties_last_updated_at,
         properties_last_operation, created_at, version, is_identified, is_user_id)
        VALUES ($1, $2, $3, '{}', '{}', '{}', NOW(), 0, false, NULL)
        ON CONFLICT DO NOTHING"#,
    )
    .bind(other_person_id)
    .bind(uuid::Uuid::now_v7())
    .bind(other_team_id)
    .execute(&ctx.pool)
    .await
    .unwrap();

    // Delete only ctx.team_id persons
    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 1000)
        .await
        .expect("Failed to delete persons batch");

    assert_eq!(deleted, 1);

    // Other team's person should still exist
    let other_person = ctx
        .storage
        .get_person_by_id(other_team_id, other_person_id)
        .await
        .unwrap();
    assert!(other_person.is_some());

    // Cleanup both teams
    sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
        .bind(other_team_id)
        .execute(&ctx.pool)
        .await
        .ok();
    ctx.cleanup().await.ok();
}

// ============================================================
// Delete personless distinct IDs batch for team tests
// ============================================================

#[tokio::test]
async fn test_delete_personless_distinct_ids_batch_for_team() {
    let ctx = TestContext::new().await;

    ctx.insert_personless_distinct_id("personless_1")
        .await
        .unwrap();
    ctx.insert_personless_distinct_id("personless_2")
        .await
        .unwrap();
    ctx.insert_personless_distinct_id("personless_3")
        .await
        .unwrap();

    // batch_size=2 deletes 2 of the 3 rows.
    let deleted = ctx
        .storage
        .delete_personless_distinct_ids_batch_for_team(ctx.team_id, 2)
        .await
        .expect("Failed to delete personless distinct IDs batch");
    assert_eq!(deleted, 2);

    // The remaining row is deleted next.
    let deleted = ctx
        .storage
        .delete_personless_distinct_ids_batch_for_team(ctx.team_id, 2)
        .await
        .expect("Failed to delete personless distinct IDs batch");
    assert_eq!(deleted, 1);

    // Nothing left.
    let deleted = ctx
        .storage
        .delete_personless_distinct_ids_batch_for_team(ctx.team_id, 2)
        .await
        .expect("Failed to delete personless distinct IDs batch");
    assert_eq!(deleted, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_personless_distinct_ids_batch_for_team_empty() {
    let ctx = TestContext::new().await;

    let deleted = ctx
        .storage
        .delete_personless_distinct_ids_batch_for_team(ctx.team_id, 1000)
        .await
        .expect("Failed to delete personless distinct IDs batch");
    assert_eq!(deleted, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_personless_distinct_ids_batch_for_team_cross_team_isolation() {
    let ctx = TestContext::new().await;

    ctx.insert_personless_distinct_id("team_a_personless")
        .await
        .unwrap();

    // Insert a personless distinct ID for a different team directly.
    let other_team_id = ctx.team_id + 1;
    sqlx::query(
        r#"INSERT INTO posthog_personlessdistinctid
        (distinct_id, team_id, is_merged, created_at)
        VALUES ($1, $2, false, NOW())
        ON CONFLICT DO NOTHING"#,
    )
    .bind("team_b_personless")
    .bind(other_team_id)
    .execute(&ctx.pool)
    .await
    .unwrap();

    let deleted = ctx
        .storage
        .delete_personless_distinct_ids_batch_for_team(ctx.team_id, 1000)
        .await
        .expect("Failed to delete personless distinct IDs batch");
    assert_eq!(deleted, 1);

    // The other team's row should remain.
    let remaining: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM posthog_personlessdistinctid WHERE team_id = $1")
            .bind(other_team_id)
            .fetch_one(&ctx.pool)
            .await
            .unwrap();
    assert_eq!(remaining, 1);

    sqlx::query("DELETE FROM posthog_personlessdistinctid WHERE team_id = $1")
        .bind(other_team_id)
        .execute(&ctx.pool)
        .await
        .ok();
    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_personless_distinct_ids_batch_for_team_zero_batch_size() {
    let ctx = TestContext::new().await;

    ctx.insert_personless_distinct_id("personless_zero")
        .await
        .unwrap();

    // A non-positive batch size deletes nothing.
    let deleted = ctx
        .storage
        .delete_personless_distinct_ids_batch_for_team(ctx.team_id, 0)
        .await
        .expect("Failed to delete personless distinct IDs batch");
    assert_eq!(deleted, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_batch_for_team_rolls_back_on_partial_failure() {
    let ctx = TestContext::new().await;

    let p1 = ctx.insert_person("rollback_user_1", None).await.unwrap();
    let p2 = ctx.insert_person("rollback_user_2", None).await.unwrap();

    // Create a table with a RESTRICT FK to posthog_person. When
    // delete_persons_batch_for_team reaches step 3 (DELETE FROM posthog_person),
    // this FK will cause the delete to fail — after step 2 already deleted the
    // distinct_ids within the same transaction.
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS _test_person_fk_block (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL,
            person_id BIGINT NOT NULL,
            FOREIGN KEY (team_id, person_id)
                REFERENCES posthog_person(team_id, id) ON DELETE RESTRICT
        )",
    )
    .execute(&ctx.pool)
    .await
    .expect("Failed to create blocking FK table");

    // Block deletion of p1 — both p1 and p2 are selected in the same batch,
    // so the entire transaction should fail and roll back
    sqlx::query("INSERT INTO _test_person_fk_block (team_id, person_id) VALUES ($1, $2)")
        .bind(ctx.team_id as i32)
        .bind(p1.id)
        .execute(&ctx.pool)
        .await
        .expect("Failed to insert blocking reference");

    let result = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 100)
        .await;

    assert!(result.is_err());

    // Both persons should still exist — transaction rolled back
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p1.id)
        .await
        .unwrap()
        .is_some());
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p2.id)
        .await
        .unwrap()
        .is_some());

    // Distinct IDs should also still exist — proves the step 2 deletes were rolled back
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "rollback_user_1")
        .await
        .unwrap()
        .is_some());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "rollback_user_2")
        .await
        .unwrap()
        .is_some());

    // Cleanup
    sqlx::query("DELETE FROM _test_person_fk_block WHERE team_id = $1")
        .bind(ctx.team_id as i32)
        .execute(&ctx.pool)
        .await
        .ok();
    ctx.cleanup().await.ok();
}

// ============================================================
// Delete persons by UUID tests
// ============================================================

#[tokio::test]
async fn test_delete_persons_small_batch() {
    let ctx = TestContext::new().await;

    let p1 = ctx.insert_person("del_uuid_1", None).await.unwrap();
    let p2 = ctx.insert_person("del_uuid_2", None).await.unwrap();
    let p3 = ctx.insert_person("del_uuid_3", None).await.unwrap();

    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[p1.uuid, p2.uuid])
        .await
        .expect("Failed to delete persons");

    assert_eq!(deleted, 2);

    // p1 and p2 gone, p3 remains
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p1.id)
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p2.id)
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, p3.id)
        .await
        .unwrap()
        .is_some());

    // Distinct IDs for deleted persons should also be gone
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "del_uuid_1")
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "del_uuid_2")
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "del_uuid_3")
        .await
        .unwrap()
        .is_some());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_empty_uuids() {
    let ctx = TestContext::new().await;
    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[])
        .await
        .expect("Failed to delete persons");
    assert_eq!(deleted, 0);
    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_nonexistent_uuids() {
    let ctx = TestContext::new().await;
    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[Uuid::now_v7(), Uuid::now_v7()])
        .await
        .expect("Failed to delete persons");
    assert_eq!(deleted, 0);
    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_with_multiple_distinct_ids() {
    let ctx = TestContext::new().await;

    let p1 = ctx.insert_person("multi_did_1", None).await.unwrap();
    ctx.add_distinct_id_to_person(p1.id, "multi_did_1b")
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(p1.id, "multi_did_1c")
        .await
        .unwrap();

    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[p1.uuid])
        .await
        .expect("Failed to delete persons");

    assert_eq!(deleted, 1);

    // All three distinct IDs should be gone
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "multi_did_1")
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "multi_did_1b")
        .await
        .unwrap()
        .is_none());
    assert!(ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "multi_did_1c")
        .await
        .unwrap()
        .is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_large_batch_triggers_parallel() {
    let ctx = TestContext::new().await;

    // Create 150 persons — with chunk_size=50, this triggers 3 parallel chunks
    let mut uuids = Vec::new();
    for i in 0..150 {
        let p = ctx
            .insert_person(&format!("parallel_del_{i}"), None)
            .await
            .unwrap();
        // Give some persons extra distinct_ids to exercise bin-packing
        if i % 10 == 0 {
            for j in 0..5 {
                ctx.add_distinct_id_to_person(p.id, &format!("parallel_del_{i}_extra_{j}"))
                    .await
                    .unwrap();
            }
        }
        uuids.push(p.uuid);
    }

    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &uuids)
        .await
        .expect("Failed to delete persons");

    assert_eq!(deleted, 150);

    // Verify all are gone
    for i in 0..150 {
        assert!(
            ctx.storage
                .get_person_by_distinct_id(ctx.team_id, &format!("parallel_del_{i}"))
                .await
                .unwrap()
                .is_none(),
            "Person {i} should have been deleted"
        );
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_batch_for_team_large_batch() {
    let ctx = TestContext::new().await;

    // Create 150 persons. batch_size=100 selects 100, chunk_size=50 means
    // two parallel chunks per call — exercises the parallel delete path.
    for i in 0..150 {
        let p = ctx
            .insert_person(&format!("batch_team_del_{i}"), None)
            .await
            .unwrap();
        if i % 10 == 0 {
            for j in 0..5 {
                ctx.add_distinct_id_to_person(p.id, &format!("batch_team_del_{i}_extra_{j}"))
                    .await
                    .unwrap();
            }
        }
    }

    // First call: selects and deletes 100 of 150
    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 100)
        .await
        .expect("Failed to delete persons batch");
    assert_eq!(deleted, 100);

    // Second call: deletes the remaining 50
    let deleted = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 100)
        .await
        .expect("Failed to delete persons batch");
    assert_eq!(deleted, 50);

    // Third call: nothing left
    let remaining = ctx
        .storage
        .delete_persons_batch_for_team(ctx.team_id, 100)
        .await
        .expect("Failed to delete persons batch");
    assert_eq!(remaining, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_idempotent() {
    let ctx = TestContext::new().await;

    let p1 = ctx.insert_person("idem_1", None).await.unwrap();
    let p2 = ctx.insert_person("idem_2", None).await.unwrap();

    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[p1.uuid, p2.uuid])
        .await
        .expect("Failed to delete persons");
    assert_eq!(deleted, 2);

    // Second call with the same UUIDs should be a no-op
    let deleted_again = ctx
        .storage
        .delete_persons(ctx.team_id, &[p1.uuid, p2.uuid])
        .await
        .expect("Failed to delete persons");
    assert_eq!(deleted_again, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_cross_team_isolation() {
    let ctx = TestContext::new().await;

    let p1 = ctx.insert_person("cross_team_1", None).await.unwrap();

    // Create a person in a different team
    let other_team_id = ctx.team_id + 1;
    let other_person_id: i64 =
        rand::Rng::gen_range(&mut rand::thread_rng(), 1_000_000..100_000_000);
    let other_uuid = Uuid::now_v7();
    sqlx::query(
        "INSERT INTO posthog_person \
         (id, uuid, team_id, properties, properties_last_updated_at, \
          properties_last_operation, created_at, version, is_identified, is_user_id) \
         VALUES ($1, $2, $3, '{}', '{}', '{}', NOW(), 0, false, NULL) \
         ON CONFLICT DO NOTHING",
    )
    .bind(other_person_id)
    .bind(other_uuid)
    .bind(other_team_id as i32)
    .execute(&ctx.pool)
    .await
    .unwrap();

    // Delete from ctx.team_id — should not touch the other team's person
    let deleted = ctx
        .storage
        .delete_persons(ctx.team_id, &[p1.uuid, other_uuid])
        .await
        .expect("Failed to delete persons");
    assert_eq!(deleted, 1);

    // Other team's person should still exist
    let still_exists = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM posthog_person WHERE team_id = $1 AND uuid = $2",
    )
    .bind(other_team_id as i32)
    .bind(other_uuid)
    .fetch_one(&ctx.pool)
    .await
    .unwrap();
    assert_eq!(still_exists, 1);

    // Cleanup
    sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
        .bind(other_team_id as i32)
        .execute(&ctx.pool)
        .await
        .ok();
    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_delete_persons_partial_failure_returns_error() {
    let ctx = TestContext::new().await;

    // Create a person and block its deletion with a RESTRICT FK.
    let blocked = ctx.insert_person("blocked_person", None).await.unwrap();
    let normal = ctx.insert_person("normal_person", None).await.unwrap();

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS _test_person_fk_block (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL,
            person_id BIGINT NOT NULL,
            FOREIGN KEY (team_id, person_id)
                REFERENCES posthog_person(team_id, id) ON DELETE RESTRICT
        )",
    )
    .execute(&ctx.pool)
    .await
    .expect("Failed to create blocking FK table");

    sqlx::query("INSERT INTO _test_person_fk_block (team_id, person_id) VALUES ($1, $2)")
        .bind(ctx.team_id as i32)
        .bind(blocked.id)
        .execute(&ctx.pool)
        .await
        .expect("Failed to insert blocking reference");

    // The call should return an error because the FK blocks deletion
    let result = ctx
        .storage
        .delete_persons(ctx.team_id, &[blocked.uuid, normal.uuid])
        .await;
    assert!(result.is_err(), "Expected error due to blocked FK");

    // The blocked person should still exist
    assert!(ctx
        .storage
        .get_person_by_id(ctx.team_id, blocked.id)
        .await
        .unwrap()
        .is_some());

    // Cleanup
    sqlx::query("DELETE FROM _test_person_fk_block WHERE team_id = $1")
        .bind(ctx.team_id as i32)
        .execute(&ctx.pool)
        .await
        .ok();
    ctx.cleanup().await.ok();
}

// ============================================================
// Bulk read chunking tests — exercise the parallel path
// (test chunk_size=50, so >50 items triggers chunking)
// ============================================================

#[tokio::test]
async fn test_get_persons_by_ids_chunked() {
    let ctx = TestContext::new().await;

    let mut ids = Vec::new();
    for i in 0..80 {
        let p = ctx
            .insert_person(&format!("bulk_id_{i}"), None)
            .await
            .unwrap();
        ids.push(p.id);
    }

    let result = ctx
        .storage
        .get_persons_by_ids(ctx.team_id, &ids, true)
        .await
        .expect("Failed to get persons by ids");

    assert_eq!(result.len(), 80);
    let returned_ids: Vec<i64> = result.iter().map(|p| p.id).collect();
    for id in &ids {
        assert!(returned_ids.contains(id), "Missing person id {id}");
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_uuids_chunked() {
    let ctx = TestContext::new().await;

    let mut uuids = Vec::new();
    for i in 0..80 {
        let p = ctx
            .insert_person(&format!("bulk_uuid_{i}"), None)
            .await
            .unwrap();
        uuids.push(p.uuid);
    }

    let result = ctx
        .storage
        .get_persons_by_uuids(ctx.team_id, &uuids, true)
        .await
        .expect("Failed to get persons by uuids");

    assert_eq!(result.len(), 80);
    let returned_uuids: Vec<Uuid> = result.iter().map(|p| p.uuid).collect();
    for uuid in &uuids {
        assert!(returned_uuids.contains(uuid), "Missing person uuid {uuid}");
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team_chunked() {
    let ctx = TestContext::new().await;

    let mut distinct_ids = Vec::new();
    for i in 0..80 {
        let did = format!("bulk_did_{i}");
        ctx.insert_person(&did, None).await.unwrap();
        distinct_ids.push(did);
    }

    let result = ctx
        .storage
        .get_persons_by_distinct_ids_in_team(ctx.team_id, &distinct_ids, true)
        .await
        .expect("Failed to get persons by distinct ids");

    assert_eq!(result.len(), 80);
    let mut found_count = 0;
    for (did, person) in &result {
        assert!(
            distinct_ids.contains(did),
            "Unexpected distinct_id {did} in result"
        );
        if person.is_some() {
            found_count += 1;
        }
    }
    assert_eq!(found_count, 80, "All persons should be found");

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team_chunked_preserves_missing() {
    let ctx = TestContext::new().await;

    // Create 60 persons but request 80 distinct_ids (20 nonexistent)
    let mut distinct_ids = Vec::new();
    for i in 0..60 {
        let did = format!("partial_did_{i}");
        ctx.insert_person(&did, None).await.unwrap();
        distinct_ids.push(did);
    }
    for i in 60..80 {
        distinct_ids.push(format!("missing_did_{i}"));
    }

    let result = ctx
        .storage
        .get_persons_by_distinct_ids_in_team(ctx.team_id, &distinct_ids, true)
        .await
        .expect("Failed to get persons");

    assert_eq!(result.len(), 80);
    let found: Vec<_> = result.iter().filter(|(_, p)| p.is_some()).collect();
    let missing: Vec<_> = result.iter().filter(|(_, p)| p.is_none()).collect();
    assert_eq!(found.len(), 60);
    assert_eq!(missing.len(), 20);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team_handles_duplicates() {
    let ctx = TestContext::new().await;

    ctx.insert_person("dup_did_a", None).await.unwrap();
    ctx.insert_person("dup_did_b", None).await.unwrap();

    // A repeated distinct_id, plus a repeated non-existent one. The query
    // deduplicates these, while the response mirrors the input list: each id
    // resolves on its first occurrence and is None on any repeat.
    let distinct_ids = vec![
        "dup_did_a".to_string(),
        "dup_did_a".to_string(),
        "dup_did_b".to_string(),
        "missing_dup".to_string(),
        "missing_dup".to_string(),
    ];

    let result = ctx
        .storage
        .get_persons_by_distinct_ids_in_team(ctx.team_id, &distinct_ids, true)
        .await
        .expect("Failed to get persons");

    assert_eq!(
        result
            .iter()
            .map(|(did, _)| did.clone())
            .collect::<Vec<_>>(),
        distinct_ids
    );
    assert!(result[0].1.is_some());
    assert!(result[1].1.is_none());
    assert!(result[2].1.is_some());
    assert!(result[3].1.is_none());
    assert!(result[4].1.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_distinct_ids_for_persons_chunked() {
    let ctx = TestContext::new().await;

    let mut person_ids = Vec::new();
    for i in 0..80 {
        let p = ctx
            .insert_person(&format!("did_bulk_{i}"), None)
            .await
            .unwrap();
        // Add a second distinct_id to some persons
        if i % 5 == 0 {
            ctx.add_distinct_id_to_person(p.id, &format!("did_bulk_{i}_extra"))
                .await
                .unwrap();
        }
        person_ids.push(p.id);
    }

    let result = ctx
        .storage
        .get_distinct_ids_for_persons(ctx.team_id, &person_ids, ConsistencyLevel::Eventual, None)
        .await
        .expect("Failed to get distinct ids for persons");

    // 80 persons, 16 with 2 distinct_ids each = 96 total
    assert_eq!(result.len(), 96);

    // Every person_id should appear at least once
    let returned_person_ids: std::collections::HashSet<i64> =
        result.iter().map(|d| d.person_id).collect();
    for pid in &person_ids {
        assert!(returned_person_ids.contains(pid), "Missing person_id {pid}");
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_distinct_ids_for_persons_chunked_with_limit() {
    let ctx = TestContext::new().await;

    let mut person_ids = Vec::new();
    for i in 0..80 {
        let p = ctx
            .insert_person(&format!("did_lim_{i}"), None)
            .await
            .unwrap();
        ctx.add_distinct_id_to_person(p.id, &format!("did_lim_{i}_b"))
            .await
            .unwrap();
        ctx.add_distinct_id_to_person(p.id, &format!("did_lim_{i}_c"))
            .await
            .unwrap();
        person_ids.push(p.id);
    }

    // Each person has 3 distinct_ids, limit to 1 per person
    let result = ctx
        .storage
        .get_distinct_ids_for_persons(
            ctx.team_id,
            &person_ids,
            ConsistencyLevel::Eventual,
            Some(1),
        )
        .await
        .expect("Failed to get distinct ids with limit");

    // Should get exactly 80 rows (1 per person)
    assert_eq!(result.len(), 80);

    ctx.cleanup().await.ok();
}

// ============================================================
// include_properties=false storage tests
// ============================================================

#[tokio::test]
async fn test_get_persons_by_ids_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"email": "test@example.com"});
    let person = ctx
        .insert_person("props_test_1", Some(props))
        .await
        .expect("Failed to insert person");

    let with_props = ctx
        .storage
        .get_persons_by_ids(ctx.team_id, &[person.id], true)
        .await
        .expect("Failed to get persons with props");
    assert_eq!(with_props.len(), 1);
    assert!(with_props[0].properties.is_some());

    let without_props = ctx
        .storage
        .get_persons_by_ids(ctx.team_id, &[person.id], false)
        .await
        .expect("Failed to get persons without props");
    assert_eq!(without_props.len(), 1);
    assert_eq!(without_props[0].id, person.id);
    assert!(without_props[0].properties.is_none());
    assert!(without_props[0].properties_last_updated_at.is_none());
    assert!(without_props[0].properties_last_operation.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_uuids_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"email": "test@example.com"});
    let person = ctx
        .insert_person("props_test_2", Some(props))
        .await
        .expect("Failed to insert person");

    let without_props = ctx
        .storage
        .get_persons_by_uuids(ctx.team_id, &[person.uuid], false)
        .await
        .expect("Failed to get persons without props");
    assert_eq!(without_props.len(), 1);
    assert_eq!(without_props[0].id, person.id);
    assert!(without_props[0].properties.is_none());
    assert!(without_props[0].properties_last_updated_at.is_none());
    assert!(without_props[0].properties_last_operation.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_in_team_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"email": "test@example.com"});
    ctx.insert_person("props_did_test", Some(props))
        .await
        .expect("Failed to insert person");

    let results = ctx
        .storage
        .get_persons_by_distinct_ids_in_team(ctx.team_id, &["props_did_test".to_string()], false)
        .await
        .expect("Failed to get persons without props");
    assert_eq!(results.len(), 1);
    let person = results[0].1.as_ref().expect("Person should be found");
    assert!(person.properties.is_none());
    assert!(person.properties_last_updated_at.is_none());
    assert!(person.properties_last_operation.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_persons_by_distinct_ids_cross_team_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"email": "test@example.com"});
    ctx.insert_person("props_cross_test", Some(props))
        .await
        .expect("Failed to insert person");

    let results = ctx
        .storage
        .get_persons_by_distinct_ids_cross_team(
            &[(ctx.team_id, "props_cross_test".to_string())],
            false,
        )
        .await
        .expect("Failed to get persons without props");
    assert_eq!(results.len(), 1);
    let person = results[0].1.as_ref().expect("Person should be found");
    assert!(person.properties.is_none());
    assert!(person.properties_last_updated_at.is_none());
    assert!(person.properties_last_operation.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_groups_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"name": "Acme Corp"});
    ctx.insert_group(0, "grp_props_test", Some(props))
        .await
        .expect("Failed to insert group");

    let with_props = ctx
        .storage
        .get_groups(
            ctx.team_id,
            &[personhog_replica::storage::GroupIdentifier {
                group_type_index: 0,
                group_key: "grp_props_test".to_string(),
            }],
            ConsistencyLevel::Eventual,
            true,
        )
        .await
        .expect("Failed to get groups with props");
    assert_eq!(with_props.len(), 1);
    assert!(with_props[0].group_properties.is_some());

    let without_props = ctx
        .storage
        .get_groups(
            ctx.team_id,
            &[personhog_replica::storage::GroupIdentifier {
                group_type_index: 0,
                group_key: "grp_props_test".to_string(),
            }],
            ConsistencyLevel::Eventual,
            false,
        )
        .await
        .expect("Failed to get groups without props");
    assert_eq!(without_props.len(), 1);
    assert!(without_props[0].group_properties.is_none());
    assert!(without_props[0].properties_last_updated_at.is_none());
    assert!(without_props[0].properties_last_operation.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_get_groups_batch_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"name": "Batch Corp"});
    ctx.insert_group(0, "grp_batch_props", Some(props))
        .await
        .expect("Failed to insert group");

    let without_props = ctx
        .storage
        .get_groups_batch(
            &[GroupKey {
                team_id: ctx.team_id,
                group_type_index: 0,
                group_key: "grp_batch_props".to_string(),
            }],
            ConsistencyLevel::Eventual,
            false,
        )
        .await
        .expect("Failed to get groups batch without props");
    assert_eq!(without_props.len(), 1);
    assert!(without_props[0].1.group_properties.is_none());
    assert!(without_props[0].1.properties_last_updated_at.is_none());
    assert!(without_props[0].1.properties_last_operation.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_list_groups_without_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"name": "Listed Corp"});
    ctx.insert_group(0, "grp_list_props", Some(props))
        .await
        .expect("Failed to insert group");

    let (groups, _) = ctx
        .storage
        .list_groups(
            ctx.team_id,
            0,
            "",
            "",
            None,
            0,
            100,
            ConsistencyLevel::Eventual,
            false,
        )
        .await
        .expect("Failed to list groups without props");
    assert!(!groups.is_empty());
    for g in &groups {
        assert!(g.group_properties.is_none());
        assert!(g.properties_last_updated_at.is_none());
        assert!(g.properties_last_operation.is_none());
    }

    ctx.cleanup().await.ok();
}

// ============================================================
// split_person storage tests
// ============================================================

#[tokio::test]
async fn test_split_person_empty_distinct_ids() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("original@example.com", None)
        .await
        .unwrap();

    let results = ctx
        .storage
        .split_person(ctx.team_id, person.id, &[])
        .await
        .expect("Empty split should succeed");

    assert!(results.is_empty());
    ctx.cleanup().await.ok();
}

#[rstest]
#[case::single_split(1)]
#[case::two_splits(2)]
#[case::five_splits(5)]
#[tokio::test]
async fn test_split_person_creates_new_persons(#[case] num_splits: usize) {
    let ctx = TestContext::new().await;
    let person = ctx.insert_person("keeper@example.com", None).await.unwrap();

    let mut split_dids = Vec::new();
    for i in 0..num_splits {
        let did = format!("split_{i}@example.com");
        ctx.add_distinct_id_to_person(person.id, &did)
            .await
            .unwrap();
        split_dids.push(did);
    }

    let results = ctx
        .storage
        .split_person(ctx.team_id, person.id, &split_dids)
        .await
        .expect("Split should succeed");

    assert_eq!(results.len(), num_splits);

    for (i, result) in results.iter().enumerate() {
        // Results come back in request order
        assert_eq!(result.distinct_id, split_dids[i]);
        assert_eq!(result.new_person_version, 101); // original version 0 + 101
        assert_eq!(result.pdi_version, 101); // original PDI version 0 + 101

        // New person should exist in DB
        let new_person = ctx
            .storage
            .get_person_by_uuid(ctx.team_id, result.new_person_uuid)
            .await
            .expect("Lookup should succeed")
            .expect("New person should exist");
        assert_eq!(new_person.version, Some(101));
        assert_eq!(new_person.created_at, result.new_person_created_at);

        // PDI should now point to the new person
        let looked_up = ctx
            .storage
            .get_person_by_distinct_id(ctx.team_id, &result.distinct_id)
            .await
            .expect("Lookup should succeed")
            .expect("Person for distinct_id should exist");
        assert_eq!(looked_up.uuid, result.new_person_uuid);
    }

    // Original person still exists with its keeper distinct_id
    let original = ctx
        .storage
        .get_person_by_id(ctx.team_id, person.id)
        .await
        .expect("Lookup should succeed")
        .expect("Original person should still exist");
    assert_eq!(original.uuid, person.uuid);

    let original_by_did = ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "keeper@example.com")
        .await
        .expect("Lookup should succeed")
        .expect("Keeper DID should still resolve to original");
    assert_eq!(original_by_did.id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_version_arithmetic() {
    let ctx = TestContext::new().await;

    // Insert a person with a non-zero version
    let person_id = rand::thread_rng().gen_range(1_000_000i64..100_000_000);
    let person_uuid = Uuid::now_v7();
    let person_version: i64 = 42;

    sqlx::query(
        r#"INSERT INTO posthog_person
        (id, uuid, team_id, properties, properties_last_updated_at,
         properties_last_operation, created_at, version, is_identified, is_user_id)
        VALUES ($1, $2, $3, '{}'::jsonb, '{}', '{}', NOW(), $4, false, NULL)"#,
    )
    .bind(person_id)
    .bind(person_uuid)
    .bind(ctx.team_id)
    .bind(person_version)
    .execute(&ctx.pool)
    .await
    .unwrap();

    // Insert PDIs with non-zero versions
    let pdi_version: i64 = 7;
    for did in &["v_did_a", "v_did_b"] {
        sqlx::query(
            r#"INSERT INTO posthog_persondistinctid
            (distinct_id, person_id, team_id, version) VALUES ($1, $2, $3, $4)"#,
        )
        .bind(*did)
        .bind(person_id)
        .bind(ctx.team_id)
        .bind(pdi_version)
        .execute(&ctx.pool)
        .await
        .unwrap();
    }

    let results = ctx
        .storage
        .split_person(
            ctx.team_id,
            person_id,
            &["v_did_a".to_string(), "v_did_b".to_string()],
        )
        .await
        .expect("Split should succeed");

    for result in &results {
        assert_eq!(
            result.new_person_version,
            person_version + 101,
            "New person version should be original + 101"
        );
        assert_eq!(
            result.pdi_version,
            pdi_version + 101,
            "PDI version should be original + 101"
        );
    }

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_deterministic_uuids() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("det_keeper@example.com", None)
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "det_split@example.com")
        .await
        .unwrap();

    let results = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &["det_split@example.com".to_string()],
        )
        .await
        .expect("Split should succeed");

    // Compute expected UUID the same way the implementation does
    let namespace = Uuid::from_bytes([
        0x93, 0x29, 0x79, 0xb4, 0x65, 0xc3, 0x44, 0x24, 0x84, 0x67, 0x0b, 0x66, 0xec, 0x27, 0xbc,
        0x22,
    ]);
    let expected_uuid = Uuid::new_v5(
        &namespace,
        format!("{}:det_split@example.com", ctx.team_id).as_bytes(),
    );

    assert_eq!(results[0].new_person_uuid, expected_uuid);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_idempotent() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("idem_keeper@example.com", None)
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "idem_split@example.com")
        .await
        .unwrap();

    let results1 = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &["idem_split@example.com".to_string()],
        )
        .await
        .expect("First split should succeed");

    // After the first split, the PDI is reassigned to the new person.
    // A second call with the same person_id should get NOT_FOUND because
    // the distinct_id no longer belongs to that person.
    let err = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &["idem_split@example.com".to_string()],
        )
        .await
        .expect_err("Second split should fail because DID moved");

    let msg = err.to_string();
    assert!(
        msg.contains("Not found"),
        "Expected NotFound error, got: {msg}"
    );

    // The new person should still exist with the correct UUID
    let new_person = ctx
        .storage
        .get_person_by_uuid(ctx.team_id, results1[0].new_person_uuid)
        .await
        .expect("Lookup should succeed")
        .expect("New person should still exist");
    assert_eq!(new_person.version, Some(results1[0].new_person_version));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_preserves_created_at_of_existing_person() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("preexist_keeper@example.com", None)
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "preexist_split@example.com")
        .await
        .unwrap();

    // Pre-create the person the split will upsert into (same deterministic
    // UUIDv5), with a created_at in the past.
    let namespace = Uuid::from_bytes([
        0x93, 0x29, 0x79, 0xb4, 0x65, 0xc3, 0x44, 0x24, 0x84, 0x67, 0x0b, 0x66, 0xec, 0x27, 0xbc,
        0x22,
    ]);
    let split_uuid = Uuid::new_v5(
        &namespace,
        format!("{}:preexist_split@example.com", ctx.team_id).as_bytes(),
    );
    let old_created_at = chrono::DateTime::parse_from_rfc3339("2020-01-02T03:04:05Z")
        .unwrap()
        .with_timezone(&chrono::Utc);
    let existing_id = rand::thread_rng().gen_range(1_000_000i64..100_000_000);
    sqlx::query(
        r#"INSERT INTO posthog_person
        (id, uuid, team_id, properties, properties_last_updated_at,
         properties_last_operation, created_at, version, is_identified, is_user_id)
        VALUES ($1, $2, $3, '{}'::jsonb, '{}', '{}', $4, 3, false, NULL)"#,
    )
    .bind(existing_id)
    .bind(split_uuid)
    .bind(ctx.team_id)
    .bind(old_created_at)
    .execute(&ctx.pool)
    .await
    .unwrap();

    let results = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &["preexist_split@example.com".to_string()],
        )
        .await
        .expect("Split should succeed");

    // The upsert keeps the existing person's created_at; the response must
    // report it so callers publish the value that matches Postgres.
    assert_eq!(results[0].new_person_uuid, split_uuid);
    assert_eq!(results[0].new_person_created_at, old_created_at);
    assert_eq!(results[0].new_person_version, 101); // source person version 0 + 101

    let upserted = ctx
        .storage
        .get_person_by_uuid(ctx.team_id, split_uuid)
        .await
        .expect("Lookup should succeed")
        .expect("Upserted person should exist");
    assert_eq!(upserted.created_at, old_created_at);
    assert_eq!(upserted.version, Some(101));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_not_found_unknown_distinct_id() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("nf_keeper@example.com", None)
        .await
        .unwrap();

    let err = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &["nonexistent@example.com".to_string()],
        )
        .await
        .expect_err("Should fail with NOT_FOUND");

    let msg = err.to_string();
    assert!(
        msg.contains("Not found"),
        "Expected NotFound error, got: {msg}"
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_not_found_wrong_person() {
    let ctx = TestContext::new().await;
    let person_a = ctx.insert_person("a@example.com", None).await.unwrap();
    let _person_b = ctx.insert_person("b@example.com", None).await.unwrap();

    // Try to split person_b's distinct_id from person_a
    let err = ctx
        .storage
        .split_person(ctx.team_id, person_a.id, &["b@example.com".to_string()])
        .await
        .expect_err("Should fail with NOT_FOUND");

    let msg = err.to_string();
    assert!(
        msg.contains("Not found"),
        "Expected NotFound error, got: {msg}"
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_not_found_nonexistent_person() {
    let ctx = TestContext::new().await;

    let err = ctx
        .storage
        .split_person(
            ctx.team_id,
            999999999,
            &["anything@example.com".to_string()],
        )
        .await
        .expect_err("Should fail for nonexistent person");

    let msg = err.to_string();
    assert!(
        msg.contains("Not found"),
        "Expected NotFound error, got: {msg}"
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_cross_team_isolation() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("iso_keeper@example.com", None)
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "iso_split@example.com")
        .await
        .unwrap();

    let other_team_id = ctx.team_id + 1;

    // Splitting with wrong team_id should fail
    let err = ctx
        .storage
        .split_person(
            other_team_id,
            person.id,
            &["iso_split@example.com".to_string()],
        )
        .await
        .expect_err("Should fail with wrong team_id");

    let msg = err.to_string();
    assert!(
        msg.contains("Not found"),
        "Expected NotFound error, got: {msg}"
    );

    // Original should be untouched
    let original = ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "iso_split@example.com")
        .await
        .expect("Lookup should succeed")
        .expect("Original DID should still resolve");
    assert_eq!(original.id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_transaction_rollback_on_partial_failure() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("tx_keeper@example.com", None)
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "tx_split_a@example.com")
        .await
        .unwrap();

    // Request includes one valid and one invalid distinct_id.
    // Ownership validation under the lock should reject the whole request.
    let err = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &[
                "tx_split_a@example.com".to_string(),
                "tx_nonexistent@example.com".to_string(),
            ],
        )
        .await
        .expect_err("Should fail due to unknown distinct_id");

    let msg = err.to_string();
    assert!(
        msg.contains("Not found"),
        "Expected NotFound error, got: {msg}"
    );

    // Valid distinct_id should NOT have been reassigned (no partial commit)
    let still_original = ctx
        .storage
        .get_person_by_distinct_id(ctx.team_id, "tx_split_a@example.com")
        .await
        .expect("Lookup should succeed")
        .expect("DID should still resolve to original");
    assert_eq!(
        still_original.id, person.id,
        "tx_split_a should still belong to original person after failed split"
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_new_persons_have_empty_properties() {
    let ctx = TestContext::new().await;
    let props = serde_json::json!({"email": "rich@example.com", "plan": "enterprise"});
    let person = ctx
        .insert_person("prop_keeper@example.com", Some(props))
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "prop_split@example.com")
        .await
        .unwrap();

    let results = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &["prop_split@example.com".to_string()],
        )
        .await
        .expect("Split should succeed");

    let new_person = ctx
        .storage
        .get_person_by_uuid(ctx.team_id, results[0].new_person_uuid)
        .await
        .expect("Lookup should succeed")
        .expect("New person should exist");

    // New persons from split get empty properties, not the original's
    let props_str = new_person.properties.expect("properties should be set");
    let props_val: serde_json::Value =
        serde_json::from_str(&props_str).expect("properties should be valid JSON");
    assert_eq!(props_val, serde_json::json!({}));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_split_person_each_did_gets_unique_person() {
    let ctx = TestContext::new().await;
    let person = ctx
        .insert_person("multi_keeper@example.com", None)
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "multi_a@example.com")
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "multi_b@example.com")
        .await
        .unwrap();
    ctx.add_distinct_id_to_person(person.id, "multi_c@example.com")
        .await
        .unwrap();

    let results = ctx
        .storage
        .split_person(
            ctx.team_id,
            person.id,
            &[
                "multi_a@example.com".to_string(),
                "multi_b@example.com".to_string(),
                "multi_c@example.com".to_string(),
            ],
        )
        .await
        .expect("Split should succeed");

    // Each split distinct_id should get a different new person UUID
    let uuids: std::collections::HashSet<Uuid> =
        results.iter().map(|r| r.new_person_uuid).collect();
    assert_eq!(
        uuids.len(),
        3,
        "Each split DID should produce a unique person"
    );

    // None of them should be the original person
    for uuid in &uuids {
        assert_ne!(
            *uuid, person.uuid,
            "New person UUID must differ from original"
        );
    }

    ctx.cleanup().await.ok();
}

// ============================================================
// Undelete repair: reset version tests
// ============================================================

#[tokio::test]
async fn test_set_person_distinct_id_version_floor_updates_and_returns_person() {
    let ctx = TestContext::new().await;
    let person = ctx.insert_person("repair_did", None).await.unwrap();

    let returned = ctx
        .storage
        .set_person_distinct_id_version_floor(ctx.team_id, "repair_did", 150)
        .await
        .expect("reset should succeed")
        .expect("person should be returned");
    assert_eq!(returned.id, person.id);
    assert_eq!(returned.uuid, person.uuid);

    let version: i64 = sqlx::query_scalar(
        "SELECT version FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind("repair_did")
    .fetch_one(&ctx.pool)
    .await
    .unwrap();
    assert_eq!(version, 150);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_set_person_distinct_id_version_floor_missing_returns_none() {
    let ctx = TestContext::new().await;

    let returned = ctx
        .storage
        .set_person_distinct_id_version_floor(ctx.team_id, "nonexistent_did", 10)
        .await
        .expect("reset should succeed");
    assert!(returned.is_none());

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_set_person_distinct_id_version_floor_does_not_lower() {
    let ctx = TestContext::new().await;
    let person = ctx.insert_person("repair_high_did", None).await.unwrap();

    // Put the PDI at a high version first.
    sqlx::query(
        "UPDATE posthog_persondistinctid SET version = 200 WHERE team_id = $1 AND distinct_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind("repair_high_did")
    .execute(&ctx.pool)
    .await
    .unwrap();

    // A lower min_version must not lower it — but the person is still returned.
    let returned = ctx
        .storage
        .set_person_distinct_id_version_floor(ctx.team_id, "repair_high_did", 150)
        .await
        .expect("reset should succeed")
        .expect("person should still be returned when the distinct_id exists");
    assert_eq!(returned.id, person.id);

    let version: i64 = sqlx::query_scalar(
        "SELECT version FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind("repair_high_did")
    .fetch_one(&ctx.pool)
    .await
    .unwrap();
    assert_eq!(version, 200);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_set_person_version_floor_guarded_bump() {
    let ctx = TestContext::new().await;
    let person = ctx.insert_person("rv_did", None).await.unwrap();

    // Bump above the current version (0).
    let updated = ctx
        .storage
        .set_person_version_floor(ctx.team_id, person.id, 50)
        .await
        .unwrap();
    assert!(updated);
    let p = ctx
        .storage
        .get_person_by_id(ctx.team_id, person.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(p.version, Some(50));

    // A lower min_version is a no-op — the guard never lowers a version.
    let updated = ctx
        .storage
        .set_person_version_floor(ctx.team_id, person.id, 10)
        .await
        .unwrap();
    assert!(!updated);
    let p = ctx
        .storage
        .get_person_by_id(ctx.team_id, person.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(p.version, Some(50));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_set_person_version_floor_missing_person() {
    let ctx = TestContext::new().await;

    let updated = ctx
        .storage
        .set_person_version_floor(ctx.team_id, 999_999_999, 5)
        .await
        .unwrap();
    assert!(!updated);

    ctx.cleanup().await.ok();
}
