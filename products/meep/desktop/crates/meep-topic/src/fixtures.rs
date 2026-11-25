//! Deterministic, self-contained data from the Meep prototype.

use crate::*;
use chrono::{DateTime, TimeDelta, Utc};
use uuid::Uuid;

fn id<T: From<Uuid>>(n: u128) -> T {
    Uuid::from_u128(n).into()
}

// The prototype's week includes Monday, November 17, 2025.
fn nov(day: i64, hour: i64, minute: i64) -> DateTime<Utc> {
    DateTime::UNIX_EPOCH
        + TimeDelta::seconds(1_761_955_200)
        + TimeDelta::days(day - 1)
        + TimeDelta::hours(hour)
        + TimeDelta::minutes(minute)
}

fn connection(service: &str, channel: &str) -> Source {
    Source::Connection {
        connection: service.into(),
        channel: channel.into(),
    }
}

fn receive(
    state: &mut TopicState,
    thread: u128,
    n: u128,
    source: Source,
    author: &str,
    text: &str,
    at: DateTime<Utc>,
) -> Result<(), TopicError> {
    let message = Message {
        id: id(1000 + n),
        producer: if source == Source::User {
            Producer::User
        } else {
            Producer::System
        },
        origin: Some(source.into_origin(author.into(), at, None)),
        author: author.into(),
        at,
        text: text.into(),
        external_id: None,
    };
    state.receive(message, format!("new-web/i{thread}"), id(100 + thread), at)?;
    Ok(())
}

fn handle(
    state: &mut TopicState,
    n: u128,
    summary: &str,
    outcomes: Vec<Outcome>,
    at: DateTime<Utc>,
) -> Result<(), TopicError> {
    state.sort(
        id(100 + n),
        Decision::Handle {
            summary: summary.into(),
            outcomes,
        },
        at,
    )?;
    Ok(())
}

fn fact(n: u128, text: &str, author: &str, via: &str, day: i64, thread: Option<u128>) -> Fact {
    Fact {
        id: id(300 + n),
        text: text.into(),
        provenance: Provenance {
            origin: None,
            author: author.into(),
            via: via.into(),
            at: nov(day, 0, 0),
            thread: thread.map(|n| id(100 + n)),
        },
        superseded_by: None,
        invalidated_by: None,
        withdrawn_at: None,
    }
}

fn log(day: i64, text: &str) -> LogEntry {
    LogEntry {
        origin: None,
        at: nov(day, 0, 0),
        text: text.into(),
    }
}

/// Builds the New web topic, including its seven conversations and five board tasks.
/// All timestamps and IDs are fixed, and all referenced facts and tasks belong to the fixture.
pub fn new_web() -> Result<TopicState, TopicError> {
    let mut topic = Topic::new(id(1), "New web", nov(1, 0, 0));
    topic.mission = "Simplify the new web navigation.".into();
    topic.goals = vec![
        Goal {
            id: id(501),
            text: "Increase WAU by 10%".into(),
            progress: Some(Progress::Target {
                current: 3.1,
                target: 10.0,
                unit: "%".into(),
            }),
        },
        Goal {
            id: id(502),
            text: "Keep time to reach a page within ±1%".into(),
            progress: Some(Progress::Guardrail {
                current: 0.4,
                low: -1.0,
                high: 1.0,
                unit: "%".into(),
            }),
        },
    ];
    topic.rules = vec![
        Rule {
            id: id(401),
            text: "Never post in #general.".into(),
            effect: RuleEffect::Deny(ActionKind("slack-post-general".into())),
            from_task: None,
            created_at: topic.created_at,
        },
        Rule {
            id: id(402),
            text: "Ignore dependency updates.".into(),
            effect: RuleEffect::Skip(Matcher {
                connection: Some("github".into()),
                ..Default::default()
            }),
            from_task: None,
            created_at: topic.created_at,
        },
    ];
    *topic.default_watches_mut() = [
        (601, "posthog", "flag", "new-web-nav", "Flag new-web-nav"),
        (
            602,
            "posthog",
            "insight",
            "Time to reach a page",
            "Insight \"Time to reach a page\"",
        ),
        (603, "slack", "channel", "#new-web", "#new-web"),
        (604, "github", "label", "new-web", "PRs labelled new-web"),
    ]
    .into_iter()
    .map(|(n, connection, kind, key, label)| Watch {
        id: id(n),
        connection: connection.into(),
        kind: kind.into(),
        key: key.into(),
        label: label.into(),
    })
    .collect();
    let mut state = TopicState::new(topic);
    let slack = connection("slack", "#new-web");

    let at = nov(9, 12, 1);
    receive(
        &mut state,
        7,
        9,
        slack.clone(),
        "Slack",
        "Who wants tacos?",
        at,
    )?;
    state.sort(
        id(107),
        Decision::Skip {
            reason: "Not about navigation.".into(),
            rule: None,
        },
        at,
    )?;

    let at = nov(10, 3, 12);
    receive(
        &mut state,
        6,
        8,
        connection("github", "new-web"),
        "GitHub",
        "Automated dependency update merged.",
        at,
    )?;
    state.sort(
        id(106),
        Decision::Skip {
            reason: "Skipped by rule: ignore dependency updates.".into(),
            rule: Some(id(402)),
        },
        at,
    )?;

    let at = nov(10, 18, 40);
    receive(
        &mut state,
        5,
        7,
        Source::User,
        "You",
        "Forwarded from your notes.",
        at,
    )?;
    state.add_task(
        id(202),
        "Look at nav usage before Friday",
        Actor::User,
        Some(id(105)),
        at,
    )?;
    handle(
        &mut state,
        5,
        "Added to To do.",
        vec![Outcome::Task(id(202))],
        at,
    )?;

    let at = nov(11, 7, 0);
    receive(
        &mut state,
        4,
        6,
        connection("posthog", "WAU"),
        "PostHog",
        "Weekly active users fell from 18,420 to 17,870.",
        at,
    )?;
    state.add_fact(
        fact(4, "WAU 17,870 on Nov 11", "Inbox", "PostHog", 11, Some(4)),
        at,
    )?;
    handle(
        &mut state,
        4,
        "Inside normal weekly variation. Noted, no task.",
        vec![Outcome::Fact(id(304))],
        at,
    )?;
    state.add_task(
        id(206),
        "Write the beta release note",
        Actor::User,
        None,
        at,
    )?;
    state.start(id(206), "Writing", at)?;
    state.complete(id(206), "Posted. Checked that it is live.", at)?;

    let at = nov(12, 8, 30);
    receive(
        &mut state,
        2,
        4,
        connection("scout", "recordings"),
        "Scout",
        "In 14 of 60 session recordings, people opened the pinned menu and closed it without choosing anything.",
        at,
    )?;
    state.add_task(
        id(201),
        "Audit the pinned pages copy",
        Actor::Inbox(id(102)),
        Some(id(102)),
        at,
    )?;
    state.add_task(
        id(204),
        "Rename \"Pinned\" to \"Shortcuts\"",
        Actor::Routine("Copy check".into()),
        Some(id(102)),
        at,
    )?;
    handle(
        &mut state,
        2,
        "14 of 60 sessions opened the pinned menu and left. Added two tasks.",
        vec![Outcome::Task(id(201)), Outcome::Task(id(204))],
        at,
    )?;

    let at = nov(12, 14, 20);
    receive(
        &mut state,
        3,
        5,
        Source::Topic(id(2)),
        "@Quill migration",
        "The new navigation still uses five components from the old library: Menu, Popover, Tabs, Tooltip and Badge.",
        at,
    )?;
    state.add_task(
        id(203),
        "Migrate 5 components",
        Actor::Inbox(id(103)),
        Some(id(103)),
        at,
    )?;
    state.add_fact(
        fact(
            3,
            "5 components left to migrate",
            "Inbox",
            "@Quill migration",
            12,
            Some(3),
        ),
        at,
    )?;
    handle(
        &mut state,
        3,
        "Menu, Popover, Tabs, Tooltip and Badge. Started on them.",
        vec![Outcome::Task(id(203)), Outcome::Fact(id(303))],
        at,
    )?;
    state.start(
        id(203),
        "Menu, Popover and Tabs migrated. PR 2304 open.",
        nov(13, 0, 0),
    )?;

    let at = nov(18, 0, 0);
    state.add_fact(
        fact(2, "All areas should have pinned", "Adam", "Meep", 18, None),
        at,
    )?;
    state.progress(id(203), "Tooltip, 4 of 5", at)?;
    state.start(id(204), "Checking copy", at)?;
    state.submit(
        id(204),
        Action {
            depends_on_facts: None,
            kind: ActionKind("copy-change".into()),
            label: "Merge PR 2310".into(),
            done_label: "Merged PR 2310".into(),
            payload: serde_json::json!({ "pr": 2310 }),
        },
        "Changed 6 strings in 3 files. PR 2310 passes all checks.",
        None,
        at,
    )?;

    let at = nov(19, 10, 2);
    state.add_fact(
        fact(
            1,
            "We only have 5 rail items, no more",
            "Shy",
            "Slack",
            19,
            None,
        ),
        at,
    )?;
    receive(
        &mut state,
        1,
        1,
        slack.clone(),
        "Adam",
        "Five feels tight. Dashboards is where I live all day.",
        at,
    )?;
    receive(
        &mut state,
        1,
        2,
        slack.clone(),
        "Priya",
        "+1, can we get a sixth slot just for Dashboards?",
        nov(19, 10, 5),
    )?;
    let at = nov(19, 10, 11);
    receive(
        &mut state,
        1,
        3,
        slack,
        "Leo",
        "Same. Otherwise it is two clicks every time.",
        at,
    )?;
    state.sort(id(101), Decision::Ask {
        summary: "Three people want a sixth slot for Dashboards.".into(),
        reason: "This conflicts with a decision you made: the rail holds five items, no more. I can draft a reply that explains the limit and points to Shortcuts, but I won't speak for you in Slack without asking.".into(),
        suggestions: vec![
            Suggestion::DraftReply {
                draft: "We capped the rail at five so every item stays one click away. Dashboards is in Shortcuts by default, one click from anywhere. If that still feels slow after a week, tell me and we'll look at the numbers together.".into(),
                task_title: "Reply to the pushback in #new-web".into(),
            },
            Suggestion::MakeTask { title: "Decide on a sixth rail slot".into() }, Suggestion::Leave,
        ],
    }, at)?;

    // The captured inbox has editorial subjects and the board has worker-written logs.
    state.threads.sort_by_key(|t| t.id);
    for (thread, subject) in state.threads.iter_mut().zip([
        "Pushback on five rail items",
        "Users are confused by pinned pages",
        "Five components left to migrate",
        "WAU down 3% week over week",
        "Look at the nav usage data before Friday",
        "Dependency update merged",
        "Lunch order in #new-web",
    ]) {
        thread.subject = subject.into();
        thread.unseen = false;
    }
    state.topic.facts.sort_by_key(|f| f.id);
    state.tasks.sort_by_key(|t| t.id);
    for task in &mut state.tasks {
        task.log = match task.id.0.as_u128() {
            203 => vec![
                log(13, "Menu, Popover and Tabs migrated. PR 2304 open."),
                log(18, "Badge done. Working on Tooltip."),
            ],
            204 => vec![
                log(18, "Found 6 uses of \"Pinned\" in the navigation."),
                log(18, "Opened PR 2310. All checks pass."),
            ],
            206 => vec![log(11, "Posted. Checked that it is live.")],
            _ => vec![],
        };
    }
    Ok(state)
}
