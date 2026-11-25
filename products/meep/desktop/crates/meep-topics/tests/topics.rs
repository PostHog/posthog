use anyhow::{Result, bail};
use meep_topics::{TopicInfo, Topics};
use serde_json::json;
use std::fs;
use std::sync::Barrier;
use std::thread;

#[test]
fn a_topic_keeps_its_id_metadata_and_files_across_restarts() -> Result<()> {
    let root = tempfile::tempdir()?;
    let first = {
        let catalog = Topics::open(root.path())?;
        let mut info = TopicInfo::new("What helped people this week?");
        info.description = "Keep examples of changes that helped someone.".into();
        info.metadata.insert("period".into(), json!("weekly"));
        let topic = catalog.create(info)?;
        let files = topic.files()?;
        files.create_dir("notes")?;
        files.write("notes/task.bin", [0, 127, 255])?;
        topic.id()
    };

    let catalog = Topics::open(root.path())?;
    let topic = catalog.get(first.to_string().parse()?)?;
    let second = catalog.create(TopicInfo::new("What helped people this week?"))?;
    assert_ne!(first, second.id());
    assert!(!second.files()?.try_exists("notes/task.bin")?);
    topic.update(|info| {
        info.name = "My impact".into();
        Ok(())
    })?;
    let catalog = Topics::open(root.path())?;
    let reopened = catalog.get(first)?;
    assert_eq!(reopened.files()?.read("notes/task.bin")?, [0, 127, 255]);
    let all = catalog.list()?;
    assert_eq!(all.len(), 2);
    let (_, info) = all.iter().find(|(id, _)| *id == first).unwrap();
    assert_eq!(info.name, "My impact");
    assert_eq!(
        info.description,
        "Keep examples of changes that helped someone."
    );
    assert_eq!(info.metadata["period"], "weekly");
    Ok(())
}

#[test]
fn failed_edits_preserve_the_previous_record() -> Result<()> {
    let root = tempfile::tempdir()?;
    let catalog = Topics::open(root.path())?;
    assert!(catalog.create(TopicInfo::new("  ")).is_err());
    fs::create_dir(root.path().join(".new-interrupted"))?;
    assert!(catalog.list()?.is_empty());

    let saved = TopicInfo::new("Reports");
    let topic = catalog.create(saved.clone())?;
    let result = topic.update(|info| {
        info.metadata.insert("partial".into(), json!(true));
        bail!("Discard this edit")
    });
    assert!(result.is_err());
    assert!(
        topic
            .update(|info| {
                info.name.clear();
                Ok(())
            })
            .is_err()
    );
    assert_eq!(catalog.get(topic.id())?.info()?, saved);
    Ok(())
}

#[test]
fn separate_catalogs_keep_concurrent_edits() -> Result<()> {
    let root = tempfile::tempdir()?;
    let topic = Topics::open(root.path())?.create(TopicInfo::new("Shared"))?;
    let barrier = Barrier::new(4);
    let root = root.path();
    let id = topic.id();
    thread::scope(|scope| {
        for index in 0..4 {
            let barrier = &barrier;
            scope.spawn(move || {
                barrier.wait();
                let other = Topics::open(root).unwrap().get(id).unwrap();
                other
                    .update(|info| {
                        info.metadata.insert(index.to_string(), json!(index));
                        Ok(())
                    })
                    .unwrap();
            });
        }
    });
    assert_eq!(topic.info()?.metadata.len(), 4);
    Ok(())
}

#[test]
fn file_operations_stay_inside_the_selected_topic() -> Result<()> {
    let root = tempfile::tempdir()?;
    let catalog = Topics::open(root.path())?;
    let a = catalog.create(TopicInfo::new("A"))?;
    let b = catalog.create(TopicInfo::new("B"))?;
    b.files()?.write("note", "private")?;
    let files = a.files()?;
    assert!(files.read("../space.json").is_err());
    let other_note = root.path().join(b.id().to_string()).join("files/note");
    assert!(files.read(&other_note).is_err());
    #[cfg(unix)]
    {
        // Model a link that a separate native program placed in this directory.
        let link = root.path().join(a.id().to_string()).join("files/other");
        std::os::unix::fs::symlink(&other_note, link)?;
        assert!(files.read("other").is_err());
        assert!(files.write("other", "changed").is_err());
    }
    assert_eq!(b.files()?.read_to_string("note")?, "private");
    Ok(())
}

#[test]
fn an_existing_catalog_opens_with_the_same_ids_and_files() -> Result<()> {
    let root = tempfile::tempdir()?;
    let old_id = "d89edd53-8850-4dcc-a8c1-54bad48073f4";
    let directory = root.path().join(old_id);
    fs::create_dir_all(directory.join("files"))?;
    fs::write(directory.join("space.lock"), b"")?;
    fs::write(
        directory.join("space.json"),
        br#"{"name":"Notes","metadata":{"color":"blue"}}"#,
    )?;
    fs::write(directory.join("files/idea.md"), "Try this on Monday")?;

    let catalog = Topics::open(root.path())?;
    let topic = catalog.get(old_id.parse()?)?;
    assert!(topic.info()?.description.is_empty());
    topic.update(|info| {
        info.description = "Ideas for next week".into();
        Ok(())
    })?;
    let records = Topics::open(root.path())?.list()?;
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].0.to_string(), old_id);
    assert_eq!(records[0].1.metadata["color"], "blue");
    assert_eq!(records[0].1.description, "Ideas for next week");
    assert_eq!(
        topic.files()?.read_to_string("idea.md")?,
        "Try this on Monday"
    );
    Ok(())
}
