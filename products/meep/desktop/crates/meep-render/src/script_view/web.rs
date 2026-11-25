//! Fixture-only browser lifecycle. No persistence, broker, filesystem or network.
use super::*;

type Dispatch = fn(&str, &Value) -> Result<Value, String>;
pub(super) struct ViewContext {
    dispatch: Dispatch,
    retired: std::cell::Cell<bool>,
}
impl ViewContext {
    pub fn is_retired(&self) -> bool {
        self.retired.get()
    }
    pub fn mount_error(&self) -> Option<String> {
        None
    }
}

pub fn mount(source: &str, dispatch: Dispatch, cx: &mut App) -> Result<Entity<ScriptView>, String> {
    mount_with_state(source, &json!({}), dispatch, cx)
}
fn mount_with_state(
    source: &str,
    state: &Value,
    dispatch: Dispatch,
    cx: &mut App,
) -> Result<Entity<ScriptView>, String> {
    let engine = Engine::new(source, state)?;
    let mut memo = styles::Memo::default();
    let tree = parse(ScriptEngine::render(&engine), &mut memo)?;
    let (web_badge, web_card) = engine.badge().unwrap_or_default();
    let entity = cx.new(|cx| ScriptView {
        shared: Rc::new(Shared::new(engine, memo)),
        context: ViewContext {
            dispatch,
            retired: std::cell::Cell::new(false),
        },
        focus: cx.focus_handle(),
        tree: Some(Rc::new(tree)),
        stale: false,
        error: None,
        inputs: HashMap::new(),
        inputs_synced: None,
        pending_focus: None,
        save_failures: 0,
        web_timers: 0,
        web_badge,
        web_card,
        empty_visible: true,
        empty: Rc::new(|| div().into_any_element()),
    });
    let weak = entity.downgrade();
    let app = RefCell::new(cx.to_async());
    entity.read(cx).shared.engine.set_wake(move || {
        let _ = weak.update(&mut *app.borrow_mut(), |this, cx| {
            this.drain_browser_jobs(cx)
        });
    });
    entity.update(cx, |this, cx| {
        let result = ScriptEngine::init(&this.shared.engine);
        this.report(result);
        this.after_js(cx, false);
    });
    Ok(entity)
}
impl ScriptView {
    pub(super) fn after_js(&mut self, cx: &mut Context<Self>, _gesture: bool) {
        if self.context.is_retired() {
            return;
        }
        let queue = self.shared.engine.take_queue();
        if queue.dirty {
            (self.web_badge, self.web_card) = self.shared.engine.badge().unwrap_or_default();
            self.stale = true;
            cx.notify();
        }
        // Settle on a later GPUI turn: browser Promise continuations run on the
        // browser's microtask queue, then notify the retained view via __host_dirty.
        for (id, method, params) in queue.requests {
            let result = (self.context.dispatch)(&method, &params);
            cx.spawn(async move |this, cx| {
                let _ = this.update(cx, |this, cx| {
                    let result = ScriptEngine::settle(&this.shared.engine, id, result);
                    this.report(result);
                    this.after_js(cx, false);
                });
            })
            .detach();
        }
        for (kind, value) in queue.local {
            match kind.as_str() {
                "timer" if self.web_timers < 128 => {
                    self.web_timers += 1;
                    let id = value["id"].as_u64().unwrap_or_default();
                    let delay = std::time::Duration::from_millis(
                        value["ms"].as_u64().unwrap_or(0).clamp(10, 86_400_000),
                    );
                    cx.spawn(async move |this, cx| {
                        cx.background_executor().timer(delay).await;
                        let _ = this.update(cx, |this, cx| {
                            this.web_timers -= 1;
                            let result = ScriptEngine::fire(&this.shared.engine, id);
                            this.report(result);
                            this.after_js(cx, false);
                        });
                    })
                    .detach();
                }
                "focus" => {
                    self.pending_focus = value.as_str().map(str::to_owned);
                    cx.notify();
                }
                _ => self.report(Err(format!("{kind} is unavailable in the web preview"))),
            }
        }
    }
    /// Called after browser microtasks; requests and dirty state may arrive
    /// after the synchronous engine entry has already returned.
    pub fn drain_browser_jobs(&mut self, cx: &mut Context<Self>) {
        self.after_js(cx, false);
    }
}

/// An edit mounts a fresh generation, including init/parse, while retaining the
/// live script state. Publish only after preparation succeeds, as in AppView.
pub fn revise(
    current: &Entity<ScriptView>,
    source: &str,
    cx: &mut App,
) -> Result<Entity<ScriptView>, String> {
    let live = current.read(cx).shared.engine.checkpoint()?;
    let dispatch = current.read(cx).context.dispatch;
    let (next, _) = super::prepare_revision(source, json!({}), Some(live), |source, state| {
        mount_with_state(source, state, dispatch, cx)
    })?;
    let old = current.read(cx);
    old.context.retired.set(true);
    old.shared.engine.retire();
    Ok(next)
}
