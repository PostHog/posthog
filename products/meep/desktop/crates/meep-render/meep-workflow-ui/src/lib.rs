//! A workflow read as an outline of what it does and how its last run went.
//!
//! The definition is the executable AST; this is a reading of it, not a second
//! source of truth. Four rules keep large workflows short without hiding what
//! matters:
//! 1. recovery wrappers (`try`) become a mark on the steps they protect, and a
//!    wrapper around the whole workflow becomes one line about failure;
//! 2. one-sided conditions become a tag on the steps they guard;
//! 3. data steps (`command`, `expression`) fold into a count, shown on request;
//! 4. loops say how much they did, and consecutive saves merge into one row.
//!
//! Groups nest one level: parallel branches are one row each, and anything
//! deeper flattens into its nearest group with counts.
use meep_ui::{
    components as ui, controls,
    gpui_kit::{self, assets::IconName as Glyph, component::*, prelude::FluentBuilder, *},
    settings,
};
#[cfg(all(feature = "editor", not(target_family = "wasm")))]
pub mod editor;
mod model;
use model::model;
mod outline;
#[cfg(all(feature = "editor", not(target_family = "wasm")))]
mod rhai_format;
#[cfg(all(feature = "editor", not(target_family = "wasm")))]
mod workflow_form;
use serde_json::Value;
#[cfg(test)]
use serde_json::json;
use ui::{CANVAS as PAPER, INK};

use std::rc::Rc;
#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
#[cfg(target_family = "wasm")]
use web_time::Instant;

fn row() -> Div {
    ui::row().gap(px(0.))
}
fn col() -> Div {
    ui::column().gap(px(0.))
}
fn text(s: impl Into<SharedString>) -> Div {
    div().child(s.into())
}

#[derive(Clone, Debug)]
pub enum EditTarget {
    Script,
    Step(String),
}
pub type Edit = Rc<dyn Fn(EditTarget, &mut Window, &mut App)>;
pub type SourceIcon = fn(&str, &str, f32) -> AnyElement;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
enum Status {
    /// No run recorded at all.
    Unknown,
    Ok,
    /// Recorded run, but this step didn't start (condition not met, earlier failure).
    Skipped,
    Recovered,
    /// In flight in a live run.
    Running,
    Failed,
}

#[derive(Clone)]
enum Tile {
    Glyph(Glyph),
    /// A connection's own mark: (name, kind).
    Brand(String, &'static str),
}

#[derive(Clone)]
struct Call {
    title: String,
    started: u64,
    elapsed: f64,
}

#[derive(Clone)]
struct Row {
    key: String,
    title: String,
    tile: Tile,
    /// Short facts under the title, in order.
    meta: Vec<String>,
    /// What protects it: shown as a mark; the text says what happens.
    recovery: Option<String>,
    /// The condition it runs under.
    guard: Option<String>,
    uses: Option<String>,
    status: Status,
    start: f64,
    elapsed: Option<f64>,
    /// Inside a loop: the time is per call, spread across the loop.
    looped: bool,
    started: u64,
    calls: Vec<Call>,
    data: Vec<String>,
    edit: Option<String>,
    children: Vec<Row>,
    /// A data step, shown only when data steps are.
    data_row: bool,
    /// The step's own error from the last run.
    error: Option<String>,
}

impl Row {
    fn new(key: impl Into<String>, title: impl Into<String>, tile: Tile) -> Self {
        Self {
            key: key.into(),
            title: title.into(),
            tile,
            meta: vec![],
            recovery: None,
            guard: None,
            uses: None,
            status: Status::Unknown,
            start: 0.,
            elapsed: None,
            looped: false,
            started: 0,
            calls: vec![],
            data: vec![],
            edit: None,
            children: vec![],
            data_row: false,
            error: None,
        }
    }
}

#[derive(Clone, Default)]
struct Ctx {
    recovery: Option<String>,
    guard: Option<String>,
    /// Iterations of the enclosing loop, when inside one.
    iterations: Option<u64>,
    /// 0 at the top, 1 inside a group: deeper structure flattens.
    depth: usize,
}

pub struct Model {
    rows: Vec<Row>,
    /// What runs when the whole workflow fails.
    failure: Option<String>,
    /// Whether that ran in the last run.
    failure_ran: bool,
    data_steps: usize,
    total: f64,
    traced: bool,
    /// A run in progress: times keep counting from when this arrived.
    live: bool,
}

fn step_glyph(kind: &str) -> Glyph {
    match kind {
        "trigger" => Glyph::MousePointer2,
        "lane" => Glyph::Rows3,
        "join" => Glyph::GitMerge,
        "cli" | "command" => Glyph::Terminal,
        "source" => Glyph::Plug,
        "ai" | "agent" => Glyph::Zap,
        "notify" => Glyph::Bell,
        "state" | "dataset" => Glyph::Database,
        "expression" => Glyph::Braces,
        "if" => Glyph::GitBranch,
        "parallel" => Glyph::Layers,
        "map" => Glyph::Rows3,
        "merge" => Glyph::GitMerge,
        "try" => Glyph::LifeBuoy,
        _ => Glyph::Square,
    }
}

fn find_step<'a>(steps: &'a Value, id: &str) -> Option<&'a Value> {
    for step in steps.as_array()? {
        if step["id"] == id {
            return Some(step);
        }
        for key in ["steps", "then", "else", "catch"] {
            if let Some(found) = find_step(&step[key], id) {
                return Some(found);
            }
        }
        for branch in step["branches"].as_array().into_iter().flatten() {
            if let Some(found) = find_step(&branch["steps"], id) {
                return Some(found);
            }
        }
    }
    None
}

/// The kind of the step with this ID.
fn kind_of<'a>(definition: &'a Value, id: &str) -> Option<&'a str> {
    find_step(&definition["steps"], id).and_then(|s| s["kind"].as_str())
}

fn human_name(value: &str) -> String {
    let chars: Vec<char> = value.chars().collect();
    let mut words: Vec<String> = vec![];
    let mut word = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if c == '_' || c == '-' || c.is_whitespace() {
            if !word.is_empty() {
                words.push(std::mem::take(&mut word));
            }
            continue;
        }
        let prev = i.checked_sub(1).map(|j| chars[j]);
        let next = chars.get(i + 1).copied();
        let boundary = c.is_uppercase()
            && prev.is_some_and(|p| {
                p.is_lowercase()
                    || p.is_ascii_digit()
                    || (p.is_uppercase() && next.is_some_and(|n| n.is_lowercase()))
            });
        if boundary && !word.is_empty() {
            words.push(std::mem::take(&mut word));
        }
        word.push(c);
    }
    if !word.is_empty() {
        words.push(word);
    }
    let words: Vec<String> = words
        .into_iter()
        .enumerate()
        .map(|(i, w)| {
            let acronym = w.chars().count() > 1 && w.chars().all(|c| !c.is_lowercase());
            if acronym {
                w
            } else if i == 0 {
                let mut cs = w.chars();
                cs.next()
                    .map(|f| {
                        f.to_uppercase().collect::<String>() + cs.as_str().to_lowercase().as_str()
                    })
                    .unwrap_or_default()
            } else {
                w.to_lowercase()
            }
        })
        .collect();
    words.join(" ")
}

impl Model {
    /// Few enough steps that the data steps are the story, not noise.
    fn small(&self) -> bool {
        self.rows
            .iter()
            .filter(|r| !r.data_row)
            .map(|r| 1 + r.children.iter().filter(|c| !c.data_row).count())
            .sum::<usize>()
            <= 3
    }
    /// The first step that failed, for the page's alert.
    pub fn failed_step(&self) -> Option<String> {
        fn find(rows: &[Row]) -> Option<String> {
            rows.iter().find_map(|r| {
                find(&r.children).or_else(|| {
                    (r.status == Status::Failed && r.children.is_empty()).then(|| r.title.clone())
                })
            })
        }
        find(&self.rows)
    }
}

pub struct Outline {
    definition: Value,
    trace: Value,
    model: Rc<Model>,
    expanded: Option<String>,
    show_data: bool,
    on_edit: Option<Edit>,
    source_icon: Option<SourceIcon>,
    error: Option<String>,
    /// When the latest live snapshot arrived; running times count on from it.
    received: Instant,
    ticking: bool,
    scroll: ScrollHandle,
    /// Index, among the scrolled items, of the one holding the failed step.
    failed_item: std::cell::Cell<Option<usize>>,
}

impl Outline {
    pub fn new(definition: Value, trace: Value, _cx: &mut Context<Self>) -> Self {
        let model = Rc::new(model(&definition, &trace));
        // A failed run opens on the step that failed.
        let expanded = first_failed_key(&model.rows);
        let show_data = model.small();
        Self {
            definition,
            trace,
            model,
            expanded,
            show_data,
            on_edit: None,
            source_icon: None,
            error: None,
            received: Instant::now(),
            ticking: false,
            scroll: ScrollHandle::new(),
            failed_item: Default::default(),
        }
    }
    pub fn with_source_icon(mut self, icon: SourceIcon) -> Self {
        self.source_icon = Some(icon);
        self
    }
    pub fn on_edit(mut self, callback: Edit) -> Self {
        self.on_edit = Some(callback);
        self
    }
    pub fn error(&mut self, error: Option<String>) {
        self.error = error;
    }
    pub fn model(&self) -> Rc<Model> {
        self.model.clone()
    }
    /// Opens the step that failed and scrolls to it.
    pub fn reveal_failure(&mut self, cx: &mut Context<Self>) {
        self.expanded = first_failed_key(&self.model.rows);
        if let Some(index) = self.failed_item.get() {
            self.scroll.scroll_to_item(index);
        }
        cx.notify();
    }

    /// Whether a run is in progress, and how long it has been going.
    pub fn running(&self) -> Option<f64> {
        self.model
            .live
            .then(|| self.model.total + self.received.elapsed().as_secs_f64() * 1000.)
    }
    /// A snapshot of a run in progress.
    pub fn live(&mut self, trace: Value, cx: &mut Context<Self>) {
        self.model = Rc::new(model(&self.definition, &trace));
        self.trace = trace;
        self.received = Instant::now();
        // Keep the clocks moving between snapshots.
        if !self.ticking {
            self.ticking = true;
            cx.spawn(async move |this, cx| {
                loop {
                    cx.background_executor()
                        .timer(std::time::Duration::from_millis(100))
                        .await;
                    let going = this
                        .update(cx, |o, cx| {
                            let going = o.model.live && o.received.elapsed().as_secs() < 30;
                            if !going {
                                o.ticking = false;
                            }
                            cx.notify();
                            going
                        })
                        .unwrap_or(false);
                    if !going {
                        break;
                    }
                }
            })
            .detach();
        }
        cx.notify();
    }
    pub fn receive(&mut self, definition: Value, trace: Value, cx: &mut Context<Self>) {
        // While a run is in progress the saved trace is cleared; keep the
        // live one until the finished trace arrives.
        if trace.is_null() && self.model.live && self.definition == definition {
            return;
        }
        if self.definition == definition && self.trace == trace {
            return;
        }
        self.definition = definition;
        if trace["live"] == true {
            self.live(trace, cx);
        } else {
            self.model = Rc::new(model(&self.definition, &trace));
            self.trace = trace;
            cx.notify();
        }
    }
}

fn first_failed_key(rows: &[Row]) -> Option<String> {
    rows.iter().find_map(|r| {
        first_failed_key(&r.children).or_else(|| {
            (r.status == Status::Failed && r.children.is_empty()).then(|| r.key.clone())
        })
    })
}

fn event_label(trigger: &Value) -> Option<&'static str> {
    if trigger["kind"] != "event" {
        return None;
    }
    match trigger["event"].as_str()? {
        "messageArrived" => Some("When a message arrives"),
        "taskAdded" => Some("When a task is added"),
        "taskMoved" => Some("When a task moves"),
        "routineFailed" => Some("When a routine fails"),
        _ => None,
    }
}

/// "1.3 s", "840 ms", "2 min 4 s".
fn time(ms: f64) -> String {
    if ms < 1. {
        "<1 ms".into()
    } else if ms < 1000. {
        format!("{} ms", ms.round())
    } else if ms < 60_000. {
        let s = ms / 1000.;
        if s < 10. {
            format!("{s:.1} s")
        } else {
            format!("{} s", s.round())
        }
    } else {
        let s = (ms / 1000.).round() as u64;
        format!("{} min {} s", s / 60, s % 60)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest() -> (Value, Value) {
        let definition = json!({"steps":[{"id":"wrap","kind":"try","title":"Refresh","steps":[
            {"id":"prep","kind":"expression","title":"Prepare"},
            {"id":"fetch","kind":"parallel","title":"Fetch","branches":[
                {"id":"a","title":"GitHub","steps":[{"id":"pre","kind":"expression","title":"Prepare lookup"},{"id":"each","kind":"map","title":"Per PR","steps":[{"id":"gh","kind":"cli","permit":"gh","title":"Read PR"}]}]},
                {"id":"b","title":"PostHog","steps":[{"id":"safe","kind":"try","title":"Keep cache","steps":[{"id":"ph","kind":"source","source":"PostHog","tool":"exec"}],"catch":[{"id":"cached","kind":"expression","title":"Read cache"}]}]}
            ]},
            {"id":"commit","kind":"if","title":"Commit the latest refresh only","then":[{"id":"s1","kind":"state","title":"Save"},{"id":"s2","kind":"dataset","title":"Cache"}]}
        ],"catch":[{"id":"clear","kind":"state","title":"Publish refresh error"}]}]});
        let trace = json!({"elapsedMs":4000.0,"nodes":{
            "wrap":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":4000.0},
            "prep":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":1.0},
            "fetch":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":3900.0},
            "pre":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":1.0},
            "each":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":900.0},
            "gh":{"started":12,"completed":12,"failed":0,"recovered":0,"elapsedMs":2400.0},
            "safe":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":3900.0},
            "ph":{"started":1,"completed":0,"failed":1,"recovered":0,"elapsedMs":3900.0},
            "commit":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":3.0},
            "s1":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":1.0},
            "s2":{"started":1,"completed":1,"failed":0,"recovered":0,"elapsedMs":1.0}}});
        (definition, trace)
    }

    #[::core::prelude::v1::test]
    fn rules_turn_structure_into_a_short_outline() {
        let (definition, trace) = digest();
        let m = model(&definition, &trace);
        let visible: Vec<&Row> = m.rows.iter().filter(|r| !r.data_row).collect();
        // Whole-run wrapper → failure line, not a level.
        assert_eq!(m.failure.as_deref(), Some("publish refresh error"));
        assert_eq!(
            visible.len(),
            2,
            "{:?}",
            visible.iter().map(|r| &r.title).collect::<Vec<_>>()
        );
        // Parallel: one row per branch, named by the branch.
        let fetch = visible[0];
        assert_eq!(fetch.children.len(), 2);
        assert_eq!(fetch.children[0].title, "GitHub");
        assert!(
            fetch.children[0].meta.contains(&"12 calls".to_string()),
            "{:?}",
            fetch.children[0].meta
        );
        // Untitled source step is named by what it does; recovery is a mark.
        assert_eq!(fetch.children[1].calls[0].title, "Query PostHog");
        assert!(fetch.children[1].recovery.is_some());
        assert_eq!(fetch.children[1].status, Status::Failed);
        // The alert names the branch the failure happened in.
        assert_eq!(m.failed_step().as_deref(), Some("PostHog"));
        // Saves behind one guard → one row named by the guard.
        assert_eq!(visible[1].title, "Commit the latest refresh");
        assert!(visible[1].meta.contains(&"2 writes".to_string()));
        // Data steps are counted, not shown: prep and pre. A fallback's own
        // steps are described by the recovery mark, not counted again.
        assert_eq!(m.data_steps, 2);
    }

    #[::core::prelude::v1::test]
    fn untraced_workflows_have_no_invented_status() {
        let (definition, _) = digest();
        let m = model(&definition, &Value::Null);
        assert!(!m.traced);
        assert!(m.rows.iter().all(|r| r.status == Status::Unknown));
    }
}
