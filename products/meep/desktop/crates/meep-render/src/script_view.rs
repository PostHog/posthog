//! Renders a script view's element tree with real GPUI and the shared `ui`
//! blocks. JavaScript runs only when something happens (an event, a source
//! result, a timer, a key, a command); painting, layout, scrolling and text
//! input stay native.
#[path = "script_view/build.rs"]
mod build;
#[path = "script_view/components.rs"]
mod components;
#[path = "script_view/images.rs"]
mod images;
#[cfg(all(not(target_family = "wasm"), feature = "ui-tests"))]
pub use images::seed_preview_image;
#[cfg(not(target_family = "wasm"))]
pub use images::{forget_file_images, forget_remote_images};
#[path = "script_view/inputs.rs"]
mod inputs;
#[path = "script_view/layers.rs"]
mod layers;
#[path = "script_view/props.rs"]
mod props;
use crate::script_contract::COMPONENTS;
#[path = "script_view/interact.rs"]
mod interact;
#[path = "script_view/regions.rs"]
mod regions;
#[cfg(feature = "ui-tests")]
pub use regions::set_enabled as set_regions_enabled;
#[cfg(not(target_family = "wasm"))]
#[path = "script_view/native.rs"]
mod native;
#[path = "script_view/scene_view.rs"]
mod scene_view;
#[path = "script_view/selectable.rs"]
mod selectable;
#[path = "script_view/styles.rs"]
mod styles;
#[path = "script_view/table.rs"]
mod table;
#[path = "script_view/tree.rs"]
mod tree;
#[cfg(target_family = "wasm")]
#[path = "script_view/web.rs"]
mod web;
#[cfg(not(target_family = "wasm"))]
#[path = "script_view/workflow.rs"]
mod workflow;
use crate::script::{self, Engine};
use crate::script_engine::ScriptEngine;
use crate::sdk::ui;
#[cfg(not(target_family = "wasm"))]
use crate::sdk::{self, MountedView, NativeView, ViewContext};
use gpui_kit::assets::IconName;
use gpui_kit::component::{
    checkbox::Checkbox,
    input::{InputEvent, InputState, TextareaState},
    menu::{ContextMenuExt, DropdownMenu, PopupMenuItem},
    switch::Switch,
    *,
};
use gpui_kit::component::{
    date_picker::{DatePicker, DatePickerEvent, DatePickerState, DateTime as PickerDateTime},
    time_field::{TimeField, TimeFieldEvent, TimeFieldState, TimePrecision},
};
use gpui_kit::prelude::FluentBuilder;
use gpui_kit::*;
use serde_json::{Value, json};
use std::{cell::RefCell, collections::HashMap, rc::Rc};
#[cfg(target_family = "wasm")]
use web::ViewContext;

#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
#[cfg(target_family = "wasm")]
use web_time::Instant;

#[cfg(not(target_family = "wasm"))]
pub use native::mount;
#[cfg(not(target_family = "wasm"))]
pub use native::{mount_snapshot, mount_with_empty};
#[cfg(target_family = "wasm")]
pub use web::{mount, revise};

use build::Build;
use inputs::{Editor, Slot};
use layers::*;
use props::*;
use tree::{Node, Tree};

actions!(script_view, [CancelDrag]);

/// Escape cancels a script drag. Bound in the `ScriptDrag` context, which the
/// view sets only while a drag is active, so it outranks the window's own
/// Escape binding then and never otherwise.
pub fn bind_keys(cx: &mut App) {
    cx.bind_keys([KeyBinding::new("escape", CancelDrag, Some("ScriptDrag"))]);
}

#[derive(Clone, Default, serde::Serialize)]
pub struct Perf {
    renders: u64,
    last_render_js_ms: f64,
    max_render_js_ms: f64,
    last_build_ms: f64,
    max_build_ms: f64,
    rows_built: u64,
    native_rows_built: u64,
    /// Data tables that ran their query; redraws with an unchanged dataset
    /// and query reuse the last result.
    table_queries: u64,
    max_row_js_ms: f64,
    row_js_ms_total: f64,
    events: u64,
    last_event_js_ms: f64,
    max_event_js_ms: f64,
    /// Renders of cached regions (see `regions`); frames that reuse a region
    /// don't count.
    region_renders: u64,
    /// Parsing a render into the typed tree (see `tree`), styles included.
    last_tree_ms: f64,
    #[cfg(not(target_family = "wasm"))]
    checkpoint_preparations: u64,
    #[cfg(not(target_family = "wasm"))]
    checkpoint_preparation_ms: f64,
}

#[cfg(not(target_family = "wasm"))]
impl Perf {
    pub fn changes_since(&self, before: &Self) -> Value {
        json!({
            "script_renders": self.renders - before.renders,
            "element_events": self.events - before.events,
            "region_renders": self.region_renders - before.region_renders,
            "checkpoint_preparations": self.checkpoint_preparations - before.checkpoint_preparations,
            "checkpoint_preparation_ms_total": self.checkpoint_preparation_ms - before.checkpoint_preparation_ms,
        })
    }
}

/// A control the window draws inside a view because it is the window's own:
/// the agent and model selector is the same one the app's sessions use,
/// backed by the same catalog. Views reach it only through their props and
/// one change handler; it never gives a script a path around the broker.
/// A host control's change handler.
pub type OnChange = Rc<dyn Fn(Value, &mut App)>;
/// Latest argument source per handler for pointer-rate events.
type Coalesced = HashMap<(String, &'static str), Rc<dyn Fn() -> Value>>;
pub struct HostElement<'a> {
    pub kind: &'a str,
    pub key: &'a str,
    pub props: &'a Value,
    pub on_change: OnChange,
}
pub type HostElements = Rc<dyn Fn(HostElement, &mut Window, &mut App) -> Option<AnyElement>>;

/// Lets the window draw its own controls inside this view. Without a host
/// (screenshots, tests), those elements draw a static stand-in.
pub fn set_host_elements(view: &AnyView, host: HostElements, cx: &mut App) {
    if let Ok(view) = view.clone().downcast::<ScriptView>() {
        view.update(cx, |view, cx| {
            *view.shared.host.borrow_mut() = Some(host);
            cx.notify();
        });
    }
}

struct Shared {
    engine: Engine,
    /// The window's own controls, when a window hosts this view.
    host: RefCell<Option<HostElements>>,
    rows: RefCell<HashMap<(u32, usize), Rc<Node>>>,
    /// Resolved styles by kind and props, shared by renders, rows and cells.
    memo: RefCell<styles::Memo>,
    /// Retained list scroll positions and the last `scrollTo` applied.
    scrolls: RefCell<HashMap<String, (UniformListScrollHandle, Option<u64>)>>,
    /// Each data table's rows in display order, kept while its dataset and
    /// query are unchanged so redraws never filter or sort again.
    tables: RefCell<HashMap<String, table::Rows>>,
    /// Scene density levels baked into textures, by scene name.
    scene_images: RefCell<HashMap<String, Vec<scene_view::DensityImage>>>,
    #[cfg(not(target_family = "wasm"))]
    images: RefCell<images::Cache>,
    perf: RefCell<Perf>,
    /// Last painted bounds of measured elements, for local pointer positions.
    bounds: RefCell<HashMap<String, Bounds<Pixels>>>,
    /// Latest argument source per handler for pointer-rate events, read and
    /// sent once per frame.
    coalesced: RefCell<Coalesced>,
    /// This render's handler IDs for events that run after their cause.
    late: RefCell<HashMap<(String, &'static str), u32>>,
    frame_scheduled: std::cell::Cell<bool>,
    drag: RefCell<Option<interact::ActiveDrag>>,
    /// Elements a drag let go of, by key: how far they were moved and when,
    /// so they settle back (or leave from there) instead of jumping.
    settle: RefCell<HashMap<String, (Point<Pixels>, Instant)>>,
    /// Where the left button last went down on a draggable element.
    pressed: std::cell::Cell<Option<Point<Pixels>>>,
    scroll_handles: RefCell<HashMap<String, ScrollHandle>>,
    scroll_targets: RefCell<HashMap<String, Value>>,
    layout_reports: RefCell<HashMap<String, (Instant, u32)>>,
    regions: RefCell<regions::Regions>,
    /// The clip the view's own content paints under, so layers can keep it.
    clip: std::cell::Cell<Option<ViewClip>>,
}
impl Shared {
    fn new(engine: Engine, memo: styles::Memo) -> Self {
        Self {
            engine,
            rows: RefCell::default(),
            scrolls: RefCell::default(),
            tables: RefCell::default(),
            scene_images: RefCell::default(),
            #[cfg(not(target_family = "wasm"))]
            images: RefCell::default(),
            perf: RefCell::default(),
            bounds: RefCell::default(),
            coalesced: RefCell::default(),
            late: RefCell::default(),
            frame_scheduled: Default::default(),
            drag: RefCell::default(),
            settle: RefCell::default(),
            pressed: Default::default(),
            scroll_handles: RefCell::default(),
            scroll_targets: RefCell::default(),
            layout_reports: RefCell::default(),
            regions: RefCell::default(),
            clip: Default::default(),
            memo: RefCell::new(memo),
            host: RefCell::default(),
        }
    }

    /// Allows 20 `onLayout` reports per element per second, so a view that
    /// resizes itself in answer to its own size can't spin.
    fn layout_budget(&self, key: &str) -> bool {
        let now = Instant::now();
        let mut reports = self.layout_reports.borrow_mut();
        let entry = reports.entry(key.to_owned()).or_insert((now, 0));
        if now.duration_since(entry.0) > std::time::Duration::from_secs(1) {
            *entry = (now, 0);
        }
        entry.1 += 1;
        entry.1 <= 20
    }
    /// Rows are rendered by JS once per tree generation and then reused, so
    /// scrolling back and forth costs no JavaScript.
    fn row(&self, function: u32, index: usize, list: &str) -> Result<Rc<Node>, String> {
        if let Some(row) = self.rows.borrow().get(&(function, index)) {
            return Ok(row.clone());
        }
        let started = Instant::now();
        let row = ScriptEngine::row(&self.engine, function, index)?;
        script::check_tree(&row)?;
        let ms = started.elapsed().as_secs_f64() * 1000.0;
        let mut perf = self.perf.borrow_mut();
        perf.rows_built += 1;
        perf.row_js_ms_total += ms;
        perf.max_row_js_ms = perf.max_row_js_ms.max(ms);
        drop(perf);
        let row = Node::fragment(row, format!("{list}.{index}"), &mut self.memo.borrow_mut())?;
        self.rows
            .borrow_mut()
            .insert((function, index), row.clone());
        Ok(row)
    }
}

pub struct ScriptView {
    shared: Rc<Shared>,
    context: ViewContext,
    focus: FocusHandle,
    tree: Option<Rc<Tree>>,
    stale: bool,
    error: Option<String>,
    inputs: HashMap<String, Slot>,
    /// The tree the text fields were last matched against. Cleared by
    /// typing, so a controlled field's value is checked again.
    inputs_synced: Option<std::rc::Weak<Tree>>,
    pending_focus: Option<String>,
    #[cfg(not(target_family = "wasm"))]
    save_scheduled: bool,
    #[cfg(not(target_family = "wasm"))]
    saved_state: Value,
    save_failures: u32,
    #[cfg(not(target_family = "wasm"))]
    epoch: u64,
    #[cfg(not(target_family = "wasm"))]
    background: Option<async_channel::Sender<Result<Value, String>>>,
    #[cfg(not(target_family = "wasm"))]
    background_done: bool,
    #[cfg(not(target_family = "wasm"))]
    background_value: Value,
    #[cfg(not(target_family = "wasm"))]
    background_id: Option<u32>,
    #[cfg(not(target_family = "wasm"))]
    background_request: Option<String>,
    #[cfg(not(target_family = "wasm"))]
    host_requests: HashMap<u32, Option<String>>,
    #[cfg(not(target_family = "wasm"))]
    native_workflows: HashMap<u32, meep_workflows::runner::Control>,
    #[cfg(not(target_family = "wasm"))]
    workflow_generations: Rc<RefCell<HashMap<String, u64>>>,
    #[cfg(not(target_family = "wasm"))]
    timer_slots: std::sync::Arc<tokio::sync::Semaphore>,
    #[cfg(not(target_family = "wasm"))]
    init_started: bool,
    #[cfg(not(target_family = "wasm"))]
    snapshot: bool,
    #[cfg(target_family = "wasm")]
    web_timers: usize,
    #[cfg(target_family = "wasm")]
    web_badge: Option<String>,
    #[cfg(target_family = "wasm")]
    web_card: Option<Value>,
    empty_visible: bool,
    empty: Rc<dyn Fn() -> AnyElement>,
}

/// A script's render, checked and parsed into the typed tree.
fn parse(rendered: Result<Value, String>, memo: &mut styles::Memo) -> Result<Tree, String> {
    let value = rendered?;
    script::check_tree(&value)?;
    Tree::compile(value, memo)
}

/// `cmd-shift-k`, `down`, `enter`: the names scripts use in `keys`.
fn key_name(keystroke: &Keystroke) -> String {
    let m = &keystroke.modifiers;
    let mut name = String::new();
    for (on, part) in [
        (m.control, "ctrl-"),
        (m.alt, "alt-"),
        (m.shift, "shift-"),
        (m.platform, "cmd-"),
        (m.function, "fn-"),
    ] {
        if on {
            name.push_str(part);
        }
    }
    name.push_str(&keystroke.key);
    name
}

impl ScriptView {
    #[cfg(feature = "ui-tests")]
    pub fn preview_no_tree(&mut self, cx: &mut Context<Self>) {
        self.tree = None;
        self.stale = false;
        cx.notify();
    }
    /// The keys of the subtrees rendering as cached regions.
    #[cfg(feature = "ui-tests")]
    pub fn region_keys(&self) -> Vec<String> {
        self.shared.regions.borrow().keys()
    }
    /// Render the script again on the next frame, as a state change does.
    #[cfg(feature = "ui-tests")]
    pub fn mark_stale(&mut self, cx: &mut Context<Self>) {
        self.stale = true;
        cx.notify();
    }
    fn report(&mut self, result: Result<(), String>) {
        if let Err(error) = result {
            self.shared
                .engine
                .logs
                .borrow_mut()
                .push_back(format!("error: {error}"));
            self.error = Some(error);
        }
    }
    #[cfg(feature = "ui-tests")]
    pub fn insert_scene(&mut self, name: &str, scene: crate::scene::Scene, cx: &mut Context<Self>) {
        self.shared
            .engine
            .scenes
            .borrow_mut()
            .scenes
            .insert(name.into(), Rc::new(scene));
        self.stale = true;
        cx.notify();
    }
    /// Replaces the datasets even when the view changed them since its last save.
    #[cfg(feature = "ui-tests")]
    pub fn replace_datasets(&mut self, value: Value) {
        self.shared.engine.data.borrow_mut().load(value);
        self.stale = true;
    }
    /// An imported view's needs, from the broker's mount reply.
    #[cfg(not(target_family = "wasm"))]
    pub fn set_host_needs(&mut self, needs: &Value) {
        if let Err(error) = self.shared.engine.set_host_needs(needs) {
            self.shared
                .engine
                .logs
                .borrow_mut()
                .push_back(format!("error: imported needs: {error}"));
        }
    }
    pub fn restore_datasets(&mut self, value: Value) {
        if !self.shared.engine.data.borrow().dirty() {
            self.shared.engine.data.borrow_mut().load(value);
            self.stale = true;
        }
    }
    /// Runs a script handler. `gesture` is true only for discrete user
    /// input (a click, key press, typing, a release); it is what lets the
    /// handler copy or open a URL. Layout, hover, pointer moves, scrolls and
    /// anything coalesced or debounced pass false: they can fire without the
    /// user meaning to act.
    fn invoke(&mut self, handler: u32, argument: Value, gesture: bool, cx: &mut Context<Self>) {
        if self.context.is_retired() {
            return;
        }
        let started = Instant::now();
        let result = ScriptEngine::invoke(&self.shared.engine, handler, &argument);
        let ms = started.elapsed().as_secs_f64() * 1000.0;
        {
            let mut perf = self.shared.perf.borrow_mut();
            perf.events += 1;
            perf.last_event_js_ms = ms;
            perf.max_event_js_ms = perf.max_event_js_ms.max(ms);
        }
        self.report(result);
        self.after_js(cx, gesture);
    }
    /// Puts a dragged element back where it started.
    fn cancel_drag(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        cx.stop_active_drag(window);
        if let Some((h, argument)) = self.shared.end_drag(true) {
            self.invoke(h, argument, true, cx);
        }
        cx.notify();
    }
    fn key_down(&mut self, event: &KeyDownEvent, _: &mut Window, cx: &mut Context<Self>) {
        if self.context.is_retired() {
            return;
        }

        match ScriptEngine::key(&self.shared.engine, &key_name(&event.keystroke)) {
            Ok(true) => {
                cx.stop_propagation();
                self.after_js(cx, true);
            }
            Ok(false) => {}
            Err(error) => self.report(Err(error)),
        }
    }
    /// While a script element is dragged, follow every pointer move in the
    /// window (not just over the view) and finish on release. Registered
    /// only during a drag, so an idle view adds no window listeners.
    fn drag_listeners(&self, cx: &mut Context<Self>) -> AnyElement {
        let active = self.shared.drag.borrow().is_some();
        let (shared, weak) = (self.shared.clone(), cx.weak_entity());
        canvas(
            |_, _, _| {},
            move |_, _, window, _| {
                if !active {
                    return;
                }
                let (moves, moved) = (shared.clone(), weak.clone());
                window.on_mouse_event(move |e: &MouseMoveEvent, phase, window, cx| {
                    if phase != DispatchPhase::Capture {
                        return;
                    }
                    let (key, argument) = {
                        let mut drag = moves.drag.borrow_mut();
                        let Some(drag) = drag.as_mut() else { return };
                        drag.current = e.position;
                        (drag.key.clone(), drag.live())
                    };
                    if moves.late(&key, "onDrag").is_some() {
                        moves.coalesce(
                            moved.clone(),
                            &key,
                            "onDrag",
                            Rc::new(move || argument.clone()),
                            window,
                        );
                    }
                    let _ = moved.update(cx, |_, cx| cx.notify());
                });
                let (ends, ended) = (shared.clone(), weak.clone());
                window.on_mouse_event(move |e: &MouseUpEvent, phase, _, cx| {
                    if phase != DispatchPhase::Capture || e.button != MouseButton::Left {
                        return;
                    }
                    let (ends, ended) = (ends.clone(), ended.clone());
                    cx.defer(move |cx| ends.finish_drag(&ended, cx));
                });
            },
        )
        .absolute()
        .size_0()
        .into_any_element()
    }
    #[cfg(not(target_family = "wasm"))]
    fn perf(&self) -> Value {
        serde_json::to_value(&*self.shared.perf.borrow()).unwrap_or_default()
    }
    #[cfg(not(target_family = "wasm"))]
    pub fn performance_snapshot(&self) -> Perf {
        self.shared.perf.borrow().clone()
    }
}

/// Drops the top-level `_`-prefixed keys a script put in a host request.
/// The broker reads those as host-set control fields (`_background_request`,
/// `_host_auth`), and the window's connection is host-authenticated, so a
/// script must never supply them; the host adds its own afterwards.
#[cfg(not(target_family = "wasm"))]
pub fn strip_reserved(params: &mut Value) {
    if let Some(params) = params.as_object_mut() {
        params.retain(|key, _| !key.starts_with('_'));
    }
}

impl Render for ScriptView {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        // Colors are resolved into the tree, so a new palette renders anew.
        if self
            .tree
            .as_ref()
            .is_some_and(|tree| tree.palette != styles::palette())
        {
            self.stale = true;
        }
        if self.stale {
            self.stale = false;
            let started = Instant::now();
            let rendered = ScriptEngine::render(&self.shared.engine);
            let ms = started.elapsed().as_secs_f64() * 1000.0;
            let started = Instant::now();
            let rendered = parse(rendered, &mut self.shared.memo.borrow_mut());
            {
                let mut perf = self.shared.perf.borrow_mut();
                perf.renders += 1;
                perf.last_render_js_ms = ms;
                perf.max_render_js_ms = perf.max_render_js_ms.max(ms);
                perf.last_tree_ms = started.elapsed().as_secs_f64() * 1000.0;
            }
            match rendered {
                Ok(tree) => {
                    self.tree = Some(Rc::new(tree));
                    if self.save_failures == 0 && self.context.mount_error().is_none() {
                        self.error = None;
                    }
                    self.shared.rows.borrow_mut().clear();
                }
                Err(error) => self.error = Some(error),
            }
        }
        let started = Instant::now();
        if let Some(tree) = self.tree.clone() {
            // Fields change only with the tree or with typing; animation
            // frames skip the walk.
            let synced = self
                .inputs_synced
                .as_ref()
                .is_some_and(|w| std::ptr::eq(w.as_ptr(), Rc::as_ptr(&tree)));
            if !synced {
                self.prepare_inputs(&tree, window, cx);
                self.inputs_synced = Some(Rc::downgrade(&tree));
            }
        }
        if let Some(key) = self.pending_focus.take()
            && let Some(slot) = self.inputs.get(&key)
        {
            slot.editor.focus(window, cx);
        }
        let inputs = self
            .inputs
            .iter()
            .map(|(key, slot)| (key.clone(), slot.editor.clone()))
            .collect();
        let read_only = self.context.is_retired();
        let build = Build {
            scope: format!("script-{}", cx.entity_id()).into(),
            shared: self.shared.clone(),
            weak: cx.weak_entity(),
            inputs: Rc::new(inputs),
            read_only,
            region_root: None,
            region_key: None,
            control: false,
        };
        self.shared
            .regions
            .borrow_mut()
            .begin(regions::BuildInputs::new(&build, self.tree.clone()));
        let body = match &self.tree {
            Some(tree) => build.node(&tree.root, window, cx),
            None if self.empty_visible => (self.empty)(),
            None => div().into_any_element(),
        };
        // Sheets and dialogs, placed against the whole view (see `layers`).
        let layers: Vec<AnyElement> = self
            .tree
            .iter()
            .flat_map(|tree| tree.layers.iter())
            .map(|node| build.layer(node, window, cx))
            .collect();
        self.shared.regions.borrow_mut().end();
        if let Some(error) = self.context.mount_error() {
            self.error = Some(error);
        }
        let ms = started.elapsed().as_secs_f64() * 1000.0;
        {
            let mut perf = self.shared.perf.borrow_mut();
            perf.last_build_ms = ms;
            perf.max_build_ms = perf.max_build_ms.max(ms);
        }
        let drag_layer = self.drag_listeners(cx);
        let dragging = self.shared.drag.borrow().is_some();
        div()
            .id("script-view")
            .when(dragging, |el| el.key_context("ScriptDrag"))
            .on_action(cx.listener(|this, _: &CancelDrag, window, cx| this.cancel_drag(window, cx)))
            .track_focus(&self.focus)
            .size_full()
            .flex()
            .flex_col()
            .min_h_0()
            .on_key_down(cx.listener(|this, event: &KeyDownEvent, window, cx| {
                this.key_down(event, window, cx)
            }))
            // Clicking empty space puts keyboard focus inside the view so its
            // `keys` work; clicks on fields keep their own focus.
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(|this, _, window, cx| {
                    if !this.focus.contains_focused(window, cx) {
                        this.focus.focus(window, cx);
                    }
                }),
            )
            .when_some(self.error.clone(), |el, error| {
                el.child(
                    div()
                        .p(px(12.))
                        .flex_shrink_0()
                        .child(ui::error_message("script-error", error)),
                )
            })
            .child(div().flex_1().min_h_0().flex().flex_col().child(body))
            .relative()
            .children(layers)
            .child(drag_layer)
            .child(clip_probe(self.shared.clone()))
    }
}

/// The block editor with this id in a mounted script view (previews, tests).
#[cfg(feature = "ui-tests")]
pub fn block_editor(
    view: &AnyView,
    id: &str,
    cx: &App,
) -> Option<Entity<crate::block_editor::BlockEditor>> {
    let view = view.clone().downcast::<ScriptView>().ok()?;
    match &view.read(cx).inputs.get(id)?.editor {
        Editor::Blocks(editor) => Some(editor.clone()),
        _ => None,
    }
}

/// Stage a new generation from the latest checkpoint before replacing the old
/// one. Both broker-delivered edits and browser replay edits take this path.
/// A mount error leaves the existing entity and generation untouched.
pub fn prepare_revision<T, E>(
    source: &str,
    mut saved: Value,
    live: Option<Value>,
    mount: impl FnOnce(&str, &Value) -> Result<T, E>,
) -> Result<(T, Value), E> {
    if let Some(snapshot) = live {
        if let (Some(base), Some(snapshot)) = (saved.as_object_mut(), snapshot.as_object()) {
            base.extend(snapshot.clone());
        } else {
            saved = snapshot;
        }
    }
    let next = mount(source, &saved)?;
    Ok((next, saved))
}

impl ScriptView {
    #[cfg(any(target_family = "wasm", feature = "ui-tests"))]
    pub fn sidebar_badge(&self) -> Option<String> {
        #[cfg(target_family = "wasm")]
        {
            self.web_badge.clone()
        }
        #[cfg(not(target_family = "wasm"))]
        {
            self.shared.engine.sidebar_metadata().0
        }
    }
    /// The badge object behind the sidebar hover card (browser preview).
    #[cfg(target_family = "wasm")]
    pub fn sidebar_card_value(&self) -> Option<Value> {
        self.web_card.clone()
    }
    #[cfg(target_family = "wasm")]
    pub fn preview_checkpoint(&self) -> Result<Value, String> {
        self.shared.engine.checkpoint()
    }
}
