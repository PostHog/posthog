# meep-topic

A topic brings its inbox, task board, facts and rules together. The host supplies IDs and timestamps. Each successful command returns numbered changes. The same envelope can be applied on an offline replica and on the server.

```rust
use chrono::DateTime;
use meep_topic::{Command, Envelope, Topic, TopicState};

# fn main() -> Result<(), Box<dyn std::error::Error>> {
let now = DateTime::UNIX_EPOCH;
let topic = "00000000-0000-0000-0000-000000000001".parse()?;
let mut state = TopicState::new(Topic::new(topic, "New web", now));
let request = Envelope {
    id: "00000000-0000-0000-0000-000000000002".parse()?,
    topic,
    issued_at: now,
    command: Command::AddTask {

        id: "00000000-0000-0000-0000-000000000003".parse()?,
        title: "Review the pinned menu".into(),
    },
};
let changes = state.apply(&request)?;
assert_eq!(changes[0].seq, 1);
assert_eq!(state.tasks[0].title, "Review the pinned menu");
# Ok(())
# }
```

`Envelope::create` builds the initial state for a `CreateTopic` request. The `fixtures` feature supplies the New web inbox and board through `fixtures::new_web`.

Chat enters Sorting during optimistic apply. Model decisions arrive as server revisions. Skip matchers carry optional connection and channel IDs, and the rule text describes its meaning.
