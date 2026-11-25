use super::*;
use chrono::Utc;
use meep_ui::gpui_kit::component::input::{Enter, Textarea};
use meep_ui::gpui_kit::component::{Disableable, Icon, Sizable, switch::Switch};
use std::collections::BTreeSet;

pub(super) fn count(n: usize, word: &str) -> String {
    match (n, word) {
        (1, _) => format!("1 {word}"),
        (_, "reply") => format!("{n} replies"),
        _ => format!("{n} {word}s"),
    }
}

pub(super) struct Attention {
    pub kind: &'static str,
    pub title: String,
    pub detail: String,
    pub page: Page,
    pub action: String,
}
/// The "you're done here" state: a check, "Nothing needs you", and a line
/// on why. Needs you and a skipped-only inbox both use it.
fn all_clear(why: impl Into<SharedString>) -> Div {
    ui::column()
        .w_full()
        .items_center()
        .gap(px(6.))
        .pt(px(56.))
        .pb(px(40.))
        .child(
            div()
                .size(px(44.))
                .mb(px(8.))
                .rounded_full()
                .bg(ui::ink(0x08))
                .flex()
                .items_center()
                .justify_center()
                .child(
                    Icon::new(Glyph::CheckCheck)
                        .size(px(20.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                ),
        )
        .child(
            div()
                .text_size(px(15.))
                .font_weight(FontWeight::SEMIBOLD)
                .child("Nothing needs you"),
        )
        .child(ui::caption(why.into()).max_w(px(440.)).text_center())
}
/// What kind of thing waits on you, as an icon on a tinted tile: a choice, a
/// question, an approval, a run that failed, a broken connection.
fn kind_tile(kind: &str) -> Stateful<Div> {
    let (glyph, tone, name) = match kind {
        "Decide" => (Glyph::GitBranch, UNREAD, "Decision"),
        "Question" => (Glyph::MessageCircle, UNREAD, "Question"),
        "Approve" => (Glyph::ShieldCheck, ui::POSITIVE, "Approval"),
        "Problem" => (Glyph::Plug, warning(), "Broken connection"),
        _ => (Glyph::TriangleAlert, warning(), "Failed run"),
    };
    // The icon is the kind; hover or a screen reader names it.
    div()
        .id(SharedString::from(format!("kind-{name}")))
        .aria_label(name)
        .tooltip(move |w, cx| {
            meep_ui::gpui_kit::component::tooltip::Tooltip::new(name).build(w, cx)
        })
        .flex_none()
        .size(px(32.))
        .rounded(px(9.))
        .bg(rgb(tone).opacity(0.12))
        .flex()
        .items_center()
        .justify_center()
        .child(Icon::new(glyph).size(px(16.)).text_color(rgb(tone)))
}
pub(super) fn thread_tab(thread: &Thread) -> Tab {
    if thread.is_agent_report() {
        Tab::Inbox
    } else if thread.key.starts_with("file-review/") {
        Tab::Files
    } else {
        Tab::Facts
    }
}
pub(super) fn attention(n: &NeedsYouItem, state: &TopicState) -> Option<Attention> {
    let id = state.topic.id;
    let (kind, title, detail, tab, item, action) = match n {
        NeedsYouItem::Decide {
            topic,
            thread,
            title,
            detail,
        } if *topic == id => (
            "Decide",
            title,
            detail,
            state
                .threads
                .iter()
                .find(|item| item.id.to_string() == *thread)
                .map_or(Tab::Facts, thread_tab),
            Detail::Thread(thread.parse().ok()?),
            "Decide",
        ),
        NeedsYouItem::Approve {
            topic,
            task,
            title,
            detail,
            action,
        } if *topic == id => (
            if action.as_deref() == Some("Reply") {
                "Question"
            } else {
                "Approve"
            },
            title,
            detail,
            Tab::Tasks,
            Detail::Task(task.parse().ok()?),
            action.as_deref().unwrap_or("Approve"),
        ),
        NeedsYouItem::Problem {
            topics,
            connection,
            title,
            detail,
        } if topics.contains(&id) => (
            "Problem",
            title,
            detail,
            Tab::Routines,
            Detail::Problem(connection.clone()),
            "Reconnect",
        ),
        _ => return None,
    };
    // The conversation's own permission prompt is answered in the chat.
    let in_chat = matches!(n, NeedsYouItem::Approve { task, .. }
        if state.tasks.iter().any(|t| t.is_session() && t.id.to_string() == *task));
    Some(Attention {
        kind,
        title: title.clone(),
        detail: detail.clone(),
        page: if in_chat {
            Page::Topic(id, Tab::Chat, None)
        } else {
            Page::Topic(id, tab, Some(item))
        },
        action: action.into(),
    })
}
/// Opening the inspector marks a thread seen. Its displayed date follows the conversation.
pub(super) fn message_time(t: &Thread) -> chrono::DateTime<Utc> {
    t.messages.last().map_or(t.created_at, |message| message.at)
}
/// The inbox's reports in reading order: open ones by priority (P0 first)
/// then newest, then the ones the person resolved or dismissed, newest first.
pub(super) fn ordered_threads(s: &TopicState, _skipped: bool) -> Vec<&Thread> {
    let mut list: Vec<_> = s
        .threads
        .iter()
        .filter(|t| t.is_agent_report() && !s.archived_threads.contains(&t.id))
        .collect();
    list.sort_by_key(|t| {
        let sources = t.report_sources.as_ref();
        (
            sources.and_then(|r| r.verdict.as_ref()).is_some(),
            sources
                .and_then(|r| r.priority)
                .unwrap_or(meep_topic::ReportPriority::P2),
            std::cmp::Reverse(message_time(t)),
        )
    });
    list
}
/// A report the person has not resolved or dismissed.
pub(super) fn report_open(t: &Thread) -> bool {
    t.report_sources
        .as_ref()
        .is_some_and(|r| r.verdict.is_none())
}
/// Red for what is urgent, ink for the middle, quiet for the rest.
pub(super) const RISK: u32 = 0xd1453b;
/// A report's priority as a small tinted badge; closed reports fade.
pub(super) fn priority_badge(p: Option<meep_topic::ReportPriority>, open: bool) -> Div {
    let c = p.map_or(ui::theme::color(ui::TERTIARY), priority_tone);
    let c = if open {
        c
    } else {
        ui::theme::color(ui::TERTIARY)
    };
    div()
        .flex_none()
        .w(px(26.))
        .h(px(20.))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(5.))
        .when(p.is_some(), |d| {
            d.bg(rgb(c).opacity(if open { 0.14 } else { 0.08 }))
        })
        .text_size(px(11.5))
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(c))
        .children(p.map(|p| p.label()))
}
pub(super) fn priority_tone(p: meep_topic::ReportPriority) -> u32 {
    use meep_topic::ReportPriority::*;
    match p {
        P0 | P1 => RISK,
        P2 => ui::theme::color(ui::SECONDARY),
        P3 | P4 => ui::theme::color(ui::TERTIARY),
    }
}
/// An evidence kind's icon.
pub(super) fn evidence_glyph(kind: Option<&str>) -> Glyph {
    match kind.unwrap_or_default() {
        "replay" => Glyph::Play,
        "error" => Glyph::TriangleAlert,
        "event" | "insight" => Glyph::ChartColumn,
        "ticket" | "slack" | "survey" => Glyph::MessageSquare,
        "github" => Glyph::GitPullRequest,
        "log" => Glyph::Rows3,
        _ => Glyph::FileText,
    }
}
/// The report's lead: its summary's first paragraph, as plain text.
pub(super) fn report_lead(t: &Thread) -> String {
    plain_line(
        t.summary
            .split("\n\n")
            .find(|p| !p.trim().is_empty())
            .unwrap_or_default(),
    )
}
/// Where the work on a report stands, as the inbox row says it: its verdict,
/// else the newest linked task's state.
pub(super) fn report_status(state: &TopicState, t: &Thread) -> Option<String> {
    if let Some(v) = t.report_sources.as_ref().and_then(|r| r.verdict.as_ref()) {
        return Some(
            match v.outcome {
                meep_topic::ReportOutcome::Resolved => "Resolved",
                meep_topic::ReportOutcome::Dismissed => "Dismissed",
            }
            .into(),
        );
    }
    let task = state
        .tasks
        .iter()
        .filter(|task| task.from_thread == Some(t.id))
        .max_by_key(|task| task.updated_at)?;
    let investigating = task.title.starts_with("Investigate");
    Some(
        match task.column {
            Column::InProgress if investigating => "Investigating",
            Column::InProgress => "Fix in progress",
            Column::NeedsYou => "Waiting on you",
            Column::Done if investigating => "Investigated",
            Column::Done => "Fix done",
            Column::Todo => "Queued",
        }
        .into(),
    )
}
/// Short actor name for task origin and table cells.
pub(super) fn actor(a: &Actor) -> String {
    match a {
        Actor::User => "You".into(),
        Actor::Agent => "Agent".into(),
        Actor::Routine(s) => s.clone(),
        Actor::Topic(_) => "Topic".into(),
        Actor::Inbox(_) => "Inbox".into(),
    }
}
pub(super) fn human_size(n: usize) -> String {
    match n {
        0..1024 => format!("{n} bytes"),
        1024..1_048_576 => format!("{:.1} KB", n as f64 / 1024.),
        _ => format!("{:.1} MB", n as f64 / 1_048_576.),
    }
}
/// A short, human age: "now", "5m ago", "3h ago", "2d ago", "4w ago".
pub(super) fn ago(d: chrono::Duration) -> String {
    let m = d.num_minutes().max(0);
    match m {
        0 => "now".into(),
        1..60 => format!("{m}m ago"),
        60..1440 => format!("{}h ago", m / 60),
        1440..20160 => format!("{}d ago", m / 1440),
        _ => format!("{}w ago", m / 10080),
    }
}
/// What starts a routine: the topic's own schedule wording when PostHog only
/// says it runs on a schedule, otherwise PostHog's trigger.
/// What a built-in stage does, and what turning it off means.
/// A row in a settings-style grouped list on the Context page.
fn context_row() -> Div {
    ui::row().w_full().py(px(11.)).gap(px(12.))
}
/// How much automated work this topic has used: agent starts against the hourly
/// cap, and System 1 calls and workflow runs today and this week.
fn usage_section(state: &TopicState) -> Div {
    let now = Utc::now();
    let usage = &state.usage;
    let today = now.date_naive();
    let day = usage.days.get(&today).cloned().unwrap_or_default();
    let (week_calls, week_runs) = usage.days.values().fold((0, 0), |(c, r), d| {
        (c + d.system_one, r + d.routine_dispatches)
    });
    let row = |label: &'static str, value: String| {
        context_row()
            .child(meep_shell::settings::copy(label, ""))
            .child(meep_shell::settings::value_text(value).text_size(px(12.)))
            .into_any_element()
    };
    ui::column()
        .child(meep_shell::settings::section(
            "Usage",
            "The work that the agent did for this topic.",
            None,
            false,
        ))
        .child(plain_rows([
            row(
                "Agent starts in the last hour",
                format!("{} of {}", usage.last_hour(now), usage.hourly_cap),
            ),
            row(
                "Sorting calls",
                format!("{} today · {week_calls} this week", day.system_one),
            ),
            row(
                "Workflow runs",
                format!("{} today · {week_runs} this week", day.routine_dispatches),
            ),
        ]))
}
/// The open request, waiting for the person, to turn this routine on.
fn activation_request(state: &TopicState, routine: &str) -> Option<TaskId> {
    state
        .tasks
        .iter()
        .find(|t| {
            t.column == Column::NeedsYou
                && t.action.as_ref().is_some_and(|a| {
                    a.kind.0 == "routine-activate" && a.payload["routine"] == routine
                })
        })
        .map(|t| t.id)
}
/// A routine fed by sources names them; any other names its trigger.
fn routine_caption(details: Option<&meep_wire::WorkflowDetails>, r: &RoutineInfo) -> String {
    let sources: Vec<_> = r.binding.watches.iter().map(|w| w.label.as_str()).collect();
    match sources.as_slice() {
        [] => trigger_text(details, r),
        [one] => format!("From {one}"),
        [one, two] => format!("From {one} and {two}"),
        [one, rest @ ..] => format!("From {one} and {} more", rest.len()),
    }
}
/// What happened to an observed event, in a few words.
fn outcome_text(o: &meep_topic::ObservationOutcome) -> String {
    use meep_topic::ObservationOutcome as O;
    match o {
        O::Pending => "Waiting to run".into(),
        O::Dispatched => "Running".into(),
        O::Inboxed(_) => "Put in the inbox".into(),
        O::Dropped { reason } => format!("Dropped: {reason}"),
        O::Task(_) => "Made a task".into(),
        O::Fact(_) => "Saved a fact".into(),
        O::Asked(_) => "Asked you".into(),
        O::Approval(_) => "Sent for approval".into(),
        O::Evidence(_) => "Added to a task".into(),
        O::FellBack { reason, .. } => format!("Sorted by Sort inbox: {reason}"),
        O::Finished { reason } => format!("Finished: {reason}"),
        O::Failed { reason } => format!("Failed: {reason}"),
    }
}
fn routine_panel(head: Div) -> Div {
    ui::column()
        .gap(px(22.))
        .min_w_0()
        .max_w(px(820.))
        .child(head)
}
fn routine_section(title: &'static str, body: impl IntoElement) -> Div {
    ui::column()
        .child(
            div()
                .text_size(px(13.))
                .font_weight(FontWeight::SEMIBOLD)
                .pb(px(10.))
                .child(title),
        )
        .child(body)
}
fn trigger_text(details: Option<&meep_wire::WorkflowDetails>, r: &RoutineInfo) -> String {
    if details.and_then(|d| d.manual_run_allowed) == Some(false) {
        return "When a watched source changes".into();
    }
    match details.and_then(|d| d.trigger.as_deref()) {
        Some("On a schedule") | None => r.binding.trigger.clone(),
        Some(t) => t.to_owned(),
    }
}
fn run_label(status: &str) -> &'static str {
    match status.to_ascii_lowercase().as_str() {
        "success" | "completed" | "succeeded" => "Completed",
        "failed" | "error" => "Failed",
        "running" => "Running",
        "queued" | "scheduled" => "Queued",
        _ => "Unknown",
    }
}
/// The warning orange, adjusted for the current appearance.
pub(super) fn warning() -> u32 {
    ui::theme::color(0xc2610c)
}
fn run_color(status: &str) -> u32 {
    match run_label(status) {
        "Completed" => ui::theme::color(ui::POSITIVE),
        "Failed" => warning(),
        _ => 0xb0b0b0,
    }
}
/// The goal line's height, read-only and while editing.
const GOAL_HEIGHT: f32 = 44.;
/// Mail's unread blue: the one chromatic mark in a list.
pub(super) const UNREAD: u32 = 0x2f7cf6;

/// A subject short enough for a title: the first line, cut at its first clause
/// when a whole request was used as the subject.
pub(super) fn short_subject(subject: &str) -> String {
    let line = subject.lines().next().unwrap_or_default().trim();
    if line.chars().count() <= 64 {
        return line.to_owned();
    }
    for stop in [": ", ". ", " — ", "? "] {
        if let Some(i) = line.find(stop)
            && (12..=72).contains(&line[..i].chars().count())
        {
            return line[..i + stop.trim_end().len()]
                .trim_end_matches([':', '.'])
                .to_owned();
        }
    }
    line.to_owned()
}

/// Markdown and line breaks flattened into one readable line, for previews.
pub(super) fn plain_line(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for line in text.lines() {
        let line = line.trim();
        // List markers and headings say nothing in a one-line preview.
        let line = line
            .trim_start_matches(['#', '>', '-', '*', '+'])
            .trim_start();
        let line = match line.split_once(". ") {
            Some((n, rest)) if !n.is_empty() && n.chars().all(|c| c.is_ascii_digit()) => rest,
            _ => line,
        };
        if line.is_empty() {
            continue;
        }
        if !out.is_empty() {
            out.push(' ');
        }
        out.push_str(line);
    }
    out.replace("**", "").replace('`', "").replace("__", "")
}

impl Desktop {
    pub(super) fn connection_label<'a>(&'a self, id: &'a str) -> &'a str {
        self.services
            .get(id)
            .map(String::as_str)
            .unwrap_or(match id {
                "posthog" => "PostHog",
                "github" => "GitHub",
                "slack" => "Slack",
                other => other,
            })
    }

    /// Resolve the service or topic display name independently of the channel.
    pub(super) fn source(&self, topic: &Topic, source: &Source) -> String {
        match source {
            Source::User => "You".into(),
            Source::Topic(id) => self
                .states
                .iter()
                .find(|s| s.topic.id == *id)
                .map(|s| format!("@{}", s.topic.name))
                .unwrap_or_else(|| format!("@{id}")),
            Source::Connection {
                connection,
                channel,
            } => topic
                .watches()
                .find(|w| w.connection == *connection && w.key == *channel && w.kind == "service")
                .map(|w| w.label.clone())
                .unwrap_or_else(|| self.connection_label(connection).to_owned()),
        }
    }
    pub(super) fn sender(&self, topic: &Topic, m: &Message) -> String {
        if m.reply_target() == Some(Source::Topic(topic.id)) && !m.author.is_empty() {
            m.author.clone()
        } else {
            m.reply_target()
                .map_or_else(|| m.author.clone(), |src| self.source(topic, &src))
        }
    }

    pub(super) fn task_origin(&self, state: &TopicState, task: &meep_topic::Task) -> String {
        match &task.added_by {
            Actor::Inbox(id) => state
                .threads
                .iter()
                .find(|t| t.id == *id)
                .and_then(|t| t.messages.first())
                .and_then(Message::reply_target)
                .map(|src| self.source(&state.topic, &src))
                .unwrap_or_else(|| actor(&task.added_by)),
            Actor::Topic(id) => self.source(&state.topic, &Source::Topic(*id)),
            other => actor(other),
        }
    }
    /// How to fix a connection: sign in again only when the sign-in expired;
    /// anything else is settled in Settings.
    pub(super) fn problem_fix(&self, connection: &str) -> (bool, &'static str) {
        let expired = self
            .client()
            .connections()
            .ok()
            .and_then(|c| c.connections.into_iter().find(|c| c.id == connection))
            .is_some_and(|c| c.health == "expired");
        if expired {
            (true, "Sign in again")
        } else {
            (false, "Open Settings")
        }
    }
    pub(super) fn fix_problem(
        &mut self,
        connection: String,
        topic: Option<TopicId>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        match (self.problem_fix(&connection).0, topic) {
            (true, Some(topic)) => {
                self.issue(topic, Command::Reconnect { connection });
            }
            _ => {
                self.settings_page = if connection == "posthog" {
                    SettingsPage::General
                } else {
                    SettingsPage::Connections
                };
                self.go(Page::Settings, w, cx)
            }
        }
    }
    /// One card per broken connection: what is wrong, what it affects, and the fix.
    fn problem_card(
        &self,
        i: usize,
        topics: &[TopicId],
        connection: &str,
        title: &str,
        detail: &str,
        cx: &Context<Self>,
    ) -> Div {
        let names: Vec<String> = topics
            .iter()
            .filter_map(|t| self.states.iter().find(|s| s.topic.id == *t))
            .map(|s| format!("@{}", s.topic.name))
            .collect();
        let (_, label) = self.problem_fix(connection);
        let connection = connection.to_owned();
        let first = topics.first().copied();
        ui::row()
            .items_start()
            .gap(px(14.))
            .p(px(16.))
            .rounded(px(12.))
            .bg(rgb(warning()).opacity(0.07))
            .border_1()
            .border_color(rgb(warning()).opacity(0.18))
            // The same tile as an item's kind, so the two read as one family.
            .child(kind_tile("Problem"))
            .child(
                ui::column()
                    .flex_1()
                    .min_w_0()
                    .gap(px(3.))
                    .child(
                        div()
                            .text_size(px(14.))
                            .font_weight(FontWeight::SEMIBOLD)
                            .child(title.to_owned()),
                    )
                    .child(
                        div()
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .line_height(relative(1.45))
                            .child(detail.to_owned()),
                    )
                    .when(!names.is_empty(), |c| {
                        c.child(ui::caption(format!("Affects {}", names.join(", "))).pt(px(4.)))
                    }),
            )
            .child(
                control(
                    format!("problem-fix-{i}"),
                    label,
                    true,
                    cx,
                    move |s, w, cx| s.fix_problem(connection.clone(), first, w, cx),
                )
                .self_center(),
            )
    }
    pub(super) fn attention_page(&self, cx: &Context<Self>) -> Div {
        let n = self.needs.len();
        let topics = self
            .needs
            .iter()
            .flat_map(|item| match item {
                NeedsYouItem::Decide { topic, .. } | NeedsYouItem::Approve { topic, .. } => {
                    vec![*topic]
                }
                NeedsYouItem::Problem { topics, .. } => topics.clone(),
            })
            .collect::<BTreeSet<_>>()
            .len();
        let mut showed_approval = false;
        // What waits, by kind, for the line under the title.
        let mut tally: Vec<(&'static str, usize)> = vec![];
        let mut tally_one = |kind: &'static str| match tally.iter_mut().find(|t| t.0 == kind) {
            Some(t) => t.1 += 1,
            None => tally.push((kind, 1)),
        };
        // One readable column, centred: an item's words and its action stay
        // close at any width.
        const MEASURE: f32 = 760.;
        let mut body = ui::column()
            .w_full()
            .max_w(px(MEASURE))
            .mx_auto()
            .gap(px(28.))
            .pt(px(20.))
            .pb(px(40.));
        for (i, item) in self.needs.iter().enumerate() {
            if let NeedsYouItem::Problem {
                topics,
                connection,
                title,
                detail,
            } = item
            {
                tally_one("Problem");
                body = body.child(self.problem_card(i, topics, connection, title, detail, cx));
            }
        }
        for state in &self.states {
            let id = state.topic.id;
            // Connection problems are listed once, above the topics they affect.
            let rows: Vec<_> = self
                .needs
                .iter()
                .filter(|n| !matches!(n, NeedsYouItem::Problem { .. }))
                .filter_map(|n| attention(n, state))
                .collect();
            let approved = self
                .just_approved
                .filter(|a| a.0 == id)
                .and_then(|(_, id, rule)| {
                    state.tasks.iter().find(|t| {
                        t.id == id && t.approval_rule == Some(rule) && t.column == Column::Done
                    })
                });
            if rows.is_empty() && approved.is_none() {
                continue;
            }
            let waiting = rows.len();
            // The topic's name, how many of its items wait, and the way in.
            let heading = ui::row()
                .px(px(2.))
                .pb(px(8.))
                .gap(px(8.))
                .child(ui::nav::glyph(Glyph::AtSign, false))
                .child(
                    div()
                        .min_w_0()
                        .truncate()
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(state.topic.name.clone()),
                )
                .child(
                    div()
                        .text_size(px(12.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(waiting.to_string()),
                )
                .child(div().flex_1())
                .child(
                    ui::row()
                        .id(SharedString::from(format!("attention-topic-{id}")))
                        .role(Role::Link)
                        .flex_none()
                        .gap(px(2.))
                        .cursor_pointer()
                        .text_size(px(12.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                        .child("Open topic")
                        .child(Icon::new(Glyph::ChevronRight).size(px(12.)))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(Page::Topic(id, Tab::Chat, None), w, cx)
                        })),
                );
            // A topic's items sit together on one card under its name.
            let mut section = ui::column()
                .gap_0()
                .flex_none()
                .rounded(px(12.))
                .border_1()
                .border_color(ui::ink(0x10))
                .overflow_hidden();
            for (i, mut a) in rows.into_iter().enumerate() {
                let page = a.page.clone();
                let review_page = a.page.clone();
                let dest = a.page;
                let task = match &dest {
                    Page::Topic(_, _, Some(Detail::Task(id))) => {
                        state.tasks.iter().find(|t| t.id == *id)
                    }
                    // The conversation's own prompt: its row opens the chat.
                    Page::Topic(_, Tab::Chat, None) => state.tasks.iter().find(|t| {
                        t.is_session() && t.column == Column::NeedsYou && t.action.is_some()
                    }),
                    _ => None,
                };
                let prompt = task.filter(|t| t.is_session()).map(|t| t.id);
                let review = task.map(|t| t.review_version);
                // How long it has waited: the thread's last message, or the
                // task's last change.
                let since = match &dest {
                    Page::Topic(_, _, Some(Detail::Thread(t))) => state
                        .threads
                        .iter()
                        .find(|th| th.id == *t)
                        .map(message_time),
                    _ => task.map(|t| t.updated_at),
                };
                // A run that could not start waits on the person with no
                // proposed action; it reads as that, not as its error text.
                let failed = task.is_some_and(|t| {
                    t.column == Column::NeedsYou
                        && t.action.is_none()
                        && !t.review_before_start
                        && t.assignment.as_ref() != Some(&InboxAssignment::Human)
                        && t.result.is_some()
                });
                // A routine retries itself; only other work is sent back.
                let retry = failed
                    && !task
                        .is_some_and(|t| matches!(t.assignment, Some(InboxAssignment::Routine(_))));
                if failed {
                    a.kind = "Needs attention";
                    a.detail = if retry {
                        "It couldn’t start. Try again runs it from the beginning."
                    } else {
                        "It couldn’t start. See why opens the run and its error."
                    }
                    .into();
                    a.action = if retry { "Try again" } else { "See why" }.into();
                }
                tally_one(a.kind);
                let button = control(
                    format!("attention-act-{id}-{i}"),
                    a.action,
                    false,
                    cx,
                    move |s, w, cx| match &dest {
                        Page::Topic(_, _, Some(Detail::Task(task))) if retry => {
                            if let Some(version) = review {
                                s.issue(
                                    id,
                                    Command::SendBack {
                                        task: *task,
                                        expected_review: Some(version),
                                        note: String::new(),
                                    },
                                );
                            }
                        }
                        Page::Topic(_, _, Some(Detail::Task(_))) if failed => {
                            s.go(dest.clone(), w, cx)
                        }
                        Page::Topic(_, _, Some(Detail::Task(task)))
                            if let Some(version) = review =>
                        {
                            s.approve(id, *task, version, None)
                        }
                        Page::Topic(_, Tab::Chat, None)
                            if let (Some(task), Some(version)) = (prompt, review) =>
                        {
                            s.approve(id, task, version, None)
                        }
                        Page::Topic(_, _, Some(Detail::Problem(connection))) => {
                            s.issue(
                                id,
                                Command::Reconnect {
                                    connection: connection.clone(),
                                },
                            );
                        }
                        _ => s.go(dest.clone(), w, cx),
                    },
                );
                section = section.child(
                    line(format!("attention-row-{id}-{i}"), false)
                        // Icon, title and age share the row's top line.
                        .items_start()
                        .px(px(14.))
                        .py(px(12.))
                        .gap(px(14.))
                        .rounded_none()
                        .when(i > 0, |r| r.border_t_1().border_color(ui::ink(0x0d)))
                        .child(kind_tile(a.kind).self_start())
                        .child(
                            ui::column()
                                .flex_1()
                                .min_w_0()
                                .gap(px(3.))
                                .child(
                                    // Two lines before a long title gives way.
                                    div()
                                        .min_w_0()
                                        .text_size(px(14.))
                                        .font_weight(FontWeight::SEMIBOLD)
                                        .line_clamp(2)
                                        .child(short_subject(&a.title)),
                                )
                                // Agent text can be markdown; one plain sentence previews it.
                                .child(
                                    ui::caption(plain_line(
                                        a.detail
                                            .split("\n\n")
                                            .find(|p| !p.trim().is_empty())
                                            .unwrap_or_default(),
                                    ))
                                    // The why behind the ask: two lines before it gives way.
                                    .line_clamp(2),
                                ),
                        )
                        // When it arrived, then what to do about it. Past a day of
                        // waiting, the age turns amber.
                        .child(
                            ui::column()
                                .flex_none()
                                .self_start()
                                .items_end()
                                .gap(px(6.))
                                .children(since.map(|at| {
                                    let waited = Utc::now() - at;
                                    div()
                                        .text_size(px(12.))
                                        .text_color(rgb(if waited > chrono::Duration::days(1) {
                                            warning()
                                        } else {
                                            ui::theme::color(ui::TERTIARY)
                                        }))
                                        .child(ago(waited))
                                }))
                                .child(
                                    ui::row()
                                        .gap(px(4.))
                                        // An approval acts at once; Review opens what it would send.
                                        .when(a.kind == "Approve", |r| {
                                            let open = review_page.clone();
                                            r.child(
                                                div()
                                                    .id(SharedString::from(format!(
                                                        "attention-review-{id}-{i}"
                                                    )))
                                                    .role(Role::Link)
                                                    .flex_none()
                                                    .self_center()
                                                    .px(px(6.))
                                                    .cursor_pointer()
                                                    .text_size(px(13.))
                                                    .text_color(rgb(ui::theme::color(
                                                        ui::SECONDARY,
                                                    )))
                                                    .hover(|s| {
                                                        s.text_color(rgb(ui::theme::color(ui::INK)))
                                                    })
                                                    .child("Review")
                                                    .on_click(cx.listener(move |s, _, w, cx| {
                                                        cx.stop_propagation();
                                                        s.go(open.clone(), w, cx)
                                                    })),
                                            )
                                        })
                                        .child(button.w(px(116.)).flex_none()),
                                ),
                        )
                        .on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx))),
                );
            }
            if let Some(task) = approved {
                showed_approval = true;
                section = section.child(self.after_approval(state, task, cx))
            }
            body = body.child(ui::column().gap_0().child(heading).child(section));
        }
        // "1 failed run · 3 decisions · across 3 topics": what is broken first.
        let rank = |kind: &str| match kind {
            "Problem" => 0,
            "Needs attention" => 1,
            "Approve" => 2,
            "Decide" => 3,
            _ => 4,
        };
        tally.sort_by_key(|(kind, _)| rank(kind));
        let mut parts: Vec<String> = tally
            .iter()
            .map(|(kind, n)| {
                count(
                    *n,
                    match *kind {
                        "Decide" => "decision",
                        "Question" => "question",
                        "Approve" => "approval",
                        "Problem" => "broken connection",
                        _ => "failed run",
                    },
                )
            })
            .collect();
        if topics > 1 {
            parts.push(format!("across {}", count(topics, "topic")));
        }
        let summary = parts.join(" · ");
        if n == 0 && !showed_approval {
            body = body.child(all_clear(
                "Decisions, approvals and broken connections from your topics land here. \
                 Everything else they get done on their own.",
            ))
        }
        ui::column().size_full().child(
            scroll("attention-items").w_full().child(
                ui::column()
                    .w_full()
                    .max_w(px(MEASURE))
                    .mx_auto()
                    .child(
                        self.header_row(cx).child(
                            ui::column()
                                .gap(px(2.))
                                .child(ui::heading("needs-title", "Needs you"))
                                .when(n > 0, |c| c.child(ui::caption(summary))),
                        ),
                    )
                    .child(body),
            ),
        )
    }
    pub(super) fn topic_view(
        &self,
        state: &TopicState,
        tab: Tab,
        detail: Option<&Detail>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let topic = &state.topic;
        let id = topic.id;
        let topic_id = id;
        let topic_archived = state.archived;
        // A broken connection shows as a banner over the content, not a clipped button.
        let problem = self.needs.iter().find_map(|n| match n {
            NeedsYouItem::Problem {
                topics, connection, ..
            } if topics.contains(&id) => Some(connection.clone()),
            _ => None,
        });
        let pane = self.topic_pane_width(w);
        let mut tools: Vec<AnyElement> = vec![];
        if tab == Tab::Tasks && detail.is_none() && state.tasks.iter().any(|t| !t.hidden()) {
            tools.push(
                self.tasks_toolbar(id, pane < px(760.), cx)
                    .into_any_element(),
            );
        }
        if tab == Tab::Routines && detail.is_none() && !self.new_routine {
            tools.push(
                control("bind", "New routine", false, cx, |s, w, cx| {
                    s.compose_routine(w, cx)
                })
                .icon(Glyph::Plus)
                // Buttons default to the top of their row; in the crumb bar they centre.
                .self_center()
                .into_any_element(),
            );
        }
        tools.extend(self.show_overview_button(w, cx));
        let tab_in = ui::motion::arrival(
            ElementId::from(SharedString::from(format!("tab-{id}-{tab:?}-{detail:?}"))),
            false,
            w,
            cx,
        )
        .progress
        .clamp(0., 1.);
        let routine = match &detail {
            Some(Detail::Routine(key)) if tab == Tab::Routines && !self.new_routine => state
                .topic
                .routines
                .iter()
                .find(|r| &r.binding.id == key && r.binding.backend == "posthog"),
            _ => None,
        };
        let task = match detail {
            Some(Detail::Task(t)) => state.tasks.iter().find(|task| task.id == *t),
            _ => None,
        };
        // Pages that carry their own crumb bar: the conversation, a task, an
        // inbox report and a routine. Everything else opens under the topic's.
        let own_header = tab == Tab::Chat && detail.is_none()
            || task.is_some()
            || routine.is_some()
            || matches!(
                detail,
                Some(Detail::Thread(_) | Detail::Fact(_) | Detail::Problem(_))
            );
        let body: AnyElement = if let Some(t) = task {
            self.task_panel(state, t, w, cx).into_any_element()
        } else if tab == Tab::Chat && detail.is_none() {
            self.chat_view(state, w, cx).into_any_element()
        } else if let Some(d) =
            detail.filter(|d| matches!(d, Detail::Thread(_) | Detail::Fact(_) | Detail::Problem(_)))
        {
            self.thread_page(state, d, w, cx).into_any_element()
        } else {
            ui::column()
                .size_full()
                .min_h_0()
                .children(routine.map(|r| self.routine_bar(state.topic.id, r, cx)))
                .child(
                    scroll("topic-content")
                        .track_scroll(&self.content_scroll)
                        .h_full()
                        .px(px(super::details::PAGE_X))
                        .pt(px(super::details::PAGE_TOP))
                        .pb(px(12.))
                        .child({
                            let content = match (tab, detail) {
                                (_, Some(Detail::Goal(g))) => self.goal_page(state, *g, cx),
                                (_, Some(Detail::Linked(k))) => self.linked_page(state, k, cx),
                                _ => match tab {
                                    Tab::Chat | Tab::Inbox => self.inbox(state, w, cx),
                                    Tab::Needs => self.topic_needs(state, cx),
                                    Tab::Tasks => self.tasks_page(state, w, cx),
                                    Tab::Files => self.data_page(state, cx),
                                    Tab::Routines => self.routines(state, w, cx),
                                    Tab::Mission
                                    | Tab::Goals
                                    | Tab::Facts
                                    | Tab::Linked
                                    | Tab::Rules => self.context_page(state, tab, w, cx),
                                },
                            };
                            let content = if matches!(tab, Tab::Facts | Tab::Files) {
                                ui::column()
                                    .w_full()
                                    .child(self.review_links(state, tab, cx))
                                    .child(content)
                            } else {
                                content
                            };
                            // One reading column, as the conversation has; the file
                            // browser and the board need the whole width.
                            let wide = tab == Tab::Files
                                || (tab == Tab::Tasks
                                    && self.task_display.boards.contains(&state.topic.id));
                            if wide {
                                content
                            } else {
                                div().w_full().max_w(px(720.)).mx_auto().child(content)
                            }
                        })
                        .flex_1()
                        .min_h_0(),
                )
                .into_any_element()
        };
        let mut body = ui::column()
            .relative()
            .flex_1()
            .min_h_0()
            .opacity(tab_in)
            .child(body);
        if tab == Tab::Tasks && self.adding {
            body = body.child(self.task_composer(w, cx));
        }
        // Every page keeps the conversation one line away, about what it shows.
        let talks = task.is_none() && !(tab == Tab::Chat && detail.is_none()) && !self.new_routine;
        if talks {
            let answering = Self::chat_answer_in_progress(state).map(|t| t.id);
            body = body.child(
                div()
                    .flex_none()
                    .w_full()
                    .flex()
                    .justify_center()
                    .px(px(super::details::PAGE_X))
                    .pb(px(14.))
                    .pt(px(6.))
                    .child(
                        div()
                            .w_full()
                            .max_w(px(720.))
                            .child(self.topic_composer(state, answering, w, cx)),
                    ),
            );
        }
        let header = (!own_header).then(|| {
            let current = match detail {
                Some(Detail::Goal(g)) => topic.goals.iter().find(|x| x.id == *g).map(|x| {
                    (
                        Some(ui::nav::glyph(Glyph::Target, false).into_any_element()),
                        x.text.clone(),
                    )
                }),
                Some(Detail::Linked(key)) => topic
                    .context_sources
                    .iter()
                    .find(|x| x.key == *key)
                    .map(|x| (None, x.label.clone())),
                _ => None,
            };
            crumb_bar(topic_crumbs(id, &topic.name, tab, current, cx), None, tools)
        });
        ui::column()
            .size_full()
            .min_h_0()
            .flex_1()
            .gap_0()
            .rounded(px(12.))
            .overflow_hidden()
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .children(header)
            .when(topic_archived, |c| {
                c.child(
                    ui::row()
                        .id("topic-archived")
                        .flex_none()
                        .gap(px(10.))
                        .px(px(24.))
                        .py(px(9.))
                        .bg(ui::ink(0x08))
                        .border_b_1()
                        .border_color(ui::ink(0x10))
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .child("Archived. Nothing new arrives and routines are paused."),
                        )
                        .child(control(
                            "unarchive-topic",
                            "Restore",
                            false,
                            cx,
                            move |s, _, cx| {
                                s.issue(topic_id, Command::UnarchiveTopic);
                                cx.notify()
                            },
                        )),
                )
            })
            .when_some(problem, |c, connection| {
                // A plain title; the raw cause lives in the connection pane.
                let (expired, label) = self.problem_fix(&connection);
                let service = self.connection_label(&connection);
                let title = if expired {
                    format!("Sign in to {service} again")
                } else {
                    format!("{service} isn't responding. Meep will retry.")
                };
                c.child(
                    ui::row()
                        .id("topic-health")
                        .flex_none()
                        .gap(px(10.))
                        .px(px(24.))
                        .py(px(9.))
                        .bg(rgb(warning()).opacity(0.07))
                        .border_b_1()
                        .border_color(rgb(warning()).opacity(0.16))
                        .child(
                            Icon::new(Glyph::TriangleAlert)
                                .size(px(13.))
                                .text_color(rgb(warning())),
                        )
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .truncate()
                                .font_weight(FontWeight::MEDIUM)
                                .child(title),
                        )
                        .child(control(
                            "topic-health-fix",
                            label,
                            false,
                            cx,
                            move |s, w, cx| s.fix_problem(connection.clone(), Some(id), w, cx),
                        )),
                )
            })
            .child(body)
            .relative()
            .when(self.overview_overlay && !self.overview_docked(w), |c| {
                c.child(
                    div()
                        .absolute()
                        .top_0()
                        .right_0()
                        .bottom_0()
                        .w(px(super::overview::WIDTH))
                        .border_l_1()
                        .border_color(ui::ink(0x12))
                        .shadow_lg()
                        .occlude()
                        .child(self.overview(state, cx)),
                )
            })
    }
    /// The width the topic's own pane gets beside the sidebar and the Overview.
    pub(super) fn topic_pane_width(&self, w: &Window) -> Pixels {
        let viewport = w.viewport_size().width;
        viewport
            - if self.sidebar_hidden {
                px(0.)
            } else {
                px(meep_ui::design::current().sidebar)
            }
            - if self.overview_docked(w) {
                px(super::overview::WIDTH + meep_shell::GUTTER)
            } else {
                px(0.)
            }
    }
    /// The topic's own Needs you: its decisions, approvals and problems.
    fn topic_needs(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let items: Vec<_> = self
            .needs
            .iter()
            .filter_map(|n| attention(n, state))
            .collect();
        if items.is_empty() {
            return ui::column()
                .w_full()
                .max_w(px(720.))
                .mx_auto()
                .pt(px(40.))
                .items_center()
                .child(ui::caption("Nothing needs you here."));
        }
        let mut list = ui::column().w_full().max_w(px(720.)).mx_auto();
        for (i, a) in items.into_iter().enumerate() {
            let page = a.page.clone();
            list = list.child(
                ui::row()
                    .id(SharedString::from(format!("topic-need-{i}")))
                    .gap(px(12.))
                    .px(px(12.))
                    // The dot hangs in the margin, as in the inbox.
                    .ml(px(-31.))
                    .mr(px(-12.))
                    .py(px(10.))
                    .rounded(px(8.))
                    .cursor_pointer()
                    .hover(|s| s.bg(ui::ink(0x06)))
                    .child(div().size(px(7.)).rounded_full().bg(rgb(UNREAD)))
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .child(
                                div()
                                    .truncate()
                                    .font_weight(FontWeight::MEDIUM)
                                    .child(a.title.clone()),
                            )
                            .child(ui::caption(a.detail.clone()).truncate()),
                    )
                    .child(ui::caption(a.kind))
                    .on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx))),
            );
        }
        list
    }
    fn inbox(&self, state: &TopicState, w: &Window, cx: &Context<Self>) -> Div {
        // These match the fixed two-line rows and section headings below. Keep
        // spacers at the same height so the shared scroll handle stays stable.
        const ROW_HEIGHT: f32 = 56.;
        const OVERSCAN: f32 = 300.;
        let all = ordered_threads(state, true);
        if all.is_empty() {
            return deck(
                Glyph::Inbox,
                UNREAD,
                "Waiting for the first report",
                format!("@{}", state.topic.name),
                [
                    "Agents send their reports here.",
                    "Each report shows its evidence and a next step that you can start.",
                ],
            )
            .child(
                control(
                    "inbox-sources",
                    "Add a source",
                    false,
                    cx,
                    move |s, w, cx| s.ask_in_chat("Find and add this PostHog object: ", w, cx),
                )
                .mt(px(16.))
                .self_center(),
            );
        }
        let id = state.topic.id;
        let mut list = ui::column()
            .w_full()
            .max_w(px(960.))
            .mx_auto()
            .gap_0()
            .pt(px(4.));
        let virtualize = !w.is_a11y_active() && !cx.has_active_drag();
        let top = (-f32::from(self.content_scroll.offset().y)).max(0.);
        let height = f32::from(self.content_scroll.bounds().size.height)
            .max(f32::from(w.viewport_size().height));
        let low = (top - OVERSCAN).max(0.);
        let high = top + height + OVERSCAN;
        let mut skipped_height = 0_f32;
        // Resolved and dismissed reports wait behind a quiet line at the end.
        let closed = all.iter().filter(|t| !report_open(t)).count();
        let open = all.len() - closed;
        for (index, t) in all.into_iter().enumerate() {
            if index == open {
                if skipped_height > 0. {
                    list = list.child(div().h(px(skipped_height)).flex_none());
                    skipped_height = 0.;
                }
                list = list.child(
                    ui::row()
                        .id("show-closed-reports")
                        .role(Role::Button)
                        .h(px(ROW_HEIGHT))
                        .mt(px(if open > 0 { 8. } else { 0. }))
                        .px(px(0.))
                        .gap(px(6.))
                        .rounded(px(6.))
                        .cursor_pointer()
                        .text_size(px(13.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                        .child(Icon::new(Glyph::ChevronRight).size(px(12.)).rotate(
                            meep_ui::gpui_kit::radians(if self.skipped {
                                std::f32::consts::FRAC_PI_2
                            } else {
                                0.
                            }),
                        ))
                        .child(format!("{closed} resolved or dismissed"))
                        .on_click(cx.listener(|s, _, _, cx| {
                            s.skipped = !s.skipped;
                            cx.notify()
                        })),
                );
                if !self.skipped {
                    break;
                }
            }
            let row_y = index as f32 * ROW_HEIGHT;
            if virtualize && index < open && (row_y + ROW_HEIGHT < low || row_y > high) {
                skipped_height += ROW_HEIGHT;
                continue;
            }
            if skipped_height > 0. {
                list = list.child(div().h(px(skipped_height)).flex_none());
                skipped_height = 0.;
            }
            let page = Page::Topic(id, Tab::Inbox, Some(Detail::Thread(t.id)));
            let thread = t.id;
            let is_open = report_open(t);
            let sources = t.report_sources.as_ref();
            let priority = sources.and_then(|r| r.priority);
            let status = report_status(state, t);
            let lead = report_lead(t);
            let group: SharedString = format!("report-row-{thread}").into();
            let when = {
                let at = message_time(t);
                let age = Utc::now() - at;
                if age < chrono::Duration::days(7) {
                    ago(age)
                } else {
                    at.with_timezone(&chrono::Local).format("%b %e").to_string()
                }
            };
            let tone = |c: u32| {
                rgb(if is_open {
                    c
                } else {
                    ui::theme::color(ui::TERTIARY)
                })
            };
            // One line, as a mail client reads: priority, the headline and its
            // lead, where the work stands, and when. Quick verdicts on hover.
            let verdict = |key: &'static str,
                           glyph: Glyph,
                           label: &'static str,
                           outcome,
                           reason: &'static str| {
                ui::contextual_icon_button(
                    SharedString::from(format!("{key}-{thread}")),
                    glyph,
                    label,
                    group.clone(),
                    false,
                )
                .tooltip(label)
                .on_click(cx.listener(move |s, _, _, cx| {
                    cx.stop_propagation();
                    s.issue(
                        id,
                        Command::SetReportVerdict {
                            thread,
                            outcome: Some(outcome),
                            reason: reason.into(),
                        },
                    );
                    cx.notify()
                }))
            };
            list = list.child(
                line(format!("thread-{}", t.id), self.page == page)
                    .group(group.clone())
                    .h(px(ROW_HEIGHT))
                    .flex_none()
                    .when(self.page == page, |row| {
                        row.track_scroll(&self.selection_bounds)
                    })
                    .gap(px(10.))
                    .px(px(12.))
                    // The unread dot hangs in the page margin, so the headline lines
                    // up with every other list's first column.
                    .w_auto()
                    .ml(px(-28.))
                    .mr(px(-12.))
                    .rounded(px(8.))
                    .items_start()
                    .pt(px(9.))
                    .text_size(px(14.))
                    // Unread: a dot in the gutter and a heavier headline.
                    .child(
                        div()
                            .w(px(6.))
                            .h(px(20.))
                            .flex_none()
                            .flex()
                            .items_center()
                            .when(t.unseen, |slot| {
                                slot.child(
                                    div()
                                        .id(format!("unseen-{}", t.id))
                                        .aria_label("Unread")
                                        .size(px(6.))
                                        .rounded_full()
                                        .bg(rgb(UNREAD)),
                                )
                            }),
                    )
                    // Priority as a small tinted badge, so P0/P1 read at a glance.
                    .child(
                        div()
                            .id(format!("priority-{}", t.id))
                            .child(priority_badge(priority, is_open)),
                    )
                    // The headline, then where it stands and its lead on a quieter line.
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .gap(px(2.))
                            .child(
                                div()
                                    .id(format!("thread-title-{}", t.id))
                                    .h(px(20.))
                                    .truncate()
                                    .font_weight(if t.unseen {
                                        FontWeight::SEMIBOLD
                                    } else {
                                        FontWeight::MEDIUM
                                    })
                                    .text_color(tone(ui::theme::color(ui::INK)))
                                    .child(short_subject(&t.subject)),
                            )
                            .child(
                                ui::row()
                                    .gap(px(0.))
                                    .min_w_0()
                                    .text_size(px(12.5))
                                    .children(status.clone().map(|st| {
                                        div()
                                            .flex_none()
                                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                            .child(format!("{st} · "))
                                    }))
                                    .child(
                                        div()
                                            .flex_1()
                                            .min_w_0()
                                            .truncate()
                                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                            .child(lead),
                                    ),
                            ),
                    )
                    .child(
                        div()
                            .relative()
                            .flex_none()
                            .w(px(64.))
                            .h(px(20.))
                            .flex()
                            .items_center()
                            .justify_end()
                            .child(
                                div()
                                    .text_size(px(12.5))
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                    .group_hover(group.clone(), |s| s.opacity(0.))
                                    .when(!is_open, |d| d.opacity(1.))
                                    .child(when),
                            )
                            .when(is_open, |slot| {
                                slot.child(
                                    ui::row()
                                        .absolute()
                                        .right(px(-6.))
                                        .gap(px(2.))
                                        .child(verdict(
                                            "quick-resolve",
                                            Glyph::CircleCheck,
                                            "Resolve",
                                            meep_topic::ReportOutcome::Resolved,
                                            "Fixed",
                                        ))
                                        .child(verdict(
                                            "quick-dismiss",
                                            Glyph::EyeOff,
                                            "Dismiss",
                                            meep_topic::ReportOutcome::Dismissed,
                                            "Not relevant",
                                        )),
                                )
                            }),
                    )
                    .on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx))),
            );
        }
        if skipped_height > 0. {
            list = list.child(div().h(px(skipped_height)).flex_none());
        }
        list
    }
    fn review_links(&self, state: &TopicState, tab: Tab, cx: &Context<Self>) -> Div {
        let prefix = match tab {
            Tab::Facts => "fact-review/",
            Tab::Files => "file-review/",
            _ => return div(),
        };
        let topic = state.topic.id;
        let mut reviews = ui::column().gap(px(8.));
        for thread in state.threads.iter().filter(|thread| {
            thread.key.starts_with(prefix)
                && !state.archived_threads.contains(&thread.id)
                && matches!(thread.state, ThreadState::NeedsYou { .. })
        }) {
            let id = thread.id;
            reviews = reviews.child(control(
                format!("review-{id}"),
                format!("Review: {}", short_subject(&thread.subject)),
                false,
                cx,
                move |s, w, cx| s.go(Page::Topic(topic, tab, Some(Detail::Thread(id))), w, cx),
            ));
        }
        reviews
    }
    /// Commit the inline edit to the replica and return focus to the topic.
    pub(super) fn save_mission(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let mission = self.mission_edit.read(cx).value().trim().to_owned();
        if let Some(id) = self.topic_id()
            && self.issue(id, Command::SetMission { mission })
        {
            self.editing = false;
            self.focus.focus(w, cx);
        }
    }
    /// What the topic is for, what it knows, what it works with and how it
    /// acts, read top to bottom in one centred column: the goal as the page's
    /// title, then each part as a settings-style section over one grouped list.
    fn context_page(&self, state: &TopicState, part: Tab, _w: &Window, cx: &Context<Self>) -> Div {
        use meep_shell::settings as set;
        let t = &state.topic;
        let id = t.id;
        let now = Utc::now();
        let tertiary = || rgb(ui::theme::get(2));
        // Rows of a group share one inset and rhythm.
        let list_row = || ui::row().w_full().py(px(11.)).gap(px(12.));

        // ── Goal ──────────────────────────────────────────────────────────
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
        let mission = if self.editing {
            ui::column()
                .on_action(cx.listener(|s, _: &Enter, w, cx| {
                    s.save_mission(w, cx);
                    cx.notify();
                }))
                .gap(px(8.))
                .child(
                    // The field's border stays inside the column; its own padding
                    // insets the text. The goal keeps its reading size and wraps
                    // like the read-only goal.
                    div().w_full().min_h(px(GOAL_HEIGHT)).child(
                        Textarea::new(&self.mission_edit)
                            .aria_label("Mission")
                            .text_size(px(22.))
                            .line_height(relative(1.3))
                            .font_weight(FontWeight::SEMIBOLD),
                    ),
                )
                .child(
                    ui::row()
                        .justify_end()
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
        } else {
            ui::row()
                .group("mission")
                .items_start()
                .gap(px(6.))
                .child(
                    div()
                        .id("mission-text")
                        .role(Role::Button)
                        .flex()
                        .items_center()
                        .flex_1()
                        .min_w_0()
                        // The editor's height and inset, so nothing below
                        // moves when editing starts.
                        .min_h(px(GOAL_HEIGHT))
                        .ml(px(-12.))
                        .px(px(12.))
                        .cursor_text()
                        .rounded(px(8.))
                        .text_size(px(22.))
                        .line_height(relative(1.3))
                        .font_weight(FontWeight::SEMIBOLD)
                        .hover(|e| e.bg(ui::ink(0x06)))
                        .child(div().flex_1().min_w_0().child(t.mission.clone()))
                        .on_click(cx.listener(move |s, _, w, cx| start_edit(s, w, cx))),
                )
                .child(
                    // Quiet until the goal is pointed at.
                    ui::row()
                        .h(px(GOAL_HEIGHT))
                        .flex_none()
                        .opacity(0.45)
                        .group_hover("mission", |s| s.opacity(1.))
                        .child(
                            ui::icon_button("edit-mission", Glyph::Pencil, "Edit the goal")
                                .on_click(cx.listener(move |s, _, w, cx| start_edit(s, w, cx))),
                        ),
                )
        };
        // Goals have the page to themselves: a card each, two to a row, with the
        // number that matters large and the bar across the card.
        let metrics: Vec<AnyElement> = t.goals.iter().map(|g| goal_card(id, g, cx)).collect();

        // ── Facts ─────────────────────────────────────────────────
        let current: Vec<&Fact> = t.facts.iter().filter(|f| f.is_current()).collect();
        let disputed = state.disputed_facts();
        let replaced = t.facts.len() - current.len();
        let sources: BTreeSet<&str> = current
            .iter()
            .map(|f| f.provenance.author.as_str())
            .collect();
        // Facts learned per week, oldest first: a small bar strip.
        let weeks = 8usize;
        let mut per_week = vec![0usize; weeks];
        for f in &current {
            let age = (now - f.provenance.at).num_days().max(0) as usize / 7;
            if age < weeks {
                per_week[weeks - 1 - age] += 1;
            }
        }
        let peak = per_week.iter().copied().max().unwrap_or(0).max(1);
        // A trend needs a few weeks of learning; fewer reads as noise.
        let active_weeks = per_week.iter().filter(|n| **n > 0).count();
        let strip =
            ui::row()
                .items_end()
                .gap(px(3.))
                .h(px(18.))
                .children(per_week.iter().enumerate().map(|(i, n)| {
                    div()
                        .w(px(5.))
                        .h(px(3. + 15. * *n as f32 / peak as f32))
                        .rounded(px(1.5))
                        .bg(if i + 1 == weeks {
                            rgb(ui::theme::color(ui::INK))
                        } else {
                            ui::ink(0x22)
                        })
                }));
        let latest = current.iter().map(|f| f.provenance.at).max();
        // The crumb bar names the page; a quiet line says how much it knows.
        let mut knows = ui::column().gap(px(12.)).when(!current.is_empty(), |c| {
            c.child(
                ui::row()
                    .gap(px(12.))
                    .child(
                        ui::caption(format!(
                            "{} from {} · latest {}",
                            count(current.len(), "fact"),
                            count(sources.len(), "source"),
                            latest.map(|at| ago(now - at)).unwrap_or_default()
                        ))
                        .flex_1(),
                    )
                    .when(active_weeks >= 3, |r| r.child(strip)),
            )
        });
        if current.is_empty() {
            knows = knows.child(set::empty(
                "No facts",
                "The agent adds facts when it reads the inbox. Each fact links to its source.",
            ));
        }
        let mut sorted = current.clone();
        sorted.sort_by_key(|f| std::cmp::Reverse(f.provenance.at));
        let mut facts = Vec::new();
        for f in sorted {
            let fid = f.id;
            let author = &f.provenance.author;
            let initials: String = author
                .split_whitespace()
                .filter_map(|w| w.chars().next())
                .take(2)
                .flat_map(char::to_uppercase)
                .collect();
            facts.push(
                list_row()
                    .id(SharedString::from(format!("fact-{fid}")))
                    .group(format!("fact-{fid}"))
                    .items_start()
                    .py(px(12.))
                    .child(
                        div()
                            .size(px(24.))
                            .mt(px(1.))
                            .flex_none()
                            .rounded_full()
                            .bg(ui::ink(0x0c))
                            .flex()
                            .items_center()
                            .justify_center()
                            .text_size(px(9.5))
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .child(if initials.is_empty() {
                                "·".into()
                            } else {
                                initials
                            }),
                    )
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .gap(px(3.))
                            .child(
                                div()
                                    .text_size(px(13.5))
                                    .line_height(relative(1.45))
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
                    // Removing is a hover affordance, not a standing mark on every row.
                    .child(
                        div()
                            .flex_none()
                            .opacity(0.)
                            .group_hover(format!("fact-{fid}"), |s| s.opacity(1.))
                            .child(
                                ui::icon_button(
                                    SharedString::from(format!("forget-{fid}")),
                                    Glyph::X,
                                    "Remove fact",
                                )
                                .on_click(cx.listener(
                                    move |s, _, _, cx| {
                                        s.issue(id, Command::RemoveFact { fact: fid });
                                        cx.notify()
                                    },
                                )),
                            ),
                    )
                    .into_any_element(),
            );
        }
        if !facts.is_empty() {
            knows = knows.child(plain_rows(facts));
        }
        if replaced > 0 {
            knows = knows.child(set::note(format!(
                "{} replaced with newer facts",
                count(replaced, "earlier fact")
            )));
        }

        // ── Sources ────────────────────────────────────────────
        let mut sources_rows = Vec::new();
        for (i, watch) in t.context_sources.iter().enumerate() {
            let kind = match watch.kind.as_str() {
                "topic" => "Topic",
                "flag" => "Feature flag",
                "insight" => "Insight",
                "event" => "Event",
                "channel" => "Channel",
                "repository" | "repo" => "Repository",
                "service" => "Service",
                other => other,
            };
            let glyph = match watch.kind.as_str() {
                "topic" => Glyph::AtSign,
                "flag" => Glyph::Flag,
                "insight" | "event" => Glyph::ChartColumn,
                "channel" => Glyph::Hash,
                _ => Glyph::Plug,
            };
            let source = watch.id;
            let key = watch.key.clone();
            sources_rows.push(
                list_row()
                    .id(SharedString::from(format!("context-source-{i}")))
                    .cursor_pointer()
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(
                            Page::Topic(id, Tab::Linked, Some(Detail::Linked(key.clone()))),
                            w,
                            cx,
                        )
                    }))
                    .group(format!("watch-{i}"))
                    .relative()
                    .py(px(10.))
                    .child(if watch.kind == "service" {
                        set::logo_tile()
                            .size(px(28.))
                            .child(meep_render::brands::logo(&watch.label, 15.))
                    } else {
                        set::tile()
                            .size(px(28.))
                            .child(ui::nav::glyph(glyph, false))
                    })
                    // Every source arrives through PostHog; the kind is enough.
                    .child(set::copy(watch.label.clone(), kind.to_owned()))
                    .child(
                        div()
                            .absolute()
                            .top_0()
                            .bottom_0()
                            .right(px(set::ROW_X - 4.))
                            .flex()
                            .items_center()
                            .opacity(0.)
                            .group_hover(format!("watch-{i}"), |s| s.opacity(1.))
                            .child(
                                ui::icon_button(
                                    SharedString::from(format!("unwatch-{i}")),
                                    Glyph::X,
                                    "Remove source",
                                )
                                .on_click(cx.listener(
                                    move |s, _, _, cx| {
                                        s.issue(id, Command::RemoveContextSource { source });
                                        cx.notify()
                                    },
                                )),
                            ),
                    )
                    .into_any_element(),
            );
        }
        sources_rows.push(
            list_row()
                .id("edit-watch")
                .role(Role::Button)
                .py(px(10.))
                .text_size(px(13.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .cursor_pointer()
                .hover(|s| {
                    s.bg(ui::ink(0x05))
                        .text_color(rgb(ui::theme::color(ui::INK)))
                })
                .child(
                    div()
                        .size(px(28.))
                        .flex_none()
                        .flex()
                        .items_center()
                        .justify_center()
                        .child(ui::nav::glyph(Glyph::Plus, false)),
                )
                .child("Add a source")
                .on_click(cx.listener(move |s, _, w, cx| {
                    s.ask_in_chat("Find and add this PostHog object: ", w, cx)
                }))
                .into_any_element(),
        );
        let works = ui::column().child(plain_rows(sources_rows));

        // ── Automation ───────────────────────────────────────────────────
        let mut rules = Vec::new();
        for rule in &t.rules {
            let rid = rule.id;
            rules.push(
                list_row()
                    .group(format!("rule-{rid}"))
                    .items_start()
                    .child(
                        div()
                            .mt(px(1.))
                            .text_color(tertiary())
                            .child(ui::nav::glyph(Glyph::ShieldCheck, false)),
                    )
                    .child(set::copy(
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
                    .child(
                        div()
                            .flex_none()
                            .opacity(0.)
                            .group_hover(format!("rule-{rid}"), |s| s.opacity(1.))
                            .child(
                                ui::icon_button(
                                    SharedString::from(format!("remove-{rid}")),
                                    Glyph::X,
                                    "Remove rule",
                                )
                                .on_click(cx.listener(
                                    move |s, _, _, cx| {
                                        s.issue(id, Command::RemoveRule { rule: rid });
                                        cx.notify()
                                    },
                                )),
                            ),
                    )
                    .into_any_element(),
            );
        }
        let stages = [(
            "check_facts",
            "Check facts",
            "Show changes that do not agree with the facts.",
            t.settings.check_facts,
        )]
        .into_iter()
        .map(|(key, name, description, enabled)| {
            list_row()
                .child(set::copy(name, description))
                .child(
                    Switch::new(format!("stage-{key}"))
                        .small()
                        .checked(enabled)
                        .accessibility_label(name)
                        .on_change(cx.listener(move |s, on: &bool, _, cx| {
                            s.issue(
                                id,
                                Command::SetTopicSetting {
                                    key: key.into(),
                                    enabled: *on,
                                },
                            );
                            cx.notify()
                        })),
                )
                .into_any_element()
        });
        // PostHog's own Scout reports, brought into this inbox.
        let feed = t.settings.scout_feed.clone();
        let scout = list_row()
            .child(set::copy(
                "PostHog Scout reports",
                match feed.as_deref() {
                    None => "Send PostHog Scout reports to this inbox.".to_owned(),
                    Some("") => "All Scout reports for this project go to this inbox.".to_owned(),
                    Some(term) => format!("Scout reports about “{term}” go to this inbox."),
                },
            ))
            .child(
                Switch::new("stage-scout-feed")
                    .small()
                    .checked(feed.is_some())
                    .accessibility_label("PostHog Scout reports")
                    .on_change(cx.listener(move |s, on: &bool, _, cx| {
                        s.issue(
                            id,
                            Command::SetScoutFeed {
                                feed: on.then(String::new),
                            },
                        );
                        cx.notify()
                    })),
            )
            .into_any_element();
        let stages = stages.chain(std::iter::once(scout));
        let acts = ui::column()
            .child(set::section(
                "Automation",
                "The checks that the agent does, and the rules that it obeys.",
                None,
                true,
            ))
            .child(plain_rows(stages))
            .child(
                div()
                    .pt(px(20.))
                    .pb(px(8.))
                    .text_size(px(12.))
                    .font_weight(FontWeight::MEDIUM)
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .child("Rules"),
            )
            .child(if rules.is_empty() {
                plain_rows([list_row()
                    .child(ui::caption(
                        "No rules. When you approve an action, you can make it a rule.",
                    ))
                    .into_any_element()])
            } else {
                plain_rows(rules)
            });

        let page = ui::column()
            .w_full()
            .max_w(px(720.))
            .pb(px(48.))
            .gap(px(12.));
        // Each part of the topic's context is its own page from the Overview.
        let page = match part {
            Tab::Mission => page
                .child(
                    ui::column()
                        .gap(px(4.))
                        .child(ui::caption("Mission"))
                        .child(mission),
                )
                .child(usage_section(state)),
            Tab::Goals => page.child(if metrics.is_empty() {
                ui::caption("No goals yet. Tell the agent in chat what success looks like.")
            } else {
                goal_grid(metrics)
            }),
            Tab::Facts => page.child(knows),
            Tab::Linked => page.child(works),
            _ => page.child(acts).children(self.removed_section(state, cx)),
        };
        div().w_full().flex().justify_center().child(page)
    }
    /// Facts and rules the person removed, each with a way back.
    fn removed_section(&self, state: &TopicState, cx: &Context<Self>) -> Option<Div> {
        let id = state.topic.id;
        let restore = |key: String, text: String, label: &'static str, command: Command| {
            context_row()
                .child(meep_shell::settings::copy(text, label))
                .child(control(key, "Restore", false, cx, move |s, _, _| {
                    s.issue(id, command.clone());
                }))
                .into_any_element()
        };
        let mut rows = Vec::new();
        for f in state.topic.facts.iter().filter(|f| {
            f.withdrawn_at.is_some() && f.superseded_by.is_none() && f.invalidated_by.is_none()
        }) {
            rows.push(restore(
                format!("restore-fact-{}", f.id),
                f.text.clone(),
                "Forgotten fact",
                Command::RestoreFact { fact: f.id },
            ));
        }
        for (&id, (_, _, rule)) in &state.removed_rules {
            rows.push(restore(
                format!("restore-rule-{id}"),
                rule.text.clone(),
                "Removed rule",
                Command::RestoreRule { rule: id },
            ));
        }
        (!rows.is_empty()).then(|| {
            ui::column()
                .child(meep_shell::settings::section(
                    "Recently removed",
                    "Restore items that you removed in error.",
                    None,
                    false,
                ))
                .child(meep_shell::settings::group(rows))
        })
    }
    /// Link to the evidence and display the service name recorded for its source.
    pub(super) fn fact_source(&self, state: &TopicState, f: &Fact, cx: &Context<Self>) -> Div {
        self.fact_meta(state, f, None, None, cx)
    }
    /// The fact's source as one line, with an optional warning lead and a
    /// trailing note, all joined by the same ` · ` separator.
    fn fact_meta(
        &self,
        state: &TopicState,
        f: &Fact,
        lead: Option<&str>,
        tail: Option<String>,
        cx: &Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let provenance = &f.provenance;
        let thread = provenance
            .thread
            .and_then(|id| state.threads.iter().find(|t| t.id == id));
        let message = thread.and_then(|t| {
            t.messages.iter().find(|m| {
                m.at == provenance.at
                    && m.author == provenance.author
                    && match &m.reply_target() {
                        Some(Source::Connection { connection, .. }) => {
                            connection == &provenance.via
                        }
                        Some(Source::Topic(_)) => provenance.via == "topic",
                        Some(Source::User) | None => false,
                    }
            })
        });
        let via = message
            .map(|m| {
                if let Some(Source::Connection {
                    connection,
                    channel,
                }) = &m.reply_target()
                    && let Some(watch) = state.topic.watches().find(|w| {
                        w.connection == *connection
                            && w.key == *channel
                            && matches!(w.kind.as_str(), "flag" | "insight" | "event")
                    })
                {
                    return watch.label.clone();
                }
                self.sender(&state.topic, m)
            })
            .unwrap_or_else(|| self.connection_label(&provenance.via).to_owned());
        let source = format!("{} · {via}", provenance.author);
        let parts: Vec<&str> = lead
            .into_iter()
            .chain([source.as_str()])
            .chain(tail.as_deref())
            .collect();
        let text = SharedString::from(parts.join(" · "));
        let highlights = lead
            .map(|l| {
                (
                    0..l.len(),
                    HighlightStyle {
                        color: Some(rgb(warning()).into()),
                        ..Default::default()
                    },
                )
            })
            .into_iter()
            .collect::<Vec<_>>();
        let text = ui::caption_style().child(StyledText::new(text).with_highlights(highlights));
        if let Some(t) = thread {
            let tab = thread_tab(t);
            let t = t.id;
            div().child(
                text.id(format!("provenance-{}", f.id))
                    .role(Role::Link)
                    .cursor_pointer()
                    .hover(|s| s.underline())
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(Page::Topic(id, tab, Some(Detail::Thread(t))), w, cx)
                    })),
            )
        } else {
            text
        }
    }
    pub(super) fn fetch_workflow(
        &mut self,
        id: TopicId,
        key: String,
        enabled: Option<bool>,
        w: &Window,
        cx: &mut Context<Self>,
    ) {
        let c = self.client().clone();
        if let Some(enabled) = enabled {
            if let Err(e) = c.set_workflow_enabled(id, &key, enabled) {
                self.fail(e);
            }
            cx.notify();
            return;
        }
        self.job(
            async move { c.refresh_workflow(id, &key).await },
            w,
            cx,
            |s, r, _, _| {
                if let Err(e) = r {
                    s.fail(e)
                }
            },
        )
    }
    fn routines(&self, state: &TopicState, w: &Window, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let workflows = || {
            state
                .topic
                .routines
                .iter()
                .filter(|r| r.binding.backend == "posthog")
        };
        if self.new_routine {
            return self.routine_page(w, cx);
        }
        if let Page::Topic(_, _, Some(Detail::Routine(key))) = &self.page
            && let Some(routine) = workflows().find(|r| &r.binding.id == key)
        {
            return self.routine_flow(id, routine, cx);
        }
        let mut list = ui::column().w_full().gap_0();
        if workflows().next().is_none() {
            return list.py(px(24.)).child(ui::caption("No routines yet."));
        }
        // A routine can't be healthy while the topic's connection is down.
        let waiting_on = self.needs.iter().find_map(|n| match n {
            NeedsYouItem::Problem {
                topics, connection, ..
            } if topics.contains(&id) => Some(self.connection_label(connection).to_owned()),
            _ => None,
        });
        for r in workflows() {
            let key = r.binding.id.clone();
            let info = self.client().cached_workflow(id, &key).ok().flatten();
            let off = !info.as_ref().map_or(r.enabled, |d| d.enabled);
            // An activation request waiting in Needs you outranks the routine's health.
            let awaiting = activation_request(state, &key);
            let (dot, status) = if awaiting.is_some() {
                (warning(), "Waiting for your approval".to_owned())
            } else if off {
                (ui::theme::color(ui::TERTIARY), "Off".to_owned())
            } else if let Some(service) = &waiting_on {
                (warning(), format!("Waiting on {service}"))
            } else {
                match r.health {
                    RoutineHealth::Ok => (ui::theme::color(ui::POSITIVE), "Healthy".to_owned()),
                    RoutineHealth::Unknown => (ui::theme::color(ui::TERTIARY), health(&r.health)),
                    RoutineHealth::Failing(_) => (warning(), "Needs attention".to_owned()),
                }
            };
            let name = div()
                .flex_1()
                .min_w_0()
                .truncate()
                .font_weight(FontWeight::MEDIUM)
                .child(r.binding.name.clone());
            // A dot carries where it stands; the switch lives on the routine itself.
            let dot = div()
                .id(format!("routine-status-{key}"))
                .aria_label(status.clone())
                .flex_none()
                .size(px(7.))
                .rounded_full()
                .bg(rgb(dot));
            let row = line(format!("routine-{key}"), false)
                .w_full()
                .gap(px(12.))
                .px(px(12.))
                .py(px(12.))
                .border_b_1()
                .border_color(ui::ink(16))
                .child(
                    ui::column()
                        .flex_1()
                        .min_w_0()
                        .gap(px(3.))
                        .child(name)
                        .child(ui::caption(routine_caption(info.as_ref(), r)).truncate()),
                )
                .child(dot)
                .child(ui::caption(status))
                .child(ui::nav::glyph(Glyph::ChevronRight, false));
            list = list.child(row.on_click(cx.listener(move |s, _, w, cx| {
                s.go(
                    Page::Topic(id, Tab::Routines, Some(Detail::Routine(key.clone()))),
                    w,
                    cx,
                )
            })));
        }
        list
    }

    /// A routine page's bar: "Routines › name", when it runs, and its quiet
    /// tools (open in PostHog, delete).
    pub(super) fn routine_bar(&self, id: TopicId, r: &RoutineInfo, cx: &Context<Self>) -> Div {
        let key = r.binding.id.clone();
        let details = self.client().cached_workflow(id, &key).ok().flatten();
        let mut tools: Vec<AnyElement> = vec![];
        if let Some(url) = details.as_ref().and_then(|d| d.url.clone()) {
            tools.push(
                ui::icon_button("open-workflow", Glyph::ExternalLink, "Open in PostHog")
                    .tooltip("Open in PostHog")
                    .on_click(move |_, _, cx| cx.open_url(&url))
                    .into_any_element(),
            );
        }
        if let Ok(flow) = Uuid::parse_str(&r.binding.external_id) {
            let routine = key.clone();
            tools.push(
                ui::icon_button("delete-routine", Glyph::Trash, "Delete routine")
                    .tooltip("Delete routine")
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.open_sheet(Sheet::DeleteRoutine(id, routine.clone(), flow), w, cx)
                    }))
                    .into_any_element(),
            );
        }
        crumb_bar(
            topic_crumbs(
                id,
                &self
                    .states
                    .iter()
                    .find(|s| s.topic.id == id)
                    .map(|s| s.topic.name.clone())
                    .unwrap_or_default(),
                Tab::Routines,
                Some((None, r.binding.name.clone())),
                cx,
            ),
            Some(trigger_text(details.as_ref(), r)),
            tools,
        )
    }
    fn routine_flow(&self, id: TopicId, r: &RoutineInfo, cx: &Context<Self>) -> Div {
        let key = r.binding.id.clone();
        let awaiting = self
            .states
            .iter()
            .find(|s| s.topic.id == id)
            .and_then(|s| activation_request(s, &key));
        let details = self.client().cached_workflow(id, &key).ok().flatten();
        let source_only = details.as_ref().and_then(|d| d.manual_run_allowed) == Some(false);
        let run = key.clone();
        // One switch says whether it runs; Run now tries it once either way the
        // workflow allows. Both sit with the title they act on.
        let mut actions = ui::row().flex_wrap().items_center().min_w_0().gap(px(8.));
        if let Some(d) = &details {
            let toggle = key.clone();
            actions = actions.child(
                ui::row()
                    .gap(px(8.))
                    .pr(px(4.))
                    .child(ui::caption(if d.enabled { "On" } else { "Off" }))
                    .child(
                        Switch::new("enable-routine")
                            .small()
                            .accessibility_label(format!("Turn {} on", r.binding.name))
                            .checked(d.enabled)
                            .color(rgb(ui::theme::color(ui::INK)))
                            .on_change(cx.listener(move |s, on: &bool, w, cx| {
                                s.fetch_workflow(id, toggle.clone(), Some(*on), w, cx)
                            })),
                    ),
            );
        }
        actions = actions.child(
            control("run-now", "Run now", false, cx, move |s, _, _| {
                s.issue(
                    id,
                    Command::StartRoutine {
                        routine: run.clone(),
                        variables: Default::default(),
                    },
                );
            })
            .icon(Glyph::Play)
            .disabled(
                source_only
                    || r.uncertain_manual_run.is_some()
                    || details.as_ref().is_some_and(|d| !d.enabled)
                    || matches!(r.health, RoutineHealth::Failing(_)),
            ),
        );
        if source_only {
            actions = actions.child(ui::caption("Runs when a watched source changes."));
        }
        if details.is_none() && r.binding.backend == "posthog" {
            let load = key.clone();
            actions = actions.child(control(
                "load-workflow",
                "Load workflow details",
                false,
                cx,
                move |s, w, cx| s.fetch_workflow(id, load.clone(), None, w, cx),
            ));
        }
        // The bar above names the routine and when it runs. Here: its controls
        // first, then what is wrong with it, if anything. The switch says on or
        // off, so only an unloaded routine is marked.
        let head = ui::row()
            .items_center()
            .flex_wrap()
            .gap(px(12.))
            .child(actions)
            .when(details.is_none(), |row| {
                row.child(
                    div()
                        .flex_none()
                        .px(px(7.))
                        .py(px(1.))
                        .rounded(px(6.))
                        .text_size(px(11.))
                        .font_weight(FontWeight::MEDIUM)
                        .bg(ui::ink(0x0b))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .child("Not loaded"),
                )
            })
            .when(matches!(r.health, RoutineHealth::Failing(_)), |row| {
                row.child(
                    ui::caption(health(&r.health))
                        .id("routine-health-warning")
                        .w_full()
                        .min_w_0()
                        .whitespace_normal()
                        .text_color(rgb(warning())),
                )
            });
        let head = match awaiting {
            Some(task) => ui::column().gap(px(12.)).child(head).child(
                ui::row()
                    .gap(px(10.))
                    .px(px(12.))
                    .py(px(9.))
                    .rounded(px(8.))
                    .bg(rgb(warning()).opacity(0.07))
                    .child(
                        div()
                            .flex_1()
                            .child("Turning this on is waiting for your approval."),
                    )
                    .child(control(
                        "review-activation",
                        "Review",
                        true,
                        cx,
                        move |s, w, cx| {
                            s.go(Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))), w, cx)
                        },
                    )),
            ),
            None => ui::column().child(head),
        };
        let head = if let Some(expected) = r.uncertain_manual_run {
            let routine = key.clone();
            head.child(
                ui::row().w_full().flex_wrap().gap(px(8.))
                    .child(ui::caption("A run may have started. Check PostHog before acknowledging or running it again.").w_full().min_w_0().whitespace_normal().text_color(rgb(warning())))
                    .child(control("acknowledge-routine-run", "I checked PostHog", false, cx, move |s, _, _| {
                        s.issue(id, Command::AcknowledgeRoutineDispatch { routine: routine.clone(), expected });
                    })),
            )
        } else {
            head
        };
        let Some(d) = details else {
            return ui::column()
                .gap(px(18.))
                .child(head)
                .child(ui::caption("Loading the workflow from PostHog…"));
        };
        // Last seven days, flow-wide, as one ruled strip.
        let stat = |value: String, label: &'static str, first: bool| {
            ui::column()
                .flex_1()
                .min_w(px(96.))
                .gap(px(2.))
                .px(px(14.))
                .py(px(10.))
                .when(!first, |c| c.border_l_1().border_color(ui::ink(0x0f)))
                .child(
                    div()
                        .text_size(px(15.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(value),
                )
                .child(ui::caption(label))
        };
        let week = d.week.unwrap_or_default();
        let total = week.succeeded + week.failed;
        let stats = ui::row()
            .flex_wrap()
            .rounded(px(10.))
            .border_1()
            .border_color(ui::ink(0x0f))
            .child(stat(total.to_string(), "Outcomes this week", true))
            .child(stat(
                if total == 0 {
                    "–".into()
                } else {
                    format!("{:.0}%", 100. * week.succeeded as f64 / total as f64)
                },
                "Successful outcomes",
                false,
            ))
            .child(
                stat(week.failed.to_string(), "Failed outcomes", false)
                    .when(week.failed > 0, |c| c.text_color(rgb(warning()))),
            )
            .child(stat(
                r.last_run
                    .map(|t| super::pages::ago(Utc::now() - t))
                    .unwrap_or_else(|| "Never".into()),
                "Last run",
                false,
            ));
        // The flow, step by step, on one vertical rail. A split's rail runs on
        // as a trunk past its paths; each path hangs off it at an elbow, under
        // its condition.
        const NODE: f32 = 28.;
        const STEP: f32 = 34.;
        let rule = ui::ink(0x24);
        let mut flow = ui::column().gap_0();
        // An exit only restates that a path ends; the rail already shows it.
        let graph: Vec<_> = d.graph.iter().filter(|s| s.kind != "exit").collect();
        // Whether the split at `level` still has a path to come below row `i`.
        let more_paths = |i: usize, level: usize| {
            graph[i + 1..]
                .iter()
                .take_while(|s| usize::from(s.depth) > level)
                .any(|s| usize::from(s.depth) == level + 1 && s.branch.is_some())
        };
        // The guides left of a row: one trunk per open split, and for a path's
        // condition, the elbow that joins it to its split.
        let guides = |i: usize, depth: usize, elbow: bool| {
            let mut g = div().relative().flex_none().w(px(STEP * depth as f32));
            for level in 0..depth {
                let x = STEP * level as f32 + NODE / 2. - 0.75;
                let more = more_paths(i, level);
                if elbow && level + 1 == depth {
                    // ├ while more paths follow; a rounded └ for the last one.
                    g = if more {
                        g.child(
                            div()
                                .absolute()
                                .left(px(x))
                                .top_0()
                                .bottom_0()
                                .w(px(1.5))
                                .bg(rule),
                        )
                        .child(
                            div()
                                .absolute()
                                .left(px(x))
                                .right_0()
                                .top(relative(0.5))
                                .h(px(1.5))
                                .bg(rule),
                        )
                    } else {
                        g.child(
                            div()
                                .absolute()
                                .left(px(x))
                                .right_0()
                                .top_0()
                                .h(relative(0.5))
                                .mb(px(-1.5))
                                .border_l(px(1.5))
                                .border_b(px(1.5))
                                .border_color(rule)
                                .rounded_bl(px(8.)),
                        )
                    };
                } else if more {
                    g = g.child(
                        div()
                            .absolute()
                            .left(px(x))
                            .top_0()
                            .bottom_0()
                            .w(px(1.5))
                            .bg(rule),
                    );
                }
            }
            g
        };
        for (i, step) in graph.iter().enumerate() {
            let step = *step;
            let glyph = match step.kind.as_str() {
                "trigger" => Glyph::Zap,
                "delay" => Glyph::Clock,
                "wait_until_condition" | "wait_until_time_window" => Glyph::Hourglass,
                "conditional_branch" => Glyph::GitBranch,
                "random_cohort_branch" => Glyph::Shuffle,
                "function_email" => Glyph::Mail,
                "function_sms" | "function_push" => Glyph::Send,
                "function" => Glyph::Webhook,
                "exit" => Glyph::LogOut,
                _ => Glyph::Workflow,
            };
            if let Some(label) = &step.branch {
                // The split this path leaves from: the nearest step above, one level up.
                let conditional = graph[..i]
                    .iter()
                    .rev()
                    .find(|s| s.depth < step.depth)
                    .is_some_and(|s| s.kind == "conditional_branch");
                let otherwise = label == "Otherwise";
                let first_path = graph[i - 1].depth < step.depth;
                // An unnamed condition arrives as "Condition 3": it says
                // which, not what, so it reads quieter than a named one.
                let unnamed = label
                    .strip_prefix("Condition ")
                    .is_some_and(|n| n.parse::<u32>().is_ok());
                let label = if unnamed {
                    label.to_lowercase()
                } else {
                    label.clone()
                };
                flow = flow.child(
                    ui::row()
                        .gap_0()
                        .items_stretch()
                        .child(guides(i, step.depth.into(), true))
                        .child(
                            // Paths after the first stand a little apart, so each
                            // reads as one group with its condition.
                            div()
                                .relative()
                                .pt(px(if first_path { 2. } else { 10. }))
                                .pb(px(6.))
                                // A short stub from the condition into its first step.
                                .child(
                                    div()
                                        .absolute()
                                        .left(px(NODE / 2. - 0.75))
                                        .bottom_0()
                                        .h(px(6.))
                                        .w(px(1.5))
                                        .bg(rule),
                                )
                                .child(
                                    ui::row()
                                        .h(px(24.))
                                        .px(px(9.))
                                        .gap(px(5.))
                                        .rounded_full()
                                        .border_1()
                                        .border_color(ui::ink(0x14))
                                        // The fallback path is outlined only; real
                                        // conditions carry a fill.
                                        .bg(if otherwise {
                                            rgb(ui::theme::color(ui::CANVAS))
                                        } else {
                                            ui::ink(0x06)
                                        })
                                        .text_size(px(12.))
                                        .when(conditional && !otherwise, |r| {
                                            r.child(
                                                div()
                                                    .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                                    .child("If"),
                                            )
                                        })
                                        .child(
                                            div()
                                                .font_weight(FontWeight::MEDIUM)
                                                .text_color(rgb(ui::theme::color(
                                                    if otherwise || unnamed {
                                                        ui::SECONDARY
                                                    } else {
                                                        ui::INK
                                                    },
                                                )))
                                                .child(label),
                                        ),
                                ),
                        ),
                );
            }
            // The rail runs on to the next step on this path, or, from a
            // split, into its first path.
            let last = graph.get(i + 1).is_none_or(|next| {
                next.depth < step.depth || (next.branch.is_some() && next.depth == step.depth)
            });
            let trigger = step.kind == "trigger";
            let split = graph.get(i + 1).is_some_and(|next| next.depth > step.depth);
            // A split's own sentence ("Split into 4 paths…") is what the
            // tree below it already shows.
            let detail = if trigger {
                Some(trigger_text(Some(&d), r))
            } else if split {
                None
            } else {
                step.detail.clone()
            }
            .filter(|d| *d != step.name);
            let exit = step.kind == "exit";
            // Every step runs as often as the flow; only failures are worth a mark.
            let counts = step.counts.filter(|c| c.failed > 0).map(|c| {
                ui::row()
                    .flex_none()
                    .gap(px(4.))
                    .child(
                        Icon::new(Glyph::CircleX)
                            .size(px(12.))
                            .text_color(rgb(warning())),
                    )
                    .child(ui::caption(format!("{} failed", c.failed)).text_color(rgb(warning())))
            });
            flow = flow.child(
                ui::row()
                    .gap_0()
                    .items_stretch()
                    .child(guides(i, step.depth.into(), false))
                    .child(
                        ui::row()
                            .flex_1()
                            .min_w_0()
                            .items_stretch()
                            .gap(px(12.))
                            .child(
                                // The rail: node on top, line down to the next step.
                                ui::column()
                                    .w(px(NODE))
                                    .flex_none()
                                    .items_center()
                                    .child(
                                        div()
                                            .size(px(NODE))
                                            .rounded(px(8.))
                                            .flex()
                                            .items_center()
                                            .justify_center()
                                            .border_1()
                                            .border_color(ui::ink(0x12))
                                            .bg(rgb(ui::theme::color(ui::CANVAS)))
                                            .child(Icon::new(glyph).size(px(14.)).text_color(rgb(
                                                ui::theme::color(if trigger {
                                                    ui::INK
                                                } else {
                                                    ui::SECONDARY
                                                }),
                                            ))),
                                    )
                                    .when(!last, |c| {
                                        c.child(
                                            div()
                                                .w(px(1.5))
                                                .flex_1()
                                                .min_h(px(if split { 2. } else { 12. }))
                                                .bg(rule),
                                        )
                                    }),
                            )
                            .child(
                                ui::row()
                                    .flex_1()
                                    .min_w_0()
                                    .items_start()
                                    .gap(px(12.))
                                    .pb(px(if last {
                                        4.
                                    } else if split {
                                        6.
                                    } else {
                                        16.
                                    }))
                                    .child(
                                        ui::column()
                                            .flex_1()
                                            .min_w_0()
                                            .gap(px(1.))
                                            .pt(px(4.))
                                            .child(
                                                div()
                                                    .font_weight(if exit {
                                                        FontWeight::NORMAL
                                                    } else {
                                                        FontWeight::MEDIUM
                                                    })
                                                    .text_color(rgb(ui::theme::color(if exit {
                                                        ui::SECONDARY
                                                    } else {
                                                        ui::INK
                                                    })))
                                                    .child(step.name.clone()),
                                            )
                                            // Failures sit beside the step they belong
                                            // to, not across the page from it.
                                            .when(detail.is_some() || counts.is_some(), |c| {
                                                c.child(
                                                    ui::row()
                                                        .gap(px(8.))
                                                        .children(detail.map(ui::caption))
                                                        .children(counts),
                                                )
                                            }),
                                    ),
                            ),
                    ),
            );
        }
        if d.graph.is_empty() {
            flow = flow.child(ui::caption("This workflow has no steps yet."));
        }
        // Recent runs.
        let mut runs = ui::column().gap_0();
        for run in d.run_history.iter().take(6) {
            let (label, color) = (run_label(&run.status), run_color(&run.status));
            runs = runs.child(
                ui::row()
                    .items_start()
                    .gap(px(10.))
                    .py(px(9.))
                    .border_b_1()
                    .border_color(ui::ink(0x0d))
                    .child(
                        div()
                            .mt(px(5.))
                            .size(px(7.))
                            .rounded_full()
                            .flex_none()
                            .bg(rgb(color)),
                    )
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .gap(px(1.))
                            .child(
                                div().child(run.result.clone().unwrap_or_else(|| label.to_owned())),
                            )
                            .child(ui::caption(format!(
                                "{label}{}{}",
                                run.at
                                    .map(|t| format!(
                                        " · {}",
                                        t.with_timezone(&chrono::Local).format("%b %e, %H:%M")
                                    ))
                                    .unwrap_or_default(),
                                run.duration_ms
                                    .map(|ms| format!(" · {:.1}s", ms as f64 / 1000.))
                                    .unwrap_or_default()
                            ))),
                    ),
            );
        }
        if d.run_history.is_empty() {
            runs = runs.child(ui::caption("No runs yet."));
        }
        routine_panel(head)
            .child(stats)
            .child(routine_section("Flow", flow))
            .when(!r.observations.is_empty(), |c| {
                c.child(routine_section("Recent events", events(r)))
            })
            .child(routine_section("Recent runs", runs))
    }
}

/// The newest source events a routine handled, with their outcome.
fn events(r: &RoutineInfo) -> Div {
    let now = Utc::now();
    let mut list = ui::column().gap(px(8.));
    for o in r.observations.iter().rev().take(8) {
        let who = if o.origin.author.is_empty() {
            o.origin.channel.clone()
        } else {
            o.origin.author.clone()
        };
        list = list.child(
            ui::column()
                .gap(px(1.))
                .child(div().text_size(px(13.)).child(outcome_text(&o.outcome)))
                .child(ui::caption(format!("{who} · {}", ago(now - o.at)))),
        );
    }
    list
}
pub(super) fn health(h: &RoutineHealth) -> String {
    match h {
        RoutineHealth::Ok => "Healthy".into(),
        RoutineHealth::Unknown => "Not checked".into(),
        RoutineHealth::Failing(e) => e.clone(),
    }
}

/// A topic screen's list: plain rows on the page with a hairline between them, the
/// same on every screen.
fn plain_rows(rows: impl IntoIterator<Item = AnyElement>) -> Div {
    let mut list = ui::column().w_full();
    for (n, row) in rows.into_iter().enumerate() {
        if n > 0 {
            list = list.child(div().h(px(1.)).flex_none().bg(ui::ink(0x0d)));
        }
        list = list.child(row);
    }
    list
}

/// Goal cards, two to a row.
fn goal_grid(cards: Vec<AnyElement>) -> Div {
    let mut grid = ui::column().w_full().gap(px(12.));
    let mut cards = cards.into_iter().peekable();
    while cards.peek().is_some() {
        let mut row = ui::row().w_full().items_stretch().gap(px(12.));
        for _ in 0..2 {
            row = row.child(div().flex_1().min_w_0().flex().children(cards.next()));
        }
        grid = grid.child(row);
    }
    grid
}

/// One goal as a card: what kind it is and whether it is on track, what it is, the
/// number that matters, and its bar.
fn goal_card(id: TopicId, g: &meep_topic::Goal, cx: &Context<Desktop>) -> AnyElement {
    use super::overview::{goal_measure, goal_on_track, goal_track};
    let (_, ratio, band) = goal_measure(g);
    let (kind, value, context) = match &g.progress {
        Some(Progress::Target {
            current,
            target,
            unit,
        }) => (
            "Target",
            format!("{current}"),
            format!("of {target} {unit}"),
        ),
        Some(Progress::Guardrail {
            current,
            low,
            high,
            unit,
        }) => (
            "Guardrail",
            format!("{current} {unit}"),
            format!("keep within {low}–{high}"),
        ),
        None => ("Goal", "—".to_owned(), "Not measured yet".to_owned()),
    };
    let measured = ratio.is_some();
    let on_track = goal_on_track(g);
    let (status, tone) = if !measured {
        ("No data", ui::theme::color(ui::TERTIARY))
    } else if on_track {
        ("On track", ui::theme::color(ui::POSITIVE))
    } else {
        ("Off track", ui::theme::color(0xc2610c))
    };
    let gid = g.id;
    ui::column()
        .id(SharedString::from(format!("goal-{gid}")))
        .flex_1()
        .min_w_0()
        .gap(px(14.))
        .p(px(16.))
        .rounded(px(12.))
        .border_1()
        .border_color(ui::ink(0x0e))
        .cursor_pointer()
        .hover(|s| s.bg(ui::ink(0x04)))
        .on_click(cx.listener(move |s, _, w, cx| {
            s.go(Page::Topic(id, Tab::Goals, Some(Detail::Goal(gid))), w, cx)
        }))
        .child(
            ui::row()
                .gap(px(8.))
                .child(ui::caption(kind).flex_1())
                .child(
                    ui::row()
                        .gap(px(5.))
                        .text_size(px(12.))
                        .text_color(rgb(tone))
                        .child(div().size(px(6.)).rounded_full().bg(rgb(tone)))
                        .child(status),
                ),
        )
        .child(
            div()
                .text_size(px(15.))
                .font_weight(FontWeight::SEMIBOLD)
                .line_height(relative(1.35))
                .line_clamp(2)
                .min_h(px(40.))
                .child(g.text.clone()),
        )
        .child(
            ui::row()
                .items_end()
                .gap(px(6.))
                .child(
                    div()
                        .text_size(px(26.))
                        .line_height(px(30.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_color(if measured {
                            rgb(ui::theme::color(ui::INK))
                        } else {
                            rgb(ui::theme::color(ui::TERTIARY))
                        })
                        .child(value),
                )
                .child(
                    div()
                        .pb(px(3.))
                        .text_size(px(13.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .truncate()
                        .child(context),
                ),
        )
        .child(
            goal_track(ratio, band, 0.)
                .w_full()
                .h(px(6.))
                .rounded(px(3.)),
        )
        .into_any_element()
}
