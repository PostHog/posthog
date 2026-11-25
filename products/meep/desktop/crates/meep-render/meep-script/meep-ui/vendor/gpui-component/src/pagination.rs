use std::{ops::Range, rc::Rc};

use gpui::{
    App, ElementId, IntoElement, ParentElement, RenderOnce, SharedString, StyleRefinement, Styled,
    Window, prelude::FluentBuilder, px,
};
use rust_i18n::t;

use gpui_base::{Pagination as BasePagination, PaginationItem as PageItem, PaginationState};

use crate::{
    Disableable, Icon, Sizable, Size, StyledExt,
    button::{Button, ButtonVariants},
    h_flex,
    icon::IconName,
    menu::{DropdownMenu as _, PopupMenuItem},
};

/// The most pages an ellipsis menu lists.
///
/// The menu renders every item on each frame it is open, so listing every
/// hidden page of a large set makes each hover repaint thousands of rows.
const MAX_ELLIPSIS_MENU_PAGES: usize = 100;

/// The pages an ellipsis menu lists: the hidden pages closest to the current
/// page, at most [`MAX_ELLIPSIS_MENU_PAGES`] of them.
fn ellipsis_menu_pages(hidden: Range<usize>, current_page: usize) -> Range<usize> {
    if hidden.len() <= MAX_ELLIPSIS_MENU_PAGES {
        hidden
    } else if hidden.start > current_page {
        hidden.start..hidden.start + MAX_ELLIPSIS_MENU_PAGES
    } else {
        hidden.end - MAX_ELLIPSIS_MENU_PAGES..hidden.end
    }
}

/// Pagination with page navigation, next and previous links.
#[derive(IntoElement)]
pub struct Pagination {
    id: ElementId,
    style: StyleRefinement,
    size: Size,
    current_page: usize,
    total_pages: usize,
    disabled: bool,
    compact: bool,
    visible_pages: usize,
    on_click: Option<Rc<dyn Fn(&usize, &mut Window, &mut App)>>,
}

impl Pagination {
    /// Create a new Pagination component with the given ID.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            size: Size::default(),
            current_page: 1,
            total_pages: 1,
            visible_pages: 5,
            disabled: false,
            compact: false,
            on_click: None,
        }
    }

    /// Set the current page number (1-based).
    ///
    /// The value will be clamped between 1 and total_pages when total_pages is set.
    pub fn current_page(mut self, page: usize) -> Self {
        self.current_page = page.max(1);
        self
    }

    /// Set the total number of pages.
    pub fn total_pages(mut self, pages: usize) -> Self {
        self.total_pages = pages.max(1);
        if self.current_page > self.total_pages {
            self.current_page = self.total_pages;
        }
        self
    }

    /// Set the handler for page change (when clicking on page numbers, prev, or next).
    ///
    /// This handler receives the new page number to navigate to.
    ///
    /// # Examples
    ///
    /// ```ignore
    /// Pagination::new("my-pagination")
    ///     .current_page(current_page)
    ///     .total_pages(total_pages)
    ///     .on_click(|page, _, cx| {
    ///         // Handle page change
    ///     })
    /// ```
    pub fn on_click(mut self, handler: impl Fn(&usize, &mut Window, &mut App) + 'static) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Set to display as compact style.
    ///
    /// If true, only the prev, next buttons with only icon.
    pub fn compact(mut self) -> Self {
        self.compact = true;
        self
    }

    /// Set viewable maximum number of page buttons, default
    pub fn visible_pages(mut self, max: usize) -> Self {
        self.visible_pages = max;
        self
    }

    fn render_nav_button(&self, state: &PaginationState, is_prev: bool) -> Button {
        let (id, label, icon) = if is_prev {
            ("prev", t!("Pagination.previous"), IconName::ChevronLeft)
        } else {
            ("next", t!("Pagination.next"), IconName::ChevronRight)
        };

        let target_page = if is_prev {
            state.previous_page()
        } else {
            state.next_page()
        };

        Button::new(id)
            .ghost()
            .compact()
            .with_size(self.size)
            .disabled(target_page.is_none())
            .tooltip(label.clone())
            .when(self.compact, |this| this.icon(icon.clone()))
            .when(!self.compact, |this| {
                this.child(
                    h_flex()
                        .w_full()
                        .gap_2()
                        .flex_nowrap()
                        .when(is_prev, |this| this.flex_row_reverse())
                        .child(SharedString::from(label))
                        .child(Icon::new(icon)),
                )
            })
            .when_some(
                target_page.filter(|_| state.has_on_change()),
                |this, target_page| {
                    let state = state.clone();
                    this.on_click(move |_, window, cx| {
                        state.request_page(target_page, window, cx);
                    })
                },
            )
    }
}

impl Disableable for Pagination {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Sizable for Pagination {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Pagination {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Pagination {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let mut state = PaginationState::new(self.current_page, self.total_pages)
            .visible_pages(self.visible_pages)
            .disabled(self.disabled);
        if let Some(on_click) = self.on_click.clone() {
            state = state.on_change(move |page, window, cx| on_click(&page, window, cx));
        }
        let page_numbers = (!self.compact).then(|| state.items()).unwrap_or_default();

        let current_page = state.current_page();
        let is_disabled = self.disabled;
        let item_state = state.clone();

        BasePagination::new(self.id.clone(), state.clone())
            .h_flex()
            .px_2()
            .py_2()
            .gap_1()
            .items_center()
            .refine_style(&self.style)
            .child(self.render_nav_button(&state, true))
            .children({
                page_numbers.into_iter().map(|item| match item {
                    PageItem::Page(page) => {
                        let is_selected = page == current_page;

                        Button::new(page)
                            .with_size(self.size)
                            .map(|this| {
                                if is_selected {
                                    this.outline()
                                } else {
                                    this.ghost()
                                }
                            })
                            .label(page.to_string())
                            .compact()
                            .disabled(is_disabled)
                            .when(!is_selected && item_state.has_on_change(), |this| {
                                let state = item_state.clone();
                                this.on_click(move |_, window, cx| {
                                    state.request_page(page, window, cx);
                                })
                            })
                            .into_any_element()
                    }
                    PageItem::Ellipsis(range) => Button::new(SharedString::from(format!(
                        "ellipsis-{}-{}",
                        range.start, range.end
                    )))
                    .ghost()
                    .with_size(self.size)
                    .compact()
                    .disabled(self.disabled)
                    .icon(IconName::Ellipsis)
                    .dropdown_menu({
                        let state = item_state.clone();
                        move |mut menu, _, _| {
                            for page in ellipsis_menu_pages(range.clone(), current_page) {
                                menu = menu.item(
                                    PopupMenuItem::new(format!("{}", page))
                                        .checked(page == current_page)
                                        .on_click({
                                            let state = state.clone();
                                            move |_, window, cx| {
                                                state.request_page(page, window, cx);
                                            }
                                        }),
                                )
                            }

                            menu.min_w(px(55.)).max_h(px(240.)).scrollable(true)
                        }
                    })
                    .into_any_element(),
                })
            })
            .child(self.render_nav_button(&state, false))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ellipsis_menu_pages() {
        // Short gaps list every hidden page.
        assert_eq!(ellipsis_menu_pages(2..8, 1), 2..8);
        assert_eq!(ellipsis_menu_pages(2..8, 9), 2..8);

        // Long gaps keep the pages next to the current page.
        assert_eq!(ellipsis_menu_pages(4..10_000, 1), 4..104);
        assert_eq!(ellipsis_menu_pages(2..9_997, 10_000), 9_897..9_997);
        assert_eq!(ellipsis_menu_pages(5_003..10_000, 5_000), 5_003..5_103);
        assert_eq!(ellipsis_menu_pages(2..4_998, 5_000), 4_898..4_998);
    }
}
