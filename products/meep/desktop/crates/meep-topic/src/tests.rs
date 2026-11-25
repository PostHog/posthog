use super::*;
use chrono::{DateTime, TimeDelta, Utc};
use uuid::Uuid;

const NOW: DateTime<Utc> = DateTime::UNIX_EPOCH;

fn id<T: From<Uuid>>(n: u128) -> T {
    Uuid::from_u128(n).into()
}
fn state() -> TopicState {
    TopicState::new(Topic::new(id(1), "Navigation", NOW))
}
fn message(n: u128) -> Message {
    Message {
        id: id(n),
        producer: Producer::System,
        origin: Some(
            Source::Connection {
                connection: "slack".into(),
                channel: "#new-web".into(),
            }
            .into_origin("Adam".into(), NOW, Some(format!("slack-{n}"))),
        ),
        author: "Adam".into(),
        at: NOW,
        text: "One more rail slot?".into(),
        external_id: Some(format!("slack-{n}")),
    }
}
fn task_suggestion() -> Suggestion {
    Suggestion::MakeTask {
        title: "Decide on a sixth slot".into(),
    }
}
fn ask() -> Decision {
    Decision::Ask {
        summary: "A question about the rail.".into(),
        reason: "This conflicts with your decision.".into(),
        suggestions: vec![task_suggestion(), Suggestion::Leave],
    }
}
fn fact(n: u128) -> Fact {
    Fact {
        id: id(n),
        text: format!("The rail holds {n} items"),
        provenance: Provenance {
            origin: None,
            author: "Shy".into(),
            via: "Slack".into(),
            at: NOW,
            thread: None,
        },
        superseded_by: None,
        invalidated_by: None,
        withdrawn_at: None,
    }
}
fn action() -> Action {
    Action {
        depends_on_facts: None,
        kind: ActionKind("copy-change".into()),
        label: "Merge PR 2310".into(),
        done_label: "Merged PR 2310".into(),
        payload: serde_json::json!({ "pr": 2310 }),
    }
}
fn rule(n: u128, effect: RuleEffect) -> Rule {
    Rule {
        id: id(n),
        text: "Topic policy.".into(),
        effect,
        from_task: None,
        created_at: NOW,
    }
}
fn target(current: f64) -> Progress {
    Progress::Target {
        current,
        target: 10.0,
        unit: "%".into(),
    }
}
fn watch(n: u128) -> Watch {
    Watch {
        id: id(n),
        connection: "slack".into(),
        kind: "channel".into(),
        key: "#new-web".into(),
        label: "New web chat".into(),
    }
}
fn todo() -> TopicState {
    let mut state = state();
    state
        .add_task(id(9), "Review copy", Actor::User, None, NOW)
        .unwrap();
    state
}

#[test]
fn a_resolved_thread_keeps_its_outcomes_and_becomes_unseen_on_a_new_message() {
    let mut s = state();
    let first = s.receive(message(1), "rail", id(7), NOW).unwrap();
    assert_eq!(first[0].kind, ChangeKind::ThreadOpened(id(7)));
    assert_eq!(s.threads[0].state, ThreadState::Sorting);
    let outcomes = vec![
        Outcome::Note("Nothing to do.".into()),
        Outcome::File("notes.md".into()),
        Outcome::Reply {
            to: Source::User,
            text: "Saved.".into(),
        },
    ];
    s.sort(
        id(7),
        Decision::Handle {
            summary: "Noted.".into(),
            outcomes: outcomes.clone(),
        },
        NOW,
    )
    .unwrap();
    s.mark_seen(id(7), NOW).unwrap();
    assert!(!s.threads[0].unseen);
    let later = NOW + TimeDelta::minutes(5);
    let changes = s.receive(message(2), "rail", id(8), later).unwrap();
    assert_eq!(changes[0].kind, ChangeKind::ThreadUpdated(id(7)));
    assert_eq!(s.threads.len(), 1);
    let thread = &s.threads[0];
    assert_eq!(thread.outcomes, outcomes);
    assert_eq!(thread.updated_at, later);
    assert_eq!(thread.state, ThreadState::Handled);
    assert!(thread.unseen);
    assert_eq!(thread.messages, [message(1), message(2)]);
    assert_eq!(s.digest(later).messages, 1);
}

#[test]
fn only_automatic_skips_break_the_group_and_never_fall_back_to_an_older_thread() {
    let mut s = state();
    s.add_rule(rule(3, RuleEffect::Skip(Matcher::default())), NOW)
        .unwrap();
    for n in 1..=2 {
        s.receive(message(n), "rail", id(n), NOW).unwrap();
        s.sort(
            id(n),
            Decision::Skip {
                reason: "Rule matched.".into(),
                rule: Some(id(3)),
            },
            NOW,
        )
        .unwrap();
    }
    s.receive(message(3), "rail", id(3), NOW).unwrap();
    s.sort(id(3), ask(), NOW).unwrap();
    s.answer(id(3), Suggestion::Leave, id(8), NOW).unwrap();
    s.receive(message(4), "rail", id(4), NOW).unwrap();
    assert_eq!(s.threads.len(), 3);
    assert_eq!(s.threads[2].messages, [message(3), message(4)]);
    assert!(matches!(
        s.threads[2].state,
        ThreadState::Skipped { rule: None, .. }
    ));
    assert!(s.tasks.is_empty());
    assert_eq!(
        s.digest(NOW),
        Digest {
            messages: 4,
            tasks: 0,
            facts: 0,
            skips: 3
        }
    );
}

#[test]
fn making_a_task_from_an_offered_choice_resolves_and_links_the_thread() {
    let mut s = state();
    s.receive(message(1), "rail", id(1), NOW).unwrap();
    s.sort(id(1), ask(), NOW).unwrap();
    assert_eq!(s.needs_you().threads, [id(1)]);
    let changes = s.answer(id(1), task_suggestion(), id(4), NOW).unwrap();
    assert_eq!(
        changes.iter().map(|c| c.kind.clone()).collect::<Vec<_>>(),
        [
            ChangeKind::TaskAdded(id(4)),
            ChangeKind::ThreadUpdated(id(1))
        ]
    );
    assert_eq!(s.needs_you(), NeedsYou::default());
    assert_eq!(s.threads[0].state, ThreadState::Handled);
    assert_eq!(s.threads[0].outcomes, [Outcome::Task(id(4))]);
    assert_eq!(s.tasks[0].column, Column::Todo);
    assert_eq!(s.tasks[0].from_thread, Some(id(1)));
    assert_eq!(s.tasks[0].added_by, Actor::Inbox(id(1)));
}

#[test]
fn rejected_inbox_commands_leave_messages_outcomes_activity_and_sequence_untouched() {
    let mut s = todo();
    s.receive(message(1), "rail", id(7), NOW).unwrap();
    let sorting = s.clone();
    assert!(matches!(
        s.answer(id(7), Suggestion::Leave, id(1), NOW),
        Err(TopicError::ThreadState(_))
    ));
    assert!(s.receive(message(1), "other", id(8), NOW).is_err());
    assert!(s.receive(message(2), "other", id(7), NOW).is_err());
    assert!(
        s.sort(
            id(7),
            Decision::Handle {
                summary: "Linked.".into(),
                outcomes: vec![Outcome::Task(id(404))]
            },
            NOW
        )
        .is_err()
    );
    assert!(
        s.sort(
            id(7),
            Decision::Skip {
                reason: "Skip.".into(),
                rule: Some(id(404))
            },
            NOW
        )
        .is_err()
    );
    assert!(s.mark_seen(id(404), NOW).is_err());
    assert_eq!(s, sorting);
    s.sort(id(7), ask(), NOW).unwrap();
    let asking = s.clone();
    assert!(s.sort(id(7), ask(), NOW).is_err());
    assert!(matches!(
        s.answer(
            id(7),
            Suggestion::MakeTask {
                title: "Other".into()
            },
            id(1),
            NOW
        ),
        Err(TopicError::SuggestionNotOffered(_))
    ));
    assert!(matches!(
        s.answer(id(7), task_suggestion(), id(9), NOW),
        Err(TopicError::DuplicateId(_))
    ));
    assert_eq!(s, asking);
}

#[test]
fn a_worker_can_revise_a_submission_and_the_approved_edit_is_logged() {
    let mut s = todo();
    s.start(id(9), "Reading six strings", NOW).unwrap();
    s.progress(id(9), "Opened PR.", NOW).unwrap();
    assert_eq!(s.tasks[0].worker.as_deref(), Some("Opened PR."));
    s.submit(
        id(9),
        action(),
        "Changed six strings",
        Some("Shortcuts".into()),
        NOW,
    )
    .unwrap();
    assert_eq!(
        s.tasks[0]
            .log
            .iter()
            .map(|l| l.text.as_str())
            .collect::<Vec<_>>(),
        [
            "Started work. Reading six strings.",
            "Updated progress. Opened PR.",
            "Requested approval for “Merge PR 2310”."
        ]
    );
    assert_eq!(s.needs_you().tasks, [id(9)]);
    assert!(s.tasks[0].worker.is_none());
    s.send_back(id(9), "Keep Pinned in settings.", NOW).unwrap();
    assert_eq!(s.tasks[0].column, Column::InProgress);
    assert!(
        s.tasks[0]
            .log
            .last()
            .unwrap()
            .text
            .contains("Keep Pinned in settings.")
    );
    assert!(s.needs_you().tasks.is_empty());
    s.submit(
        id(9),
        action(),
        "Changed five strings",
        Some("Open Shortcuts".into()),
        NOW,
    )
    .unwrap();
    let changes = s
        .approve(id(9), Some("Show Shortcuts".into()), NOW)
        .unwrap();
    assert_eq!(
        changes.last().unwrap().kind,
        ChangeKind::TaskApproved {
            task: id(9),
            offer_always: true
        }
    );
    let t = &s.tasks[0];
    assert_eq!(t.result.as_deref(), Some("Changed five strings"));
    assert_eq!(t.column, Column::Done);
    assert_eq!(t.draft.as_deref(), Some("Show Shortcuts"));
    assert_eq!(t.log.last().unwrap().text, "Approved “Merge PR 2310”.");
    assert_eq!(s.activity.last().unwrap().actor, Actor::User);
}

#[test]
fn an_existing_allow_rule_suppresses_the_offer_and_a_deny_blocks_approval() {
    let kind = action().kind;
    for (effect, expected) in [
        (RuleEffect::Allow(kind.clone()), false),
        (RuleEffect::Deny(kind.clone()), false),
        (RuleEffect::Ask(kind.clone()), true),
        (RuleEffect::Skip(Matcher::default()), true),
        (RuleEffect::Allow(ActionKind("different".into())), true),
    ] {
        let mut s = todo();
        s.start(id(9), "Editing", NOW).unwrap();
        s.submit(id(9), action(), "Ready", None, NOW).unwrap();
        let denied = matches!(&effect, RuleEffect::Deny(_));
        s.add_rule(rule(1, effect), NOW).unwrap();
        if denied {
            let before = s.clone();
            assert_eq!(
                s.approve(id(9), Some("Stale edit".into()), NOW),
                Err(TopicError::ActionDenied(id(1)))
            );
            assert_eq!(s, before);
            continue;
        }
        let changes = s.approve(id(9), None, NOW).unwrap();
        assert_eq!(
            changes.last().unwrap().kind,
            ChangeKind::TaskApproved {
                task: id(9),
                offer_always: expected
            }
        );
    }
}

#[test]
fn drags_update_the_board_and_unreviewed_work_completes_with_a_result() {
    let mut s = todo();
    for column in [
        Column::NeedsYou,
        Column::Done,
        Column::Todo,
        Column::InProgress,
    ] {
        let changes = s.move_task(id(9), column, NOW).unwrap();
        assert_eq!(changes.len(), 1);
        assert_eq!(s.tasks[0].column, column);
        assert_eq!(s.activity.last().unwrap().actor, Actor::User);
    }
    let before = s.clone();
    assert!(
        s.move_task(id(9), Column::InProgress, NOW)
            .unwrap()
            .is_empty()
    );
    assert_eq!(s, before);
    let changes = s.complete(id(9), "Report saved.", NOW).unwrap();
    assert_eq!(changes.len(), 1);
    assert_eq!(s.tasks[0].column, Column::Done);
    assert_eq!(s.tasks[0].result.as_deref(), Some("Report saved."));
}

#[test]
fn worker_and_review_commands_require_their_respective_columns() {
    let mut s = todo();
    let before = s.clone();
    for error in [
        s.progress(id(9), "Almost done", NOW),
        s.approve(id(9), Some("Edit".into()), NOW),
        s.send_back(id(9), "Try again", NOW),
        s.submit(id(9), action(), "Ready", None, NOW),
        s.complete(id(9), "Done", NOW),
    ] {
        assert_eq!(error, Err(TopicError::TaskColumn(id(9), Column::Todo)));
    }
    assert_eq!(
        s.start(id(404), "Reading", NOW),
        Err(TopicError::UnknownTask(id(404)))
    );
    assert!(
        s.add_task(id(9), "Duplicate", Actor::User, None, NOW)
            .is_err()
    );
    assert!(
        s.add_task(id(2), "No thread", Actor::User, Some(id(404)), NOW)
            .is_err()
    );
    assert_eq!(s, before);
    s.start(id(9), "Reading", NOW).unwrap();
    let before = s.clone();
    assert_eq!(
        s.start(id(9), "Duplicate", NOW),
        Err(TopicError::TaskColumn(id(9), Column::InProgress))
    );
    assert_eq!(s, before);
}

#[test]
fn superseding_keeps_provenance_and_removal_preserves_the_historical_digest() {
    let mut s = state();
    s.add_fact(fact(5), NOW).unwrap();
    let later = NOW + TimeDelta::days(1);
    let changes = s.supersede_fact(id(5), fact(6), later).unwrap();
    assert_eq!(changes[1].kind, ChangeKind::FactSuperseded(id(5), id(6)));
    assert_eq!(s.topic.facts[0].superseded_by, Some(id(6)));
    assert_eq!(s.topic.facts[0].provenance, fact(5).provenance);
    assert_eq!(s.topic.facts[1], fact(6));
    let before = s.clone();
    assert!(s.supersede_fact(id(5), fact(7), later).is_err());
    assert!(s.supersede_fact(id(6), fact(5), later).is_err());
    assert!(s.supersede_fact(id(404), fact(7), later).is_err());
    assert!(s.remove_fact(id(404), later).is_err());
    assert_eq!(s, before);
    s.remove_fact(id(5), later).unwrap();
    assert_eq!(s.topic.facts, [fact(6)]);
    assert!(s.add_fact(fact(5), later).is_err());
    assert_eq!(s.digest(NOW).facts, 2);
    assert_eq!(s.digest(later).facts, 1);
}

#[test]
fn context_changes_preserve_order_validate_references_and_describe_every_edit() {
    let mut s = state();
    let mut changes = s.set_mission("Simplify navigation.", NOW).unwrap();
    let goal = Goal {
        id: id(1),
        text: "Increase WAU".into(),
        progress: None,
    };
    changes.extend(s.add_goal(goal.clone(), NOW).unwrap());
    changes.extend(
        s.update_goal_progress(id(1), Some(target(3.1)), NOW)
            .unwrap(),
    );
    assert_eq!(s.topic.goals[0].progress, Some(target(3.1)));
    let policy = rule(2, RuleEffect::Ask(action().kind));
    changes.extend(s.add_rule(policy.clone(), NOW).unwrap());
    changes.extend(s.set_watch(vec![watch(3), watch(4)], NOW).unwrap());
    assert_eq!(s.topic.mission, "Simplify navigation.");
    assert_eq!(
        s.topic.watches().cloned().collect::<Vec<_>>(),
        [watch(3), watch(4)]
    );
    assert_eq!(s.topic.rules, std::slice::from_ref(&policy));
    let before = s.clone();
    assert!(s.add_goal(goal, NOW).is_err());
    assert!(s.update_goal_progress(id(99), None, NOW).is_err());
    assert!(
        s.update_goal_progress(id(1), Some(target(f64::INFINITY)), NOW)
            .is_err()
    );
    assert!(s.add_rule(policy, NOW).is_err());
    assert!(s.remove_rule(id(99), NOW).is_err());
    assert!(s.set_watch(vec![watch(4), watch(4)], NOW).is_err());
    assert_eq!(s, before);
    changes.extend(s.remove_rule(id(2), NOW).unwrap());
    assert!(s.topic.rules.is_empty());
    changes.extend(s.update_goal_progress(id(1), None, NOW).unwrap());
    assert_eq!(s.topic.goals[0].progress, None);
    assert_eq!(s.activity.len(), 7);
    for (i, change) in changes.iter().enumerate() {
        assert_eq!(change.seq, i as u64 + 1);
        assert_eq!(change.at, NOW);
        assert!(!s.activity[i].text.is_empty());
    }
}

fn envelope(n: u128, command: Command) -> Envelope {
    Envelope {
        id: id(n),
        topic: id(1),
        issued_at: NOW + TimeDelta::seconds(n as i64),
        command,
    }
}

#[test]
fn a_failed_compound_command_preserves_every_byte_including_history() {
    let mut s = todo();
    s.start(id(9), "Checking", NOW).unwrap();
    s.submit(id(9), action(), "Ready", None, NOW).unwrap();
    s.add_rule(rule(7, RuleEffect::Ask(action().kind)), NOW)
        .unwrap();
    let original = serde_json::to_vec(&s).unwrap();
    for command in [
        Command::Approve {
            task: id(9),
            expected_review: None,
            edited_draft: Some("Changed".into()),
            always: true,
            rule_id: id(7),
        },
        Command::Chat {
            message_id: id(3),
            text: "Review".into(),
            task_id: id(9),
            queue: false,
        },
        Command::CreateTopic {
            name: "Other".into(),
            mission: String::new(),
        },
        Command::SetTopicIcon {
            icon: TopicIcon {
                hedgehog: "unknown".into(),
                color: "ink".into(),
            },
        },
    ] {
        assert!(s.apply(&envelope(44, command)).is_err());
        assert_eq!(serde_json::to_vec(&s).unwrap(), original);
    }
    let wrong = Envelope {
        topic: id(80),
        ..envelope(
            22,
            Command::SetMission {
                mission: "Other".into(),
            },
        )
    };
    assert_eq!(s.apply(&wrong), Err(TopicError::WrongTopic(id(80))));
    assert_eq!(serde_json::to_vec(&s).unwrap(), original);
}

#[test]
fn topic_icon_survives_replication_and_legacy_snapshots_keep_their_default() {
    let mut creation = envelope(
        44,
        Command::CreateTopic {
            name: "Navigation".into(),
            mission: "Find usability issues".into(),
        },
    );
    creation.topic = id(32 << 96);
    let (mut state, _) = creation.create().unwrap();
    let (server, _) = creation.create_at(NOW + TimeDelta::seconds(1)).unwrap();
    let default = state.topic.display_icon();
    assert_eq!(server.topic.display_icon(), default);
    assert_eq!(state.topic.icon.as_ref(), Some(&default));

    let mut legacy = serde_json::to_value(&state).unwrap();
    legacy["topic"].as_object_mut().unwrap().remove("icon");
    let legacy: TopicState = serde_json::from_value(legacy).unwrap();
    assert_eq!(legacy.topic.display_icon().hedgehog, "wizard-1");
    assert_ne!(legacy.topic.display_icon().hedgehog, default.hedgehog);

    let icon = TopicIcon {
        hedgehog: "banana".into(),
        color: "plum".into(),
    };
    let command = Envelope {
        topic: creation.topic,
        ..envelope(45, Command::SetTopicIcon { icon: icon.clone() })
    };
    let replicated = serde_json::from_value(serde_json::to_value(command).unwrap()).unwrap();
    state.apply(&replicated).unwrap();
    let snapshot: TopicState =
        serde_json::from_value(serde_json::to_value(state).unwrap()).unwrap();
    assert_eq!(snapshot.topic.display_icon(), icon);
}

#[test]
fn withdrawing_a_replacement_keeps_the_link_and_retires_it_from_context() {
    let mut s = state();
    s.add_fact(fact(5), NOW).unwrap();
    s.supersede_fact(id(5), fact(6), NOW).unwrap();
    let changes = s.remove_fact(id(6), NOW).unwrap();
    assert_eq!(changes[0].kind, ChangeKind::FactRemoved(id(6)));
    assert!(s.topic.facts.iter().all(|fact| !fact.is_current()));
    assert_eq!(s.topic.facts[0].superseded_by, Some(id(6)));
    assert_eq!(s.topic.facts[1].withdrawn_at, Some(NOW));
    let before = s.clone();
    assert!(s.remove_fact(id(6), NOW).is_err());
    assert_eq!(s, before);
}

#[test]
fn joining_conversations_keeps_task_and_fact_sources_navigable() -> Result<(), TopicError> {
    let mut s = state();
    let (target, incoming) = (id(10), id(11));
    s.receive(message(2), "open", target, NOW)?;
    s.sort(target, ask(), NOW)?;
    s.receive(message(3), "pending", incoming, NOW)?;
    s.add_task(id(4), "Check", Actor::Inbox(incoming), Some(incoming), NOW)?;
    let mut sourced = fact(5);
    sourced.provenance.thread = Some(incoming);
    s.add_fact(sourced, NOW)?;
    s.join_thread(incoming, target, NOW)?;
    assert_eq!(s.threads.len(), 1);
    assert_eq!(s.tasks[0].from_thread, Some(target));
    assert_eq!(s.tasks[0].added_by, Actor::Inbox(target));
    assert_eq!(s.topic.facts[0].provenance.thread, Some(target));
    let before = s.clone();
    assert!(matches!(
        s.receive(message(6), "another", incoming, NOW),
        Err(TopicError::DuplicateId(_))
    ));
    assert_eq!(s, before);
    Ok(())
}

#[test]
fn answering_one_question_preserves_the_next_and_targets_its_original_message()
-> Result<(), TopicError> {
    let mut s = state();
    let thread = id(20);
    let first = message(1);
    let mut second = message(2);
    second.origin = Some(Source::Topic(id(44)).into_origin(
        second.author.clone(),
        NOW,
        second.external_id.clone(),
    ));
    s.receive(first.clone(), "shared", thread, NOW)?;
    s.receive(second.clone(), "shared", id(21), NOW)?;
    let draft = Suggestion::DraftReply {
        draft: "Confirmed".into(),
        task_title: "Reply".into(),
    };
    for m in [&first, &second] {
        s.decide_message(
            thread,
            m.id,
            Decision::Ask {
                reason: m.text.clone(),
                summary: m.text.clone(),
                suggestions: vec![draft.clone(), Suggestion::Leave],
            },
            NOW,
        )?;
    }
    let first_answer = envelope(
        40,
        Command::Answer {
            thread,
            expected_review: Some(0),
            suggestion: draft.clone(),
            task_id: id(50),
        },
    );
    s.apply(&first_answer)?;
    assert_eq!(
        s.tasks[0].action.as_ref().unwrap().payload["message"],
        serde_json::json!(first.id)
    );
    assert_eq!(s.threads[0].question_source, Some(second.id));
    let before = s.clone();
    assert_eq!(s.apply(&first_answer), Err(TopicError::StaleInboxReview));
    assert_eq!(s, before);
    s.apply(&envelope(
        41,
        Command::Reply {
            thread,
            text: "I will check.".into(),
        },
    ))?;
    assert_eq!(s.needs_you().threads, [thread]);
    s.apply(&envelope(
        42,
        Command::Answer {
            thread,
            expected_review: Some(1),
            suggestion: draft,
            task_id: id(51),
        },
    ))?;
    assert_eq!(
        s.tasks[1].action.as_ref().unwrap().payload["message"],
        serde_json::json!(second.id)
    );
    assert!(s.needs_you().threads.is_empty());
    Ok(())
}

#[test]
fn a_replacement_proposal_requires_its_own_approval_and_allowance() -> Result<(), TopicError> {
    let mut s = state();
    let task = id(3);
    s.add_task(task, "Review", Actor::User, None, NOW)?;
    s.start(task, "Investigating", NOW)?;
    s.submit(task, action(), "First proposal", Some("A".into()), NOW)?;
    let first = s.tasks[0].review_version;
    s.send_back(task, "Revise", NOW)?;
    s.submit(task, action(), "Second proposal", Some("B".into()), NOW)?;
    let current = s.tasks[0].review_version;
    let approve = |expected_review| Command::Approve {
        task,
        expected_review,
        edited_draft: None,
        always: false,
        rule_id: id(9),
    };
    let before = s.clone();
    assert_eq!(
        s.apply(&envelope(51, approve(Some(first)))),
        Err(TopicError::StaleTaskReview)
    );
    assert_eq!(
        s.apply(&envelope(52, approve(None))),
        Err(TopicError::StaleTaskReview)
    );
    assert_eq!(s, before);
    let allow = |expected_review, rule_id| Command::AllowReviewedAction {
        task,
        expected_review,
        action_kind: action().kind,
        rule_id,
    };
    s.apply(&envelope(53, approve(Some(current))))?;
    assert_eq!(
        s.apply(&envelope(54, allow(first + 1, id(9)))),
        Err(TopicError::StaleTaskReview)
    );
    // A different device could have approved this version with a different edited draft.
    assert_eq!(
        s.apply(&envelope(57, allow(current + 1, id(18)))),
        Err(TopicError::StaleTaskReview)
    );
    s.apply(&envelope(55, allow(current + 1, id(9))))?;
    s.move_task(task, Column::NeedsYou, NOW)?;
    s.move_task(task, Column::Done, NOW)?;
    assert_eq!(
        s.apply(&envelope(56, allow(s.tasks[0].review_version, id(9)))),
        Err(TopicError::StaleTaskReview)
    );
    Ok(())
}

#[test]
fn reopening_a_reviewed_reply_preserves_its_text_and_requires_a_new_action()
-> Result<(), TopicError> {
    let mut s = todo();
    let thread = id(22);
    let task = id(23);
    let reply = Suggestion::DraftReply {
        draft: "Confirmed".into(),
        task_title: "Reply".into(),
    };
    s.receive(message(1), "follow-up", thread, NOW)?;
    s.threads[0].parent_task = Some(s.tasks[0].id);
    s.sort(
        thread,
        Decision::Ask {
            summary: "Reply".into(),
            reason: "Confirm".into(),
            suggestions: vec![reply.clone()],
        },
        NOW,
    )?;
    s.answer(thread, reply, task, NOW)?;
    assert_eq!(s.tasks[1].parent, Some(s.tasks[0].id));
    s.approve(task, None, NOW)?;
    s.move_task(task, Column::NeedsYou, NOW)?;
    assert!(s.tasks[1].action.is_none());
    assert_eq!(s.tasks[1].draft.as_deref(), Some("Confirmed"));
    let changes = s.approve(task, None, NOW)?;
    assert!(matches!(
        changes.last().unwrap().kind,
        ChangeKind::TaskApproved {
            offer_always: false,
            ..
        }
    ));
    Ok(())
}

fn lead(
    s: &mut TopicState,
    n: u128,
    parent: TaskId,
    assignment: InboxAssignment,
    requires_permission: bool,
) -> Result<TaskId, TopicError> {
    let thread = id(1000 + n);
    s.receive(message(2000 + n), format!("lead-{n}"), thread, NOW)?;
    s.threads.last_mut().unwrap().parent_task = Some(parent);
    let task = id(3000 + n);
    s.add_inbox_task(
        task,
        thread,
        "Check source",
        assignment,
        requires_permission,
        NOW,
    )?;
    Ok(task)
}

#[test]
fn follow_up_admission_uses_topic_rules_for_agent_and_routine_work() -> Result<(), TopicError> {
    let mut s = todo();
    let root = s.tasks[0].id;
    let investigation = InboxAssignment::Investigate;
    let routine = InboxAssignment::Routine("stock".into());
    for n in 1..=3 {
        let task = lead(&mut s, n, root, investigation.clone(), false)?;
        assert!(s.tasks.last().unwrap().review_before_start);
        s.approve(task, None, NOW)?;
    }
    let task = lead(&mut s, 4, root, routine.clone(), false)?;
    assert!(s.tasks.last().unwrap().review_before_start);
    s.apply(&envelope(
        400,
        Command::Approve {
            task,
            always: true,
            expected_review: Some(0),
            edited_draft: None,
            rule_id: id(410),
        },
    ))?;
    let kind = ActionKind::start_follow_up();
    assert_eq!(
        s.topic.rules.last().unwrap().effect,
        RuleEffect::Allow(kind.clone())
    );
    for (n, assignment) in [(5, investigation.clone()), (6, routine.clone())] {
        lead(&mut s, n, root, assignment, false)?;
        assert_eq!(s.tasks.last().unwrap().column, Column::Todo);
    }
    lead(&mut s, 7, root, investigation.clone(), true)?;
    assert!(s.tasks.last().unwrap().review_before_start);
    for (n, effect) in [
        (8, RuleEffect::Ask(kind.clone())),
        (9, RuleEffect::Deny(kind)),
    ] {
        s.add_rule(
            Rule {
                id: id(n),
                text: "Restrict starts".into(),
                effect,
                from_task: None,
                created_at: NOW,
            },
            NOW,
        )?;
        let task = lead(&mut s, n, root, routine.clone(), false)?;
        assert!(s.tasks.last().unwrap().review_before_start);
        if n == 9 {
            assert_eq!(
                s.approve(task, None, NOW),
                Err(TopicError::ActionDenied(id(n)))
            );
        }
    }
    Ok(())
}

#[test]
fn a_reviewed_follow_up_can_add_a_rule_after_the_worker_starts() -> Result<(), TopicError> {
    let mut s = state();
    let task = lead(&mut s, 5, id(4), InboxAssignment::Investigate, false)?;
    s.apply(&envelope(
        6,
        Command::Approve {
            task,
            expected_review: Some(0),
            edited_draft: None,
            always: false,
            rule_id: id(7),
        },
    ))?;
    assert!(s.topic.rules.is_empty());
    s.start(task, "Checking", NOW)?;
    s.apply(&envelope(
        8,
        Command::AllowReviewedAction {
            task,
            expected_review: 1,
            action_kind: ActionKind::start_follow_up(),
            rule_id: id(7),
        },
    ))?;
    assert_eq!(s.topic.rules[0].from_task, Some(task));
    assert_eq!(
        s.topic.rules[0].effect,
        RuleEffect::Allow(ActionKind::start_follow_up())
    );
    Ok(())
}

#[test]
fn a_queued_start_rechecks_permission_and_rejects_a_new_denial() -> Result<(), TopicError> {
    let mut s = state();
    let kind = ActionKind::start_follow_up();
    let rule = |n, effect| Rule {
        id: id(n),
        effect,
        text: "Start policy".into(),
        from_task: None,
        created_at: NOW,
    };
    s.add_rule(rule(1, RuleEffect::Allow(kind.clone())), NOW)?;
    let task = lead(&mut s, 5, id(4), InboxAssignment::Investigate, false)?;
    assert_eq!(s.tasks[0].column, Column::Todo);
    s.remove_rule(id(1), NOW)?;
    s.review_follow_up_start(task, NOW)?;
    assert!(s.tasks[0].review_before_start);
    s.apply(&envelope(
        6,
        Command::Approve {
            task,
            expected_review: Some(0),
            edited_draft: None,
            always: false,
            rule_id: id(7),
        },
    ))?;
    s.add_rule(rule(8, RuleEffect::Deny(kind)), NOW)?;
    s.review_follow_up_start(task, NOW)?;
    assert_eq!(s.tasks[0].column, Column::NeedsYou);
    assert_eq!(
        s.approve(task, None, NOW),
        Err(TopicError::ActionDenied(id(8)))
    );
    Ok(())
}

#[test]
fn routine_question_task_keeps_source_context_and_custom_titles() {
    let body = "How should we handle this item?\n\nThe flag is now inactive.\n\nRollout details.";
    for (producer, offered, expected) in [
        (
            Producer::Routine("sort".into()),
            body,
            "The flag is now inactive.\n\nRollout details.",
        ),
        (
            Producer::Routine("sort".into()),
            "Review the rollout",
            "Review the rollout",
        ),
        (Producer::User, body, body),
    ] {
        let mut s = state();
        let mut source = message(1);
        source.producer = producer;
        source.text = body.into();
        s.receive(source, "source", id(7), NOW).unwrap();
        let suggestion = Suggestion::MakeTask {
            title: offered.into(),
        };
        s.decide_message(
            id(7),
            id(1),
            Decision::Ask {
                summary: body.into(),
                reason: body.into(),
                suggestions: vec![suggestion.clone()],
            },
            NOW,
        )
        .unwrap();
        s.answer(id(7), suggestion, id(9), NOW).unwrap();
        let task = &s.tasks[0];
        assert_eq!(task.title, expected);
        assert_eq!(task.from_thread, Some(id(7)));
        assert_eq!(task.source_message, Some(id(1)));
        assert_eq!(s.threads[0].messages[0].text, body);
    }
}

#[test]
fn report_task_is_explicit_linked_and_keeps_evidence() -> Result<(), TopicError> {
    let mut s = state();
    let mut m = message(20);
    m.producer = Producer::PostHogTask(id(30));
    m.text = "Checkout failed for three merchants.".into();
    s.receive(m, "report", id(21), NOW)?;
    let report = &mut s.threads[0];
    report.subject = "Checkout failures".into();
    report.report_sources = Some(ReportSources {
        references: vec![],
        evidence: vec![ReportEvidence {
            kind: None,
            at: None,
            description: "Error spike".into(),
            source_id: "https://example.org/chart".into(),
        }],
        observation: None,
        ..Default::default()
    });
    assert!(s.tasks.is_empty());
    s.apply(&envelope(
        22,
        Command::AddReportTask {
            thread: id(21),
            id: id(23),
            title: "Fix checkout".into(),
            instructions: "Implement a fix".into(),
        },
    ))?;
    let task = &s.tasks[0];
    assert_eq!(task.from_thread, Some(id(21)));
    assert!(task.queued);
    let instructions = task.instructions.as_ref().unwrap();
    assert!(instructions.contains("three merchants"));
    assert!(instructions.contains("Error spike"));
    assert!(instructions.contains("https://example.org/chart"));
    // Resolving closes the report with its reason; reopening clears it.
    s.apply(&envelope(
        24,
        Command::SetReportVerdict {
            thread: id(21),
            outcome: Some(ReportOutcome::Resolved),
            reason: "Fixed".into(),
        },
    ))?;
    let verdict = s.threads[0]
        .report_sources
        .as_ref()
        .unwrap()
        .verdict
        .as_ref()
        .unwrap();
    assert_eq!(
        (verdict.outcome, verdict.reason.as_str()),
        (ReportOutcome::Resolved, "Fixed")
    );
    s.apply(&envelope(
        25,
        Command::SetReportVerdict {
            thread: id(21),
            outcome: None,
            reason: String::new(),
        },
    ))?;
    assert!(
        s.threads[0]
            .report_sources
            .as_ref()
            .unwrap()
            .verdict
            .is_none()
    );
    Ok(())
}
