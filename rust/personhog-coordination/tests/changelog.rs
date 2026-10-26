mod common;

use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::Duration;

use personhog_coordination::changelog::{load_changelog_config, watch_changelog_config_loop};
use personhog_coordination::types::{ChangelogConfig, Generation};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use common::{store_at, test_store, FlakyProxy, ETCD_ENDPOINT};

#[tokio::test]
async fn a_second_seed_is_refused() {
    let store = test_store("changelog-seed").await;
    assert!(store
        .seed_changelog_config("personhog_updates_64", 64, "personhog-writer")
        .await
        .unwrap());
    assert!(!store
        .seed_changelog_config("personhog_updates_128", 128, "other-writer")
        .await
        .unwrap());
    let config = store.get_changelog_config().await.unwrap().unwrap();
    assert_eq!(
        (
            config.topic.as_str(),
            config.partitions,
            config.epoch,
            config.writer_group.as_str()
        ),
        ("personhog_updates_64", 64, 1, "personhog-writer")
    );
}

#[tokio::test]
async fn boot_polls_until_the_config_is_seeded() {
    let store = test_store("changelog-boot").await;
    let seeder = Arc::clone(&store);
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        seeder
            .seed_changelog_config("personhog_updates_64", 64, "personhog-writer")
            .await
            .unwrap();
    });
    let loaded = tokio::time::timeout(
        Duration::from_secs(5),
        load_changelog_config(&store, Duration::from_millis(20)),
    )
    .await
    .expect("boot polls until the config is seeded")
    .unwrap();
    assert_eq!((loaded.partitions, loaded.epoch), (64, 1));
}

/// What a loop starts from before it has adopted anything.
fn nothing_adopted() -> ChangelogConfig {
    ChangelogConfig {
        epoch: 0,
        ..ChangelogConfig::new("unadopted", 0)
    }
}

async fn next_adopted(rx: &mut mpsc::UnboundedReceiver<ChangelogConfig>) -> ChangelogConfig {
    tokio::time::timeout(Duration::from_secs(5), rx.recv())
        .await
        .expect("a config is adopted")
        .expect("the loop is alive")
}

#[tokio::test]
async fn the_watch_delivers_newer_epochs_and_retires_but_nothing_stale() {
    let store = test_store("changelog-watch").await;
    store
        .seed_changelog_config("personhog_updates_64", 64, "personhog-writer")
        .await
        .unwrap();

    let (tx, mut rx) = mpsc::unbounded_channel();
    let cancel = CancellationToken::new();
    let loop_store = Arc::clone(&store);
    let loop_cancel = cancel.clone();
    tokio::spawn(async move {
        watch_changelog_config_loop(
            loop_store,
            nothing_adopted(),
            Duration::from_secs(30),
            loop_cancel,
            |c| {
                tx.send(c.clone()).unwrap();
                ControlFlow::Continue(())
            },
        )
        .await;
    });

    assert_eq!(next_adopted(&mut rx).await.epoch, 1);

    let flipped = ChangelogConfig {
        topic: "personhog_updates_128".into(),
        partitions: 128,
        epoch: 2,
        writer_group: String::new(),
        retire_groups: vec![],
        draining: Vec::new(),
    };
    store.put_changelog_config(&flipped).await.unwrap();
    assert_eq!(next_adopted(&mut rx).await, flipped);

    store.put_changelog_config(&flipped).await.unwrap();
    store
        .put_changelog_config(&ChangelogConfig {
            epoch: 1,
            ..flipped.clone()
        })
        .await
        .unwrap();
    let newer = ChangelogConfig {
        epoch: 3,
        draining: vec![Generation {
            topic: "personhog_updates_128".into(),
            partitions: 128,
            epoch: 2,
        }],
        ..flipped.clone()
    };
    store.put_changelog_config(&newer).await.unwrap();
    assert_eq!(next_adopted(&mut rx).await, newer);

    // A retire keeps the epoch and only shrinks `draining`.
    let retired = ChangelogConfig {
        draining: Vec::new(),
        ..newer.clone()
    };
    store.put_changelog_config(&retired).await.unwrap();
    assert_eq!(next_adopted(&mut rx).await, retired);
    // The pre-retire object arriving late is older, not a new generation.
    store.put_changelog_config(&newer).await.unwrap();
    store.put_changelog_config(&retired).await.unwrap();
    // Deliveries keep revision order, so the next one proves the stale writes were dropped.
    let sentinel = ChangelogConfig {
        epoch: 4,
        ..retired.clone()
    };
    store.put_changelog_config(&sentinel).await.unwrap();
    assert_eq!(next_adopted(&mut rx).await, sentinel);

    cancel.cancel();
}

#[tokio::test]
async fn a_severed_watch_still_adopts_the_flip_through_reconcile() {
    let proxy = FlakyProxy::start("127.0.0.1:2379").await;
    let prefix = format!("/test-changelog-sever-{}/", uuid::Uuid::new_v4());
    let watched = store_at(&proxy.endpoint, &prefix).await;
    let direct = store_at(ETCD_ENDPOINT, &prefix).await;
    direct
        .seed_changelog_config("personhog_updates_64", 64, "personhog-writer")
        .await
        .unwrap();

    let (tx, mut rx) = mpsc::unbounded_channel();
    let cancel = CancellationToken::new();
    let loop_cancel = cancel.clone();
    tokio::spawn(async move {
        watch_changelog_config_loop(
            watched,
            nothing_adopted(),
            Duration::from_millis(300),
            loop_cancel,
            |c| {
                tx.send(c.epoch).unwrap();
                ControlFlow::Continue(())
            },
        )
        .await;
    });
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(5), rx.recv())
            .await
            .unwrap(),
        Some(1)
    );

    proxy.set_blackholed(true);
    proxy.sever();
    direct
        .put_changelog_config(&ChangelogConfig {
            topic: "personhog_updates_128".into(),
            partitions: 128,
            epoch: 2,
            writer_group: String::new(),
            retire_groups: vec![],
            draining: Vec::new(),
        })
        .await
        .unwrap();
    proxy.set_blackholed(false);

    assert_eq!(
        tokio::time::timeout(Duration::from_secs(10), rx.recv())
            .await
            .expect("the flip is adopted after the stream heals"),
        Some(2)
    );
    cancel.cancel();
}
