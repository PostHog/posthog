mod common;

use std::time::Duration;

use chrono::{TimeZone, Utc};
use common::TestContext;

use personhog_common::persons::person_uuid;
use personhog_identity::storage::{AttachOutcome, IdentityStorage, PersonStub, StubOutcome};

/// Storage-assertion helpers used only by this test binary.
impl TestContext {
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

    async fn person_count(&self) -> i64 {
        sqlx::query_scalar("SELECT count(*) FROM posthog_person WHERE team_id = $1")
            .bind(self.team_id as i32)
            .fetch_one(&self.pool)
            .await
            .expect("Failed to count persons")
    }

    /// Tombstones a person the way the delete saga does: flag flipped,
    /// version parked above every prior write, properties cleared.
    async fn tombstone_person(&self, person_id: i64, version: i64) {
        sqlx::query(
            r#"
            UPDATE posthog_person
            SET is_deleted = true, version = $3, properties = '{}'::jsonb
            WHERE team_id = $1 AND id = $2
            "#,
        )
        .bind(self.team_id as i32)
        .bind(person_id)
        .bind(version)
        .execute(&self.pool)
        .await
        .expect("Failed to tombstone person");
    }

    async fn tombstone_distinct_id(&self, distinct_id: &str, version: i64) {
        sqlx::query(
            r#"
            UPDATE posthog_persondistinctid
            SET is_deleted = true, version = $3
            WHERE team_id = $1 AND distinct_id = $2
            "#,
        )
        .bind(self.team_id as i32)
        .bind(distinct_id)
        .bind(version)
        .execute(&self.pool)
        .await
        .expect("Failed to tombstone distinct id");
    }

    async fn insert_tombstoned_person(&self, uuid: uuid::Uuid, version: i64) -> i64 {
        sqlx::query_scalar(
            r#"
            INSERT INTO posthog_person
                (created_at, properties, properties_last_updated_at, properties_last_operation,
                 team_id, is_identified, uuid, version, is_deleted)
            VALUES (now(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, $1, false, $2, $3, true)
            RETURNING id
            "#,
        )
        .bind(self.team_id as i32)
        .bind(uuid)
        .bind(version)
        .fetch_one(&self.pool)
        .await
        .expect("Failed to insert tombstoned person")
    }

    async fn insert_tombstoned_distinct_id(&self, distinct_id: &str, person_id: i64, version: i64) {
        sqlx::query(
            r#"
            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version, is_deleted)
            VALUES ($1, $2, $3, $4, true)
            "#,
        )
        .bind(distinct_id)
        .bind(person_id)
        .bind(self.team_id as i32)
        .bind(version)
        .execute(&self.pool)
        .await
        .expect("Failed to insert tombstoned distinct id");
    }

    /// (is_deleted, version) for a person row, tombstoned or not.
    async fn person_state(&self, person_id: i64) -> (bool, Option<i64>) {
        sqlx::query_as(
            "SELECT is_deleted, version FROM posthog_person WHERE team_id = $1 AND id = $2",
        )
        .bind(self.team_id as i32)
        .bind(person_id)
        .fetch_one(&self.pool)
        .await
        .expect("Failed to fetch person state")
    }

    /// (person_id, is_deleted, version) for a distinct id row, tombstoned or not.
    async fn distinct_id_state(&self, distinct_id: &str) -> Option<(i64, bool, Option<i64>)> {
        sqlx::query_as(
            r#"
            SELECT person_id, is_deleted, version FROM posthog_persondistinctid
            WHERE team_id = $1 AND distinct_id = $2
            "#,
        )
        .bind(self.team_id as i32)
        .bind(distinct_id)
        .fetch_optional(&self.pool)
        .await
        .expect("Failed to fetch distinct id state")
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
async fn extra_distinct_ids_always_get_version_one() {
    let ctx = TestContext::new().await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "primary", &["extra-a", "extra-b"])])
        .await
        .expect("create should succeed");
    let [StubOutcome::Committed { created: true, .. }] = &outcomes[..] else {
        panic!("expected created outcome");
    };

    // The primary derives the person uuid, so its history is correct by
    // construction: version 0. Extras can't be proven history-free, so they
    // always get version 1 and let ClickHouse emit an override.
    assert_eq!(ctx.distinct_id_version("primary").await, Some(0));
    assert_eq!(ctx.distinct_id_version("extra-a").await, Some(1));
    assert_eq!(ctx.distinct_id_version("extra-b").await, Some(1));

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
async fn lost_race_undo_keeps_extras_shared_with_a_committed_stub() {
    let ctx = TestContext::new().await;
    // The loser's primary distinct id is already mapped elsewhere, so its
    // whole stub rolls back — but an extra shared with a committed stub was
    // written under the winner's person and must survive the undo.
    ctx.insert_person_with_distinct_id("undo-taken").await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[
            stub(&ctx, "undo-winner", &["undo-shared"]),
            stub(&ctx, "undo-taken", &["undo-own", "undo-shared"]),
        ])
        .await
        .expect("create should not error");
    assert!(
        matches!(
            outcomes[..],
            [
                StubOutcome::Committed { created: true, .. },
                StubOutcome::LostRace
            ]
        ),
        "expected committed + lost race, got {outcomes:?}"
    );

    // The undone stub's own rows are gone, the shared extra's mapping stands.
    assert_eq!(ctx.distinct_id_version("undo-own").await, None);
    assert_eq!(ctx.distinct_id_version("undo-shared").await, Some(1));

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

/// A deleted person's rows stay behind as tombstones; re-creating the same
/// distinct id must revive them above the tombstone version instead of
/// inserting a fresh row that restarts at version 0 (which would lose to the
/// ClickHouse tombstone forever).
#[tokio::test]
async fn deleted_person_is_revived_above_the_tombstone_on_recreate() {
    let ctx = TestContext::new().await;

    let first = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "revive-me", &[])])
        .await
        .expect("first create should succeed");
    let [StubOutcome::Committed { person, .. }] = &first[..] else {
        panic!("expected committed outcome");
    };
    let person_id = person.id;

    ctx.tombstone_person(person_id, 7).await;
    ctx.tombstone_distinct_id("revive-me", 3).await;

    // Tombstoned rows are invisible to resolution.
    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "revive-me".to_string())])
        .await
        .expect("resolve should succeed");
    assert!(resolved.is_empty(), "tombstoned person must not resolve");

    let second = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "revive-me", &[])])
        .await
        .expect("recreate should succeed");
    let [StubOutcome::Committed { person, created }] = &second[..] else {
        panic!("expected committed outcome, got {second:?}");
    };
    assert!(created, "a revival is a creation to the caller");
    assert_eq!(person.id, person_id, "revival keeps the row, not a new one");
    assert_eq!(person.version, Some(8), "revived above the tombstone");
    assert_eq!(person.properties.as_deref(), Some("{}"));
    assert_eq!(
        ctx.distinct_id_state("revive-me").await,
        Some((person_id, false, Some(4))),
        "mapping revived above its tombstone"
    );
    assert_eq!(ctx.person_count().await, 1);

    ctx.cleanup().await.ok();
}

/// A revived stub that loses the mapping race must be re-tombstoned, not
/// hard-deleted: the tombstones predate this transaction and deleting them
/// would reopen the version-0-resurrection hole for the next recreate.
#[tokio::test]
async fn lost_race_rollback_re_tombstones_revived_rows() {
    let ctx = TestContext::new().await;
    // "steal-did" is live-mapped to another person, while its deterministic
    // uuid still belongs to a tombstoned person with a tombstoned extra.
    let live_id = ctx.insert_person_with_distinct_id("steal-did").await;
    let dead_id = ctx
        .insert_tombstoned_person(person_uuid(ctx.team_id, "steal-did"), 5)
        .await;
    ctx.insert_tombstoned_distinct_id("dead-extra", dead_id, 2)
        .await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[stub(&ctx, "steal-did", &["dead-extra"])])
        .await
        .expect("create should not error");
    assert!(
        matches!(outcomes[..], [StubOutcome::LostRace]),
        "live mapping must win, got {outcomes:?}"
    );

    let (is_deleted, version) = ctx.person_state(dead_id).await;
    assert!(
        is_deleted,
        "revived person must be re-tombstoned, not deleted"
    );
    assert!(
        version > Some(5),
        "re-tombstone stays above the old tombstone"
    );
    let (_, extra_deleted, extra_version) = ctx
        .distinct_id_state("dead-extra")
        .await
        .expect("revived mapping must be re-tombstoned, not deleted");
    assert!(extra_deleted);
    assert!(extra_version > Some(2));

    let resolved = ctx
        .storage
        .resolve_distinct_ids(&[(ctx.team_id, "steal-did".to_string())])
        .await
        .expect("resolve should succeed");
    assert_eq!(
        resolved[&(ctx.team_id, "steal-did".to_string())].id,
        live_id
    );
    assert_eq!(ctx.person_count().await, 2, "no orphan third person");

    ctx.cleanup().await.ok();
}

/// Duplicate keys in one batch conflict-update the same tombstoned row; the
/// pre-insert dedup keeps Postgres from rejecting the command with "ON
/// CONFLICT DO UPDATE cannot affect row a second time".
#[tokio::test]
async fn duplicate_batch_keys_against_tombstones_do_not_error() {
    let ctx = TestContext::new().await;
    let dead_id = ctx
        .insert_tombstoned_person(person_uuid(ctx.team_id, "dup-did"), 4)
        .await;
    ctx.insert_tombstoned_distinct_id("dup-did", dead_id, 1)
        .await;
    ctx.insert_tombstoned_distinct_id("dup-extra", dead_id, 1)
        .await;

    let outcomes = ctx
        .storage
        .create_person_stubs(&[
            stub(&ctx, "dup-did", &["dup-extra"]),
            stub(&ctx, "dup-did", &["dup-extra"]),
        ])
        .await
        .expect("duplicate keys in one batch must not error");

    let [StubOutcome::Committed { person: a, .. }, StubOutcome::Committed { person: b, .. }] =
        &outcomes[..]
    else {
        panic!("expected two committed outcomes, got {outcomes:?}");
    };
    assert_eq!(a.id, dead_id);
    assert_eq!(b.id, dead_id);
    let (is_deleted, _) = ctx.person_state(dead_id).await;
    assert!(!is_deleted, "person revived exactly once");

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

#[tokio::test]
async fn attach_covers_fresh_revived_and_live_mappings_per_row() {
    let ctx = TestContext::new().await;
    let owner = ctx.insert_person_with_distinct_id("attach-owner").await;
    let target = ctx.insert_person_with_distinct_id("attach-target").await;
    ctx.insert_tombstoned_distinct_id("attach-tomb", owner, 5)
        .await;

    let outcomes = ctx
        .storage
        .attach_distinct_ids(
            ctx.team_id,
            target,
            &[
                "attach-fresh".to_string(),
                "attach-tomb".to_string(),
                "attach-owner".to_string(),
            ],
        )
        .await
        .expect("attach should succeed");

    assert_eq!(
        outcomes.get("attach-fresh"),
        Some(&AttachOutcome::Attached { version: 1 })
    );
    assert_eq!(
        outcomes.get("attach-tomb"),
        Some(&AttachOutcome::Attached { version: 6 })
    );
    assert_eq!(
        outcomes.get("attach-owner"),
        Some(&AttachOutcome::AlreadyMapped { person_id: owner })
    );
    assert_eq!(
        ctx.distinct_id_state("attach-fresh").await,
        Some((target, false, Some(1)))
    );
    assert_eq!(
        ctx.distinct_id_state("attach-tomb").await,
        Some((target, false, Some(6)))
    );
    assert_eq!(
        ctx.distinct_id_state("attach-owner").await,
        Some((owner, false, Some(0)))
    );

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn attach_to_a_dead_person_attaches_nothing() {
    let ctx = TestContext::new().await;
    let corpse = ctx.insert_tombstoned_person(uuid::Uuid::new_v4(), 3).await;

    let outcomes = ctx
        .storage
        .attach_distinct_ids(ctx.team_id, corpse, &["attach-corpse".to_string()])
        .await
        .expect("attach should succeed");

    assert!(outcomes.is_empty());
    assert_eq!(ctx.distinct_id_state("attach-corpse").await, None);

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn attach_works_on_a_configured_table_set() {
    // Runs attach against the tmp namespace — a leftover hardcoded posthog_
    // table in its interpolated queries would pass silently on the default
    // set. Asserted through table-aware storage reads, not the raw-SQL
    // helpers above (those assume the default set).
    let ctx = TestContext::new_with_tables(common::tmp_tables()).await;
    let target = ctx
        .insert_person_with_distinct_id("tmp-attach-target")
        .await;

    let outcomes = ctx
        .storage
        .attach_distinct_ids(ctx.team_id, target, &["tmp-attach-fresh".to_string()])
        .await
        .expect("attach should succeed");

    assert_eq!(
        outcomes.get("tmp-attach-fresh"),
        Some(&AttachOutcome::Attached { version: 1 })
    );
    let key = (ctx.team_id, "tmp-attach-fresh".to_string());
    let resolved = ctx
        .storage
        .resolve_distinct_ids(std::slice::from_ref(&key))
        .await
        .expect("resolve should succeed");
    assert_eq!(resolved.get(&key).map(|p| p.id), Some(target));

    ctx.cleanup().await.ok();
}

#[tokio::test]
async fn attach_refuses_a_person_held_by_a_live_lifecycle_op() {
    // A deletion overlapping an attach: the delete saga's destructive
    // transaction sweeps the person's distinct id rows, then tombstones
    // the person row, then commits. An attach whose liveness join runs
    // mid-transaction still reads the live person version, so without a
    // further guard it inserts a mapping the sweep already missed — a
    // live distinct id pointing at a tombstoned person, which can never
    // resolve and never gets cleaned up. The saga commits its mark before
    // any destructive statement, so an attach that could land in that
    // window always observes the mark; refusing marked persons closes it.
    let ctx = TestContext::new().await;
    let victim = ctx.insert_person_with_distinct_id("marked-victim").await;

    // The saga's claim, committed before the fence and the destructive TX.
    let op_id = uuid::Uuid::now_v7();
    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, lease_expires_at, request) \
         VALUES ($1, 'delete', $2, 'marked', now() + interval '1 hour', '{}'::jsonb)",
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("seed op row");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'marked')",
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .bind(victim)
    .execute(&ctx.pool)
    .await
    .expect("seed mark row");

    // The destructive transaction, mid-flight: distinct ids swept, person
    // not yet tombstoned, nothing committed.
    let mut destroying_tx = ctx.pool.begin().await.expect("begin destroying tx");
    sqlx::query("UPDATE posthog_persondistinctid SET is_deleted = true, version = COALESCE(version, 0) + 1 WHERE team_id = $1 AND person_id = $2")
        .bind(ctx.team_id as i32)
        .bind(victim)
        .execute(&mut *destroying_tx)
        .await
        .expect("sweep distinct ids");

    // The overlapping attach must refuse: the person is mark-held.
    let outcomes = ctx
        .storage
        .attach_distinct_ids(ctx.team_id, victim, &["zombie-did".to_string()])
        .await
        .expect("attach call succeeds");
    assert!(
        outcomes.is_empty(),
        "attach must not touch a mark-held person, got {outcomes:?}"
    );

    // The deletion finishes.
    sqlx::query("UPDATE posthog_person SET is_deleted = true, version = COALESCE(version, 0) + 1 WHERE team_id = $1 AND id = $2")
        .bind(ctx.team_id as i32)
        .bind(victim)
        .execute(&mut *destroying_tx)
        .await
        .expect("tombstone person");
    destroying_tx.commit().await.expect("commit deletion");

    // No zombie: nothing maps the distinct id to the dead person.
    assert_eq!(ctx.distinct_id_state("zombie-did").await, None);

    sqlx::query("DELETE FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .execute(&ctx.pool)
        .await
        .expect("cleanup op");
    ctx.cleanup().await.ok();
}
