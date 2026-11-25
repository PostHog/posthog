//! Manual fixture benchmark: cargo test -p meep scroll_and_chat_timings -- --ignored --nocapture
use super::*;
use std::time::Instant;

#[gpui::test]
#[ignore]
fn scroll_and_chat_timings(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    ui.simulate_resize(size(px(1220.), px(780.)));
    let now = chrono::DateTime::UNIX_EPOCH;
    let id = TopicId(Uuid::new_v4());
    for count in [10, 100, 500] {
        let mut state = TopicState::new(Topic::new(id, "Performance fixture", now));
        for index in 0..count {
            state
                .add_task(
                    TaskId(Uuid::new_v4()),
                    format!("Fixture task {index}"),
                    Actor::User,
                    None,
                    now,
                )
                .unwrap();
        }
        ui.update(|_, cx| {
            desktop.update(cx, |s, cx| {
                s.states = vec![state];
                s.page = Page::Topic(id, Tab::Tasks, None);
                cx.notify();
            })
        });
        draw(ui);
        let mut scroll = Vec::new();
        for index in 0..30 {
            let start = Instant::now();
            ui.simulate_event(gpui::ScrollEvent {
                position: point(px(500.), px(350.)),
                delta: gpui::ScrollDelta::Pixels(point(
                    px(0.),
                    px(if index % 2 == 0 { -80. } else { 80. }),
                )),
                touch_phase: gpui::TouchPhase::Moved,
                ..Default::default()
            });
            draw(ui);
            if count >= 100 && index == 0 {
                ui.update(|_, cx| {
                    assert!(
                        desktop.read(cx).content_scroll.offset().y < px(0.),
                        "scroll must move the task list"
                    )
                });
            }
            scroll.push(start.elapsed().as_secs_f64() * 1000.);
        }
        let mut chat = Vec::new();
        for index in 0..20 {
            let start = Instant::now();
            ui.update(|_, cx| {
                desktop.update(cx, |s, cx| {
                    s.page = Page::Topic(
                        id,
                        if index % 2 == 0 {
                            Tab::Chat
                        } else {
                            Tab::Tasks
                        },
                        None,
                    );
                    cx.notify();
                })
            });
            draw(ui);
            chat.push(start.elapsed().as_secs_f64() * 1000.);
        }
        for (name, samples) in [
            ("scroll+draw", &mut scroll),
            ("chat toggle+draw", &mut chat),
        ] {
            samples.sort_by(f64::total_cmp);
            eprintln!(
                "{count} tasks {name}: p50={:.2}ms p95={:.2}ms max={:.2}ms",
                samples[samples.len() / 2],
                samples[(samples.len() * 95 / 100).min(samples.len() - 1)],
                samples[samples.len() - 1]
            );
        }
    }
}

/// Compare independently scaled inbox, board and topic-chat fixtures.
#[gpui::test]
#[ignore]
fn other_screen_timings(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    ui.simulate_resize(size(px(1220.), px(780.)));
    let now = chrono::DateTime::UNIX_EPOCH;
    let topic = TopicId(Uuid::new_v4());
    for count in [10, 100, 500] {
        for screen in ["inbox", "inbox+tasks", "report", "board", "chat"] {
            let mut state = TopicState::new(Topic::new(topic, "Performance fixture", now));
            if screen == "inbox+tasks" {
                for index in 0..count {
                    state
                        .add_task(
                            TaskId(Uuid::new_v4()),
                            format!("Fixture task {index}"),
                            Actor::User,
                            None,
                            now,
                        )
                        .unwrap();
                }
            }
            if screen == "board" {
                for index in 0..count {
                    state
                        .add_task(
                            TaskId(Uuid::new_v4()),
                            format!("Fixture task {index}"),
                            Actor::User,
                            None,
                            now,
                        )
                        .unwrap();
                }
            } else {
                let chat = screen == "chat";
                let chat_thread = ThreadId(Uuid::new_v4());
                for index in 0..count {
                    let id = if chat {
                        chat_thread
                    } else {
                        ThreadId(Uuid::new_v4())
                    };
                    let source = if chat {
                        Source::User
                    } else {
                        Source::Connection {
                            connection: "posthog".into(),
                            channel: "fixture".into(),
                        }
                    };
                    state
                        .receive(
                            Message {
                                id: MessageId(if chat && index == 0 {
                                    id.0
                                } else {
                                    Uuid::new_v4()
                                }),
                                producer: if chat {
                                    Producer::User
                                } else {
                                    Producer::System
                                },
                                origin: Some(source.into_origin("Fixture".into(), now, None)),
                                author: "Fixture".into(),
                                at: now,
                                text: format!(
                                    "Fixture message number {index}: a representative short update."
                                ),
                                external_id: None,
                            },
                            id.to_string(),
                            id,
                            now,
                        )
                        .unwrap();
                }
                assert_eq!(
                    if chat {
                        state.threads[0].messages.len()
                    } else {
                        state.threads.len()
                    },
                    count
                );
            }
            let report = state
                .threads
                .first()
                .map(|thread| Detail::Thread(thread.id));
            ui.update(|_, cx| {
                desktop.update(cx, |s, cx| {
                    s.states = vec![state];
                    s.page = Page::Topic(
                        topic,
                        if screen == "board" {
                            Tab::Tasks
                        } else {
                            Tab::Inbox
                        },
                        if screen == "report" { report } else { None },
                    );
                    s.task_display.boards.clear();
                    if screen == "board" {
                        s.task_display.boards.insert(topic);
                    }
                    if screen == "chat" {
                        s.page = Page::Topic(topic, Tab::Chat, None);
                    }
                    cx.notify();
                })
            });
            draw(ui);
            let mut timings = Vec::new();
            for _ in 0..20 {
                let start = Instant::now();
                draw(ui);
                timings.push(start.elapsed().as_secs_f64() * 1000.);
            }
            timings.sort_by(f64::total_cmp);
            eprintln!(
                "{count} {screen} redraw: p50={:.2}ms p95={:.2}ms",
                timings[10], timings[19]
            );
        }
    }
}

/// Measure the animation frames while the Overview opens and closes.
#[gpui::test]
#[ignore]
fn overview_motion_timings(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    ui.simulate_resize(size(px(1220.), px(780.)));
    ui.update(|_, cx| {
        ui::motion::set_input(ui::motion::InputOrigin::Pointer, cx);
        cx.set_reduce_motion(false);
    });
    let now = chrono::DateTime::UNIX_EPOCH;
    let topic = TopicId(Uuid::new_v4());
    for (count, message_count) in [(10, 0), (100, 0), (500, 0), (100, 100), (100, 500)] {
        let mut state = TopicState::new(Topic::new(topic, "Performance fixture", now));
        for index in 0..count {
            state
                .add_task(
                    TaskId(Uuid::new_v4()),
                    format!("Fixture task {index}"),
                    Actor::User,
                    None,
                    now,
                )
                .unwrap();
        }
        let thread = ThreadId(Uuid::new_v4());
        for index in 0..message_count {
            state
                .receive(
                    Message {
                        id: MessageId(if index == 0 { thread.0 } else { Uuid::new_v4() }),
                        producer: Producer::User,
                        origin: Some(Source::User.into_origin("Fixture".into(), now, None)),
                        author: "Fixture".into(),
                        at: now,
                        text: format!(
                            "Fixture message number {index}: a representative short update."
                        ),
                        external_id: None,
                    },
                    thread.to_string(),
                    thread,
                    now,
                )
                .unwrap();
        }
        ui.update(|_, cx| {
            desktop.update(cx, |s, cx| {
                s.states = vec![state];
                s.page = Page::Topic(topic, Tab::Tasks, None);
                s.overview_hidden = true;
                cx.notify();
            })
        });
        draw(ui);
        let mut timings = Vec::new();
        let mut widths = Vec::new();
        for visible in [true, false] {
            ui.update(|_, cx| {
                desktop.update(cx, |s, cx| {
                    s.overview_hidden = !visible;
                    cx.notify();
                })
            });
            draw(ui);
            for _ in 0..16 {
                ui.executor()
                    .advance_clock(std::time::Duration::from_millis(16));
                let start = Instant::now();
                let width = ui.update(|w, cx| {
                    w.simulate_next_frame(cx);
                    w.draw(cx).clear(cx);
                    let key = format!("{:?}]", ElementId::from("topic-overview-slot"));
                    w.visual_elements()
                        .iter()
                        .find(|e| e.element_id.ends_with(&key))
                        .map(|e| f32::from(e.bounds.size.width))
                        .unwrap_or_default()
                });
                timings.push(start.elapsed().as_secs_f64() * 1000.);
                widths.push(width);
            }
        }
        let low = widths.iter().copied().fold(f32::INFINITY, f32::min);
        let high = widths.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        assert!(high - low > 100., "chat slot did not animate: {widths:?}");
        timings.sort_by(f64::total_cmp);
        eprintln!(
            "{count} tasks {message_count} messages chat motion: p50={:.2}ms p95={:.2}ms max={:.2}ms",
            timings[16], timings[30], timings[31]
        );
    }
}

#[gpui::test]
fn virtual_inbox_scroll_reaches_distant_thread(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    ui.simulate_resize(size(px(1220.), px(780.)));
    let now = chrono::DateTime::UNIX_EPOCH;
    let topic = TopicId(Uuid::new_v4());
    let mut state = TopicState::new(Topic::new(topic, "Performance fixture", now));
    let mut ids = Vec::new();
    for index in 0..100 {
        let id = ThreadId(Uuid::new_v4());
        ids.push(id);
        state
            .receive(
                Message {
                    id: MessageId(Uuid::new_v4()),
                    producer: Producer::PostHogTask(TaskId(Uuid::new_v4())),
                    origin: Some(
                        Source::Connection {
                            connection: "posthog".into(),
                            channel: "fixture".into(),
                        }
                        .into_origin("Fixture".into(), now, None),
                    ),
                    author: "Fixture".into(),
                    at: now,
                    text: format!("Message {index}"),
                    external_id: None,
                },
                id.to_string(),
                id,
                now,
            )
            .unwrap();
        state.threads.last_mut().unwrap().report_sources = Some(meep_topic::ReportSources {
            references: vec![],
            evidence: vec![],
            observation: None,
            ..Default::default()
        });
    }
    ui.update(|_, cx| {
        desktop.update(cx, |s, cx| {
            s.states = vec![state];
            s.page = Page::Topic(topic, Tab::Inbox, None);
            cx.notify();
        })
    });
    draw(ui);
    ui.simulate_event(gpui::ScrollEvent {
        position: point(px(500.), px(350.)),
        // Row 50 of 56pt inbox rows.
        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-2650.))),
        touch_phase: gpui::TouchPhase::Moved,
        ..Default::default()
    });
    draw(ui);
    let target = ids[50];
    click(ui, &format!("thread-{target}"));
    ui.update(|_, cx| {
        assert_eq!(
            desktop.read(cx).page,
            Page::Topic(topic, Tab::Inbox, Some(Detail::Thread(target)))
        )
    });
}

#[gpui::test]
fn virtual_task_scroll_reaches_and_opens_distant_row(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    ui.simulate_resize(size(px(1220.), px(1400.)));
    let now = chrono::DateTime::UNIX_EPOCH;
    let topic = TopicId(Uuid::new_v4());
    let mut state = TopicState::new(Topic::new(topic, "Performance fixture", now));
    let mut ids = Vec::new();
    for index in 0..100 {
        let id = TaskId(Uuid::new_v4());
        ids.push(id);
        state
            .add_task(id, format!("Fixture task {index}"), Actor::User, None, now)
            .unwrap();
    }
    ui.update(|_, cx| {
        desktop.update(cx, |s, cx| {
            s.states = vec![state];
            s.page = Page::Topic(topic, Tab::Tasks, None);
            cx.notify();
        })
    });
    draw(ui);
    // The first draw must cover a viewport taller than the usual window.
    let tall_row = format!(
        "{:?}]",
        ElementId::from(SharedString::from(format!("card-{}", ids[24])))
    );
    ui.update(|w, _| {
        assert!(
            w.visual_elements()
                .iter()
                .any(|e| e.element_id.ends_with(&tall_row))
        );
    });
    ui.simulate_event(gpui::ScrollEvent {
        position: point(px(500.), px(350.)),
        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-3000.))),
        touch_phase: gpui::TouchPhase::Moved,
        ..Default::default()
    });
    draw(ui);
    let target = ids[72];
    click(ui, &format!("card-{target}"));
    ui.update(|_, cx| {
        assert_eq!(
            desktop.read(cx).page,
            Page::Topic(topic, Tab::Tasks, Some(Detail::Task(target)))
        )
    });
    // Keyboard selection may jump beyond the currently rendered window.
    for _ in 0..27 {
        ui.simulate_keystrokes("down");
    }
    draw(ui);
    ui.update(|w, cx| {
        w.simulate_next_frame(cx);
        w.draw(cx).clear(cx);
        let desktop = desktop.read(cx);
        assert_eq!(
            desktop.page,
            Page::Topic(topic, Tab::Tasks, Some(Detail::Task(ids[99])))
        );
        assert!(
            desktop.selection_bounds.bounds().bottom()
                <= desktop.content_scroll.bounds().bottom() + px(1.)
        );
    });
}

#[gpui::test]
fn virtual_chat_scroll_and_append(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    ui.simulate_resize(size(px(1220.), px(780.)));
    let now = chrono::DateTime::UNIX_EPOCH;
    let topic = TopicId(Uuid::new_v4());
    let thread = ThreadId(Uuid::new_v4());
    let mut state = TopicState::new(Topic::new(topic, "Performance fixture", now));
    for index in 0..100 {
        state
            .receive(
                Message {
                    id: MessageId(if index == 0 { thread.0 } else { Uuid::new_v4() }),
                    producer: Producer::User,
                    origin: Some(Source::User.into_origin("Fixture".into(), now, None)),
                    author: "Fixture".into(),
                    at: now,
                    text: if index % 3 == 0 {
                        format!("Message number {index}: this longer update wraps onto several lines so the history has rows of different heights. The view should keep its position when selecting text.")
                    } else {
                        format!("Message number {index}")
                    },
                    external_id: None,
                },
                thread.to_string(),
                thread,
                now,
            )
            .unwrap();
    }
    ui.update(|_, cx| {
        desktop.update(cx, |s, cx| {
            s.states = vec![state];
            s.page = Page::Topic(topic, Tab::Chat, None);
            cx.notify();
        })
    });
    draw(ui);
    // A conversation opens at its newest message.
    let newest = format!("user-turn-{topic}-99");
    ui.update(|w, cx| {
        assert!(
            desktop.read(cx).chat_list.borrow().is_some(),
            "virtual list must be active"
        );
        assert!(
            w.visual_elements()
                .iter()
                .any(|e| e.element_id.contains(&newest)),
            "newest message must render"
        );
    });
    // The list measures rows as they come into view, so scroll up in steps.
    for _ in 0..40 {
        ui.simulate_event(gpui::ScrollEvent {
            position: point(px(560.), px(350.)),
            delta: gpui::ScrollDelta::Pixels(point(px(0.), px(2_000.))),
            touch_phase: gpui::TouchPhase::Moved,
            ..Default::default()
        });
        draw(ui);
    }
    let first = format!("user-turn-{topic}-0");
    ui.update(|w, _| {
        assert!(
            w.visual_elements()
                .iter()
                .any(|e| e.element_id.contains(&first)),
            "scrolling up reaches the first message"
        );
    });
    let bounds = |ui: &mut VisualTestContext, id: String| {
        let key = format!("{:?}]", ElementId::from(SharedString::from(id)));
        ui.update(|w, _| {
            w.visual_elements()
                .iter()
                .rev()
                .find(|e| e.element_id.ends_with(&key))
                .map(|e| e.bounds)
                .expect("message text is visible")
        })
    };
    let first = bounds(ui, format!("{topic}-0-text"));
    let second = bounds(ui, format!("{topic}-1-text"));
    let from = point(first.origin.x + px(1.), first.origin.y + px(5.));
    let to = point(second.right() - px(1.), second.center().y);
    let modifiers = Modifiers::default();
    ui.simulate_mouse_move(from, None, modifiers);
    ui.simulate_mouse_down(from, MouseButton::Left, modifiers);
    ui.simulate_mouse_move(to, MouseButton::Left, modifiers);
    ui.simulate_mouse_up(to, MouseButton::Left, modifiers);
    draw(ui);
    ui.simulate_keystrokes("cmd-c");
    let copied = ui
        .read_from_clipboard()
        .and_then(|item| item.text())
        .unwrap();
    assert!(copied.contains("Message number 0"), "{copied:?}");
    assert!(copied.contains("Message number 1"), "{copied:?}");
    ui.simulate_event(gpui::ScrollEvent {
        position: point(px(560.), px(350.)),
        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-2000.))),
        touch_phase: gpui::TouchPhase::Moved,
        ..Default::default()
    });
    draw(ui);
    ui.update(|_, cx| cx.write_to_clipboard(ClipboardItem::new_string("sentinel".into())));
    ui.simulate_keystrokes("cmd-c");
    assert_eq!(
        ui.read_from_clipboard().and_then(|item| item.text()),
        Some(copied.clone()),
        "scrolling must preserve the selected transcript text"
    );
    ui.update(|_, cx| {
        desktop.update(cx, |s, cx| {
            s.states[0]
                .receive(
                    Message {
                        id: MessageId(Uuid::new_v4()),
                        producer: Producer::User,
                        origin: Some(Source::User.into_origin("Fixture".into(), now, None)),
                        author: "Fixture".into(),
                        at: now,
                        text: "Reply while selecting".into(),
                        external_id: None,
                    },
                    thread.to_string(),
                    thread,
                    now,
                )
                .unwrap();
            cx.notify();
        })
    });
    draw(ui);
    ui.update(|_, cx| cx.write_to_clipboard(ClipboardItem::new_string("sentinel".into())));
    ui.simulate_keystrokes("cmd-c");
    assert_eq!(
        ui.read_from_clipboard().and_then(|item| item.text()),
        Some(copied),
        "an incoming reply must not clear the selection"
    );
    ui.update(|w, cx| {
        gpui_kit::base::TextSelection::clear(w, cx);
        w.refresh();
    });
    draw(ui);
    ui.simulate_event(gpui::ScrollEvent {
        position: point(px(560.), px(350.)),
        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-2000.))),
        touch_phase: gpui::TouchPhase::Moved,
        ..Default::default()
    });
    draw(ui);
    let before = ui.update(|_, cx| {
        desktop
            .read(cx)
            .chat_list
            .borrow()
            .as_ref()
            .unwrap()
            .list
            .logical_scroll_top()
            .item_ix
    });
    assert!(before > 0, "chat must scroll");
    let later = bounds(ui, format!("{topic}-{}-text", before + 2));
    let from = point(later.origin.x + px(1.), later.center().y);
    let to = point(later.right() - px(1.), later.center().y);
    ui.simulate_mouse_move(from, None, modifiers);
    ui.simulate_mouse_down(from, MouseButton::Left, modifiers);
    ui.simulate_mouse_move(to, MouseButton::Left, modifiers);
    ui.simulate_mouse_up(to, MouseButton::Left, modifiers);
    draw(ui);
    ui.update(|w, cx| {
        w.simulate_next_frame(cx);
        w.draw(cx).clear(cx);
    });
    let later_during_selection = bounds(ui, format!("{topic}-{}-text", before + 2));
    assert!(
        (later_during_selection.origin.y - later.origin.y).abs() < px(2.),
        "starting a selection must keep the same message in place"
    );
    ui.update(|w, cx| {
        gpui_kit::base::TextSelection::clear(w, cx);
        w.refresh();
    });
    draw(ui);
    let later_after_selection = bounds(ui, format!("{topic}-{}-text", before + 2));
    assert!(
        (later_after_selection.origin.y - later_during_selection.origin.y).abs() < px(2.),
        "ending a selection must keep the same message in place"
    );
    let before = ui.update(|_, cx| {
        desktop
            .read(cx)
            .chat_list
            .borrow()
            .as_ref()
            .unwrap()
            .list
            .logical_scroll_top()
            .item_ix
    });
    ui.update(|_, cx| {
        desktop.update(cx, |s, cx| {
            s.states[0]
                .receive(
                    Message {
                        id: MessageId(Uuid::new_v4()),
                        producer: Producer::User,
                        origin: Some(Source::User.into_origin("Fixture".into(), now, None)),
                        author: "Fixture".into(),
                        at: now,
                        text: "New reply".into(),
                        external_id: None,
                    },
                    thread.to_string(),
                    thread,
                    now,
                )
                .unwrap();
            cx.notify();
        })
    });
    draw(ui);
    ui.update(|_, cx| {
        let desktop = desktop.read(cx);
        let cache = desktop.chat_list.borrow();
        let list = &cache.as_ref().unwrap().list;
        assert_eq!(list.item_count(), 102);
        assert_eq!(
            list.logical_scroll_top().item_ix,
            before,
            "appending must preserve the reading position"
        );
    });
}
