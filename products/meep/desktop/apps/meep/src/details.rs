use super::{pages::warning, *};
use chrono::Utc;
use meep_protocol::sessions::{AgentApproval, AgentMessage, AgentSession};
use meep_ui::gpui_kit::component::{
    Disableable, Icon, Sizable,
    button::ButtonVariants as _,
    input::{Enter, Textarea},
    menu::{DropdownMenu, PopupMenu, PopupMenuItem},
};

/// Every topic screen's edge: content and composer start this far from the pane's side.
pub(super) const PAGE_X: f32 = 24.;
/// Space between the crumb bar and a screen's first line.
pub(super) const PAGE_TOP: f32 = 16.;

#[derive(Clone, Debug, PartialEq)]
pub(super) struct ChatTask {
    id: TaskId,
    title: String,
    column: Column,
    stalled: bool,
    detail: String,
    started: chrono::DateTime<Utc>,
    updated: chrono::DateTime<Utc>,
}

impl ChatTask {
    fn new(task: &meep_topic::Task) -> Self {
        let first_line = |text: &str| {
            text.lines()
                .map(str::trim)
                .find(|line| !line.is_empty())
                .unwrap_or_default()
                .to_owned()
        };
        let stalled = task.column == Column::NeedsYou
            && task.input_question.is_none()
            && task.action.is_none()
            && !task.review_before_start
            && task.assignment.as_ref() != Some(&InboxAssignment::Human)
            && task.result.is_some();
        let detail = match task.column {
            Column::NeedsYou if let Some(question) = &task.input_question => first_line(question),
            Column::NeedsYou if stalled => {
                super::pages::failure_reason(task.result.as_deref().unwrap_or_default())
            }
            Column::NeedsYou if task.review_before_start => "Starts once you approve".to_owned(),
            Column::NeedsYou => task.action.as_ref().map_or_else(
                || "Waiting for your approval".to_owned(),
                |action| format!("Approve “{}”", action.label),
            ),
            Column::InProgress => "Working".to_owned(),
            Column::Todo if task.queued => "Waiting to start".to_owned(),
            Column::Todo => "Not started".to_owned(),
            Column::Done => task
                .result
                .as_deref()
                .map(first_line)
                .filter(|line| !line.is_empty())
                .unwrap_or_else(|| "Done".to_owned()),
        };
        Self {
            id: task.id,
            title: meep_topic::title_line(&task.title).to_owned(),
            column: task.column,
            stalled,
            detail,
            started: task.created_at,
            updated: task.updated_at,
        }
    }

    fn status(&self) -> &'static str {
        match self.column {
            _ if self.stalled => "Failed",
            Column::Todo => "Queued",
            Column::InProgress => "Working",
            Column::NeedsYou => "Needs you",
            Column::Done => "Done",
        }
    }

    fn elapsed(&self, now: chrono::DateTime<Utc>) -> Option<String> {
        let end = match self.column {
            Column::Todo => return None,
            Column::InProgress => now,
            Column::NeedsYou | Column::Done => self.updated,
        };
        let seconds = (end - self.started).num_seconds().max(0);
        Some(if seconds >= 3600 {
            format!(
                "{}:{:02}:{:02}",
                seconds / 3600,
                seconds / 60 % 60,
                seconds % 60
            )
        } else {
            format!("{}:{:02}", seconds / 60, seconds % 60)
        })
    }

    fn tone(&self) -> u32 {
        match self.column {
            _ if self.stalled => warning(),
            Column::NeedsYou => super::pages::UNREAD,
            _ => ui::theme::color(ui::SECONDARY),
        }
    }

    fn mark(&self) -> Div {
        if self.stalled {
            div()
                .flex_none()
                .size(px(14.))
                .flex()
                .items_center()
                .justify_center()
                .child(
                    Icon::new(Glyph::TriangleAlert)
                        .size(px(13.))
                        .text_color(rgb(warning())),
                )
        } else {
            super::tasks_view::status_icon(self.column)
        }
    }
}

fn chat_task_summary(tasks: &[ChatTask]) -> Vec<(String, u32)> {
    let count = |matches: fn(&ChatTask) -> bool| tasks.iter().filter(|t| matches(t)).count();
    let quiet = ui::theme::color(ui::SECONDARY);
    [
        (count(|t| t.stalled), "failed", "failed", warning()),
        (
            count(|t| t.column == Column::NeedsYou && !t.stalled),
            "needs you",
            "need you",
            super::pages::UNREAD,
        ),
        (
            count(|t| t.column == Column::InProgress),
            "working",
            "working",
            quiet,
        ),
        (
            count(|t| t.column == Column::Todo),
            "queued",
            "queued",
            quiet,
        ),
        (count(|t| t.column == Column::Done), "done", "done", quiet),
    ]
    .into_iter()
    .filter(|(n, ..)| *n > 0)
    .map(|(n, one, many, tone)| (format!("{n} {}", if n == 1 { one } else { many }), tone))
    .collect()
}

fn chat_groups_task(state: &TopicState, task: TaskId) -> bool {
    let from = state
        .tasks
        .iter()
        .find(|t| t.id == task)
        .and_then(|t| t.from_thread);
    state.threads.iter().any(|thread| {
        thread.is_topic_chat()
            && (from == Some(thread.id)
                || thread
                    .outcomes
                    .iter()
                    .any(|outcome| matches!(outcome, Outcome::Task(id) if *id == task)))
    })
}

fn chat_linked_tasks(
    state: &TopicState,
    thread_rows: &BTreeMap<ThreadId, usize>,
    count: usize,
) -> Vec<Vec<ChatTask>> {
    let mut rows = vec![Vec::new(); count];
    for task in state.tasks.iter().filter(|task| !task.is_session()) {
        let Some(index) = state
            .threads
            .iter()
            .filter(|thread| thread.is_topic_chat())
            .find(|thread| {
                task.from_thread == Some(thread.id)
                    || thread
                        .outcomes
                        .iter()
                        .any(|outcome| matches!(outcome, Outcome::Task(id) if *id == task.id))
            })
            .and_then(|thread| thread_rows.get(&thread.id))
        else {
            continue;
        };
        rows[*index].push(ChatTask::new(task));
    }
    rows
}

impl Desktop {
    fn chat_task_group(&self, topic: TopicId, tasks: &[ChatTask], cx: &Context<Desktop>) -> Div {
        let Some(first) = tasks.first() else {
            return div();
        };
        let key = format!("chat-tasks-folded-{}", first.id);
        let fold = key.clone();
        let grouped = tasks.len() > 1;
        let open = !grouped || !self.expanded.contains(&key);
        let now = Utc::now();
        let mut card = ui::column()
            .w_full()
            .p(px(4.))
            .gap(px(1.))
            .rounded(px(10.))
            .border_1()
            .border_color(ui::ink(0x16))
            .bg(ui::ink(0x05));
        if grouped {
            let summary = chat_task_summary(tasks);
            let spoken = summary
                .iter()
                .map(|(text, _)| text.as_str())
                .collect::<Vec<_>>()
                .join(", ");
            let mut line = ui::row().min_w_0().gap(px(6.));
            for (i, (text, tone)) in summary.into_iter().enumerate() {
                if i > 0 {
                    line = line.child(
                        div()
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child("·"),
                    );
                }
                line = line.child(div().flex_none().text_color(rgb(tone)).child(text));
            }
            card = card.child(
                Button::new(SharedString::from(key.clone()))
                    .ghost()
                    .w_full()
                    .h(px(32.))
                    .px(px(8.))
                    .rounded(px(6.))
                    .accessibility_label(format!(
                        "{} {} tasks, {spoken}",
                        if open { "Hide" } else { "Show" },
                        tasks.len()
                    ))
                    .child(
                        ui::row()
                            .flex_1()
                            .min_w_0()
                            .gap(px(10.))
                            .text_size(px(13.))
                            .child(
                                Icon::new(Glyph::ListChecks)
                                    .size(px(14.))
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                            )
                            .child(
                                div()
                                    .flex_none()
                                    .font_weight(FontWeight::MEDIUM)
                                    .text_color(rgb(ui::theme::color(ui::INK)))
                                    .child(format!("{} tasks", tasks.len())),
                            )
                            .child(line.flex_1().overflow_hidden().text_size(px(12.5)))
                            .child(
                                Icon::new(if open {
                                    Glyph::ChevronDown
                                } else {
                                    Glyph::ChevronRight
                                })
                                .size(px(13.))
                                .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                            ),
                    )
                    .on_click(cx.listener(move |s, _, _, cx| {
                        cx.stop_propagation();
                        let open = s.expanded.remove(&key);
                        if !open {
                            s.expanded.insert(key.clone());
                        }
                        s.folds.toggled(key.clone(), open, cx);
                        cx.notify()
                    })),
            );
        }
        let mut rows = ui::column().gap(px(1.));
        for task in tasks {
            let id = task.id;
            let elapsed = task.elapsed(now);
            let spoken = match &elapsed {
                Some(time) => format!("{}, {}, {}, {time}", task.title, task.status(), task.detail),
                None => format!("{}, {}, {}", task.title, task.status(), task.detail),
            };
            let detail_tone = match task.column {
                Column::NeedsYou => task.tone(),
                _ => ui::theme::color(ui::SECONDARY),
            };
            rows = rows.child(
                Button::new(SharedString::from(format!("chat-task-{id}")))
                    .ghost()
                    .w_full()
                    .h(px(32.))
                    .px(px(8.))
                    .rounded(px(6.))
                    .role(Role::Link)
                    .accessibility_label(spoken)
                    .tooltip(task.detail.clone())
                    .child(
                        ui::row()
                            .flex_1()
                            .min_w_0()
                            .gap(px(10.))
                            .text_size(px(13.))
                            .child(task.mark())
                            .child(
                                div()
                                    .min_w(px(48.))
                                    .max_w(relative(0.55))
                                    .truncate()
                                    .text_color(rgb(ui::theme::color(ui::INK)))
                                    .child(task.title.clone()),
                            )
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .truncate()
                                    .text_size(px(12.5))
                                    .text_color(rgb(detail_tone))
                                    .child(task.detail.clone()),
                            )
                            .when_some(elapsed, |row, time| {
                                row.child(
                                    div()
                                        .flex_none()
                                        .text_size(px(12.5))
                                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                        .child(time),
                                )
                            })
                            .child(
                                Icon::new(Glyph::ArrowUpRight)
                                    .size(px(13.))
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                            ),
                    )
                    .on_click(cx.listener(move |s, _, w, cx| {
                        cx.stop_propagation();
                        s.go(
                            Page::Topic(topic, Tab::Tasks, Some(Detail::Task(id))),
                            w,
                            cx,
                        );
                        cx.notify()
                    })),
            );
        }
        card.children(
            self.folds
                .reveal(&fold, open, cx, || rows.into_any_element()),
        )
    }

    fn tick_running_chat_tasks(&self, linked: &[Vec<ChatTask>], cx: &mut Context<Self>) {
        let running = linked
            .iter()
            .flatten()
            .any(|task| task.column == Column::InProgress);
        if !running || self.chat_tick.replace(true) {
            return;
        }
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(std::time::Duration::from_secs(1))
                .await;
            let _ = this.update(cx, |this, cx| {
                this.chat_tick.set(false);
                cx.notify();
            });
        })
        .detach();
    }
}

struct Pane {
    kicker: String,
    /// A run that stopped before doing work: the chip reads "Didn't run" in warning orange.
    failed: bool,
    body: Div,
    /// Shown above the actions, outside the scroll, so it stays in view.
    footer: Option<Div>,
    actions: Vec<Button>,
    /// A conversation title shown in the bar instead of in the body.
    title: Option<String>,
    /// Quiet controls at the end of the bar.
    tools: Vec<AnyElement>,
    /// A conversation: content keeps a reading width, centred in a wide pane.
    conversation: bool,
}

impl Pane {
    fn new(kicker: impl Into<String>, body: Div) -> Self {
        Self {
            kicker: kicker.into(),
            failed: false,
            body,
            footer: None,
            actions: Vec::new(),
            title: None,
            tools: Vec::new(),
            conversation: false,
        }
    }
}
/// The reading width of a conversation: long answers stay comfortable in a wide pane.
pub(super) const READING: f32 = 720.;

fn warning_panel() -> Div {
    ui::column()
        .gap(px(6.))
        .p(px(14.))
        .rounded(px(10.))
        .bg(rgb(warning()).opacity(0.07))
        .border_1()
        .border_color(rgb(warning()).opacity(0.18))
}
/// One inspector section: a small caption over its content, with the same rhythm in every pane.
fn section(label: impl Into<SharedString>, content: impl IntoElement) -> Div {
    ui::column()
        .gap(px(8.))
        .child(ui::caption(label).font_weight(FontWeight::MEDIUM))
        .child(content)
}
/// The space between sections in an inspector pane.
const SECTION_GAP: f32 = 24.;
fn human_size(n: usize) -> String {
    match n {
        1 => "1 byte".into(),
        n if n < 1024 => format!("{n} bytes"),
        n if n < 1024 * 1024 => format!("{:.1} KB", n as f64 / 1024.),
        n => format!("{:.1} MB", n as f64 / (1024. * 1024.)),
    }
}

fn related_row(
    id: impl Into<SharedString>,
    kind: &'static str,
    title: String,
    status: Option<Column>,
) -> Stateful<Div> {
    let glyph = match kind {
        "Inbox" => Glyph::Inbox,
        "Task" | "Parent" | "Child" => Glyph::SquareCheck,
        "Fact" => Glyph::Lightbulb,
        "File" => Glyph::FileText,
        _ => Glyph::ArrowUpRight,
    };
    // One dense line, like a Linear relation: what it is, then where it stands.
    line(id, false)
        .gap(px(8.))
        .h(px(32.))
        .px(px(8.))
        .rounded(px(6.))
        .child(ui::nav::glyph(glyph, false))
        .child(div().flex_1().min_w_0().truncate().child(title))
        .when_some(status, |r, col| {
            r.child(
                ui::row()
                    .flex_none()
                    .gap(px(5.))
                    .child(div().size(px(6.)).rounded_full().bg(rgb(column_dot(col))))
                    .child(ui::caption(column_name(col))),
            )
        })
        .when(status.is_none() && kind != "Inbox", |r| {
            r.child(ui::caption(kind).flex_none())
        })
}
/// A quiet frame around related rows.
/// Drop the markdown sections whose heading (`## Impact` or `**Impact:**`)
/// matches one of the names switched on, up to the next heading.
fn without_sections(text: &str, drop: &[(bool, &[&str])]) -> String {
    let heading = |line: &str| -> Option<String> {
        let line = line.trim();
        let name = if let Some(h) = line.strip_prefix('#') {
            h.trim_start_matches('#').trim()
        } else {
            line.strip_prefix("**")?
                .split("**")
                .next()?
                .trim_end_matches(':')
                .trim()
        };
        Some(name.trim_end_matches(':').to_lowercase())
    };
    let dropped = |name: &str| drop.iter().any(|(on, names)| *on && names.contains(&name));
    let mut out = vec![];
    let mut skipping = false;
    for line in text.lines() {
        if let Some(name) = heading(line) {
            skipping = dropped(&name);
            if skipping {
                // A bold "**Impact:** text" heading carries its text on the same line.
                continue;
            }
        }
        if !skipping {
            out.push(line);
        }
    }
    out.join("\n").trim().to_owned()
}
fn related_group() -> Div {
    ui::column()
        .gap(px(1.))
        .p(px(3.))
        .rounded(px(8.))
        .border_1()
        .border_color(ui::ink(0x10))
}

/// The coloured dot shared by the board and every detail header.
pub(super) fn column_dot(c: Column) -> u32 {
    match c {
        Column::Todo => 0x9a9a9a,
        Column::InProgress => 0xe2a23b,
        Column::NeedsYou => super::pages::UNREAD,
        Column::Done => 0x3fa063,
    }
}

impl Desktop {
    /// A secondary disclosure for raw service text: plain copy first, diagnosis on request.
    fn details_disclosure(
        &self,
        id: &'static str,
        key: String,
        text: String,
        cx: &Context<Desktop>,
    ) -> Div {
        let open = self.expanded.contains(&key);
        let fold = key.clone();
        ui::column()
            .gap(px(4.))
            .pt(px(2.))
            .child(
                ui::row()
                    .id(id)
                    .gap(px(4.))
                    .cursor_pointer()
                    .child(
                        Icon::new(if open {
                            Glyph::ChevronDown
                        } else {
                            Glyph::ChevronRight
                        })
                        .size(px(12.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                    )
                    .child(ui::caption(if open {
                        "Hide details"
                    } else {
                        "Show details"
                    }))
                    .on_click(cx.listener(move |s, _, _, cx| {
                        let open = !s.expanded.remove(&key);
                        if open {
                            s.expanded.insert(key.clone());
                        }
                        s.folds.toggled(key.clone(), open, cx);
                        cx.notify()
                    })),
            )
            .children(self.folds.reveal(&fold, open, cx, || {
                div()
                    .text_size(px(12.))
                    .line_height(relative(1.45))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .child(text)
                    .into_any_element()
            }))
    }

    pub(super) fn after_approval(
        &self,
        state: &TopicState,
        t: &meep_topic::Task,
        cx: &Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let task = t.id;
        let mut body = ui::column()
            .rounded(px(8.))
            .p(px(12.))
            .bg(ui::ink(10))
            .child(match &t.action {
                Some(a) => format!("Approved “{}”.", a.label),
                None if t.column == Column::Done => "Done".to_string(),
                None => "Approved the start.".to_string(),
            });
        // A released start is approved as the start-follow-up kind.
        let kind = t
            .action
            .as_ref()
            .map(|a| a.kind.clone())
            .unwrap_or_else(ActionKind::start_follow_up);
        if let Some(rule_id) = t.approval_rule {
            let a = &kind;
            let version = t.review_version;
            body = body.child(ui::caption(a.approval_question())).child(
                ui::row()
                    .flex_wrap()
                    .child(control(
                        "always-do-it",
                        "Always allow",
                        true,
                        cx,
                        move |s, _, _| {
                            if s.issue(
                                id,
                                Command::AllowReviewedAction {
                                    task,
                                    expected_review: version,
                                    action_kind: kind.clone(),
                                    rule_id,
                                },
                            ) {
                                s.just_approved = None
                            }
                        },
                    ))
                    .child(control(
                        "keep-asking",
                        "Keep asking",
                        false,
                        cx,
                        |s, _, _| s.just_approved = None,
                    )),
            );
        }
        body
    }
    /// An inbox thread read as the page itself, in place of the list.
    pub(super) fn thread_page(
        &self,
        state: &TopicState,
        d: &Detail,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let tab = if let Page::Topic(_, t, _) = self.page {
            t
        } else {
            Tab::Inbox
        };
        let pane = match d {
            Detail::Thread(t) => state
                .threads
                .iter()
                .find(|m| m.id == *t)
                .map(|m| self.thread(state, m, w, cx)),
            Detail::Task(t) => state
                .tasks
                .iter()
                .find(|m| m.id == *t)
                .map(|m| self.task(state, m, false, w, cx)),
            // Routines, goals and linked sources open in the page itself.
            Detail::Routine(_) | Detail::Scout(_) | Detail::Goal(_) | Detail::Linked(_) => {
                return div();
            }
            Detail::Fact(f) => state.topic.facts.iter().find(|v| v.id == *f).map(|f| {
                Pane::new(
                    if state.disputed_facts().contains(&f.id) {
                        "Disputed fact"
                    } else if f.is_current() {
                        "Fact"
                    } else {
                        "Historical fact"
                    },
                    ui::column()
                        .gap(px(14.))
                        .child(item_title(
                            if f.is_current() {
                                "Fact"
                            } else {
                                "Historical fact"
                            },
                            f.text.clone(),
                        ))
                        .child(self.fact_source(state, f, cx)),
                )
            }),
            Detail::Table(_) => return div(),
            Detail::File(path) => {
                let content = match self.client().cached_file(id, path) {
                    Ok(Some(file)) => ui::column()
                        .border_1()
                        .border_color(ui::ink(24))
                        .p(px(14.))
                        .rounded(px(8.))
                        .child(ui::caption(if file.revision == 0 {
                            format!("Queued for upload · {}", human_size(file.bytes.len()))
                        } else {
                            human_size(file.bytes.len())
                        }))
                        .child(
                            std::str::from_utf8(&file.bytes)
                                .map(|s| s.chars().take(80_000).collect::<String>())
                                .unwrap_or_else(|_| "Binary file".into()),
                        ),
                    Ok(None) => ui::caption("Fetching file…"),
                    Err(e) => ui::caption(e.to_string()),
                };
                let (folder, name) = path.rsplit_once('/').unwrap_or(("", path.as_str()));
                let kicker = if folder.is_empty() {
                    "File".into()
                } else {
                    format!("File · {folder}")
                };
                let name = name.to_owned();
                let path = path.clone();
                let mut pane = Pane::new(
                    kicker,
                    ui::column()
                        .child(ui::heading("file-name", name))
                        .child(content),
                );
                pane.actions.push(
                    control(
                        "chat-file",
                        "Ask about this file",
                        false,
                        cx,
                        move |s, w, cx| {
                            s.chat_reference = Some(path.clone());
                            s.open_chat(w, cx);
                            s.composer.focus_handle(cx).focus(w, cx);
                        },
                    )
                    .icon(Glyph::MessageSquare),
                );
                Some(pane)
            }
            Detail::Problem(connection) => self
                .client()
                .connections()
                .ok()
                .and_then(|c| c.connections.into_iter().find(|c| c.id == *connection))
                .map(|c| {
                    let (_, label) = self.problem_fix(&c.id);
                    let since = c.unhealthy_since.map(|t| {
                        format!(
                            "Since {}",
                            t.with_timezone(&chrono::Local).format("%b %e, %H:%M")
                        )
                    });
                    let expired = c.health == "expired";
                    let topics: Vec<(TopicId, String)> = self
                        .states
                        .iter()
                        .filter(|t| c.grants.contains(&t.topic.id))
                        .map(|t| (t.topic.id, t.topic.name.clone()))
                        .collect();
                    let tone = rgb(warning());
                    let mut body = ui::column()
                        .gap(px(SECTION_GAP))
                        .child(
                            ui::row()
                                .gap(px(12.))
                                .child(
                                    // A tinted tile keeps the mark legible in both themes and
                                    // keeps the tile from reading as empty while it decodes.
                                    div()
                                        .flex_none()
                                        .size(px(40.))
                                        .rounded(px(10.))
                                        .bg(ui::ink(0x08))
                                        .border_1()
                                        .border_color(ui::ink(0x12))
                                        .flex()
                                        .items_center()
                                        .justify_center()
                                        .child(if meep_render::brands::mark(&c.label).is_some() {
                                            meep_render::brands::logo(&c.label, 22.)
                                        } else {
                                            div().child(
                                                Icon::new(Glyph::Plug).size(px(18.)).text_color(
                                                    rgb(ui::theme::color(ui::SECONDARY)),
                                                ),
                                            )
                                        }),
                                )
                                .child(
                                    ui::column()
                                        .flex_1()
                                        .min_w_0()
                                        .gap(px(2.))
                                        .child(ui::heading("health-name", c.label.clone()))
                                        .children(c.account.clone().map(|account| {
                                            ui::caption(if c.kind == "posthog" {
                                                format!("Project · {account}")
                                            } else {
                                                account
                                            })
                                            .truncate()
                                        })),
                                ),
                        )
                        .child(
                            ui::column()
                                .gap(px(6.))
                                .p(px(12.))
                                .rounded(px(10.))
                                .bg(rgb(warning()).opacity(0.08))
                                .border_1()
                                .border_color(rgb(warning()).opacity(0.22))
                                .child(
                                    ui::row()
                                        .gap(px(8.))
                                        .child(
                                            Icon::new(Glyph::TriangleAlert)
                                                .size(px(14.))
                                                .text_color(tone),
                                        )
                                        .child(div().font_weight(FontWeight::SEMIBOLD).child(
                                            if expired { "Signed out" } else { "Not working" },
                                        ))
                                        .children(
                                            since.map(|t| ui::caption(t).ml_auto().flex_none()),
                                        ),
                                )
                                .child(div().line_height(relative(1.5)).child(if expired {
                                    "Sign in again and Meep picks up where it stopped."
                                } else {
                                    "Meep keeps retrying. Work that needs it waits until it's back."
                                }))
                                // The raw service error is for diagnosis, behind a disclosure.
                                .child({
                                    let key = format!("connection-details-{}", c.id);

                                    self.details_disclosure(
                                        "connection-details",
                                        key,
                                        c.summary.clone(),
                                        cx,
                                    )
                                }),
                        );
                    if !topics.is_empty() {
                        let mut list = ui::column().gap(px(6.));
                        for (tid, name) in topics {
                            list = list.child(
                                line(format!("health-topic-{tid}"), false)
                                    .gap(px(10.))
                                    .px(px(10.))
                                    .py(px(8.))
                                    .rounded(px(8.))
                                    .border_1()
                                    .border_color(ui::ink(0x12))
                                    .child(ui::nav::glyph(Glyph::AtSign, false))
                                    .child(div().flex_1().min_w_0().truncate().child(name))
                                    .child(ui::nav::glyph(Glyph::ChevronRight, false))
                                    .on_click(cx.listener(move |s, _, w, cx| {
                                        s.go(Page::Topic(tid, Tab::Chat, None), w, cx)
                                    })),
                            );
                        }
                        body = body.child(section("Topics using it", list));
                    }
                    let mut pane = Pane::new("Connection", body);
                    let connection = c.id.clone();
                    pane.actions
                        .push(control("reconnect", label, true, cx, move |s, w, cx| {
                            s.fix_problem(connection.clone(), Some(id), w, cx)
                        }));
                    pane
                }),
        }
        .unwrap_or_else(|| Pane::new("Details", ui::caption("This item is no longer available.")));
        let frame = ui::column().h_full().min_h_0().gap_0().flex_1().min_w_0();
        // The item replaced its tab's list: the crumbs lead back to it.
        let header = crumb_bar(
            topic_crumbs(
                id,
                &state.topic.name,
                Some(&state.topic.display_icon()),
                tab,
                Some((
                    None,
                    pane.title.clone().unwrap_or_else(|| pane.kicker.clone()),
                )),
                cx,
            ),
            pane.title.is_some().then(|| pane.kicker.clone()),
            pane.tools
                .into_iter()
                .chain(self.show_overview_button(w, cx)),
        );
        frame
            .child(header)
            .child(
                scroll("details-scroll")
                    .px(px(PAGE_X))
                    .pt(px(PAGE_TOP))
                    // A footer note casts a fade over the scroll's end; the extra room lets
                    // the last line scroll clear of it.
                    .pb(px(if pane.footer.is_some() { 36. } else { 20. }))
                    .when(pane.conversation, |s| s.items_center())
                    .child(
                        pane.body
                            .when(pane.conversation, |b| b.w_full().max_w(px(READING))),
                    ),
            )
            .when(!pane.actions.is_empty() || pane.footer.is_some(), |el| {
                el.child(
                    ui::column()
                        .flex_none()
                        .gap(px(10.))
                        .border_t_1()
                        .border_color(ui::ink(0x0f))
                        .px(px(20.))
                        .py(px(12.))
                        // A footer that holds a note covers part of the scroll; the shadow
                        // shows the content continues underneath.
                        .when(pane.footer.is_some(), |el| {
                            el.border_color(ui::ink(0x1a)).shadow(vec![BoxShadow {
                                color: hsla(0., 0., 0., 0.08),
                                offset: point(px(0.), px(-6.)),
                                blur_radius: px(12.),
                                spread_radius: px(0.),
                                inset: false,
                            }])
                        })
                        .when(pane.conversation, |s| s.items_center())
                        .child(
                            ui::column()
                                .w_full()
                                .gap(px(10.))
                                .when(pane.conversation, |b| b.max_w(px(READING)))
                                .children(pane.footer)
                                .child(ui::row().flex_wrap().gap(px(8.)).children(pane.actions)),
                        ),
                )
            })
    }
    /// An agent report, laid out as a PostHog Scout report: what kind and how
    /// urgent, the headline and its lead, the number that matters, the
    /// proposal with Implement or Investigate, then the evidence it rests on.
    fn report_pane(&self, s: &TopicState, t: &Thread, cx: &Context<Self>) -> Pane {
        use super::pages::{report_open, report_status};
        use meep_topic::{ReportOutcome, ReportVerdict};
        let id = s.topic.id;
        let thread = t.id;
        let owner = cx.entity().downgrade();
        let sources = t.report_sources.clone().unwrap_or_default();
        let open = report_open(t);
        // Work started from this report; the task that wrote it is not its work.
        let tasks: Vec<_> = s
            .tasks
            .iter()
            .filter(|task| task.from_thread == Some(t.id))
            .collect();
        let running = tasks
            .iter()
            .filter(|task| matches!(task.column, Column::InProgress | Column::NeedsYou))
            .max_by_key(|task| task.updated_at)
            .map(|task| task.id);
        let mut body = ui::column().gap(px(36.));

        // Kind and urgency, how far along it is, when it last changed; the
        // verdicts sit at the end of the same line.
        let mut meta = ui::row()
            .min_w_0()
            .gap(px(6.))
            .text_size(px(13.))
            .text_color(rgb(ui::theme::color(ui::SECONDARY)));
        // The priority as a word in its tone, as Scout sets it.
        if let Some(p) = sources.priority {
            meta = meta
                .child(
                    div()
                        .flex_none()
                        .font_weight(FontWeight::MEDIUM)
                        .text_color(rgb(if open {
                            super::pages::priority_tone(p)
                        } else {
                            ui::theme::color(ui::TERTIARY)
                        }))
                        .child(p.label()),
                )
                .child("·");
        }
        if sources.external.is_some() {
            meta = meta
                .child(div().flex_none().child("PostHog Scout"))
                .child("·");
        }
        // A closed report's pill already says how it ended.
        if let Some(status) = report_status(s, t).filter(|_| open) {
            meta = meta.child(div().flex_none().child(status)).child("·");
        }
        meta = meta.child(div().min_w_0().truncate().child(format!(
            "Updated {}",
            super::pages::ago(Utc::now() - super::pages::message_time(t))
        )));
        let verdict = |label: &'static str,
                       glyph: Glyph,
                       outcome: ReportOutcome,
                       reasons: &'static [&'static str]| {
            let owner = owner.clone();
            ui::button(SharedString::from(format!("report-{label}")), label)
                .small()
                .icon(glyph)
                .dropdown_menu_with_anchor(gpui::Anchor::TopRight, move |mut m: PopupMenu, _, _| {
                    m = m.label(if outcome == ReportOutcome::Resolved {
                        "How was it resolved?"
                    } else {
                        "Why dismiss it?"
                    });
                    for reason in reasons {
                        let owner = owner.clone();
                        m = m.item(PopupMenuItem::new(*reason).on_click(move |_, _, cx| {
                            let _ = owner.update(cx, |s, cx| {
                                s.issue(
                                    id,
                                    Command::SetReportVerdict {
                                        thread,
                                        outcome: Some(outcome),
                                        reason: (*reason).into(),
                                    },
                                );
                                cx.notify()
                            });
                        }));
                    }
                    m
                })
        };
        let closing: AnyElement = match &sources.verdict {
            Some(ReportVerdict {
                outcome, reason, ..
            }) => ui::row()
                .flex_none()
                .gap(px(8.))
                .child(
                    ui::row()
                        .gap(px(5.))
                        .px(px(8.))
                        .h(px(24.))
                        .rounded_full()
                        .bg(ui::ink(0x0a))
                        .text_size(px(12.))
                        .child(
                            Icon::new(if *outcome == ReportOutcome::Resolved {
                                Glyph::CircleCheck
                            } else {
                                Glyph::EyeOff
                            })
                            .size(px(12.)),
                        )
                        .child(format!(
                            "{} · {reason}",
                            if *outcome == ReportOutcome::Resolved {
                                "Resolved"
                            } else {
                                "Dismissed"
                            }
                        )),
                )
                .child(
                    ui::button("report-reopen", "Reopen")
                        .small()
                        .on_click(cx.listener(move |s, _, _, cx| {
                            s.issue(
                                id,
                                Command::SetReportVerdict {
                                    thread,
                                    outcome: None,
                                    reason: String::new(),
                                },
                            );
                            cx.notify()
                        })),
                )
                .into_any_element(),
            None => ui::row()
                .flex_none()
                .gap(px(2.))
                .child(verdict(
                    "Resolve",
                    Glyph::CircleCheck,
                    ReportOutcome::Resolved,
                    &["Fixed", "Fixed outside Meep", "No action needed"],
                ))
                .child(verdict(
                    "Dismiss",
                    Glyph::EyeOff,
                    ReportOutcome::Dismissed,
                    &[
                        "Already fixed",
                        "Report unclear",
                        "Analysis wrong",
                        "Won’t fix: intentional",
                        "Not relevant",
                    ],
                ))
                .into_any_element(),
        };

        // The headline and its lead; the rest of the write-up waits behind
        // Full report.
        let (lead, rest) = match t.summary.trim().split_once("\n\n") {
            Some((lead, rest)) => (lead.trim().to_owned(), rest.trim().to_owned()),
            None => (t.summary.trim().to_owned(), String::new()),
        };
        // The impact line and the Proposal already say these; the full report
        // keeps only what they do not.
        let rest = without_sections(
            &rest,
            &[
                (sources.impact.is_some(), &["impact"][..]),
                (
                    sources.proposal.is_some(),
                    &[
                        "solution",
                        "fix",
                        "proposed fix",
                        "recommendation",
                        "next steps",
                        "proposal",
                    ][..],
                ),
            ],
        );
        let full_key = format!("report-full-{thread}");
        let full = self.toggled_groups.contains(&full_key);
        // The rest of the write-up opens from the action line, beside the verdicts.
        let full_button = (!rest.is_empty()).then(|| {
            let key = full_key.clone();
            ui::button(
                "report-full",
                if full { "Hide report" } else { "Full report" },
            )
            .small()
            .icon(Glyph::FileText)
            .on_click(cx.listener(move |s, _, _, cx| {
                let open = !s.toggled_groups.remove(&key);
                if open {
                    s.toggled_groups.insert(key.clone());
                }
                s.folds.toggled(key.clone(), open, cx);
                cx.notify()
            }))
        });
        let mut headline = ui::column()
            .gap(px(14.))
            .child(
                ui::row()
                    .gap(px(2.))
                    .child(meta.flex_1().mr(px(10.)))
                    .children(full_button)
                    .child(closing),
            )
            .child(
                div()
                    .text_size(px(20.))
                    .line_height(relative(1.3))
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(t.subject.clone()),
            )
            .child(
                div()
                    .id("report-body")
                    .role(Role::Label)
                    .aria_label(super::pages::plain_line(&lead))
                    .child(
                        meep_shell::transcript::chat_markdown(
                            format!("report-lead-{thread}").into(),
                            lead.clone(),
                        )
                        .text_size(px(15.))
                        .line_height(relative(1.55)),
                    ),
            );
        // The number that matters: its figure stands out, the sentence follows.
        if let Some(impact) = sources.impact.as_deref() {
            let (figure, after) = match impact.split_once(' ') {
                Some((first, after))
                    if first.chars().next().is_some_and(|c| c.is_ascii_digit()) =>
                {
                    (first.to_owned(), after.to_owned())
                }
                _ => (String::new(), impact.to_owned()),
            };
            // One line in the text's own size: the figure in weight, what it counts after.
            headline = headline.child(
                ui::row()
                    .id("report-impact")
                    .items_start()
                    .gap(px(5.))
                    .pt(px(4.))
                    .text_size(px(15.))
                    .line_height(relative(1.55))
                    .when(!figure.is_empty(), |r| {
                        r.child(
                            div()
                                .flex_none()
                                .font_weight(FontWeight::SEMIBOLD)
                                .child(figure),
                        )
                    })
                    .child(div().flex_1().min_w_0().child(after)),
            );
        }
        // The write-up under the lead, flat in the page's own type.
        if !rest.is_empty() {
            headline = headline.children(self.folds.reveal(&full_key, full, cx, || {
                meep_shell::transcript::chat_markdown(format!("report-rest-{thread}").into(), rest)
                    .text_size(px(15.))
                    .line_height(relative(1.55))
                    .into_any_element()
            }));
        }
        body = body.child(headline);

        // Proposal: what the agent would do, and the buttons that do it.
        let heading = |text: &'static str| {
            div()
                .text_size(px(16.))
                .font_weight(FontWeight::SEMIBOLD)
                .child(text)
        };
        // Implement and Investigate are turns in the topic's conversation, with the
        // report attached. They wait for the agent's current work, as ⌘↵ does.
        let start = move |s: &mut Self, implement: bool, w: &mut Window, cx: &mut Context<Self>| {
            let Some(report) = s
                .states
                .iter()
                .find(|st| st.topic.id == id)
                .and_then(|st| st.threads.iter().find(|t| t.id == thread))
            else {
                return;
            };
            let subject = meep_topic::title_line(&report.subject);
            let ask = if implement {
                format!(
                    "Implement the report “{subject}”: confirm the problem still happens, make \
                     the change its proposal describes (open a pull request when it is code), \
                     then tell me what you changed and how you checked it."
                )
            } else {
                format!(
                    "Investigate the report “{subject}”: confirm the problem and find its root \
                     cause, and publish what you find as a report with evidence. Don’t change \
                     anything yet."
                )
            };
            // The agent reads the report itself (summary, proposal, evidence) with its
            // topic tools; the person's line stays short.
            let text = format!("{ask}\n\nReport {thread}");
            if s.issue(
                id,
                Command::Chat {
                    message_id: MessageId(Uuid::new_v4()),
                    text,
                    task_id: TaskId(Uuid::new_v4()),
                    queue: true,
                },
            ) {
                s.open_chat(w, cx);
            }
        };
        let mut next = ui::row().flex_wrap().gap(px(8.));
        if let Some(task) = running {
            next = next.child(
                control(
                    "report-open-task",
                    "Open the running task",
                    true,
                    cx,
                    move |s, w, cx| {
                        s.go(Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))), w, cx)
                    },
                )
                .icon(Glyph::Clock),
            );
        } else if open {
            next = next
                .child(
                    control(
                        "report-implement",
                        "Implement",
                        true,
                        cx,
                        move |s, w, cx| start(s, true, w, cx),
                    )
                    .icon(Glyph::Wrench)
                    .tooltip("Start an agent task that makes the change"),
                )
                .child(
                    control(
                        "report-investigate",
                        "Investigate",
                        false,
                        cx,
                        move |s, w, cx| start(s, false, w, cx),
                    )
                    .icon(Glyph::Search)
                    .tooltip("Start an agent task that finds the root cause"),
                );
        }
        let ask = format!(
            "About the report “{}”: ",
            meep_topic::title_line(&t.subject)
        );
        // Asking is the light option: text, not another box.
        next = next.child(
            ui::button("report-ask", "Ask about it")
                .icon(Glyph::Sparkles)
                .h(px(28.))
                .px(px(10.))
                .rounded(px(6.))
                .on_click(cx.listener(move |s, _, w, cx| {
                    cx.stop_propagation();
                    s.ask_in_chat(&ask, w, cx);
                    cx.notify()
                })),
        );
        // A closed report has nothing left to start.
        body = body.when(open || running.is_some(), |body| {
            body.child(
                ui::column()
                    .gap(px(10.))
                    .child(heading(if sources.proposal.is_some() {
                        "Proposal"
                    } else {
                        "Next step"
                    }))
                    .children(sources.proposal.clone().map(|p| {
                        div()
                            .text_size(px(15.))
                            .line_height(relative(1.55))
                            .child(p)
                    }))
                    .child(next.pt(px(4.))),
            )
        });

        // Evidence: three first, the rest on request.
        // Named references read as evidence without a source to open.
        let items: Vec<meep_topic::ReportEvidence> = sources
            .evidence
            .iter()
            .cloned()
            .chain(
                sources
                    .references
                    .iter()
                    .map(|r| meep_topic::ReportEvidence {
                        description: r.clone(),
                        source_id: String::new(),
                        kind: None,
                        at: None,
                    }),
            )
            .collect();
        if !items.is_empty() {
            let all_key = format!("report-evidence-{thread}");
            let all = self.toggled_groups.contains(&all_key);
            let total = items.len();
            let mut list = ui::column().gap_0();
            let mut more = ui::column().gap_0();
            for (i, e) in items.into_iter().enumerate() {
                let (text, kind, at) = (e.description, e.kind, e.at);
                let source = Some(e.source_id).filter(|s| !s.is_empty());
                let link = source
                    .as_ref()
                    .filter(|s| s.starts_with("https://") || s.starts_with("http://"))
                    .cloned();
                let when = at.map(|at| {
                    let local = at.with_timezone(&chrono::Local);
                    if local.date_naive() == chrono::Local::now().date_naive() {
                        "Today".to_owned()
                    } else {
                        local.format("%b %e").to_string()
                    }
                });
                let row = ui::row()
                    .id(SharedString::from(format!("report-source-{i}")))
                    .items_start()
                    .gap(px(12.))
                    .py(px(7.))
                    .text_size(px(14.))
                    .when_some(link.clone(), |r, url| {
                        r.cursor_pointer()
                            .on_click(move |_, _, cx| cx.open_url(&url))
                    })
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .gap(px(2.))
                            .child(div().line_height(relative(1.5)).line_clamp(2).child(text))
                            .children(
                                source
                                    .filter(|_| link.is_none())
                                    .map(|s| ui::caption(s).truncate()),
                            ),
                    )
                    .child(
                        div()
                            .flex_none()
                            .w(px(16.))
                            .pt(px(3.))
                            .flex()
                            .justify_center()
                            .child(
                                Icon::new(if link.is_some() && kind.is_none() {
                                    Glyph::ExternalLink
                                } else {
                                    super::pages::evidence_glyph(kind.as_deref())
                                })
                                .size(px(14.))
                                .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                            ),
                    )
                    .child(
                        div()
                            .flex_none()
                            .w(px(52.))
                            .pt(px(1.))
                            .text_right()
                            .text_size(px(13.))
                            .line_height(px(21.))
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .children(when),
                    );
                if i < 3 {
                    list = list.child(row);
                } else {
                    more = more.child(row);
                }
            }
            let list = list.children(
                self.folds
                    .reveal(&all_key, all, cx, || more.into_any_element()),
            );
            let toggle = (total > 3).then(|| {
                let key = all_key.clone();
                ui::row()
                    .id("report-evidence-all")
                    .role(Role::Button)
                    .cursor_pointer()
                    .text_size(px(13.))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                    .child(if all {
                        "Show fewer".to_owned()
                    } else {
                        format!("See all {total}")
                    })
                    .on_click(cx.listener(move |s, _, _, cx| {
                        let open = !s.toggled_groups.remove(&key);
                        if open {
                            s.toggled_groups.insert(key.clone());
                        }
                        s.folds.toggled(key.clone(), open, cx);
                        cx.notify()
                    }))
            });
            body = body.child(
                ui::column()
                    .gap(px(6.))
                    .child(
                        ui::row()
                            .child(heading("Evidence").flex_1())
                            .children(toggle),
                    )
                    .child(list),
            );
        }

        // Work started from it.
        if !tasks.is_empty() {
            let mut links = related_group();
            for (i, task) in tasks.into_iter().enumerate() {
                let target = task.id;
                links = links.child(
                    related_row(
                        format!("outcome-{i}"),
                        "Task",
                        meep_topic::title_line(&task.title),
                        Some(task.column),
                    )
                    .on_click(cx.listener(move |s, _, w, cx| s.open_beside(id, target, w, cx))),
                );
            }
            body = body.child(
                ui::column()
                    .gap(px(10.))
                    .child(heading("Work on this"))
                    .child(links),
            );
        }

        // Up and down through the inbox's reports, as in the Scout queue.
        let order: Vec<ThreadId> = super::pages::ordered_threads(s, false)
            .into_iter()
            .map(|t| t.id)
            .collect();
        let at = order.iter().position(|t| *t == thread);
        let step = |delta: isize| {
            at.and_then(|i| order.get((i as isize + delta).max(0) as usize))
                .filter(|t| **t != thread)
                .copied()
        };
        let mut tools: Vec<AnyElement> = vec![];
        if let Some(i) = at.filter(|_| order.len() > 1) {
            tools.push(
                ui::caption(format!("{} of {}", i + 1, order.len()))
                    .mr(px(4.))
                    .into_any_element(),
            );
            for (key, glyph, label, target) in [
                (
                    "report-previous",
                    Glyph::ChevronUp,
                    "Previous report",
                    step(-1),
                ),
                ("report-next", Glyph::ChevronDown, "Next report", step(1)),
            ] {
                tools.push(
                    ui::icon_button(key, glyph, label)
                        .disabled(target.is_none())
                        .on_click(cx.listener(move |s, _, w, cx| {
                            if let Some(t) = target {
                                s.go(Page::Topic(id, Tab::Inbox, Some(Detail::Thread(t))), w, cx)
                            }
                        }))
                        .into_any_element(),
                );
            }
        }
        // An imported Scout report links back to where it lives in PostHog.
        if let Some(url) = sources.external.as_ref().map(|e| e.url.clone()) {
            tools.push(
                ui::icon_button(
                    "report-open-external",
                    Glyph::ExternalLink,
                    "Open in PostHog",
                )
                .tooltip("Open in PostHog")
                .on_click(move |_, _, cx| cx.open_url(&url))
                .into_any_element(),
            );
        }
        let archive = owner.clone();
        tools.push(
            ui::icon_button("thread-more", Glyph::Ellipsis, "More actions")
                .dropdown_menu_with_anchor(gpui::Anchor::TopRight, move |m: PopupMenu, _, _| {
                    let archive = archive.clone();
                    m.item(
                        PopupMenuItem::new("Archive")
                            .icon(Icon::new(Glyph::Archive))
                            .on_click(move |_, w, cx| {
                                let _ = archive.update(cx, |s, cx| {
                                    if s.issue(id, Command::ArchiveThread { thread }) {
                                        s.go(Page::Topic(id, Tab::Inbox, None), w, cx)
                                    }
                                });
                            }),
                    )
                })
                .into_any_element(),
        );
        // The bar names the report; the topic is already in the header above it.
        Pane {
            kicker: String::new(),
            failed: false,
            body,
            footer: None,
            actions: vec![],
            title: Some(super::pages::short_subject(&t.subject)),
            tools,
            conversation: true,
        }
    }
    fn thread(&self, s: &TopicState, t: &Thread, _w: &Window, cx: &Context<Self>) -> Pane {
        let mut actions = Vec::new();
        let id = s.topic.id;
        let thread = t.id;
        let mut body = ui::column().gap(px(SECTION_GAP));
        // Agent reports read as their own page.
        if t.is_agent_report() {
            return self.report_pane(s, t, cx);
        }
        let banner = self
            .needs
            .iter()
            .any(|n| matches!(n, NeedsYouItem::Problem { topics, .. } if topics.contains(&id)));
        // Sorting state reads after the conversation it is about.
        let mut status = ui::column().gap(px(12.));
        let has_status = t.report_sources.is_some()
            || matches!(t.state, ThreadState::Sorting)
            || matches!(&t.state, ThreadState::NeedsYou { .. } if t.summary.is_empty());
        match &t.state {
            ThreadState::Sorting if t.sort_retry.is_some() => {
                // Sorting failed and will be tried again: a quiet line, not an alarm.
                let retry = t.sort_retry.as_ref().expect("checked above");
                let (title, cause) = retry
                    .reason
                    .split_once(": ")
                    .unwrap_or((retry.reason.as_str(), ""));
                let when = retry.next_at.with_timezone(&chrono::Local).format("%H:%M");
                let key = format!("thread-problem-{thread}");
                status = status.child(
                    ui::row()
                        .id("thread-retry")
                        .items_start()
                        .gap(px(10.))
                        .child(
                            div().w(px(24.)).flex().justify_center().pt(px(2.)).child(
                                Icon::new(Glyph::Clock)
                                    .size(px(14.))
                                    .text_color(rgb(warning())),
                            ),
                        )
                        .child(
                            ui::column()
                                .flex_1()
                                .min_w_0()
                                .gap(px(4.))
                                .child(
                                    div()
                                        .line_height(relative(1.45))
                                        .child(format!("{title}. Trying again at {when}.")),
                                )
                                .child(ui::caption(format!(
                                    "Attempt {} of 6. After that it waits for you.",
                                    retry.failures + 1
                                )))
                                .when(!cause.is_empty(), |el| {
                                    el.child(self.details_disclosure(
                                        "thread-problem-details",
                                        key,
                                        cause.to_owned(),
                                        cx,
                                    ))
                                })
                                .when(!banner, |el| {
                                    el.child(control(
                                        "gateway-settings",
                                        "Open Settings",
                                        false,
                                        cx,
                                        |s, w, cx| s.go(Page::Settings, w, cx),
                                    ))
                                }),
                        ),
                );
            }
            ThreadState::Sorting => {
                status =
                    status.child(
                        ui::row()
                            .gap(px(10.))
                            .child(div().w(px(24.)).flex().justify_center().child(
                                meep_ui::gpui_kit::component::spinner::Spinner::new().small(),
                            ))
                            .child(ui::caption("Working out where this goes…")),
                    );
            }
            ThreadState::NeedsYou { reason, .. } if t.summary.is_empty() => {
                // A failed or declined sort has a reason and no written take.
                let (title, cause) = reason.split_once(": ").unwrap_or((reason, ""));
                status = status.child(
                    warning_panel()
                        .child(
                            ui::row()
                                .gap(px(8.))
                                .child(
                                    Icon::new(Glyph::TriangleAlert)
                                        .size(px(14.))
                                        .text_color(rgb(warning())),
                                )
                                .child(
                                    div()
                                        .font_weight(FontWeight::MEDIUM)
                                        .child(title.to_owned()),
                                ),
                        )
                        // The raw service error is for diagnosis, behind a disclosure.
                        .when(!cause.is_empty(), |el| {
                            let key = format!("thread-problem-{thread}");

                            el.child(
                                div()
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                    .line_height(relative(1.45))
                                    .child("Meep couldn’t sort this message, so it waits here for you."),
                            )
                            .child(self.details_disclosure(
                                "thread-problem-details",
                                key,
                                cause.to_owned(),
                                cx,
                            ))
                        })
                        // The page banner already offers Settings for a broken connection.
                        .when(!banner, |el| {
                            el.child(control(
                                "gateway-settings",
                                "Open Settings",
                                false,
                                cx,
                                |s, w, cx| s.go(Page::Settings, w, cx),
                            ))
                        }),
                );
            }
            _ => {}
        }
        if let Some(sources) = &t.report_sources {
            let mut refs = ui::column().gap(px(4.));
            for e in &sources.evidence {
                refs = refs.child(ui::caption(e.description.clone()));
            }
            for reference in &sources.references {
                refs = refs.child(ui::caption(reference.clone()));
            }
            status = status.child(section("Sources", refs));
        }
        let source = t.question_message().map_or("", |m| m.text.as_str());
        let summary = t.summary.trim();
        let report = if source.is_empty() {
            summary
        } else if summary.is_empty()
            || summary == t.subject.trim()
            || summary == meep_topic::title_line(source)
            || source.trim() == summary
        {
            source
        } else {
            body = body.child(meep_shell::transcript::chat_markdown(
                format!("summary-{thread}").into(),
                summary.to_owned(),
            ));
            source
        };
        if !report.is_empty() {
            body = body.child(
                div()
                    .id("report-body")
                    .role(Role::Label)
                    .aria_label(super::pages::plain_line(report))
                    .child(
                        meep_shell::transcript::chat_markdown(
                            format!("report-{thread}").into(),
                            report.to_owned(),
                        )
                        .text_size(px(ui::BODY)),
                    ),
            );
        }
        if has_status {
            body = body.child(status);
        }
        for receipt in s
            .activity
            .iter()
            .filter(|a| a.subject == Ref::Thread(thread) && a.delivery.is_some())
        {
            body = body.child(ui::caption(receipt.text.clone()));
        }
        let tasks: Vec<_> = s.tasks.iter().filter(|task| t.links_task(task)).collect();
        if !tasks.is_empty() {
            let mut links = related_group();
            for (i, task) in tasks.into_iter().enumerate() {
                let target = task.id;
                links = links.child(
                    related_row(
                        format!("outcome-{i}"),
                        "Task",
                        meep_topic::title_line(&task.title),
                        Some(task.column),
                    )
                    .on_click(cx.listener(move |s, _, w, cx| s.open_beside(id, target, w, cx))),
                );
            }
            body = body.child(section("Linked tasks", links));
        }
        if !t.is_agent_report()
            && let ThreadState::NeedsYou { suggestions, .. } = &t.state
        {
            for (i, sugg) in suggestions.iter().enumerate() {
                let suggestion = sugg.clone();
                let version = t.review_version;
                let label = match sugg {
                    Suggestion::DraftReply { .. } => "Draft a reply",
                    Suggestion::MakeTask { .. } => "Make a task",
                    Suggestion::Investigate => "Investigate",
                    Suggestion::AnswerInChat => "Answer in chat",
                    Suggestion::AcceptEvidence { task, fact, .. } => {
                        if let Some(text) = fact {
                            body = body.child(section("Proposed fact", text.clone()));
                        }
                        if let Some(task) = task.and_then(|id| s.tasks.iter().find(|t| t.id == id))
                        {
                            body = body.child(section("Related task", task.title.clone()));
                        }
                        match (task.is_some(), fact.is_some()) {
                            (true, true) => "Save fact and attach to task",
                            (true, false) => "Attach to task",
                            _ => "Save fact",
                        }
                    }
                    Suggestion::ChooseFileRevision {
                        path,
                        current,
                        candidate,
                        use_candidate,
                    } => {
                        let revision = if *use_candidate { *candidate } else { *current };
                        let path = path.clone();
                        body = body.child(control(
                            format!("save-file-{revision}"),
                            format!("Save revision {revision}…"),
                            false,
                            cx,
                            move |s, w, cx| s.save_file_revision(id, &path, revision, w, cx),
                        ));
                        if *use_candidate {
                            body = body
                                .child(ui::caption(format!("Offline edit · revision {candidate}")));
                            "Use offline revision"
                        } else {
                            body = body.child(ui::caption(format!(
                                "Current contents · revision {current}"
                            )));
                            "Keep current revision"
                        }
                    }
                    Suggestion::ResolveFacts { resolution, .. } => match resolution {
                        FactResolution::KeepChanged => "Keep A",
                        FactResolution::KeepExisting => "Keep B",
                        FactResolution::KeepBoth => "Keep both",
                        FactResolution::KeepDependent => "Keep B",
                        FactResolution::RetireDependent => "Retire B",
                    },
                    Suggestion::SortAgain { .. } => "Sort again",
                    Suggestion::Leave => "Leave it",
                };
                actions.push(control(
                    format!("answer-{i}"),
                    label,
                    i == 0,
                    cx,
                    move |s, _, _| {
                        s.issue(
                            id,
                            Command::Answer {
                                thread,
                                expected_review: Some(version),
                                suggestion: suggestion.clone(),
                                task_id: TaskId(Uuid::new_v4()),
                            },
                        );
                    },
                ));
            }
        }
        // The question and its answers sit together, right under the conversation.
        if !t.is_agent_report()
            && let ThreadState::NeedsYou { reason, .. } = &t.state
            && !t.summary.is_empty()
        {
            let answers: Vec<_> = std::mem::take(&mut actions);
            body = body.child(
                ui::column()
                    .id("your-call")
                    .gap(px(10.))
                    .p(px(12.))
                    .rounded(px(10.))
                    .bg(rgb(super::pages::UNREAD).opacity(0.06))
                    .border_1()
                    .border_color(rgb(super::pages::UNREAD).opacity(0.22))
                    .child(
                        ui::column()
                            .gap(px(4.))
                            .child(
                                ui::caption("Your call")
                                    .font_weight(FontWeight::MEDIUM)
                                    .text_color(rgb(super::pages::UNREAD)),
                            )
                            .child(
                                div()
                                    .font_weight(FontWeight::MEDIUM)
                                    .line_height(relative(1.45))
                                    .child(reason.clone()),
                            ),
                    )
                    .when(!answers.is_empty(), |c| {
                        c.child(ui::row().flex_wrap().gap(px(8.)).children(answers))
                    }),
            );
        }
        let owner = cx.entity().downgrade();
        let mut skip = None;
        if !matches!(t.state, ThreadState::Skipped { .. })
            && let Some(m) = t.messages.first()
        {
            let (connection, channel) = match &m.reply_target() {
                Some(Source::Connection {
                    connection,
                    channel,
                }) => (Some(connection.clone()), Some(channel.clone())),
                _ => (None, None),
            };
            let subject = t.subject.clone();
            let by = m.author.clone();
            let owner = owner.clone();
            skip = Some(move |w: &mut Window, cx: &mut App| {
                let _ = owner.update(cx, |s, cx| {
                    let rule = Rule {
                        id: RuleId(Uuid::new_v4()),
                        text: format!("Skip messages from {by} about “{subject}”."),
                        effect: RuleEffect::Skip(Matcher {
                            connection: connection.clone(),
                            channel: channel.clone(),
                        }),
                        from_task: None,
                        created_at: Utc::now(),
                    };
                    if s.issue(id, Command::AddRule { rule }) {
                        s.go(Page::Topic(id, Tab::Rules, None), w, cx);
                    }
                });
            });
        }
        let mut kicker = t
            .messages
            .first()
            .map(|m| self.sender(&s.topic, m))
            .unwrap_or_else(|| "Inbox".into());
        if let Some(Source::Connection {
            connection,
            channel,
        }) = t.messages.first().and_then(Message::reply_target).as_ref()
            && !channel.is_empty()
        {
            let channel = s
                .topic
                .watches()
                .find(|w| w.connection == *connection && w.key == *channel)
                .map_or(channel.as_str(), |w| w.label.as_str());
            if channel != kicker {
                kicker.push_str(&format!(" · {channel}"));
            }
        }
        kicker.push_str(&format!(
            " · {}",
            super::pages::message_time(t)
                .with_timezone(&chrono::Local)
                .format("%b %e")
        ));
        // Secondary actions stay out of the way, in the bar's menu.
        let archive = owner.clone();
        let skip = skip.map(std::rc::Rc::new);
        let more = ui::icon_button("thread-more", Glyph::Ellipsis, "More actions")
            .dropdown_menu_with_anchor(gpui::Anchor::TopRight, move |mut m: PopupMenu, _, _| {
                if let Some(skip) = skip.clone() {
                    m = m.item(
                        PopupMenuItem::new("Skip messages like this")
                            .icon(Icon::new(Glyph::Shield))
                            .on_click(move |_, w, cx| skip(w, cx)),
                    );
                }
                let archive = archive.clone();
                m.item(
                    PopupMenuItem::new("Archive")
                        .icon(Icon::new(Glyph::Archive))
                        .on_click(move |_, w, cx| {
                            let _ = archive.update(cx, |s, cx| {
                                if s.issue(id, Command::ArchiveThread { thread }) {
                                    s.go(Page::Topic(id, Tab::Inbox, None), w, cx)
                                }
                            });
                        }),
                )
            });
        Pane {
            kicker,
            failed: false,
            body,
            footer: None,
            actions,
            title: Some(super::pages::short_subject(&t.subject)),
            tools: vec![more.into_any_element()],
            conversation: true,
        }
    }
    fn task(
        &self,
        s: &TopicState,
        t: &meep_topic::Task,
        // In the side chat the composer starts and stops the run.
        panel: bool,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Pane {
        let id = s.topic.id;
        let task = t.id;
        let mut actions = Vec::new();
        // The title sits in the bar; the body opens with how the task runs.
        let mut header = ui::column().gap(px(4.));
        // A run that could not finish waits on the person with no proposed action.
        let failed = t.column == Column::NeedsYou
            && t.action.is_none()
            && !t.review_before_start
            && t.assignment.as_ref() != Some(&InboxAssignment::Human)
            && t.result.is_some();
        // A routine retries itself; its card keeps the routine's own wording.
        let routine = matches!(t.assignment, Some(InboxAssignment::Routine(_)));
        let evidence_hold = t
            .action
            .as_ref()
            .and_then(|a| s.check_action_evidence(a).err());
        let version = t.review_version;
        if let Some(assignment) = &t.assignment {
            let label = match assignment {
                meep_topic::InboxAssignment::ChatAnswer => "Chat answer · PostHog Tasks".to_owned(),
                meep_topic::InboxAssignment::Human => "For you".to_owned(),
                meep_topic::InboxAssignment::Session => "For the topic agent".to_owned(),
                meep_topic::InboxAssignment::Investigate => "Sub-agent · PostHog Tasks".to_owned(),
                meep_topic::InboxAssignment::Routine(key) => {
                    let name = s
                        .topic
                        .routines
                        .iter()
                        .find(|r| r.binding.id == *key)
                        .map_or(key.as_str(), |r| r.binding.name.as_str());
                    format!("Automation · {name}")
                }
            };
            let glyph = match assignment {
                meep_topic::InboxAssignment::ChatAnswer => Glyph::MessageCircle,
                meep_topic::InboxAssignment::Human => Glyph::UserRound,
                meep_topic::InboxAssignment::Session => Glyph::AtSign,
                meep_topic::InboxAssignment::Investigate => Glyph::Search,
                meep_topic::InboxAssignment::Routine(_) => Glyph::Workflow,
            };
            header = header.child(
                ui::row()
                    .gap(px(6.))
                    .child(
                        Icon::new(glyph)
                            .size(px(13.))
                            .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                    )
                    .child(ui::caption(label)),
            );
        }
        // An empty header would still take a section gap.
        let mut body = ui::column()
            .gap(px(SECTION_GAP))
            .when(t.assignment.is_some(), |b| b.child(header));
        // Where the work came from opens the conversation, as its context.
        // Opened beside its own thread, the thread is already in view.
        if let Some(thread) = t
            .from_thread
            .filter(|tid| !matches!(self.page, Page::Topic(_, _, Some(Detail::Thread(open))) if open == *tid))
            .and_then(|tid| s.threads.iter().find(|v| v.id == tid))
        {
            let tid = thread.id;
            let tab = super::pages::thread_tab(thread);
            body = body.child(
                ui::row()
                    .id("came-from")
                    .role(Role::Link)
                    .self_start()
                    .gap(px(6.))
                    .cursor_pointer()
                    .text_size(px(12.))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                    .child(Icon::new(Glyph::Inbox).size(px(13.)))
                    .child(format!(
                        "From {} · {}",
                        thread
                            .messages
                            .first()
                            .and_then(Message::reply_target)
                            .map(|src| self.source(&s.topic, &src))
                            .unwrap_or_else(|| "the source".into()),
                        super::pages::short_subject(&thread.subject)
                    ))
                    .child(Icon::new(Glyph::ChevronRight).size(px(11.)))
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(
                            Page::Topic(id, tab, Some(Detail::Thread(tid))),
                            w,
                            cx,
                        )
                    })),
            );
        }
        let has_run = !self.run_messages.is_empty() || self.sending_runs.contains(&t.id);
        // Finished work with no transcript adds nothing, not even a gap.
        if panel
            || has_run
            || t.instructions.is_some()
            || matches!(t.column, Column::Todo | Column::InProgress)
        {
            body = body.child(self.run_transcript(s, t, w, cx));
        }

        if t.column == Column::NeedsYou
            && let Some(reason) = &evidence_hold
        {
            body = body.child(ui::caption(reason.to_string()));
        }
        if t.approval_rule
            .is_some_and(|rule| self.just_approved == Some((id, task, rule)))
            && (t.column == Column::Done || t.action.is_none())
        {
            body = body.child(self.after_approval(s, t, cx))
        }
        // Parent and child links read as one group.
        let mut linked_rows = related_group();
        let mut has_linked = false;
        for linked in s
            .tasks
            .iter()
            .filter(|other| t.parent == Some(other.id) || other.parent == Some(task))
        {
            let target = linked.id;
            let kind = if t.parent == Some(target) {
                "Parent"
            } else {
                "Child"
            };
            has_linked = true;
            linked_rows = linked_rows.child(
                related_row(
                    format!("linked-{target}"),
                    kind,
                    meep_topic::title_line(&linked.title),
                    Some(linked.column),
                )
                .on_click(cx.listener(move |s, _, w, cx| {
                    s.go(
                        Page::Topic(id, Tab::Tasks, Some(Detail::Task(target))),
                        w,
                        cx,
                    )
                })),
            );
        }
        if has_linked {
            body = body.child(section("Related work", linked_rows));
        }
        for receipt in s
            .activity
            .iter()
            .filter(|a| a.subject == Ref::Task(task) && a.delivery.is_some())
        {
            body = body.child(section(
                format!(
                    "Delivery · {}",
                    receipt
                        .at
                        .with_timezone(&chrono::Local)
                        .format("%b %e, %H:%M:%S")
                ),
                ui::caption(receipt.text.clone()),
            ));
        }
        if t.column == Column::NeedsYou
            && t.result.as_deref().is_some_and(|text| {
                text.starts_with("Delivery failed:") || text.starts_with("Execution failed:")
            })
        {
            body = body.child(ui::caption(
                "Check the outcome in the connected service before retrying.",
            ));
        }
        if !t.suggestions.is_empty() {
            let mut steps = ui::column().gap(px(8.));
            for (i, title) in t.suggestions.iter().enumerate() {
                let title = title.clone();
                let task_title = t.title.clone();
                steps = steps.child(
                    ui::row()
                        .items_start()
                        .gap(px(12.))
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .line_height(relative(1.5))
                                .child(title.clone()),
                        )
                        // A next step goes back to the topic's agent, in its conversation.
                        .child(
                            control(
                                format!("ask-suggestion-{i}"),
                                "Ask the agent",
                                false,
                                cx,
                                move |s, w, cx| {
                                    let text = format!(
                                        "Follow up on “{}”: {}",
                                        meep_topic::title_line(&task_title),
                                        title
                                    );
                                    s.issue(
                                        id,
                                        Command::Chat {
                                            message_id: MessageId(Uuid::new_v4()),
                                            text,
                                            task_id: TaskId(Uuid::new_v4()),
                                            queue: false,
                                        },
                                    );
                                    s.open_chat(w, cx);
                                },
                            )
                            .flex_none(),
                        ),
                );
            }
            body = body.child(section("Suggested next steps", steps));
        }
        if let Some(question) = &t.input_question {
            body = body.child(section(
                "Question",
                div().line_height(relative(1.55)).child(question.clone()),
            ));
        } else if failed && let Some(reason) = &t.result {
            body = body.child(
                warning_panel()
                    .child(
                        ui::row()
                            .gap(px(8.))
                            .child(
                                Icon::new(Glyph::TriangleAlert)
                                    .size(px(14.))
                                    .text_color(rgb(warning())),
                            )
                            .child(
                                div()
                                    .font_weight(FontWeight::MEDIUM)
                                    .child("Needs attention"),
                            ),
                    )
                    .child(
                        div()
                            .line_height(relative(1.45))
                            .child(super::pages::failure_reason(reason)),
                    )
                    // The raw service error is for diagnosis, behind a disclosure.
                    .child({
                        let key = format!("task-failure-{task}");

                        self.details_disclosure("failure-details", key, reason.clone(), cx)
                    }),
            );
        } else if let Some(result) = &t.result
            && t.draft.as_ref() != Some(result)
            // The run's own last answer already says it.
            && !has_run
            && !panel
        {
            body = body.child(section(
                "Result",
                div().line_height(relative(1.55)).child(result.clone()),
            ))
        }
        let mut draft_card = None;
        if t.column == Column::NeedsYou && t.action.is_some() && t.draft.is_some() {
            // The proposed side effect, ready to edit before it goes out.
            draft_card = Some(
                ui::column()
                    .gap(px(8.))
                    .p(px(12.))
                    .rounded(px(10.))
                    .border_1()
                    .border_color(ui::ink(0x14))
                    .bg(ui::ink(0x03))
                    .child(
                        ui::row()
                            .gap(px(6.))
                            .child(
                                Icon::new(Glyph::Send)
                                    .size(px(13.))
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                            )
                            .child(
                                ui::caption("Draft for your review")
                                    .font_weight(FontWeight::MEDIUM),
                            ),
                    )
                    .child(
                        Textarea::new(&self.draft)
                            .aria_label("Draft reply")
                            .small()
                            .appearance(false)
                            .bordered(false)
                            .p(px(0.))
                            // The field's own inset would push the text off the card's edge.
                            .mx(px(-8.))
                            .text_size(px(ui::BODY))
                            .line_height(relative(1.5))
                            .min_h(px(44.)),
                    ),
            );
        } else if let Some(draft) = &t.draft {
            body = body.child(section(
                "Reviewed draft",
                div().line_height(relative(1.5)).child(draft.clone()),
            ))
        }
        let mut footer = None;
        if t.column == Column::NeedsYou && t.input_question.is_none() {
            let has_draft = t.action.is_some() && t.draft.is_some();
            if self.send_back {
                // In the footer, so the note is in view as soon as send-back opens.
                footer = Some(
                    ui::column()
                        .gap(px(6.))
                        .child(ui::caption("What should change?").font_weight(FontWeight::MEDIUM))
                        .child(
                            Textarea::new(&self.note)
                                .aria_label("What should change?")
                                .min_h(px(56.))
                                .max_h(px(160.)),
                        ),
                );
                actions.push(control(
                    "submit-note",
                    "Send back",
                    true,
                    cx,
                    move |s, w, cx| {
                        let note = s.note.read(cx).value().trim().to_owned();
                        if !note.is_empty()
                            && s.issue(
                                id,
                                Command::SendBack {
                                    task,
                                    note,
                                    expected_review: Some(version),
                                },
                            )
                        {
                            s.send_back = false;
                            s.focus.focus(w, cx);
                        }
                    },
                ));
                actions.push(control("cancel-note", "Cancel", false, cx, |s, w, cx| {
                    s.send_back = false;
                    s.focus.focus(w, cx)
                }));
            } else {
                if failed && !routine {
                    actions.push(control(
                        "retry-task",
                        "Try again",
                        true,
                        cx,
                        move |s, _, _| {
                            s.issue(
                                id,
                                Command::SendBack {
                                    task,
                                    expected_review: Some(version),
                                    note: String::new(),
                                },
                            );
                        },
                    ));
                }
                if evidence_hold.is_none() {
                    actions.push(control(
                        "approve",
                        if failed && !routine {
                            "Dismiss".to_owned()
                        } else {
                            t.review_action_label().to_owned()
                        },
                        !failed && !routine,
                        cx,
                        move |s, _, cx| {
                            s.approve(
                                id,
                                task,
                                version,
                                has_draft.then(|| s.draft.read(cx).value().to_string()),
                            )
                        },
                    ));
                }
                if t.review_before_start && t.parent.is_some() {
                    actions.push(control(
                        "decline-follow-up",
                        "Decline follow-up",
                        false,
                        cx,
                        move |s, _, _| {
                            s.issue(
                                id,
                                Command::DeclineFollowUp {
                                    task,
                                    expected_review: version,
                                },
                            );
                        },
                    ));
                }
                if !t.review_before_start
                    && matches!(t.assignment, Some(InboxAssignment::Routine(_)))
                {
                    actions.push(control(
                        "retry-routine",
                        "Retry routine",
                        failed,
                        cx,
                        move |s, _, _| {
                            s.issue(
                                id,
                                Command::SendBack {
                                    task,
                                    expected_review: Some(version),
                                    note: String::new(),
                                },
                            );
                        },
                    ));
                } else if t.assignment != Some(InboxAssignment::Human) && !failed {
                    actions.push(control(
                        "send-back",
                        "Send back…",
                        false,
                        cx,
                        |s, w, cx| {
                            s.send_back = true;
                            s.note.update(cx, |e, cx| {
                                e.set_value("", w, cx);
                                e.focus(w, cx)
                            })
                        },
                    ));
                }
            }
        }
        if !panel && t.column == Column::Todo && t.queued {
            actions.push(
                control("start-task", "Start", true, cx, move |s, _, _| {
                    s.issue(id, Command::StartTask { task });
                })
                .icon(Glyph::Play),
            );
        }
        if !panel && t.column == Column::InProgress {
            actions.push(
                control("stop-task", "Stop", false, cx, move |s, _, _| {
                    s.issue(id, Command::CancelRun { task });
                })
                .icon(Glyph::Square)
                .tooltip("Stop the agent"),
            );
        }
        // The topic's own agent is implied; only other sources earn a "From" kicker.
        let mut kicker = if t.added_by == Actor::Agent {
            String::new()
        } else {
            format!("From {}", super::pages::actor(&t.added_by))
        };
        if let Actor::Inbox(tid) = t.added_by
            && let Some(src) = s
                .threads
                .iter()
                .find(|v| v.id == tid)
                .and_then(|v| v.messages.first())
                .and_then(Message::reply_target)
        {
            kicker = format!("From {}", self.source(&s.topic, &src));
        }
        // Running work is stopped first; a finished or queued task can go.
        let mut tools = vec![];
        if t.column != Column::InProgress {
            let (id, task) = (s.topic.id, t.id);
            tools.push(
                ui::icon_button("delete-task", Glyph::Trash, "Delete task")
                    .on_click(cx.listener(move |s, _, w, cx| {
                        if s.issue(id, Command::DeleteTask { task }) {
                            s.go(Page::Topic(id, Tab::Tasks, None), w, cx)
                        }
                    }))
                    .into_any_element(),
            );
        }
        // The review's own actions sit on the draft they act on.
        if let Some(card) = draft_card {
            let answers: Vec<_> = if self.send_back {
                vec![]
            } else {
                std::mem::take(&mut actions)
            };
            body = body.child(card.when(!answers.is_empty(), |c| {
                c.child(
                    ui::row()
                        .flex_wrap()
                        .gap(px(8.))
                        .pt(px(4.))
                        .children(answers),
                )
            }));
        }
        // The origin link in the conversation already names where it came from.
        if t.from_thread.is_some() {
            kicker.clear();
        }
        Pane {
            kicker,
            // The failed callout already names the state; a header chip would repeat it.
            failed,
            body,
            footer,
            actions,
            title: Some(meep_topic::title_line(&t.title)),
            tools,
            conversation: true,
        }
    }
    /// A task opened in the side chat: the same one-line bar as the topic chat, with
    /// the task's status mark in place of the topic's. The run itself is the body;
    /// the composer carries the model and starts, steers or stops the agent.
    pub(super) fn task_panel(
        &self,
        state: &TopicState,
        t: &meep_topic::Task,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let pane = self.task(state, t, true, w, cx);
        let inset = self.chat_inset(w);
        let (mark, status) = if pane.failed {
            (
                div().flex_none().child(
                    Icon::new(Glyph::TriangleAlert)
                        .size(px(14.))
                        .text_color(rgb(warning())),
                ),
                "Needs attention",
            )
        } else if t.queued && t.column == Column::Todo {
            (super::tasks_view::status_icon(t.column), "Queued")
        } else {
            (
                super::tasks_view::status_icon(t.column),
                column_name(t.column),
            )
        };
        let mark = div()
            .id("task-status")
            .flex_none()
            .child(mark)
            .tooltip(move |w, cx| {
                meep_ui::gpui_kit::component::tooltip::Tooltip::new(status).build(w, cx)
            });
        let mut tools = pane.tools;
        tools.extend(self.show_overview_button(w, cx));
        let header = crumb_bar(
            topic_crumbs(
                state.topic.id,
                &state.topic.name,
                Some(&state.topic.display_icon()),
                Tab::Tasks,
                Some((
                    Some(mark.into_any_element()),
                    meep_topic::title_line(&t.title),
                )),
                cx,
            ),
            None,
            tools,
        );
        // Sending back has its own note and buttons in place of the composer; any
        // other answer the task still waits for closes the conversation it answers.
        let (body, composer) = if self.send_back {
            (
                pane.body,
                pane.footer.map(|f| {
                    ui::column()
                        .flex_none()
                        .gap(px(10.))
                        .px(px(16.))
                        .py(px(12.))
                        .border_t_1()
                        .border_color(ui::ink(0x0f))
                        .child(f)
                        .child(ui::row().flex_wrap().gap(px(6.)).children(pane.actions))
                        .into_any_element()
                }),
            )
        } else {
            (
                pane.body.when(!pane.actions.is_empty(), |b| {
                    b.child(ui::row().flex_wrap().gap(px(6.)).children(pane.actions))
                }),
                Some(self.run_composer(state, t, w, cx).into_any_element()),
            )
        };
        // Work a routine or another topic handed over names its origin, as the inbox
        // link does for a thread; the topic's own agent and you go unsaid.
        let origin = (t.from_thread.is_none()
            && !matches!(pane.kicker.as_str(), "" | "From You" | "From Agent"))
        .then(|| {
            ui::row()
                .gap(px(6.))
                .text_size(px(12.))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .child(Icon::new(Glyph::Workflow).size(px(13.)))
                .child(pane.kicker.clone())
        });
        let body = ui::column()
            .gap(px(SECTION_GAP))
            .children(origin)
            .child(body);
        ui::column()
            .size_full()
            .child(header)
            .child(
                scroll("task-chat-stream")
                    .track_scroll(&self.run_scroll)
                    .px(px(inset))
                    .pt(px(PAGE_TOP - 8.))
                    .pb(px(16.))
                    .child(body),
            )
            .children(composer)
    }

    /// The conversation's inset: the page edge every topic screen shares, growing into
    /// a centred reading column when the pane is wide.
    pub(super) fn chat_inset(&self, w: &Window) -> f32 {
        // The conversation is the topic's main pane: a centred reading column.
        let width = f32::from(self.topic_pane_width(w)) - 3. * meep_shell::GUTTER;
        ((width - 720.) / 2.).max(PAGE_X)
    }
    /// The header button that brings the Overview back when it is tucked away
    /// or the window is too narrow to dock it.
    pub(super) fn show_overview_button(&self, w: &Window, cx: &Context<Self>) -> Vec<AnyElement> {
        if self.overview_docked(w) {
            return vec![];
        }
        vec![
            ui::icon_button("show-overview", Glyph::PanelRight, "Show overview")
                .tooltip("Overview · ⌘\\")
                .on_click(cx.listener(|s, _, w, cx| {
                    if let Page::Topic(id, ..) = s.page {
                        s.toggle_overview(id, w)
                    }
                    cx.notify()
                }))
                .into_any_element(),
        ]
    }
    fn run_transcript(
        &self,
        state: &TopicState,
        t: &meep_topic::Task,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let session = AgentSession {
            id: t.id.to_string(),
            topic: Some(state.topic.id.to_string()),
            title: t.title.clone(),
            view_id: String::new(),
            // A task queued on the board has not started, even if a previous
            // provider status says "queued". Do not animate a thinking turn
            // until the person starts it.
            status: if t.queued && t.column == Column::Todo && !self.sending_runs.contains(&t.id) {
                "queued".into()
            } else if self.sending_runs.contains(&t.id)
                || t.column == Column::InProgress
                || matches!(
                    self.run_status.as_str(),
                    "in_progress" | "queued" | "started"
                )
            {
                "running".into()
            } else {
                self.run_status.clone()
            },
            messages: self.run_messages.clone(),
            error: None,
            agent_command: String::new(),
            provider_session_id: None,
            secure_launcher_version: None,
            model_id: t.model.clone(),
            effort: t.reasoning_effort.clone(),
            approvals: vec![],
        };
        let mut session = session;
        if let Some(turns) = self.pending_turns.get(&t.id) {
            for turn in turns {
                let index = turn.after_messages.min(session.messages.len());
                session.messages.insert(index, turn.message.clone());
            }
        }
        let reduced = cx.reduce_motion();
        self.activity.update(cx, |a, cx| {
            a.set_active(session.status == "running", reduced, cx)
        });
        if session.messages.is_empty() {
            // Before the run reports anything, the brief is the conversation's first turn;
            // work that is starting or running shows its title as the brief.
            let brief = t
                .instructions
                .clone()
                .filter(|b| !b.trim().is_empty())
                .unwrap_or_else(|| meep_topic::title_line(&t.title));
            session
                .messages
                .push(meep_protocol::sessions::AgentMessage {
                    role: "user".into(),
                    text: brief,
                    created_at: t.created_at.timestamp_millis(),
                    ..Default::default()
                });
            if t.column == Column::Done
                && let Some(result) = &t.result
            {
                session
                    .messages
                    .push(meep_protocol::sessions::AgentMessage {
                        role: "assistant".into(),
                        text: result.clone(),
                        created_at: t.updated_at.timestamp_millis(),
                        ..Default::default()
                    });
            }
            let note = match (t.column, self.run_notice.as_deref()) {
                (_, Some(n)) => n.to_owned(),
                (Column::Todo, _) if t.queued => {
                    "Queued. Start it, or send a note and it starts with that.".into()
                }
                // A running agent shows its working indicator under the brief instead.
                (Column::InProgress, _) => {
                    return self.chat_transcript(Some(&session), w, cx);
                }
                (Column::Todo, _) => "Starting the agent…".into(),
                _ => String::new(),
            };
            return ui::column()
                .gap(px(12.))
                .child(div().mx(px(-ui::PANEL_INSET)).child(self.chat_transcript(
                    Some(&session),
                    w,
                    cx,
                )))
                .when(!note.is_empty(), |c| {
                    c.child(
                        ui::row()
                            .gap(px(8.))
                            .child(
                                Icon::new(Glyph::Zap)
                                    .size(px(13.))
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                            )
                            .child(ui::caption(note)),
                    )
                });
        }
        // The transcript brings its own inset; the task's cards line up with its text.
        div()
            .mx(px(-ui::PANEL_INSET))
            .my(px(-16.))
            .child(self.chat_transcript(Some(&session), w, cx))
    }
    /// The task's composer: the model it runs on where the topic chat has its picker,
    /// and one action that follows the run. A queued task starts, a running one
    /// stops while the draft is empty, and otherwise a message goes to the agent.
    fn run_composer(
        &self,
        state: &TopicState,
        t: &meep_topic::Task,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let task = t.id;
        self.ensure_chat_models(id, w, cx);
        let queued = t.queued && t.column == Column::Todo;
        let input = &self.run_input;
        let empty = input.read(cx).value().trim().is_empty() && self.run_files.is_empty();
        let stop = t.column == Column::InProgress && empty && !queued;
        self.run_models.update(cx, |p, cx| {
            p.set_selection(
                self.run_model.as_deref().or(t.model.as_deref()),
                Default::default(),
                t.model.is_none(),
                cx,
            )
        });
        let action = if stop {
            meep_ui::composer::submit("stop-run", "Stop the agent")
                .icon(Glyph::Square)
                .tooltip("Stop the agent")
                .on_click(cx.listener(move |s, _, _, cx| {
                    s.issue(id, Command::CancelRun { task });
                    cx.notify()
                }))
        } else {
            meep_ui::composer::submit(
                "send-run-message",
                if queued {
                    "Start the agent"
                } else {
                    "Send message"
                },
            )
            .when(queued, |b| b.icon(Glyph::Play))
            .tooltip(if queued {
                "Start · ↵"
            } else {
                "Send · ↵"
            })
            .disabled(
                (empty && !queued) || self.sending_runs.contains(&task) || self.chat_uploading > 0,
            )
            .on_click(cx.listener(|s, _, w, cx| s.send_run_message(w, cx)))
        };
        ui::column()
            .flex_none()
            .px(px(self.chat_inset(w)))
            .pb(px(12.))
            .child(
                meep_shell::composer::surface(input.focus_handle(cx).contains_focused(w, cx))
                    .w_full()
                    .id("task-run-composer")
                    .on_drop(cx.listener(|s, paths: &ExternalPaths, w, cx| {
                        s.upload_chat_files(paths.paths().to_vec(), w, cx)
                    }))
                    .child(self.file_chips(&self.run_files, Attach::Run, cx))
                    .on_action(cx.listener(|s, a: &Enter, w, cx| {
                        if !a.shift {
                            s.send_run_message(w, cx)
                        }
                    }))
                    .child(
                        div()
                            .px(px(4.))
                            .pt(px(2.))
                            .child(meep_shell::composer::input(input, "Message the agent")),
                    )
                    .child(
                        ui::row()
                            .gap(px(6.))
                            .pl(px(4.))
                            .child(
                                ui::icon_button(
                                    "attach-run-files",
                                    Glyph::Paperclip,
                                    "Attach files",
                                )
                                .on_click(cx.listener(|s, _, w, cx| s.choose_chat_files(w, cx))),
                            )
                            .child(self.run_models.clone())
                            .child(div().flex_1())
                            .child(action),
                    ),
            )
    }
    pub(super) fn chat_view(
        &self,
        state: &TopicState,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        if let Some((_, task)) = self.chat_task()
            && let Some(t) = state.tasks.iter().find(|t| t.id == task)
        {
            return self.task_panel(state, t, w, cx);
        }
        let mut messages = vec![];
        let mut thread_rows = BTreeMap::new();
        for t in &state.threads {
            if !t.is_topic_chat() {
                continue;
            }
            thread_rows.insert(t.id, messages.len());
            for m in &t.messages {
                // Meep's own lines (setup, a to-do it picked up) are notes, not the person.
                if m.producer == meep_topic::Producer::System {
                    // Notes are written for the agent; their line here speaks to the person.
                    let worded = [
                        (
                            "The person approved; carry it out now, exactly as proposed: ",
                            "You approved: ",
                        ),
                        (
                            "Allowed by the person's rule; carry it out now, exactly as proposed: ",
                            "Allowed by your rule: ",
                        ),
                        ("Approved by the person and done: ", "Done: "),
                        ("The person declined: ", "You declined: "),
                    ]
                    .iter()
                    .find_map(|(note, said)| {
                        m.text
                            .strip_prefix(note)
                            .map(|rest| format!("{said}{rest}"))
                    });
                    let line = if m.text.starts_with("Set up this topic") {
                        "Setting up this topic from its mission".to_owned()
                    } else {
                        meep_topic::title_line(&worded.unwrap_or_else(|| m.text.clone()))
                    };
                    messages.push(AgentMessage {
                        role: "assistant".into(),
                        agent_name: String::new(),
                        text: format!("_{line}_"),
                        created_at: m.at.timestamp_millis(),
                        ..Default::default()
                    });
                    continue;
                }
                messages.push(AgentMessage {
                    role: if m.reply_target() == Some(Source::User) {
                        "user"
                    } else {
                        "assistant"
                    }
                    .into(),
                    // The pane header already names the topic; its own replies go unsigned.
                    agent_name: if m.reply_target() == Some(Source::Topic(id)) {
                        String::new()
                    } else {
                        m.author.clone()
                    },
                    text: m.text.clone(),
                    created_at: m.at.timestamp_millis(),
                    ..Default::default()
                })
            }
            let linked = t.outcomes.iter().find_map(|outcome| match outcome {
                Outcome::Task(id) => state.tasks.iter().find(|task| task.id == *id),
                _ => None,
            });
            if let Some(task) = linked
                && !t.outcomes.iter().any(|o| {
                    matches!(
                        o,
                        Outcome::Reply {
                            to: Source::User,
                            ..
                        }
                    )
                })
            {
                // The topic agent's turn: its reply lands on this message. Only a question
                // or a failure is worth a line of its own, on the message it answers.
                let status = if task.is_session() {
                    match task.column {
                        _ if task.from_thread != Some(t.id) => None,
                        Column::NeedsYou if let Some(question) = &task.input_question => {
                            Some(question.clone())
                        }
                        Column::NeedsYou if task.action.is_some() => None,
                        Column::NeedsYou => Some(format!(
                            "{} Send your message again to retry.",
                            task.result.as_deref().unwrap_or("Something went wrong.")
                        )),
                        _ => None,
                    }
                } else {
                    Some(t.summary.clone()).filter(|summary| !summary.trim().is_empty())
                };
                if let Some(status) = status {
                    messages.push(AgentMessage {
                        role: "assistant".into(),
                        agent_name: String::new(),
                        text: status,
                        created_at: task.updated_at.timestamp_millis(),
                        ..Default::default()
                    });
                }
            }
            for o in &t.outcomes {
                if let Outcome::Reply {
                    to: Source::User,
                    text,
                } = o
                {
                    messages.push(AgentMessage {
                        role: "assistant".into(),
                        agent_name: String::new(),
                        text: text.clone(),
                        created_at: t.updated_at.timestamp_millis(),
                        ..Default::default()
                    })
                }
            }
        }
        // A routine runs on its own and reports to the inbox; the chat keeps one line.
        for task in state
            .tasks
            .iter()
            .filter(|t| t.is_routine_run() && t.column == Column::Done)
        {
            let result = task
                .result
                .as_deref()
                .and_then(|r| r.lines().find(|l| !l.trim().is_empty()))
                .map(|l| format!(" · {}", l.trim()))
                .unwrap_or_default();
            messages.push(AgentMessage {
                role: "assistant".into(),
                agent_name: String::new(),
                text: format!("_{} ran{result}_", meep_topic::title_line(&task.title)),
                created_at: task.updated_at.timestamp_millis(),
                ..Default::default()
            });
        }
        // Routines that run inside their PostHog workflow leave a run record instead.
        for run in &state.routine_report_runs {
            let name = state
                .topic
                .routines
                .iter()
                .find(|r| r.binding.id == run.routine)
                .map_or(run.routine.as_str(), |r| r.binding.name.as_str());
            let found = match run.threads.len() {
                0 => "nothing new".to_owned(),
                1 => "1 report".to_owned(),
                n => format!("{n} reports"),
            };
            messages.push(AgentMessage {
                role: "assistant".into(),
                agent_name: String::new(),
                text: format!("_{name} ran · {found}_"),
                created_at: run.at.timestamp_millis(),
                ..Default::default()
            });
        }
        let mut order: Vec<_> = (0..messages.len()).collect();
        order.sort_by_key(|&index| messages[index].created_at);
        let mut sorted_rows = vec![0; messages.len()];
        for (sorted, original) in order.into_iter().enumerate() {
            sorted_rows[original] = sorted;
        }
        for index in thread_rows.values_mut() {
            *index = sorted_rows[*index];
        }
        messages.sort_by_key(|m| m.created_at);
        let linked = chat_linked_tasks(state, &thread_rows, messages.len());
        self.tick_running_chat_tasks(&linked, cx);
        let receipts = std::sync::Arc::new(chat_receipts(state, &messages));
        let answering = Self::chat_answer_in_progress(state).map(|t| t.id);
        let reduced = cx.reduce_motion();
        self.activity
            .update(cx, |a, cx| a.set_active(answering.is_some(), reduced, cx));
        self.ensure_chat_models(id, w, cx);
        let session = AgentSession {
            id: id.to_string(),
            topic: Some(id.to_string()),
            view_id: String::new(),
            title: state.topic.name.clone(),
            status: if answering.is_some() {
                "running"
            } else {
                "idle"
            }
            .into(),
            messages,
            error: None,
            agent_command: String::new(),
            provider_session_id: None,
            secure_launcher_version: None,
            model_id: None,
            effort: None,
            approvals: vec![],
        };
        let mut stream = scroll("chat-stream").gap(px(12.));
        let virtual_chat =
            !session.messages.is_empty() && !w.is_a11y_active() && !cx.has_active_drag();
        if !virtual_chat && !session.messages.is_empty() {
            for (index, message) in session.messages.iter().enumerate() {
                let key = format!("{}-{index}", session.id);
                stream = stream.child(self.transcript_row(
                    &session,
                    meep_shell::transcript::TranscriptRow {
                        message,
                        key: &key,
                        index,
                        active: index + 1 == session.messages.len() && session.status == "running",
                    },
                    w,
                    cx,
                ));
                if !linked[index].is_empty() {
                    stream = stream.child(self.chat_task_group(id, &linked[index], cx));
                }
            }
        } else if session.messages.is_empty() {
            const STARTERS: [(Glyph, &str); 3] = [
                (Glyph::ListChecks, "What should I do first?"),
                (Glyph::Map, "Plan the next steps toward the mission"),
                (Glyph::Clock, "Summarize what changed this week"),
            ];
            // Each row's own padding bleeds into the gutter so its glyph sits on the text edge.
            let mut starters = ui::column().gap(px(2.)).mx(px(-10.)).mt(px(4.));
            for (i, (glyph, text)) in STARTERS.into_iter().enumerate() {
                starters = starters.child(
                    starter(format!("chat-starter-{i}"), glyph, text)
                        .child(starter_chevron())
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.composer.update(cx, |e, cx| {
                                e.set_value(text, w, cx);
                                e.focus(w, cx)
                            });
                        })),
                );
            }
            // With no messages yet, the inbox's empty state already offers this.
            if !state.threads.is_empty() {
                starters = starters.child(
                    starter("chat-choose", Glyph::Plug, "Add a source")
                        .child(starter_chevron())
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.ask_in_chat("Find and add this PostHog object: ", w, cx)
                        })),
                );
            }
            stream = stream
                .child(
                    ui::column()
                        .gap(px(4.))
                        .pt(px(8.))
                        .child(super::topic_icon::bob(
                            "topic-chat-hello",
                            super::topic_icon::tile(&state.topic.display_icon(), 56.).mb(px(10.)),
                            cx.reduce_motion(),
                        ))
                        .child(
                            div()
                                .text_size(px(15.))
                                .font_weight(FontWeight::SEMIBOLD)
                                .child(format!("Work with @{}", state.topic.name)),
                        )
                        .child(ui::caption("Ask a question or hand it something to do. It works on it and reports back here.")),
                )
                .child(starters)
        }
        let stream = if virtual_chat {
            self.virtual_topic_chat(state, session, linked, receipts, w, cx)
                .into_any_element()
        } else {
            stream.into_any_element()
        };
        let inset = self.chat_inset(w);
        let mut pane = ui::column()
            .size_full()
            .min_h_0()
            .gap(px(10.))
            .px(px(inset))
            .pb(px(12.))
            .child(
                crumb_bar(
                    topic_crumbs(
                        id,
                        &state.topic.name,
                        Some(&state.topic.display_icon()),
                        Tab::Chat,
                        None,
                        cx,
                    ),
                    None,
                    self.show_overview_button(w, cx),
                )
                .mx(px(-inset)),
            )
            .child(stream);
        let text = self.composer.read(cx).value().to_string();
        if let Some((before, term)) = text.rsplit_once('@')
            && !term.ends_with(' ')
        {
            for other in self
                .states
                .iter()
                .filter(|t| {
                    t.topic.id != id
                        && t.topic
                            .name
                            .to_lowercase()
                            .starts_with(&term.to_lowercase())
                })
                .take(8)
            {
                let mention = format!("{before}@{} ", other.topic.name);
                pane = pane.child(control(
                    format!("mention-{}", other.topic.id),
                    format!("@{}", other.topic.name),
                    false,
                    cx,
                    move |s, w, cx| {
                        s.composer.update(cx, |e, cx| {
                            e.set_value(mention.clone(), w, cx);
                            e.focus(w, cx)
                        })
                    },
                ))
            }
        }
        pane.children(self.briefing(state, w, cx))
            .children(self.session_prompt(state, cx))
            .children(self.session_bar(state))
            .child(self.topic_composer(state, answering, w, cx))
    }
    /// What needs the person, waiting in the conversation when they arrive.
    fn briefing(&self, state: &TopicState, w: &Window, cx: &Context<Self>) -> Option<Div> {
        let id = state.topic.id;
        if self.briefing_dismissed.contains(&id) || self.overview_docked(w) {
            return None;
        }
        let groups: Vec<_> = super::pages::attention_groups(&self.needs, state)
            .into_iter()
            .filter(|g| !matches!(g.latest.page, Page::Topic(_, Tab::Chat, None)))
            .collect();
        if groups.is_empty() {
            return None;
        }
        Some(
            ui::row()
                .flex_none()
                .h(px(40.))
                .pl(px(14.))
                .pr(px(6.))
                .gap(px(10.))
                .rounded(px(10.))
                .border_1()
                .border_color(ui::ink(0x12))
                .child(
                    Icon::new(Glyph::Bell)
                        .size(px(14.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                )
                .child(
                    div()
                        .flex_none()
                        .text_size(px(13.))
                        .font_weight(FontWeight::MEDIUM)
                        .child("Needs you"),
                )
                .child(
                    div()
                        .flex_1()
                        .min_w_0()
                        .truncate()
                        .text_size(px(13.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .child(super::pages::attention_tally(&groups)),
                )
                .child(
                    control("briefing-review", "Review", false, cx, move |s, w, cx| {
                        s.go(Page::Topic(id, Tab::Needs, None), w, cx)
                    })
                    .self_center(),
                )
                .child(
                    ui::icon_button("dismiss-briefing", Glyph::X, "Not now")
                        .size(px(24.))
                        .on_click(cx.listener(move |s, _, _, cx| {
                            s.briefing_dismissed.insert(id);
                            cx.notify()
                        })),
                ),
        )
    }
    fn virtual_topic_chat(
        &self,
        state: &TopicState,
        session: AgentSession,
        linked: Vec<Vec<ChatTask>>,
        receipts: std::sync::Arc<Vec<Vec<Receipt>>>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let topic = state.topic.id;
        let selecting = gpui_kit::base::TextSelection::has_selection(w, cx);
        let count = if selecting { 1 } else { session.messages.len() };
        let running = session.status == "running";
        let (list_state, selection_rows, anchor) = {
            let mut cached = self.chat_list.borrow_mut();
            let cache = cached.get_or_insert_with(|| super::desktop::TopicChatList {
                topic,
                // A conversation opens at its latest message and follows new ones
                // while the person reads at the bottom.
                list: {
                    let list = ListState::new(count, ListAlignment::Top, px(300.))
                        .with_uniform_item_height(px(80.));
                    list.set_follow_mode(FollowMode::Tail);
                    list
                },
                messages: session.messages.clone(),
                linked: linked.clone(),
                running,
                full_selection: selecting,
                selection_rows: Vec::new(),
            });
            let mut anchor = None;
            if cache.topic != topic {
                cache.topic = topic;
                cache.list.reset_with_uniform_height(count, px(80.));
                cache.list.set_follow_mode(FollowMode::Tail);
            } else if cache.full_selection != selecting {
                // Keep the same list and text element IDs while a selection is
                // active, so off-screen selected text remains copyable.
                let offset = cache.list.scroll_px_offset_for_scrollbar();
                let height = cache.list.max_offset_for_scrollbar().y
                    + cache.list.viewport_bounds().size.height;
                let viewport = cache.list.viewport_bounds();
                let old_top = cache.list.logical_scroll_top().item_ix;
                let old_anchor = if selecting {
                    let index = old_top.min(session.messages.len() - 1);
                    cache
                        .list
                        .bounds_for_item(index)
                        .map(|bounds| (index, bounds.top()))
                } else {
                    cache
                        .selection_rows
                        .iter()
                        .enumerate()
                        .find_map(|(index, row)| {
                            let bounds = row.get();
                            (bounds.bottom() > viewport.top() && bounds.top() < viewport.bottom())
                                .then_some((index, bounds.top()))
                        })
                };
                cache.list.reset_with_uniform_height(
                    count,
                    if selecting {
                        height.max(px(80.))
                    } else {
                        px(80.)
                    },
                );
                if selecting {
                    cache.list.set_offset_from_scrollbar(offset);
                    anchor = old_anchor;
                } else if let Some((index, top)) = old_anchor {
                    cache.list.scroll_to(ListOffset {
                        item_ix: index,
                        offset_in_item: (viewport.top() - top).max(px(0.)),
                    });
                } else {
                    cache.list.set_offset_from_scrollbar(offset);
                }
            } else if selecting {
                if cache.messages != session.messages
                    || cache.linked != linked
                    || cache.running != running
                {
                    cache.list.remeasure_items(0..1);
                }
            } else {
                let prefix = cache
                    .messages
                    .iter()
                    .zip(&session.messages)
                    .take_while(|(a, b)| a == b)
                    .count();
                if prefix != cache.messages.len()
                    || prefix != session.messages.len()
                    || cache.linked != linked
                {
                    let changed = if cache.linked != linked { 0 } else { prefix };
                    cache
                        .list
                        .splice(changed..cache.list.item_count(), count - changed);
                } else if cache.running != running && !session.messages.is_empty() {
                    let last = session.messages.len() - 1;
                    cache.list.remeasure_items(last..last + 1);
                }
            }
            cache.messages = session.messages.clone();
            cache.linked = linked.clone();
            cache.running = running;
            cache.full_selection = selecting;
            if selecting {
                cache
                    .selection_rows
                    .resize_with(session.messages.len(), || {
                        std::rc::Rc::new(std::cell::Cell::new(Bounds::default()))
                    });
            } else {
                cache.selection_rows.clear();
            }
            (cache.list.clone(), cache.selection_rows.clone(), anchor)
        };
        if let Some((index, top)) = anchor
            && let Some(row) = selection_rows.get(index).cloned()
        {
            let list = list_state.clone();
            let scheduled_offset = list.scroll_px_offset_for_scrollbar();
            let owner = cx.weak_entity();
            w.on_next_frame(move |w, cx| {
                let still_selecting = owner
                    .read_with(cx, |s, _| {
                        s.on_chat()
                            && s.topic_id() == Some(topic)
                            && s.chat_task().is_none()
                            && s.chat_list
                                .borrow()
                                .as_ref()
                                .is_some_and(|cache| cache.topic == topic && cache.full_selection)
                    })
                    .unwrap_or(false);
                if !still_selecting {
                    return;
                }
                if list.scroll_px_offset_for_scrollbar() != scheduled_offset {
                    return;
                }
                let adjustment = row.get().top() - top;
                if adjustment.abs() > px(0.5) {
                    list.scroll_by(adjustment);
                    w.refresh();
                }
            });
        }
        let owner = cx.weak_entity();
        let session = std::sync::Arc::new(session);
        ui::column().flex_1().min_h_0().w_full().child(
            list(list_state, move |index, w, cx| {
                owner
                    .update(cx, |s, cx| {
                        if selecting {
                            let mut transcript =
                                ui::column().min_w_0().gap(px(16.)).px(px(16.)).py(px(16.));
                            for (index, message) in session.messages.iter().enumerate() {
                                let key = format!("{}-{index}", session.id);
                                let bounds = selection_rows[index].clone();
                                transcript = transcript.child(
                                    s.transcript_row(
                                        &session,
                                        meep_shell::transcript::TranscriptRow {
                                            message,
                                            key: &key,
                                            index,
                                            active: index + 1 == session.messages.len()
                                                && session.status == "running",
                                        },
                                        w,
                                        cx,
                                    )
                                    .relative()
                                    .child(
                                        canvas(move |area, _, _| bounds.set(area), |_, _, _, _| {})
                                            .absolute()
                                            .inset_0(),
                                    ),
                                );
                                if !linked[index].is_empty() {
                                    transcript = transcript.child(s.chat_task_group(
                                        topic,
                                        &linked[index],
                                        cx,
                                    ));
                                }
                            }
                            let content = ui::column()
                                .w_full()
                                .child(div().mx(px(-16.)).child(transcript));
                            content.into_any_element()
                        } else if let Some(message) = session.messages.get(index) {
                            let key = format!("{}-{index}", session.id);
                            ui::column()
                                .w_full()
                                .pt(px(if index == 0 { 16. } else { 0. }))
                                .pb(px(16.))
                                .child(s.transcript_row(
                                    &session,
                                    meep_shell::transcript::TranscriptRow {
                                        message,
                                        key: &key,
                                        index,
                                        active: index + 1 == session.messages.len()
                                            && session.status == "running",
                                    },
                                    w,
                                    cx,
                                ))
                                .children(
                                    receipts
                                        .get(index)
                                        .filter(|r| !r.is_empty())
                                        .map(|r| receipt_rows(index, r, cx)),
                                )
                                .when(!linked[index].is_empty(), |el| {
                                    el.child(
                                        s.chat_task_group(topic, &linked[index], cx).mt(px(10.)),
                                    )
                                })
                                .into_any_element()
                        } else {
                            div().into_any_element()
                        }
                    })
                    .unwrap_or_else(|_| div().into_any_element())
            })
            .w_full()
            .h_full(),
        )
    }
    pub(super) fn topic_composer(
        &self,
        state: &TopicState,
        answering: Option<TaskId>,
        w: &Window,
        cx: &Context<Self>,
    ) -> impl IntoElement {
        let id = state.topic.id;
        let reference = self.chat_reference.as_ref();
        let mut chips = meep_ui::composer::attachment_row();
        if let Some(path) = reference {
            let mime = mime_guess::from_path(path)
                .first_or_octet_stream()
                .to_string();
            chips = chips.child(
                meep_ui::composer::attachment_chip(path, &mime).child(
                    ui::icon_button("remove-chat-reference", Glyph::X, "Remove reference")
                        .size(px(22.))
                        .on_click(cx.listener(|s, _, _, cx| {
                            s.chat_reference = None;
                            cx.notify()
                        })),
                ),
            );
        }
        let subject = (!self.on_chat()).then(|| self.page_subject()).flatten();
        if let Some((glyph, label, _)) = &subject {
            chips = chips.child(
                ui::row()
                    .flex_none()
                    .max_w(px(320.))
                    .gap(px(6.))
                    .px(px(8.))
                    .h(px(26.))
                    .rounded(px(7.))
                    .border_1()
                    .border_color(ui::ink(0x12))
                    .bg(ui::ink(0x05))
                    .text_size(px(12.))
                    .child(ui::nav::glyph(*glyph, false))
                    .child(div().min_w_0().truncate().child(label.clone())),
            );
        }
        chips = chips.child(self.file_chips(&self.chat_files, Attach::Chat, cx));
        let has_chips = reference.is_some()
            || subject.is_some()
            || !self.chat_files.is_empty()
            || self.chat_uploading > 0;
        let input = &self.composer;
        let text = input.read(cx).value();
        let can_send =
            self.chat_uploading == 0 && (!text.trim().is_empty() || !self.chat_files.is_empty());
        let actions = ui::row()
            .gap(px(2.))
            .child(
                ui::icon_button("attach-chat-files", Glyph::Paperclip, "Attach files")
                    .tooltip("Attach files · saved to this topic’s Files")
                    .on_click(cx.listener(|s, _, w, cx| s.choose_chat_files(w, cx))),
            )
            .child(
                div()
                    .min_w_0()
                    .flex_shrink(1.)
                    .child(self.chat_models.clone()),
            )
            .child(div().flex_1())
            .when_some(answering, |row, task| {
                row.child(
                    ui::icon_button("stop-chat-answer", Glyph::Square, "Stop answering")
                        .tooltip("Stop answering · closes the answer task")
                        .on_click(cx.listener(move |s, _, _, cx| {
                            s.issue(
                                id,
                                Command::MoveTask {
                                    task,
                                    column: Column::Done,
                                },
                            );
                            cx.notify()
                        })),
                )
            })
            .child(
                meep_ui::composer::submit("send-chat-message", "Send message")
                    .tooltip("Send · ↵   After current work · ⌘↵")
                    .disabled(!can_send)
                    .on_click(cx.listener(move |s, _, w, cx| s.send_chat(w, cx))),
            );
        meep_ui::composer::surface(input.focus_handle(cx).contains_focused(w, cx))
            .id("chat-composer")
            // ↵ reaches the agent now; ⌘↵ waits for its current work.
            .on_action(cx.listener(move |s, action: &Enter, w, cx| {
                if !action.shift {
                    s.send_chat_as(action.secondary, w, cx);
                }
            }))
            // Files dropped on the composer upload into the topic and attach.
            .drag_over::<ExternalPaths>(|style, _, _, _| style.border_color(ui::ink(0x48)))
            .on_drop(cx.listener(|s, paths: &ExternalPaths, w, cx| {
                s.upload_chat_files(paths.paths().to_vec(), w, cx)
            }))
            .when(has_chips, |el| el.child(chips))
            .child(
                div()
                    .px(px(4.))
                    .pt(px(2.))
                    .child(meep_ui::composer::input(input, "Message the topic")),
            )
            .child(actions)
    }
}

/// A starter row's trailing affordance, so a resting row still reads as clickable.
fn starter_chevron() -> Div {
    div()
        .ml_auto()
        .flex_none()
        .child(ui::nav::glyph(Glyph::ChevronRight, false))
}

/// Group a topic's model catalogue by the runtime that runs each model, in catalogue order.
pub(super) fn model_groups(
    models: &[meep_wire::ChatModel],
) -> Vec<meep_shell::model_picker::AgentModels> {
    use meep_shell::model_picker::{AgentModels, Model};
    let mut groups: Vec<AgentModels> = vec![];
    for m in models {
        let runtime = m.runtime.clone().unwrap_or_else(|| "posthog".into());
        let index = match groups.iter().position(|g| g.id == runtime) {
            Some(i) => i,
            None => {
                let mut chars = runtime.chars();
                let name = chars
                    .next()
                    .map(|c| c.to_uppercase().chain(chars).collect())
                    .unwrap_or_default();
                groups.push(AgentModels {
                    mark: meep_ui::agent_marks::named(&runtime),
                    id: runtime,
                    name,
                    models: vec![],
                });
                groups.len() - 1
            }
        };
        groups[index].models.push(Model {
            id: m.id.clone(),
            name: m.name.clone(),
            note: (!m.meep_tools).then(|| "No Meep tools".into()),
        });
    }
    groups
}

/// A free topic path for an upload: `uploads/<name>`, numbered when the name is taken.
fn upload_path(taken: &HashSet<String>, name: &str) -> String {
    let first = format!("uploads/{name}");
    if !taken.contains(&first) {
        return first;
    }
    let file = std::path::Path::new(name);
    let stem = file.file_stem().and_then(|s| s.to_str()).unwrap_or(name);
    let extension = file.extension().and_then(|e| e.to_str());
    (2..)
        .map(|n| match extension {
            Some(ext) => format!("uploads/{stem} {n}.{ext}"),
            None => format!("uploads/{stem} {n}"),
        })
        .find(|path| !taken.contains(path))
        .unwrap_or(first)
}

impl Desktop {
    /// Load the topic's model catalogue the first time its chat shows.
    pub(super) fn ensure_chat_models(&self, topic: TopicId, w: &Window, cx: &mut Context<Self>) {
        // The catalogue is the account's; keep showing it while this topic's choice loads,
        // so the picker never flashes a raw model ID.
        if self.chat_models_topic.replace(Some(topic)) != Some(topic) {
            self.chat_models
                .update(cx, |p, cx| p.set_recovery(None, cx));
            self.task_models
                .update(cx, |p, cx| p.set_recovery(None, cx));
            self.load_chat_models(topic, w, cx);
        } else if self
            .chat_models_failed
            .get()
            .is_some_and(|at| at.elapsed() >= std::time::Duration::from_secs(5))
        {
            self.chat_models_failed.set(None);
            self.load_chat_models(topic, w, cx);
        }
    }
    pub(super) fn chosen_task_model(&self) -> Option<&meep_wire::ChatModel> {
        self.catalogue.models.iter().find(|m| {
            Some(&m.id)
                == self
                    .task_model
                    .as_ref()
                    .or(self.catalogue.selected.as_ref())
                    .or(self.catalogue.default_model.as_ref().map(|m| &m.id))
        })
    }
    pub(super) fn sync_task_selection(&self, cx: &mut Context<Self>) {
        let effort = meep_shell::model_picker::Effort {
            levels: self
                .chosen_task_model()
                .into_iter()
                .flat_map(|m| &m.supported_efforts)
                .map(|e| (e.clone(), e.clone()))
                .collect(),
            current: self.task_effort.clone(),
            can_reset: true,
            ..Default::default()
        };
        self.task_models.update(cx, |p, cx| {
            p.set_selection(self.task_model.as_deref(), effort, true, cx)
        });
    }
    pub(super) fn load_chat_models(&self, topic: TopicId, w: &Window, cx: &mut Context<Self>) {
        let c = self.client().clone();
        self.job(
            async move { c.chat_models(topic).await },
            w,
            cx,
            move |s, r, _, cx| {
                if s.chat_models_topic.get() == Some(topic) {
                    s.show_chat_models(r, cx)
                }
            },
        );
    }
    pub(super) fn connect_model_topic(&self, topic: TopicId, w: &Window, cx: &mut Context<Self>) {
        let c = self.client().clone();
        self.job(
            async move {
                c.grant_topic("posthog", topic).await?;
                c.chat_models(topic).await
            },
            w,
            cx,
            move |s, r, _, cx| {
                if s.chat_models_topic.get() == Some(topic) {
                    s.show_chat_models(r, cx);
                }
            },
        );
    }
    pub(super) fn show_chat_models(
        &mut self,
        r: Result<meep_wire::ChatModels>,
        cx: &mut Context<Self>,
    ) {
        self.chat_models_failed
            .set(r.is_err().then(std::time::Instant::now));
        match r {
            Ok(mut catalogue) => {
                if let Some(default) = &catalogue.default_model
                    && !catalogue
                        .models
                        .iter()
                        .any(|m| m.id == default.id && m.runtime == default.runtime)
                {
                    catalogue.models.push(default.clone());
                }
                for (picker, compact) in [
                    (&self.chat_models, true),
                    (&self.run_models, true),
                    (&self.task_models, false),
                ] {
                    picker.update(cx, |p, cx| {
                        p.set_catalog(model_groups(&catalogue.models), cx);
                        p.set_trigger(catalogue.models.is_empty(), compact, cx);
                    });
                }
                self.chat_models.update(cx, |p, cx| {
                    p.set_default_model(
                        catalogue.default_model.as_ref().map(|m| m.id.as_str()),
                        catalogue
                            .default_model
                            .as_ref()
                            .and_then(|m| m.runtime.as_deref()),
                        cx,
                    );
                    p.set_selection(catalogue.selected.as_deref(), Default::default(), true, cx)
                });
                self.catalogue = catalogue;
            }
            Err(e) => {
                let (message, recovery) = match e.downcast_ref::<meep_client::TransportError>() {
                    Some(meep_client::TransportError::Api { code, message, .. }) => (
                        message.clone(),
                        (code == "missing_topic_grant")
                            .then(|| "Connect this topic to PostHog".to_owned()),
                    ),
                    Some(meep_client::TransportError::Unavailable(_)) => {
                        ("Couldn’t load models. Try refreshing.".to_owned(), None)
                    }
                    _ => (format!("{e:#}"), None),
                };
                self.catalogue = Default::default();
                for (picker, compact) in [
                    (&self.chat_models, true),
                    (&self.run_models, true),
                    (&self.task_models, false),
                ] {
                    picker.update(cx, |p, cx| {
                        p.set_catalog_error(message.clone(), cx);
                        p.set_recovery(recovery.clone(), cx);
                        p.set_trigger(false, compact, cx);
                    });
                }
            }
        }
        self.sync_task_selection(cx);
    }
    /// The composer's model choice goes to the server, which runs chat answers on it.
    pub(super) fn chat_model_changed(
        &mut self,
        change: &meep_shell::model_picker::Change,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        use meep_shell::model_picker::Change;
        let Some(topic) = self.chat_models_topic.get() else {
            return;
        };
        match change {
            Change::Model(model) => {
                let model = model.clone();
                let c = self.client().clone();
                self.chat_models
                    .update(cx, |p, cx| p.set_trigger(true, true, cx));
                self.job(
                    async move { c.set_chat_model(topic, model.as_deref()).await },
                    w,
                    cx,
                    move |s, r, _, cx| {
                        if s.chat_models_topic.get() != Some(topic) {
                            return;
                        }
                        match r {
                            Ok(catalogue) => s.show_chat_models(Ok(catalogue), cx),
                            Err(e) => {
                                s.chat_models
                                    .update(cx, |p, cx| p.set_trigger(false, true, cx));
                                s.fail(e)
                            }
                        }
                    },
                );
            }
            Change::Recover => self.connect_model_topic(topic, w, cx),
            Change::Refresh => self.load_chat_models(topic, w, cx),
            Change::Effort(_) => {}
        }
    }
    pub(super) fn file_chips(&self, files: &[String], to: Attach, cx: &Context<Self>) -> Div {
        let mut chips = meep_ui::composer::attachment_row();
        for (i, path) in files.iter().enumerate() {
            let mime = mime_guess::from_path(path).first_or_octet_stream();
            let name = path.strip_prefix("uploads/").unwrap_or(path);
            let remove = path.clone();
            chips = chips.child(
                meep_ui::composer::attachment_chip(name, mime.essence_str()).child(
                    ui::icon_button(
                        SharedString::from(format!("remove-chat-file-{i}")),
                        Glyph::X,
                        format!("Remove {name}"),
                    )
                    .size(px(22.))
                    .on_click(cx.listener(move |s, _, _, cx| {
                        // The upload stays in the topic's Files; only the draft lets go.
                        match to {
                            Attach::Run => &mut s.run_files,
                            Attach::Chat => &mut s.chat_files,
                            Attach::Task => &mut s.task_files,
                            Attach::View => &mut s.views.files,
                        }
                        .retain(|p| *p != remove);
                        cx.notify()
                    })),
                ),
            );
        }
        let uploading = if matches!(to, Attach::View) {
            self.views.uploading
        } else {
            self.chat_uploading
        };
        if uploading > 0 {
            chips = chips.child(
                ui::row()
                    .h(px(26.))
                    .gap(px(6.))
                    .px(px(6.))
                    .child(self.activity_indicator().clone())
                    .child(ui::caption(if uploading == 1 {
                        "Uploading 1 file…".to_owned()
                    } else {
                        format!("Uploading {uploading} files…")
                    })),
            );
        }
        chips
    }
    /// Choose files to upload into the topic and attach to the next message.
    pub(super) fn choose_chat_files(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let target = (self.topic_id(), self.chat_task());
        let chosen = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: true,
            prompt: Some("Attach".into()),
        });
        self.job(
            async move { chosen.await? },
            w,
            cx,
            move |s, result, w, cx| match result {
                Ok(_) if (s.topic_id(), s.chat_task()) != target => {}
                Ok(Some(paths)) => s.upload_chat_files(paths, w, cx),
                Ok(None) => {}
                Err(error) => s.fail(error.context("Meep couldn’t open the file chooser.")),
            },
        );
    }
    /// Save each file into the topic's Files under `uploads/` and attach it to the draft.
    /// A file the server refuses keeps a local copy behind the Save a copy/Discard notice.
    pub(super) fn upload_chat_files(
        &mut self,
        paths: Vec<std::path::PathBuf>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(topic) = self.topic_id() else {
            return;
        };
        let run = self.chat_task();
        // The task being created takes the files while its form is open.
        let into_task = self.adding;
        let mut taken: HashSet<String> = self
            .client()
            .cached_files(topic)
            .unwrap_or_default()
            .into_iter()
            .chain(self.chat_files.iter().cloned())
            .chain(self.task_files.iter().cloned())
            .collect();
        for source in paths {
            let Some(name) = source.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            let dest = upload_path(&taken, name);
            taken.insert(dest.clone());
            self.chat_uploading += 1;
            let c = self.client().clone();
            let target = dest.clone();
            self.job(
                async move {
                    let bytes = tokio::task::spawn_blocking(move || std::fs::read(&source))
                        .await?
                        .map_err(|e| anyhow::anyhow!("Could not read the file to attach: {e}"))?;
                    c.put_file(topic, &target, bytes).await
                },
                w,
                cx,
                move |s, r, _, _| {
                    s.chat_uploading = s.chat_uploading.saturating_sub(1);
                    match r {
                        Ok(_) if into_task && s.adding && s.topic_id() == Some(topic) => {
                            s.task_files.push(dest)
                        }
                        Ok(_) if s.topic_id() == Some(topic) && s.chat_task() == run => {
                            if run.is_some() {
                                s.run_files.push(dest)
                            } else {
                                s.chat_files.push(dest)
                            }
                        }
                        Ok(_) => {}
                        Err(e) => {
                            let kept = s.client().rejections().is_ok_and(|r| {
                                r.iter().any(|(id, _)| {
                                    s.client()
                                        .rejected_file_path(*id)
                                        .is_ok_and(|p| p.as_deref() == Some(dest.as_str()))
                                })
                            });
                            // A refused upload already has its notice with a saved copy.
                            if !kept {
                                s.fail(e)
                            }
                        }
                    }
                },
            );
        }
        cx.notify()
    }
    /// The chat answer the topic is still working on, if any.
    pub(super) fn chat_answer_in_progress(state: &TopicState) -> Option<&meep_topic::Task> {
        state
            .threads
            .iter()
            .filter(|t| t.is_topic_chat())
            .flat_map(|t| &t.outcomes)
            .filter_map(|o| match o {
                Outcome::Task(id) => state.tasks.iter().find(|task| task.id == *id),
                _ => None,
            })
            .rfind(|task| {
                task.assignment == Some(InboxAssignment::ChatAnswer)
                    && matches!(task.column, Column::Todo | Column::InProgress)
            })
    }
    /// Text for one file attached to a chat message: its revision and a readable excerpt.
    pub(super) fn chat_file_excerpt(&self, topic: TopicId, path: &str) -> Option<String> {
        let file = self.client().cached_file(topic, path).ok().flatten()?;
        let excerpt = std::str::from_utf8(&file.bytes)
            .map(|s| s.chars().take(4000).collect::<String>())
            .unwrap_or_else(|_| format!("Binary file, {} bytes.", file.bytes.len()));
        Some(format!(
            "File · {path} ({})\n\n{excerpt}",
            if file.revision == 0 {
                "pending upload".into()
            } else {
                format!("revision {}", file.revision)
            }
        ))
    }
}
impl TranscriptHost for Desktop {
    fn expanded(&self) -> &HashSet<String> {
        &self.expanded
    }
    fn expanded_mut(&mut self) -> &mut HashSet<String> {
        &mut self.expanded
    }
    /// Topic chat leaves `agent_command` empty so its own replies carry no name.
    fn harness_name(command: &str) -> &str {
        if command.is_empty() { "" } else { "Agent" }
    }
    fn activity_indicator(&self) -> &Entity<ActivityIndicator> {
        &self.activity
    }
    fn approval_card(
        &self,
        _: &AgentSession,
        _: &AgentApproval,
        _: &mut Window,
        _: &mut Context<Self>,
    ) -> Div {
        div()
    }
}
impl ChatHost for Desktop {
    fn chat_input(&self) -> &Entity<TextareaState> {
        if matches!(self.page, Page::View(_) | Page::NewView) {
            &self.views.prompt
        } else {
            &self.composer
        }
    }
    fn send_chat(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        self.send_chat_as(false, w, cx)
    }
}

/// A quiet line under an agent reply naming something it set up.
#[derive(Clone)]
pub(super) struct Receipt {
    glyph: Glyph,
    text: String,
    page: Option<Page>,
}

/// What the agent changed while answering each message: its activity between
/// the person's message and their next one, under the last reply in between.
fn chat_receipts(state: &TopicState, messages: &[AgentMessage]) -> Vec<Vec<Receipt>> {
    let id = state.topic.id;
    let mut out = vec![vec![]; messages.len()];
    let mut start = i64::MIN;
    let mut i = 0;
    while i < messages.len() {
        if messages[i].role == "user" {
            start = messages[i].created_at;
            i += 1;
            continue;
        }
        // The last reply before the next message from the person.
        let mut last = i;
        while last + 1 < messages.len() && messages[last + 1].role != "user" {
            last += 1;
        }
        let end = messages.get(last + 1).map_or(i64::MAX, |m| m.created_at);
        out[last] = state
            .activity
            .iter()
            .filter(|a| matches!(a.actor, Actor::Agent))
            .filter(|a| {
                let at = a.at.timestamp_millis();
                at >= start && at < end
            })
            .filter_map(|a| receipt(id, state, a))
            .collect();
        i = last + 1;
    }
    out
}

fn receipt(id: TopicId, state: &TopicState, a: &meep_topic::Activity) -> Option<Receipt> {
    let lower = a.text.to_lowercase();
    let (glyph, page) = match &a.subject {
        Ref::Task(t) => {
            // The conversation's own run and any run's progress are not changes it made.
            if state.tasks.iter().any(|x| x.id == *t && x.is_session())
                || chat_groups_task(state, *t)
                || a.text.starts_with("Started work")
                || a.text.starts_with("Updated progress")
            {
                return None;
            }
            (
                Glyph::SquareCheck,
                Some(Page::Topic(id, Tab::Tasks, Some(Detail::Task(*t)))),
            )
        }
        Ref::Fact(f) => (
            Glyph::Pencil,
            Some(Page::Topic(id, Tab::Facts, Some(Detail::Fact(*f)))),
        ),
        Ref::Rule(_) => (Glyph::ShieldCheck, Some(Page::Topic(id, Tab::Rules, None))),
        Ref::Routine(key) => (
            Glyph::Repeat,
            Some(Page::Topic(
                id,
                Tab::Routines,
                Some(Detail::Routine(key.clone())),
            )),
        ),
        Ref::Thread(t) => {
            let thread = state.threads.iter().find(|x| x.id == *t)?;
            // The conversation itself is not a receipt, nor is a report the person
            // archived; a filed report is.
            if thread.is_topic_chat() || state.archived_threads.contains(t) {
                return None;
            }
            (
                Glyph::Inbox,
                Some(Page::Topic(id, Tab::Inbox, Some(Detail::Thread(*t)))),
            )
        }
        Ref::Topic if lower.contains("mission") => {
            (Glyph::Flag, Some(Page::Topic(id, Tab::Mission, None)))
        }
        Ref::Topic if lower.contains("goal") || lower.contains("progress") => {
            (Glyph::Target, Some(Page::Topic(id, Tab::Goals, None)))
        }
        Ref::Topic if lower.contains("source") || lower.contains("link") => {
            (Glyph::Link, Some(Page::Topic(id, Tab::Linked, None)))
        }
        Ref::Topic => (Glyph::Check, None),
    };
    Some(Receipt {
        glyph,
        text: a.text.trim_end_matches('.').to_owned(),
        page,
    })
}

/// Receipts under a reply: at most four, then a count.
fn receipt_rows(index: usize, receipts: &[Receipt], cx: &Context<Desktop>) -> Div {
    let mut col = ui::column().gap(px(3.)).pt(px(8.));
    for (i, r) in receipts.iter().take(4).enumerate() {
        let page = r.page.clone();
        let linked = page.is_some();
        col = col.child(
            ui::row()
                .id(SharedString::from(format!("receipt-{index}-{i}")))
                .gap(px(7.))
                .min_w_0()
                .text_size(px(12.5))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .child(
                    meep_ui::gpui_kit::component::Icon::new(r.glyph)
                        .size(px(13.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                )
                .child(div().min_w_0().truncate().child(r.text.clone()))
                .when(linked, |row| {
                    row.cursor_pointer()
                        .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                })
                .when_some(page, |row, page| {
                    row.on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx)))
                }),
        );
    }
    if receipts.len() > 4 {
        col = col.child(ui::caption(format!("and {} more", receipts.len() - 4)));
    }
    col
}

/// Which draft an uploaded file is attached to.
#[derive(Clone, Copy)]
pub(super) enum Attach {
    /// The topic chat's next message.
    Chat,
    /// The open task conversation's next message.
    Run,
    /// The task being created.
    Task,
    /// The view request being written.
    View,
}

impl Desktop {
    /// Send the composer's message. `queue` waits for the agent's current work.
    pub(super) fn send_chat_as(&mut self, queue: bool, w: &mut Window, cx: &mut Context<Self>) {
        if matches!(self.page, Page::View(_) | Page::NewView) {
            self.send_view(w, cx);
            return;
        }
        let text = self.composer.read(cx).value().trim().to_owned();
        if self.chat_uploading > 0 || (text.is_empty() && self.chat_files.is_empty()) {
            return;
        }
        let Some(id) = self.topic_id() else {
            return;
        };
        let mut parts = vec![];
        for path in self.chat_reference.iter().chain(&self.chat_files) {
            match self.chat_file_excerpt(id, path) {
                Some(excerpt) => parts.push(excerpt),
                None => {
                    self.error = Some(format!("{path} is not available in this replica yet."));
                    cx.notify();
                    return;
                }
            }
        }
        // The person's words come first: they name the chat thread and any task it
        // makes; the attached context follows.
        // Written from a page, the message carries what that page is about.
        let from_page = !self.on_chat();
        if from_page {
            if let Page::Topic(_, _, Some(Detail::File(path))) = &self.page {
                if let Some(excerpt) = self.chat_file_excerpt(id, path) {
                    parts.insert(0, excerpt);
                }
            } else if let Some((_, _, about)) = self.page_subject() {
                parts.insert(0, about);
            }
        }
        if !text.is_empty() {
            parts.insert(0, text);
        }
        let text = parts.join("\n\n");
        if self.issue(
            id,
            Command::Chat {
                message_id: MessageId(Uuid::new_v4()),
                text,
                task_id: TaskId(Uuid::new_v4()),
                queue,
            },
        ) {
            self.chat_reference = None;
            self.chat_files.clear();
            self.composer.update(cx, |e, cx| e.set_value("", w, cx));
            // What the person just sent is in view, with the reply to come.
            if let Some(chat) = self.chat_list.borrow().as_ref() {
                chat.list.set_follow_mode(FollowMode::Tail);
            }
            // The answer arrives in the conversation.
            if from_page {
                self.open_chat(w, cx);
            }
        }
        cx.notify()
    }

    /// The conversation's open permission prompt, answered right in the chat.
    fn session_prompt(&self, state: &TopicState, cx: &Context<Self>) -> Option<Div> {
        let id = state.topic.id;
        let task = state
            .tasks
            .iter()
            .rev()
            .find(|t| t.is_session())
            .filter(|t| t.column == Column::NeedsYou)?;
        let action = task.action.as_ref()?;
        let (tid, review) = (task.id, task.review_version);
        Some(
            ui::column()
                .flex_none()
                .gap(px(8.))
                .mb(px(8.))
                .p(px(12.))
                .rounded(px(10.))
                .border_1()
                .border_color(ui::ink(0x18))
                .child(ui::caption("The agent asks for your OK"))
                .child(
                    div()
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(action.label.clone()),
                )
                .child(
                    ui::row()
                        .gap(px(8.))
                        .child(control(
                            "session-approve",
                            "Approve",
                            true,
                            cx,
                            move |s, _, _| s.approve(id, tid, review, None),
                        ))
                        .child(control(
                            "session-decline",
                            "Decline",
                            false,
                            cx,
                            move |s, _, cx| {
                                s.issue(
                                    id,
                                    Command::SendBack {
                                        task: tid,
                                        expected_review: Some(review),
                                        note: "Declined.".into(),
                                    },
                                );
                                cx.notify()
                            },
                        )),
                ),
        )
    }
    /// What the agent is doing and what's waiting for it, with Stop.
    fn session_bar(&self, state: &TopicState) -> Option<Div> {
        let working = Self::chat_answer_in_progress(state)
            .filter(|t| t.column == Column::InProgress)
            .map(|t| t.worker.clone());
        let messages = state
            .threads
            .iter()
            .filter(|t| t.is_topic_chat() && t.state == ThreadState::Sorting)
            .count();
        let todos = state
            .tasks
            .iter()
            .filter(|t| t.assignment == Some(InboxAssignment::Session) && t.column == Column::Todo)
            .count();
        if working.is_none() && messages == 0 && todos == 0 {
            return None;
        }
        let mut waiting = vec![];
        if messages > 0 {
            waiting.push(format!(
                "{messages} message{} waiting",
                if messages == 1 { "" } else { "s" }
            ));
        }
        if todos > 0 {
            waiting.push(format!(
                "{todos} to-do{} waiting",
                if todos == 1 { "" } else { "s" }
            ));
        }
        // Stop sits in the composer while it works.
        let mut parts = vec![];
        if let Some(progress) = working {
            parts.push(match progress.as_deref() {
                // Provider states such as "in_progress" say nothing the word Working does not.
                Some(p)
                    if !p.is_empty() && p != "Running" && p != "in_progress" && p != "Starting" =>
                {
                    format!("Working · {p}")
                }
                _ => "Working".to_owned(),
            });
        }
        parts.extend(waiting);
        Some(
            ui::row()
                .flex_none()
                .mx(px(14.))
                .mb(px(6.))
                .text_size(px(12.5))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .child(parts.join(" · ")),
        )
    }
}

/// An agent's structured final message, as the person reads it: the result it carries
/// instead of the JSON it was written in.
pub(super) fn readable_answer(text: &str) -> String {
    for (offset, _) in text.match_indices('{').rev() {
        let Some(Ok(value)) = serde_json::Deserializer::from_str(&text[offset..])
            .into_iter::<serde_json::Value>()
            .next()
        else {
            continue;
        };
        let inner = ["Findings", "Submitted"]
            .iter()
            .find_map(|k| value.get(*k))
            .unwrap_or(&value);
        if let Some(result) = inner.get("result").and_then(|r| r.as_str()) {
            let before = text[..offset].trim();
            return if before.is_empty() {
                result.to_owned()
            } else {
                format!("{before}\n\n{result}")
            };
        }
    }
    text.to_owned()
}

/// An item page's head, the same on every one: what kind of thing it is, then its name.
pub(super) fn item_title(kind: impl Into<SharedString>, title: impl Into<SharedString>) -> Div {
    ui::column()
        .gap(px(4.))
        .child(ui::caption(kind.into()))
        .child(
            div()
                .text_size(px(22.))
                .line_height(relative(1.3))
                .font_weight(FontWeight::SEMIBOLD)
                .child(title.into()),
        )
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::prelude::v1::test;

    fn request(state: &mut TopicState, text: &str, at: chrono::DateTime<Utc>) -> ThreadId {
        let thread = ThreadId(Uuid::new_v4());
        state
            .receive(
                Message {
                    id: MessageId(thread.0),
                    producer: Producer::User,
                    origin: Some(Source::User.into_origin("You".into(), at, None)),
                    author: "You".into(),
                    at,
                    text: text.into(),
                    external_id: None,
                },
                thread.to_string(),
                thread,
                at,
            )
            .unwrap();
        thread
    }

    fn start(
        state: &mut TopicState,
        thread: ThreadId,
        title: &str,
        at: chrono::DateTime<Utc>,
        shape: impl FnOnce(&mut meep_topic::Task),
    ) {
        let id = TaskId(Uuid::new_v4());
        state
            .add_task(id, title, Actor::Agent, Some(thread), at)
            .unwrap();
        let index = state.threads.iter().position(|t| t.id == thread).unwrap();
        state.threads[index].outcomes.push(Outcome::Task(id));
        let task = state.tasks.iter_mut().find(|t| t.id == id).unwrap();
        task.created_at = at;
        task.updated_at = at;
        shape(task);
    }

    #[test]
    fn parallel_tasks_group_under_the_request_that_started_them() {
        let at = chrono::DateTime::parse_from_rfc3339("2026-01-05T10:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut state = TopicState::new(Topic::new(TopicId(Uuid::new_v4()), "Launch", at));
        let first = request(&mut state, "Check the plan and onboarding.", at);
        start(&mut state, first, "Review the plan", at, |t| {
            t.column = Column::Done;
            t.result = Some("Ready for review.\nTwo dates moved.".into());
            t.updated_at = at + chrono::Duration::seconds(688);
        });
        start(&mut state, first, "Check onboarding", at, |t| {
            t.column = Column::NeedsYou;
            t.input_question = Some("Web or mobile?".into());
            t.result = Some("Partial notes".into());
        });
        start(&mut state, first, "Summarize the changelog", at, |t| {
            t.column = Column::NeedsYou;
            t.result = Some("GitHub connection expired.".into());
        });
        start(&mut state, first, "Answer in chat", at, |t| {
            t.assignment = Some(InboxAssignment::ChatAnswer);
        });
        let later = at + chrono::Duration::minutes(5);
        let second = request(&mut state, "Draft the email.", later);
        start(&mut state, second, "Draft the email", later, |t| {
            t.column = Column::InProgress;
        });
        let rows = BTreeMap::from([(first, 0), (second, 1)]);
        let linked = chat_linked_tasks(&state, &rows, 2);
        let now = later + chrono::Duration::seconds(75);
        let shown = |group: &[ChatTask]| {
            group
                .iter()
                .map(|t| {
                    (
                        t.title.clone(),
                        t.status(),
                        t.detail.clone(),
                        t.elapsed(now),
                    )
                })
                .collect::<Vec<_>>()
        };
        assert_eq!(
            shown(&linked[0]),
            [
                (
                    "Review the plan".to_owned(),
                    "Done",
                    "Ready for review.".to_owned(),
                    Some("11:28".to_owned()),
                ),
                (
                    "Check onboarding".to_owned(),
                    "Needs you",
                    "Web or mobile?".to_owned(),
                    Some("0:00".to_owned()),
                ),
                (
                    "Summarize the changelog".to_owned(),
                    "Failed",
                    "GitHub connection expired.".to_owned(),
                    Some("0:00".to_owned()),
                ),
            ]
        );
        assert_eq!(
            shown(&linked[1]),
            [(
                "Draft the email".to_owned(),
                "Working",
                "Working".to_owned(),
                Some("1:15".to_owned()),
            )]
        );
        assert_eq!(
            chat_task_summary(&linked[0])
                .into_iter()
                .map(|(text, _)| text)
                .collect::<Vec<_>>(),
            ["1 failed", "1 needs you", "1 done"]
        );
    }
}
