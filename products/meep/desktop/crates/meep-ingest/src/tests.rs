use super::*;
use anyhow::Result;
use meep_topic::Watch;

fn event() -> Event {
    Event {
        connection: "slack".into(),
        kind: "channel".into(),
        external_id: "1".into(),
        channel: "#rail".into(),
        thread_hint: None,
        author: "Mia".into(),
        at: DateTime::UNIX_EPOCH,
        text: "\n Design   NOTES \nbody".into(),
        attributes: Value::Null,
    }
}

#[test]
fn matches_every_watch_field_and_delivers_once_per_topic() -> Result<()> {
    let a = "00000000-0000-0000-0000-000000000001".parse()?;
    let b = "00000000-0000-0000-0000-000000000002".parse()?;
    let w = Watch {
        id: "00000000-0000-0000-0000-000000000003".parse()?,
        connection: "slack".into(),
        kind: "channel".into(),
        key: "#rail".into(),
        label: "Rail".into(),
    };
    let binding = |id: &str, watches| RoutineBinding {
        id: id.into(),
        watches,
        name: id.into(),
        backend: "posthog".into(),
        external_id: id.into(),
        trigger: "Source event".into(),
    };
    let watchers = [
        (a, binding("one", vec![w.clone(), w.clone()])),
        (b, binding("two", vec![w.clone()])),
        (a, binding("one", vec![w.clone()])),
        (a, binding("three", vec![w])),
    ];
    let mut e = event();
    assert_eq!(
        route(&e, &watchers),
        [(a, "one".into()), (b, "two".into()), (a, "three".into())]
    );
    e.kind = "label".into();
    assert!(route(&e, &watchers).is_empty());
    e.kind = "channel".into();
    e.channel = "#other".into();
    assert!(route(&e, &watchers).is_empty());
    e.channel = "#rail".into();
    e.connection = "other".into();
    assert!(route(&e, &watchers).is_empty());
    Ok(())
}

#[test]
fn both_seen_stores_scope_keys_to_the_account_and_sqlite_survives_restart() -> Result<()> {
    fn exercise<S: SeenStore>(mut deduper: Deduper<S>) -> Result<()> {
        let mut e = event();
        assert!(!deduper.seen(&e)?);
        assert!(deduper.record(&e)?);
        assert!(deduper.seen(&e)?);
        e.text = "edited".into();
        assert!(!deduper.record(&e)?);
        e.connection = "another-account".into();
        assert!(deduper.record(&e)?);
        Ok(())
    }
    exercise(Deduper::new(MemorySeenStore::default()))?;
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("seen.sqlite");
    exercise(Deduper::new(StoreSeenStore::new(Connection::open(&path)?)?))?;
    assert!(Deduper::new(StoreSeenStore::new(Connection::open(path)?)?).seen(&event())?);
    Ok(())
}
