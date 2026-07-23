mod common;

use std::time::Duration;

use chrono::{TimeZone, Utc};
use common::TestContext;

use personhog_common::persons::person_uuid;
use personhog_identity::storage::{IdentityStorage, PersonStub, StubOutcome};

/// Storage-assertion helpers used only by this test binary.
impl TestContext {
    async fn insert_personless_distinct_id(&self, distinct_id: &str, is_merged: bool) {
        sqlx::query(
            r#"
            INSERT INTO posthog_personlessdistinctid (distinct_id, is_merged, created_at, team_id)
            VALUES ($1, $2, now(), $3)
            "#,
        )
        .bind(distinct_id)
        .bind(is_merged)
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await
        .expect("Failed to insert personless distinct id");
    }

    async fn distinct_id_version(&self, distinct_id: &str) -> Option<i64> {
        sqlx::query_scalar(
            "SELECT version FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2",
        )
        .bind(self.team_id as i32)
        .bind(distinct_id)
        .fetch_optional(&self.pool)
        .await
        .expect("Failed to fetch distinct id version")
        .flatten()
    }

    async fn personless_is_merged(&self, distinct_id: &str) -> Option<bool> {
        sqlx::query_scalar(
            "SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2",
        )
        .bind(self.team_id as i32)
        .bind(distinct_id)
        .fetch_optional(&self.pool)
        .await
        .expect("Failed to fetch personless row")
    }

    async fn person_count(&self) -> i64 {
        sqlx::query_scalar("SELECT count(*) FROM posthog_person WHERE team_id = $1")
            .bind(self.team_id as i32)
            .fetch_one(&self.pool)
            .await
            .expect("Failed to count persons")
    }
}

fn stub(ctx: &TestContext, distinct_id: &str, extras: &[&str]) -> PersonStub {
    PersonStub {
        team_id: ctx.team_id,
        distinct_id: distinct_id.to_string(),
        extra_distinct_ids: extras.iter().map(|s| s.to_string()).collect(),
        created_at: Utc.with_ymd_and_hms(2026, 7, 20, 12, 34, 56).unwrap(),
        is_identified: false,
    }
}

#[tokio::test]
async fn creates_stub_with_deterministic_uuid_and_version_zero() {
    let ctx = TestContext::new().await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "user-1", &[])])
        .await
        .expect("create should succeed");

    let [StubOutcome::Committed { person, created }] = &outcomes[..] else {
        panic!("expected one committed outcome");
    };
    assert!(created);
    assert_eq!(person.uuid, person_uuid(ctx.team_id, "user-1"));
    assert_eq!(person.version, Some(0));
    assert_eq!(person.properties.as_deref(), Some("{}"));
    assert!(!person.is_identified);
    assert_eq!(
        person.created_at,
        Utc.with_ymd_and_hms(2026, 7, 20, 12, 34, 56).unwrap()
    );
    assert_eq!(ctx.distinct_id_version("user-1").await, Some(0));

    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "user-1".to_string())])
        .await
        .expect("resolve should succeed");
    assert_eq!(resolved[&(ctx.team_id, "user-1".to_string())].id, person.id);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn retried_create_returns_existing_person_without_duplicating() {
    let ctx = TestContext::new().await;

    let first = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "user-2", &[])])
        .await
        .expect("first create should succeed");
    let [StubOutcome::Committed {
        person: first_person,
        created: true,
    }] = &first[..]
    else {
        panic!("expected created outcome");
    };

    let second = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "user-2", &[])])
        .await
        .expect("second create should succeed");
    let [StubOutcome::Committed { person, created }] = &second[..] else {
        panic!("expected committed outcome");
    };
    assert!(!created);
    assert_eq!(person.id, first_person.id);
    assert_eq!(ctx.person_count().await, 1);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn extra_distinct_ids_carry_personless_history_as_version_one() {
    let ctx = TestContext::new().await;
    // "seen-before" was used personless; "fresh" was not.
    ctx.insert_personless_distinct_id("seen-before", false)
        .await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "primary", &["seen-before", "fresh"])])
        .await
        .expect("create should succeed");
    let [StubOutcome::Committed { created: true, .. }] = &outcomes[..] else {
        panic!("expected created outcome");
    };

    assert_eq!(ctx.distinct_id_version("primary").await, Some(0));
    assert_eq!(ctx.distinct_id_version("seen-before").await, Some(1));
    assert_eq!(ctx.distinct_id_version("fresh").await, Some(0));
    // Both extras are marked merged so concurrent personless events re-resolve.
    assert_eq!(ctx.personless_is_merged("seen-before").await, Some(true));
    assert_eq!(ctx.personless_is_merged("fresh").await, Some(true));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn create_loses_race_when_distinct_id_is_mapped_to_another_person() {
    let ctx = TestContext::new().await;
    // The distinct id is already mapped to a person whose uuid is not the
    // deterministic one (e.g. it arrived via merge), so the stub insert
    // succeeds but the mapping conflict must roll that stub back.
    let existing_id = ctx.insert_person_with_distinct_id("taken").await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "taken", &[])])
        .await
        .expect("create should not error");
    assert!(matches!(outcomes[..], [StubOutcome::LostRace]));

    // No orphan stub row was left behind.
    assert_eq!(ctx.person_count().await, 1);
    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "taken".to_string())])
        .await
        .expect("resolve should succeed");
    assert_eq!(
        resolved[&(ctx.team_id, "taken".to_string())].id,
        existing_id
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn batch_mixes_created_existing_and_lost_race_outcomes_per_row() {
    let ctx = TestContext::new().await;
    let taken_id = ctx.insert_person_with_distinct_id("mix-taken").await;
    // "mix-existing" already has its deterministic stub from an earlier create.
    let seeded = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "mix-existing", &[])])
        .await
        .expect("seed create should succeed");
    let [StubOutcome::Committed {
        person: seeded_person,
        created: true,
    }] = &seeded[..]
    else {
        panic!("expected seeded outcome");
    };

    let outcomes = ctx
        .storage
        .create_person_stubs(&[
            stub(&ctx, "mix-new", &[]),
            stub(&ctx, "mix-existing", &[]),
            stub(&ctx, "mix-taken", &[]),
        ])
        .await
        .expect("batch create should succeed");

    let [StubOutcome::Committed {
        person: new_person,
        created: true,
    }, StubOutcome::Committed {
        person: existing_person,
        created: false,
    }, StubOutcome::LostRace] = &outcomes[..]
    else {
        panic!("expected created/existing/lost-race outcomes, got {outcomes:?}");
    };

    assert_eq!(new_person.uuid, person_uuid(ctx.team_id, "mix-new"));
    assert_eq!(existing_person.id, seeded_person.id);
    // The lost race left no orphan: taken + existing + new = 3 persons.
    assert_eq!(ctx.person_count().await, 3);
    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "mix-taken".to_string())])
        .await
        .expect("resolve should succeed");
    assert_eq!(
        resolved[&(ctx.team_id, "mix-taken".to_string())].id,
        taken_id
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn concurrent_creates_for_one_distinct_id_create_exactly_once() {
    let ctx = TestContext::new().await;

    let tasks: Vec<_> = (0..8)
        .map(|_| {
            let storage = ctx.storage.clone();
            let stub = stub(&ctx, "race-key", &[]);
            tokio::spawn(async move { storage.create_person_stubs(&[stub]).await })
        })
        .collect();

    let mut created_count = 0;
    let mut person_ids = Vec::new();
    for task in tasks {
        let outcomes = task
            .await
            .expect("task must not panic")
            .expect("create should not error");
        let [StubOutcome::Committed { person, created }] = &outcomes[..] else {
            panic!("every racer must converge on the winner, got {outcomes:?}");
        };
        created_count += usize::from(*created);
        person_ids.push(person.id);
    }

    assert_eq!(created_count, 1, "exactly one racer reports created = true");
    assert!(person_ids.windows(2).all(|w| w[0] == w[1]));
    assert_eq!(ctx.person_count().await, 1);

    ctx.cleanup().await.ok();
}

/// The uncommitted-winner window: a concurrent creator has inserted the
/// deterministic-uuid person but not yet committed. Our insert must block in
/// the speculative-insert wait, and after the winner commits, the separate
/// winner-fetch statement must see the row in its fresh snapshot — a
/// same-statement fetch would miss it and lose the person entirely.
#[tokio::test]
async fn create_blocked_on_uncommitted_winner_resolves_to_it_after_commit() {
    let ctx = TestContext::new().await;
    let uuid = person_uuid(ctx.team_id, "held-key");

    let mut held = ctx.pool.begin().await.expect("begin held tx");
    let winner_id: i64 = sqlx::query_scalar(
        r#"
        INSERT INTO posthog_person
            (created_at, properties, properties_last_updated_at, properties_last_operation,
             team_id, is_identified, uuid, version)
        VALUES (now(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, $1, false, $2, 0)
        RETURNING id
        "#,
    )
    .bind(ctx.team_id as i32)
    .bind(uuid)
    .fetch_one(&mut *held)
    .await
    .expect("insert uncommitted winner");

    let storage = ctx.storage.clone();
    let racing_stub = stub(&ctx, "held-key", &[]);
    let racer = tokio::spawn(async move { storage.create_person_stubs(&[racing_stub]).await });

    // The racer's insert conflicts with the uncommitted row, so it must sit
    // in the speculative-insert wait for as long as the transaction is open.
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(
        !racer.is_finished(),
        "create must block on the uncommitted winner's insert"
    );

    held.commit().await.expect("commit winner");
    let outcomes = racer
        .await
        .expect("task must not panic")
        .expect("create should not error");
    let [StubOutcome::Committed { person, created }] = &outcomes[..] else {
        panic!("racer must resolve to the committed winner, got {outcomes:?}");
    };
    assert!(!created);
    assert_eq!(person.id, winner_id);

    // The winner had no distinct id row; the racer attached it.
    assert_eq!(ctx.person_count().await, 1);
    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "held-key".to_string())])
        .await
        .expect("resolve should succeed");
    assert_eq!(
        resolved[&(ctx.team_id, "held-key".to_string())].id,
        winner_id
    );

    ctx.cleanup().await.ok();
}

/// The uncommitted mapping-steal window: a concurrent writer (a merge, an
/// add-distinct-id) has mapped the distinct id to a different person but not
/// yet committed. Our stub insert succeeds (different uuid), the distinct id
/// insert blocks on the unique index, and after the winner commits the whole
/// stub must roll back as a lost race — leaving no orphan person behind.
#[tokio::test]
async fn create_blocked_on_uncommitted_mapping_rolls_back_as_lost_race() {
    let ctx = TestContext::new().await;

    let mut held = ctx.pool.begin().await.expect("begin held tx");
    let other_id: i64 = sqlx::query_scalar(
        r#"
        INSERT INTO posthog_person
            (created_at, properties, properties_last_updated_at, properties_last_operation,
             team_id, is_identified, uuid, version)
        VALUES (now(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, $1, false, gen_random_uuid(), 0)
        RETURNING id
        "#,
    )
    .bind(ctx.team_id as i32)
    .fetch_one(&mut *held)
    .await
    .expect("insert other person");
    sqlx::query(
        r#"
        INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
        VALUES ($1, $2, $3, 0)
        "#,
    )
    .bind("stolen-key")
    .bind(other_id)
    .bind(ctx.team_id as i32)
    .execute(&mut *held)
    .await
    .expect("map distinct id in held tx");

    let storage = ctx.storage.clone();
    let racing_stub = stub(&ctx, "stolen-key", &[]);
    let racer = tokio::spawn(async move { storage.create_person_stubs(&[racing_stub]).await });

    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(
        !racer.is_finished(),
        "create must block on the uncommitted distinct id mapping"
    );

    held.commit().await.expect("commit mapping winner");
    let outcomes = racer
        .await
        .expect("task must not panic")
        .expect("create should not error");
    assert!(
        matches!(outcomes[..], [StubOutcome::LostRace]),
        "stolen mapping must resolve to a lost race, got {outcomes:?}"
    );

    // The racer's stub was rolled back; only the mapping winner remains.
    assert_eq!(ctx.person_count().await, 1);
    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "stolen-key".to_string())])
        .await
        .expect("resolve should succeed");
    assert_eq!(
        resolved[&(ctx.team_id, "stolen-key".to_string())].id,
        other_id
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn resolve_returns_only_existing_keys() {
    let ctx = TestContext::new().await;
    let person_id = ctx.insert_person_with_distinct_id("known").await;

    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[
            (ctx.team_id, "known".to_string()),
            (ctx.team_id, "unknown".to_string()),
        ])
        .await
        .expect("resolve should succeed");

    assert_eq!(resolved.len(), 1);
    assert_eq!(resolved[&(ctx.team_id, "known".to_string())].id, person_id);

    ctx.cleanup().await.ok();
}
