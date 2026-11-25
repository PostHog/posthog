use super::*;
use meep_topic::*;

const NOW: DateTime<Utc> = DateTime::UNIX_EPOCH;

fn rule_id(n: u8) -> RuleId {
    format!("00000000-0000-0000-0000-{n:012x}").parse().unwrap()
}

fn rule(n: u8, effect: RuleEffect) -> Rule {
    Rule {
        id: rule_id(n),
        text: "Test rule.".into(),
        effect,
        from_task: None,
        created_at: NOW,
    }
}

fn action(kind: &str) -> Action {
    Action {
        depends_on_facts: None,
        kind: ActionKind(kind.into()),
        label: "Merge PR".into(),
        done_label: "Merged PR".into(),
        payload: Default::default(),
    }
}

#[test]
fn the_last_matching_action_rule_decides_and_reports_its_own_id() {
    let merge = action("merge-pr");
    let kind = merge.kind.clone();
    let mut rules = vec![rule(1, RuleEffect::Deny(kind.clone()))];
    assert_eq!(decide(&rules, &merge), Verdict::Refuse(rule_id(1)));
    rules.push(rule(2, RuleEffect::Allow(kind.clone())));
    rules.push(rule(3, RuleEffect::Skip(Matcher::default())));
    rules.push(rule(4, RuleEffect::Deny(ActionKind("copy-change".into()))));
    assert_eq!(decide(&rules, &merge), Verdict::Run(rule_id(2)));
    rules.push(rule(5, RuleEffect::Ask(kind)));
    assert_eq!(decide(&rules, &merge), Verdict::Ask(Some(rule_id(5))));
    assert_eq!(decide(&rules, &action("custom-action")), Verdict::Ask(None));
}

#[test]
fn connection_and_channel_select_candidates_in_reverse_precedence_order() {
    let mut state = fixtures::new_web().unwrap();
    let mut message = state.threads.remove(0).messages.remove(0);
    let matcher = Matcher {
        connection: Some("slack".into()),
        channel: Some("#new-web".into()),
    };
    let rules = [
        rule(1, RuleEffect::Skip(Matcher::default())),
        rule(2, RuleEffect::Skip(matcher)),
    ];
    assert_eq!(
        skip_candidates(&rules, &message)
            .map(|r| r.id)
            .collect::<Vec<_>>(),
        [rule_id(2), rule_id(1)]
    );
    for source in [
        Source::User,
        Source::Topic(state.topic.id),
        Source::Connection {
            connection: "github".into(),
            channel: "#new-web".into(),
        },
        Source::Connection {
            connection: "slack".into(),
            channel: "#general".into(),
        },
    ] {
        message.origin = Some(source.into_origin(
            message.author.clone(),
            message.at,
            message.external_id.clone(),
        ));
        assert_eq!(skip_candidates(&rules[1..], &message).next(), None);
    }
}

fn run_limit(max_runs_per_hour: usize) -> Limits {
    Limits {
        max_hops: 0,
        max_runs_per_hour,
    }
}

#[test]
fn run_capacity_recovers_one_start_at_a_time_at_the_hour_boundary() {
    let limits = run_limit(2);
    let mut window = RunWindow::default();
    assert!(window.try_start(NOW, limits));
    assert!(window.try_start(NOW + TimeDelta::minutes(10), limits));
    assert!(!window.try_start(NOW + TimeDelta::minutes(59), limits));
    let mut restored: RunWindow =
        serde_json::from_value(serde_json::to_value(window).unwrap()).unwrap();
    assert!(restored.has_capacity(NOW + TimeDelta::minutes(10), run_limit(3)));
    assert!(restored.try_start(NOW + TimeDelta::hours(1), limits));
    assert!(!restored.try_start(NOW + TimeDelta::minutes(69), limits));
    assert!(restored.try_start(NOW + TimeDelta::minutes(70), limits));
}

#[test]
fn a_zero_budget_and_a_clock_rollback_do_not_admit_extra_runs() {
    let mut window = RunWindow::default();
    assert!(!window.try_start(NOW, run_limit(0)));
    let limits = run_limit(2);
    assert!(window.try_start(NOW, limits));
    assert!(!window.try_start(NOW - TimeDelta::seconds(1), limits));
    assert!(window.try_start(NOW, limits));
    assert!(!window.try_start(NOW, limits));
}
