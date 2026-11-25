use std::ops::Range;

use crate::{
    Icon, IconName, Sizable, Size, StyledExt,
    empty::{Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyMediaVariant, EmptyTitle},
    group_box::GroupBoxVariant,
    h_resizable,
    input::{Input, InputState},
    resizable_panel,
    setting::SettingPage,
    sidebar::{Sidebar, SidebarMenu, SidebarMenuItem},
};
use gpui::{
    App, AppContext as _, Axis, ElementId, Entity, InteractiveElement as _, IntoElement,
    ParentElement as _, Pixels, RenderOnce, StyleRefinement, Styled, Window, container_query, div,
    prelude::FluentBuilder as _, px, relative,
};
use rust_i18n::t;

const STACKED_LAYOUT_MAX_WIDTH: Pixels = px(480.);

/// The settings structure containing multiple pages for app settings.
///
/// The hierarchy of settings is as follows:
///
/// ```ignore
/// Settings
///   SettingPage     <- The single active page displayed
///     SettingGroup
///       SettingItem
///         Label
///         SettingField (e.g., Switch, Dropdown, Input)
/// ```
#[derive(IntoElement)]
pub struct Settings {
    id: ElementId,
    pages: Vec<SettingPage>,
    group_variant: GroupBoxVariant,
    size: Size,
    sidebar_width: Pixels,
    sidebar_size_range: Range<Pixels>,
    sidebar_style: StyleRefinement,
    default_selected_index: SelectIndex,
    header_style: StyleRefinement,
}

impl Settings {
    /// Create a new settings with the given ID.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            pages: vec![],
            group_variant: GroupBoxVariant::default(),
            size: Size::default(),
            sidebar_width: px(250.0),
            sidebar_size_range: px(160.0)..px(360.0),
            sidebar_style: StyleRefinement::default(),
            default_selected_index: SelectIndex::default(),
            header_style: StyleRefinement::default(),
        }
    }

    /// Set the width of the sidebar, default is `250px`.
    pub fn sidebar_width(mut self, width: impl Into<Pixels>) -> Self {
        self.sidebar_width = width.into();
        self
    }

    /// Set the resize range of the sidebar, default is `160px..360px`.
    pub fn sidebar_size_range(mut self, range: impl Into<Range<Pixels>>) -> Self {
        self.sidebar_size_range = range.into();
        self
    }

    /// Add a page to the settings.
    pub fn page(mut self, page: SettingPage) -> Self {
        self.pages.push(page);
        self
    }

    /// Add pages to the settings.
    pub fn pages(mut self, pages: impl IntoIterator<Item = SettingPage>) -> Self {
        self.pages.extend(pages);
        self
    }

    /// Set the default variant for all setting groups.
    ///
    /// All setting groups will use this variant unless overridden individually.
    pub fn with_group_variant(mut self, variant: GroupBoxVariant) -> Self {
        self.group_variant = variant;
        self
    }

    /// Set the style refinement for the sidebar.
    pub fn sidebar_style(mut self, style: &StyleRefinement) -> Self {
        self.sidebar_style = style.clone();
        self
    }

    /// Set the default index of the page to be selected.
    pub fn default_selected_index(mut self, index: SelectIndex) -> Self {
        self.default_selected_index = index;
        self
    }

    /// Set the style refinement for the header.
    pub fn header_style(mut self, style: &StyleRefinement) -> Self {
        self.header_style = style.clone();
        self
    }

    fn render_active_page(
        &self,
        state: &Entity<SettingsState>,
        filter: &SettingsFilter,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> gpui::AnyElement {
        let page_ix = state.read(cx).selected_index.page_ix;
        if let Some(page) = self.pages.get(page_ix)
            && !filter.groups[page_ix].is_empty()
        {
            return page
                .render(page_ix, &filter.groups[page_ix], state, options, window, cx)
                .into_any_element();
        }

        if filter.visible_pages().next().is_none() {
            return div()
                .size_full()
                .debug_selector(|| "settings-no-results".into())
                .child(Self::render_no_results())
                .into_any_element();
        }

        div().into_any_element()
    }

    fn render_no_results() -> impl IntoElement {
        Empty::new().size_full().header(
            EmptyHeader::new()
                .media(
                    EmptyMedia::new()
                        .with_variant(EmptyMediaVariant::Icon)
                        .child(Icon::new(IconName::Search)),
                )
                .title(EmptyTitle::new().child(t!("Settings.no_results")))
                .description(EmptyDescription::new().child(t!("Settings.no_results_description"))),
        )
    }

    fn render_sidebar(
        &self,
        state: &Entity<SettingsState>,
        filter: &SettingsFilter,
        _: &mut Window,
        cx: &mut App,
    ) -> impl IntoElement {
        let selected_index = state.read(cx).selected_index;
        let search_input = state.read(cx).search_input.clone();

        Sidebar::new("settings-sidebar")
            .w(relative(1.))
            .border_0()
            .refine_style(&self.sidebar_style)
            .collapsible(false)
            .collapsed(false)
            .header(
                div()
                    .w_full()
                    .refine_style(&self.header_style)
                    .child(Input::new(&search_input).prefix(IconName::Search)),
            )
            .child(
                SidebarMenu::new().children(filter.visible_pages().map(|page_ix| {
                    let page = &self.pages[page_ix];
                    let groups = &filter.groups[page_ix];
                    let is_page_active = selected_index.page_ix == page_ix
                        && (selected_index.group_ix.is_none() || groups.len() == 1);
                    SidebarMenuItem::new(page.title.clone())
                        .click_to_open(true)
                        .when_some(page.icon.clone(), |this, icon| this.icon(icon))
                        .default_open(page.default_open)
                        .active(is_page_active)
                        .on_click({
                            let state = state.clone();
                            move |_, _, cx| {
                                state.update(cx, |state, cx| {
                                    state.selected_index = SelectIndex {
                                        page_ix,
                                        ..Default::default()
                                    };
                                    state.deferred_scroll_group_ix = None;
                                    cx.notify();
                                })
                            }
                        })
                        .when(groups.len() > 1, |this| {
                            this.children(
                                groups
                                    .iter()
                                    .copied()
                                    .filter(|&ix| page.groups[ix].title.is_some())
                                    .map(|group_ix| {
                                        let group = &page.groups[group_ix];
                                        let is_active = selected_index.page_ix == page_ix
                                            && selected_index.group_ix == Some(group_ix);
                                        let title = group.title.clone().unwrap_or_default();

                                        SidebarMenuItem::new(title).active(is_active).on_click({
                                            let state = state.clone();
                                            move |_, _, cx| {
                                                state.update(cx, |state, cx| {
                                                    state.selected_index = SelectIndex {
                                                        page_ix,
                                                        group_ix: Some(group_ix),
                                                    };
                                                    state.deferred_scroll_group_ix = Some(group_ix);
                                                    cx.notify();
                                                })
                                            }
                                        })
                                    }),
                            )
                        })
                })),
            )
    }
}

impl Sizable for Settings {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

/// Visible groups in each original page. Filtering never renumbers source data.
struct SettingsFilter {
    groups: Vec<Vec<usize>>,
}

impl SettingsFilter {
    fn new(pages: &[SettingPage], query: &str, cx: &App) -> Self {
        Self {
            groups: pages
                .iter()
                .map(|page| {
                    page.groups
                        .iter()
                        .enumerate()
                        .filter_map(|(ix, group)| group.is_match(query, cx).then_some(ix))
                        .collect()
                })
                .collect(),
        }
    }

    fn visible_pages(&self) -> impl Iterator<Item = usize> + '_ {
        self.groups
            .iter()
            .enumerate()
            .filter_map(|(ix, groups)| (!groups.is_empty()).then_some(ix))
    }

    fn selected_index(&self, selected: SelectIndex) -> SelectIndex {
        let page_ix = self
            .visible_pages()
            .find(|&ix| ix == selected.page_ix)
            .or_else(|| self.visible_pages().next());
        let Some(page_ix) = page_ix else {
            // Keep the selection while there are no results so clearing the query
            // can restore it. The empty filter prevents rendering a stale page.
            return selected;
        };

        SelectIndex {
            page_ix,
            group_ix: selected
                .group_ix
                .filter(|ix| page_ix == selected.page_ix && self.groups[page_ix].contains(ix)),
        }
    }
}

pub(super) struct SettingsState {
    pub(super) selected_index: SelectIndex,
    /// If set, defer scrolling to this group index after rendering.
    pub(super) deferred_scroll_group_ix: Option<usize>,
    pub(super) search_input: Entity<InputState>,
}

/// Options for rendering setting item.
///
/// The fields are private and reached through the methods below, so that a new
/// one can be added without breaking the item renderers. The setters take
/// `self` by value, so a nested renderer narrows a copy of its parent options:
///
/// ```ignore
/// item.render_item(&options.with_item_ix(item_ix), window, cx)
/// ```
#[derive(Clone, Copy)]
pub struct RenderOptions {
    page_ix: usize,
    group_ix: usize,
    item_ix: usize,
    size: Size,
    group_variant: GroupBoxVariant,
    layout: Axis,
    disabled: bool,
}

impl RenderOptions {
    pub fn new() -> Self {
        Self {
            page_ix: 0,
            group_ix: 0,
            item_ix: 0,
            size: Size::default(),
            group_variant: GroupBoxVariant::default(),
            layout: Axis::Horizontal,
            disabled: false,
        }
    }

    pub fn with_page_ix(mut self, page_ix: usize) -> Self {
        self.page_ix = page_ix;
        self
    }

    pub fn with_group_ix(mut self, group_ix: usize) -> Self {
        self.group_ix = group_ix;
        self
    }

    pub fn with_item_ix(mut self, item_ix: usize) -> Self {
        self.item_ix = item_ix;
        self
    }

    pub fn with_size(mut self, size: Size) -> Self {
        self.size = size;
        self
    }

    pub fn with_group_variant(mut self, group_variant: GroupBoxVariant) -> Self {
        self.group_variant = group_variant;
        self
    }

    pub fn with_layout(mut self, layout: Axis) -> Self {
        self.layout = layout;
        self
    }

    pub fn with_disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn page_ix(&self) -> usize {
        self.page_ix
    }

    pub fn group_ix(&self) -> usize {
        self.group_ix
    }

    pub fn item_ix(&self) -> usize {
        self.item_ix
    }

    pub fn size(&self) -> Size {
        self.size
    }

    pub fn group_variant(&self) -> GroupBoxVariant {
        self.group_variant
    }

    pub fn layout(&self) -> Axis {
        self.layout
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }
}

impl Default for RenderOptions {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone, Copy, Default)]
pub struct SelectIndex {
    pub page_ix: usize,
    pub group_ix: Option<usize>,
}

impl RenderOnce for Settings {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = window.use_keyed_state(self.id.clone(), cx, |window, cx| {
            let search_input = cx.new(|cx| {
                InputState::new(window, cx)
                    .placeholder(t!("Settings.search_placeholder"))
                    .default_value("")
            });

            SettingsState {
                search_input,
                selected_index: self.default_selected_index,
                deferred_scroll_group_ix: None,
            }
        });

        let query = state.read(cx).search_input.read(cx).value();
        let filter = SettingsFilter::new(&self.pages, &query, cx);
        let previous = state.read(cx).selected_index;
        let selected = filter.selected_index(previous);
        if selected.page_ix != previous.page_ix || selected.group_ix != previous.group_ix {
            state.update(cx, |state, _| {
                state.selected_index = selected;
                state.deferred_scroll_group_ix = None;
            });
        }
        let options = RenderOptions::new()
            .with_size(self.size)
            .with_group_variant(self.group_variant);
        let sidebar_size_range = self.sidebar_size_range.clone();
        let sidebar = self
            .render_sidebar(&state, &filter, window, cx)
            .into_any_element();

        h_resizable(self.id.clone())
            .child(
                resizable_panel()
                    .size(self.sidebar_width)
                    .size_range(sidebar_size_range)
                    .child(sidebar),
            )
            .child(
                resizable_panel().child(container_query(move |size, window, cx| {
                    let options = options.with_layout(if size.width <= STACKED_LAYOUT_MAX_WIDTH {
                        Axis::Vertical
                    } else {
                        Axis::Horizontal
                    });
                    self.render_active_page(&state, &filter, &options, window, cx)
                })),
            )
    }
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
