use gpui::{
    AnyElement, App, InteractiveElement as _, IntoElement, ParentElement, Pixels, RenderOnce,
    SharedString, StyleRefinement, Styled, TextAlign, Window, div, prelude::FluentBuilder as _, px,
    relative,
};
use gpui_base::{
    Table as BaseTable, TableBody as BaseTableBody, TableCaption as BaseTableCaption,
    TableCell as BaseTableCell, TableHead as BaseTableHead, TableHeader as BaseTableHeader,
    TableRow as BaseTableRow,
};

use crate::{ActiveTheme as _, AnyChildElement, ChildElement, Sizable, Size, StyledExt as _};

const MIN_CELL_WIDTH: Pixels = px(100.);

/// A basic table component for directly rendering tabular data.
///
/// Unlike [`DataTable`], this is a simple, stateless, composable table
/// without virtual scrolling or column management.
///
/// Size set via [`Sizable`] is automatically propagated to all children.
///
/// # Example
///
/// ```rust,ignore
/// Table::new()
///     .small()
///     .child(TableHeader::new().child(
///         TableRow::new()
///             .child(TableHead::new().child("Name"))
///             .child(TableHead::new().child("Email"))
///     ))
///     .child(TableBody::new()
///         .child(TableRow::new()
///             .child(TableCell::new().child("John"))
///             .child(TableCell::new().child("john@example.com")))
///     )
///     .child(TableCaption::new().child("A list of recent invoices."))
/// ```
#[derive(IntoElement)]
pub struct Table {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyChildElement>,
    size: Size,
    accessibility_label: Option<SharedString>,
}

impl Table {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            size: Size::default(),
            accessibility_label: None,
        }
    }

    /// Set the name a screen reader announces for the table.
    ///
    /// A [`TableCaption`] is visible descriptive content and is not used
    /// automatically as the table's accessible name.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    pub fn child(mut self, child: impl ChildElement + 'static) -> Self {
        self.children.push(AnyChildElement::new(child));
        self
    }

    pub fn children<E: ChildElement + 'static>(
        mut self,
        children: impl IntoIterator<Item = E>,
    ) -> Self {
        self.children
            .extend(children.into_iter().map(AnyChildElement::new));
        self
    }
}

impl Styled for Table {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for Table {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for Table {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl RenderOnce for Table {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        BaseTable::new(("table", self.ix))
            .when_some(self.accessibility_label, |this, label| {
                this.accessibility_label(label)
            })
            .w_full()
            .text_sm()
            .overflow_hidden()
            .bg(cx.theme().tokens.table)
            .refine_style(&self.style)
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, c)| c.into_any(ix, self.size)),
            )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stores_an_explicit_accessibility_label() {
        let plain = Table::new();
        assert_eq!(plain.accessibility_label, None);

        let named = Table::new().accessibility_label("Recent invoices");
        assert_eq!(
            named.accessibility_label.as_deref(),
            Some("Recent invoices")
        );
    }
}

/// The header section of a [`Table`], wrapping header rows.
#[derive(IntoElement)]
pub struct TableHeader {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyChildElement>,
    size: Size,
}

impl TableHeader {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            size: Size::default(),
        }
    }

    pub fn child(mut self, child: impl ChildElement + 'static) -> Self {
        self.children.push(AnyChildElement::new(child));
        self
    }

    pub fn children<E: ChildElement + 'static>(
        mut self,
        children: impl IntoIterator<Item = E>,
    ) -> Self {
        self.children
            .extend(children.into_iter().map(AnyChildElement::new));
        self
    }
}

impl Styled for TableHeader {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ChildElement for TableHeader {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl Sizable for TableHeader {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl RenderOnce for TableHeader {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        BaseTableHeader::new(("table-header", self.ix))
            .w_full()
            .bg(cx.theme().tokens.table_head)
            .text_color(cx.theme().table_head_foreground)
            .refine_style(&self.style)
            .border_b_1()
            .border_color(cx.theme().table_row_border)
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, c)| c.into_any(ix, self.size)),
            )
    }
}

/// The body section of a [`Table`], wrapping data rows.
#[derive(IntoElement)]
pub struct TableBody {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyChildElement>,
    size: Size,
}

impl TableBody {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            size: Size::default(),
        }
    }

    pub fn child(mut self, child: impl ChildElement + 'static) -> Self {
        self.children.push(AnyChildElement::new(child));
        self
    }

    pub fn children<E: ChildElement + 'static>(
        mut self,
        children: impl IntoIterator<Item = E>,
    ) -> Self {
        self.children
            .extend(children.into_iter().map(AnyChildElement::new));
        self
    }
}

impl Styled for TableBody {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for TableBody {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for TableBody {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl RenderOnce for TableBody {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        BaseTableBody::new(("table-body", self.ix))
            .w_full()
            .refine_style(&self.style)
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, c)| c.into_any(ix, self.size)),
            )
    }
}

/// The footer section of a [`Table`], wrapping footer rows.
#[derive(IntoElement)]
pub struct TableFooter {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyChildElement>,
    size: Size,
}

impl TableFooter {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            size: Size::default(),
        }
    }

    pub fn child(mut self, child: impl ChildElement + 'static) -> Self {
        self.children.push(AnyChildElement::new(child));
        self
    }

    pub fn children<E: ChildElement + 'static>(
        mut self,
        children: impl IntoIterator<Item = E>,
    ) -> Self {
        self.children
            .extend(children.into_iter().map(AnyChildElement::new));
        self
    }
}

impl Styled for TableFooter {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for TableFooter {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for TableFooter {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl RenderOnce for TableFooter {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        div()
            .id(("table-footer", self.ix))
            .w_full()
            .bg(cx.theme().tokens.table_foot)
            .text_color(cx.theme().table_foot_foreground)
            .border_t_1()
            .border_color(cx.theme().table_row_border)
            .refine_style(&self.style)
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, c)| c.into_any(ix, self.size)),
            )
    }
}

/// A row in a [`Table`].
#[derive(IntoElement)]
pub struct TableRow {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyChildElement>,
    size: Size,
}

impl TableRow {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            size: Size::default(),
        }
    }

    pub fn child(mut self, child: impl ChildElement + 'static) -> Self {
        self.children.push(AnyChildElement::new(child));
        self
    }

    pub fn children<E: ChildElement + 'static>(
        mut self,
        children: impl IntoIterator<Item = E>,
    ) -> Self {
        self.children
            .extend(children.into_iter().map(AnyChildElement::new));
        self
    }
}

impl Styled for TableRow {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for TableRow {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for TableRow {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl RenderOnce for TableRow {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        BaseTableRow::new(("table-row", self.ix), self.ix + 1)
            .w_full()
            .flex()
            .flex_row()
            .refine_style(&self.style)
            .border_color(cx.theme().table_row_border)
            .when(self.ix > 0, |this| this.border_t_1())
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, c)| c.into_any(ix, self.size)),
            )
    }
}

/// A header cell in a [`TableRow`].
#[derive(IntoElement)]
pub struct TableHead {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyElement>,
    col_span: usize,
    align: TextAlign,
    size: Size,
}

impl TableHead {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            col_span: 1,
            align: TextAlign::Left,
            size: Size::default(),
        }
    }

    /// Set the column span of this header cell.
    pub fn col_span(mut self, span: usize) -> Self {
        self.col_span = span.max(1);
        self
    }

    /// Set text alignment to center.
    pub fn text_center(mut self) -> Self {
        self.align = TextAlign::Center;
        self
    }

    /// Set text alignment to right.
    pub fn text_right(mut self) -> Self {
        self.align = TextAlign::Right;
        self
    }
}

impl ParentElement for TableHead {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Sizable for TableHead {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for TableHead {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl Styled for TableHead {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for TableHead {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let paddings = self.size.table_cell_padding();

        BaseTableHead::new(("table-head", self.ix), self.ix + 1)
            .flex()
            .items_center()
            .when(self.style.size.width.is_none(), |this| {
                this.flex_shrink_1()
                    .flex_basis(relative(self.col_span as f32))
            })
            .min_w(MIN_CELL_WIDTH * self.col_span)
            .px(paddings.left)
            .py(paddings.top)
            .when(self.align == TextAlign::Center, |this| {
                this.justify_center()
            })
            .when(self.align == TextAlign::Right, |this| this.justify_end())
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// A data cell in a [`TableRow`].
#[derive(IntoElement)]
pub struct TableCell {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyElement>,
    col_span: usize,
    align: TextAlign,
    size: Size,
}

impl TableCell {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            col_span: 1,
            align: TextAlign::Left,
            size: Size::default(),
        }
    }

    /// Set the column span of this cell.
    pub fn col_span(mut self, span: usize) -> Self {
        self.col_span = span.max(1);
        self
    }

    /// Set text alignment to center.
    pub fn text_center(mut self) -> Self {
        self.align = TextAlign::Center;
        self
    }

    /// Set text alignment to right.
    pub fn text_right(mut self) -> Self {
        self.align = TextAlign::Right;
        self
    }
}

impl ParentElement for TableCell {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Sizable for TableCell {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for TableCell {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl Styled for TableCell {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for TableCell {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let paddings = self.size.table_cell_padding();

        BaseTableCell::new(("table-cell", self.ix), self.ix + 1)
            .flex()
            .items_center()
            .when(self.style.size.width.is_none(), |this| {
                this.flex_shrink_1()
                    .flex_basis(relative(self.col_span as f32))
            })
            .min_w(MIN_CELL_WIDTH * self.col_span)
            .px(paddings.left)
            .py(paddings.top)
            .when(self.align == TextAlign::Center, |this| {
                this.justify_center()
            })
            .when(self.align == TextAlign::Right, |this| this.justify_end())
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// A caption displayed below the [`Table`].
#[derive(IntoElement)]
pub struct TableCaption {
    ix: usize,
    style: StyleRefinement,
    children: Vec<AnyElement>,
    size: Size,
}

impl TableCaption {
    pub fn new() -> Self {
        Self {
            ix: 0,
            style: StyleRefinement::default(),
            children: Vec::new(),
            size: Size::default(),
        }
    }
}

impl ParentElement for TableCaption {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Sizable for TableCaption {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ChildElement for TableCaption {
    fn with_ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self
    }
}

impl Styled for TableCaption {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for TableCaption {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let paddings = self.size.table_cell_padding();

        BaseTableCaption::new(("table-caption", self.ix))
            .w_full()
            .px(paddings.left)
            .py(paddings.top)
            .text_sm()
            .text_color(cx.theme().muted_foreground)
            .text_center()
            .refine_style(&self.style)
            .children(self.children)
    }
}
