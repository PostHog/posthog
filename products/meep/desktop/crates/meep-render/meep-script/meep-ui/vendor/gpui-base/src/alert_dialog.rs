use gpui::prelude::FluentBuilder as _;
use gpui::{
    App, ClickEvent, FocusHandle, InteractiveElement as _, IntoElement, MouseButton, ParentElement,
    Pixels, RenderOnce, Role, StatefulInteractiveElement as _, StyleRefinement, Styled, Window,
    div,
};
use smallvec::SmallVec;

use crate::StyledExt as _;
use crate::{Dialog, DialogChangeReason, DialogHandle};

macro_rules! alert_part {
    ($name:ident, $id:literal) => {
        alert_part!($name, $id, false);
    };
    ($name:ident, $id:literal, $occlude:literal) => {
        #[derive(IntoElement)]
        pub struct $name {
            style: StyleRefinement,
            children: SmallVec<[gpui::AnyElement; 2]>,
        }
        impl $name {
            pub fn new() -> Self {
                Self {
                    style: StyleRefinement::default(),
                    children: SmallVec::new(),
                }
            }
        }
        impl Default for $name {
            fn default() -> Self {
                Self::new()
            }
        }
        impl ParentElement for $name {
            fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
                self.children.extend(elements);
            }
        }
        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }
        impl RenderOnce for $name {
            fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
                div()
                    .id($id)
                    // Presses on the popup stay off the backdrop behind it.
                    .when($occlude, |this| this.occlude())
                    .children(self.children)
                    .refine_style(&self.style)
            }
        }
    };
}

alert_part!(AlertDialogBackdrop, "alert-dialog-backdrop");
alert_part!(AlertDialogPopup, "alert-dialog-popup", true);
alert_part!(AlertDialogTitle, "alert-dialog-title");
alert_part!(AlertDialogDescription, "alert-dialog-description");

#[derive(IntoElement)]
pub struct AlertDialogTrigger {
    trigger: gpui::AnyElement,
    open: std::rc::Rc<dyn Fn(&mut Window, &mut App)>,
    handle: Option<DialogHandle>,
}
impl AlertDialogTrigger {
    pub fn new(trigger: impl IntoElement) -> Self {
        Self {
            trigger: trigger.into_any_element(),
            open: std::rc::Rc::new(|_, _| {}),
            handle: None,
        }
    }
    pub fn on_open(mut self, open: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.open = std::rc::Rc::new(open);
        self
    }
    pub fn handle(mut self, handle: DialogHandle) -> Self {
        self.handle = Some(handle);
        self
    }
}
impl RenderOnce for AlertDialogTrigger {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        div()
            .on_mouse_down(MouseButton::Left, move |_, window, cx| {
                if let Some(handle) = self.handle.as_ref() {
                    handle.set_open(true, DialogChangeReason::TriggerPress, window, cx);
                }
                (self.open)(window, cx);
                cx.stop_propagation();
            })
            .child(self.trigger)
    }
}

macro_rules! alert_close_part {
    ($name:ident, $id:literal) => {
        #[derive(IntoElement)]
        pub struct $name {
            style: StyleRefinement,
            children: SmallVec<[gpui::AnyElement; 1]>,
        }
        impl $name {
            pub fn new() -> Self {
                Self {
                    style: StyleRefinement::default(),
                    children: SmallVec::new(),
                }
            }
        }
        impl Default for $name {
            fn default() -> Self {
                Self::new()
            }
        }
        impl ParentElement for $name {
            fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
                self.children.extend(elements);
            }
        }
        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }
        impl RenderOnce for $name {
            fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
                div()
                    .id($id)
                    .on_click(|_, window, cx| {
                        window.dispatch_action(Box::new(crate::actions::Cancel), cx)
                    })
                    .children(self.children)
                    .refine_style(&self.style)
            }
        }
    };
}
alert_close_part!(AlertDialogClose, "alert-dialog-close");
alert_close_part!(AlertDialogCancel, "alert-dialog-cancel");

/// Wrapper that dispatches the alert dialog's confirm action.
#[derive(IntoElement)]
pub struct AlertDialogAction {
    style: StyleRefinement,
    children: SmallVec<[gpui::AnyElement; 1]>,
}

impl AlertDialogAction {
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: SmallVec::new(),
        }
    }
}

impl Default for AlertDialogAction {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for AlertDialogAction {
    fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for AlertDialogAction {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AlertDialogAction {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        div()
            .id("alert-dialog-action")
            .on_click(|_, window, cx| {
                window.dispatch_action(Box::new(crate::actions::Confirm { secondary: false }), cx)
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// Alert-dialog specialization of the Base modal host.
pub struct AlertDialog(Dialog);

impl AlertDialog {
    pub fn new(cx: &mut App) -> Self {
        Self(
            Dialog::new(cx)
                .role(Role::AlertDialog)
                .close_on_backdrop_press(false),
        )
    }
    pub fn open(mut self, open: bool) -> Self {
        self.0 = self.0.open(open);
        self
    }
    pub fn handle(mut self, handle: DialogHandle) -> Self {
        self.0 = self.0.handle(handle);
        self
    }
    pub fn on_open_change(
        mut self,
        handler: impl Fn(bool, DialogChangeReason, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.0 = self.0.on_open_change(handler);
        self
    }
    pub fn backdrop(mut self, element: impl IntoElement) -> Self {
        self.0 = self.0.backdrop(element);
        self
    }
    pub fn popup(mut self, element: impl IntoElement) -> Self {
        self.0 = self.0.popup(element);
        self
    }
    pub fn close_on_escape(mut self, value: bool) -> Self {
        self.0 = self.0.close_on_escape(value);
        self
    }
    pub fn dismiss_below_y(mut self, value: Pixels) -> Self {
        self.0 = self.0.dismiss_below_y(value);
        self
    }
    pub fn on_ok(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.0 = self.0.on_ok(handler);
        self
    }
    pub fn on_cancel(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.0 = self.0.on_cancel(handler);
        self
    }
    pub fn on_close(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.0 = self.0.on_close(handler);
        self
    }
    #[doc(hidden)]
    pub fn layer(mut self, index: usize, topmost: bool) -> Self {
        self.0 = self.0.layer(index, topmost);
        self
    }
    #[doc(hidden)]
    pub fn focus_handle(mut self, value: FocusHandle) -> Self {
        self.0 = self.0.focus_handle(value);
        self
    }
    #[doc(hidden)]
    pub fn request_close(
        mut self,
        handler: impl Fn(bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.0 = self.0.request_close(handler);
        self
    }
}

impl Styled for AlertDialog {
    fn style(&mut self) -> &mut StyleRefinement {
        self.0.style()
    }
}
impl ParentElement for AlertDialog {
    fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
        self.0.extend(elements);
    }
}
impl IntoElement for AlertDialog {
    type Element = <Dialog as IntoElement>::Element;
    fn into_element(self) -> Self::Element {
        self.0.into_element()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{Context, Render, div, point, px};
    use std::{cell::Cell, rc::Rc};

    struct Harness {
        close_requested: Rc<Cell<bool>>,
    }

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let close_requested = self.close_requested.clone();
            AlertDialog::new(cx)
                .request_close(move |_, _, _| close_requested.set(true))
                .backdrop(div().size(px(200.)))
        }
    }

    #[gpui::test]
    fn backdrop_is_not_closable_by_default(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let close_requested = Rc::new(Cell::new(false));
        let (_, cx) = cx.add_window_view({
            let close_requested = close_requested.clone();
            move |_, _| Harness { close_requested }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        cx.simulate_click(point(px(20.), px(20.)), Default::default());

        assert!(!close_requested.get());
    }

    /// The host centers its popup by default; styling the alert dialog
    /// replaces that layout just as it does for a plain dialog.
    #[gpui::test]
    fn host_style_positions_the_popup(cx: &mut gpui::TestAppContext) {
        use gpui::{Bounds, canvas};

        struct TopLeft(Rc<Cell<Bounds<Pixels>>>);
        impl Render for TopLeft {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                let bounds = self.0.clone();
                AlertDialog::new(cx).items_start().justify_start().popup(
                    canvas(move |popup, _, _| bounds.set(popup), |_, _, _, _| {}).size(px(100.)),
                )
            }
        }

        cx.update(crate::init);
        let bounds = Rc::new(Cell::new(Bounds::default()));
        let (_, cx) = cx.add_window_view({
            let bounds = bounds.clone();
            move |_, _| TopLeft(bounds)
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(bounds.get().origin, point(px(0.), px(0.)));
    }
}
