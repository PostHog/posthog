use std::{ops::Range, rc::Rc};

use gpui::{
    AnyElement, App, ElementId, InteractiveElement, IntoElement, ParentElement, RenderOnce, Role,
    SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
};

use crate::StyledExt as _;

type PageChangeHandler = Rc<dyn Fn(usize, &mut Window, &mut App)>;

/// A visible destination in a pagination control.
#[derive(Debug, Clone, Eq, PartialEq)]
pub enum PaginationItem {
    Page(usize),
    Ellipsis(Range<usize>),
}

/// The controlled behavior shared by every part of a pagination control.
#[derive(Clone)]
pub struct PaginationState {
    current_page: usize,
    total_pages: usize,
    visible_pages: usize,
    disabled: bool,
    on_change: Option<PageChangeHandler>,
}

impl PaginationState {
    pub fn new(current_page: usize, total_pages: usize) -> Self {
        let total_pages = total_pages.max(1);
        Self {
            current_page: current_page.clamp(1, total_pages),
            total_pages,
            visible_pages: 5,
            disabled: false,
            on_change: None,
        }
    }

    pub fn visible_pages(mut self, visible_pages: usize) -> Self {
        self.visible_pages = visible_pages.max(5);
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Handles a requested page change.
    ///
    /// Unlike the element-level controls, this is a model-level request that
    /// may also come from the keyboard or from application code, so it does not
    /// carry a pointer event.
    pub fn on_change(mut self, handler: impl Fn(usize, &mut Window, &mut App) + 'static) -> Self {
        self.on_change = Some(Rc::new(handler));
        self
    }

    pub fn current_page(&self) -> usize {
        self.current_page
    }

    pub fn total_pages(&self) -> usize {
        self.total_pages
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn has_on_change(&self) -> bool {
        self.on_change.is_some()
    }

    pub fn previous_page(&self) -> Option<usize> {
        (!self.disabled && self.current_page > 1).then(|| self.current_page - 1)
    }

    pub fn next_page(&self) -> Option<usize> {
        (!self.disabled && self.current_page < self.total_pages).then(|| self.current_page + 1)
    }

    /// Requests a controlled page change after applying the shared disabled,
    /// bounds, and current-page guards.
    pub fn request_page(&self, page: usize, window: &mut Window, cx: &mut App) {
        if self.disabled || page == self.current_page || !(1..=self.total_pages).contains(&page) {
            return;
        }

        if let Some(on_change) = &self.on_change {
            on_change(page, window, cx);
        }
    }

    pub fn items(&self) -> Vec<PaginationItem> {
        calculate_items(self.current_page, self.total_pages, self.visible_pages)
    }
}

/// An unstyled pagination navigation landmark.
#[derive(IntoElement)]
pub struct Pagination {
    base: gpui::Stateful<gpui::Div>,
    state: PaginationState,
    style: StyleRefinement,
    accessibility_label: SharedString,
    children: Vec<AnyElement>,
}

impl Pagination {
    pub fn new(id: impl Into<ElementId>, state: PaginationState) -> Self {
        Self {
            base: div().id(id.into()),
            state,
            style: StyleRefinement::default(),
            accessibility_label: "Pagination".into(),
            children: Vec::new(),
        }
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = label.into();
        self
    }

    pub fn state(&self) -> &PaginationState {
        &self.state
    }
}

impl ParentElement for Pagination {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for Pagination {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl InteractiveElement for Pagination {
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Pagination {}

impl RenderOnce for Pagination {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::Navigation)
            .aria_label(self.accessibility_label)
            .children(self.children)
            .refine_style(&self.style)
    }
}

fn calculate_items(current: usize, total: usize, max_visible: usize) -> Vec<PaginationItem> {
    if total <= 1 {
        return vec![];
    }

    let max_visible = max_visible.max(5);
    if total <= max_visible {
        return (1..=total).map(PaginationItem::Page).collect();
    }

    let mut pages = vec![PaginationItem::Page(1)];
    let side_pages = (max_visible - 3) / 2;
    let start = if current <= side_pages + 1 {
        2
    } else if current > total - side_pages - 1 {
        total - side_pages - 1
    } else {
        current - side_pages
    };

    if start > 2 {
        pages.push(PaginationItem::Ellipsis(2..start));
    }

    let end = if current >= total - side_pages {
        total - 1
    } else if current <= side_pages + 1 {
        side_pages + 2
    } else {
        current + side_pages
    };

    pages.extend((start..=end).map(PaginationItem::Page));
    if end < total - 1 {
        pages.push(PaginationItem::Ellipsis(end + 1..total));
    }
    pages.push(PaginationItem::Page(total));
    pages
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    use gpui::{Element as _, accesskit};

    #[test]
    fn clamps_controlled_values_and_navigation_boundaries() {
        let first = PaginationState::new(0, 0);
        assert_eq!(first.current_page(), 1);
        assert_eq!(first.total_pages(), 1);
        assert_eq!(first.previous_page(), None);
        assert_eq!(first.next_page(), None);

        let last = PaginationState::new(20, 10);
        assert_eq!(last.current_page(), 10);
        assert_eq!(last.previous_page(), Some(9));
        assert_eq!(last.next_page(), None);
        assert_eq!(last.clone().disabled(true).previous_page(), None);
    }

    #[test]
    fn creates_pages_and_navigable_ellipsis_ranges() {
        assert_eq!(
            PaginationState::new(5, 10).visible_pages(7).items(),
            vec![
                PaginationItem::Page(1),
                PaginationItem::Ellipsis(2..3),
                PaginationItem::Page(3),
                PaginationItem::Page(4),
                PaginationItem::Page(5),
                PaginationItem::Page(6),
                PaginationItem::Page(7),
                PaginationItem::Ellipsis(8..10),
                PaginationItem::Page(10),
            ]
        );
    }

    #[gpui::test]
    fn validates_every_page_change_request(cx: &mut gpui::TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let requested = Rc::new(Cell::new(None));
            let state = PaginationState::new(3, 5).on_change({
                let requested = requested.clone();
                move |page, _, _| requested.set(Some(page))
            });

            state.request_page(3, window, cx);
            state.request_page(0, window, cx);
            state.request_page(6, window, cx);
            assert_eq!(requested.get(), None);

            state.request_page(4, window, cx);
            assert_eq!(requested.get(), Some(4));
            requested.set(None);
            state.clone().disabled(true).request_page(2, window, cx);
            assert_eq!(requested.get(), None);
        });
    }

    #[gpui::test]
    fn exposes_a_named_navigation_landmark(cx: &mut gpui::TestAppContext) {
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let mut node = accesskit::Node::new(Role::Navigation);
            Pagination::new("pagination", PaginationState::new(1, 5))
                .accessibility_label("Search results pages")
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut node);

            assert_eq!(node.role(), Role::Navigation);
            assert_eq!(node.label(), Some("Search results pages"));
        });
    }
}
