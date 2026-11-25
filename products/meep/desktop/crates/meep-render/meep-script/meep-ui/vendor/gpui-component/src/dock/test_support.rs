//! Panel doubles shared by the skin's tests.
//!
//! This lives beside the production modules rather than inside one module's
//! `mod tests` because the same double is needed by more than one of them: a
//! tab group and a dock each hand a panel to a different frame, and the
//! question — did the panel get a height? — is the same. Mirrors
//! `gpui_base::dock::test_support`.

use std::{cell::Cell, rc::Rc};

use gpui::{
    App, AppContext as _, Context, Entity, EventEmitter, FocusHandle, Focusable, IntoElement,
    Pixels, Render, Styled as _, Window, div,
};
use gpui_base::dock::PanelEvent;

use crate::{ElementExt as _, dock::Panel};

/// A panel that records the height its container actually gave it.
///
/// The defect it exists for is invisible to every behavioral test: a panel
/// whose content region resolves to zero height still activates, still
/// persists, and still opens a window. Only a measurement sees it.
pub(crate) struct MeasuredProbe {
    focus_handle: FocusHandle,
    height: Rc<Cell<Pixels>>,
}

impl MeasuredProbe {
    pub(crate) fn new(height: Rc<Cell<Pixels>>, cx: &mut App) -> Entity<Self> {
        cx.new(|cx| Self {
            focus_handle: cx.focus_handle(),
            height,
        })
    }
}

impl gpui_base::dock::Panel for MeasuredProbe {
    fn panel_name(&self) -> &'static str {
        "MeasuredProbe"
    }
}

impl Panel for MeasuredProbe {}
impl EventEmitter<PanelEvent> for MeasuredProbe {}

impl Focusable for MeasuredProbe {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for MeasuredProbe {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        let height = self.height.clone();
        div()
            .size_full()
            .on_prepaint(move |bounds, _, _| height.set(bounds.size.height))
    }
}

/// A probe that records the whole box it was given, not only its height.
///
/// A dock's fault is a width fault -- a dock that never states its extent stops
/// being a column and takes whatever the row hands it -- so asking about it
/// needs the measurement `MeasuredProbe` does not keep.
pub(crate) struct SizedProbe {
    focus_handle: FocusHandle,
    size: Rc<Cell<gpui::Size<Pixels>>>,
}

impl SizedProbe {
    pub(crate) fn new(size: Rc<Cell<gpui::Size<Pixels>>>, cx: &mut App) -> Entity<Self> {
        cx.new(|cx| Self {
            focus_handle: cx.focus_handle(),
            size,
        })
    }
}

impl gpui_base::dock::Panel for SizedProbe {
    fn panel_name(&self) -> &'static str {
        "SizedProbe"
    }
}

impl Panel for SizedProbe {}
impl EventEmitter<PanelEvent> for SizedProbe {}

impl Focusable for SizedProbe {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for SizedProbe {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        let size = self.size.clone();
        div()
            .size_full()
            .on_prepaint(move |bounds, _, _| size.set(bounds.size))
    }
}

/// A [`MeasuredProbe`] whose `visible` can be switched off.
///
/// Hiding the only panel of a slot is the one edit that takes a whole slot out
/// of a split without changing the tree, so it is the only way to ask whether
/// the *drawn* slots still fill the split.
pub(crate) struct HideableProbe {
    focus_handle: FocusHandle,
    visible: bool,
    height: Rc<Cell<Pixels>>,
}

impl HideableProbe {
    pub(crate) fn new(height: Rc<Cell<Pixels>>, cx: &mut App) -> Entity<Self> {
        cx.new(|cx| Self {
            focus_handle: cx.focus_handle(),
            visible: true,
            height,
        })
    }

    pub(crate) fn set_visible(&mut self, visible: bool, cx: &mut Context<Self>) {
        self.visible = visible;
        cx.notify();
    }
}

impl gpui_base::dock::Panel for HideableProbe {
    fn panel_name(&self) -> &'static str {
        "HideableProbe"
    }

    fn visible(&self, _: &App) -> bool {
        self.visible
    }
}

impl Panel for HideableProbe {}
impl EventEmitter<PanelEvent> for HideableProbe {}

impl Focusable for HideableProbe {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for HideableProbe {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        let height = self.height.clone();
        div()
            .size_full()
            .on_prepaint(move |bounds, _, _| height.set(bounds.size.height))
    }
}
