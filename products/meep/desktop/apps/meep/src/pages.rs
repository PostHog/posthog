use super::*;
use chrono::Utc;
use meep_ui::gpui_kit::component::{
    Disableable, Icon, Sizable, button::ButtonVariants as _, switch::Switch,
};
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
    pub task: Option<TaskId>,
    pub version: Option<u64>,
    pub since: Option<chrono::DateTime<Utc>>,
    pub retry: bool,
}

pub(super) struct AttentionGroup {
    pub latest: Attention,
    pub earlier: Vec<Attention>,
}

pub(super) fn attention_rank(kind: &str) -> u8 {
    match kind {
        "Problem" => 0,
        "Failed" => 1,
        "Question" => 2,
        "Approve" => 3,
        "Assigned" => 4,
        _ => 5,
    }
}

pub(super) fn attention_word(kind: &str) -> &'static str {
    match kind {
        "Problem" => "broken connection",
        "Failed" => "failed run",
        "Question" => "question",
        "Approve" => "approval",
        "Assigned" => "task for you",
        _ => "decision",
    }
}

pub(super) fn attention_section(kind: &str) -> &'static str {
    match kind {
        "Problem" => "Broken connections",
        "Failed" => "Failed runs",
        "Question" => "Questions",
        "Approve" => "Approvals",
        "Assigned" => "Assigned to you",
        _ => "Decisions",
    }
}

pub(super) fn attention_tally(groups: &[AttentionGroup]) -> String {
    let mut tally: Vec<(&'static str, usize)> = vec![];
    for g in groups {
        match tally.iter_mut().find(|t| t.0 == g.latest.kind) {
            Some(t) => t.1 += 1,
            None => tally.push((g.latest.kind, 1)),
        }
    }
    tally.sort_by_key(|(kind, _)| attention_rank(kind));
    tally
        .iter()
        .map(|(kind, n)| match (*n, attention_word(kind)) {
            (1, word) => format!("1 {word}"),
            (n, "task for you") => format!("{n} tasks for you"),
            (n, word) => format!("{n} {word}s"),
        })
        .collect::<Vec<_>>()
        .join(" · ")
}

pub(super) fn attention_groups(needs: &[NeedsYouItem], state: &TopicState) -> Vec<AttentionGroup> {
    let mut groups: Vec<AttentionGroup> = vec![];
    for a in needs.iter().filter_map(|n| attention(n, state)) {
        let same = |g: &&mut AttentionGroup| {
            a.task.is_some()
                && g.latest.task.is_some()
                && g.latest.kind == a.kind
                && g.latest.title.trim().eq_ignore_ascii_case(a.title.trim())
        };
        if let Some(g) = groups.iter_mut().find(|g| same(g)) {
            if a.since > g.latest.since {
                let older = std::mem::replace(&mut g.latest, a);
                g.earlier.push(older);
            } else {
                g.earlier.push(a);
            }
            g.earlier.sort_by_key(|e| std::cmp::Reverse(e.since));
        } else {
            groups.push(AttentionGroup {
                latest: a,
                earlier: vec![],
            });
        }
    }
    groups.sort_by_key(|g| attention_rank(g.latest.kind));
    groups
}

#[derive(Clone, Debug, PartialEq)]
pub(super) enum AttentionStep {
    Open(Page),
    Reconnect(String),
    Retry(TaskId, u64),
    Resolve(TaskId, u64),
}

pub(super) fn attention_plan(
    kind: &str,
    retry: bool,
    page: &Page,
    attempts: &[(TaskId, u64)],
    dismiss: bool,
) -> Vec<AttentionStep> {
    let resolve = |list: &[(TaskId, u64)]| {
        list.iter()
            .map(|&(task, version)| AttentionStep::Resolve(task, version))
            .collect::<Vec<_>>()
    };
    match (kind, attempts.first()) {
        ("Problem", _) => match page {
            Page::Topic(_, _, Some(Detail::Problem(connection))) => {
                vec![AttentionStep::Reconnect(connection.clone())]
            }
            _ => vec![AttentionStep::Open(page.clone())],
        },
        ("Failed", Some(_)) if dismiss => resolve(attempts),
        ("Failed", Some(&(task, version))) if retry => {
            let mut plan = vec![AttentionStep::Retry(task, version)];
            plan.extend(resolve(&attempts[1..]));
            plan
        }
        ("Approve" | "Assigned", Some(&(task, version))) => {
            vec![AttentionStep::Resolve(task, version)]
        }
        _ => vec![AttentionStep::Open(page.clone())],
    }
}

pub(super) fn failure_reason(raw: &str) -> String {
    let lower = raw.to_lowercase();
    let words: Vec<&str> = lower
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|w| !w.is_empty())
        .collect();
    let code = |c: &str| words.contains(&c);
    let has = |phrase: &str| lower.contains(phrase);
    let known = if code("402") || has("payment required") || has("billing") || has("credit balance")
    {
        Some("Model billing limit reached.")
    } else if code("401") || code("403") || has("unauthorized") || has("invalid api key") {
        Some("The model provider rejected the credentials.")
    } else if code("429") || has("rate limit") {
        Some("Rate limited by the model provider.")
    } else if has("timed out") || has("timeout") {
        Some("The run took too long and stopped.")
    } else if code("500") || code("502") || code("503") || code("529") || has("overloaded") {
        Some("Temporary model provider error.")
    } else {
        None
    };
    if let Some(known) = known {
        return known.to_owned();
    }
    let line = raw
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .unwrap_or_default();
    let line = match line.split_once(": ") {
        Some((head, rest)) if head.contains('_') && !head.contains(' ') => rest,
        _ => line,
    };
    if line.is_empty() {
        "The run stopped before it finished.".to_owned()
    } else {
        line.to_owned()
    }
}

/// The "you're done here" state: a hedgehog bobbing on a pool float, and two
/// lines on what would land here. Needs you and a skipped-only inbox both use it.
fn all_clear(line: &'static str, reduced: bool) -> Div {
    const W: f32 = 240.;
    const HOG: f32 = 112.;
    const WATER: f32 = 104.;
    const H: f32 = WATER + 24.;
    const BEAT: std::time::Duration = std::time::Duration::from_millis(3600);
    let wave = |x: f32, y: f32, w: f32, phase: f32| {
        let at = move |el: Div, t: f32| {
            let swell = (t * std::f32::consts::TAU).sin();
            el.left(px(x + swell * 4.))
                .opacity(0.55 + 0.45 * swell.abs())
        };
        let el = div()
            .absolute()
            .top(px(y))
            .w(px(w))
            .h(px(2.))
            .rounded_full()
            .bg(ui::ink(0x30));
        if reduced {
            at(el, phase).into_any_element()
        } else {
            el.with_animation(
                SharedString::from(format!("all-clear-wave-{x}")),
                Animation::new(BEAT).repeat(),
                move |el, t| at(el, (t + phase) % 1.),
            )
            .into_any_element()
        }
    };
    let hog = super::topic_icon::bob(
        "all-clear-float",
        super::topic_icon::hero("float", HOG)
            .absolute()
            .left(px((W - HOG) / 2.))
            .top(px(WATER - HOG * 0.8)),
        reduced,
    );
    ui::column()
        .w_full()
        .items_center()
        .pt(px(64.))
        .pb(px(40.))
        .child(
            div()
                .relative()
                .flex_none()
                .w(px(W))
                .h(px(H))
                .child(
                    div()
                        .absolute()
                        .left(px((W - 120.) / 2.))
                        .top(px(WATER - 6.))
                        .w(px(120.))
                        .h(px(12.))
                        .rounded_full()
                        .shadow(vec![BoxShadow {
                            color: rgba(0x00000022).into(),
                            offset: point(px(0.), px(0.)),
                            blur_radius: px(14.),
                            spread_radius: px(2.),
                            inset: false,
                        }]),
                )
                .child(wave(28., WATER - 10., 26., 0.))
                .child(wave(48., WATER + 6., 16., 0.35))
                .child(wave(W - 56., WATER - 4., 28., 0.6))
                .child(wave(W - 74., WATER + 12., 14., 0.15))
                .child(hog),
        )
        .child(
            div()
                .pt(px(12.))
                .text_size(px(15.))
                .font_weight(FontWeight::SEMIBOLD)
                .child("Nothing needs you"),
        )
        .child(
            div()
                .pt(px(6.))
                .text_center()
                .text_size(px(12.))
                .line_height(px(17.))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .child(div().child(line)),
        )
}
/// What kind of thing waits on you, as an icon on a tinted tile: a choice, a
/// question, an approval, a run that failed, a broken connection.
pub(super) fn attention_glyph(kind: &str) -> (Glyph, u32, &'static str) {
    match kind {
        "Decide" => (Glyph::GitBranch, UNREAD, "Decision"),
        "Question" => (Glyph::MessageCircle, UNREAD, "Question"),
        "Approve" => (Glyph::ShieldCheck, ui::POSITIVE, "Approval"),
        "Assigned" => (
            Glyph::CircleUser,
            ui::theme::color(ui::SECONDARY),
            "Assigned to you",
        ),
        "Problem" => (Glyph::Plug, warning(), "Broken connection"),
        _ => (Glyph::TriangleAlert, warning(), "Failed run"),
    }
}

pub(super) fn kind_tile(kind: &str) -> Stateful<Div> {
    let (glyph, tone, name) = attention_glyph(kind);
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
    } else if matches!(&thread.state, ThreadState::NeedsYou { suggestions, .. } if suggestions.iter().any(|s| matches!(s, Suggestion::LinkRepository { .. })))
    {
        Tab::Sources
    } else if thread.key.starts_with("file-review/") {
        Tab::Files
    } else if thread.is_topic_chat() && !thread.key.starts_with("fact-review/") {
        Tab::Chat
    } else {
        Tab::Facts
    }
}
pub(super) fn attention(n: &NeedsYouItem, state: &TopicState) -> Option<Attention> {
    let id = state.topic.id;
    match n {
        NeedsYouItem::Decide {
            topic,
            thread,
            title,
            detail,
        } if *topic == id => {
            let found = state
                .threads
                .iter()
                .find(|item| item.id.to_string() == *thread);
            Some(Attention {
                kind: "Decide",
                title: title.clone(),
                detail: detail.clone(),
                page: Page::Topic(
                    id,
                    found.map_or(Tab::Facts, thread_tab),
                    Some(Detail::Thread(thread.parse().ok()?)),
                ),
                action: "Decide".into(),
                task: None,
                version: None,
                since: found.map(message_time),
                retry: false,
            })
        }
        NeedsYouItem::Approve {
            topic,
            task,
            title,
            detail,
            action,
        } if *topic == id => {
            let task_id: TaskId = task.parse().ok()?;
            let t = state.tasks.iter().find(|t| t.id == task_id);
            let in_chat = t.is_some_and(|t| t.is_session());
            let failed = t.is_some_and(|t| {
                !t.is_session()
                    && t.column == Column::NeedsYou
                    && t.input_question.is_none()
                    && t.action.is_none()
                    && !t.review_before_start
                    && t.assignment.as_ref() != Some(&InboxAssignment::Human)
                    && t.result.is_some()
            });
            let routine =
                t.is_some_and(|t| matches!(t.assignment, Some(InboxAssignment::Routine(_))));
            let question =
                t.is_some_and(|t| t.input_question.is_some()) || action.as_deref() == Some("Reply");
            let genuine = t.is_some_and(|t| t.action.is_some() || t.review_before_start) || in_chat;
            let (kind, detail, action) = if failed {
                (
                    "Failed",
                    failure_reason(t.and_then(|t| t.result.as_deref()).unwrap_or(detail)),
                    if routine { "See why" } else { "Try again" }.to_owned(),
                )
            } else if question {
                ("Question", detail.clone(), "Reply".to_owned())
            } else if genuine {
                let detail = if !detail.trim().is_empty() {
                    detail.clone()
                } else if t.is_some_and(|t| t.review_before_start) {
                    "Starts once you approve.".to_owned()
                } else {
                    "Waiting for your approval.".to_owned()
                };
                (
                    "Approve",
                    detail,
                    action.clone().unwrap_or_else(|| "Approve".into()),
                )
            } else {
                ("Assigned", detail.clone(), "Mark done".to_owned())
            };
            Some(Attention {
                kind,
                title: title.clone(),
                detail,
                page: if in_chat {
                    Page::Topic(id, Tab::Chat, None)
                } else {
                    Page::Topic(id, Tab::Tasks, Some(Detail::Task(task_id)))
                },
                action,
                task: Some(task_id),
                version: t.map(|t| t.review_version),
                since: t.map(|t| t.updated_at),
                retry: failed && !routine,
            })
        }
        NeedsYouItem::Problem {
            topics,
            connection,
            title,
            detail,
        } if topics.contains(&id) => Some(Attention {
            kind: "Problem",
            title: title.clone(),
            detail: detail.clone(),
            page: Page::Topic(id, Tab::Routines, Some(Detail::Problem(connection.clone()))),
            action: "Reconnect".into(),
            task: None,
            version: None,
            since: None,
            retry: false,
        }),
        _ => None,
    }
}
/// Opening the inspector marks a thread seen. Its displayed date follows the conversation.
pub(super) fn message_time(t: &Thread) -> chrono::DateTime<Utc> {
    t.messages.last().map_or(t.created_at, |message| message.at)
}
/// The inbox's reports in reading order: open ones by priority (P0 first)
/// then newest, then the ones the person resolved or dismissed, newest first.
/// Scout findings that have not become inbox reports yet.
pub(super) fn unopened_findings(state: &TopicState) -> Vec<(uuid::Uuid, &meep_topic::ScoutReport)> {
    let mut findings: Vec<_> = state
        .scouts
        .iter()
        .flat_map(|scout| scout.reports.iter().map(move |r| (scout.id, r)))
        .filter(|(_, r)| {
            !state.threads.iter().any(|t| {
                t.report_sources
                    .as_ref()
                    .and_then(|s| s.external.as_ref())
                    .is_some_and(|e| e.id == r.id.to_string())
            })
        })
        .collect();
    findings.sort_by_key(|(_, r)| std::cmp::Reverse(r.filed_at));
    findings
}
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
/// What starts a routine: the topic's own schedule wording when PostHog only
/// says it runs on a schedule, otherwise PostHog's trigger.
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
const ATTENTION_HEADING_HEIGHT: f32 = 30.;
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
        const MEASURE: f32 = 680.;
        let mut items: Vec<(Option<(&TopicState, usize)>, AnyElement)> = vec![];
        for (i, item) in self.needs.iter().enumerate() {
            if let NeedsYouItem::Problem {
                topics,
                connection,
                title,
                detail,
            } = item
            {
                tally_one("Problem");
                items.push((
                    None,
                    self.problem_card(i, topics, connection, title, detail, cx)
                        .into_any_element(),
                ));
            }
        }
        for state in &self.states {
            let id = state.topic.id;
            // Connection problems are listed once, above the topics they affect.
            let needs: Vec<NeedsYouItem> = self
                .needs
                .iter()
                .filter(|n| !matches!(n, NeedsYouItem::Problem { .. }))
                .cloned()
                .collect();
            let rows = attention_groups(&needs, state);
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
            let heading = self.attention_heading(state, waiting, false, cx);
            // A topic's items sit together on one card under its name.
            let mut section = ui::column().gap_0().flex_none().mx(px(-12.));
            for (i, group) in rows.iter().enumerate() {
                tally_one(group.latest.kind);
                section =
                    section.child(self.attention_row(id, &format!("{id}-{i}"), group, i == 0, cx));
            }
            if let Some(task) = approved {
                showed_approval = true;
                section = section.child(self.after_approval(state, task, cx))
            }
            items.push((
                Some((state, waiting)),
                ui::column()
                    .gap_0()
                    .child(heading)
                    .child(section)
                    .into_any_element(),
            ));
        }
        // "1 failed run · 3 decisions · across 3 topics": what is broken first.
        tally.sort_by_key(|(kind, _)| attention_rank(kind));
        let mut parts: Vec<String> = tally
            .iter()
            .map(|(kind, n)| match (*n, attention_word(kind)) {
                (n, "task for you") if n > 1 => format!("{n} tasks for you"),
                (n, word) => count(n, word),
            })
            .collect();
        if topics > 1 {
            parts.push(format!("across {}", count(topics, "topic")));
        }
        let summary = parts.join(" · ");
        if n == 0 && !showed_approval {
            items.push((
                None,
                all_clear("Your topics are working on their own.", cx.reduce_motion())
                    .into_any_element(),
            ))
        }
        let measure = || ui::column().w_full().max_w(px(MEASURE)).mx_auto();
        let list = &self.attention_scroll;
        let viewport = list.bounds().top();
        let offset = list.offset().y.max(-list.max_offset().y);
        let current = (0..items.len()).rev().find(|&i| {
            list.bounds_for_item(i)
                .is_some_and(|b| b.top() + offset < viewport)
        });
        let stuck = current.and_then(|i| {
            let (state, waiting) = items[i].0?;
            let own = list.bounds_for_item(i)?;
            let limit = list
                .bounds_for_item(i + 1)
                .map_or(own.bottom(), |next| next.top())
                + offset;
            (limit > viewport).then(|| {
                let push = (limit - viewport - px(ATTENTION_HEADING_HEIGHT)).min(px(0.));
                div()
                    .absolute()
                    .top(push)
                    .left_0()
                    .right_0()
                    .block_mouse_except_scroll()
                    .bg(rgb(ui::theme::color(ui::CANVAS)))
                    .child(
                        measure()
                            .border_b_1()
                            .border_color(ui::ink(0x0f))
                            .child(self.attention_heading(state, waiting, true, cx)),
                    )
            })
        });
        ui::column()
            .size_full()
            .child(
                measure().flex_none().pb(px(12.)).child(
                    meep_shell::settings::header(
                        "Needs you",
                        if n > 0 {
                            summary
                        } else {
                            "Decisions, approvals and fixes from all your topics.".to_owned()
                        },
                        None,
                    )
                    .pb_0(),
                ),
            )
            .child(
                ui::column()
                    .relative()
                    .flex_1()
                    .min_h_0()
                    .child(
                        scroll("attention-items")
                            .track_scroll(list)
                            .w_full()
                            .gap(px(20.))
                            .pt(px(8.))
                            .pb(px(40.))
                            .children(items.into_iter().map(|(_, item)| {
                                div().w_full().flex_none().child(measure().child(item))
                            })),
                    )
                    .children(stuck),
            )
    }
    fn attention_heading(
        &self,
        state: &TopicState,
        waiting: usize,
        stuck: bool,
        cx: &Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let link = if stuck {
            format!("attention-topic-stuck-{id}")
        } else {
            format!("attention-topic-{id}")
        };
        let group = SharedString::from(format!("{link}-group"));
        ui::row()
            .h(px(ATTENTION_HEADING_HEIGHT))
            .flex_none()
            .pb(px(6.))
            .child(
                ui::row()
                    .id(SharedString::from(link))
                    .group(group.clone())
                    .role(Role::Link)
                    .aria_label(format!("Open {}", state.topic.name))
                    .min_w_0()
                    .gap(px(10.))
                    .cursor_pointer()
                    .child(
                        super::topic_icon::small_sidebar_tile(&state.topic.display_icon(), 20.)
                            .ml(px(-2.)),
                    )
                    .child(
                        div()
                            .min_w_0()
                            .truncate()
                            .font_weight(FontWeight::SEMIBOLD)
                            .child(state.topic.name.clone()),
                    )
                    .child(
                        div()
                            .flex_none()
                            .text_size(px(12.))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child(waiting.to_string()),
                    )
                    .child(
                        div()
                            .flex_none()
                            .ml(px(-4.))
                            .opacity(0.)
                            .group_hover(group, |s| s.opacity(1.))
                            .child(
                                Icon::new(Glyph::ChevronRight)
                                    .size(px(12.))
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                            ),
                    )
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(Page::Topic(id, Tab::Chat, None), w, cx)
                    })),
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
        let overlay = ui::motion::pane(
            "topic-overview-overlay",
            self.overview_overlay && !self.overview_docked(w),
            w,
            cx,
        );
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
        tools.extend(self.show_overview_button(w, cx));
        let tab_in = ui::motion::arrival(
            ElementId::from(SharedString::from(match tab {
                Tab::Files => format!(
                    "tab-{id}-Files-{}",
                    self.files_stacked(w) && self.shown_file(state).is_some()
                ),
                _ => format!("tab-{id}-{tab:?}-{detail:?}"),
            })),
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
        } else if let Some(split) = (tab == Tab::Files)
            .then(|| self.files_split(state, w, cx))
            .flatten()
        {
            split.into_any_element()
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
                        .pt(px(super::details::PAGE_TOP - if routine.is_some() { 8. } else { 0. }))
                        .pb(px(12.))
                        .child({
                            let content = match (tab, detail) {
                                (Tab::Routines | Tab::Inbox, Some(Detail::Scout(key))) => {
                                    self.scout_page(state, *key, tab == Tab::Inbox)
                                }
                                (_, Some(Detail::Goal(g))) => self.goal_page(state, *g, cx),
                                (_, Some(Detail::Source(k))) => self.source_page(state, k, cx),
                                _ => match tab {
                                    Tab::Chat | Tab::Inbox => self.inbox(state, w, cx),
                                    Tab::Needs => self.topic_needs(state, cx),
                                    Tab::Tasks => self.tasks_page(state, w, cx),
                                    Tab::Files => self.data_page(state, cx),
                                    Tab::Routines => self.routines(state, w, cx),
                                    Tab::Mission
                                    | Tab::Goals
                                    | Tab::Facts
                                    | Tab::Sources
                                    | Tab::Rules => self.context_page(state, tab, w, cx),
                                },
                            };
                            let content = if detail.is_none() && matches!(tab, Tab::Needs | Tab::Tasks | Tab::Inbox | Tab::Files) {
                                let (title, about) = match tab {
                                    Tab::Needs => ("Needs you", "Decisions, approvals and fixes for this topic."),
                                    Tab::Tasks => ("Tasks", "Work the agent runs for this topic. Open a task to see its run."),
                                    Tab::Files => ("Files", "Files the agent made and files you added to this topic."),
                                    _ => ("Inbox", "Reports and requests for this topic. Open one to act on it."),
                                };
                                ui::column()
                                    .w_full()
                                    .gap_0()
                                    .child(meep_shell::settings::header(title, about, None))
                                    .child(content)
                            } else {
                                content
                            };
                            let content = if matches!(tab, Tab::Facts | Tab::Files) {
                                ui::column()
                                    .w_full()
                                    .gap_0()
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
        let talks = task.is_none()
            && !(tab == Tab::Chat && detail.is_none())
            && !(tab == Tab::Needs && detail.is_none())
            && !self.new_routine;
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
        let file = (tab == Tab::Files)
            .then(|| self.shown_file(state))
            .flatten();
        let header = (!own_header).then(|| {
            let current = match detail {
                Some(Detail::Scout(id)) => state.scouts.iter().find(|s| s.id == *id).map(|s| {
                    let title = if tab == Tab::Inbox {
                        s.reports
                            .first()
                            .map_or_else(|| s.name.clone(), |r| r.title.clone())
                    } else {
                        s.name.clone()
                    };
                    (
                        Some(ui::nav::glyph(Glyph::Binoculars, false).into_any_element()),
                        title,
                    )
                }),
                Some(Detail::Goal(g)) => topic.goals.iter().find(|x| x.id == *g).map(|x| {
                    (
                        Some(ui::nav::glyph(Glyph::Target, false).into_any_element()),
                        x.text.clone(),
                    )
                }),
                Some(Detail::Source(key)) => topic
                    .context_sources
                    .iter()
                    .find(|x| x.key == *key)
                    .map(|x| (None, x.label.clone())),
                _ => file
                    .as_ref()
                    .map(|path| (None, path.rsplit('/').next().unwrap_or(path).to_owned())),
            };
            crumb_bar(
                topic_crumbs(
                    id,
                    &topic.name,
                    Some(&topic.display_icon()),
                    tab,
                    current,
                    cx,
                ),
                file.as_ref().map(|path| self.file_meta(state, path)),
                file.as_ref()
                    .map(|path| self.file_tools(state, path, !self.files_stacked(w), cx))
                    .unwrap_or_default()
                    .into_iter()
                    .chain(tools),
            )
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
            .when(overlay.should_render(), |c| {
                c.child(super::navigation::side_overlay(
                    super::overview::WIDTH,
                    overlay.progress,
                    self.overview(state, cx),
                ))
            })
    }
    /// The width the topic's own pane gets beside the sidebar and the Overview.
    pub(super) fn topic_pane_width(&self, w: &Window) -> Pixels {
        let (rail, overview) = self.pane_target.get();
        w.viewport_size().width
            - px(super::navigation::TOPIC_SIDEBAR_WIDTH * rail)
            - px((super::overview::WIDTH + meep_shell::GUTTER) * overview)
    }
    /// The topic's own Needs you: its decisions, approvals and problems.
    fn topic_needs(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let groups = attention_groups(&self.needs, state);
        if groups.is_empty() {
            return all_clear("This topic is working on its own.", cx.reduce_motion());
        }
        let mut page = ui::column().w_full().gap(px(20.)).pt(px(4.)).pb(px(40.));
        let mut start = 0;
        while start < groups.len() {
            let kind = groups[start].latest.kind;
            let end = groups[start..]
                .iter()
                .position(|g| g.latest.kind != kind)
                .map_or(groups.len(), |n| start + n);
            let mut rows = ui::column().gap_0().mx(px(-12.));
            for (n, group) in groups[start..end].iter().enumerate() {
                rows = rows.child(self.attention_row(
                    id,
                    &format!("{id}-{}", start + n),
                    group,
                    n == 0,
                    cx,
                ));
            }
            page = page.child(
                ui::column()
                    .gap_0()
                    .child(
                        ui::row()
                            .gap(px(6.))
                            .pb(px(2.))
                            .text_size(px(12.))
                            .child(
                                div()
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                    .child(attention_section(kind)),
                            )
                            .child(
                                div()
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                    .child((end - start).to_string()),
                            ),
                    )
                    .child(rows),
            );
            start = end;
        }
        page
    }
    fn inbox(&self, state: &TopicState, w: &Window, cx: &Context<Self>) -> Div {
        // These match the fixed two-line rows and section headings below. Keep
        // spacers at the same height so the shared scroll handle stays stable.
        const ROW_HEIGHT: f32 = 56.;
        const OVERSCAN: f32 = 300.;
        let all = ordered_threads(state, true);
        let findings = unopened_findings(state);
        let finding_rows = |list: Div| {
            let topic = state.topic.id;
            findings.iter().fold(list, |list, (scout, report)| {
                let scout = *scout;
                let age = Utc::now() - report.filed_at;
                list.child(
                    ui::row()
                        .id(SharedString::from(format!("finding-row-{}", report.id)))
                        .role(Role::Button)
                        .h(px(ROW_HEIGHT))
                        .w_full()
                        .gap(px(12.))
                        .items_center()
                        .cursor_pointer()
                        .child(ui::nav::glyph(Glyph::Inbox, false))
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .truncate()
                                .child(report.title.clone()),
                        )
                        .child(ui::caption(ago(age)))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(
                                Page::Topic(topic, Tab::Inbox, Some(Detail::Scout(scout))),
                                w,
                                cx,
                            )
                        })),
                )
            })
        };
        if all.is_empty() && !findings.is_empty() {
            return finding_rows(
                ui::column()
                    .w_full()
                    .max_w(px(960.))
                    .mx_auto()
                    .gap_0()
                    .pt(px(4.)),
            );
        }
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
                control("inbox-sources", "Add source", false, cx, move |s, w, cx| {
                    s.ask_in_chat("Find and add this PostHog object: ", w, cx)
                })
                .mt(px(16.))
                .self_center(),
            );
        }
        let id = state.topic.id;
        let mut list = finding_rows(
            ui::column()
                .w_full()
                .max_w(px(960.))
                .mx_auto()
                .gap_0()
                .pt(px(4.)),
        );
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
        let closed_fold = format!("inbox-closed-{id}");
        let mut rows: [Vec<AnyElement>; 2] = [vec![], vec![]];
        let any_priority = all
            .iter()
            .any(|t| t.report_sources.as_ref().and_then(|r| r.priority).is_some());
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
                        .on_click(cx.listener(move |s, _, _, cx| {
                            s.skipped = !s.skipped;
                            s.folds.toggled(format!("inbox-closed-{id}"), s.skipped, cx);
                            cx.notify()
                        })),
                );
                if self.folds.progress(&closed_fold, self.skipped, cx) <= 0. {
                    break;
                }
            }
            let row_y = index as f32 * ROW_HEIGHT;
            if virtualize && index < open && (row_y + ROW_HEIGHT < low || row_y > high) {
                skipped_height += ROW_HEIGHT;
                continue;
            }
            if skipped_height > 0. {
                rows[usize::from(index >= open)]
                    .push(div().h(px(skipped_height)).flex_none().into_any_element());
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
            rows[usize::from(index >= open)].push(
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
                    .when(any_priority, |row| {
                        row.child(
                            div()
                                .id(format!("priority-{}", t.id))
                                .child(priority_badge(priority, is_open)),
                        )
                    })
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
                    .on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx)))
                    .into_any_element(),
            );
        }
        if skipped_height > 0. {
            rows[usize::from(closed > 0)]
                .push(div().h(px(skipped_height)).flex_none().into_any_element());
        }
        let [open_rows, closed_rows] = rows;
        let mut list = list.children(open_rows);
        if !closed_rows.is_empty() {
            list = list.children(self.folds.reveal(&closed_fold, self.skipped, cx, || {
                ui::column()
                    .gap_0()
                    .children(closed_rows)
                    .into_any_element()
            }));
        }
        list
    }
    pub(super) fn review_links(&self, state: &TopicState, tab: Tab, cx: &Context<Self>) -> Div {
        let prefix = match tab {
            Tab::Facts => "fact-review/",
            Tab::Files => "file-review/",
            _ => return div(),
        };
        let topic = state.topic.id;
        let mut reviews = ui::column().gap(px(8.));
        let mut any = false;
        for thread in state.threads.iter().filter(|thread| {
            thread.key.starts_with(prefix)
                && !state.archived_threads.contains(&thread.id)
                && matches!(thread.state, ThreadState::NeedsYou { .. })
        }) {
            let id = thread.id;
            any = true;
            reviews = reviews.child(control(
                format!("review-{id}"),
                format!("Review: {}", short_subject(&thread.subject)),
                false,
                cx,
                move |s, w, cx| s.go(Page::Topic(topic, tab, Some(Detail::Thread(id))), w, cx),
            ));
        }
        reviews.when(any, |r| r.pb(px(16.)))
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
    /// acts: one Settings-style page for each part, in one centred column.
    fn context_page(&self, state: &TopicState, part: Tab, _w: &Window, cx: &Context<Self>) -> Div {
        let page = ui::column().w_full().max_w(px(720.)).pb(px(48.));
        let page = match part {
            Tab::Mission => page.child(self.mission_page(state, cx)),
            Tab::Goals => page.child(self.goals_page(state, cx)),
            Tab::Facts => page.child(self.facts_page(state, cx)),
            Tab::Sources => page.child(self.sources_page(&state.topic, cx)),
            _ => page.child(self.rules_page(state, cx)),
        };
        div().w_full().flex().justify_center().child(page)
    }
    /// Link to the evidence and display the service name recorded for its source.
    pub(super) fn fact_source(&self, state: &TopicState, f: &Fact, cx: &Context<Self>) -> Div {
        self.fact_meta(state, f, None, None, cx)
    }
    /// The fact's source as one line, with an optional warning lead and a
    /// trailing note, all joined by the same ` · ` separator.
    pub(super) fn fact_meta(
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
        use super::topic_pages::{chevron, empty_group, glyph_tile, nav_row};
        use meep_shell::settings::{self as set, Tone};
        let head = set::header(
            "Routines",
            "Scouts watch for changes. Routines run on a schedule or an event.",
            Some(
                control("bind", "New routine", false, cx, |s, w, cx| {
                    s.compose_routine(w, cx)
                })
                .into_any_element(),
            ),
        );
        let page = ui::column().w_full().max_w(px(720.)).mx_auto().pb(px(48.));
        if workflows().next().is_none() && state.scouts.is_empty() {
            return page.child(head).child(empty_group(
                "No scouts or routines yet",
                "Ask in chat to watch for a change, or add a routine.",
            ));
        }
        let mut page = page.child(head);
        if !state.scouts.is_empty() {
            page = page
                .child(set::section("Scouts", "", None, true))
                .child(set::group(state.scouts.iter().map(|scout| {
                    let key = scout.id;
                    nav_row(format!("scout-{key}"))
                        .aria_label(SharedString::from(scout.name.clone()))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(
                                Page::Topic(id, Tab::Routines, Some(Detail::Scout(key))),
                                w,
                                cx,
                            )
                        }))
                        .child(glyph_tile(Glyph::Binoculars))
                        .child(set::copy(scout.name.clone(), "Scout"))
                        .child(if scout.enabled {
                            set::status("On", Tone::Positive)
                        } else {
                            set::status("Off", Tone::Neutral)
                        })
                        .child(chevron())
                        .into_any_element()
                })));
        }
        // A routine can't be healthy while the topic's connection is down.
        let waiting_on = self.needs.iter().find_map(|n| match n {
            NeedsYouItem::Problem {
                topics, connection, ..
            } if topics.contains(&id) => Some(self.connection_label(connection).to_owned()),
            _ => None,
        });
        let mut rows = Vec::new();
        for r in workflows() {
            let key = r.binding.id.clone();
            let info = self.client().cached_workflow(id, &key).ok().flatten();
            let off = !info.as_ref().map_or(r.enabled, |d| d.enabled);
            // An activation request waiting in Needs you outranks the routine's health.
            let awaiting = activation_request(state, &key);
            let (tone, status) = if awaiting.is_some() {
                (Tone::Warning, "Waiting for your approval".to_owned())
            } else if off {
                (Tone::Neutral, "Off".to_owned())
            } else if let Some(service) = &waiting_on {
                (Tone::Warning, format!("Waiting on {service}"))
            } else {
                match r.health {
                    RoutineHealth::Ok => (Tone::Positive, "Healthy".to_owned()),
                    RoutineHealth::Unknown => (Tone::Neutral, health(&r.health)),
                    RoutineHealth::Failing(_) => (Tone::Warning, "Needs attention".to_owned()),
                }
            };
            rows.push(
                nav_row(format!("routine-{key}"))
                    .aria_label(SharedString::from(r.binding.name.clone()))
                    .child(glyph_tile(Glyph::Repeat))
                    .child(set::copy(
                        r.binding.name.clone(),
                        routine_caption(info.as_ref(), r),
                    ))
                    .child(
                        div()
                            .id(SharedString::from(format!("routine-status-{key}")))
                            .aria_label(SharedString::from(status.clone()))
                            .child(set::status(status, tone)),
                    )
                    .child(chevron())
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(
                            Page::Topic(id, Tab::Routines, Some(Detail::Routine(key.clone()))),
                            w,
                            cx,
                        )
                    }))
                    .into_any_element(),
            );
        }
        if !rows.is_empty() {
            page = page
                .child(set::section("Routines", "", None, state.scouts.is_empty()))
                .child(set::group(rows));
        }
        page
    }

    fn scout_page(&self, state: &TopicState, id: Uuid, as_report: bool) -> Div {
        let page = ui::column().w_full().gap(px(16.));
        let Some(scout) = state.scouts.iter().find(|scout| scout.id == id) else {
            return page.child(ui::caption("This scout is no longer linked to this topic."));
        };
        let heading = ui::row()
            .items_start()
            .gap(px(12.))
            .child(if as_report {
                ui::column()
                    .flex_1()
                    .min_w_0()
                    .gap(px(6.))
                    .child(super::details::item_title(
                        "Report",
                        scout
                            .reports
                            .first()
                            .map_or_else(|| scout.name.clone(), |r| r.title.clone()),
                    ))
            } else {
                ui::column()
                    .flex_1()
                    .min_w_0()
                    .gap(px(6.))
                    .child(super::details::item_title_with(
                        "Scout",
                        scout.name.clone(),
                        meep_shell::settings::status(
                            if scout.enabled { "On" } else { "Off" },
                            if scout.enabled {
                                meep_shell::settings::Tone::Positive
                            } else {
                                meep_shell::settings::Tone::Neutral
                            },
                        )
                        .text_size(px(12.)),
                    ))
            })
            .children(
                self.identity
                    .as_ref()
                    .filter(|_| !as_report)
                    .map(|identity| {
                        let url = identity.inbox_url("scouts", &scout.skill_name);
                        ui::icon_button("open-scout", Glyph::ExternalLink, "Open scout in PostHog")
                            .tooltip("Open scout in PostHog")
                            .on_click(move |_, _, cx| cx.open_url(url.as_str()))
                    }),
            );
        let mut page = page.child(heading);
        if scout.reports.is_empty() {
            return page.child(ui::caption("No findings yet."));
        }
        if !as_report {
            page = page.child(
                meep_shell::settings::section("Recent findings", "", None, false).mb(px(-10.)),
            );
        }
        for report in &scout.reports {
            page = page.child(
                ui::column()
                    .gap(px(5.))
                    .child(
                        ui::row()
                            .gap(px(8.))
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .font_weight(FontWeight::MEDIUM)
                                    .child(report.title.clone()),
                            )
                            .child(ui::caption(ago(chrono::Utc::now() - report.filed_at)))
                            .children(self.identity.as_ref().map(|identity| {
                                let url = identity.inbox_url("reports", &report.id.to_string());
                                ui::icon_button(
                                    format!("open-report-{}", report.id),
                                    Glyph::ExternalLink,
                                    "Open report in PostHog",
                                )
                                .tooltip("Open report in PostHog")
                                .on_click(move |_, _, cx| cx.open_url(url.as_str()))
                            })),
                    )
                    .child(meep_shell::transcript::chat_markdown(
                        format!("scout-finding-{}", report.id).into(),
                        report.summary.clone(),
                    )),
            );
        }
        page
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
        let topic = self
            .states
            .iter()
            .find(|s| s.topic.id == id)
            .map(|s| &s.topic);
        crumb_bar(
            topic_crumbs(
                id,
                topic.map_or("", |topic| topic.name.as_str()),
                topic.map(Topic::display_icon).as_ref(),
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
            .when_some(
                if source_only {
                    Some("This routine runs only from its trigger.")
                } else if r.uncertain_manual_run.is_some() {
                    Some("The last manual run may still be going.")
                } else if details.as_ref().is_some_and(|d| !d.enabled) {
                    Some("Turn the routine on to run it.")
                } else if matches!(r.health, RoutineHealth::Failing(_)) {
                    Some("Fix the routine before you run it.")
                } else {
                    None
                },
                |b, why| b.disabled(true).tooltip(why),
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
        let head = ui::column()
            .gap(px(14.))
            .child(super::details::item_title(
                "Routine",
                r.binding.name.clone(),
            ))
            .child(head);
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
            .child(stat(total.to_string(), "Runs this week", true))
            .child(stat(
                if total == 0 {
                    "–".into()
                } else {
                    format!("{:.0}%", 100. * week.succeeded as f64 / total as f64)
                },
                "Success rate",
                false,
            ))
            .child(
                stat(
                    if total == 0 {
                        "–".into()
                    } else {
                        week.failed.to_string()
                    },
                    "Failed",
                    false,
                )
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

impl Desktop {
    fn act_on_attention(
        &mut self,
        topic: TopicId,
        plan: Vec<AttentionStep>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        for step in plan {
            match step {
                AttentionStep::Open(page) => self.go(page, w, cx),
                AttentionStep::Reconnect(connection) => {
                    self.issue(topic, Command::Reconnect { connection });
                }
                AttentionStep::Retry(task, version) => {
                    if !self.issue(
                        topic,
                        Command::SendBack {
                            task,
                            expected_review: Some(version),
                            note: String::new(),
                        },
                    ) {
                        return;
                    }
                }
                AttentionStep::Resolve(task, version) => self.approve(topic, task, version, None),
            }
        }
    }

    pub(super) fn needs_count(&self) -> usize {
        let problems = self
            .needs
            .iter()
            .filter(|n| matches!(n, NeedsYouItem::Problem { .. }))
            .count();
        let rest: Vec<NeedsYouItem> = self
            .needs
            .iter()
            .filter(|n| !matches!(n, NeedsYouItem::Problem { .. }))
            .cloned()
            .collect();
        problems
            + self
                .states
                .iter()
                .map(|state| attention_groups(&rest, state).len())
                .sum::<usize>()
    }

    pub(super) fn attention_row(
        &self,
        topic: TopicId,
        key: &str,
        group: &AttentionGroup,
        first: bool,
        cx: &Context<Self>,
    ) -> Stateful<Div> {
        let a = &group.latest;
        let kind = a.kind;
        let retry = a.retry;
        let page = a.page.clone();
        let attempts: std::sync::Arc<Vec<(TaskId, u64)>> = std::sync::Arc::new(
            std::iter::once(a)
                .chain(&group.earlier)
                .filter_map(|e| Some((e.task?, e.version?)))
                .collect(),
        );
        let (glyph, tone, name) = attention_glyph(kind);
        let quiet = rgb(ui::theme::color(ui::TERTIARY));
        let primary = {
            let page = page.clone();
            let attempts = attempts.clone();
            control(
                format!("attention-act-{key}"),
                a.action.clone(),
                false,
                cx,
                move |s, w, cx| {
                    let plan = attention_plan(kind, retry, &page, &attempts, false);
                    s.act_on_attention(topic, plan, w, cx)
                },
            )
            .min_w(px(84.))
        };
        let secondary = match kind {
            "Failed" if retry => Some("Dismiss"),
            "Approve" | "Assigned" => Some("Review"),
            _ => None,
        }
        .map(|label| {
            let page = page.clone();
            let attempts = attempts.clone();
            ui::button(SharedString::from(format!("attention-alt-{key}")), label)
                .h(px(28.))
                .px(px(10.))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .on_click(cx.listener(move |s, _, w, cx| {
                    cx.stop_propagation();
                    if label == "Dismiss" {
                        let plan = attention_plan(kind, retry, &page, &attempts, true);
                        s.act_on_attention(topic, plan, w, cx)
                    } else {
                        s.go(page.clone(), w, cx)
                    }
                    cx.notify()
                }))
        });
        let detail = plain_line(
            a.detail
                .split("\n\n")
                .find(|p| !p.trim().is_empty())
                .unwrap_or_default(),
        );
        let mut lead = !detail.is_empty();
        let mut meta = ui::row()
            .flex_wrap()
            .gap_x(px(6.))
            .text_size(px(13.))
            .line_height(relative(1.45))
            .text_color(quiet)
            .when(lead, |m| {
                m.child(
                    div()
                        .min_w_0()
                        .line_clamp(2)
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .child(detail),
                )
            });
        if let Some(at) = a.since {
            let waited = Utc::now() - at;
            if lead {
                meta = meta.child("·");
            }
            lead = true;
            meta = meta.child(
                div()
                    .when(waited > chrono::Duration::days(1), |d| {
                        d.text_color(rgb(warning()))
                    })
                    .child(ago(waited)),
            );
        }
        if kind == "Failed" || !group.earlier.is_empty() {
            let tries = group.earlier.len() + 1;
            let mut runs: Vec<&Attention> = group.earlier.iter().collect();
            runs.reverse();
            runs.push(a);
            if lead {
                meta = meta.child("·");
            }
            if tries > 1 {
                meta = meta
                    .child(if tries == 2 {
                        "Tried twice".to_owned()
                    } else {
                        format!("Tried {tries} times")
                    })
                    .child("·");
            }
            meta = meta.child(if tries == 1 { "Run" } else { "Runs" });
            for (n, run) in runs.into_iter().enumerate() {
                let dest = run.page.clone();
                let when = run
                    .since
                    .map(|at| at.with_timezone(&chrono::Local).format("%H:%M").to_string())
                    .unwrap_or_else(|| format!("{}", n + 1));
                meta = meta.child(
                    Button::new(SharedString::from(format!("attention-run-{key}-{n}")))
                        .ghost()
                        .h(px(18.))
                        .px(px(3.))
                        .mx(px(-3.))
                        .rounded(px(4.))
                        .role(Role::Link)
                        .accessibility_label(format!("Open run from {when}"))
                        .child(
                            div()
                                .text_size(px(13.))
                                .underline()
                                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                .child(when),
                        )
                        .on_click(cx.listener(move |s, _, w, cx| {
                            cx.stop_propagation();
                            s.go(dest.clone(), w, cx)
                        })),
                );
            }
        }
        line(format!("attention-row-{key}"), false)
            .items_start()
            .px(px(12.))
            .py(px(9.))
            .gap(px(12.))
            .rounded(px(8.))
            .when(!first, |r| r.mt(px(2.)))
            .child(
                div()
                    .id(SharedString::from(format!("attention-kind-{key}")))
                    .aria_label(name)
                    .flex_none()
                    .mt(px(2.))
                    .child(Icon::new(glyph).size(px(16.)).text_color(rgb(tone))),
            )
            .child(
                ui::column()
                    .flex_1()
                    .min_w_0()
                    .gap(px(2.))
                    .child(
                        div()
                            .min_w_0()
                            .text_size(px(14.))
                            .line_height(relative(1.35))
                            .font_weight(FontWeight::MEDIUM)
                            .line_clamp(2)
                            .child(short_subject(&a.title)),
                    )
                    .child(meta),
            )
            .child(
                ui::row()
                    .flex_none()
                    .self_center()
                    .gap(px(4.))
                    .children(secondary)
                    .child(primary),
            )
            .on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::prelude::v1::test;

    #[test]
    fn needs_you_separates_failures_questions_and_approvals_and_folds_retries() {
        let at = chrono::DateTime::parse_from_rfc3339("2026-01-05T10:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let id = TopicId(Uuid::new_v4());
        let mut state = TopicState::new(Topic::new(id, "Brief", at));
        let mut add = |title: &str, minutes: i64, shape: &dyn Fn(&mut meep_topic::Task)| {
            let task = TaskId(Uuid::new_v4());
            state.add_task(task, title, Actor::Agent, None, at).unwrap();
            let t = state.tasks.iter_mut().find(|t| t.id == task).unwrap();
            t.column = Column::NeedsYou;
            t.updated_at = at + chrono::Duration::minutes(minutes);
            shape(t);
            task
        };
        let failed =
            |t: &mut meep_topic::Task| t.result = Some("agent_error: API Error: 402".into());
        let first = add("Make the checklist", 1, &failed);
        let second = add("Make the checklist", 9, &failed);
        add("Confirm the time zone", 5, &|t| {
            t.input_question = Some("Berlin or New York?".into())
        });
        add("Book the room", 3, &|t| t.review_before_start = true);
        let needs = meep_wire::NeedsYou::from_states([&state], std::iter::empty()).items;
        let groups = attention_groups(&needs, &state);
        let shown: Vec<_> = groups
            .iter()
            .map(|g| {
                (
                    g.latest.kind,
                    g.latest.title.as_str(),
                    g.latest.detail.as_str(),
                    g.latest.action.as_str(),
                    g.earlier.len(),
                )
            })
            .collect();
        assert_eq!(
            shown,
            [
                (
                    "Failed",
                    "Make the checklist",
                    "Model billing limit reached.",
                    "Try again",
                    1
                ),
                (
                    "Question",
                    "Confirm the time zone",
                    "Berlin or New York?",
                    "Reply",
                    0
                ),
                (
                    "Approve",
                    "Book the room",
                    "Starts once you approve.",
                    "Approve start",
                    0
                ),
            ]
        );
        assert_eq!(groups[0].latest.task, Some(second));
        let page = groups[0].latest.page.clone();
        let attempts = [(second, 0), (first, 0)];
        assert_eq!(
            attention_plan("Failed", true, &page, &attempts, false),
            [
                AttentionStep::Retry(second, 0),
                AttentionStep::Resolve(first, 0)
            ]
        );
        assert_eq!(
            attention_plan("Failed", true, &page, &attempts, true),
            [
                AttentionStep::Resolve(second, 0),
                AttentionStep::Resolve(first, 0)
            ]
        );
        assert_eq!(
            attention_tally(&groups),
            "1 failed run · 1 question · 1 approval"
        );
    }
}
