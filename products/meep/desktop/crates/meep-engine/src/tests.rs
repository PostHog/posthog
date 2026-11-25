use super::*;
use anyhow::Result;
use chrono::TimeDelta;
use meep_ingest::{Event, FixtureConnector};
use meep_store::Connection as Database;
use serde_json::{Value, json};

mod inbox;
mod observations;
mod persistence;
mod routines;
mod workers;

fn limits() -> Limits {
    Limits {
        max_hops: 2,
        max_runs_per_hour: 12,
    }
}

async fn world() -> Result<(Engine, Arc<ManualClock>)> {
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = Engine::with_backends(
        Arc::new(crate::MemoryStore::default()),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(crate::fixture_flows::FixtureFlows)],
        limits(),
        Arc::new(FixtureAgent::default()),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    Ok((engine, clock))
}

fn watch() -> Watch {
    Watch {
        id: id(),
        connection: "slack".into(),
        kind: "channel".into(),
        key: "#rail".into(),
        label: "Rail".into(),
    }
}

async fn watching(engine: &Engine, name: &str) -> Result<TopicId> {
    let (topic, _) = engine.create_topic(name, "Ship the rail").await?;
    engine.set_watch(topic, vec![watch()]).await?;
    Ok(topic)
}

fn event(key: &str, text: &str, attributes: Value) -> Event {
    Event {
        connection: "slack".into(),
        kind: "channel".into(),
        external_id: key.into(),
        channel: "#rail".into(),
        thread_hint: Some(key.into()),
        author: "Mia".into(),
        at: DateTime::UNIX_EPOCH,
        text: text.into(),
        attributes,
    }
}

fn draft(state: &TopicState) -> Suggestion {
    let ThreadState::NeedsYou { suggestions, .. } =
        &state.threads.last().expect("conversation").state
    else {
        panic!("expected a decision")
    };
    suggestions[0].clone()
}

fn action() -> Action {
    Action {
        depends_on_facts: None,
        kind: ActionKind("slack-reply".into()),
        label: "Send reply".into(),
        done_label: "Reply sent in #rail".into(),
        payload: json!({"channel":"#rail"}),
    }
}

fn scripted() -> FixtureAgent {
    let mut agent = FixtureAgent::default();
    agent.script(
        "Draft",
        Script {
            delay: TimeDelta::seconds(5),
            progress: "Reading the thread".into(),
            outcome: RunState::Submitted {
                action: action(),
                result: "Reply ready".into(),
                draft: Some("Five items".into()),
            },
        },
    );
    agent
}

fn envelope(topic: TopicId, command: Command) -> Envelope {
    Envelope {
        id: id(),
        topic,
        issued_at: DateTime::UNIX_EPOCH,
        command,
    }
}
