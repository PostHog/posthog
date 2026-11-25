use crate::TestSupportExt as _;
use gpui::{
    AnyElement, App, Div, ElementId, InteractiveElement, Interactivity, IntoElement, ParentElement,
    RenderOnce, Role, SharedString, Stateful, StatefulInteractiveElement, StyleRefinement, Styled,
    Window, div, prelude::FluentBuilder as _,
};

use crate::StyledExt as _;

macro_rules! table_part {
    ($name:ident, $role:expr, $docs:literal) => {
        #[doc = $docs]
        #[derive(IntoElement)]
        pub struct $name {
            base: crate::ObservedElement<Stateful<Div>>,
            style: StyleRefinement,
            children: Vec<AnyElement>,
        }

        impl $name {
            #[doc = concat!("Create ", $docs)]
            pub fn new(id: impl Into<ElementId>) -> Self {
                Self {
                    base: div().id(id).test_support(),
                    style: StyleRefinement::default(),
                    children: Vec::new(),
                }
            }
        }

        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }

        impl ParentElement for $name {
            fn extend(&mut self, children: impl IntoIterator<Item = AnyElement>) {
                self.children.extend(children);
            }
        }

        impl InteractiveElement for $name {
            fn interactivity(&mut self) -> &mut Interactivity {
                self.base.interactivity()
            }

            fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
                self.base = self.base.track_focus(handle);
                self
            }
        }

        impl StatefulInteractiveElement for $name {}

        impl RenderOnce for $name {
            fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
                self.base
                    .role($role)
                    .children(self.children)
                    .refine_style(&self.style)
            }
        }
    };
}

/// An unstyled semantic table root.
#[derive(IntoElement)]
pub struct Table {
    base: crate::ObservedElement<Stateful<Div>>,
    style: StyleRefinement,
    children: Vec<AnyElement>,
    row_count: Option<usize>,
    column_count: Option<usize>,
    accessibility_label: Option<SharedString>,
}

impl Table {
    /// Create an unstyled semantic table root.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            children: Vec::new(),
            row_count: None,
            column_count: None,
            accessibility_label: None,
        }
    }

    /// Sets the total number of rows, including rows outside the rendered
    /// range. Assistive technology needs this to announce "row 5 of 200" for a
    /// virtualized table whose rendered rows are only a window onto the data.
    pub fn row_count(mut self, count: usize) -> Self {
        self.row_count = Some(count);
        self
    }

    /// Sets the total number of columns, including columns outside the
    /// rendered range.
    pub fn column_count(mut self, count: usize) -> Self {
        self.column_count = Some(count);
        self
    }

    /// Sets the table's accessible name.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl Styled for Table {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Table {
    fn extend(&mut self, children: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(children);
    }
}

impl InteractiveElement for Table {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }

    fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(handle);
        self
    }
}

impl StatefulInteractiveElement for Table {}

impl RenderOnce for Table {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::Table)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .when_some(self.row_count, |this, count| this.aria_row_count(count))
            .when_some(self.column_count, |this, count| {
                this.aria_column_count(count)
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}
table_part!(
    TableHeader,
    Role::RowGroup,
    "An unstyled table header group."
);
table_part!(TableBody, Role::RowGroup, "An unstyled table body group.");

/// An unstyled semantic table row.
#[derive(IntoElement)]
pub struct TableRow {
    base: crate::ObservedElement<Stateful<Div>>,
    style: StyleRefinement,
    row_index: usize,
    children: Vec<AnyElement>,
}

impl TableRow {
    /// Create an unstyled semantic table row with a one-based accessibility index.
    pub fn new(id: impl Into<ElementId>, row_index: usize) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            row_index,
            children: Vec::new(),
        }
    }
}

impl Styled for TableRow {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for TableRow {
    fn extend(&mut self, children: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(children);
    }
}

impl InteractiveElement for TableRow {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }

    fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(handle);
        self
    }
}

impl StatefulInteractiveElement for TableRow {}

impl RenderOnce for TableRow {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::Row)
            .aria_row_index(self.row_index)
            .children(self.children)
            .refine_style(&self.style)
    }
}

macro_rules! table_cell {
    ($name:ident, $role:expr, $docs:literal) => {
        #[doc = $docs]
        #[derive(IntoElement)]
        pub struct $name {
            base: crate::ObservedElement<Stateful<Div>>,
            style: StyleRefinement,
            column_index: usize,
            children: Vec<AnyElement>,
        }

        impl $name {
            #[doc = concat!("Create ", $docs, " with a one-based accessibility index.")]
            pub fn new(id: impl Into<ElementId>, column_index: usize) -> Self {
                Self {
                    base: div().id(id).test_support(),
                    style: StyleRefinement::default(),
                    column_index,
                    children: Vec::new(),
                }
            }
        }

        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }

        impl ParentElement for $name {
            fn extend(&mut self, children: impl IntoIterator<Item = AnyElement>) {
                self.children.extend(children);
            }
        }

        impl InteractiveElement for $name {
            fn interactivity(&mut self) -> &mut Interactivity {
                self.base.interactivity()
            }

            fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
                self.base = self.base.track_focus(handle);
                self
            }
        }

        impl StatefulInteractiveElement for $name {}

        impl RenderOnce for $name {
            fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
                self.base
                    .role($role)
                    .aria_column_index(self.column_index)
                    .children(self.children)
                    .refine_style(&self.style)
            }
        }
    };
}

table_cell!(
    TableHead,
    Role::ColumnHeader,
    "An unstyled table column header."
);
table_cell!(TableCell, Role::Cell, "An unstyled table data cell.");

/// An unstyled table caption slot.
#[derive(IntoElement)]
pub struct TableCaption {
    base: crate::ObservedElement<Stateful<Div>>,
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl TableCaption {
    /// Create an unstyled table caption slot.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl Styled for TableCaption {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for TableCaption {
    fn extend(&mut self, children: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(children);
    }
}

impl InteractiveElement for TableCaption {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }

    fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(handle);
        self
    }
}

impl StatefulInteractiveElement for TableCaption {}

impl RenderOnce for TableCaption {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base.children(self.children).refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{Context, Element as _, Modifiers, Render, TestAppContext, accesskit, point, px};
    use std::{cell::Cell, rc::Rc};

    #[gpui::test]
    fn table_projects_its_accessible_name(cx: &mut TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let mut node = accesskit::Node::new(Role::Table);
            Table::new("positions")
                .accessibility_label("Open positions")
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut node);

            assert_eq!(node.label(), Some("Open positions"));
        });
    }

    #[gpui::test]
    fn row_and_cells_project_accessibility_indices(cx: &mut TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let mut row = accesskit::Node::new(Role::Row);
            TableRow::new("row", 3)
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut row);
            assert_eq!(row.row_index(), Some(3));

            let mut head = accesskit::Node::new(Role::GenericContainer);
            TableHead::new("head", 2)
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut head);
            assert_eq!(head.column_index(), Some(2));

            let mut cell = accesskit::Node::new(Role::Cell);
            TableCell::new("cell", 4)
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut cell);
            assert_eq!(cell.column_index(), Some(4));
        });
    }

    struct TableHarness {
        clicks: Rc<Cell<usize>>,
    }

    impl Render for TableHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let clicks = self.clicks.clone();
            Table::new("table")
                .debug_selector(|| "base-table".into())
                .w(px(120.))
                .h(px(60.))
                .on_click(move |_, _, _| clicks.set(clicks.get() + 1))
                .child(
                    TableBody::new("body").child(
                        TableRow::new("row", 1)
                            .child(TableCell::new("cell", 1).child(
                                div().debug_selector(|| "table-child".into()).size(px(20.)),
                            )),
                    ),
                )
        }
    }

    #[gpui::test]
    fn table_forwards_children_instance_style_and_pointer_interaction(cx: &mut TestAppContext) {
        let clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let clicks = clicks.clone();
            move |_, _| TableHarness { clicks }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let table = cx.debug_bounds("base-table").expect("table is rendered");
        assert_eq!(table.size.width, px(120.));
        assert_eq!(table.size.height, px(60.));
        let child = cx.debug_bounds("table-child").expect("child is rendered");
        assert_eq!(child.size.width, px(20.));
        assert_eq!(child.size.height, px(20.));

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        cx.simulate_click(point(px(100.), px(50.)), Modifiers::default());
        assert_eq!(clicks.get(), 2);
    }
}
