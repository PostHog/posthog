use super::overview::{goal_measure, goal_on_track};
use super::pages::{ago, count};
use super::*;
use chrono::Utc;
use meep_shell::settings::{self as set, Tone, group, header, section};
use meep_ui::gpui_kit::component::input::{Enter, Textarea};
use meep_ui::gpui_kit::component::{Icon, Sizable, switch::Switch};

pub(super) fn row(id: impl Into<SharedString>) -> Stateful<Div> {
    ui::row()
        .id(ElementId::Name(id.into()))
        .w_full()
        .min_h(px(60.))
        .px(px(set::ROW_X))
        .py(px(10.))
        .gap(px(12.))
}

pub(super) fn nav_row(id: impl Into<SharedString>) -> Stateful<Div> {
    row(id)
        .role(Role::Button)
        .cursor_pointer()
        .hover(|s| s.bg(ui::ink(0x05)))
        .active(|s| s.bg(ui::ink(0x0a)))
}

pub(super) fn chevron() -> Icon {
    Icon::new(Glyph::ChevronRight)
        .size(px(14.))
        .text_color(rgb(ui::theme::get(2)))
}

pub(super) fn glyph_tile(glyph: Glyph) -> Div {
    set::tile().child(ui::nav::glyph(glyph, false))
}

pub(super) fn hover_remove(
    group_name: SharedString,
    id: impl Into<SharedString>,
    label: &'static str,
    cx: &Context<Desktop>,
    f: impl Fn(&mut Desktop) + 'static,
) -> Div {
    div()
        .flex_none()
        .opacity(0.)
        .group_hover(group_name, |s| s.opacity(1.))
        .child(
            ui::icon_button(ElementId::Name(id.into()), Glyph::X, label).on_click(cx.listener(
                move |s, _, _, cx| {
                    cx.stop_propagation();
                    f(s);
                    cx.notify()
                },
            )),
        )
}

pub(super) fn wrap_copy(title: impl Into<SharedString>, detail: impl Into<SharedString>) -> Div {
    let detail: SharedString = detail.into();
    ui::column()
        .flex_1()
        .min_w_0()
        .gap(px(2.))
        .child(
            div()
                .text_size(px(13.))
                .line_height(px(18.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(ui::theme::color(ui::INK)))
                .child(title.into()),
        )
        .when(!detail.is_empty(), |c| {
            c.child(
                div()
                    .text_size(px(12.))
                    .line_height(px(17.))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .child(detail),
            )
        })
}

pub(super) fn empty_group(title: &str, detail: &str) -> Div {
    group([set::empty(title.to_owned(), detail.to_owned()).into_any_element()])
}

fn status_for(g: &meep_topic::Goal) -> (&'static str, Tone) {
    let (_, ratio, _) = goal_measure(g);
    match (ratio.is_some(), goal_on_track(g)) {
        (false, _) => ("No data", Tone::Neutral),
        (true, true) => ("On track", Tone::Positive),
        (true, false) => ("Off track", Tone::Warning),
    }
}

fn goal_summary(g: &meep_topic::Goal) -> String {
    match &g.progress {
        Some(Progress::Target {
            current,
            target,
            unit,
        }) => format!("Target · {current} of {target} {unit}"),
        Some(Progress::Guardrail {
            current,
            low,
            high,
            unit,
        }) => format!("Guardrail · {current} {unit}, keep within {low}–{high}"),
        None => "Not measured yet".into(),
    }
}

impl Desktop {
    pub(super) fn mission_page(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let t = &state.topic;
        let id = t.id;
        let start_edit = move |s: &mut Self, w: &mut Window, cx: &mut Context<Self>| {
            if let Some(state) = s.states.iter().find(|state| state.topic.id == id) {
                s.editing = true;
                s.mission_edit.update(cx, |e, cx| {
                    e.set_value(state.topic.mission.clone(), w, cx);
                    e.focus(w, cx);
                });
                cx.notify();
            }
        };
        let body = if self.editing {
            group([
                set::field(
                    "Mission",
                    "",
                    div()
                        .w_full()
                        .on_action(cx.listener(|s, _: &Enter, w, cx| {
                            s.save_mission(w, cx);
                            cx.notify();
                        }))
                        .child(
                            Textarea::new(&self.mission_edit)
                                .aria_label("Mission")
                                .text_size(px(15.))
                                .line_height(relative(1.4)),
                        ),
                )
                .into_any_element(),
                set::footer(
                    ui::row()
                        .gap(px(8.))
                        .child(control(
                            "cancel-mission",
                            "Cancel",
                            false,
                            cx,
                            |s, w, cx| {
                                s.editing = false;
                                s.focus.focus(w, cx);
                            },
                        ))
                        .child(control("save-mission", "Save", true, cx, |s, w, cx| {
                            s.save_mission(w, cx)
                        })),
                )
                .into_any_element(),
            ])
        } else if t.mission.trim().is_empty() {
            group([set::item(
                "No mission yet",
                "Write what this topic works toward.",
                control(
                    "edit-mission",
                    "Write mission",
                    false,
                    cx,
                    move |s, w, cx| start_edit(s, w, cx),
                ),
            )
            .into_any_element()])
        } else {
            group([row("mission-text")
                .items_start()
                .py(px(14.))
                .child(
                    div()
                        .flex_1()
                        .min_w_0()
                        .text_size(px(15.))
                        .line_height(relative(1.4))
                        .font_weight(FontWeight::MEDIUM)
                        .child(t.mission.clone()),
                )
                .child(control(
                    "edit-mission",
                    "Edit",
                    false,
                    cx,
                    move |s, w, cx| start_edit(s, w, cx),
                ))
                .into_any_element()])
        };
        let now = Utc::now();
        let usage = &state.usage;
        let day = usage
            .days
            .get(&now.date_naive())
            .cloned()
            .unwrap_or_default();
        let (week_calls, week_runs) = usage.days.values().fold((0, 0), |(c, r), d| {
            (c + d.system_one, r + d.routine_dispatches)
        });
        let usage_row = |label: &'static str, detail: &'static str, value: String| {
            set::item(label, detail, set::value_text(value)).into_any_element()
        };
        ui::column()
            .child(header(
                "Mission",
                "What this topic works toward. The agent reads it before every task.",
                None,
            ))
            .child(body)
            .child(section(
                "Usage",
                "The work that the agent did for this topic.",
                None,
                false,
            ))
            .child(group([
                usage_row(
                    "Agent starts",
                    "In the last hour, against the hourly limit",
                    format!("{} of {}", usage.last_hour(now), usage.hourly_cap),
                ),
                usage_row(
                    "Sorting calls",
                    "Inbox items the agent sorted",
                    format!("{} today · {week_calls} this week", day.system_one),
                ),
                usage_row(
                    "Workflow runs",
                    "Routines that the agent started",
                    format!("{} today · {week_runs} this week", day.routine_dispatches),
                ),
            ]))
    }

    pub(super) fn goals_page(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let add = control("add-goal", "Add a goal", false, cx, |s, w, cx| {
            s.ask_in_chat("Add a goal for this topic: ", w, cx)
        })
        .into_any_element();
        let body = if state.topic.goals.is_empty() {
            empty_group(
                "No goals yet",
                "Tell the agent in chat what success looks like.",
            )
        } else {
            group(state.topic.goals.iter().map(|g| {
                let gid = g.id;
                let (status, tone) = status_for(g);
                nav_row(format!("goal-{gid}"))
                    .aria_label(SharedString::from(g.text.clone()))
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(Page::Topic(id, Tab::Goals, Some(Detail::Goal(gid))), w, cx)
                    }))
                    .child(glyph_tile(Glyph::Target))
                    .child(wrap_copy(g.text.clone(), goal_summary(g)))
                    .child(set::status(status, tone))
                    .child(chevron())
                    .into_any_element()
            }))
        };
        ui::column()
            .child(header(
                "Goals",
                "What success looks like for this topic. Open a goal to see its progress.",
                Some(add),
            ))
            .child(body)
    }

    pub(super) fn facts_page(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let t = &state.topic;
        let id = t.id;
        let now = Utc::now();
        let mut current: Vec<&Fact> = t.facts.iter().filter(|f| f.is_current()).collect();
        current.sort_by_key(|f| std::cmp::Reverse(f.provenance.at));
        let disputed = state.disputed_facts();
        let replaced = t
            .facts
            .iter()
            .filter(|f| f.superseded_by.is_some() || f.invalidated_by.is_some())
            .count();
        let sources: std::collections::BTreeSet<&str> = current
            .iter()
            .map(|f| f.provenance.author.as_str())
            .collect();
        let summary = current
            .iter()
            .map(|f| f.provenance.at)
            .max()
            .map(|latest| {
                format!(
                    "{} from {} · latest {}",
                    count(current.len(), "fact"),
                    count(sources.len(), "source"),
                    ago(now - latest)
                )
            })
            .unwrap_or_default();
        let footnote = [
            summary,
            if replaced > 0 {
                format!(
                    "{} replaced with newer facts",
                    count(replaced, "earlier fact")
                )
            } else {
                String::new()
            },
        ]
        .into_iter()
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" · ");
        let body = if current.is_empty() {
            empty_group(
                "No facts yet",
                "The agent adds facts when it reads the inbox. Each fact links to its source.",
            )
        } else {
            group(current.into_iter().map(|f| {
                let fid = f.id;
                let hover = SharedString::from(format!("fact-{fid}"));
                let initials: String = f
                    .provenance
                    .author
                    .split_whitespace()
                    .filter_map(|w| w.chars().next())
                    .take(2)
                    .flat_map(char::to_uppercase)
                    .collect();
                row(format!("fact-{fid}"))
                    .group(hover.clone())
                    .items_start()
                    .py(px(12.))
                    .child(
                        set::tile()
                            .text_size(px(11.))
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .child(if initials.is_empty() {
                                "·".to_owned()
                            } else {
                                initials
                            }),
                    )
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .gap(px(3.))
                            .pt(px(1.))
                            .child(
                                div()
                                    .text_size(px(13.))
                                    .line_height(px(18.))
                                    .child(f.text.clone()),
                            )
                            .child(self.fact_meta(
                                state,
                                f,
                                disputed.contains(&fid).then_some("Disputed · Not reviewed"),
                                Some(ago(now - f.provenance.at)),
                                cx,
                            )),
                    )
                    .child(hover_remove(
                        hover,
                        format!("forget-{fid}"),
                        "Remove fact",
                        cx,
                        move |s| {
                            s.issue(id, Command::RemoveFact { fact: fid });
                        },
                    ))
                    .into_any_element()
            }))
        };
        ui::column()
            .child(header(
                "Facts",
                "What the agent knows about this topic. Each fact links to its source.",
                None,
            ))
            .child(body)
            .when(!footnote.is_empty(), |c| c.child(set::note(footnote)))
            .children(self.removed_section(state, Tab::Facts, cx))
    }

    pub(super) fn rules_page(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let t = &state.topic;
        let id = t.id;
        let now = Utc::now();
        let switch_row = |key: &'static str,
                          name: &'static str,
                          detail: String,
                          on: bool,
                          f: fn(bool) -> Command| {
            set::item(
                name,
                detail,
                Switch::new(format!("stage-{key}"))
                    .small()
                    .checked(on)
                    .accessibility_label(name)
                    .on_change(cx.listener(move |s, on: &bool, _, cx| {
                        s.issue(id, f(*on));
                        cx.notify()
                    })),
            )
            .into_any_element()
        };
        let feed = t.settings.scout_feed.clone();
        let checks = group([
            switch_row(
                "check_facts",
                "Check facts",
                "Show changes that do not agree with the facts.".into(),
                t.settings.check_facts,
                |on| Command::SetTopicSetting {
                    key: "check_facts".into(),
                    enabled: on,
                },
            ),
            switch_row(
                "scout-feed",
                "PostHog Scout reports",
                match feed.as_deref() {
                    None => "Send PostHog Scout reports to this inbox.".to_owned(),
                    Some("") => "All Scout reports for this project go to this inbox.".to_owned(),
                    Some(term) => format!("Scout reports about “{term}” go to this inbox."),
                },
                feed.is_some(),
                |on| Command::SetScoutFeed {
                    feed: on.then(String::new),
                },
            ),
        ]);
        let rules = if t.rules.is_empty() {
            empty_group(
                "No rules yet",
                "When you approve an action, you can make it a rule.",
            )
        } else {
            group(t.rules.iter().map(|rule| {
                let rid = rule.id;
                let hover = SharedString::from(format!("rule-{rid}"));
                row(format!("rule-row-{rid}"))
                    .group(hover.clone())
                    .child(glyph_tile(Glyph::ShieldCheck))
                    .child(wrap_copy(
                        rule.text.clone(),
                        format!(
                            "{} {}",
                            if rule.from_task.is_some() {
                                "From an approval"
                            } else {
                                "Added"
                            },
                            ago(now - rule.created_at)
                        ),
                    ))
                    .child(hover_remove(
                        hover,
                        format!("remove-{rid}"),
                        "Remove rule",
                        cx,
                        move |s| {
                            s.issue(id, Command::RemoveRule { rule: rid });
                        },
                    ))
                    .into_any_element()
            }))
        };
        ui::column()
            .child(header(
                "Rules",
                "The checks that the agent does, and the rules that it obeys.",
                None,
            ))
            .child(section("Checks", "", None, true))
            .child(checks)
            .child(section(
                "Rules",
                "The agent follows these before it acts.",
                None,
                false,
            ))
            .child(rules)
            .children(self.removed_section(state, Tab::Rules, cx))
    }

    fn removed_section(&self, state: &TopicState, part: Tab, cx: &Context<Self>) -> Option<Div> {
        let id = state.topic.id;
        let restore = |key: String, text: String, label: &'static str, command: Command| {
            set::item(
                text,
                label,
                control(key, "Restore", false, cx, move |s, _, _| {
                    s.issue(id, command.clone());
                }),
            )
            .into_any_element()
        };
        let mut rows = Vec::new();
        if part == Tab::Facts {
            let withdrawn = state.topic.facts.iter().filter(|f| {
                f.withdrawn_at.is_some() && f.superseded_by.is_none() && f.invalidated_by.is_none()
            });
            let mut seen = std::collections::BTreeSet::new();
            for f in withdrawn.chain(state.removed_facts.values()) {
                if !seen.insert(f.id) {
                    continue;
                }
                rows.push(restore(
                    format!("restore-fact-{}", f.id),
                    f.text.clone(),
                    "Removed fact",
                    Command::RestoreFact { fact: f.id },
                ));
            }
        } else {
            for (&rid, (_, _, rule)) in &state.removed_rules {
                rows.push(restore(
                    format!("restore-rule-{rid}"),
                    rule.text.clone(),
                    "Removed rule",
                    Command::RestoreRule { rule: rid },
                ));
            }
        }
        (!rows.is_empty()).then(|| {
            ui::column()
                .child(section(
                    "Recently removed",
                    "Restore items that you removed in error.",
                    None,
                    false,
                ))
                .child(group(rows))
        })
    }
}
