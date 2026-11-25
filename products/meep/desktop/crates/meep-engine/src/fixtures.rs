//! A self-contained version of the six-topic prototype.
use super::*;
use crate::fixture_flows::*;
use chrono::TimeDelta;
use meep_ingest::{Event, FixtureConnector};
use serde_json::{Value, json};

/// Opens the prototype with a real clock, expired Slack account and scheduled Quill handoff.
pub async fn demo() -> Result<Engine> {
    demo_with_clock(Arc::new(SystemClock)).await
}

/// Opens the same world on a host-supplied clock for deterministic demos and tests.
pub async fn demo_with_clock(clock: Arc<dyn Clock>) -> Result<Engine> {
    let now = clock.now();
    let mut agent = FixtureAgent::default();
    agent.script(
        "Check rail contrast in dark themes",
        Script {
            delay: TimeDelta::seconds(15),
            progress: "Checking 2 of 9 themes".into(),
            outcome: RunState::Done {
                result: "All nine themes pass.".into(),
            },
        },
    );
    let engine = Engine::with_backends(
        Arc::new(crate::MemoryStore::default()),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(FixtureFlows)],
        Limits {
            max_hops: 4,
            max_runs_per_hour: 60,
        },
        Arc::new(agent),
        Arc::new(FixtureSorter),
        clock,
    )
    .await?;
    let mut state = meep_topic::fixtures::new_web()?;
    let web = state.topic.id;
    let quill = state
        .threads
        .iter()
        .flat_map(|t| &t.messages)
        .find_map(|m| match m.reply_target() {
            Some(Source::Topic(t)) => Some(t),
            _ => None,
        })
        .context("missing fixture sender")?;
    let pushback = state
        .threads
        .iter()
        .find(|t| t.subject == "Pushback on five rail items")
        .context("missing pushback thread")?
        .key
        .clone();
    state.add_rule(
        Rule {
            id: id(),
            text: "Skip Slack lunch plans.".into(),
            effect: RuleEffect::Skip(Matcher {
                connection: Some("slack".into()),
                ..Default::default()
            }),
            from_task: None,
            created_at: now,
        },
        now,
    )?;
    engine.install(state, vec![], None).await?;
    for (name, mission, title, fact) in [
        (
            "Shy Alter",
            "Anything that belongs to no other topic.",
            "Write the Q1 planning notes",
            "Prefers written updates to meetings",
        ),
        (
            "Rail Redesign",
            "Ship the new navigation rail to everyone.",
            "Check rail contrast in dark themes",
            "Rail collapses under 900 px",
        ),
        (
            "Canvas loadtime",
            "Keep canvas load under two seconds.",
            "Find what slowed canvas load",
            "Production peaks at 460 users",
        ),
        (
            "Canvas adoption",
            "Get more teams using canvas each week.",
            "Interview two teams that stopped using canvas",
            "212 weekly canvas teams",
        ),
        (
            "Quill migration",
            "Move every screen to the Quill components.",
            "Migrate Settings screens",
            "121 old uses left",
        ),
    ] {
        let mut topic = Topic::new(
            if name == "Quill migration" {
                quill
            } else {
                id()
            },
            name,
            now,
        );
        topic.mission = mission.into();
        let mut state = TopicState::new(topic);
        state.add_task(id(), title, Actor::User, None, now)?;
        state.add_fact(
            Fact {
                id: id(),
                text: fact.into(),
                provenance: Provenance {
                    origin: None,
                    author: name.into(),
                    via: "Prototype".into(),
                    at: now,
                    thread: None,
                },
                superseded_by: None,
                invalidated_by: None,
                withdrawn_at: None,
            },
            now,
        )?;
        if name == "Canvas loadtime" {
            let task = id();
            state.add_task(
                task,
                "Raise the load test to 500 users",
                Actor::Agent,
                None,
                now,
            )?;
            state.start(task, "Compared traffic peaks", now)?;
            state.submit(
                task,
                Action {
                    depends_on_facts: None,
                    kind: ActionKind("load-test-change".into()),
                    label: "Raise to 500".into(),
                    done_label: "Load test raised to 500 users".into(),
                    payload: json!({"users":500}),
                },
                "The test uses 200 users. Production peaked at 460 this week.",
                None,
                now,
            )?;
        }
        engine.install(state, vec![], None).await?;
    }
    let since = now - TimeDelta::hours(1);
    let slack =
        |n: i64, author: &str, text: &str, thread_hint: Option<String>, attributes: Value| Event {
            connection: "slack".into(),
            kind: "channel".into(),
            external_id: format!("missed-{n}"),
            channel: "#new-web".into(),
            author: author.into(),
            text: text.into(),
            at: since + TimeDelta::minutes(n),
            thread_hint,
            attributes,
        };
    let missed = vec![
        slack(
            11,
            "Mia",
            "Agree with Adam. Dashboards should be one click.",
            Some(pushback),
            Value::Null,
        ),
        slack(
            20,
            "Adam",
            "Notes from review: keep five items, move Settings to the bottom.",
            None,
            json!({"fact":"Settings moves to the bottom of the rail"}),
        ),
        slack(
            31,
            "Mia",
            "Lunch in #new-web: pizza or sushi?",
            None,
            json!({"skip":true}),
        ),
        slack(
            32,
            "Adam",
            "Lunch in #new-web: sushi gets my vote.",
            None,
            json!({"skip":true}),
        ),
    ];
    let github = Event {
        connection: "github".into(),
        kind: "label".into(),
        external_id: "pr-2304".into(),
        channel: "new-web".into(),
        thread_hint: Some("new-web/pr-2304".into()),
        author: "GitHub".into(),
        text: "PR 2304 opened: Menu, Popover, Tabs".into(),
        at: since,
        attributes: Value::Null,
    };
    let posthog = Event {
        connection: "posthog".into(),
        kind: "insight".into(),
        external_id: "page-time".into(),
        channel: "Time to reach a page".into(),
        thread_hint: Some("new-web/page-time".into()),
        author: "PostHog".into(),
        text: "Time to reach a page is within the guardrail.".into(),
        at: since,
        attributes: json!({"fact":"Time to reach a page is within ±1%."}),
    };
    for (service, label, events) in [
        ("slack", "Slack", missed),
        ("github", "GitHub", vec![github]),
        ("posthog", "PostHog", vec![posthog]),
    ] {
        let health = if service == "slack" {
            Health::Expired {
                since,
                detail: "Slack sign-in expired".into(),
            }
        } else {
            Health::Ok { checked_at: now }
        };
        engine.add_connection(Connection {
            unrouted: 0,
            id: service.into(),
            kind: service.into(),
            label: label.into(),
            account: "Demo".into(),
            health,
            grants: vec![web],
        })?;
        engine.attach_connector(Arc::new(FixtureConnector::new(service, events)));
    }
    for (topic, key, name, trigger) in [
        (
            web,
            "finish-migration",
            "Finish the migration",
            "When a message arrives",
        ),
        (
            quill,
            "tooltip-ready",
            "Report Tooltip readiness",
            "Scheduled",
        ),
    ] {
        let mut binding = fixture_binding(key);
        binding.name = name.into();
        binding.trigger = trigger.into();
        engine.bind_routine(topic, binding).await?;
    }
    Ok(engine)
}
