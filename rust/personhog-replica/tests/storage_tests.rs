mod common;

use common::TestContext;

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
        .get_distinct_ids_for_person(ctx.team_id, person.id)
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
        .get_group(ctx.team_id, group.group_type_index, &group.group_key)
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
        .get_group_type_mappings_by_team_id(ctx.team_id)
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
        .check_cohort_membership(person.id, &[cohort_id_1, cohort_id_2])
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
