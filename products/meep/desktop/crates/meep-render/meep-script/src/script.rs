//! Interpreted script views. A view is a JavaScript file run in QuickJS: it
//! keeps state and returns a plain element tree, and the host renders that
//! tree with real GPUI (`script_view.rs`). Nothing is compiled, so an edit is
//! live in milliseconds and the app ships no Rust toolchain for views.
//!
//! The script can only reach the host through the functions defined here, so
//! source calls and CLI runs keep going through the broker's permission checks.
mod scene;
use scene::scene_request;
mod errors;
use errors::describe;
mod props;
use props::{PROP_TABLE, check_props_for, check_tree_props, edit_distance};

use rquickjs::{Context, Ctx, Function, Runtime};
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    collections::VecDeque,
    rc::Rc,
    time::{Duration, Instant},
};

/// One JavaScript entry (render, event, command) may not run longer than this.
const BUDGET: Duration = Duration::from_millis(500);
const MEMORY: usize = 64 * 1024 * 1024;
const LOGS: usize = 50;
const STOPPED: &str = "\u{0}stopped";
/// Promise jobs one entry may settle. Real views settle a handful; a job
/// that keeps queueing jobs never empties the queue on its own.
const JOBS: usize = 1_000_000;
const LATE_JOBS: usize = 10_000;

pub use crate::script_contract::ELEMENTS;
pub use crate::script_contract::check_tree;

/// Work the script asked the host to do. Drained after every entry, so JS
/// never re-enters itself through a host call.
pub use crate::script_engine::HostQueue;

/// A shallow state delta. Missing keys and explicit nulls stay distinct.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct StatePatch {
    pub set: serde_json::Map<String, Value>,
    pub remove: Vec<String>,
}
impl StatePatch {
    pub fn between(before: &Value, after: &Value) -> Self {
        let empty = serde_json::Map::new();
        let before = before.as_object().unwrap_or(&empty);
        let after = after.as_object().unwrap_or(&empty);
        Self {
            set: after
                .iter()
                .filter(|(k, v)| before.get(*k) != Some(*v))
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
            remove: before
                .keys()
                .filter(|k| !after.contains_key(*k))
                .cloned()
                .collect(),
        }
    }
    pub fn apply(&self, state: &mut Value) {
        if !state.is_object() {
            *state = json!({});
        }
        let object = state.as_object_mut().unwrap();
        object.extend(self.set.clone());
        for key in &self.remove {
            object.remove(key);
        }
    }
}

pub struct Engine {
    runtime: Runtime,
    context: Context,
    queue: Rc<RefCell<HostQueue>>,
    pub logs: Rc<RefCell<VecDeque<String>>>,
    deadline: Rc<Cell<Option<Instant>>>,
    interrupted: Rc<Cell<bool>>,
    /// Set when an entry stopped with promise jobs still queued. Those jobs
    /// would run again on every later entry, so the engine refuses to enter.
    halted: RefCell<Option<String>>,
    pub data: Rc<RefCell<crate::datasets::Datasets>>,
    /// Large node-and-edge data drawn natively (`host.scene`).
    pub scenes: Rc<RefCell<crate::scene::Scenes>>,
}

impl Engine {
    /// Load a script and restore `saved` state over its declared defaults.
    pub fn new(source: &str, saved: &Value) -> Result<Self, String> {
        Self::new_checked(source, saved, false)
    }
    fn new_checked(source: &str, saved: &Value, check_props: bool) -> Result<Self, String> {
        let runtime = Runtime::new().map_err(|e| e.to_string())?;
        runtime.set_memory_limit(MEMORY);
        runtime.set_max_stack_size(1024 * 1024);
        let deadline: Rc<Cell<Option<Instant>>> = Rc::default();
        let interrupted: Rc<Cell<bool>> = Rc::default();
        let clock = deadline.clone();
        let interruption = interrupted.clone();
        runtime.set_interrupt_handler(Some(Box::new(move || {
            let expired = clock.get().is_some_and(|end| Instant::now() > end);
            interruption.set(expired);
            expired
        })));
        let context = Context::full(&runtime).map_err(|e| e.to_string())?;
        let engine = Self {
            runtime,
            context,
            queue: Rc::default(),
            logs: Rc::default(),
            deadline,
            interrupted,
            halted: RefCell::default(),
            data: Rc::default(),
            scenes: Rc::default(),
        };
        let (queue, logs) = (engine.queue.clone(), engine.logs.clone());
        engine.enter(|ctx| {
            let globals = ctx.globals();
            globals.set(
                "__host_check_props",
                Function::new(
                    ctx.clone(),
                    |ctx: Ctx<'_>,
                     kind: String,
                     props: String,
                     at: String|
                     -> rquickjs::Result<()> {
                        let props = serde_json::from_str(&props).map_err(|_| {
                            rquickjs::Exception::throw_type(
                                &ctx,
                                "Element props must be JSON values",
                            )
                        })?;
                        check_props_for(&kind, &props, &at)
                            .map_err(|error| rquickjs::Exception::throw_type(&ctx, &error))
                    },
                )?,
            )?;
            let data = engine.data.clone();
            let data_queue = queue.clone();
            globals.set(
                "__host_data",
                Function::new(
                    ctx.clone(),
                    move |ctx: Ctx<'_>,
                          op: String,
                          name: String,
                          args: String|
                          -> rquickjs::Result<String> {
                        let args = args.parse::<Value>().map_err(|_| {
                            rquickjs::Exception::throw_type(&ctx, "Invalid dataset arguments")
                        })?;
                        let value = data
                            .borrow_mut()
                            .request_owned(&op, &name, args)
                            .map_err(|e| rquickjs::Exception::throw_type(&ctx, &e))?;
                        if matches!(op.as_str(), "set" | "patch" | "remove" | "clear") {
                            data_queue.borrow_mut().dirty = true;
                        }
                        Ok(value.to_string())
                    },
                )?,
            )?;
            let scenes = engine.scenes.clone();
            let scene_queue = queue.clone();
            globals.set(
                "__host_scene",
                Function::new(
                    ctx.clone(),
                    move |ctx: Ctx<'_>,
                          op: String,
                          name: String,
                          columns: rquickjs::Value<'_>|
                          -> rquickjs::Result<String> {
                        let fail = |e: String| rquickjs::Exception::throw_type(&ctx, &e);
                        let result = scene_request(&scenes, &op, &name, &columns).map_err(fail)?;
                        if op != "info" {
                            scene_queue.borrow_mut().dirty = true;
                        }
                        Ok(result.to_string())
                    },
                )?,
            )?;
            // Block editor documents to and from Markdown, synchronously:
            // pure conversions with no host access.
            globals.set(
                "__host_markdown",
                Function::new(
                    ctx.clone(),
                    move |ctx: Ctx<'_>, op: String, text: String| -> rquickjs::Result<String> {
                        use crate::block_editor::{markdown, model::Doc};
                        match op.as_str() {
                            "to" => {
                                let value = text.parse::<Value>().map_err(|_| {
                                    rquickjs::Exception::throw_type(
                                        &ctx,
                                        "toMarkdown needs an array of blocks",
                                    )
                                })?;
                                Ok(markdown::to_markdown(&Doc::from_json(&value).blocks))
                            }
                            _ => Ok(Doc::new(markdown::from_markdown(&text))
                                .to_json()
                                .to_string()),
                        }
                    },
                )?,
            )?;
            let dirty = queue.clone();
            globals.set(
                "__host_dirty",
                Function::new(ctx.clone(), move || dirty.borrow_mut().dirty = true)?,
            )?;
            let requests = queue.clone();
            globals.set(
                "__host_request",
                Function::new(
                    ctx.clone(),
                    move |ctx: Ctx<'_>,
                          id: u32,
                          method: String,
                          params: String|
                          -> rquickjs::Result<()> {
                        // The native runner, not JavaScript, reports its failure diagnostic.
                        if method == "native.workflows.trace" {
                            return Err(rquickjs::Exception::throw_type(
                                &ctx,
                                "Workflow traces are submitted by the native runner",
                            ));
                        }
                        if !requests.borrow_mut().reserve(method.len() + params.len()) {
                            return Err(rquickjs::Exception::throw_type(
                                &ctx,
                                "Host request queue limit exceeded",
                            ));
                        }
                        let params = params.parse::<Value>().unwrap_or(Value::Null);
                        requests.borrow_mut().requests.push((id, method, params));
                        Ok(())
                    },
                )?,
            )?;
            let local = queue.clone();
            globals.set(
                "__host_local",
                Function::new(
                    ctx.clone(),
                    move |ctx: Ctx<'_>, kind: String, value: String| -> rquickjs::Result<()> {
                        if !local.borrow_mut().reserve(kind.len() + value.len()) {
                            return Err(rquickjs::Exception::throw_type(
                                &ctx,
                                "Host effect queue limit exceeded",
                            ));
                        }
                        let value = value.parse::<Value>().unwrap_or(Value::Null);
                        if kind == "open_url"
                            && crate::links::web_url(value.as_str().unwrap_or("")).is_err()
                        {
                            return Err(rquickjs::Exception::throw_type(
                                &ctx,
                                "Only HTTP, HTTPS and mailto links are allowed",
                            ));
                        }
                        if !["copy", "open_url", "focus", "timer"].contains(&kind.as_str()) {
                            return Err(rquickjs::Exception::throw_type(
                                &ctx,
                                "Unknown host effect",
                            ));
                        }
                        local.borrow_mut().local.push((kind, value));
                        Ok(())
                    },
                )?,
            )?;
            globals.set(
                "__host_log",
                Function::new(ctx.clone(), move |line: String| {
                    let mut logs = logs.borrow_mut();
                    if logs.len() == LOGS {
                        logs.pop_front();
                    }
                    logs.push_back(line.chars().take(2000).collect());
                })?,
            )?;
            let mut prelude = rquickjs::context::EvalOptions::default();
            prelude.global = true;
            prelude.filename = Some("view-sdk.js".into());
            ctx.eval_with_options::<(), _>(PRELUDE, prelude)?;
            ctx.eval::<(), _>(include_str!("script_agents.js"))?;
            if check_props {
                let constructors = PROP_TABLE
                    .iter()
                    .map(|(kind, name, _)| json!([kind, name]))
                    .collect::<Vec<_>>();
                ctx.eval::<(), _>(format!("__checkConstructors({})", json!(constructors)))?;
            }
            let mut options = rquickjs::context::EvalOptions::default();
            options.global = true;
            options.strict = false;
            options.filename = Some("view.js".into());
            ctx.eval_with_options::<(), _>(source, options)?;
            ctx.eval::<(), _>("__ready()")
        })?;
        let saved = serde_json::to_string(saved).unwrap_or_else(|_| "null".into());
        engine.call::<()>("__boot", (saved,))?;
        Ok(engine)
    }

    /// Run JS with a time budget, turning exceptions into readable errors,
    /// then settle any promise jobs it queued.
    fn enter<R>(&self, f: impl FnOnce(Ctx<'_>) -> rquickjs::Result<R>) -> Result<R, String> {
        if let Some(error) = self.halted.borrow().clone() {
            return Err(error);
        }
        self.deadline.set(Some(Instant::now() + BUDGET));
        let result = self
            .context
            .with(|ctx| f(ctx.clone()).map_err(|e| describe(&ctx, e)));
        let jobs = self.drain_jobs();
        let timed_out = self.interrupted.replace(false);
        self.deadline.set(None);
        // QuickJS raises an exception with no value both when interrupted and
        // when allocation fails. Only the interrupt handler knows which happened.
        let unexplained = |error: String| {
            if timed_out {
                let at = error.lines().skip(1).take(3).collect::<Vec<_>>().join("\n");
                format!(
                    "Script stopped: it ran longer than 500 ms (infinite loop or too much work per update)\n{at}"
                )
            } else if error == STOPPED {
                "Script ran out of memory (64 MB). Keep large data out of the script or page it."
                    .into()
            } else {
                error
            }
        };
        let result = result.map_err(unexplained);
        let jobs = jobs.map_err(unexplained);
        let value = result?;
        jobs?;
        Ok(value)
    }

    fn drain_jobs(&self) -> Result<(), String> {
        let (mut first, mut late) = (None, 0);
        for _ in 0..JOBS {
            // Past the deadline each job is interrupted, which settles what
            // was left over; but a job too short to be interrupted can keep
            // queueing more, so only a bounded number run late.
            if self.deadline.get().is_some_and(|end| Instant::now() > end) {
                late += 1;
                if late > LATE_JOBS {
                    break;
                }
            }
            match self.runtime.execute_pending_job() {
                Ok(true) => continue,
                Ok(false) => return first.map_or(Ok(()), Err),
                Err(error) => {
                    let message = error
                        .0
                        .with(|ctx| describe(&ctx, rquickjs::Error::Exception));
                    first.get_or_insert(message);
                }
            }
        }
        if !self.runtime.is_job_pending() {
            return first.map_or(Ok(()), Err);
        }
        // Jobs are left over. They can't be dropped, and running them on the
        // next entry would hang it the same way, so this engine stops here.
        let error = format!(
            "Script stopped: its promise jobs ran longer than {} ms (a promise chain that never ends)",
            BUDGET.as_millis()
        );
        self.halted.replace(Some(error.clone()));
        Err(error)
    }

    fn call<R: for<'js> rquickjs::FromJs<'js>>(
        &self,
        name: &str,
        args: impl for<'js> rquickjs::function::IntoArgs<'js>,
    ) -> Result<R, String> {
        self.enter(|ctx| {
            let function: Function = ctx.globals().get(name)?;
            function.call(args)
        })
    }

    fn json(
        &self,
        name: &str,
        args: impl for<'js> rquickjs::function::IntoArgs<'js>,
    ) -> Result<Value, String> {
        let text: String = self.call(name, args)?;
        // `Value`'s `FromStr` is compiled inside serde_json, so it runs
        // optimized in development builds too; `from_str::<Value>` would be
        // instantiated here, unoptimized (2.6 ms against 0.5 ms for an 80 KB
        // tree).
        text.parse::<Value>()
            .map_err(|e| format!("{name} returned invalid JSON: {e}"))
    }

    /// Start the view's own work (loading data). Called once per mount.
    pub fn init(&self) -> Result<(), String> {
        self.call("__init", ())
    }
    /// Validate the view's initialization logic without allowing queued host
    /// calls or window effects to leave this fresh validation engine.
    pub fn validate_init(&self) -> Result<(), String> {
        self.call::<()>("__validateInit", ())?;
        let error: Option<String> = self.call("__init_validation_error", ())?;
        error.map_or(Ok(()), Err)
    }
    /// The whole element tree for the current state.
    pub fn render(&self) -> Result<Value, String> {
        self.json("__render", ())
    }
    /// One virtualized list row; only called for rows on screen.
    pub fn row(&self, function: u32, index: usize) -> Result<Value, String> {
        self.json("__row", (function, index as u32))
    }
    pub fn invoke(&self, handler: u32, argument: &Value) -> Result<(), String> {
        self.call("__invoke", (handler, argument.to_string()))
    }
    /// Needs the host adds to the ones the script declares (an imported
    /// view's), asked for in the same approval before `init`.
    pub fn set_host_needs(&self, needs: &Value) -> Result<(), String> {
        let needs = if needs.is_array() {
            needs.clone()
        } else {
            Value::Array(vec![])
        };
        validate_needs(&needs)?;
        self.call("__setHostNeeds", (needs.to_string(),))
    }
    pub fn settle(&self, id: u32, result: Result<Value, String>) -> Result<(), String> {
        match result {
            Ok(value) => self.call("__settle", (id, true, value.to_string())),
            Err(error) => self.call("__settle", (id, false, error)),
        }
    }
    /// A timer created by setTimeout/setInterval is due.
    pub fn fire(&self, timer: u64) -> Result<(), String> {
        self.call("__fire", (timer as f64,))
    }
    /// A key press inside the view, like `cmd-k` or `down`. True when the
    /// script's `keys` handled it.
    pub fn key(&self, name: &str) -> Result<bool, String> {
        self.call("__key", (name.to_owned(),))
    }
    pub fn has_command(&self, name: &str) -> bool {
        self.call("__has_command", (name.to_owned(),))
            .unwrap_or(false)
    }
    pub fn command(&self, name: &str, arguments: &Value) -> Result<Value, String> {
        self.json("__command", (name.to_owned(), arguments.to_string()))
    }
    pub fn background_start(&self, name: &str, args: &Value) -> Result<u32, String> {
        self.call("__backgroundStart", (name.to_owned(), args.to_string()))
    }
    pub fn background_cancel(&self, id: u32, requests: &[u32]) -> Result<(), String> {
        self.call("__backgroundCancel", (id, requests.to_vec()))
    }
    pub fn background_result(&self, id: u32) -> Result<Value, String> {
        self.json("__backgroundResult", (id, false))
    }
    pub fn background_collect(&self, id: u32) -> Result<Value, String> {
        self.json("__backgroundResult", (id, true))
    }
    pub fn init_pending(&self) -> bool {
        self.call("__init_pending", ()).unwrap_or(false)
    }
    pub fn pending_requests(&self) -> usize {
        self.queue.borrow().requests.len()
    }
    pub fn inspect(&self) -> Result<Value, String> {
        self.json("__inspect", ())
    }
    pub fn runtime_activity(&self) -> Result<Value, String> {
        self.json("__runtimeActivity", ())
    }
    pub fn discard_timers(&self, ids: Vec<u64>) -> Result<(), String> {
        self.call("__discardTimers", (ids,))
    }
    pub fn checkpoint_text(&self) -> Result<String, String> {
        self.call("__checkpoint", ())
    }
    pub fn checkpoint(&self) -> Result<Value, String> {
        self.checkpoint_text()?
            .parse::<Value>()
            .map_err(|e| e.to_string())
    }
    pub fn workflow_patch(&self, patch: &Value) -> Result<(), String> {
        self.call("__workflowPatch", (patch.to_string(),))
    }
    pub fn workflow_transform(&self, name: &str, args: &Value) -> Result<Value, String> {
        let before = self.checkpoint_text()?;
        self.data.borrow_mut().read_only = true;
        let result = self.json("__workflowTransform", (name, args.to_string()));
        self.data.borrow_mut().read_only = false;
        let reset = self.call::<bool>("__badge_end", (before,));
        reset?;
        result
    }
    pub fn cell(&self, function: u32, row: &Value) -> Result<Value, String> {
        self.json("__cell", (function, row.to_string()))
    }
    pub fn restore(&self, state: &Value) -> Result<(), String> {
        self.call("__restore", (state.to_string(),))
    }
    pub fn declared_commands(&self) -> Vec<String> {
        self.json("__commands", ())
            .ok()
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default()
    }
    pub fn badge(&self) -> Option<String> {
        self.sidebar_metadata().0
    }
    pub fn sidebar_metadata(&self) -> (Option<String>, Option<crate::sidebar::SidebarCard>) {
        let before = match self.call::<String>("__checkpoint", ()) {
            Ok(state) => state,
            Err(error) => {
                self.logs.borrow_mut().push_back(format!("error: {error}"));
                return (None, None);
            }
        };
        self.sidebar_metadata_at(before)
    }
    pub fn sidebar_metadata_at(
        &self,
        before: String,
    ) -> (Option<String>, Option<crate::sidebar::SidebarCard>) {
        self.data.borrow_mut().read_only = true;
        let result = self.json("__badge", (before.clone(),));
        self.data.borrow_mut().read_only = false;
        if self.call::<bool>("__badge_end", (before,)).unwrap_or(true) {
            self.logs
                .borrow_mut()
                .push_back("error: badge() must not change state".into());
            return (None, None);
        }
        let value = match result {
            Ok(value) => value,
            Err(error) => {
                self.logs.borrow_mut().push_back(format!("error: {error}"));
                return (None, None);
            }
        };
        let commands = self.declared_commands();
        let card = crate::sidebar::SidebarCard::normalize(&value, &commands);
        (crate::design::badge_text(value), card)
    }
    /// The badge as the script wrote it, before the sidebar shortens it, so
    /// validation can say when text would be cut.
    fn badge_written(&self) -> Option<String> {
        let before = self.call::<String>("__checkpoint", ()).ok()?;
        self.data.borrow_mut().read_only = true;
        let result = self.json("__badge", (before.clone(),));
        self.data.borrow_mut().read_only = false;
        let _ = self.call::<bool>("__badge_end", (before,));
        let value = result.ok()?;
        let value = if value.is_object() {
            value["value"].clone()
        } else {
            value
        };
        value.as_str().map(|s| s.trim().to_owned())
    }
    pub fn take_queue(&self) -> HostQueue {
        std::mem::take(&mut self.queue.borrow_mut())
    }
}

pub use crate::script_contract::diagnostic_summary;

/// Shared by install validation and the broker's declared-needs request.
pub fn validate_needs(needs: &Value) -> Result<(), String> {
    let entries = needs.as_array().ok_or("needs must be an array")?;
    for need in entries {
        let object = need.as_object().ok_or("Each need must be an object")?;
        // Names are shown in the approval sheet, one per line: a newline or
        // an overlong name could draw rows the view did not ask for.
        let names = object
            .values()
            .flat_map(|v| v.as_array().map_or_else(|| vec![v], |a| a.iter().collect()))
            .filter_map(Value::as_str);
        for name in names {
            if name.chars().count() > 128 || name.chars().any(char::is_control) {
                return Err("Names in needs must be single-line and at most 128 characters".into());
            }
        }
        let nonempty = |v: &Value| v.as_str().is_some_and(|s| !s.trim().is_empty());
        let strings = |v: &Value| {
            v.as_array()
                .is_some_and(|a| !a.is_empty() && a.iter().all(nonempty))
        };
        let valid = if object.contains_key("source") {
            object.len() == 2 && nonempty(&need["source"]) && strings(&need["tools"])
        } else {
            object.len() == 2
                && nonempty(&need["cli"])
                && need["cli"].as_str().is_some_and(|s| !s.contains('/'))
                && need["action"].as_array().is_some_and(|a| {
                    a.iter()
                        .all(|v| nonempty(v) && !v.as_str().unwrap_or("").starts_with('-'))
                })
        };
        if !valid {
            return Err(
                "Use { source, tools: [name, ...] } or { cli, action: [word, ...] } in needs"
                    .into(),
            );
        }
    }
    Ok(())
}

/// What the broker runs before accepting a script: load it, render it once
/// with the saved state, and validate the tree. Errors read like compiler
/// diagnostics for the agent; the live view is untouched.
pub fn validate(source: &str, state: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let engine = Engine::new_checked(source, state, true)?;
    validate_needs(&engine.json("__needs", ())?)?;
    // Initialization can change state/data; validate it in its own sandbox so
    // the initial render is checked as well, before any host result exists.
    let initialization = Engine::new_checked(source, state, true)?;
    initialization.validate_init().map_err(|error| {
        let cause = error.lines().next().unwrap_or(&error);
        let location = error.find("view.js:").map(|at| {
            error[at..]
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || ".:".contains(*c))
                .collect::<String>()
        });
        let at = location.map(|at| format!(" ({at})")).unwrap_or_default();
        format!("init threw {cause}{at}. Fix it before saving.\n{error}")
    })?;
    // Immediate initialization can reveal a different branch of the tree.
    // Check that branch in the same isolated engine, without changing the
    // saved state used for the original loading/empty render below.
    let initialized_tree = initialization.render()?;
    check_tree(&initialized_tree)?;
    check_tree_props(&initialized_tree)?;
    let tree = engine.render()?;
    check_tree(&tree)?;
    check_tree_props(&tree)?;
    let findings = crate::script_lint::dedupe(crate::script_lint::check(&tree));
    let errors: Vec<_> = findings
        .iter()
        .filter(|f| f.severity == crate::script_lint::Severity::Error)
        .map(|f| format!("{}: {} [{}]", f.at, f.message, f.rule))
        .collect();
    if !errors.is_empty() {
        return Err(format!(
            "The design check rejected this view:\n- {}",
            errors.join("\n- ")
        ));
    }
    let (score, grade) = crate::script_lint::grade(&findings);
    let mut warnings: Vec<String> = findings
        .iter()
        .take(12)
        .map(|f| format!("{}: {} [{}]", f.at, f.message, f.rule))
        .collect();
    // The sidebar keeps four characters of a badge. Say so instead of
    // letting "17 mo" quietly become "17 m".
    if let Some(written) = engine.badge_written().filter(|b| b.chars().count() > 4) {
        let shown: String = written.chars().take(4).collect();
        warnings.insert(0, format!(
            "badge: \"{written}\" shows as \"{shown}\". A badge keeps 4 characters: use a count or a short code, and put words in the sidebar card. [badge-cut]"
        ));
    }
    Ok(json!({
        "checked_ms": started.elapsed().as_secs_f64() * 1000.0,
        "warnings": warnings,
        "design_score": score,
        "design_grade": grade.to_string(),
    }))
}

/// Preview initialization using host-supplied read-only results in a disposable
/// engine. An unavailable or unsupported request leaves the preview incomplete.
/// Returns `None` if no source was requested, or whether the preview completed.
pub fn validate_populated(
    source: &str,
    mut resolve: impl FnMut(&Value) -> Option<Value>,
) -> Result<Option<bool>, String> {
    let engine = Engine::new_checked(source, &json!({}), true)?;
    engine.init()?;
    let mut resolved = false;
    let mut calls = 0;
    loop {
        let queue = engine.take_queue();
        // Window effects and timers stay in this disposable engine.
        if queue.requests.is_empty() {
            break;
        }
        for (id, method, args) in queue.requests {
            calls += 1;
            if calls > 16 || method != "sources.call" {
                return Ok(Some(false));
            }
            let Some(value) = resolve(&args) else {
                return Ok(Some(false));
            };
            resolved = true;
            engine.settle(id, Ok(value))?;
        }
    }
    if engine.init_pending() {
        return Ok(Some(false));
    }
    if !resolved {
        return Ok(None);
    }
    let tree = engine.render()?;
    check_tree(&tree)?;
    check_tree_props(&tree)?;
    // List callbacks are lazy and therefore absent from the rendered tree.
    fn rows(engine: &Engine, node: &Value, remaining: &mut usize) -> Result<(), String> {
        if node["t"] == "list"
            && let (Some(count), Some(function)) = (
                node["p"]["count"].as_u64(),
                node["p"]["row"]["$fn"].as_u64(),
            )
            && count > 0
            && *remaining > 0
        {
            *remaining -= 1;
            let row = engine.row(function as u32, 0)?;
            check_tree(&row)?;
            check_tree_props(&row)?;
            rows(engine, &row, remaining)?;
        }
        for child in node["c"].as_array().into_iter().flatten() {
            rows(engine, child, remaining)?;
        }
        Ok(())
    }
    rows(&engine, &tree, &mut 8)?;
    Ok(Some(true))
}

/// Grades an installed view without rejecting it: every finding, the score
/// and the letter. Used to audit existing views against the design checker.
pub fn grade(source: &str, state: &Value) -> Result<Value, String> {
    let engine = Engine::new(source, state)?;
    let tree = engine.render()?;
    check_tree(&tree)?;
    let findings = crate::script_lint::dedupe(crate::script_lint::check(&tree));
    let (score, grade) = crate::script_lint::grade(&findings);
    Ok(json!({
        "score": score,
        "grade": grade.to_string(),
        "findings": crate::script_lint::to_json(&findings),
    }))
}

/// The script-side SDK. See that file for everything a script can call.
const PRELUDE: &str = include_str!("script_prelude.js");

#[cfg(test)]
#[path = "script_agents_tests.rs"]
mod agent_tests;

#[cfg(test)]
mod benchmarks;
#[cfg(test)]
mod tests;

#[cfg(test)]
mod limits {
    /// Where QuickJS itself gives out, without the 500 ms guard.
    /// cargo test --release -p meep-script script::limits -- --ignored --nocapture
    #[test]
    #[ignore]
    fn record_capacity() {
        for limit_mb in [64usize, 256] {
            for n in [
                100_000usize,
                250_000,
                500_000,
                1_000_000,
                2_000_000,
                4_000_000,
            ] {
                let runtime = rquickjs::Runtime::new().unwrap();
                runtime.set_memory_limit(limit_mb << 20);
                let context = rquickjs::Context::full(&runtime).unwrap();
                let started = std::time::Instant::now();
                let made: Result<(), String> = context.with(|ctx| {
                    ctx.eval::<(), _>(format!("globalThis.d = Array.from({{ length: {n} }}, (_, i) => ({{ title: 'Item ' + i, status: ['Todo','Doing','Done'][i % 3], n: (i * 7) % 1000 }}));"))
                        .map_err(|e| format!("{e}: {:?}", ctx.catch()))
                });
                let make = started.elapsed();
                let started = std::time::Instant::now();
                let filtered: Result<i32, String> = context.with(|ctx| {
                    ctx.eval::<i32, _>("d.filter(r => r.n % 10 !== 3).length")
                        .map_err(|e| e.to_string())
                });
                let filter = started.elapsed();
                let used = runtime.memory_usage().malloc_size as f64 / 1048576.0;
                eprintln!(
                    "limit {limit_mb:>3} MB  n {n:>9}: {}",
                    match (made, filtered) {
                        (Ok(()), Ok(_)) => format!(
                            "create {:>7.1} ms  filter {:>6.1} ms  heap {used:>6.1} MB",
                            make.as_secs_f64() * 1e3,
                            filter.as_secs_f64() * 1e3
                        ),
                        (Err(e), _) | (_, Err(e)) => format!(
                            "FAILED after {:.0} ms: {}",
                            make.as_secs_f64() * 1e3,
                            e.chars().take(80).collect::<String>()
                        ),
                    }
                );
            }
        }
    }
}

#[cfg(test)]
mod security_tests {
    use super::*;
    #[test]
    fn raw_host_effects_obey_rust_policy_and_limits() {
        for url in ["file:///tmp/test", "javascript:alert(1)", "custom:run"] {
            let source = format!(
                "__host_local('open_url', JSON.stringify({})); view({{render:()=>Page()}})",
                serde_json::to_string(url).unwrap()
            );
            assert!(Engine::new(&source, &Value::Null).is_err());
        }
        assert!(
            Engine::new(
                "for(let i=0;i<129;i++) __host_local('focus', '\"x\"'); view({render:()=>Page()})",
                &Value::Null
            )
            .is_err()
        );
        assert!(Engine::new("__host_request(1, 'x', JSON.stringify('x'.repeat(131073))); view({render:()=>Page()})", &Value::Null).is_err());
    }
    #[test]
    fn dataset_badge_accessor_is_read_only_and_outside_checkpoint() {
        let engine = Engine::new("host.data.set('x',[{id:1,n:2}]);view({state:{q:''},badge:(s,d)=>{const rows=d.rows('x');rows[0].n=99;return d.count('x')},render:()=>Page()})",&json!({})).unwrap();
        assert_eq!(engine.badge().as_deref(), Some("1"));
        assert_eq!(engine.checkpoint().unwrap(), json!({"q":""}));
        assert_eq!(
            engine.data.borrow_mut().snapshot().unwrap()["x"]["rows"][0]["n"],
            2
        );
        let engine = Engine::new("host.data.set('x',[{id:1}]);view({badge:()=>{__host_data('clear','x','{}');return 1},render:()=>Page()})",&json!({})).unwrap();
        assert_eq!(engine.badge(), None);
        assert_eq!(
            engine
                .data
                .borrow_mut()
                .request("count", "x", &Value::Null)
                .unwrap(),
            1
        );
    }
}

impl crate::script_engine::ScriptEngine for Engine {
    fn render(&self) -> Result<Value, String> {
        Engine::render(self)
    }
    fn row(&self, function: u32, index: usize) -> Result<Value, String> {
        Engine::row(self, function, index)
    }
    fn cell(&self, function: u32, row: &Value) -> Result<Value, String> {
        Engine::cell(self, function, row)
    }
    fn invoke(&self, handler: u32, argument: &Value) -> Result<(), String> {
        Engine::invoke(self, handler, argument)
    }
    fn key(&self, name: &str) -> Result<bool, String> {
        Engine::key(self, name)
    }
    fn init(&self) -> Result<(), String> {
        Engine::init(self)
    }
    fn settle(&self, id: u32, result: Result<Value, String>) -> Result<(), String> {
        Engine::settle(self, id, result)
    }
    fn fire(&self, timer: u64) -> Result<(), String> {
        Engine::fire(self, timer)
    }
}

/// Shown for a view saved by the retired Rust compiler.
pub const RETIRED: &str = r#"view({ render: () => Page(Empty("Rebuild this view", "It was made with the retired Rust view runtime and can no longer run. Ask its agent to rebuild it.")) });"#;
