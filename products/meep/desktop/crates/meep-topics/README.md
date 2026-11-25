# meep-topics

A topic is a subject you want to return to. It can start with an idea, such as “Could we make the first day easier for new people?” It can also be a project, a recurring question such as “What needs my attention this week?”, or a record of your impact.

A topic needs only a name. You can add a description, notes, and other files as the topic develops. The ID stays the same when you change the name. An app can use this ID to connect a conversation, view, or routine to the topic.

## Start with an idea

This example saves a thought as a topic. Later, the user gives it a shorter name and adds a note. The test uses a temporary directory. In an app, open the same permanent directory on each start.

```rust
use meep_topics::{TopicInfo, Topics};

# fn main() -> anyhow::Result<()> {
let root = tempfile::tempdir()?;
let topics = Topics::open(root.path())?;
let idea = topics.create(TopicInfo::new("Could we make the first day easier for new people?"))?;
let id = idea.id();

let topics = Topics::open(root.path())?;
let topic = topics.get(id)?;
topic.update(|info| {
    info.description = info.name.clone();
    info.name = "First day at work".into();
    Ok(())
})?;
topic.files()?.write("notes.md", "Ask the next new starter about the first hour.")?;

assert_eq!(topic.id(), id);
assert_eq!(topic.info()?.description, "Could we make the first day easier for new people?");
# Ok(())
# }
```

## Storage and access

The host selects a private directory for the catalog. Each topic has a directory for ordinary files at `<catalog>/<id>/files/`. Save the topic ID as a string or a Serde value. Use `Topics::list` to find saved topics.

Use `Topic::update` to edit the latest name, description, or metadata. Concurrent edits to one topic use a file lock. An error from the edit function leaves the previous record in place.

The app decides who can open a topic. Pass relative file operations through the handle from `Topic::files`. This handle limits those operations to the file directory. A separate process needs its own file access controls. A cloud task needs a file transfer service or a mounted volume to use files from the desktop.
