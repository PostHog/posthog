use gpui::{
    AnyElement, App, Axis, DefiniteLength, IntoElement, ParentElement, RenderOnce, SharedString,
    Styled, Window, div, prelude::FluentBuilder as _, px, relative,
};

use crate::{ActiveTheme as _, AxisExt, Sizable, Size, h_flex, text::Text, v_flex};

/// A description list.
#[derive(IntoElement)]
pub struct DescriptionList {
    items: Vec<DescriptionItem>,
    size: Size,
    layout: Axis,
    label_width: DefiniteLength,
    bordered: bool,
    columns: usize,
}

/// Item for the [`DescriptionList`].
pub enum DescriptionItem {
    Item {
        label: DescriptionText,
        value: DescriptionText,
        span: usize,
    },
    Separator,
}

/// Text for the label or value in the [`DescriptionList`].
#[derive(IntoElement)]
pub enum DescriptionText {
    String(SharedString),
    Text(Text),
    AnyElement(AnyElement),
}

impl From<&str> for DescriptionText {
    fn from(text: &str) -> Self {
        DescriptionText::String(SharedString::from(text.to_string()))
    }
}

impl From<Text> for DescriptionText {
    fn from(text: Text) -> Self {
        DescriptionText::Text(text)
    }
}

impl From<AnyElement> for DescriptionText {
    fn from(element: AnyElement) -> Self {
        DescriptionText::AnyElement(element)
    }
}

impl From<SharedString> for DescriptionText {
    fn from(text: SharedString) -> Self {
        DescriptionText::String(text)
    }
}

impl From<String> for DescriptionText {
    fn from(text: String) -> Self {
        DescriptionText::String(SharedString::from(text))
    }
}

impl RenderOnce for DescriptionText {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        match self {
            DescriptionText::String(text) => div().child(text).into_any_element(),
            DescriptionText::Text(text) => text.into_any_element(),
            DescriptionText::AnyElement(element) => element,
        }
    }
}

impl DescriptionItem {
    /// Create a new description item, with a label.
    ///
    /// The value is an empty element.
    pub fn new(label: impl Into<DescriptionText>) -> Self {
        DescriptionItem::Item {
            label: label.into(),
            value: "".into(),
            span: 1,
        }
    }

    /// Set the element value of the item.
    pub fn value(mut self, value: impl Into<DescriptionText>) -> Self {
        let new_value = value.into();
        if let DescriptionItem::Item { value, .. } = &mut self {
            *value = new_value;
        }
        self
    }

    /// Set the span of the item.
    ///
    /// This method only works for [`DescriptionItem::Item`].
    pub fn span(mut self, span: usize) -> Self {
        let val = span;
        if let DescriptionItem::Item { span, .. } = &mut self {
            *span = val;
        }
        self
    }

    fn _label(&self) -> Option<&DescriptionText> {
        match self {
            DescriptionItem::Item { label, .. } => Some(label),
            _ => None,
        }
    }

    fn _span(&self) -> Option<usize> {
        match self {
            DescriptionItem::Item { span, .. } => Some(*span),
            _ => None,
        }
    }
}

impl DescriptionList {
    /// Create a new description list with the default layout (Horizontal).
    pub fn new() -> Self {
        Self {
            items: Vec::new(),
            layout: Axis::Horizontal,
            label_width: px(120.).into(),
            size: Size::default(),
            bordered: true,
            columns: 3,
        }
    }

    /// Create a vertical description list.
    pub fn vertical() -> Self {
        Self::new().layout(Axis::Vertical)
    }

    /// Create a horizontal description list, the default.
    pub fn horizontal() -> Self {
        Self::new().layout(Axis::Horizontal)
    }

    /// Set the width of the label, only works for horizontal layout.
    ///
    /// Default is `120px`.
    pub fn label_width(mut self, label_width: impl Into<DefiniteLength>) -> Self {
        self.label_width = label_width.into();
        self
    }

    /// Set the layout of the description list.
    pub fn layout(mut self, layout: Axis) -> Self {
        self.layout = layout;
        self
    }

    /// Set the border of the description list, default is `true`.
    ///
    /// `Horizontal` layout only.
    pub fn bordered(mut self, bordered: bool) -> Self {
        self.bordered = bordered;
        self
    }

    /// Set the number of columns in the description list, default is `3`.
    ///
    /// A value between `1` and `10` is allowed.
    pub fn columns(mut self, columns: usize) -> Self {
        self.columns = columns.clamp(1, 10);
        self
    }

    /// Add a [`DescriptionItem::Item`] to the list.
    pub fn item(
        mut self,
        label: impl Into<DescriptionText>,
        value: impl Into<DescriptionText>,
        span: usize,
    ) -> Self {
        self.items.push(DescriptionItem::Item {
            label: label.into(),
            value: value.into(),
            span,
        });
        self
    }

    /// Add a child to the list.
    pub fn child(mut self, child: impl Into<DescriptionItem>) -> Self {
        self.items.push(child.into());
        self
    }

    /// Add children to the list.
    pub fn children(
        mut self,
        children: impl IntoIterator<Item = impl Into<DescriptionItem>>,
    ) -> Self {
        self.items
            .extend(children.into_iter().map(Into::into).collect::<Vec<_>>());
        self
    }

    /// Add a separator to the list.
    pub fn separator(mut self) -> Self {
        self.items.push(DescriptionItem::Separator);
        self
    }

    fn group_item_rows(items: Vec<DescriptionItem>, columns: usize) -> Vec<Vec<DescriptionItem>> {
        let mut rows = vec![];
        let mut current_span = 0;
        for item in items.into_iter() {
            let span = item._span().unwrap_or(columns);
            if rows.is_empty() {
                rows.push(vec![]);
            }
            if current_span + span > columns {
                rows.push(vec![]);
                current_span = 0;
            }
            let last_group = rows.last_mut().unwrap();
            last_group.push(item);
            current_span += span;
        }
        // Remove last empty rows if it exists
        while let Some(last_group) = rows.last() {
            if !last_group.is_empty() {
                break;
            }

            rows.pop();
        }

        rows
    }
}

impl Sizable for DescriptionList {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl RenderOnce for DescriptionList {
    fn render(self, _: &mut Window, cx: &mut gpui::App) -> impl gpui::IntoElement {
        let base_gap = match self.size {
            Size::XSmall | Size::Small => px(2.),
            Size::Medium => px(4.),
            Size::Large => px(8.),
            _ => px(4.),
        };

        // Only for Horizontal layout
        let (mut padding_x, mut padding_y) = match self.size {
            Size::XSmall | Size::Small => (px(4.), px(2.)),
            Size::Medium => (px(8.), px(4.)),
            Size::Large => (px(12.), px(6.)),
            _ => (px(8.), px(4.)),
        };

        let label_width = if self.layout.is_horizontal() {
            Some(self.label_width)
        } else {
            None
        };
        if !self.bordered {
            padding_x = px(0.);
            padding_y = px(0.);
        }
        let gap = if self.bordered { px(0.) } else { base_gap };

        // Group items by columns
        let rows = Self::group_item_rows(self.items, self.columns);
        let rows_len = rows.len();

        v_flex()
            .gap(gap)
            .overflow_hidden()
            .when(self.bordered, |this| {
                this.rounded(cx.theme().radius)
                    .border_1()
                    .border_color(cx.theme().border)
            })
            .children(rows.into_iter().enumerate().map(|(ix, items)| {
                let is_last = ix == rows_len - 1;
                h_flex()
                    .when(self.bordered && !is_last, |this| {
                        this.border_b_1().border_color(cx.theme().border)
                    })
                    .children({
                        items.into_iter().enumerate().map(|(item_ix, item)| {
                            let is_first_col = item_ix == 0;

                            match item {
                                DescriptionItem::Item { label, value, span } => {
                                    let el = if self.layout.is_vertical() {
                                        v_flex()
                                    } else {
                                        div().flex().flex_row().h_full()
                                    };

                                    el.flex_1()
                                        .flex_basis(relative((span as f32) / (self.columns as f32)))
                                        .overflow_x_hidden()
                                        .child(
                                            div()
                                                .when(self.layout.is_horizontal(), |this| {
                                                    this.h_full()
                                                })
                                                .text_color(
                                                    cx.theme().description_list_label_foreground,
                                                )
                                                .text_sm()
                                                .px(padding_x)
                                                .py(padding_y)
                                                .when(self.bordered, |this| {
                                                    this.when(self.layout.is_horizontal(), |this| {
                                                        this.border_r_1()
                                                            .when(!is_first_col, |this| {
                                                                this.border_l_1()
                                                            })
                                                    })
                                                    .when(self.layout.is_vertical(), |this| {
                                                        this.border_b_1()
                                                    })
                                                    .border_color(cx.theme().border)
                                                    .bg(cx.theme().tokens.description_list_label)
                                                })
                                                .map(|this| match label_width {
                                                    Some(label_width) => {
                                                        this.w(label_width).flex_shrink_0()
                                                    }
                                                    None => this,
                                                })
                                                .child(label),
                                        )
                                        .child(
                                            div()
                                                .flex_1()
                                                .px(padding_x)
                                                .py(padding_y)
                                                .overflow_hidden()
                                                .child(value),
                                        )
                                }
                                _ => div().h_2().w_full().when(self.bordered, |this| {
                                    this.bg(cx.theme().tokens.description_list_label)
                                }),
                            }
                        })
                    })
            }))
    }
}

#[cfg(test)]
mod tests {
    use super::DescriptionItem;

    #[test]
    fn test_group_item_rows() {
        let items = vec![
            DescriptionItem::new("test1"),
            DescriptionItem::new("test2").span(2),
            DescriptionItem::new("test3"),
            DescriptionItem::new("test4"),
            DescriptionItem::new("test5"),
            DescriptionItem::new("test6").span(3),
            DescriptionItem::new("test7"),
        ];
        let rows = super::DescriptionList::group_item_rows(items, 3);
        assert_eq!(rows.len(), 4);
        assert_eq!(rows[0].len(), 2);
        assert_eq!(rows[1].len(), 3);
        assert_eq!(rows[2].len(), 1);
        assert_eq!(rows[3].len(), 1);
    }
}
