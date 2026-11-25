use std::{rc::Rc, time::Duration};

use gpui::{
    App, ClipboardItem, ElementId, IntoElement, RenderOnce, SharedString, Window,
    prelude::FluentBuilder,
};
use rust_i18n::t;

use crate::{
    IconName, Sizable, Size,
    button::{Button, ButtonVariants as _},
};

/// An element that provides clipboard copy functionality.
#[derive(IntoElement)]
pub struct Clipboard {
    id: ElementId,
    value: SharedString,
    value_fn: Option<Rc<dyn Fn(&mut Window, &mut App) -> SharedString>>,
    on_copied: Option<Rc<dyn Fn(SharedString, &mut Window, &mut App)>>,
    tooltip_text: Option<SharedString>,
    tooltip_show_delay: Option<Duration>,
    accessibility_label: Option<SharedString>,
    size: Size,
}

impl Sizable for Clipboard {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Clipboard {
    /// Create a new Clipboard element with the given ID.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            value: SharedString::default(),
            value_fn: None,
            on_copied: None,
            tooltip_text: None,
            tooltip_show_delay: None,
            accessibility_label: None,
            size: Size::XSmall,
        }
    }

    /// Set tooltip text for the clipboard button.
    pub fn tooltip(mut self, tooltip: impl Into<SharedString>) -> Self {
        self.tooltip_text = Some(tooltip.into());
        self
    }

    /// Overrides how long the pointer must rest before the tooltip shows.
    ///
    /// Defaults to [`gpui_base::TooltipDefaults::show_delay`].
    pub fn tooltip_show_delay(mut self, delay: Duration) -> Self {
        self.tooltip_show_delay = Some(delay);
        self
    }

    /// Set the name a screen reader announces. Defaults to the localized "Copy".
    ///
    /// The clipboard button shows only an icon, so it has no visible label to
    /// read, and its tooltip is a hint rather than a name.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Set the value for copying to the clipboard. Default is an empty string.
    pub fn value(mut self, value: impl Into<SharedString>) -> Self {
        self.value = value.into();
        self
    }

    /// Set the value of the clipboard to the result of the given function. Default is None.
    ///
    /// When used this, the copy value will use the result of the function.
    pub fn value_fn(
        mut self,
        value: impl Fn(&mut Window, &mut App) -> SharedString + 'static,
    ) -> Self {
        self.value_fn = Some(Rc::new(value));
        self
    }

    /// Set a callback to be invoked when the content is copied to the clipboard.
    pub fn on_copied<F>(mut self, handler: F) -> Self
    where
        F: Fn(SharedString, &mut Window, &mut App) + 'static,
    {
        self.on_copied = Some(Rc::new(handler));
        self
    }
}

impl RenderOnce for Clipboard {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = window.use_keyed_state(self.id.clone(), cx, |_, _| ClipboardState::default());

        let value = self.value.clone();
        let clipboard_id = self.id.clone();
        let copied = state.read(cx).copied;
        let value_fn = self.value_fn.clone();

        Button::new(clipboard_id)
            .icon(if copied {
                IconName::Check
            } else {
                IconName::Copy
            })
            .ghost()
            .with_size(self.size)
            .when_some(self.tooltip_text, |this, text| this.tooltip(text))
            .when_some(self.tooltip_show_delay, |this, delay| {
                this.tooltip_show_delay(delay)
            })
            .accessibility_label(
                self.accessibility_label
                    .unwrap_or_else(|| t!("Copy").into()),
            )
            .when(!copied, |this| {
                this.on_click({
                    let state = state.clone();
                    let on_copied = self.on_copied.clone();
                    move |_, window, cx| {
                        cx.stop_propagation();
                        let value = value_fn
                            .as_ref()
                            .map(|f| f(window, cx))
                            .unwrap_or_else(|| value.clone());
                        cx.write_to_clipboard(ClipboardItem::new_string(value.to_string()));
                        state.update(cx, |state, cx| {
                            state.copied = true;
                            cx.notify();
                        });

                        let state = state.clone();
                        cx.spawn(async move |cx| {
                            cx.background_executor().timer(Duration::from_secs(2)).await;
                            _ = state.update(cx, |state, cx| {
                                state.copied = false;
                                cx.notify();
                            });
                        })
                        .detach();

                        if let Some(on_copied) = &on_copied {
                            on_copied(value.clone(), window, cx);
                        }
                    }
                })
            })
    }
}

#[doc(hidden)]
#[derive(Default)]
struct ClipboardState {
    copied: bool,
}
