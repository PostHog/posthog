use gpui::{
    AnyElement, App, Axis, IntoElement, ParentElement, Pixels, Rems, RenderOnce, StyleRefinement,
    Styled, Window, prelude::FluentBuilder as _, px,
};

use crate::{
    Sizable, Size, StyledExt,
    form::{Field, FieldProps},
    h_flex, v_flex,
};

/// A form element that contains multiple form fields.
#[derive(IntoElement)]
pub struct Form {
    style: StyleRefinement,
    fields: Vec<Field>,
    footer: Option<AnyElement>,
    props: FieldProps,
}

impl Default for Form {
    fn default() -> Self {
        Self::new()
    }
}

impl Form {
    /// Creates a single-column form with labels above their controls.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            props: FieldProps::default(),
            fields: Vec::new(),
            footer: None,
        }
    }

    /// Creates a new form with labels beside their controls.
    pub fn horizontal() -> Self {
        Self::new().layout(Axis::Horizontal)
    }

    /// Creates a new form with labels above their controls.
    pub fn vertical() -> Self {
        Self::new().layout(Axis::Vertical)
    }

    /// Sets label/control orientation within each field, default is `Axis::Vertical`.
    ///
    /// This is an alias for [`Self::label_layout`]. Use [`Self::columns`] to arrange fields.
    pub fn layout(self, layout: Axis) -> Self {
        self.label_layout(layout)
    }

    /// Sets label/control orientation within each field.
    ///
    /// `Axis::Vertical` (default) places labels above controls; `Axis::Horizontal`
    /// places labels beside controls. This does not change the field grid columns.
    pub fn label_layout(mut self, layout: Axis) -> Self {
        self.props.layout = layout;
        self
    }

    /// Set the width of the labels in the form. Default is `px(140.)`.
    pub fn label_width(mut self, width: Pixels) -> Self {
        self.props.label_width = Some(width);
        self
    }

    /// Set the text size of the labels in the form. Default is `None`.
    pub fn label_text_size(mut self, size: Rems) -> Self {
        self.props.label_text_size = Some(size);
        self
    }

    /// Add a child to the form.
    pub fn child(mut self, field: impl Into<Field>) -> Self {
        self.fields.push(field.into());
        self
    }

    /// Add multiple children to the form.
    pub fn children(mut self, fields: impl IntoIterator<Item = Field>) -> Self {
        self.fields.extend(fields);
        self
    }

    /// Sets content in a full-width footer after all fields, aligned to the trailing edge.
    ///
    /// The caller owns action composition, state, and callbacks. Calling this again
    /// replaces the footer. No footer row is rendered unless content is supplied.
    pub fn footer(mut self, footer: impl IntoElement) -> Self {
        self.footer = Some(footer.into_any_element());
        self
    }

    /// Set the column count for the field grid, independently of label orientation.
    ///
    /// Default is 1.
    pub fn columns(mut self, columns: usize) -> Self {
        self.props.columns = columns;
        self
    }
}

impl Styled for Form {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for Form {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.props.size = size.into();
        self
    }
}

impl RenderOnce for Form {
    fn render(self, _window: &mut Window, _cx: &mut App) -> impl IntoElement {
        let props = self.props;

        let gap = match props.size {
            Size::XSmall | Size::Small => px(6.),
            Size::Large => px(12.),
            _ => px(8.),
        };

        v_flex()
            .w_full()
            .gap_x(gap * 3.)
            .gap_y(gap)
            .grid()
            .grid_cols(props.columns as u16)
            .children(
                self.fields
                    .into_iter()
                    .enumerate()
                    .filter(|(_, field)| field.is_visible())
                    .map(|(ix, field)| field.props(ix, props)),
            )
            .when_some(self.footer, |this, footer| {
                this.child(
                    h_flex()
                        .col_span_full()
                        .min_w_0()
                        .justify_end()
                        .child(footer),
                )
            })
            .refine_style(&self.style)
    }
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
