use std::rc::Rc;

use gpui::{
    AlignItems, AnyElement, AnyView, App, Axis, Div, ElementId, InteractiveElement as _,
    IntoElement, ParentElement, Pixels, Rems, RenderOnce, SharedString, StyleRefinement, Styled,
    Window, div, prelude::FluentBuilder as _, px,
};

use crate::{ActiveTheme as _, AxisExt, Size, StyledExt, h_flex, v_flex};

#[derive(Clone, Copy)]
pub(super) struct FieldProps {
    pub(super) size: Size,
    pub(super) layout: Axis,
    pub(super) columns: usize,

    pub(super) label_width: Option<Pixels>,
    pub(super) label_text_size: Option<Rems>,
}

impl Default for FieldProps {
    fn default() -> Self {
        Self {
            layout: Axis::Vertical,
            size: Size::default(),
            columns: 1,
            label_width: Some(px(140.)),
            label_text_size: None,
        }
    }
}

pub enum FieldBuilder {
    String(SharedString),
    Element(Rc<dyn Fn(&mut Window, &mut App) -> AnyElement>),
    View(AnyView),
}

impl Default for FieldBuilder {
    fn default() -> Self {
        Self::String(SharedString::default())
    }
}

impl From<AnyView> for FieldBuilder {
    fn from(view: AnyView) -> Self {
        Self::View(view)
    }
}

impl RenderOnce for FieldBuilder {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        match self {
            FieldBuilder::String(value) => value.into_any_element(),
            FieldBuilder::Element(builder) => builder(window, cx),
            FieldBuilder::View(view) => view.into_any_element(),
        }
    }
}

impl From<&'static str> for FieldBuilder {
    fn from(value: &'static str) -> Self {
        Self::String(value.into())
    }
}

impl From<String> for FieldBuilder {
    fn from(value: String) -> Self {
        Self::String(value.into())
    }
}

impl From<SharedString> for FieldBuilder {
    fn from(value: SharedString) -> Self {
        Self::String(value)
    }
}

/// Form field element.
#[derive(IntoElement)]
pub struct Field {
    id: ElementId,
    props: FieldProps,
    style: StyleRefinement,
    label: Option<FieldBuilder>,
    label_indent: bool,
    description: Option<FieldBuilder>,
    /// Used to render the actual form field, e.g.: Input, Switch...
    children: Vec<AnyElement>,
    visible: bool,
    required: bool,
    /// Alignment of the form field.
    align_items: Option<AlignItems>,
    col_span: u16,
    col_start: Option<i16>,
    col_end: Option<i16>,
}

impl Field {
    pub fn new() -> Self {
        Self {
            id: 0.into(),
            props: FieldProps::default(),
            style: StyleRefinement::default(),
            label: None,
            description: None,
            children: Vec::new(),
            visible: true,
            required: false,
            label_indent: true,
            align_items: None,
            col_span: 1,
            col_start: None,
            col_end: None,
        }
    }

    /// Sets the label for the form field.
    pub fn label(mut self, label: impl Into<FieldBuilder>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Sets indent with the label width (in Horizontal layout), default is `true`.
    ///
    /// Sometimes you want to align the input form left (Default is align after the label width in Horizontal layout).
    ///
    /// This is only work when the `label` is not set.
    pub fn label_indent(mut self, indent: bool) -> Self {
        self.label_indent = indent;
        self
    }

    /// Sets the label for the form field using a function.
    pub fn label_fn<F, E>(mut self, label: F) -> Self
    where
        E: IntoElement,
        F: Fn(&mut Window, &mut App) -> E + 'static,
    {
        self.label = Some(FieldBuilder::Element(Rc::new(move |window, cx| {
            label(window, cx).into_any_element()
        })));
        self
    }

    /// Sets the description for the form field.
    pub fn description(mut self, description: impl Into<FieldBuilder>) -> Self {
        self.description = Some(description.into());
        self
    }

    /// Sets the description for the form field using a function.
    pub fn description_fn<F, E>(mut self, description: F) -> Self
    where
        E: IntoElement,
        F: Fn(&mut Window, &mut App) -> E + 'static,
    {
        self.description = Some(FieldBuilder::Element(Rc::new(move |window, cx| {
            description(window, cx).into_any_element()
        })));
        self
    }

    /// Set the visibility of the form field, default is `true`.
    pub fn visible(mut self, visible: bool) -> Self {
        self.visible = visible;
        self
    }

    /// Returns whether the form field is visible.
    pub(super) fn is_visible(&self) -> bool {
        self.visible
    }

    /// Set the required status of the form field, default is `false`.
    pub fn required(mut self, required: bool) -> Self {
        self.required = required;
        self
    }

    /// Set the properties for the form field.
    ///
    /// This is internal API for sync props from From.
    pub(super) fn props(mut self, ix: usize, props: FieldProps) -> Self {
        self.id = ix.into();
        self.props = props;
        self
    }

    /// Align the form field items to the start, this is the default.
    pub fn items_start(mut self) -> Self {
        self.align_items = Some(AlignItems::Start);
        self
    }

    /// Align the form field items to the end.
    pub fn items_end(mut self) -> Self {
        self.align_items = Some(AlignItems::End);
        self
    }

    /// Align the form field items to the center.
    pub fn items_center(mut self) -> Self {
        self.align_items = Some(AlignItems::Center);
        self
    }

    /// Sets the column span for the form field.
    ///
    /// Default is 1.
    pub fn col_span(mut self, col_span: u16) -> Self {
        self.col_span = col_span;
        self
    }

    /// Sets the column start of this form field.
    pub fn col_start(mut self, col_start: i16) -> Self {
        self.col_start = Some(col_start);
        self
    }

    /// Sets the column end of this form field.
    pub fn col_end(mut self, col_end: i16) -> Self {
        self.col_end = Some(col_end);
        self
    }
}

impl ParentElement for Field {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for Field {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Field {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let layout = self.props.layout;

        let label_width = if layout.is_vertical() {
            None
        } else {
            self.props.label_width
        };
        let has_label = self.label_indent;

        #[inline]
        fn wrap_div(layout: Axis) -> Div {
            if layout.is_vertical() {
                v_flex()
            } else {
                h_flex()
            }
        }

        #[inline]
        fn wrap_label(label_width: Option<Pixels>) -> Div {
            div().when_some(label_width, |this, width| this.w(width).flex_shrink_0())
        }

        let gap = match self.props.size {
            Size::Large => px(8.),
            Size::XSmall | Size::Small => px(4.),
            _ => px(4.),
        };
        let inner_gap = if layout.is_horizontal() {
            gap
        } else {
            gap / 2.
        };

        v_flex()
            .flex_1()
            .gap(gap / 2.)
            .col_span(self.col_span)
            .when_some(self.col_start, |this, start| this.col_start(start))
            .when_some(self.col_end, |this, end| this.col_end(end))
            .refine_style(&self.style)
            .when(!self.visible, |this| this.hidden())
            .child(
                // This warp for aligning the Label + Input
                wrap_div(layout)
                    .id(self.id)
                    .gap(inner_gap)
                    .when_some(self.align_items, |this, align| {
                        this.map(|this| match align {
                            AlignItems::Start => this.items_start(),
                            AlignItems::End => this.items_end(),
                            AlignItems::Center => this.items_center(),
                            AlignItems::Baseline => this.items_baseline(),
                            _ => this,
                        })
                    })
                    .when(has_label, |this| {
                        // Label
                        this.child(
                            wrap_label(label_width)
                                .text_sm()
                                .when_some(self.props.label_text_size, |this, size| {
                                    this.text_size(size)
                                })
                                .font_medium()
                                .gap_1()
                                .items_center()
                                .when_some(self.label, |this, builder| {
                                    this.child(
                                        h_flex()
                                            .gap_1()
                                            .child(
                                                div()
                                                    .overflow_x_hidden()
                                                    .child(builder.render(window, cx)),
                                            )
                                            .when(self.required, |this| {
                                                this.child(
                                                    div().text_color(cx.theme().danger).child("*"),
                                                )
                                            }),
                                    )
                                }),
                        )
                    })
                    .child(div().w_full().flex_1().children(self.children)),
            )
            .child(
                // Other
                wrap_div(layout)
                    .gap(inner_gap)
                    .when(has_label && layout.is_horizontal(), |this| {
                        this.child(
                            // Empty for spacing to align with the input
                            wrap_label(label_width),
                        )
                    })
                    .when_some(self.description, |this, builder| {
                        this.child(
                            div()
                                .text_xs()
                                .text_color(cx.theme().muted_foreground)
                                .child(builder.render(window, cx)),
                        )
                    }),
            )
    }
}
