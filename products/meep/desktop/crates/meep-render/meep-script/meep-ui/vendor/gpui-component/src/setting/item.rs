use gpui::{
    AnyElement, App, Axis, Div, InteractiveElement as _, IntoElement, ParentElement, SharedString,
    Stateful, Styled, Window, div, prelude::FluentBuilder as _,
};
use std::{any::TypeId, ops::Deref, rc::Rc};

use crate::{
    ActiveTheme as _, AxisExt, StyledExt as _,
    label::Label,
    setting::{
        AnySettingField, ElementField, RenderOptions,
        fields::{
            BoolField, DropdownField, NumberField, ResetHandler, SettingFieldRender, StringField,
        },
    },
    text::Text,
    v_flex,
};

/// Setting item.
#[derive(Clone)]
pub enum SettingItem {
    /// A normal setting item with a title, description, and field.
    Item {
        title: SharedString,
        description: Option<Text>,
        keywords: Vec<SharedString>,
        layout: Axis,
        disabled: bool,
        field: Rc<dyn AnySettingField>,
    },
    /// A full custom element to render.
    Element {
        disabled: bool,
        keywords: Vec<SharedString>,
        /// Optional custom reset behavior. The first closure reports whether
        /// the item is "dirty" (controls reset button visibility), the second
        /// performs the reset.
        reset_handler: Option<ResetHandler>,
        render: Rc<dyn Fn(&RenderOptions, &mut Window, &mut App) -> AnyElement + 'static>,
    },
}

impl SettingItem {
    /// Create a new setting item.
    pub fn new<F>(title: impl Into<SharedString>, field: F) -> Self
    where
        F: AnySettingField + 'static,
    {
        SettingItem::Item {
            title: title.into(),
            description: None,
            layout: Axis::Horizontal,
            disabled: false,
            keywords: Vec::new(),
            field: Rc::new(field),
        }
    }

    /// Create a new custom element setting item with a render closure.
    pub fn render<R, E>(render: R) -> Self
    where
        E: IntoElement,
        R: Fn(&RenderOptions, &mut Window, &mut App) -> E + 'static,
    {
        SettingItem::Element {
            disabled: false,
            keywords: Vec::new(),
            reset_handler: None,
            render: Rc::new(move |options, window, cx| {
                render(options, window, cx).into_any_element()
            }),
        }
    }

    /// Provide custom reset behavior for a custom element item.
    ///
    /// Only applies to [`SettingItem::Element`] (created via
    /// [`SettingItem::render`]). When set, the page-level reset button will
    /// appear while `is_dirty` returns true, and clicking it invokes `reset`.
    ///
    /// - `is_dirty` reports whether the item differs from its default state.
    /// - `reset` performs the reset.
    pub fn on_reset<D, R>(mut self, is_dirty: D, reset: R) -> Self
    where
        D: Fn(&App) -> bool + 'static,
        R: Fn(&mut Window, &mut App) + 'static,
    {
        match &mut self {
            SettingItem::Element { reset_handler, .. } => {
                *reset_handler = Some((Rc::new(is_dirty), Rc::new(reset)));
            }
            // `on_reset` is meaningless for a value-bearing item: use the
            // field's own `default_value` / `SettingField::on_reset` instead.
            SettingItem::Item { .. } => {
                debug_assert!(
                    false,
                    "SettingItem::on_reset only applies to SettingItem::Element; \
                     use SettingField::default_value or SettingField::on_reset for a normal item"
                );
            }
        }
        self
    }

    /// Set additional keywords used only for search matching (not rendered).
    ///
    /// For example, an item titled "Enable Two-factor auth" can be made
    /// searchable via "MFA". This is also useful for custom elements that
    /// have no title/description but should still show up in search results.
    pub fn keywords<I, S>(mut self, keywords: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<SharedString>,
    {
        let keywords: Vec<SharedString> = keywords.into_iter().map(Into::into).collect();
        match &mut self {
            SettingItem::Item { keywords: k, .. } => *k = keywords,
            SettingItem::Element { keywords: k, .. } => *k = keywords,
        }
        self
    }

    /// Set whether the setting item is disabled, default is false.
    ///
    /// A disabled item is rendered with reduced opacity. For
    /// [`SettingItem::Item`] the underlying field is also rendered in a
    /// non-interactive state. For [`SettingItem::Element`] the `disabled` flag
    /// is forwarded via [`RenderOptions::disabled`] so the custom renderer can
    /// disable its interactive controls.
    pub fn disabled(mut self, disabled: bool) -> Self {
        match &mut self {
            SettingItem::Item { disabled: d, .. } => *d = disabled,
            SettingItem::Element { disabled: d, .. } => *d = disabled,
        }
        self
    }

    /// Set the description of the setting item.
    ///
    /// Only applies to [`SettingItem::Item`].
    pub fn description(mut self, description: impl Into<Text>) -> Self {
        match &mut self {
            SettingItem::Item { description: d, .. } => {
                *d = Some(description.into());
            }
            SettingItem::Element { .. } => {}
        }
        self
    }

    /// Set the layout of the setting item.
    ///
    /// Only applies to [`SettingItem::Item`].
    pub fn layout(mut self, layout: Axis) -> Self {
        match &mut self {
            SettingItem::Item { layout: l, .. } => {
                *l = layout;
            }
            SettingItem::Element { .. } => {}
        }
        self
    }

    pub(crate) fn is_match(&self, query: &str, cx: &App) -> bool {
        match self {
            SettingItem::Item {
                title,
                description,
                keywords,
                ..
            } => {
                let q = &query.to_lowercase();
                title.to_lowercase().contains(q)
                    || description
                        .as_ref()
                        .map_or(false, |d| d.get_text(cx).to_lowercase().contains(q))
                    || keywords.iter().any(|s| s.to_lowercase().contains(q))
            }
            // We need to show all custom elements when not searching.
            SettingItem::Element { keywords, .. } => {
                let q = &query.to_lowercase();
                query.is_empty() || keywords.iter().any(|s| s.to_lowercase().contains(q))
            }
        }
    }

    pub(crate) fn is_resettable(&self, cx: &App) -> bool {
        match self {
            SettingItem::Item { field, .. } => field.is_resettable(cx),
            SettingItem::Element { reset_handler, .. } => reset_handler
                .as_ref()
                .is_some_and(|(is_dirty, _)| is_dirty(cx)),
        }
    }

    pub(crate) fn reset(&self, window: &mut Window, cx: &mut App) {
        match self {
            SettingItem::Item { field, .. } => field.reset(window, cx),
            SettingItem::Element { reset_handler, .. } => {
                if let Some((_, reset)) = reset_handler.as_ref() {
                    reset(window, cx);
                }
            }
        }
    }

    fn render_field(
        title: SharedString,
        field: Rc<dyn AnySettingField>,
        options: RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> impl IntoElement {
        let field_type = field.field_type();
        let style = field.style().clone();
        let type_id = field.deref().type_id();
        let renderer: Box<dyn SettingFieldRender> = match type_id {
            t if t == std::any::TypeId::of::<bool>() => {
                Box::new(BoolField::new(field_type.is_switch(), title))
            }
            t if t == TypeId::of::<f64>() && field_type.is_number_input() => {
                Box::new(NumberField::new(field_type.number_input_options(), title))
            }
            t if t == TypeId::of::<SharedString>() && field_type.is_input() => {
                Box::new(StringField::<SharedString>::new(title))
            }
            t if t == TypeId::of::<String>() && field_type.is_input() => {
                Box::new(StringField::<String>::new(title))
            }
            t if t == TypeId::of::<SharedString>() && field_type.is_dropdown() => {
                Box::new(DropdownField::<SharedString>::new(
                    field_type.dropdown_options(),
                    field_type.dropdown_scrollable(),
                    title,
                ))
            }
            t if t == TypeId::of::<String>() && field_type.is_dropdown() => {
                Box::new(DropdownField::<String>::new(
                    field_type.dropdown_options(),
                    field_type.dropdown_scrollable(),
                    title,
                ))
            }
            _ if field_type.is_element() => Box::new(ElementField::new(field_type.element())),
            _ => unimplemented!("Unsupported setting type: {}", field.deref().type_name()),
        };

        renderer.render(field, &options, &style, window, cx)
    }

    pub(super) fn render_item(
        self,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> Stateful<Div> {
        div()
            .id(SharedString::from(format!("item-{}", options.item_ix())))
            .w_full()
            .child(match self {
                SettingItem::Item {
                    title,
                    description,
                    layout,
                    disabled,
                    field,
                    ..
                } => {
                    let layout = if options.layout().is_vertical() {
                        Axis::Vertical
                    } else {
                        layout
                    };

                    div()
                        .w_full()
                        .when(disabled, |this| this.opacity(0.5))
                        .map(|this| {
                            if layout.is_horizontal() {
                                this.h_flex().justify_between().items_center()
                            } else {
                                this.v_flex()
                            }
                        })
                        .gap_3()
                        .child(
                            v_flex()
                                .map(|this| {
                                    if layout.is_horizontal() {
                                        this.flex_1().max_w_3_5()
                                    } else {
                                        this.w_full()
                                    }
                                })
                                .child(Label::new(title.clone()).text_sm())
                                .when_some(description, |this, description| {
                                    this.child(
                                        div()
                                            .size_full()
                                            .text_sm()
                                            .text_color(cx.theme().muted_foreground)
                                            .child(description),
                                    )
                                }),
                        )
                        .child(div().id("field").child(Self::render_field(
                            title,
                            field,
                            options.with_layout(layout).with_disabled(disabled),
                            window,
                            cx,
                        )))
                        .into_any_element()
                }
                SettingItem::Element {
                    disabled, render, ..
                } => div()
                    .w_full()
                    .when(disabled, |this| this.opacity(0.5))
                    .child((render)(&options.with_disabled(disabled), window, cx))
                    .into_any_element(),
            })
    }
}
