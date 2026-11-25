use super::*;
use chrono::Utc;

#[gpui::test]
fn passive_context_sources_do_not_subscribe_or_show_activity(cx: &mut TestAppContext) {
    let now = Utc::now();
    let topic = TopicId(Uuid::new_v4());
    let mut state = TopicState::new(Topic::new(topic, "Context fixture", now));
    let source = Watch {
        id: WatchId(Uuid::new_v4()),
        connection: "posthog".into(),
        kind: "flag".into(),
        key: "fixture".into(),
        label: "Fixture flag".into(),
    };
    state.set_context_sources(vec![source], now).unwrap();
    assert_eq!(state.topic.watches().count(), 0);
    let lab = Lab::with_snapshots([state]).unwrap();
    lab.runtime
        .block_on(lab.backend.client.sync_once())
        .unwrap();
    let (view, ui) = fixture(&lab, cx);
    ui.update(|w, cx| {
        view.update(cx, |s, cx| {
            s.go(Page::Topic(topic, Tab::Linked, None), w, cx)
        })
    });
    let rendered = labels(ui);
    assert!(rendered.iter().any(|s| s == "Fixture flag"), "{rendered:?}");
    assert!(
        !rendered
            .iter()
            .any(|s| s.contains("this week") || s == "Sorted by Meep"),
        "{rendered:?}"
    );
    let row = center(ui, "context-source-0");
    ui.simulate_mouse_move(row, None, Modifiers::default());
    draw(ui);
    click(ui, "unwatch-0");
    let after = lab.backend.client.topic(topic).unwrap().unwrap();
    assert!(after.topic.context_sources.is_empty());
    assert_eq!(after.topic.watches().count(), 0);
}
