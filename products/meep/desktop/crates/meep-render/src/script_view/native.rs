//! Native lifecycle: broker ownership, persistence, activation and workflows.
use super::*;

/// Only host awaits inherit activation. Siblings share a finite request budget;
/// timers and unrelated entries never borrow the last click's authority.
#[derive(Clone)]
struct Activation {
    deadline: Instant,
    remaining: Rc<std::cell::Cell<u8>>,
}
impl Activation {
    fn new() -> Self {
        Self {
            deadline: Instant::now() + std::time::Duration::from_secs(10),
            remaining: Rc::new(std::cell::Cell::new(32)),
        }
    }
    fn next(&self) -> Option<Self> {
        if Instant::now() >= self.deadline || self.remaining.get() == 0 {
            return None;
        }
        self.remaining.set(self.remaining.get() - 1);
        Some(self.clone())
    }
    fn resume(mut self, method: &str, result: &Result<Value, String>) -> Option<Self> {
        let accepted = result.as_ref().is_ok_and(|value| match method {
            "permissions.request" => value["approved"] == true,
            "native.confirm" => value == true,
            "native.files.pick" | "native.files.pickFolder" | "native.files.saveText" => {
                !value.is_null()
            }
            _ => false,
        });
        // Answering a host prompt deliberately renews this continuation's time,
        // including after a long approval, but never replenishes its budget.
        if accepted {
            self.deadline = Instant::now() + std::time::Duration::from_secs(10);
        }
        (Instant::now() < self.deadline).then_some(self)
    }
}

/// Load a script view. A script that fails to load or render returns an
/// error, so a live replacement keeps the previous generation.
pub fn mount(
    source: &str,
    _window: &mut Window,
    cx: &mut App,
    context: ViewContext,
) -> anyhow::Result<MountedView> {
    mount_with_empty(
        source,
        _window,
        cx,
        context,
        Rc::new(|| ui::empty("View", "").into_any_element()),
    )
}

pub fn mount_with_empty(
    source: &str,
    _window: &mut Window,
    cx: &mut App,
    context: ViewContext,
    empty: Rc<dyn Fn() -> AnyElement>,
) -> anyhow::Result<MountedView> {
    mount_inner(source, cx, context, empty, None)
}

/// A read-only, one-frame reconstruction. Never run init or start host work.
pub fn mount_snapshot(
    source: &str,
    cx: &mut App,
    context: ViewContext,
    datasets: Value,
) -> anyhow::Result<MountedView> {
    mount_inner(
        source,
        cx,
        context,
        Rc::new(|| div().into_any_element()),
        Some(datasets),
    )
}

fn mount_inner(
    source: &str,
    cx: &mut App,
    context: ViewContext,
    empty: Rc<dyn Fn() -> AnyElement>,
    datasets: Option<Value>,
) -> anyhow::Result<MountedView> {
    let snapshot = datasets.is_some();
    let engine = Engine::new(source, &context.initial_state).map_err(anyhow::Error::msg)?;
    if let Some(datasets) = datasets {
        engine.data.borrow_mut().load(datasets);
    }
    let mut memo = styles::Memo::default();
    let tree = parse(engine.render(), &mut memo).map_err(anyhow::Error::msg)?;
    let saved_state = engine.checkpoint().map_err(anyhow::Error::msg)?;
    let uses_data = source.contains("host.data");
    Ok(sdk::mount(cx, move |cx: &mut Context<ScriptView>| {
        let mut shared = Shared::new(engine, memo);
        shared.images.get_mut().enabled = !snapshot;
        cx.on_release(|view, cx| view.shared.images.borrow_mut().release(cx))
            .detach();
        let mut view = ScriptView {
            shared: Rc::new(shared),
            saved_state,
            save_failures: 0,
            epoch: 0,
            background: None,
            background_done: false,
            background_value: Value::Null,
            background_id: None,
            background_request: None,
            host_requests: HashMap::new(),
            native_workflows: HashMap::new(),
            workflow_generations: Rc::default(),
            timer_slots: std::sync::Arc::new(tokio::sync::Semaphore::new(128)),
            init_started: false,
            snapshot,
            empty_visible: false,
            empty,
            context,
            focus: cx.focus_handle(),
            tree: Some(Rc::new(tree)),
            inputs_synced: None,
            stale: false,
            error: None,
            inputs: HashMap::new(),
            pending_focus: None,
            save_scheduled: false,
        };
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(150))
                .await;
            let _ = this.update(cx, |this, cx| {
                this.empty_visible = true;
                if this.tree.is_none() {
                    cx.notify();
                }
            });
        })
        .detach();
        if !snapshot && (!uses_data || view.context.is_active()) {
            view.start_init(cx);
        }
        view
    }))
}

impl ScriptView {
    fn start_init(&mut self, cx: &mut Context<Self>) {
        if self.init_started || self.context.is_retired() {
            return;
        }
        self.init_started = true;
        let started = ScriptEngine::init(&self.shared.engine);
        self.report(started);
        self.after_js(cx, false);
        self.schedule_save(cx);
    }
    /// Apply what the script asked for: re-render, persist state, start
    /// broker requests and timers whose results re-enter JS later, and run
    /// window-local effects.
    pub(super) fn after_js(&mut self, cx: &mut Context<Self>, user_gesture: bool) {
        let activation =
            (user_gesture && self.context.background_request().is_none()).then(Activation::new);
        self.after_js_activated(cx, user_gesture, activation);
    }
    fn after_js_activated(
        &mut self,
        cx: &mut Context<Self>,
        user_gesture: bool,
        activation: Option<Activation>,
    ) {
        if self.snapshot {
            self.shared.engine.take_queue();
            return;
        }
        let queue = self.shared.engine.take_queue();
        if self.context.background_request().is_some() && !queue.local.is_empty() {
            if let Some(id) = self.background_id {
                let requests = queue
                    .requests
                    .iter()
                    .map(|(id, _, _)| *id)
                    .collect::<Vec<_>>();
                let _ = self.shared.engine.background_cancel(id, &requests);
            }
            let timers = queue
                .local
                .iter()
                .filter(|(kind, _)| kind == "timer")
                .filter_map(|(_, value)| value["id"].as_u64())
                .collect();
            let _ = self.shared.engine.discard_timers(timers);
            self.cancel_background(cx);
            self.report(Err(
                "Background commands cannot use window effects or timers".into(),
            ));
            return;
        }
        if queue.dirty {
            self.stale = true;
            self.schedule_save(cx);
            cx.notify();
        }
        for (id, method, mut params) in queue.requests {
            strip_reserved(&mut params);
            // Set here, after the script's own `_` keys are gone: the broker
            // shows a request the person already denied only when they ask.
            if user_gesture
                && method == "permissions.request"
                && let Some(params) = params.as_object_mut()
            {
                params.insert("_gesture".into(), json!(true));
            }
            let continuation = activation.as_ref().and_then(Activation::next);
            if continuation.is_some()
                && matches!(
                    method.as_str(),
                    "native.apps.open"
                        | "native.clipboard.paste"
                        | "native.clipboard.readText"
                        | "native.selection.readText"
                        | "native.confirm"
                        | "native.files.pick"
                        | "native.files.pickFolder"
                        | "native.files.saveText"
                )
                && let Some(params) = params.as_object_mut()
            {
                params.insert("_activation".into(), json!(true));
            }
            if self.host_requests.len() >= 32 || self.host_requests.contains_key(&id) {
                let settled = self
                    .shared
                    .engine
                    .settle(id, Err("Too many outstanding host requests".into()));
                self.report(settled);
                continue;
            }
            let epoch = self.epoch;
            let group = self.context.background_request();
            self.host_requests.insert(id, group.clone());
            let rx = if method == "native.workflows.execute" {
                self.start_native_workflow(id, params, group, cx)
            } else {
                self.context.request(&method, params)
            };
            cx.spawn(async move |this, cx| {
                let result = rx
                    .recv()
                    .await
                    .unwrap_or_else(|_| Err("The request was dropped".into()));
                let _ = this.update(cx, |this, cx| {
                    let Some(group) = this.host_requests.remove(&id) else {
                        return;
                    };
                    this.native_workflows.remove(&id);
                    if this.epoch != epoch
                        || group
                            .as_ref()
                            .is_some_and(|g| this.background_request.as_ref() != Some(g))
                    {
                        return;
                    }
                    // Propagate invocation ownership across host awaits; ordinary
                    // foreground events always enter with no background group.
                    let previous = this.context.background_request();
                    this.context.set_background_request(group);
                    let activation = continuation.and_then(|a| a.resume(&method, &result));
                    let settled = ScriptEngine::settle(&this.shared.engine, id, result);
                    this.report(settled);
                    this.after_js_activated(cx, false, activation);
                    this.context.set_background_request(previous);
                });
            })
            .detach();
        }
        let mut opened = false;
        for (kind, value) in queue.local {
            match kind.as_str() {
                "timer" => {
                    let Ok(slot) = self.timer_slots.clone().try_acquire_owned() else {
                        self.report(Err("Too many outstanding timers".into()));
                        continue;
                    };
                    let epoch = self.epoch;
                    let group = self.context.background_request();
                    let id = value["id"].as_u64().unwrap_or(0);
                    let delay = std::time::Duration::from_millis(
                        value["ms"].as_u64().unwrap_or(0).clamp(10, 86_400_000),
                    );
                    cx.spawn(async move |this, cx| {
                        cx.background_executor().timer(delay).await;
                        drop(slot);
                        let _ = this.update(cx, |this, cx| {
                            if this.epoch != epoch
                                || group
                                    .as_ref()
                                    .is_some_and(|g| this.background_request.as_ref() != Some(g))
                            {
                                return;
                            }
                            let previous = this.context.background_request();
                            this.context.set_background_request(group);
                            let fired = ScriptEngine::fire(&this.shared.engine, id);
                            this.report(fired);
                            this.after_js(cx, false);
                            this.context.set_background_request(previous);
                        });
                    })
                    .detach();
                }
                "copy" if user_gesture => cx.write_to_clipboard(ClipboardItem::new_string(
                    value.as_str().unwrap_or("").to_owned(),
                )),
                // One gesture opens at most one URL, so a click can't fan out
                // into a burst of browser tabs.
                "open_url" if user_gesture && !opened => {
                    if let Some(url) = value
                        .as_str()
                        .filter(|url| crate::links::web_url(url).is_ok())
                    {
                        opened = true;
                        cx.open_url(url);
                    }
                }
                "focus" => {
                    self.pending_focus = value.as_str().map(str::to_owned);
                    cx.notify();
                }
                _ => {}
            }
        }
        if let Some(id) = self.background_id {
            match self.shared.engine.background_result(id) {
                Ok(result) if result["done"] == true => {
                    let _ = self.shared.engine.background_collect(id);
                    self.background_id = None;
                    if let Some(error) = result["error"].as_str() {
                        self.background_request = None;
                        let _ = self.background.take().unwrap().try_send(Err(error.into()));
                    } else {
                        self.background_value = result["value"].clone();
                        self.background_done = true;
                        self.schedule_save(cx);
                    }
                }
                Err(error) => {
                    self.background_id = None;
                    self.background_request = None;
                    let _ = self.background.take().unwrap().try_send(Err(error));
                }
                _ => {}
            }
        }
    }
    fn save_failed(&mut self, error: &str) {
        self.save_failures = self.save_failures.saturating_add(1);
        self.shared
            .engine
            .logs
            .borrow_mut()
            .push_back(format!("error: Could not save changes: {error}"));
        self.error = Some("Couldn't save changes; retrying".into());
    }

    fn schedule_save(&mut self, cx: &mut Context<Self>) {
        if self.snapshot || !self.context.host.saves_checkpoints() {
            return;
        }
        if self.save_scheduled {
            return;
        }
        self.save_scheduled = true;
        let epoch = self.epoch;
        let delay = 400u64.saturating_mul(1 << self.save_failures.min(5));
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(std::time::Duration::from_millis(delay)).await;
            let request = this.update(cx, |this, cx| {
                if this.epoch != epoch { return None; }
                if this.context.is_retired() {
                    this.save_scheduled = false;
                    return None;
                }
                if !this.context.is_active() {
                    this.save_scheduled = false;
                    this.schedule_save(cx);
                    return None;
                }
                let started = Instant::now();
                let prepared = (|| -> Result<_, String> {
                    let checkpoint = this.shared.engine.checkpoint_text()?;
                    let state: Value = serde_json::from_str(&checkpoint).map_err(|e| e.to_string())?;
                    let mut data = this.shared.engine.data.borrow_mut();
                    let datasets = data.dirty().then(|| data.snapshot_text()).transpose()?;
                    Ok((checkpoint, state, datasets, data.version))
                })();
                let (checkpoint, state, datasets, data_version) = match prepared {
                    Ok(parts) => parts,
                    Err(error) => {
                        this.save_failed(&error);
                        this.save_scheduled = false;
                        this.schedule_save(cx);
                        cx.notify();
                        return None;
                    }
                };
                let (badge, sidebar_card) = this.shared.engine.sidebar_metadata_at(checkpoint);
                let mut params = json!({"state":state,"badge":badge,"sidebar_card":sidebar_card,"state_seq":this.context.sequence(),"writer":this.context.writer()});
                if let Some(request) = &this.background_request { params["_background_request"] = json!(request); }
                let mut perf = this.shared.perf.borrow_mut();
                perf.checkpoint_preparations += 1;
                perf.checkpoint_preparation_ms += started.elapsed().as_secs_f64() * 1000.;
                Some((state, data_version, this.context.clone(), params, datasets))
            }).ok().flatten();
            if let Some((state, data_version, context, params, datasets)) = request {
                let writer = context.writer();
                let result = send_checkpoint(&context, params, datasets).await;
                // Ownership can disappear independently of this engine (for example
                // when the watch disconnects). Never retry a refused checkpoint
                // without first reacquiring the window's mount.
                let remounted = if result.as_ref().err().is_some_and(|e| e.contains("View writer changed; reconnect before saving")) {
                    let (tx, rx) = async_channel::bounded(1);
                    let context = context.clone();
                    let writer = writer.clone();
                    context.runtime.clone().spawn(async move {
                        let result = context.host.remount(writer).await;
                        let _ = tx.send(result).await;
                    });
                    Some(rx.recv().await.unwrap_or_else(|_| Err("Mount request dropped".into())))
                } else { None };
                let _ = this.update(cx, |this, cx| {
                    if this.epoch != epoch { return; }
                    this.save_scheduled = false;
                    // A reply from a disconnected watch cannot update its successor.
                    if this.context.writer() != writer || !this.context.is_active() {
                        if !this.context.is_retired() { this.schedule_save(cx); }
                        return;
                    }
                    if let Some(Ok(saved)) = remounted
                        && saved["revision"].as_str() == Some(this.context.revision.as_str()) {
                            this.restore_datasets(saved["datasets"].clone());
                            this.restore_state(saved["state"].clone(), saved["state_seq"].as_u64().unwrap_or_default(), cx);
                            return;
                        }
                    match result {
                        Ok(value) if value["saved"] != false => {
                            this.saved_state = state;
                            this.shared.engine.data.borrow_mut().saved_version = data_version;
                            if let Some(sequence) = value["state_seq"].as_u64() { this.context.set_sequence(sequence); }
                            this.save_failures = 0;
                            if this.error.as_deref() == Some("Couldn't save changes; retrying") { this.error = None; }
                        }
                        Ok(value) => {
                            this.restore_state(value["state"].clone(), value["state_seq"].as_u64().unwrap_or_default(), cx);
                            return;
                        }
                        Err(error) => this.save_failed(&error),
                    }
                    let dirty = this.shared.engine.checkpoint().ok().as_ref() != Some(&this.saved_state);
                    if dirty || this.shared.engine.data.borrow().dirty() || this.save_failures > 0 { this.schedule_save(cx); }
                    else if this.background_done {
                        this.background_done = false;
                        this.background_request = None;
                        if let Some(done) = this.background.take() { let _ = done.try_send(Ok(std::mem::take(&mut this.background_value))); }
                    }
                    cx.notify();
                });
            }
        }).detach();
    }
}

impl NativeView for ScriptView {
    fn restore_state(&mut self, state: Value, sequence: u64, cx: &mut Context<Self>) {
        if self.context.mount_error().as_ref() == self.error.as_ref() {
            self.error = None;
        }
        cx.notify();
        if sequence <= self.context.sequence() {
            self.context.activate();
            self.start_init(cx);
            self.schedule_save(cx);
            return;
        }
        self.context.suspend();
        let live = match self.shared.engine.checkpoint() {
            Ok(live) => live,
            Err(error) => {
                self.report(Err(error));
                return;
            }
        };
        // Three-way merge: local edits (including removals) win conflicts;
        // unchanged keys come from the new saved state, which becomes our baseline.
        let mut merged = state.clone();
        script::StatePatch::between(&self.saved_state, &live).apply(&mut merged);
        let restart_init = !self.init_started || self.shared.engine.init_pending();
        self.epoch += 1;
        self.save_scheduled = false;
        self.save_failures = 0;
        if let Some(done) = self.background.take() {
            let _ = done.try_send(Err("Saved state was reloaded".into()));
        }
        self.background_done = false;
        self.background_id = None;
        self.background_request = None;
        for control in self.native_workflows.values() {
            control.cancel();
        }
        self.native_workflows.clear();
        self.host_requests.clear();
        self.context.set_background_request(None);
        let result = self.shared.engine.restore(&merged);
        self.report(result);
        self.saved_state = state;
        self.context.set_sequence(sequence);
        self.context.activate();
        if restart_init {
            self.init_started = false;
            self.start_init(cx);
        } else {
            self.after_js(cx, false);
        }
        self.schedule_save(cx);
    }
    fn background_scoped(
        &mut self,
        name: String,
        args: Value,
        request: String,
        cx: &mut Context<Self>,
    ) -> async_channel::Receiver<Result<Value, String>> {
        let previous = self.context.background_request();
        if self.context.is_active() && self.background.is_none() {
            self.background_request = Some(request.clone());
            self.context.set_background_request(Some(request));
        }
        let rx = self.background(name, args, cx);
        self.context.set_background_request(previous);
        rx
    }
    fn cancel_background(&mut self, cx: &mut Context<Self>) {
        if self.background.is_none() {
            return;
        }
        let group = self.background_request.take();
        let owned: Vec<_> = self
            .host_requests
            .iter()
            .filter(|(_, owner)| group.is_some() && **owner == group)
            .map(|(id, _)| *id)
            .collect();
        for id in &owned {
            self.host_requests.remove(id);
            if let Some(control) = self.native_workflows.remove(id) {
                control.cancel();
            }
        }
        if let Some(id) = self.background_id.take() {
            let result = self.shared.engine.background_cancel(id, &owned);
            self.report(result);
        }
        self.background_done = false;
        if let Some(done) = self.background.take() {
            let _ = done.try_send(Err("Background invocation was cancelled".into()));
        }
        cx.notify();
    }
    fn background(
        &mut self,
        name: String,
        args: Value,
        cx: &mut Context<Self>,
    ) -> async_channel::Receiver<Result<Value, String>> {
        let (tx, rx) = async_channel::bounded(1);
        if !self.context.is_active() || self.background.is_some() {
            let _ = tx.try_send(Err("View is reconnecting or already refreshing".into()));
        } else {
            self.background = Some(tx);
            self.background_done = false;
            let result = self.shared.engine.background_start(&name, &args);
            match result {
                Ok(id) => self.background_id = Some(id),
                Err(error) => {
                    self.background_request = None;
                    let _ = self.background.take().unwrap().try_send(Err(error));
                }
            }
            self.after_js(cx, false);
        }
        rx
    }
    fn runtime_activity(&self) -> Value {
        self.shared
            .engine
            .runtime_activity()
            .unwrap_or_else(|e| json!({"error":e}))
    }
    fn inspect(&self) -> Value {
        let mut value = self
            .shared
            .engine
            .inspect()
            .unwrap_or_else(|e| json!({"inspect_error": e}));
        if let Some(object) = value.as_object_mut() {
            object.insert("__perf".into(), self.perf());
            let logs = self.shared.engine.logs.borrow();
            object.insert(
                "__logs".into(),
                json!(logs.iter().rev().take(20).rev().collect::<Vec<_>>()),
            );
            if let Some(error) = &self.error {
                object.insert("__error".into(), json!(error));
            }
        }
        value
    }
    fn checkpoint(&self, _: &App) -> Value {
        self.shared
            .engine
            .checkpoint()
            .unwrap_or_else(|_| json!({}))
    }
    fn command(
        &mut self,
        name: &str,
        args: Value,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Result<Value, String> {
        if self.context.is_retired() {
            return Err(self
                .context
                .mount_error()
                .unwrap_or_else(|| "View is read-only".into()));
        }
        if name == "__perf" {
            return Ok(self.perf());
        }
        // ⌘F / Find in View: the script's own command, else its "search" input.
        if name == "focus_search" && !self.shared.engine.has_command(name) {
            let slot = self.inputs.get("search").ok_or("This view has no search")?;
            slot.editor.focus(window, cx);
            return Ok(json!({"focused": true}));
        }
        let result = self.shared.engine.command(name, &args);
        self.after_js(cx, false);
        result
    }
}

/// Keep every request beneath the broker's ordinary RPC limit. The final
/// checkpoint publishes the staged dataset through the same view commit path.
async fn send_checkpoint(
    context: &ViewContext,
    mut params: Value,
    datasets: Option<String>,
) -> Result<Value, String> {
    if let Some(body) = datasets {
        let upload = format!(
            "{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default()
        );
        let mut chunks = Vec::new();
        let mut start = 0;
        while start < body.len() {
            let mut end = (start + 32768).min(body.len());
            while !body.is_char_boundary(end) {
                end -= 1;
            }
            chunks.push(&body[start..end]);
            start = end;
        }
        for (index, text) in chunks.iter().enumerate() {
            let mut chunk = json!({"state_seq":params["state_seq"],"writer":params["writer"],"data_chunk":{"upload":upload,"index":index,"total":chunks.len(),"text":text}});
            if let Some(request) = params.get("_background_request") {
                chunk["_background_request"] = request.clone();
            }
            let response = context
                .request("views.state", chunk)
                .recv()
                .await
                .map_err(|_| "Dataset checkpoint dropped")??;
            if response["staged"] != true {
                return Ok(response);
            }
        }
        params["data_upload"] = json!(upload);
    }
    context
        .request("views.state", params)
        .recv()
        .await
        .map_err(|_| "Checkpoint request dropped".to_string())?
}

#[cfg(test)]
mod activation_tests {
    use super::*;
    use core::prelude::v1::test;

    #[test]
    fn live_revision_preserves_checkpoint_and_failed_script_leaves_old_generation_usable() {
        let source = "view({state:{count:1},render:state=>Text(String(state.count))})";
        let old = Engine::new(source, &json!({"count":9,"local":"keep"})).unwrap();
        let live = old.checkpoint().unwrap();
        let (next, state) = super::super::prepare_revision(
            source,
            json!({"saved":true,"count":1}),
            Some(live.clone()),
            Engine::new,
        )
        .unwrap();
        assert_eq!(state["count"], 9);
        assert_eq!(next.checkpoint().unwrap()["local"], "keep");
        assert_eq!(state["saved"], true);
        assert!(
            super::super::prepare_revision("view(", state, Some(live.clone()), Engine::new)
                .is_err()
        );
        assert_eq!(old.checkpoint().unwrap(), live);
        assert!(old.render().is_ok());
    }

    #[test]
    fn native_activation_has_a_shared_finite_request_budget() {
        let activation = Activation::new();
        let sibling = activation.clone();
        for _ in 0..32 {
            assert!(activation.next().is_some());
        }
        assert!(sibling.next().is_none());
        let resumed = sibling
            .resume("permissions.request", &Ok(json!({"approved":true})))
            .unwrap();
        assert!(
            resumed.next().is_none(),
            "Allow must not replenish the request budget"
        );
    }

    #[test]
    fn native_activation_expires_but_a_deliberate_prompt_answer_renews_its_continuation() {
        let mut expired = Activation::new();
        expired.deadline = Instant::now() - std::time::Duration::from_secs(1);
        assert!(expired.next().is_none());
        for (method, result) in [
            ("permissions.inspect", Ok(json!({"approved":true}))),
            ("permissions.request", Ok(json!({"approved":false}))),
            ("permissions.request", Err("cancelled".into())),
            ("native.confirm", Ok(json!(false))),
            ("native.files.pick", Ok(Value::Null)),
        ] {
            assert!(
                expired.clone().resume(method, &result).is_none(),
                "{method}"
            );
        }
        for (method, result) in [
            ("permissions.request", json!({"approved":true})),
            ("native.confirm", json!(true)),
            ("native.files.pick", json!([{"id":"file"}])),
            ("native.files.pickFolder", json!({"id":"folder"})),
            ("native.files.saveText", json!({"saved":true})),
        ] {
            assert!(
                expired
                    .clone()
                    .resume(method, &Ok(result))
                    .unwrap()
                    .next()
                    .is_some(),
                "{method}"
            );
        }
        assert!(
            expired.next().is_none(),
            "Other pending branches must stay expired"
        );
    }
}
