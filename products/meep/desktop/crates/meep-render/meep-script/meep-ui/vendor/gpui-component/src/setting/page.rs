use std::rc::Rc;

use gpui::{
    AnyElement, App, Entity, InteractiveElement as _, IntoElement, ListAlignment, ListOffset,
    ListState, ParentElement as _, SharedString, StyleRefinement, Styled, Window, div, list,
    prelude::FluentBuilder as _, px,
};
use rust_i18n::t;

use crate::{
    ActiveTheme, Icon, IconName, Sizable, StyledExt,
    button::{Button, ButtonVariants},
    h_flex,
    label::Label,
    scroll::ScrollableElement,
    setting::{RenderOptions, SettingGroup, settings::SettingsState},
    v_flex,
};

/// A setting page that can contain multiple setting groups.
#[derive(Clone)]
pub struct SettingPage {
    pub(super) icon: Option<Icon>,
    resettable: bool,
    pub(super) default_open: bool,
    pub(super) title: SharedString,
    pub(super) title_suffix: Option<Rc<dyn Fn(&mut Window, &mut App) -> AnyElement>>,
    pub(super) description: Option<SharedString>,
    pub(super) groups: Vec<SettingGroup>,
    pub(super) header_style: StyleRefinement,
}

impl SettingPage {
    pub fn new(title: impl Into<SharedString>) -> Self {
        Self {
            icon: None,
            resettable: true,
            default_open: false,
            title: title.into(),
            title_suffix: None,
            description: None,
            groups: Vec::new(),
            header_style: StyleRefinement::default(),
        }
    }

    /// Set the title of the setting page.
    pub fn title(mut self, title: impl Into<SharedString>) -> Self {
        self.title = title.into();
        self
    }

    /// Set a custom element to render after the title in the page header.
    ///
    /// For example, an info icon button that opens the help documentation.
    pub fn title_suffix<F, E>(mut self, suffix: F) -> Self
    where
        E: IntoElement,
        F: Fn(&mut Window, &mut App) -> E + 'static,
    {
        self.title_suffix = Some(Rc::new(move |window, cx| {
            suffix(window, cx).into_any_element()
        }));
        self
    }

    /// Set the icon of the setting page.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.icon = Some(icon.into());
        self
    }

    /// Set the description of the setting page, default is None.
    pub fn description(mut self, description: impl Into<SharedString>) -> Self {
        self.description = Some(description.into());
        self
    }

    /// Set the default open state of the setting page, default is false.
    pub fn default_open(mut self, default_open: bool) -> Self {
        self.default_open = default_open;
        self
    }

    /// Set whether the setting page is resettable, default is true.
    ///
    /// If true and the items in this page has changed, the reset button will appear.
    pub fn resettable(mut self, resettable: bool) -> Self {
        self.resettable = resettable;
        self
    }

    /// Add a setting group to the page.
    pub fn group(mut self, group: SettingGroup) -> Self {
        self.groups.push(group);
        self
    }

    /// Add multiple setting groups to the page.
    pub fn groups(mut self, groups: impl IntoIterator<Item = SettingGroup>) -> Self {
        self.groups.extend(groups);
        self
    }

    /// Set the style refinement for the header of the setting page.
    pub fn header_style(mut self, style: &StyleRefinement) -> Self {
        self.header_style = style.clone();
        self
    }

    fn is_resettable(&self, query: &str, cx: &App) -> bool {
        self.resettable
            && self
                .groups
                .iter()
                .any(|group| group.is_resettable(query, cx))
    }

    fn reset_all(&self, query: &str, window: &mut Window, cx: &mut App) {
        for group in &self.groups {
            group.reset(query, window, cx);
        }
    }

    /// The group the sidebar marks for the given scroll position: the titled
    /// group at or above the top of the viewport. At the end of the list the
    /// last groups cannot reach the top, so a group selected below the top
    /// stays marked, and the last group is marked otherwise. `None` marks the
    /// page itself.
    fn group_at_scroll_top(
        &self,
        group_indices: &[usize],
        selected_group_ix: Option<usize>,
        scroll_top: ListOffset,
        is_scrolled_to_end: bool,
    ) -> Option<usize> {
        let selected_pos =
            selected_group_ix.and_then(|ix| group_indices.iter().position(|&g| g == ix));
        if is_scrolled_to_end && selected_pos.is_some_and(|pos| pos > scroll_top.item_ix) {
            return selected_group_ix;
        }

        let top_pos = if is_scrolled_to_end {
            group_indices.len().saturating_sub(1)
        } else {
            scroll_top.item_ix
        };
        group_indices
            .iter()
            .take(top_pos + 1)
            .rev()
            .copied()
            .find(|&ix| self.groups[ix].title.is_some())
    }

    pub(super) fn render(
        &self,
        ix: usize,
        group_indices: &[usize],
        state: &Entity<SettingsState>,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> impl IntoElement {
        let search_input = state.read(cx).search_input.clone();
        let query = search_input.read(cx).value();
        let groups = group_indices
            .iter()
            .map(|&ix| (ix, self.groups[ix].clone()))
            .collect::<Vec<_>>();
        let groups_count = groups.len();

        let page_state = window.use_keyed_state(
            SharedString::from(format!("list-state:{}", ix)),
            cx,
            |_, _| PageState {
                list: ListState::new(groups_count, ListAlignment::Top, px(100.)),
                query: query.clone(),
                groups: group_indices.to_vec(),
                scroll_top: ListOffset::default(),
                scrolled_programmatically: false,
            },
        );
        let changed =
            page_state.read(cx).query != query || page_state.read(cx).groups != group_indices;
        let list_state = page_state.read(cx).list.clone();
        if changed {
            page_state.update(cx, |state, _| {
                state.list.reset(groups_count);
                state.query = query.clone();
                state.groups = group_indices.to_vec();
            });
        }

        let deferred_scroll_group_ix = state.read(cx).deferred_scroll_group_ix;
        let scroll_group_ix = deferred_scroll_group_ix.or_else(|| {
            changed
                .then_some(state.read(cx).selected_index.group_ix)
                .flatten()
        });
        if deferred_scroll_group_ix.is_some() {
            state.update(cx, |state, _| state.deferred_scroll_group_ix = None);
        }
        if let Some(group_ix) = scroll_group_ix
            && let Some(visible_ix) = group_indices.iter().position(|&ix| ix == group_ix)
        {
            // Scroll by index: after a page switch the list is rebuilt unmeasured,
            // and `scroll_to_reveal_item` would resolve to the top.
            list_state.scroll_to(ListOffset {
                item_ix: visible_ix,
                offset_in_item: px(0.),
            });
        }

        // Follow the scroll position in the sidebar, like a table of contents.
        let scroll_top = list_state.logical_scroll_top();
        let programmatic = changed || scroll_group_ix.is_some();
        let scrolled = !programmatic
            && !page_state.read(cx).scrolled_programmatically
            && page_state.read(cx).scroll_top != scroll_top;
        page_state.update(cx, |state, _| {
            state.scroll_top = scroll_top;
            state.scrolled_programmatically = programmatic;
        });
        if scrolled {
            let selected_group_ix = state.read(cx).selected_index.group_ix;
            let group_ix = self.group_at_scroll_top(
                group_indices,
                selected_group_ix,
                scroll_top,
                list_state.is_scrolled_to_end() == Some(true),
            );
            if group_ix != selected_group_ix {
                state.update(cx, |state, _| state.selected_index.group_ix = group_ix);
                // The sidebar has already been rendered in this frame.
                window.refresh();
            }
        }

        v_flex()
            .id(ix)
            .size_full()
            .child(
                v_flex()
                    .p_4()
                    .gap_3()
                    .border_b_1()
                    .border_color(cx.theme().border)
                    .refine_style(&self.header_style)
                    .child(
                        h_flex()
                            .justify_between()
                            .child(
                                h_flex()
                                    .gap_1()
                                    .child(self.title.clone())
                                    .when_some(self.title_suffix.clone(), |this, suffix| {
                                        this.child(suffix(window, cx))
                                    }),
                            )
                            .when(self.is_resettable(&query, cx), |this| {
                                this.child(
                                    Button::new("reset")
                                        .icon(IconName::Undo2)
                                        .ghost()
                                        .small()
                                        .tooltip(t!("Settings.Reset All"))
                                        .on_click({
                                            let page = self.clone();
                                            let query = query.clone();
                                            move |_, window, cx| {
                                                page.reset_all(&query, window, cx);
                                            }
                                        }),
                                )
                            }),
                    )
                    .when_some(self.description.clone(), |this, description| {
                        this.child(
                            Label::new(description)
                                .text_sm()
                                .text_color(cx.theme().muted_foreground),
                        )
                    }),
            )
            .child(
                div()
                    .relative()
                    .flex_1()
                    .w_full()
                    .child(gpui_base::ScrollBounce::new(
                        "bounce",
                        &list_state,
                        list(list_state.clone(), {
                            let query = query.clone();
                            let options = *options;
                            move |visible_ix, window, cx| {
                                let (group_ix, group) = groups[visible_ix].clone();
                                // Keep horizontal padding inside the list's clip bounds
                                // so focus rings can extend beyond the group's edges.
                                div()
                                    .w_full()
                                    .px_4()
                                    .child(group.py_4().render(
                                        &query,
                                        &options.with_page_ix(ix).with_group_ix(group_ix),
                                        window,
                                        cx,
                                    ))
                                    .into_any_element()
                            }
                        })
                        .size_full(),
                    ))
                    .vertical_scrollbar(&list_state),
            )
    }
}

struct PageState {
    list: ListState,
    query: SharedString,
    groups: Vec<usize>,
    /// The scroll position seen by the last render.
    scroll_top: ListOffset,
    /// Set when the page scrolls itself, so the clamping applied by the next
    /// layout is not mistaken for the user moving through the page.
    scrolled_programmatically: bool,
}
