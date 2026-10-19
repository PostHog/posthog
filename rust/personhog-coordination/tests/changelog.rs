mod common;

use common::test_store;

#[tokio::test]
async fn a_second_seed_is_refused() {
    let store = test_store("changelog-seed").await;
    assert!(store
        .seed_changelog_config("personhog_updates_64", 64, vec![])
        .await
        .unwrap());
    assert!(!store
        .seed_changelog_config("personhog_updates_128", 128, vec![])
        .await
        .unwrap());
    let config = store.get_changelog_config().await.unwrap().unwrap();
    assert_eq!(
        (config.topic.as_str(), config.partitions, config.epoch),
        ("personhog_updates_64", 64, 1)
    );
}
