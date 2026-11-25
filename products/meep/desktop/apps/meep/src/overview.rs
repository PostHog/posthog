//! The Overview: the topic's other surfaces, minimised beside its conversation.
//! One flat list of sections; each folds open to a short preview, and anything
//! in it opens in the topic's main pane under a breadcrumb.
use super::pages::{
    UNREAD, ago, attention_glyph, attention_groups, attention_section, ordered_threads,
};
use super::*;
use chrono::Utc;
use meep_ui::gpui_kit::component::Icon;
use std::collections::BTreeMap;

/// The Overview pane's width beside the topic.
pub(super) const WIDTH: f32 = 296.;
/// Below this window width the Overview is reached from the header instead.
const DOCK_MIN: f32 = 980.;

impl Desktop {
    /// Whether the Overview sits beside the topic right now.
    pub(super) fn overview_docked(&self, w: &Window) -> bool {
        matches!(self.page, Page::Topic(id, ..) if self.overview_shown.contains(&id))
            && w.viewport_size().width > px(DOCK_MIN)
    }

    pub(super) fn toggle_overview(&mut self, topic: TopicId, w: &Window) {
        if w.viewport_size().width <= px(DOCK_MIN) {
            self.overview_overlay = !self.overview_overlay;
        } else if !self.overview_shown.remove(&topic) {
            self.overview_shown.insert(topic);
        }
    }

    fn overview_open(&self, topic: TopicId, tab: Tab) -> bool {
        self.overview_open.contains(&(topic, tab))
    }

    pub(super) fn overview(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let (page_tab, page_detail) = match &self.page {
            Page::Topic(_, tab, detail) => (*tab, detail.clone()),
            _ => (Tab::Chat, None),
        };
        let header = ui::row()
            .flex_none()
            .h(px(CRUMB_BAR))
            .pl(px(18.))
            .pr(px(10.))
            .gap(px(8.))
            .child(
                div()
                    .flex_1()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child("Overview"),
            )
            .child(
                ui::icon_button("hide-overview", Glyph::PanelRight, "Hide overview")
                    .tooltip("Hide · ⌘\\")
                    .on_click(cx.listener(move |s, _, _, cx| {
                        if s.overview_overlay {
                            s.overview_overlay = false;
                        } else {
                            s.overview_shown.remove(&id);
                        }
                        cx.notify()
                    })),
            );
        let mut list = ui::column().gap_0().pt(px(6.)).pb(px(14.));
        let mut first = true;
        for tab in Tab::OVERVIEW {
            let Some((glyph, summary, attention_tone)) = self.overview_summary(state, tab) else {
                continue;
            };
            first = false;
            let open = self.overview_open(id, tab);
            let here = page_tab == tab && page_detail.is_none();
            list = list.child(
                ui::row()
                    .id(SharedString::from(format!("overview-{tab:?}")))
                    .group(SharedString::from(format!("ov-row-{tab:?}")))
                    .role(Role::Button)
                    .mx(px(8.))
                    .px(px(10.))
                    .h(px(34.))
                    .gap(px(10.))
                    .rounded(px(7.))
                    .cursor_pointer()
                    .hover(|s| s.bg(ui::ink(0x07)))
                    .when(here, |r| r.bg(rgb(ui::theme::get(7))))
                    .child(ui::nav::glyph(glyph, false))
                    .child(div().flex_none().child(tab.label()))
                    .child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .truncate()
                            .text_right()
                            .text_size(px(12.))
                            .text_color(rgb(
                                attention_tone.unwrap_or(ui::theme::color(ui::TERTIARY))
                            ))
                            .child(summary),
                    )
                    .child(
                        div()
                            .id(SharedString::from(format!("overview-fold-{tab:?}")))
                            .size(px(22.))
                            .ml(px(-4.))
                            .mr(px(-6.))
                            .flex_none()
                            .flex()
                            .items_center()
                            .justify_center()
                            .rounded(px(5.))
                            // The disclosure shows on hover, or while the section is open.
                            .when(!open, |c| c.opacity(0.))
                            .group_hover(SharedString::from(format!("ov-row-{tab:?}")), |c| {
                                c.opacity(1.)
                            })
                            .child(
                                Icon::new(if open {
                                    Glyph::ChevronDown
                                } else {
                                    Glyph::ChevronRight
                                })
                                .size(px(12.))
                                .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                            ),
                    )
                    // The row opens and folds its section in place; "View all" inside
                    // goes to the section itself.
                    .on_click(cx.listener(move |s, _, _, cx| {
                        let open = !s.overview_open.remove(&(id, tab));
                        if open {
                            s.overview_open.insert((id, tab));
                        }
                        s.folds.toggled(format!("overview:{id}:{tab:?}"), open, cx);
                        cx.notify()
                    })),
            );
            list = list.children(self.folds.reveal(
                &format!("overview:{id}:{tab:?}"),
                open,
                cx,
                || {
                    ui::column()
                        .px(px(8.))
                        .pb(px(8.))
                        .child(self.overview_body(state, tab, page_tab, page_detail.as_ref(), cx))
                        .into_any_element()
                },
            ));
        }
        if first {
            list = list.child(
                ui::column()
                    .items_center()
                    .gap(px(6.))
                    .px(px(24.))
                    .pt(px(48.))
                    .child(ui::nav::glyph(Glyph::Target, false))
                    .child(
                        div()
                            .font_weight(FontWeight::SEMIBOLD)
                            .child("Nothing set up yet"),
                    )
                    .child(
                        ui::caption(
                            "As you talk, the mission, goals, facts and work in progress show up here.",
                        )
                        .text_center(),
                    ),
            );
        }
        ui::column()
            .size_full()
            .min_h_0()
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .child(header)
            .child(scroll("overview-scroll").flex_1().min_h_0().child(list))
    }

    /// A section's icon and one-line summary, or `None` when it has nothing yet.
    pub(super) fn overview_summary(
        &self,
        state: &TopicState,
        tab: Tab,
    ) -> Option<(Glyph, String, Option<u32>)> {
        let t = &state.topic;
        Some(match tab {
            Tab::Needs => {
                let groups = attention_groups(&self.needs, state);
                if groups.is_empty() {
                    return None;
                }
                let urgent = groups
                    .iter()
                    .any(|g| matches!(g.latest.kind, "Failed" | "Problem"));
                (
                    Glyph::Bell,
                    format!("{} waiting", groups.len()),
                    Some(if urgent {
                        super::pages::warning()
                    } else {
                        UNREAD
                    }),
                )
            }
            Tab::Tasks => {
                if state.tasks.iter().all(|t| t.hidden()) {
                    return None;
                }
                let running = state
                    .tasks
                    .iter()
                    .filter(|t| t.column == Column::InProgress && !t.hidden())
                    .count();
                (Glyph::SquareCheck, format!("{running} running"), None)
            }
            Tab::Inbox => {
                let reports = ordered_threads(state, true);
                if reports.is_empty() {
                    return None;
                }
                let new = reports.iter().filter(|t| t.unseen).count();
                (
                    Glyph::Inbox,
                    if new > 0 {
                        format!("{new} new")
                    } else {
                        reports.len().to_string()
                    },
                    None,
                )
            }
            Tab::Files => {
                let n = self.file_entries(state).len();
                if n == 0 {
                    return None;
                }
                (Glyph::FileText, n.to_string(), None)
            }
            Tab::Routines => {
                if t.routines.is_empty() && state.scouts.is_empty() {
                    return None;
                }
                let on = t.routines.iter().filter(|r| r.enabled).count()
                    + state.scouts.iter().filter(|s| s.enabled).count();
                (Glyph::Repeat, format!("{on} on"), None)
            }
            Tab::Mission => {
                if t.mission.trim().is_empty() {
                    return None;
                }
                (Glyph::Flag, String::new(), None)
            }
            Tab::Goals => {
                if t.goals.is_empty() {
                    return None;
                }
                let measured: Vec<_> = t.goals.iter().filter(|g| g.progress.is_some()).collect();
                let on_track = measured.iter().filter(|g| goal_on_track(g)).count();
                (
                    Glyph::Target,
                    if measured.is_empty() {
                        format!("{} unmeasured", t.goals.len())
                    } else {
                        format!("{on_track} of {} on track", t.goals.len())
                    },
                    None,
                )
            }
            Tab::Facts => {
                let n = t.facts.iter().filter(|f| f.is_current()).count();
                if n == 0 {
                    return None;
                }
                (Glyph::Pencil, n.to_string(), None)
            }
            Tab::Linked => {
                if t.context_sources.is_empty() {
                    return None;
                }
                (Glyph::Link, t.context_sources.len().to_string(), None)
            }
            Tab::Rules => {
                if t.rules.is_empty() {
                    return None;
                }
                (Glyph::ShieldCheck, t.rules.len().to_string(), None)
            }
            Tab::Chat => return None,
        })
    }

    fn overview_body(
        &self,
        state: &TopicState,
        tab: Tab,
        page_tab: Tab,
        page_detail: Option<&Detail>,
        cx: &Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let t = &state.topic;
        let now = Utc::now();
        let selected = |d: &Detail| page_detail == Some(d);
        let mut body = ui::column().gap(px(1.));
        let view_all = |label: String, tab: Tab| {
            ui::row()
                .id(SharedString::from(format!("overview-all-{tab:?}")))
                .role(Role::Link)
                .gap(px(4.))
                .pl(px(36.))
                .pr(px(10.))
                .py(px(4.))
                .rounded(px(6.))
                .cursor_pointer()
                .text_size(px(12.))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .hover(|s| {
                    s.bg(ui::ink(0x07))
                        .text_color(rgb(ui::theme::color(ui::INK)))
                })
                .child(label)
                .child(Icon::new(Glyph::ArrowRight).size(px(11.)))
                .on_click(cx.listener(move |s, _, w, cx| s.go(Page::Topic(id, tab, None), w, cx)))
        };
        match tab {
            Tab::Needs => {
                let groups = attention_groups(&self.needs, state);
                let mut start = 0;
                while start < groups.len() {
                    let kind = groups[start].latest.kind;
                    let end = groups[start..]
                        .iter()
                        .position(|g| g.latest.kind != kind)
                        .map_or(groups.len(), |n| start + n);
                    let (glyph, tone, _) = attention_glyph(kind);
                    body = body.child(
                        line(format!("ov-need-{kind}"), false)
                            .child(mark(Icon::new(glyph).size(px(13.)).text_color(rgb(tone))))
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .truncate()
                                    .child(attention_section(kind)),
                            )
                            .child(
                                ui::caption((end - start).to_string())
                                    .flex_none()
                                    .mr(px(20.)),
                            )
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(Page::Topic(id, Tab::Needs, None), w, cx)
                            })),
                    );
                    start = end;
                }
                return body;
            }
            Tab::Tasks => {
                let active: Vec<_> = state
                    .tasks
                    .iter()
                    .filter(|t| !matches!(t.column, Column::Done | Column::NeedsYou) && !t.hidden())
                    .take(4)
                    .collect();
                for task in active {
                    let tid = task.id;
                    body = body.child(
                        line(format!("ov-task-{tid}"), selected(&Detail::Task(tid)))
                            .child(mark(super::tasks_view::status_icon(task.column)))
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .truncate()
                                    .child(meep_topic::title_line(&task.title)),
                            )
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(Page::Topic(id, Tab::Tasks, Some(Detail::Task(tid))), w, cx)
                            })),
                    );
                }
            }
            Tab::Inbox => {
                let reports = ordered_threads(state, true);
                for thread in reports.iter().take(3) {
                    let tid = thread.id;
                    body = body.child(
                        line(format!("ov-report-{tid}"), selected(&Detail::Thread(tid)))
                            .h(px(44.))
                            .child(mark(div().when(thread.unseen, |d| {
                                d.child(div().size(px(6.)).rounded_full().bg(rgb(UNREAD)))
                            })))
                            .child(
                                ui::column()
                                    .flex_1()
                                    .min_w_0()
                                    .gap(px(1.))
                                    .child(
                                        div()
                                            .truncate()
                                            .line_height(px(17.))
                                            .child(thread.subject.clone()),
                                    )
                                    .child(
                                        ui::caption(ago(now - super::pages::message_time(thread)))
                                            .truncate(),
                                    ),
                            )
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(
                                    Page::Topic(id, Tab::Inbox, Some(Detail::Thread(tid))),
                                    w,
                                    cx,
                                )
                            })),
                    );
                }
            }
            Tab::Files => {
                let entries = self.file_entries(state);
                let mut folders: BTreeMap<String, usize> = BTreeMap::new();
                let mut loose = vec![];
                for path in entries.keys() {
                    match path.split_once('/') {
                        Some((head, _)) => *folders.entry(head.to_owned()).or_default() += 1,
                        None => loose.push(path.clone()),
                    }
                }
                for (name, n) in folders {
                    let folder = name.clone();
                    body = body.child(
                        line(format!("ov-folder-{name}"), false)
                            .child(ui::nav::glyph(Glyph::Folder, false))
                            .child(div().flex_1().min_w_0().truncate().child(name))
                            .child(ui::caption(n.to_string()))
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.reveal_folder(id, &folder);
                                s.go(Page::Topic(id, Tab::Files, None), w, cx)
                            })),
                    );
                }
                for path in loose {
                    let open = path.clone();
                    body = body.child(
                        line(
                            format!("ov-file-{path}"),
                            selected(&Detail::File(path.clone())),
                        )
                        .child(ui::nav::glyph(
                            if super::tables::tabular(&path) {
                                Glyph::Table2
                            } else {
                                Glyph::FileText
                            },
                            false,
                        ))
                        .child(div().flex_1().min_w_0().truncate().child(path))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(
                                Page::Topic(id, Tab::Files, Some(Detail::File(open.clone()))),
                                w,
                                cx,
                            )
                        })),
                    );
                }
            }
            Tab::Routines => {
                for scout in &state.scouts {
                    let key = scout.id;
                    body = body.child(
                        line(format!("ov-scout-{key}"), selected(&Detail::Scout(key)))
                            .aria_label(format!("Scout: {}", scout.name))
                            .child(ui::nav::glyph(Glyph::Binoculars, false))
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .truncate()
                                    .child(scout.name.clone()),
                            )
                            .when(!scout.enabled, |row| row.child(ui::caption("Off")))
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(
                                    Page::Topic(id, Tab::Routines, Some(Detail::Scout(key))),
                                    w,
                                    cx,
                                )
                            })),
                    );
                }
                for r in &t.routines {
                    let key = r.binding.id.clone();
                    let open = key.clone();
                    body = body.child(
                        line(format!("ov-routine-{key}"), selected(&Detail::Routine(key)))
                            .child(ui::nav::glyph(Glyph::Repeat, false))
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .truncate()
                                    .child(r.binding.name.clone()),
                            )
                            .when(!r.enabled, |l| l.child(ui::caption("Off")))
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(
                                    Page::Topic(
                                        id,
                                        Tab::Routines,
                                        Some(Detail::Routine(open.clone())),
                                    ),
                                    w,
                                    cx,
                                )
                            })),
                    );
                }
            }
            Tab::Mission => {
                body = body.child(
                    div()
                        .id("ov-mission")
                        .pl(px(36.))
                        .pr(px(10.))
                        .py(px(6.))
                        .rounded(px(6.))
                        .cursor_pointer()
                        .line_clamp(3)
                        .text_size(px(12.5))
                        .line_height(px(18.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .hover(|s| s.bg(ui::ink(0x07)))
                        .when(page_tab == Tab::Mission, |d| d.bg(rgb(ui::theme::get(7))))
                        .child(t.mission.clone())
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(Page::Topic(id, Tab::Mission, None), w, cx)
                        })),
                );
            }
            Tab::Goals => {
                for g in &t.goals {
                    let gid = g.id;
                    let (label, ratio, band) = goal_measure(g);
                    body = body.child(
                        ui::column()
                            .id(SharedString::from(format!("ov-goal-{gid}")))
                            .gap(px(5.))
                            .pl(px(36.))
                            .pr(px(10.))
                            .py(px(6.))
                            .rounded(px(6.))
                            .cursor_pointer()
                            .hover(|s| s.bg(ui::ink(0x07)))
                            .when(selected(&Detail::Goal(gid)), |d| {
                                d.bg(rgb(ui::theme::get(7)))
                            })
                            .child(div().truncate().child(g.text.clone()))
                            .child(
                                ui::row()
                                    .gap(px(8.))
                                    .child(goal_track(ratio, band, 140.))
                                    .child(ui::caption(label).truncate()),
                            )
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(Page::Topic(id, Tab::Goals, Some(Detail::Goal(gid))), w, cx)
                            })),
                    );
                }
            }
            Tab::Facts => {
                let mut facts: Vec<_> = t.facts.iter().filter(|f| f.is_current()).collect();
                facts.sort_by_key(|f| std::cmp::Reverse(f.provenance.at));
                for f in facts.into_iter().take(3) {
                    let fid = f.id;
                    body = body.child(
                        ui::column()
                            .id(SharedString::from(format!("ov-fact-{fid}")))
                            .gap(px(2.))
                            .pl(px(36.))
                            .pr(px(10.))
                            .py(px(6.))
                            .rounded(px(6.))
                            .cursor_pointer()
                            .hover(|s| s.bg(ui::ink(0x07)))
                            .when(selected(&Detail::Fact(fid)), |d| {
                                d.bg(rgb(ui::theme::get(7)))
                            })
                            .child(div().line_clamp(2).child(f.text.clone()))
                            .child(
                                ui::caption(format!(
                                    "{} · {}",
                                    f.provenance.author,
                                    ago(now - f.provenance.at)
                                ))
                                .truncate(),
                            )
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(Page::Topic(id, Tab::Facts, Some(Detail::Fact(fid))), w, cx)
                            })),
                    );
                }
            }
            Tab::Linked => {
                for watch in &t.context_sources {
                    let key = watch.key.clone();
                    body = body.child(
                        line(
                            format!("ov-linked-{key}"),
                            selected(&Detail::Linked(key.clone())),
                        )
                        .child(ui::nav::glyph(source_glyph(&watch.kind), false))
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .truncate()
                                .child(watch.label.clone()),
                        )
                        .child(ui::caption(source_kind(&watch.kind)).flex_none())
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(
                                Page::Topic(id, Tab::Linked, Some(Detail::Linked(key.clone()))),
                                w,
                                cx,
                            )
                        })),
                    );
                }
            }
            Tab::Rules => {
                for (i, rule) in t.rules.iter().enumerate() {
                    body = body.child(
                        line(format!("ov-rule-{i}"), false)
                            .child(effect_pill(&rule.effect))
                            .child(div().flex_1().min_w_0().truncate().child(rule.text.clone()))
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.go(Page::Topic(id, Tab::Rules, None), w, cx)
                            })),
                    );
                }
            }
            Tab::Chat => return body,
        }
        // Every open section ends the same way: a way to the whole thing.
        body.child(view_all("View all".into(), tab))
    }

    /// A goal as its own page: where it stands and how it is measured.
    pub(super) fn goal_page(&self, state: &TopicState, goal: GoalId, cx: &Context<Self>) -> Div {
        let page = ui::column().w_full().max_w(px(720.)).mx_auto().gap(px(14.));
        let Some(g) = state.topic.goals.iter().find(|g| g.id == goal) else {
            return page.child(ui::caption("This goal was removed."));
        };
        let (label, ratio, band) = goal_measure(g);
        let kind = match g.progress {
            Some(Progress::Target { .. }) => "Target",
            Some(Progress::Guardrail { .. }) => "Guardrail",
            None => "Goal",
        };
        let text = g.text.clone();
        let mut page = page.child(super::details::item_title(kind, g.text.clone()));
        if ratio.is_some() {
            page = page.child(
                ui::column()
                    .gap(px(12.))
                    .p(px(16.))
                    .rounded(px(10.))
                    .bg(ui::ink(0x05))
                    .child(
                        ui::row()
                            .gap(px(10.))
                            .items_end()
                            .child(
                                div()
                                    .text_size(px(24.))
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .child(label),
                            )
                            .child(ui::caption(if goal_on_track(g) {
                                "On track"
                            } else {
                                "Behind"
                            })),
                    )
                    .child(goal_track(ratio, band, 560.).w_full()),
            );
        } else {
            page = page
                .child(ui::caption("Not measured yet."))
                .child(ui::row().child(control(
                    "suggest-measure",
                    "Suggest a measure",
                    true,
                    cx,
                    move |s, w, cx| {
                        s.ask_in_chat(
                            &format!("Suggest how to measure the goal \"{text}\""),
                            w,
                            cx,
                        )
                    },
                )));
        }
        page
    }

    /// A linked context source as its own page.
    pub(super) fn linked_page(&self, state: &TopicState, key: &str, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let page = ui::column().w_full().max_w(px(720.)).mx_auto().gap(px(16.));
        let Some(watch) = state.topic.context_sources.iter().find(|w| w.key == key) else {
            return page.child(ui::caption("This link was removed."));
        };
        let source = watch.id;
        let service = self.connection_label(&watch.connection);
        let facts: Vec<_> = state
            .topic
            .facts
            .iter()
            .filter(|f| f.is_current() && f.provenance.via.contains(&watch.label))
            .collect();
        // The same head as every item page: what it is, its name, then where it lives.
        let mut page = page.child(
            ui::row()
                .items_start()
                .gap(px(12.))
                .child(
                    ui::column()
                        .flex_1()
                        .min_w_0()
                        .gap(px(6.))
                        .child(super::details::item_title(
                            source_kind(&watch.kind).to_owned(),
                            watch.label.clone(),
                        ))
                        .child(ui::caption(service.to_owned())),
                )
                .child(control(
                    "unlink-source",
                    "Unlink",
                    false,
                    cx,
                    move |s, w, cx| {
                        if s.issue(id, Command::RemoveContextSource { source }) {
                            s.go(Page::Topic(id, Tab::Linked, None), w, cx)
                        }
                    },
                )),
        );
        if !facts.is_empty() {
            let mut list = ui::column().gap(px(2.));
            for f in facts {
                let fid = f.id;
                list = list.child(
                    line(format!("linked-fact-{fid}"), false)
                        .h(px(34.))
                        .child(ui::nav::glyph(Glyph::Pencil, false))
                        .child(div().flex_1().min_w_0().truncate().child(f.text.clone()))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(Page::Topic(id, Tab::Facts, Some(Detail::Fact(fid))), w, cx)
                        })),
                );
            }
            page = page.child(ui::caption("Facts from it")).child(list);
        }
        page
    }

    /// Open the Files tree at a top-level folder.
    pub(super) fn reveal_folder(&mut self, topic: TopicId, folder: &str) {
        self.reveal_file(topic, &format!("{folder}/"));
    }
}

/// A preview row in an open section.
fn line(id: String, selected: bool) -> Stateful<Div> {
    ui::row()
        .id(SharedString::from(id))
        .role(Role::Button)
        .h(px(30.))
        .gap(px(10.))
        .px(px(10.))
        .rounded(px(6.))
        .text_size(px(13.))
        .cursor_pointer()
        .min_w_0()
        .hover(|s| s.bg(ui::ink(0x07)))
        .when(selected, |r| r.bg(rgb(ui::theme::get(7))))
}

/// A goal's label, how far along it is, and a guardrail's band.
pub(super) fn goal_measure(g: &meep_topic::Goal) -> (String, Option<f64>, Option<(f64, f64)>) {
    match &g.progress {
        Some(Progress::Target {
            current,
            target,
            unit,
        }) => (
            format!("{current} of {target} {unit}"),
            Some(if *target == 0. { 0. } else { current / target }),
            None,
        ),
        Some(Progress::Guardrail {
            current,
            low,
            high,
            unit,
        }) => {
            let min = low.min(*current).min(0.);
            let max = high.max(*current);
            let range = (max - min).max(f64::EPSILON);
            (
                format!("{current} {unit}"),
                Some((current - min) / range),
                Some(((low - min) / range, (high - low) / range)),
            )
        }
        None => ("Not measured".into(), None, None),
    }
}

pub(super) fn goal_on_track(g: &meep_topic::Goal) -> bool {
    match &g.progress {
        Some(Progress::Target {
            current, target, ..
        }) => *target != 0. && current / target >= 0.5,
        Some(Progress::Guardrail {
            current, low, high, ..
        }) => current >= low && current <= high,
        None => false,
    }
}

/// A goal's bar: progress toward a target, a marker in a guardrail's band, or
/// a dashed track when it is not measured.
pub(super) fn goal_track(ratio: Option<f64>, band: Option<(f64, f64)>, width: f32) -> Div {
    let mut track = div()
        .relative()
        .flex_none()
        .w(px(width))
        .h(px(4.))
        .rounded(px(2.))
        .bg(ui::ink(0x10));
    if let Some((start, w)) = band {
        track = track.child(
            div()
                .absolute()
                .left(relative(start as f32))
                .w(relative(w as f32))
                .h_full()
                .rounded(px(2.))
                .bg(rgb(ui::theme::color(ui::POSITIVE)).opacity(0.35)),
        );
    }
    match ratio {
        // The current value stands out from the band it should stay in.
        Some(r) if band.is_some() => track.child(
            div()
                .absolute()
                .left(relative(r.clamp(0., 1.) as f32))
                .top(px(-3.))
                .bottom(px(-3.))
                .w(px(3.))
                .rounded(px(2.))
                .bg(rgb(ui::theme::color(ui::INK))),
        ),
        Some(r) => track.child(
            div()
                .w(relative(r.clamp(0., 1.) as f32))
                .h_full()
                .rounded(px(2.))
                .bg(rgb(ui::theme::color(ui::POSITIVE))),
        ),
        None => track.bg(ui::ink(0x08)),
    }
}

pub(super) fn source_glyph(kind: &str) -> Glyph {
    match kind {
        "topic" => Glyph::AtSign,
        "flag" => Glyph::Flag,
        "insight" | "event" => Glyph::ChartColumn,
        "channel" => Glyph::Hash,
        "dashboard" => Glyph::LayoutDashboard,
        _ => Glyph::Plug,
    }
}

pub(super) fn source_kind(kind: &str) -> &str {
    match kind {
        "topic" => "Topic",
        "flag" => "Feature flag",
        "insight" => "Insight",
        "event" => "Event",
        "channel" => "Channel",
        "dashboard" => "Dashboard",
        "repository" | "repo" => "Repository",
        "service" => "Service",
        other => other,
    }
}

/// Allow, Ask, Deny or Skip as a small coloured label.
pub(super) fn effect_pill(effect: &meep_topic::RuleEffect) -> Div {
    use meep_topic::RuleEffect::*;
    let (label, tone) = match effect {
        Allow(_) => ("Allow", ui::POSITIVE),
        Ask(_) => ("Ask", UNREAD),
        Deny(_) => ("Deny", ui::DANGER),
        Skip(_) => ("Skip", ui::theme::color(ui::SECONDARY)),
    };
    div()
        .flex_none()
        .min_w(px(38.))
        .px(px(5.))
        .py(px(1.))
        .rounded(px(4.))
        .text_center()
        .text_size(px(10.5))
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(tone))
        .bg(rgb(tone).opacity(0.12))
        .child(label)
}

/// A preview row's marker, centred in the section's icon column so every row's text
/// lines up with the section label.
fn mark(el: impl IntoElement) -> Div {
    div()
        .w(px(ui::nav::ICON_BOX))
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .child(el)
}
