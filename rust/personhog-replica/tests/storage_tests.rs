mod common;

use common::TestContext;
use personhog_replica::storage::postgres::ConsistencyLevel;
use personhog_replica::storage::{GroupKey, HashKeyOverrideInput};

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
        .get_persons_by_ids(ctx.team_id, &[person1.id, person2.id, 999999999])
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
        .get_distinct_ids_for_person(ctx.team_id, person.id, ConsistencyLevel::Eventual)
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
    assert_eq!(fetched.group_properties, properties);

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
    assert_eq!(fetched.properties["email"], "props_test@example.com");
    assert_eq!(fetched.properties["plan"], "enterprise");

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
        .get_persons_by_uuids(ctx.team_id, &[person1.uuid, person2.uuid, nonexistent_uuid])
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
        .get_groups_batch(&keys, ConsistencyLevel::Eventual)
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

    let person = ctx
        .insert_person("upsert_single_user", None)
        .await
        .expect("Failed to insert person");

    let overrides = vec![HashKeyOverrideInput {
        person_id: person.id,
        feature_flag_key: "test-flag".to_string(),
    }];

    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &overrides, "my_hash_key")
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
async fn test_upsert_hash_key_overrides_multiple_overrides_same_hash_key() {
    let ctx = TestContext::new().await;

    let person1 = ctx
        .insert_person("upsert_multi_user1", None)
        .await
        .expect("Failed to insert person 1");
    let person2 = ctx
        .insert_person("upsert_multi_user2", None)
        .await
        .expect("Failed to insert person 2");

    // Multiple overrides for different persons and flags, all sharing the same hash_key
    let overrides = vec![
        HashKeyOverrideInput {
            person_id: person1.id,
            feature_flag_key: "flag-a".to_string(),
        },
        HashKeyOverrideInput {
            person_id: person1.id,
            feature_flag_key: "flag-b".to_string(),
        },
        HashKeyOverrideInput {
            person_id: person2.id,
            feature_flag_key: "flag-a".to_string(),
        },
    ];

    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &overrides, "shared_anon_id")
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(inserted_count, 3);

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

    // All overrides should have the same hash_key
    for person_result in &result {
        for override_entry in &person_result.overrides {
            assert_eq!(override_entry.hash_key, "shared_anon_id");
        }
    }

    // Person 1 should have 2 overrides
    let person1_result = result.iter().find(|r| r.person_id == person1.id).unwrap();
    assert_eq!(person1_result.overrides.len(), 2);

    // Person 2 should have 1 override
    let person2_result = result.iter().find(|r| r.person_id == person2.id).unwrap();
    assert_eq!(person2_result.overrides.len(), 1);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_empty_returns_zero() {
    let ctx = TestContext::new().await;

    let overrides: Vec<HashKeyOverrideInput> = vec![];

    let inserted_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &overrides, "unused_hash_key")
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(inserted_count, 0);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn test_upsert_hash_key_overrides_on_conflict_do_nothing() {
    let ctx = TestContext::new().await;

    let person = ctx
        .insert_person("upsert_conflict_user", None)
        .await
        .expect("Failed to insert person");

    let overrides = vec![HashKeyOverrideInput {
        person_id: person.id,
        feature_flag_key: "conflict-flag".to_string(),
    }];

    // First insert
    let first_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &overrides, "first_hash")
        .await
        .expect("Failed to upsert hash key overrides");

    assert_eq!(first_count, 1);

    // Second insert with same person_id and feature_flag_key should do nothing
    // (ON CONFLICT DO NOTHING)
    let second_count = ctx
        .storage
        .upsert_hash_key_overrides(ctx.team_id, &overrides, "second_hash")
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
        .delete_hash_key_overrides_by_teams(&[ctx.team_id])
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
        .delete_hash_key_overrides_by_teams(&[])
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
        .delete_hash_key_overrides_by_teams(&[999999999])
        .await
        .expect("Failed to delete hash key overrides");

    assert_eq!(deleted_count, 0);

    ctx.cleanup().await.ok();
}
