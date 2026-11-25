use super::*;
use chrono::{DateTime, Duration, Utc};

fn connection(channel: &str) -> Source {
    Source::Connection {
        connection: "posthog".into(),
        channel: channel.into(),
    }
}

fn observed(
    state: &mut TopicState,
    subject: &str,
    src: Source,
    at: DateTime<Utc>,
    messages: &[(&str, &str)],
) -> Result<ThreadId> {
    let id = ThreadId(Uuid::new_v4());
    for (i, (author, text)) in messages.iter().enumerate() {
        let at = at + Duration::minutes(i as i64 * 4);
        state.receive(
            Message {
                id: MessageId(if src == Source::User && i == 0 {
                    id.0
                } else {
                    Uuid::new_v4()
                }),
                producer: if src == Source::User {
                    Producer::User
                } else {
                    Producer::System
                },
                origin: Some(src.clone().into_origin((*author).into(), at, None)),
                author: (*author).into(),
                at,
                text: (*text).into(),
                external_id: None,
            },
            id.to_string(),
            id,
            at,
        )?;
    }
    state
        .threads
        .last_mut()
        .context("missing conversation")?
        .subject = subject.into();
    Ok(id)
}

fn take(state: &mut TopicState, id: ThreadId, summary: &str, outcomes: Vec<Outcome>) -> Result<()> {
    let at = state
        .threads
        .iter()
        .find(|t| t.id == id)
        .unwrap()
        .updated_at;
    state.sort(
        id,
        Decision::Handle {
            summary: summary.into(),
            outcomes,
        },
        at,
    )?;
    Ok(())
}

fn ask(
    state: &mut TopicState,
    id: ThreadId,
    summary: &str,
    reason: &str,
    suggestion: Suggestion,
) -> Result<()> {
    let at = state
        .threads
        .iter()
        .find(|t| t.id == id)
        .unwrap()
        .updated_at;
    state.sort(
        id,
        Decision::Ask {
            summary: summary.into(),
            reason: reason.into(),
            suggestions: vec![suggestion, Suggestion::Leave],
        },
        at,
    )?;
    Ok(())
}

fn remember(state: &mut TopicState, id: ThreadId, text: &str, via: &str) -> Result<FactId> {
    let fact = FactId(Uuid::new_v4());
    let m = state
        .threads
        .iter()
        .find(|t| t.id == id)
        .unwrap()
        .messages
        .last()
        .unwrap();
    let at = m.at;
    state.add_fact(
        Fact {
            id: fact,
            text: text.into(),
            provenance: Provenance {
                origin: None,
                author: m.author.clone(),
                via: via.into(),
                thread: Some(id),
                at,
            },
            superseded_by: None,
            invalidated_by: None,
            withdrawn_at: None,
        },
        at,
    )?;
    Ok(fact)
}

fn account() -> Result<(Lab, TopicId, ThreadId, ThreadId, TaskId)> {
    let now = Utc::now();
    let ago = |hours| now - Duration::hours(hours);
    let topic = |key, name, mission: &str| {
        let mut t = Topic::new(TopicId(Uuid::from_u128(key)), name, ago(720));
        t.mission = mission.into();
        TopicState::new(t)
    };
    let mut me = topic(1, "Me", "Keep track of commitments and follow-ups.");
    // Everything that reached Me so far was skipped: the inbox's clear state.
    for (subject, text, reason, hours) in [
        (
            "Weekly #random digest",
            "Lunch spots, a plant photo and the Friday quiz answers.",
            "Not about your commitments or follow-ups.",
            5,
        ),
        (
            "Office closed on Thursday",
            "The office is closed for maintenance; work from home.",
            "An announcement with nothing for you to do.",
            30,
        ),
    ] {
        let thread = observed(
            &mut me,
            subject,
            connection("slack"),
            ago(hours),
            &[("Slack", text)],
        )?;
        me.sort(
            thread,
            Decision::Skip {
                reason: reason.into(),
                rule: None,
            },
            ago(hours),
        )?;
    }
    for t in me.threads.iter_mut() {
        t.unseen = false;
    }
    let mut web = topic(
        2,
        "New web navigation",
        "Make it easier to find saved work from the sidebar.",
    );
    web.scouts.push(navigation_scout());
    let mut pr = topic(3, "PR reviews", "Keep the web team’s review queue moving.");
    let mut checkout = topic(
        4,
        "Checkout reliability",
        "Catch payment regressions before they reach customers.",
    );
    let planning = topic(
        5,
        "Q4 planning",
        "Keep the quarter’s milestones and owners up to date.",
    );
    let id = web.topic.id;
    // Reports as an agent publishes them: priority, impact, proposal and typed
    // evidence, the way a PostHog Scout report reads.
    let mut publish = |subject: &str,
                       summary: &str,
                       hours: i64,
                       mut sources: meep_topic::ReportSources|
     -> Result<ThreadId> {
        let thread = observed(
            &mut web,
            subject,
            Source::Topic(id),
            ago(hours),
            &[("New web navigation", summary)],
        )?;
        let published = web.threads.last_mut().unwrap();
        published.messages[0].producer = Producer::PostHogTask(TaskId(Uuid::new_v4()));
        sources.observation = None;
        published.report_sources = Some(sources);
        take(&mut web, thread, summary, vec![])?;
        Ok(thread)
    };
    let evidence =
        |description: &str, source: &str, kind: &str, hours: i64| meep_topic::ReportEvidence {
            description: description.into(),
            source_id: source.into(),
            kind: Some(kind.into()),
            at: Some(ago(hours)),
        };
    let findings = "Three pilot teams reported that saved pages take longer to find after the sidebar change. Opens of saved pages fell 18% in the pilot cohort while the baseline held steady.\n\n## Problem\nPins moved below Recents in the new rail, so a saved page now takes two extra clicks. Teams that open saved pages daily notice first.\n\n## Impact\n6 of 24 pilot teams open saved pages less since the change; support threads about it doubled this week.\n\n## Solution\nMove Pins above Recents for the pilot cohort and compare opens for a week before the next rollout.";
    let report = publish(
        "Pilot teams struggle to find saved pages",
        findings,
        1,
        meep_topic::ReportSources {
            priority: Some(meep_topic::ReportPriority::P1),
            impact: Some("6 of 24 pilot teams open saved pages less since the sidebar change.".into()),
            proposal: Some("Move Pins above Recents for the pilot cohort and compare saved page opens for a week before the next rollout.".into()),
            evidence: vec![
                evidence("A pilot user scrolls past Recents twice before finding a pinned dashboard in the new rail.", "https://us.posthog.com/replay/0193-saved-pages", "replay", 3),
                evidence("Saved page opens fell 18% for the pilot cohort while the baseline held steady.", "Saved page opens · insight 31", "insight", 5),
                evidence("“Where did my pinned pages go?” three pilot teams in #navigation-pilot", "https://posthog.slack.com/archives/C0NAV/p1742", "slack", 20),
                evidence("The rail order change shipped in PR #856.", "https://github.com/PostHog/posthog/pull/856", "github", 30),
            ],
            references: vec!["Pilot feedback · #navigation-pilot · thread 1742".into()],
            ..Default::default()
        },
    )?;
    publish(
        "Compact rail labels truncate on 13-inch screens",
        "Section labels in the compact rail cut off at 1280 px, so teams on laptops guess which icon is which.",
        4,
        meep_topic::ReportSources {
            priority: Some(meep_topic::ReportPriority::P2),
            impact: Some(
                "412 sessions on 13-inch screens hovered rail icons to read labels this week."
                    .into(),
            ),
            proposal: Some(
                "Show a tooltip after 300 ms and widen the compact rail to 64 px below 1440 px."
                    .into(),
            ),
            evidence: vec![
                evidence(
                    "Rail labels end in an ellipsis on a 1280 px window.",
                    "https://us.posthog.com/replay/0193-compact-rail",
                    "replay",
                    6,
                ),
                evidence(
                    "Hover events on rail icons tripled for screens under 1440 px.",
                    "Rail hovers · insight 44",
                    "insight",
                    8,
                ),
            ],
            ..Default::default()
        },
    )?;
    publish(
        "Search hides keyboard shortcuts",
        "Search results no longer show their shortcuts, so keyboard users stopped jumping straight to sections.",
        26,
        meep_topic::ReportSources {
            priority: Some(meep_topic::ReportPriority::P3),
            evidence: vec![evidence(
                "Shortcut hints are missing from every search result row.",
                "https://github.com/PostHog/posthog/issues/912",
                "github",
                28,
            )],
            ..Default::default()
        },
    )?;
    let resolved = publish(
        "Old rail flag still on for two teams",
        "Two teams still see the old rail because web-nav-legacy is on for them.",
        50,
        meep_topic::ReportSources {
            priority: Some(meep_topic::ReportPriority::P2),
            evidence: vec![evidence(
                "web-nav-legacy is enabled for two team IDs.",
                "web-nav-legacy · feature flag",
                "event",
                52,
            )],
            ..Default::default()
        },
    )?;
    if let Some(sources) = web
        .threads
        .iter_mut()
        .find(|t| t.id == resolved)
        .and_then(|t| t.report_sources.as_mut())
    {
        sources.verdict = Some(meep_topic::ReportVerdict {
            outcome: meep_topic::ReportOutcome::Resolved,
            reason: "Implemented manually".into(),
            at: ago(40),
        });
    }
    // Exercise the explicitly assigned built-in sorter in the gateway diagnostics previews.
    web.topic.fallback.enabled = true;
    let git = GITHUB_INSTALLATION;
    for (kind, key, label) in [
        ("service", INSTALLATION, "Slack"),
        ("service", git, "GitHub"),
        ("insight", "31", "Saved page opens"),
        ("flag", "rail", "web-nav-v2"),
    ] {
        web.topic.default_watches_mut().push(Watch {
            id: WatchId(Uuid::new_v4()),
            connection: "posthog".into(),
            kind: kind.into(),
            key: key.into(),
            label: label.into(),
        });
    }
    web.topic.default_watches_mut().push(Watch {
        id: WatchId(Uuid::new_v4()),
        connection: "topic".into(),
        kind: "topic".into(),
        key: pr.topic.id.to_string(),
        label: "@PR reviews".into(),
    });
    web.topic.goals.push(Goal {
        id: GoalId(Uuid::new_v4()),
        text: "Move teams onto the new rail".into(),
        progress: Some(Progress::Target {
            current: 18.,
            target: 24.,
            unit: "teams".into(),
        }),
    });
    web.topic.goals.push(Goal {
        id: GoalId(Uuid::new_v4()),
        text: "Keep saved pages within two clicks".into(),
        progress: None,
    });
    web.topic.goals.insert(
        1,
        Goal {
            id: GoalId(Uuid::new_v4()),
            text: "Keep saved page opens above 35%".into(),
            progress: Some(Progress::Guardrail {
                current: 39.,
                low: 35.,
                high: 100.,
                unit: "%".into(),
            }),
        },
    );
    for (kind, key, label) in [
        ("insight", "insight-31", "Saved page opens"),
        ("flag", "web-nav-v2", "web-nav-v2"),
        ("channel", "C0WEBNAV", "#web-nav"),
    ] {
        web.topic.context_sources.push(Watch {
            id: WatchId(Uuid::new_v4()),
            connection: if kind == "channel" {
                "slack"
            } else {
                "posthog"
            }
            .into(),
            kind: kind.into(),
            key: key.into(),
            label: label.into(),
        });
    }
    web.topic.rules.push(Rule {
        id: RuleId(Uuid::new_v4()),
        text: "Ask before posting rollout updates in Slack.".into(),
        effect: RuleEffect::Ask(ActionKind("slack-reply".into())),
        from_task: None,
        created_at: ago(120),
    });
    let pending = observed(
        &mut web,
        "A permanent spot for Pins?",
        connection(INSTALLATION),
        ago(2),
        &[
            (
                "Maya Chen",
                "Three pilot teams asked for Pins next to Search.",
            ),
            (
                "Eli Torres",
                "We can fit it there if we move Recents into More.",
            ),
            (
                "Maya Chen",
                "Can we try that layout with the next six teams?",
            ),
        ],
    )?;
    ask(
        &mut web,
        pending,
        "Three pilot teams want Pins one click away.",
        "Choose whether Pins can replace Recents for the next six teams.",
        Suggestion::MakeTask {
            title: "Test a dedicated Pins slot".into(),
        },
    )?;
    let first = observed(
        &mut web,
        "Keyboard focus after closing Search",
        connection(git),
        ago(19),
        &[
            (
                "Jules Park",
                "PR #842 restores focus to the item that opened Search.",
            ),
            (
                "Noor Patel",
                "Verified with VoiceOver and the compact rail.",
            ),
            (
                "Jules Park",
                "Merged in the web build. The pilot teams can try it now.",
            ),
        ],
    )?;
    let focus = remember(
        &mut web,
        first,
        "Closing Search restores focus to the originating rail item.",
        "PR #842",
    )?;
    let task = TaskId(Uuid::new_v4());
    web.add_task(
        task,
        "Send the pilot teams a focus-fix update",
        Actor::Inbox(first),
        Some(first),
        ago(18),
    )?;
    web.start(task, "Checking the merged change", ago(17))?;
    web.submit(task, meep_topic::Action { depends_on_facts: None, kind: ActionKind("slack-reply".into()), label:"Send update".into(), done_label:"Sent the update to #web-nav.".into(), payload: json!({"channel":"web-nav"}) },
        "The fix shipped. Review the note before it goes to #web-nav.", Some("The keyboard focus fix is live. Close Search with Esc and you’ll land back on the same rail item. Thanks for helping us catch it.".into()), ago(16))?;
    take(
        &mut web,
        first,
        "The keyboard fix shipped. I drafted a note for the pilot teams.",
        vec![Outcome::Task(task), Outcome::Fact(focus)],
    )?;
    let insight = observed(
        &mut web,
        "Saved page opens in the pilot cohort",
        connection("31"),
        ago(28),
        &[
            (
                "PostHog",
                "Saved page opens rose from 31% to 39% in the pilot cohort.",
            ),
            (
                "Rina Shah",
                "The cohort still has 18 teams. Internal traffic is excluded.",
            ),
        ],
    )?;
    let fact = remember(
        &mut web,
        insight,
        "Saved page opens reached 39% across the 18 pilot teams.",
        "posthog",
    )?;
    take(
        &mut web,
        insight,
        "Eight points more pilot sessions reached a saved page. Cohort size held steady.",
        vec![Outcome::Fact(fact)],
    )?;
    let flag = observed(
        &mut web,
        "Rollout holds at 18 teams",
        connection("rail"),
        ago(46),
        &[
            ("PostHog", "web-nav-v2 is enabled for 18 of the 24 teams."),
            (
                "Maya Chen",
                "The remaining six use custom sidebar groups. Wait for their migration.",
            ),
        ],
    )?;
    let fact = remember(
        &mut web,
        flag,
        "The final six teams use custom sidebar groups.",
        "posthog",
    )?;
    take(
        &mut web,
        flag,
        "The last six teams need a migration before the flag can expand.",
        vec![Outcome::Fact(fact)],
    )?;
    let review = observed(
        &mut web,
        "Review window for the compact rail",
        Source::Topic(pr.topic.id),
        ago(51),
        &[
            (
                "PR reviews",
                "Noor can take the compact rail changes on Tuesday.",
            ),
            (
                "PR reviews",
                "Navigation labels and overflow are in the same review.",
            ),
        ],
    )?;
    let follow = TaskId(Uuid::new_v4());
    web.add_task(
        follow,
        "Prepare navigation samples for Noor",
        Actor::Topic(pr.topic.id),
        Some(review),
        ago(50),
    )?;
    take(
        &mut web,
        review,
        "Noor has a Tuesday slot. I queued the two samples she needs.",
        vec![Outcome::Task(follow)],
    )?;
    for (title, origin, hours, column) in [
        (
            "Map the six custom sidebar groups",
            Actor::User,
            26,
            Column::Todo,
        ),
        (
            "Compare navigation paths by cohort",
            Actor::Routine("Pilot pulse".into()),
            14,
            Column::InProgress,
        ),
        (
            "Check overflow at compact widths",
            Actor::Agent,
            32,
            Column::InProgress,
        ),
        (
            "Publish the baseline cohort table",
            Actor::Routine("Pilot pulse".into()),
            70,
            Column::Done,
        ),
    ] {
        let tid = TaskId(Uuid::new_v4());
        let origin_is_routine = matches!(origin, Actor::Routine(_));
        web.add_task(tid, title, origin, None, ago(hours))?;
        if column != Column::Todo {
            web.start(
                tid,
                match column {
                    Column::Done => "Preparing the baseline",
                    _ if origin_is_routine => "Reading the cohort breakdown",
                    _ => "Testing the 768 px breakpoint",
                },
                ago(hours - 1),
            )?;
        }
        if column == Column::Done {
            web.complete(tid, "Saved pilot-cohorts.csv.", ago(hours - 2))?;
        }
        // Queued for later: it waits in To do until someone starts it.
        if title.starts_with("Map the six") {
            let t = web
                .tasks
                .iter_mut()
                .find(|t| t.id == tid)
                .context("queued task")?;
            t.queued = true;
            t.model = Some("claude-deep".into());
            t.instructions =
                Some("List each custom group, who owns it, and where Pins would sit.".into());
        }
    }
    let asking = TaskId(Uuid::new_v4());
    web.add_task(
        asking,
        "Review pilot feedback",
        Actor::User,
        Some(report),
        ago(3),
    )?;
    web.start(asking, "Running", ago(3))?;
    web.ask_user(asking, "Which pilot cohort should I review?".into(), ago(2))?;
    // A run PostHog refused to start: it comes back to the person to retry or dismiss.
    let failed = TaskId(Uuid::new_v4());
    web.add_task(
        failed,
        "Summarise this week's pilot feedback",
        Actor::Agent,
        None,
        ago(3),
    )?;
    web.start(failed, "Starting", ago(3))?;
    web.work_needs_attention(
        failed,
        "Start failed: PostHog did not start task 3f2c: PostHog HTTP 400 invalid_input This field is required when selecting a cloud runtime.".into(),
        ago(2),
    )?;
    for (question, answer, hours) in [
        (
            "How are teams using saved pages?",
            "Opens went from 31% to 39% across the same 18 teams. The biggest change was in the compact rail.",
            77,
        ),
        (
            "What’s holding up the next group?",
            "Six teams have custom sidebar groups. Maya wants to test where Pins belongs before enabling the flag for them.",
            76,
        ),
    ] {
        let chat = observed(
            &mut web,
            question,
            Source::User,
            ago(hours),
            &[("You", question)],
        )?;
        take(
            &mut web,
            chat,
            answer,
            vec![Outcome::Reply {
                to: Source::User,
                text: answer.into(),
            }],
        )?;
    }
    // A chat request whose answer is long markdown, as agents write it.
    let setup = "Set up this topic for its mission: decide what it should work with, propose measurable goals, and create routines if it needs recurring work.";
    let long = observed(&mut web, setup, Source::User, ago(80), &[("You", setup)])?;
    let answer = "I set this topic up to track how teams find saved work.\n\n**What it works with**\n\n1. **Saved page opens**: the PostHog insight for opens from the rail.\n2. **web-nav-v2**: the rollout flag, so a change in exposure shows up here.\n3. **#web-nav** in Slack, for what pilot teams report.\n\n**Goals I propose**\n\n- Move all 24 pilot teams onto the new rail.\n- Keep saved pages within `two clicks` from anywhere.\n\n**Routines**\n\nA weekday *Pilot pulse* checks opens each morning and files a task when they drop more than 5%. Turn it on under Routines when you are ready.";
    take(
        &mut web,
        long,
        answer,
        vec![Outcome::Reply {
            to: Source::User,
            text: answer.into(),
        }],
    )?;
    let report = observed(
        &mut web,
        "Friday pilot handoff",
        Source::Topic(id),
        ago(58),
        &[
            (
                "Friday handoff",
                "The review notes are ready for Tuesday’s pilot check-in.",
            ),
            (
                "Friday handoff",
                "I included the cohort table and the outstanding Pins decision.",
            ),
        ],
    )?;
    take(
        &mut web,
        report,
        "Filed the pilot findings and the next review agenda together.",
        vec![Outcome::File("notes/review.md".into())],
    )?;
    for t in web.threads.iter_mut().skip(2) {
        t.unseen = false;
    }
    for (key, name, trigger, flow) in [
        ("review", "Pilot pulse", "Weekdays at 09:00", 11),
        ("flag", "Rollout check", "When web-nav-v2 changes", 12),
        ("weekly", "Friday handoff", "Fridays at 16:30", 13),
    ] {
        let flow = Uuid::from_u128(flow);
        web.topic.routines.push(RoutineInfo {
            event: None,
            enabled: true,
            observations: vec![],
            binding: RoutineBinding {
                watches: vec![],
                id: key.into(),
                name: name.into(),
                trigger: trigger.into(),
                backend: "posthog".into(),
                external_id: flow.to_string(),
            },
            last_run: Some(routine_run_times(flow)[0]),
            uncertain_manual_run: None,
            health: RoutineHealth::Ok,
        });
    }
    // What the agent set up while answering the setup request: receipts in the chat.
    let set_up = now - Duration::hours(80) + Duration::minutes(2);
    let first_fact = web.topic.facts.first().map(|f| f.id);
    for (text, subject) in [
        (
            "Set the mission to “Make it easier to find saved work from the sidebar.”".to_owned(),
            Ref::Topic,
        ),
        (
            "Added the goal “Move teams onto the new rail”.".to_owned(),
            Ref::Topic,
        ),
        (
            "Linked the PostHog insight “Saved page opens”.".to_owned(),
            Ref::Topic,
        ),
        (
            "Created the routine “Pilot pulse”.".to_owned(),
            Ref::Routine("review".into()),
        ),
    ]
    .into_iter()
    .chain(first_fact.map(|f| {
        (
            "Learned “Saved page opens reached 39% across the 18 pilot teams.”".to_owned(),
            Ref::Fact(f),
        )
    })) {
        web.activity.push(Activity {
            delivery: None,
            at: set_up,
            actor: Actor::Agent,
            text,
            subject,
        });
    }
    let pr_thread = observed(
        &mut pr,
        "Split the navigation patch?",
        Source::Topic(id),
        ago(3),
        &[
            (
                "New web navigation",
                "The overflow fix is ready. The label changes still need product review.",
            ),
            (
                "New web navigation",
                "Jules can ship the fix alone before the freeze.",
            ),
        ],
    )?;
    ask(
        &mut pr,
        pr_thread,
        "The overflow fix can ship independently.",
        "Jules needs a call on splitting PR #856 before the release freeze.",
        Suggestion::MakeTask {
            title: "Split the overflow fix from PR #856".into(),
        },
    )?;
    let payment = observed(
        &mut checkout,
        "Retry policy for wallet timeouts",
        connection(INSTALLATION),
        ago(6),
        &[
            (
                "Omar Ellis",
                "We saw twelve wallet authorizations time out overnight.",
            ),
            (
                "Sana Roy",
                "A retry recovered all twelve in staging. Shall we enable it for the pilot?",
            ),
        ],
    )?;
    ask(
        &mut checkout,
        payment,
        "One retry recovered every timeout in staging.",
        "Sana needs approval to try a second authorization on the wallet pilot.",
        Suggestion::DraftReply {
            draft: "Keep retries limited to the pilot for 24 hours.".into(),
            task_title: "Review wallet retry guidance".into(),
        },
    )?;
    checkout
        .topic
        .default_watches_mut()
        .push(web.topic.watches().next().unwrap().clone());
    let sections = [
        ("Personal", vec![me.topic.id]),
        (
            "Product engineering",
            vec![id, pr.topic.id, checkout.topic.id],
        ),
        ("Planning", vec![planning.topic.id]),
    ]
    .into_iter()
    .enumerate()
    .map(|(i, (name, topics))| Section {
        id: Uuid::from_u128(i as u128 + 1),
        name: name.into(),
        collapsed: false,
        items: topics
            .into_iter()
            .map(super::super::sidebar::topic_key)
            .collect(),
    })
    .collect();
    let subscriptions: Vec<_> = web
        .topic
        .watches()
        .filter(|w| w.connection == "posthog")
        .map(|w| json!({"watch":w,"workflow":"pilot-intake","mode":"push"}))
        .collect();
    let lab = Lab::with_snapshots([me, web, pr, checkout, planning])?;
    lab.upstream.preview_catalog.store(true, Ordering::SeqCst);
    let client = &lab.backend.client;
    client.set_preference(
        "sidebar",
        &Layout {
            sections,
            loose: vec![],
        },
    )?;
    client.set_preference(
        "posthog-project",
        &json!({
            "label": "Product engineering",
            "email": "alex@northline.example",
            "region": "Us",
            "project": 7,
        }),
    )?;
    lab.runtime.block_on(async {
        let mut grant = registration(&lab.origin);
        grant.grants = vec![id];
        grant.secrets.insert("webhook_secret".into(), "test-preview-workflow".into());
        grant.secrets.insert("config".into(), json!({"watches": subscriptions}).to_string());
        client.put_connection("posthog", &grant).await?;
        client.sync_once().await?;
        for (path, content) in [
            ("navigation.csv", "Component,Owner,Status\nCompact rail,Noor,In pilot\nSearch,Jules,Shipped\nOverflow,Jules,In review\nPins,Maya,Design\nRecents,Eli,Design\nGroups,Noor,Testing"),
            ("pilot-cohorts.csv", "Cohort,Teams,Saved opens\nEarly access,6,42%\nDesign partners,8,39%\nBeta,4,35%"),
            ("notes/review.md", "Pilot review\n\n18 teams are using the compact rail. Saved page opens rose eight points with no change in cohort size.\n\nNext review\nTry Pins in the first slot with the six teams that use custom groups."),
            ("notes/keyboard-audit.txt", "VoiceOver and keyboard checks\n\nEsc returns to the active rail item. Tab moves into the page content."),
            ("notes/handoff.txt", "Tuesday review\n\nNoor has the compact rail and overflow samples. Jules is on call for the pilot."),
            ("research/session-guide.md", "Find a saved page from the compact rail. Note the first click and the number of detours.")
        ] {
            client.put_file(id, path, content.as_bytes().to_vec()).await?;
        }
        client.refresh_files(id).await?;
        for key in ["review", "flag", "weekly"] {
            client.refresh_workflow(id, key).await?;
        }
        Ok::<_, anyhow::Error>(())
    })?;
    Ok((lab, id, first, pending, task))
}

#[allow(dead_code)]
/// A task run as PostHog reports it: the brief, tool calls, and a markdown answer.
fn run_fixture() -> Vec<meep_protocol::sessions::AgentMessage> {
    use meep_protocol::sessions::{AgentMessage, SessionBlock};
    let at = Utc::now().timestamp_millis() - 40 * 60_000;
    let tool = |id: &str, name: &str, input: &str, output: &str| SessionBlock {
        id: id.into(),
        kind: "tool".into(),
        text: name.into(),
        app: Some("meep-topic".into()),
        status: "completed".into(),
        input: input.into(),
        output: output.into(),
    };
    let text = |id: &str, body: &str| SessionBlock {
        id: id.into(),
        kind: "text".into(),
        text: body.into(),
        app: None,
        status: "completed".into(),
        input: String::new(),
        output: String::new(),
    };
    let answer = "The focus fix is live in **18 of 24** pilot teams. I drafted a short update for `#web-nav`:\n\n1. **What changed**: closing Search with Esc returns focus to the rail item you came from.\n2. **Who has it**: every team on the pilot flag; the last six get it with the migration.\n3. **What to check**: keyboard-only navigation in the compact rail.\n\nReview the draft below before it goes out.";
    vec![
        AgentMessage {
            role: "user".into(),
            agent_name: String::new(),
            text: "Tell the pilot teams the keyboard focus fix shipped. Keep it short.".into(),
            blocks: vec![],
            references: vec![],
            attachments: vec![],
            created_at: at,
        },
        AgentMessage {
            role: "assistant".into(),
            agent_name: "Claude".into(),
            text: answer.into(),
            blocks: vec![
                tool(
                    "t1",
                    "get_topic",
                    "{}",
                    "New web navigation: 4 goals, 12 facts",
                ),
                tool("t2", "search_threads", "{\"q\":\"focus fix\"}", "2 threads"),
                tool(
                    "t3",
                    "read_file",
                    "{\"path\":\"notes/review.md\"}",
                    "Pilot review notes",
                ),
                text("a1", answer),
                tool(
                    "t4",
                    "propose_action",
                    "{\"kind\":\"reply\"}",
                    "Submitted for review",
                ),
            ],
            references: vec![],
            attachments: vec![],
            created_at: at + 3 * 60_000,
        },
    ]
}

fn artifact_tasks(state: &TopicState) -> (&meep_topic::Task, &meep_topic::Task) {
    let find = |c| state.tasks.iter().find(|t| t.column == c).unwrap();
    (find(Column::Done), find(Column::InProgress))
}

fn task_file(state: &TopicState) -> String {
    format!("tasks/{}/Findings.md", artifact_tasks(state).0.title)
}

/// Two tasks' worth of PostHog artifacts, and the open document's bytes.
fn task_artifacts(
    state: &TopicState,
) -> (
    Vec<meep_wire::TaskArtifact>,
    (String, Result<Vec<u8>, String>),
) {
    let (done, running) = artifact_tasks(state);
    let artifact = |task: &meep_topic::Task, id: &str, name: &str, kind: &str, version, size| {
        meep_wire::TaskArtifact {
            task: task.id,
            run: Uuid::from_u128(0xa27).to_string(),
            id: id.into(),
            name: name.into(),
            kind: kind.into(),
            version,
            size: Some(size),
            content_type: None,
            url: None,
            updated_at: None,
        }
    };
    let findings = artifact(done, "doc-1", "Findings.md", "document", 3, 1_480);
    let open = (
        findings.cache_key(),
        Ok(b"Five components still use the old navigation rail.\n\nThe saved-pages entry point moved under More, which explains the drop in pilot teams finding it. Restoring it to the top level is the smallest fix.\n\nCohorts that saw the new rail first reach saved pages 31% less often in their first week.".to_vec()),
    );
    (
        vec![
            findings,
            artifact(done, "out-1", "cohorts.csv", "output", 0, 640),
            artifact(done, "plan-1", "plan.md", "plan", 0, 320),
            artifact(running, "doc-2", "Draft digest.md", "document", 1, 900),
        ],
        open,
    )
}

pub(crate) fn preview_main_screens() -> Result<()> {
    let Some(dir) = std::env::var_os("MEEP_PREVIEW_DIR") else {
        return Ok(());
    };
    let dir = std::path::Path::new(&dir);
    std::fs::create_dir_all(dir)?;
    let (lab, id, first, pending, task) = account()?;
    let client = lab.backend.client.clone();
    let state = client.topic(id)?.context("missing navigation workspace")?;
    // The attachment preview shows a real upload and the topic's model choice.
    let catalogue = lab.runtime.block_on(async {
        client
            .put_file(
                id,
                "uploads/launch-brief.md",
                b"Launch brief for the navigation rollout".to_vec(),
            )
            .await?;
        client.set_chat_model(id, Some("claude-deep")).await
    })?;
    for column in [
        Column::Todo,
        Column::InProgress,
        Column::NeedsYou,
        Column::Done,
    ] {
        anyhow::ensure!(
            state.tasks.iter().any(|t| t.column == column),
            "missing {column:?} task"
        );
    }
    let mut cx = gpui::HeadlessAppContext::with_platform(
        gpui_platform::current_platform(true).text_system(),
        Arc::new(gpui_kit::assets::AllAssets),
        gpui_platform::current_headless_renderer,
    );
    cx.allow_parking();
    cx.update(gpui_kit::init);
    // Captures show settled layouts: transitions finish instantly.
    cx.update(|cx| cx.set_reduce_motion(true));
    let empty = Lab::open()?;
    let open = |lab: &Lab, cx: &mut gpui::HeadlessAppContext, size| {
        cx.update(|cx| {
            meep_shell::workspace::open_window(
                WindowOptions {
                    window_bounds: Some(WindowBounds::Windowed(Bounds {
                        origin: Default::default(),
                        size,
                    })),
                    show: false,
                    focus: false,
                    ..Default::default()
                },
                cx,
                |w, cx| cx.new(|cx| Desktop::new(lab.backend.clone(), lab.runtime.clone(), w, cx)),
            )
        })
    };
    let wide = size(px(1220.), px(780.));
    let (window, view) = open(&lab, &mut cx, wide)?;
    let (empty_window, _) = open(&empty, &mut cx, wide)?;
    let identity = cx.update(|cx| view.read(cx).identity.clone());
    capture(&mut cx, empty_window, dir, "first-topic")?;
    let report_page = |subject: &str| {
        Page::Topic(
            id,
            Tab::Inbox,
            state
                .threads
                .iter()
                .find(|t| t.subject == subject)
                .map(|t| Detail::Thread(t.id)),
        )
    };
    let first_goal = state.topic.goals.first().map(|g| Detail::Goal(g.id));
    for (name, page) in [
        // The topic as one agent: the conversation in front, the Overview beside it.
        ("agent-chat", Page::Topic(id, Tab::Chat, None)),
        ("agent-working", Page::Topic(id, Tab::Chat, None)),
        ("sidebar-card", Page::Topic(id, Tab::Chat, None)),
        ("agent-prompt", Page::Topic(id, Tab::Chat, None)),
        ("agent-overview", Page::Topic(id, Tab::Chat, None)),
        ("agent-tasks", Page::Topic(id, Tab::Tasks, None)),
        (
            "agent-task",
            Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))),
        ),
        ("agent-inbox", Page::Topic(id, Tab::Inbox, None)),
        (
            "agent-report",
            report_page("Pilot teams struggle to find saved pages"),
        ),
        ("agent-files", Page::Topic(id, Tab::Files, None)),
        ("agent-routines", Page::Topic(id, Tab::Routines, None)),
        ("agent-mission", Page::Topic(id, Tab::Mission, None)),
        ("agent-goals", Page::Topic(id, Tab::Goals, None)),
        (
            "agent-goal",
            Page::Topic(id, Tab::Goals, first_goal.clone()),
        ),
        ("agent-facts", Page::Topic(id, Tab::Facts, None)),
        ("agent-linked", Page::Topic(id, Tab::Linked, None)),
        (
            "agent-linked-item",
            Page::Topic(id, Tab::Linked, Some(Detail::Linked("insight-31".into()))),
        ),
        (
            "agent-fact",
            Page::Topic(
                id,
                Tab::Facts,
                state.topic.facts.first().map(|f| Detail::Fact(f.id)),
            ),
        ),
        ("agent-rules", Page::Topic(id, Tab::Rules, None)),
        ("agent-needs", Page::Topic(id, Tab::Needs, None)),
        ("compact-agent-chat", Page::Topic(id, Tab::Chat, None)),
        ("compact-agent-overview", Page::Topic(id, Tab::Goals, None)),
        ("needs-you", Page::Needs),
        ("compact-needs-you", Page::Needs),
        ("wide-inbox", Page::Topic(id, Tab::Inbox, None)),
        ("compact-inbox", Page::Topic(id, Tab::Inbox, None)),
        ("compact-context", Page::Topic(id, Tab::Facts, None)),
        ("compact-settings", Page::Settings),
        ("compact-search", Page::Needs),
        (
            "inbox-report",
            Page::Topic(
                id,
                Tab::Inbox,
                state
                    .threads
                    .iter()
                    .find(|t| t.report_sources.is_some())
                    .map(|t| Detail::Thread(t.id)),
            ),
        ),
        ("inbox", Page::Topic(id, Tab::Inbox, None)),
        // Every state of a report page: opened up, resolved, bare, and narrow.
        (
            "report-expanded",
            report_page("Pilot teams struggle to find saved pages"),
        ),
        (
            "report-resolved",
            report_page("Old rail flag still on for two teams"),
        ),
        (
            "report-minimal",
            report_page("Search hides keyboard shortcuts"),
        ),
        (
            "compact-report",
            report_page("Pilot teams struggle to find saved pages"),
        ),
        (
            "thread",
            Page::Topic(id, Tab::Inbox, Some(Detail::Thread(first))),
        ),
        (
            "pending-thread",
            Page::Topic(id, Tab::Inbox, Some(Detail::Thread(pending))),
        ),
        (
            "thread-long",
            Page::Topic(
                id,
                Tab::Inbox,
                state
                    .threads
                    .iter()
                    .find(|t| t.subject.starts_with("Set up this topic"))
                    .map(|t| Detail::Thread(t.id)),
            ),
        ),
        ("tasks", Page::Topic(id, Tab::Tasks, None)),
        ("tasks-board", Page::Topic(id, Tab::Tasks, None)),
        (
            "task-queued",
            Page::Topic(
                id,
                Tab::Tasks,
                state
                    .tasks
                    .iter()
                    .find(|t| t.queued)
                    .map(|t| Detail::Task(t.id)),
            ),
        ),
        ("compact-tasks-board", Page::Topic(id, Tab::Tasks, None)),
        ("compact-tasks", Page::Topic(id, Tab::Tasks, None)),
        ("new-task", Page::Topic(id, Tab::Tasks, None)),
        ("new-task-codex", Page::Topic(id, Tab::Tasks, None)),
        ("compact-new-task", Page::Topic(id, Tab::Tasks, None)),
        (
            "compact-task-detail",
            Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))),
        ),
        (
            "compact-empty-routines",
            Page::Topic(TopicId(Uuid::from_u128(5)), Tab::Routines, None),
        ),
        ("compact-new-routine", Page::Topic(id, Tab::Routines, None)),
        ("tasks-done", Page::Topic(id, Tab::Tasks, None)),
        (
            "empty-board",
            Page::Topic(TopicId(Uuid::from_u128(5)), Tab::Tasks, None),
        ),
        (
            "send-back",
            Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))),
        ),
        (
            "task-detail",
            Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))),
        ),
        (
            "task-running",
            Page::Topic(
                id,
                Tab::Tasks,
                state
                    .tasks
                    .iter()
                    .find(|t| t.column == Column::InProgress)
                    .map(|t| Detail::Task(t.id)),
            ),
        ),
        ("data", Page::Topic(id, Tab::Files, None)),
        (
            "table",
            Page::Topic(id, Tab::Files, Some(Detail::Table("navigation.csv".into()))),
        ),
        (
            "files",
            Page::Topic(id, Tab::Files, Some(Detail::File("notes/review.md".into()))),
        ),
        ("file-browser", Page::Topic(id, Tab::Files, None)),
        (
            "task-files",
            Page::Topic(id, Tab::Files, Some(Detail::File(task_file(&state)))),
        ),
        ("context", Page::Topic(id, Tab::Facts, None)),
        ("context-full", Page::Topic(id, Tab::Goals, None)),
        ("mission-edit", Page::Topic(id, Tab::Mission, None)),
        (
            "empty-inbox",
            Page::Topic(TopicId(Uuid::from_u128(5)), Tab::Inbox, None),
        ),
        (
            "empty-routines",
            Page::Topic(TopicId(Uuid::from_u128(5)), Tab::Routines, None),
        ),
        (
            "empty-files",
            Page::Topic(TopicId(Uuid::from_u128(5)), Tab::Files, None),
        ),
        (
            "empty-chat",
            Page::Topic(TopicId(Uuid::from_u128(5)), Tab::Chat, None),
        ),
        ("needs-clear", Page::Needs),
        (
            "inbox-skipped",
            Page::Topic(TopicId(Uuid::from_u128(1)), Tab::Inbox, None),
        ),
        (
            "scout-details",
            Page::Topic(
                id,
                Tab::Routines,
                Some(Detail::Scout(navigation_scout().id)),
            ),
        ),
        ("routines-overview", Page::Topic(id, Tab::Routines, None)),
        (
            "routines",
            Page::Topic(id, Tab::Routines, Some(Detail::Routine("review".into()))),
        ),
        (
            "compact-routine",
            Page::Topic(id, Tab::Routines, Some(Detail::Routine("review".into()))),
        ),
        ("chat", Page::Topic(id, Tab::Chat, None)),
        ("chat-attachments", Page::Topic(id, Tab::Chat, None)),
        ("chat-default-model", Page::Topic(id, Tab::Chat, None)),
        ("compact-chat", Page::Topic(id, Tab::Chat, None)),
        (
            "compact-thread",
            Page::Topic(id, Tab::Inbox, Some(Detail::Thread(first))),
        ),
        ("sources", Page::Topic(id, Tab::Chat, None)),
        ("search", Page::Needs),
        ("search-recent", Page::Needs),
        ("search-no-results", Page::Needs),
        ("new-topic", Page::Needs),
        ("routine-templates", Page::Topic(id, Tab::Routines, None)),
        (
            "task-question",
            Page::Topic(
                id,
                Tab::Tasks,
                state
                    .tasks
                    .iter()
                    .find(|t| t.input_question.is_some())
                    .map(|t| Detail::Task(t.id)),
            ),
        ),
        (
            "task-failed",
            Page::Topic(
                id,
                Tab::Tasks,
                state
                    .tasks
                    .iter()
                    .find(|t| t.title.starts_with("Summarise this week"))
                    .map(|t| Detail::Task(t.id)),
            ),
        ),
        ("error-toast", Page::Topic(id, Tab::Inbox, None)),
        ("settings", Page::Settings),
        ("settings-connections", Page::Settings),
        ("settings-store-search", Page::Settings),
        ("settings-store-category", Page::Settings),
        ("compact-settings-store", Page::Settings),
        ("settings-detail", Page::Settings),
        ("settings-remove", Page::Settings),
        ("settings-custom", Page::Settings),
        ("settings-custom-key", Page::Settings),
        ("settings-template-key", Page::Settings),
        ("settings-notifications", Page::Settings),
        ("settings-permissions", Page::Settings),
        ("settings-shortcuts", Page::Settings),
        ("settings-advanced", Page::Settings),
        ("settings-clear-cache", Page::Settings),
        ("settings-appearance", Page::Settings),
        ("settings-signed-out", Page::Settings),
        ("collapsed", Page::Needs),
        ("sidebar-rename-section", Page::Needs),
        ("sidebar-hidden", Page::Topic(id, Tab::Inbox, None)),
        ("sign-in", Page::Needs),
    ] {
        let dimensions = if matches!(name, "context-full" | "routines") {
            // The whole page: down to the sources and how it acts, or the
            // routine's whole flow and its recent runs.
            size(px(1220.), px(1900.))
        } else if name == "wide-inbox" {
            size(px(1600.), px(820.))
        } else if matches!(name, "compact-chat" | "compact-thread") {
            size(px(840.), px(600.))
        } else if name.starts_with("compact-") {
            size(px(760.), px(480.))
        } else {
            wide
        };
        cx.update_window(window, |_, w, cx| {
            if w.viewport_size() != dimensions {
                w.resize(dimensions);
                w.bounds_changed(cx);
            }
            view.update(cx, |s, cx| {
                s.reload();
                s.identity = identity.clone();
                for section in &mut s.layout.sections {
                    section.collapsed = name == "collapsed";
                }
                s.done = name == "tasks-done";
                s.renaming_section = None;
                s.task_display = Default::default();
                s.toggled_groups.clear();
                if name.contains("tasks-board") {
                    s.task_display.boards.insert(id);
                }
                if name == "report-expanded"
                    && let Page::Topic(_, _, Some(Detail::Thread(t))) = &page
                {
                    s.toggled_groups.insert(format!("report-full-{t}"));
                    s.toggled_groups.insert(format!("report-evidence-{t}"));
                }
                if name == "tasks-done" {
                    s.toggled_groups.insert("status-Done".into());
                }
                // The conversation at work with things waiting, or asking for an OK.
                s.topic_card.open = (name == "sidebar-card").then_some(id);
                if matches!(name, "agent-working" | "agent-prompt" | "sidebar-card")
                    && let Some(state) = s.states.iter_mut().find(|x| x.topic.id == id)
                    && let Some(thread) = state
                        .threads
                        .iter_mut()
                        .find(|t| t.messages.first().is_some_and(|m| m.text.starts_with("Set up this topic")))
                    && let Some(template) = state.tasks.first().cloned()
                {
                    let mut session = template;
                    session.id = TaskId(Uuid::from_u128(0x5e55));
                    session.title = "Set up this topic".into();
                    session.assignment = Some(meep_topic::InboxAssignment::ChatAnswer);
                    session.from_thread = Some(thread.id);
                    session.action = None;
                    session.worker = None;
                    thread.outcomes.insert(0, Outcome::Task(session.id));
                    state.tasks.push(session);
                    let session = state.tasks.last_mut().expect("just added");
                    if name != "agent-prompt" {
                        session.column = Column::InProgress;
                        session.worker = Some("Querying saved-page opens".into());
                        let mut todo = session.clone();
                        todo.id = TaskId(Uuid::from_u128(0x70d0));
                        todo.title = "Draft the weekly pilot summary".into();
                        todo.assignment = Some(meep_topic::InboxAssignment::Session);
                        todo.column = Column::Todo;
                        state.tasks.push(todo);
                    } else {
                        session.column = Column::NeedsYou;
                        session.action = Some(meep_topic::Action {
                            kind: meep_topic::ActionKind("routine-activate".into()),
                            label: "Activate Pilot pulse".into(),
                            done_label: "Activated Pilot pulse".into(),
                            depends_on_facts: None,
                            payload: serde_json::json!({}),
                        });
                    }
                }
                s.sidebar_hidden = name == "sidebar-hidden";
                s.overview_hidden = false;
                s.overview_open.clear();
                if name == "agent-overview" {
                    for tab in [Tab::Needs, Tab::Tasks, Tab::Mission, Tab::Goals, Tab::Facts] {
                        s.overview_open.insert((id, tab));
                    }
                } else if let Some(tab) = match name {
                    "agent-tasks" | "agent-task" => Some(Tab::Tasks),
                    "agent-inbox" | "agent-report" => Some(Tab::Inbox),
                    "agent-files" => Some(Tab::Files),
                    "agent-routines" | "scout-details" => Some(Tab::Routines),
                    "agent-goals" | "agent-goal" => Some(Tab::Goals),
                    "agent-facts" => Some(Tab::Facts),
                    "agent-linked" | "agent-linked-item" => Some(Tab::Linked),
                    "agent-fact" => Some(Tab::Facts),
                    "agent-rules" => Some(Tab::Rules),
                    _ => None,
                } {
                    s.overview_open.insert((id, tab));
                }
                s.error = (name == "error-toast")
                    .then(|| "Couldn't save the routine. PostHog rejected its schedule: weekly runs need a day.".to_owned());
                s.settings_page = match name {
                    "settings-connections"
                    | "settings-store-search"
                    | "settings-store-category"
                    | "compact-settings-store"
                    | "settings-detail"
                    | "settings-remove"
                    | "settings-custom"
                    | "settings-custom-key"
                    | "settings-template-key" => SettingsPage::Connections,
                    "settings-permissions" => SettingsPage::Permissions,
                    "settings-shortcuts" => SettingsPage::Shortcuts,
                    "settings-advanced" | "settings-clear-cache" => SettingsPage::Advanced,
                    "settings-notifications" => SettingsPage::Notifications,
                    "settings-appearance" => SettingsPage::Appearance,
                    _ => SettingsPage::General,
                };
                s.files = matches!(name, "files" | "file-browser" | "empty-files" | "task-files");
                // Task artifacts come live from PostHog; the capture supplies a listing.
                s.artifacts.clear();
                s.artifact_open = None;
                s.file_folders.clear();
                if name == "task-files" {
                    let (artifacts, open) = task_artifacts(&state);
                    s.artifacts.insert(id, Ok(artifacts));
                    s.artifacts_at.insert(id, std::time::Instant::now());
                    s.artifact_open = Some(open);
                }
                let dest = s.settings_page;
                s.settings_page = SettingsPage::General;
                s.navigate(page, w, cx);
                if name == "compact-agent-overview" {
                    s.overview_overlay = true;
                    s.overview_open.insert((id, Tab::Goals));
                }
                s.settings_page = dest;
                if dest == SettingsPage::Connections {
                    s.mcp.servers = serde_json::from_value(json!(store::installations())).unwrap();
                    s.mcp.catalog = serde_json::from_value(json!(store::catalog())).unwrap();
                    s.mcp.tools = serde_json::from_value(json!(store::tools_fixture())).unwrap();
                    use super::super::mcp_settings::Screen;
                    s.mcp.screen = match name {
                        "settings-detail" | "settings-remove" => {
                            Screen::Detail(Uuid::from_u128(101))
                        }
                        "settings-custom" | "settings-custom-key" => Screen::Custom,
                        "settings-template-key" => Screen::TemplateKey(Uuid::from_u128(6)),
                        _ => Screen::List,
                    };
                    s.mcp.confirm = name == "settings-remove";
                    s.mcp.category = (name == "settings-store-category").then(|| "dev".into());
                    let query = if name == "settings-store-search" { "issues" } else { "" };
                    s.mcp.search.update(cx, |e, cx| e.set_value(query, w, cx));
                    s.mcp.oauth = name != "settings-custom-key";
                    s.mcp.failures.insert(
                        Uuid::from_u128(103),
                        "Could not refresh tools from the upstream MCP server.".into(),
                    );
                }
                s.clear_confirm = name == "settings-clear-cache";
                if name == "needs-clear" {
                    s.needs.clear();
                }
                if name == "file-browser" {
                    s.folder = Some("notes".into());
                }
                s.chat_reference = None;
                s.chat_files = if name == "chat-attachments" {
                    vec!["uploads/launch-brief.md".into()]
                } else {
                    vec![]
                };
                if name == "chat-attachments" || name == "chat-default-model" {
                    s.chat_models_topic.set(Some(id));
                    let mut selection = catalogue.clone();
                    if name == "chat-default-model" { selection.selected = None; }
                    s.show_chat_models(Ok(selection), cx);
                }
                // Only the attachment preview carries a draft into the next capture.
                let draft = if name == "chat-attachments" {
                    "Turn the brief into next week’s plan"
                } else {
                    ""
                };
                s.composer.update(cx, |e, cx| e.set_value(draft, w, cx));
                if name.contains("routine") {
                        let t = |id: &str, name: &str, description: &str| meep_wire::RoutineTemplate {
                            id: id.into(),
                            name: name.into(),
                            description: description.into(),
                            trigger: serde_json::json!({"type": "manual"}),
                            steps: vec![],
                        };
                        s.templates = Some(Ok(vec![
                            t("sort-inbox", "Sort inbox", "Sort each message with System 1."),
                            t("urgent-only", "Urgent only", "Keep only messages that need action today."),
                            t("daily-brief", "Daily brief", "Each morning, write what changed and what needs you."),
                            t("weekly-goals", "Weekly goals", "Each Monday, check and update every goal."),
                            t("digest-then-drop", "Log, don't inbox", "Keep a note of each message without adding it to the inbox."),
                        ]));
                                    }
                match name {
                    "send-back" => s.send_back = true,
                    "mission-edit" => {
                        s.editing = true;
                        s.mission_edit.update(cx, |e, cx| {
                            e.set_value(state.topic.mission.clone(), w, cx);
                            e.focus(w, cx);
                        });
                    }
                    "new-topic" => s.open_sheet(Sheet::New, w, cx),
                    "new-task" | "compact-new-task" | "new-task-codex" => {
                        s.begin_task(id, w, cx);
                        s.task_for_agent = true;
                        s.show_chat_models(Ok(catalogue.clone()), cx);
                        if name == "new-task-codex" {
                            s.task_model = Some("codex-test".into());
                            s.sync_task_selection(cx);
                            s.task_description.update(cx, |e, cx| {
                                e.set_value("Draft the pilot follow-up email", w, cx)
                            });
                        }
                    }
                    "routine-templates"|"compact-new-routine" => s.compose_routine(w, cx),
                    "search-recent" => s.open_sheet(Sheet::Search, w, cx),
                    "search" | "search-no-results" | "compact-search" => {
                        s.open_sheet(Sheet::Search, w, cx);
                        s.search.update(cx, |e, cx| {
                            e.set_value(
                                if name != "search-no-results" {
                                    "navigation"
                                } else {
                                    "winter summit"
                                },
                                w,
                                cx,
                            )
                        });
                    }
                    "sign-in" | "settings-signed-out" => s.identity = None,
                    "sidebar-rename-section" => {
                        let id = s.layout.sections[1].id;
                        s.start_section_rename(id, w, cx);
                    }
                    "task-detail" | "compact-task-detail" | "task-running" => {
                        s.run_messages = run_fixture();
                        s.run_status = if name == "task-running" { "in_progress" } else { "completed" }.into();
                        s.run_notice = None;
                        // A late reply from the loopback server must not replace the fixture.
                        s.run_revision += 1;
                    }
                    _ => (),
                };
                cx.notify();
            })
        })?;
        cx.run_until_parked();
        if matches!(name, "task-detail" | "compact-task-detail" | "task-running") {
            // Topic refreshes reload the run from the loopback server; show the fixture.
            cx.update_window(window, |_, _, cx| {
                view.update(cx, |s, cx| {
                    s.run_messages = run_fixture();
                    s.run_notice = None;
                    s.run_revision += 1;
                    cx.notify()
                })
            })?;
        }
        capture(&mut cx, window, dir, name)?;
    }
    // An archived topic: the sidebar's Archived group, folded and open.
    let planning = TopicId(Uuid::from_u128(5));
    lab.backend.client.archive_topic(planning)?;
    for (name, open) in [("sidebar-archived", false), ("sidebar-archived-open", true)] {
        cx.update_window(window, |_, w, cx| {
            view.update(cx, |s, cx| {
                s.reload();
                s.archived_open = open;
                s.navigate(Page::Needs, w, cx);
            })
        })?;
        cx.run_until_parked();
        capture(&mut cx, window, dir, name)?;
    }
    lab.backend.client.unarchive_topic(planning)?;
    cx.update_window(window, |_, _, cx| view.update(cx, |s, _| s.reload()))?;
    capture_views(&lab, id, &mut cx, window, &view, dir)?;
    // Deliver two real intake events through the loopback model gateway. Keep the
    // unavailable and in-flight states separate from the healthy workspace captures.
    let engine = lab.server.engine();
    let (failed, sorting) = lab.runtime.block_on(async {
        for (mode, subject) in [
            ("unavailable", "Should the pilot include tablet layouts?"),
            ("sorting", "The compact rail in landscape"),
        ] {
            engine
                .ingest(meep_ingest::Event {
                    connection: "posthog".into(),
                    kind: "service".into(),
                    channel: INSTALLATION.into(),
                    external_id: mode.into(),
                    thread_hint: Some(mode.into()),
                    author: "Maya Chen".into(),
                    at: Utc::now(),
                    text: subject.into(),
                    attributes: json!({"gateway":mode}),
                })
                .await?;
            if mode == "unavailable" {
                engine.sort_pending(id).await?;
            }
        }
        client.sync_once().await?;
        let state = client.topic(id)?.context("missing navigation topic")?;
        let find = |external: &str| {
            state
                .threads
                .iter()
                .find(|t| {
                    t.messages
                        .iter()
                        .any(|m| m.external_id.as_deref() == Some(external))
                })
                .map(|t| t.id)
                .context("missing gateway event")
        };
        Ok::<_, anyhow::Error>((find("unavailable")?, find("sorting")?))
    })?;
    for (name, tab, detail) in [
        ("sorting", Tab::Inbox, Some(Detail::Thread(sorting))),
        (
            "gateway-unavailable",
            Tab::Inbox,
            Some(Detail::Thread(failed)),
        ),
        ("connection-warning", Tab::Inbox, None),
        (
            "connection-detail",
            Tab::Routines,
            Some(Detail::Problem("posthog".into())),
        ),
    ] {
        cx.update_window(window, |_, w, cx| {
            view.update(cx, |s, cx| {
                s.identity = identity.clone();
                s.reload();
                s.navigate(Page::Topic(id, tab, detail), w, cx);
            })
        })?;
        cx.run_until_parked();
        capture(&mut cx, window, dir, name)?;
    }
    cx.update_window(window, |_, w, cx| {
        w.resize(size(px(760.), px(480.)));
        w.bounds_changed(cx);
        view.update(cx, |s, cx| s.navigate(Page::Settings, w, cx));
    })?;
    cx.run_until_parked();
    capture(&mut cx, window, dir, "compact-settings-warning")?;
    let (mut offline, id, ..) = account()?;
    let (window, view) = open(&offline, &mut cx, wide)?;
    offline.disconnect()?;
    offline.backend.client.issue(
        id,
        Command::AddTask {
            id: TaskId(Uuid::new_v4()),
            title: "Check the tablet breakpoint".into(),
        },
    )?;
    ensure_offline(&offline)?;
    cx.update_window(window, |_, w, cx| {
        view.update(cx, |s, cx| {
            s.reload();
            s.navigate(Page::Topic(id, Tab::Tasks, None), w, cx);
        })
    })?;
    cx.run_until_parked();
    capture(&mut cx, window, dir, "offline-pending")?;
    Ok(())
}

fn capture_views(
    lab: &Lab,
    topic: TopicId,
    cx: &mut gpui::HeadlessAppContext,
    window: AnyWindowHandle,
    desktop: &Entity<Desktop>,
    dir: &std::path::Path,
) -> Result<()> {
    use meep_wire::views::ViewCommand;
    let id = Uuid::new_v4();
    let client = &lab.backend.client;
    let identity = client.preference::<Identity>("posthog-project")?;
    let mut mcp=lab.runtime.block_on(async{
        client.issue_view(id,ViewCommand::Create{prompt:"Build a launch tracker from the navigation team’s open work. Group tasks by status.".into(),options:Default::default()})?;
        client.sync_once().await?;
        view_fixture::session(lab,id).await
    })?;
    for name in [
        "view-building",
        "view-composer",
        "view-sidebar",
        "view-rendered",
        "view-session",
        "view-settings",
        "view-script-error",
    ] {
        if name == "view-sidebar" {
            lab.runtime.block_on(async {
                view_fixture::publish(&mut mcp, topic).await?;
                client.sync_once().await
            })?;
        }
        cx.update_window(window,|_,w,cx|desktop.update(cx,|s,cx|{
            s.identity=identity.clone();
            s.reload();
            let home=s.layout.home(&super::super::sidebar::topic_key(topic));s.move_to_section(&super::super::sidebar::view_key(id),home,cx);
            for section in &mut s.layout.sections{section.collapsed=false;}
            s.sidebar_hidden=false;
            let page=match name {"view-composer"=>Page::NewView,"view-sidebar"=>Page::Topic(topic,Tab::Inbox,None),_=>Page::View(id)};
            s.navigate(page,w,cx);s.views.panel=name=="view-session";
            if name=="view-settings"{s.open_view_settings(id,w,cx);}
            else {s.views.settings=false;}
            if name=="view-script-error"{
                // An old replica can contain source produced by an incompatible runtime.
                if let Some(row)=s.views.rows.iter_mut().find(|v|v.id==id){
                    let v=Arc::make_mut(row);
                    v.publish(v.generation(),"view({ render() { throw Error('Unsupported layout in this version') } })".into(),Utc::now()).unwrap();
                }
            }
            cx.notify();
        }))?;
        cx.run_until_parked();
        if matches!(name, "view-rendered" | "view-session") {
            // Wait for the script's asynchronous replica request and the resulting GPUI frame.
            let until = std::time::Instant::now() + std::time::Duration::from_secs(5);
            while !cx.update(|cx| desktop.read(cx).views.inspected_rows(cx) > 0) {
                anyhow::ensure!(
                    std::time::Instant::now() < until,
                    "Launch tracker did not render topic tasks"
                );
                std::thread::sleep(std::time::Duration::from_millis(10));
                cx.run_until_parked();
            }
        }
        capture(cx, window, dir, name)?;
    }
    Ok(())
}

fn ensure_offline(lab: &Lab) -> Result<()> {
    let client = &lab.backend.client;
    anyhow::ensure!(
        lab.runtime.block_on(client.sync_once()).is_err()
            && matches!(client.status(), Status::Offline { pending: 1, .. }),
        "expected one queued command in the disconnected replica"
    );
    Ok(())
}

fn capture(
    cx: &mut gpui::HeadlessAppContext,
    window: AnyWindowHandle,
    dir: &std::path::Path,
    name: &str,
) -> Result<()> {
    // MEEP_PREVIEW_ONLY=thread,task narrows a run to the captures being iterated on.
    if let Ok(only) = std::env::var("MEEP_PREVIEW_ONLY")
        && !only.split(',').any(|p| name.contains(p.trim()))
    {
        return Ok(());
    }
    for (scheme, palette) in [
        ("light", meep_ui::design::LIGHT),
        ("dark", meep_ui::design::GRAPHITE),
    ] {
        cx.update(|cx| meep_shell::appearance::set_palette(palette, cx));
        cx.update_window(window, |_, w, cx| {
            w.refresh();
            w.draw(cx).clear(cx);
        })?;
        if name.contains("settings-connections") || name.contains("settings-store") {
            // The first draw requests the theme-specific service artwork.
            cx.run_until_parked();
            cx.update_window(window, |_, w, cx| {
                w.refresh();
                w.draw(cx).clear(cx);
            })?;
        }
        cx.capture_screenshot(window)?
            .save(dir.join(format!("{scheme}-{name}.png")))?;
    }
    Ok(())
}
