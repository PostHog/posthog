use std::{rc::Rc, time::Duration};

use crate::{
    ActiveTheme, AxisExt, Sizable, Size, StyledExt, checkbox::checkbox_check_icon, h_flex,
    text::Text, tooltip::ComponentTooltip, v_flex,
};
use crate::{StyleSized as _, ThemeStyled as _};
use gpui::{
    AnyElement, App, Axis, ElementId, InteractiveElement, IntoElement, ParentElement, RenderOnce,
    SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder, relative, rems,
};
use gpui_base::{Radio as BaseRadio, RadioGroup as BaseRadioGroup};

/// A Radio element.
///
/// This is not included the Radio group implementation, you can manage the group by yourself.
#[derive(IntoElement)]
pub struct Radio {
    base: BaseRadio,
    style: StyleRefinement,
    id: ElementId,
    label: Option<Text>,
    /// The announced name, when the visible label is not it.
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
    checked: bool,
    disabled: bool,
    tab_stop: bool,
    tab_index: isize,
    size: Size,
    on_click: Option<Rc<dyn Fn(&bool, &mut Window, &mut App) + 'static>>,
    tooltip: ComponentTooltip,
    position_in_set: Option<usize>,
    size_of_set: Option<usize>,
    focus_ring_enabled: bool,
}

impl Radio {
    /// Create a new Radio element with the given id.
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id = id.into();
        Self {
            base: BaseRadio::new(id.clone()),
            id,
            style: StyleRefinement::default(),
            label: None,
            accessibility_label: None,
            children: Vec::new(),
            checked: false,
            disabled: false,
            tab_index: 0,
            tab_stop: true,
            size: Size::default(),
            on_click: None,
            tooltip: ComponentTooltip::default(),
            position_in_set: None,
            size_of_set: None,
            focus_ring_enabled: true,
        }
    }

    /// Set tooltip text for the radio.
    pub fn tooltip(mut self, tooltip: impl Into<SharedString>) -> Self {
        self.tooltip.text = Some((tooltip.into(), None));
        self
    }

    /// Overrides how long the pointer must rest before the tooltip shows.
    ///
    /// Defaults to [`gpui_base::TooltipDefaults::show_delay`].
    pub fn tooltip_show_delay(mut self, delay: Duration) -> Self {
        self.tooltip.show_delay = Some(delay);
        self
    }

    /// Set the label of the Radio element.
    pub fn label(mut self, label: impl Into<Text>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Set the name a screen reader announces, when the visible label is not
    /// it.
    ///
    /// A radio's name comes from its [`label`](Self::label) by default. Setting
    /// this replaces the announced name without changing what is displayed.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Set the checked state of the Radio element, default is `false`.
    pub fn checked(mut self, checked: bool) -> Self {
        self.checked = checked;
        self
    }

    /// Set the disabled state of the Radio element, default is `false`.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Set the tab index for the Radio element, default is `0`.
    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }

    /// Set the tab stop for the Radio element, default is `true`.
    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }

    /// Alias for [`Self::on_change`]. The last callback registered with either name wins.
    pub fn on_click(self, handler: impl Fn(&bool, &mut Window, &mut App) + 'static) -> Self {
        self.on_change(handler)
    }

    /// Handle a requested checked value from pointer or keyboard activation.
    ///
    /// This is a controlled value: the owner must write the requested value and
    /// call `cx.notify()` to render it. Disabled controls do not call the handler.
    /// This and [`Self::on_click`] share one callback; chaining them replaces
    /// the previous handler instead of calling both.
    pub fn on_change(mut self, handler: impl Fn(&bool, &mut Window, &mut App) + 'static) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }
}

impl Sizable for Radio {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl crate::FocusableExt for Radio {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl Styled for Radio {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl InteractiveElement for Radio {
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Radio {}

impl ParentElement for Radio {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for Radio {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let checked = self.checked;
        let has_content = self.label.is_some() || !self.children.is_empty();
        let indicator_size = rems(match self.size {
            Size::XSmall => 0.75,
            Size::Small => 0.875,
            Size::Large => 1.125,
            _ => 1.,
        });
        let focus_handle = window
            .use_keyed_state(self.id.clone(), cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone();
        let is_focused = focus_handle.is_focused(window);
        let disabled = self.disabled;
        let accessibility_label = self
            .accessibility_label
            .clone()
            .or_else(|| self.label.as_ref().map(|label| label.get_text(cx)));

        let (border_color, bg) = if checked {
            (cx.theme().primary, cx.theme().primary)
        } else {
            (cx.theme().input, cx.theme().input.opacity(0.5))
        };
        let (border_color, bg) = if disabled {
            (border_color.opacity(0.5), bg.opacity(0.5))
        } else {
            (border_color, bg)
        };

        self.base
            .id(self.id.clone())
            .checked(self.checked)
            .disabled(self.disabled)
            .track_focus(&focus_handle)
            .tab_stop(self.tab_stop)
            .tab_index(self.tab_index)
            .when_some(accessibility_label, |this, label| {
                this.accessibility_label(label)
            })
            .when_some(
                self.position_in_set.zip(self.size_of_set),
                |this, (position, size)| this.set_position(position, size),
            )
            .h_flex()
            .gap_x_2()
            .text_color(cx.theme().foreground)
            .items_start()
            .line_height(relative(1.))
            .rounded(cx.theme().radius * 0.5)
            .when(is_focused && self.focus_ring_enabled, |this| {
                this.focus_ring_style(window, cx)
            })
            .map(|this| match self.size {
                Size::Size(_) => this,
                size => this.input_text_size(size),
            })
            .refine_style(&self.style)
            .child(
                div()
                    .relative()
                    .size(indicator_size)
                    // Center on the first 1.25em line, including when the label wraps.
                    .when(has_content, |this| this.mt(indicator_size * 0.125))
                    .flex_shrink_0()
                    .rounded_full_style(cx)
                    .border_1()
                    .border_color(border_color)
                    .map(|this| match self.checked {
                        false => this.bg(cx.theme().input_background()),
                        true if disabled => this.bg(bg),
                        true => this.bg(cx.theme().tokens.primary),
                    })
                    .child(checkbox_check_icon(
                        self.id, self.size, checked, disabled, window, cx,
                    )),
            )
            .when(!self.children.is_empty() || self.label.is_some(), |this| {
                this.child(
                    v_flex()
                        .w_full()
                        .line_height(relative(1.25))
                        .gap_1()
                        .when_some(self.label, |this, label| {
                            this.child(
                                div()
                                    .size_full()
                                    .when(self.disabled, |this| {
                                        this.text_color(cx.theme().muted_foreground)
                                    })
                                    .child(label),
                            )
                        })
                        .children(self.children),
                )
            })
            .on_mouse_down(gpui::MouseButton::Left, |_, window, _| {
                window.prevent_default()
            })
            .when_some(self.on_click.clone(), |this, on_click| {
                this.on_change(move |next, _, window, cx| {
                    window.prevent_default();
                    on_click(&next, window, cx);
                })
            })
            .map(|this| self.tooltip.apply(this))
    }
}

/// A Radio group element.
#[derive(IntoElement)]
pub struct RadioGroup {
    id: ElementId,
    style: StyleRefinement,
    radios: Vec<Radio>,
    layout: Axis,
    selected_index: Option<usize>,
    disabled: bool,
    on_click: Option<Rc<dyn Fn(&usize, &mut Window, &mut App) + 'static>>,
}

impl RadioGroup {
    /// Creates a radio group with vertical layout and no selected item.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default().flex_1(),
            on_click: None,
            layout: Axis::Vertical,
            selected_index: None,
            disabled: false,
            radios: vec![],
        }
    }

    /// Create a new Radio group with default Vertical layout.
    pub fn vertical(id: impl Into<ElementId>) -> Self {
        Self::new(id)
    }

    /// Create a new Radio group with Horizontal layout.
    pub fn horizontal(id: impl Into<ElementId>) -> Self {
        Self::new(id).layout(Axis::Horizontal)
    }

    /// Set the layout of the Radio group. Default is `Axis::Vertical`.
    pub fn layout(mut self, layout: Axis) -> Self {
        self.layout = layout;
        self
    }

    /// Alias for [`Self::on_change`]. The last callback registered with either name wins.
    pub fn on_click(self, handler: impl Fn(&usize, &mut Window, &mut App) + 'static) -> Self {
        self.on_change(handler)
    }

    /// Handle a requested selected index from pointer or keyboard activation.
    ///
    /// This is a controlled value: the owner must write the requested value and
    /// call `cx.notify()` to render it. Disabled controls do not call the handler.
    /// This and [`Self::on_click`] share one callback; chaining them replaces
    /// the previous handler instead of calling both.
    pub fn on_change(mut self, handler: impl Fn(&usize, &mut Window, &mut App) + 'static) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Set the selected index.
    pub fn selected_index(mut self, index: Option<usize>) -> Self {
        self.selected_index = index;
        self
    }

    /// Set the disabled state.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Add a child Radio element.
    pub fn child(mut self, child: impl Into<Radio>) -> Self {
        self.radios.push(child.into());
        self
    }

    /// Add multiple child Radio elements.
    pub fn children(mut self, children: impl IntoIterator<Item = impl Into<Radio>>) -> Self {
        self.radios.extend(children.into_iter().map(Into::into));
        self
    }
}

impl Styled for RadioGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl From<&'static str> for Radio {
    fn from(label: &'static str) -> Self {
        Self::new(label).label(label)
    }
}

impl From<SharedString> for Radio {
    fn from(label: SharedString) -> Self {
        Self::new(label.clone()).label(label)
    }
}

impl From<String> for Radio {
    fn from(label: String) -> Self {
        Self::new(SharedString::from(label.clone())).label(SharedString::from(label))
    }
}

impl RenderOnce for RadioGroup {
    fn render(self, _window: &mut Window, _cx: &mut App) -> impl IntoElement {
        let on_click = self.on_click;
        let disabled = self.disabled;
        let selected_ix = self.selected_index;

        let base = if self.layout.is_vertical() {
            v_flex()
        } else {
            h_flex().w_full().flex_wrap()
        };

        let total = self.radios.len();
        BaseRadioGroup::new(self.id)
            .axis(self.layout)
            .refine_style(&self.style)
            .child(
                base.gap_3()
                    .children(self.radios.into_iter().enumerate().map(|(ix, mut radio)| {
                        let checked = selected_ix == Some(ix);

                        radio.id = ix.into();
                        radio.position_in_set = Some(ix + 1);
                        radio.size_of_set = Some(total);
                        let item_disabled = radio.disabled;
                        radio
                            .disabled(disabled || item_disabled)
                            .checked(checked)
                            .when_some(on_click.clone(), |this, on_click| {
                                this.on_click(move |_, window, cx| on_click(&ix, window, cx))
                            })
                    })),
            )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_explicit_accessibility_label_replaces_the_visible_one() {
        let plain = Radio::new("automatic").label("Automatic");
        assert_eq!(plain.accessibility_label, None);
        assert!(matches!(
            &plain.label,
            Some(Text::String(label)) if label.as_ref() == "Automatic"
        ));

        let named = Radio::new("automatic")
            .label("Automatic")
            .accessibility_label("Choose automatic mode");
        assert_eq!(
            named.accessibility_label.as_deref(),
            Some("Choose automatic mode"),
            "an explicit name must win over the visible label"
        );
        assert!(
            matches!(
                &named.label,
                Some(Text::String(label)) if label.as_ref() == "Automatic"
            ),
            "and must not change what is drawn"
        );
    }
}
