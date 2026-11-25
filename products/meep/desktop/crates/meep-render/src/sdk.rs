//! Each view owns a retained GPUI entity, state, and broker requests made
//! as that view, so the broker applies the view's own permissions.
use gpui_kit::*;
use serde_json::Value;
use std::rc::Rc;

#[cfg(not(target_family = "wasm"))]
mod context;
#[cfg(not(target_family = "wasm"))]
pub use crate::{FailureKind, HostError};
#[cfg(not(target_family = "wasm"))]
pub use context::{ViewContext, ViewHost};

pub trait NativeView: Render {
    fn inspect(&self) -> Value;
    /// Host-owned activity, without invoking a view's custom inspector.
    fn runtime_activity(&self) -> Value {
        serde_json::json!({"timers":[]})
    }
    /// State handed to the next generation of this view. Override to include
    /// transient UI state (drafts, filters, selection) omitted by inspect.
    fn checkpoint(&self, _cx: &App) -> Value {
        self.inspect()
    }
    fn restore_state(&mut self, _state: Value, _sequence: u64, _cx: &mut Context<Self>)
    where
        Self: Sized,
    {
    }
    fn background(
        &mut self,
        _name: String,
        _args: Value,
        _cx: &mut Context<Self>,
    ) -> async_channel::Receiver<Result<Value, String>>
    where
        Self: Sized,
    {
        let (tx, rx) = async_channel::bounded(1);
        let _ = tx.try_send(Err("Background commands require a script".into()));
        rx
    }
    fn background_scoped(
        &mut self,
        name: String,
        args: Value,
        _request: String,
        cx: &mut Context<Self>,
    ) -> async_channel::Receiver<Result<Value, String>>
    where
        Self: Sized,
    {
        self.background(name, args, cx)
    }
    fn cancel_background(&mut self, _cx: &mut Context<Self>)
    where
        Self: Sized,
    {
    }
    fn command(
        &mut self,
        name: &str,
        args: Value,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Result<Value, String>
    where
        Self: Sized;
}
type Command = Rc<dyn Fn(&str, Value, &mut Window, &mut App) -> Result<Value, String>>;
type Restore = Rc<dyn Fn(Value, u64, &mut App)>;
type BackgroundResult = async_channel::Receiver<Result<Value, String>>;
type Background = Rc<dyn Fn(String, Value, &mut App) -> BackgroundResult>;
type BackgroundScoped = Rc<dyn Fn(String, Value, String, &mut App) -> BackgroundResult>;
pub struct MountedView {
    pub view: AnyView,
    invoke: Command,
    inspect: Rc<dyn Fn(&App) -> Value>,
    runtime_activity: Rc<dyn Fn(&App) -> Value>,
    checkpoint: Rc<dyn Fn(&App) -> Value>,
    restore_state: Restore,
    background: Background,
    background_scoped: BackgroundScoped,
    cancel_background: Rc<dyn Fn(&mut App)>,
}
impl MountedView {
    pub fn restore_state(&self, state: Value, sequence: u64, cx: &mut App) {
        (self.restore_state)(state, sequence, cx);
    }
    pub fn background(
        &self,
        name: String,
        args: Value,
        cx: &mut App,
    ) -> async_channel::Receiver<Result<Value, String>> {
        (self.background)(name, args, cx)
    }
    pub fn background_scoped(
        &self,
        name: String,
        args: Value,
        request: String,
        cx: &mut App,
    ) -> async_channel::Receiver<Result<Value, String>> {
        (self.background_scoped)(name, args, request, cx)
    }
    pub fn cancel_background(&self, cx: &mut App) {
        (self.cancel_background)(cx);
    }
    pub fn command(
        &self,
        name: &str,
        args: Value,
        window: &mut Window,
        cx: &mut App,
    ) -> Result<Value, String> {
        (self.invoke)(name, args, window, cx)
    }
    pub fn inspect(&self, cx: &App) -> Value {
        (self.inspect)(cx)
    }
    pub fn runtime_activity(&self, cx: &App) -> Value {
        (self.runtime_activity)(cx)
    }
    pub fn checkpoint(&self, cx: &App) -> Value {
        (self.checkpoint)(cx)
    }
}
pub fn mount<V: NativeView + 'static>(
    cx: &mut App,
    build: impl FnOnce(&mut Context<V>) -> V,
) -> MountedView {
    let entity = cx.new(build);
    let invoke = entity.clone();
    let inspect = entity.clone();
    let runtime_activity = entity.clone();
    let checkpoint = entity.clone();
    let restore_state = entity.clone();
    let background = entity.clone();
    let background_scoped = entity.clone();
    let cancel_background = entity.clone();
    MountedView {
        view: entity.into(),
        invoke: Rc::new(move |name, args, window, cx| {
            invoke.update(cx, |view, cx| view.command(name, args, window, cx))
        }),
        inspect: Rc::new(move |cx| inspect.read(cx).inspect()),
        runtime_activity: Rc::new(move |cx| runtime_activity.read(cx).runtime_activity()),
        checkpoint: Rc::new(move |cx| checkpoint.read(cx).checkpoint(cx)),
        restore_state: Rc::new(move |state, sequence, cx| {
            restore_state.update(cx, |v, cx| v.restore_state(state, sequence, cx));
        }),
        background: Rc::new(move |name, args, cx| {
            background.update(cx, |v, cx| v.background(name, args, cx))
        }),
        background_scoped: Rc::new(move |name, args, request, cx| {
            background_scoped.update(cx, |v, cx| v.background_scoped(name, args, request, cx))
        }),
        cancel_background: Rc::new(move |cx| {
            cancel_background.update(cx, |v, cx| v.cancel_background(cx))
        }),
    }
}

/// Shared native design blocks available to every generated view.
pub use crate::ui;
