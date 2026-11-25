use gpui::{
    AnyElement, App, Bounds, ClickEvent, Context, DismissEvent, Edges, ElementId, Entity,
    EventEmitter, FocusHandle, Focusable, Hsla, InteractiveElement, IntoElement, Length,
    MouseDownEvent, ParentElement, Pixels, Render, RenderOnce, SharedString,
    StatefulInteractiveElement, StyleRefinement, Styled, Window, deferred, div,
    prelude::FluentBuilder, px, rems,
};

use rust_i18n::t;

pub use crate::select::Caret;

use crate::ThemeStyled as _;
use crate::{
    ActiveTheme, Disableable, ElementExt as _, Icon, IconName, IndexPath, Sizable, Size,
    StyleSized, StyledExt, h_flex,
    input::{clear_button, input_style},
    list::{List, ListState},
    searchable_list::{
        SearchableListAdapter, SearchableListChange, SearchableListDelegate, SearchableListItem,
        SearchableListState,
    },
    sizing::DROPDOWN_LIST_PADDING,
    v_flex,
};
use gpui_base::{Combobox as BaseCombobox, GlobalState};

// MARK: ComboboxTriggerContext

/// Context passed to the `render_trigger` closure on [`Combobox`].
///
/// The fields are private and reached through the methods below, so that a new
/// one can be added without breaking the trigger renderers.
pub struct ComboboxTriggerContext<'a, D: SearchableListDelegate + 'static> {
    selection: &'a [(IndexPath, D::Item)],
    placeholder: Option<&'a SharedString>,
    open: bool,
    disabled: bool,
    size: Size,
}

impl<'a, D: SearchableListDelegate + 'static> ComboboxTriggerContext<'a, D> {
    /// The items currently selected, empty when the combobox has no value.
    pub fn selection(&self) -> &'a [(IndexPath, D::Item)] {
        self.selection
    }

    pub fn placeholder(&self) -> Option<&'a SharedString> {
        self.placeholder
    }

    /// Whether the dropdown list is showing.
    pub fn is_open(&self) -> bool {
        self.open
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn size(&self) -> Size {
        self.size
    }
}

// MARK: ComboboxChange

/// Back-compat alias — new code should use [`SearchableListChange`] directly.
pub type ComboboxChange = SearchableListChange;

// MARK: ComboboxOptions

struct ComboboxOptions {
    style: StyleRefinement,
    size: Size,
    cleanable: bool,
    placeholder: Option<SharedString>,
    search_placeholder: Option<SharedString>,
    menu_width: Length,
    menu_max_h: Length,
    disabled: bool,
    appearance: bool,
    focus_ring_enabled: bool,
    trigger_icon: Option<Icon>,
    check_icon: Option<Icon>,
}

impl Default for ComboboxOptions {
    fn default() -> Self {
        Self {
            style: StyleRefinement::default(),
            size: Size::default(),
            cleanable: false,
            placeholder: None,
            search_placeholder: None,
            menu_width: Length::Auto,
            menu_max_h: rems(20.).into(),
            disabled: false,
            appearance: true,
            focus_ring_enabled: true,
            trigger_icon: None,
            check_icon: None,
        }
    }
}

// MARK: ComboboxState

/// State of the [`Combobox`] component.
pub struct ComboboxState<D: SearchableListDelegate + 'static>
where
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    pub(crate) state: SearchableListState<D>,

    // Combobox-specific fields
    multiple: bool,
    searchable: bool,
    trigger_icon: Option<Icon>,
    check_icon: Option<Icon>,
    render_trigger: Option<
        Box<dyn Fn(&ComboboxTriggerContext<D>, &mut Window, &mut App) -> AnyElement + 'static>,
    >,
    footer: Option<Box<dyn Fn(&mut Window, &mut App) -> AnyElement + 'static>>,
    focus_ring_enabled: bool,
}

/// Events emitted by [`ComboboxState`].
pub enum ComboboxEvent<D: SearchableListDelegate + 'static>
where
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    /// Emitted on every toggle (item added or removed).
    Change(Vec<<D::Item as SearchableListItem>::Value>),
    /// Emitted when the popover closes.
    Confirm(Vec<<D::Item as SearchableListItem>::Value>),
}

impl<D> ComboboxState<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    /// Create a new `Combobox` state.
    pub fn new(
        delegate: D,
        selected_indices: Vec<IndexPath>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Self {
        let weak = cx.entity().downgrade();
        let weak_confirm = weak.clone();
        let weak_cancel = weak.clone();
        let weak_empty = weak;

        let state = SearchableListState::new(
            delegate,
            selected_indices,
            move |selected_index, _secondary, window, cx| {
                cx.defer_in(window, {
                    let weak_confirm = weak_confirm.clone();
                    move |list_state, window, cx| {
                        let Some(index) = selected_index else {
                            return;
                        };

                        let Some(item) = list_state.delegate().delegate.item(index).cloned() else {
                            return;
                        };

                        let ix = index;

                        let Some(weak) = weak_confirm.upgrade() else {
                            return;
                        };

                        let (multiple, mut selection) = {
                            let s = weak.read(cx);
                            (s.multiple, s.state.selection.clone())
                        };

                        let changes = Self::selection_changes(multiple, &selection, ix, &item);

                        let before_values: Vec<_> = selection
                            .iter()
                            .map(|(_, item)| item.value().clone())
                            .collect();

                        // on_will_change is called directly — entity-handle access would
                        // re-enter the ListState lock that defer_in holds for this callback.
                        list_state
                            .delegate_mut()
                            .delegate
                            .on_will_change(&mut selection, &changes);

                        let after_values: Vec<_> = selection
                            .iter()
                            .map(|(_, item)| item.value().clone())
                            .collect();
                        let changed = before_values != after_values;
                        let should_close = !multiple
                            && (changed
                                || selection
                                    .iter()
                                    .any(|(_, selected)| selected.value() == item.value()));

                        let new_selection = weak_confirm.update(cx, |this, cx| {
                            this.state.selection = selection;

                            if changed {
                                cx.emit(ComboboxEvent::Change(this.selected_values()));
                                cx.notify();
                            }

                            if should_close {
                                cx.emit(ComboboxEvent::Confirm(this.selected_values()));
                                this.set_open(false, cx);
                                this.focus(window, cx);
                            }

                            this.state.selection.clone()
                        });

                        // Sync snapshot and fire on_confirm directly — same re-entrancy guard.
                        if let Ok(new_selection) = new_selection {
                            list_state
                                .delegate_mut()
                                .update_selection_snapshot(new_selection.clone());

                            if should_close {
                                list_state
                                    .delegate_mut()
                                    .delegate
                                    .on_confirm(&new_selection);
                            }
                        }
                    }
                });
            },
            // on_cancel — close and emit Confirm with current values
            move |_final_selected_index, window, cx| {
                cx.defer_in(window, {
                    let weak_cancel = weak_cancel.clone();
                    move |_list_state, window, cx| {
                        _ = weak_cancel.update(cx, |this, cx| {
                            // Cancel propagates to the BaseCombobox, which may already
                            // have confirmed and closed before this deferred callback.
                            if !this.state.open {
                                return;
                            }
                            cx.emit(ComboboxEvent::Confirm(this.selected_values()));
                            this.set_open(false, cx);
                            this.focus(window, cx);
                        });
                    }
                });
            },
            // on_render_empty
            move |window, cx| {
                if let Some(empty) = weak_empty
                    .upgrade()
                    .and_then(|e| e.read(cx).state.empty.as_ref().map(|f| f(window, cx)))
                {
                    empty
                } else {
                    h_flex()
                        .justify_center()
                        .py_6()
                        .text_color(cx.theme().muted_foreground.opacity(0.6))
                        .child(Icon::new(IconName::Inbox).size(px(28.)))
                        .into_any_element()
                }
            },
            Self::on_blur,
            window,
            cx,
        );

        Self {
            state,
            multiple: false,
            searchable: false,
            trigger_icon: None,
            check_icon: None,
            render_trigger: None,
            footer: None,
            focus_ring_enabled: true,
        }
    }

    /// Enable multi-select mode.
    ///
    /// When `true`, clicking an item toggles it in the selection and the popover stays open.
    /// When `false` (default), clicking an item replaces the selection and closes the popover.
    pub fn multiple(mut self, multiple: bool) -> Self {
        self.multiple = multiple;
        self
    }

    /// Enable or disable the search input at the top of the dropdown.
    pub fn searchable(mut self, searchable: bool) -> Self {
        self.searchable = searchable;
        self
    }

    /// Return the currently selected values.
    pub fn selected_values(&self) -> Vec<<D::Item as SearchableListItem>::Value> {
        self.state.selected_values()
    }

    /// Return the first selected value, or `None` when nothing is selected.
    ///
    /// Convenience for single-select mode (`.multiple(false)`).
    pub fn selected_value(&self) -> Option<<D::Item as SearchableListItem>::Value> {
        self.state.selected_values().into_iter().next()
    }

    /// Return the currently selected `(IndexPath, Item)` pairs.
    pub fn selection(&self) -> &[(IndexPath, D::Item)] {
        self.state.selection()
    }

    /// Replace the entire selection set by item values.
    ///
    /// Values are resolved through the current delegate. Values that cannot be resolved are
    /// ignored. This updates the committed selection and snapshot without emitting a
    /// [`ComboboxEvent`].
    pub fn set_selected_values(
        &mut self,
        values: &[<D::Item as SearchableListItem>::Value],
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.state.clear_query(window, cx);

        let selected_indices = {
            let list = self.state.list.read(cx);
            let delegate = &list.delegate().delegate;

            values
                .iter()
                .filter_map(|value| delegate.position(value))
                .collect::<Vec<_>>()
        };

        self.set_selected_indices(selected_indices, window, cx);
    }

    /// Replace the entire selection set.
    pub fn set_selected_indices(
        &mut self,
        indices: impl IntoIterator<Item = IndexPath>,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.state.set_selected_indices(indices, cx);
        self.state.sync_snapshot(cx);
        cx.notify();
    }

    /// Add a single index to the selection, if not already present, returning whether it was added.
    pub fn add_selected_index(&mut self, index: IndexPath, cx: &mut Context<Self>) -> bool {
        let added = self.state.add_selected_index(index, cx);

        if added {
            self.state.sync_snapshot(cx);
            cx.notify();
        }

        added
    }

    /// Remove a single index from the selection, returning whether it was removed.
    pub fn remove_selected_index(&mut self, index: IndexPath, cx: &mut Context<Self>) -> bool {
        let removed = self.state.remove_selected_index(index);

        if removed {
            self.state.sync_snapshot(cx);
        }

        removed
    }

    /// Clear all selected values.
    pub fn clear_selection(&mut self, cx: &mut Context<Self>) {
        self.state.selection.clear();
        self.state.sync_snapshot(cx);
        cx.emit(ComboboxEvent::Change(self.selected_values()));
        cx.notify();
    }

    /// Replace the underlying delegate (item data source).
    pub fn set_items(&mut self, items: D, _: &mut Window, cx: &mut Context<Self>) {
        self.state.list.update(cx, |list, _| {
            list.delegate_mut().delegate = items;
        });
    }

    /// Focus the trigger.
    pub fn focus(&self, window: &mut Window, cx: &mut App) {
        self.state.focus_handle.focus(window, cx);
    }

    /// Returns the search query.
    pub fn query(&self, cx: &App) -> SharedString {
        self.state.list.read(cx).query_input.read(cx).value()
    }

    /// Sets the search query and updates the filtered items.
    pub fn set_query(&self, query: impl Into<SharedString>, window: &mut Window, cx: &mut App) {
        let query = query.into();
        self.state.list.update(cx, |list, cx| {
            list.set_query(query.as_ref(), window, cx);
        });
    }

    fn selection_changes(
        multiple: bool,
        selection: &[(IndexPath, D::Item)],
        ix: IndexPath,
        item: &D::Item,
    ) -> Vec<SearchableListChange> {
        let is_selected = selection
            .iter()
            .any(|(_, selected_item)| selected_item.value() == item.value());

        if multiple {
            if is_selected {
                vec![SearchableListChange::Deselect { index: ix }]
            } else {
                vec![SearchableListChange::Select { index: ix }]
            }
        } else {
            let mut changes: Vec<SearchableListChange> = selection
                .iter()
                .map(|(cur_ix, _)| SearchableListChange::Deselect { index: *cur_ix })
                .collect();
            changes.push(SearchableListChange::Select { index: ix });
            changes
        }
    }

    /// Process an item click: single-select replaces the selection and closes; multi-select toggles.
    ///
    /// Calls `delegate.on_will_change` before committing and `delegate.on_confirm` when closing.
    #[allow(dead_code)]
    pub(crate) fn handle_item_select(
        &mut self,
        ix: IndexPath,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(item) = self
            .state
            .list
            .read(cx)
            .delegate()
            .delegate
            .item(ix)
            .cloned()
        else {
            return;
        };

        let changes = Self::selection_changes(self.multiple, &self.state.selection, ix, &item);

        let mut selection = self.state.selection.clone();
        let before_values: Vec<_> = selection
            .iter()
            .map(|(_, item)| item.value().clone())
            .collect();

        self.state.list.update(cx, |list, _cx| {
            list.delegate_mut()
                .delegate
                .on_will_change(&mut selection, &changes);
        });

        let after_values: Vec<_> = selection
            .iter()
            .map(|(_, item)| item.value().clone())
            .collect();
        let changed = before_values != after_values;
        let should_close = !self.multiple
            && (changed
                || selection
                    .iter()
                    .any(|(_, selected)| selected.value() == item.value()));

        self.state.selection = selection;
        self.state.sync_snapshot(cx);

        if changed {
            cx.emit(ComboboxEvent::Change(self.selected_values()));
            cx.notify();
        }

        if should_close {
            let final_selection = self.state.selection.clone();
            self.state.list.update(cx, |list, _cx| {
                list.delegate_mut().delegate.on_confirm(&final_selection);
            });

            cx.emit(ComboboxEvent::Confirm(self.selected_values()));
            self.set_open(false, cx);
            self.focus(window, cx);
        }
    }

    fn on_blur(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.state.list.read(cx).is_focused(window, cx)
            || self.state.focus_handle.is_focused(window)
        {
            return;
        }

        self.set_open(false, cx);
        cx.notify();
    }

    fn toggle_menu(&mut self, _: &ClickEvent, window: &mut Window, cx: &mut Context<Self>) {
        cx.stop_propagation();

        self.set_open(!self.state.open, cx);

        if self.state.open {
            self.state.list.focus_handle(cx).focus(window, cx);
        } else {
            cx.emit(ComboboxEvent::Confirm(self.selected_values()));
            self.focus(window, cx);
        }

        cx.notify();
    }

    /// Close the menu when a press lands outside the popup.
    ///
    /// A press on the trigger is left to propagate: swallowing it here would keep nested
    /// controls (a tag remove button, the clear button) from ever seeing the press, and
    /// `toggle_menu` closes the menu on release anyway.
    fn dismiss(&mut self, event: &MouseDownEvent, window: &mut Window, cx: &mut Context<Self>) {
        if !self.state.open || self.state.bounds.contains(&event.position) {
            return;
        }

        cx.stop_propagation();
        cx.emit(ComboboxEvent::Confirm(self.selected_values()));

        self.set_open(false, cx);
        self.focus(window, cx);
        cx.notify();
    }

    fn set_open(&mut self, open: bool, cx: &mut Context<Self>) {
        self.state.open = open;
        self.state.deferred_context = open.then(|| GlobalState::register_deferred_popover(cx));

        cx.notify();
    }

    fn clean(&mut self, _: &ClickEvent, _: &mut Window, cx: &mut Context<Self>) {
        cx.stop_propagation();
        self.clear_selection(cx);
    }

    fn default_trigger_body(&self, _window: &mut Window, cx: &mut Context<Self>) -> AnyElement {
        let placeholder_text = self
            .state
            .placeholder
            .clone()
            .unwrap_or_else(|| t!("Combobox.placeholder").into());

        if self.state.selection.is_empty() {
            return div()
                .text_color(cx.theme().muted_foreground)
                .child(placeholder_text)
                .into_any_element();
        }

        if self.multiple {
            let items: Vec<SharedString> = self
                .state
                .selection
                .iter()
                .map(|(_, i)| i.title())
                .collect();

            div()
                .w_full()
                .overflow_hidden()
                .whitespace_nowrap()
                .truncate()
                .child(items.join(", "))
                .into_any_element()
        } else {
            let title = self
                .state
                .selection
                .first()
                .map(|(_, i)| i.title())
                .unwrap_or_default();

            div()
                .w_full()
                .overflow_hidden()
                .whitespace_nowrap()
                .truncate()
                .child(title)
                .into_any_element()
        }
    }
}

impl<D> Render for ComboboxState<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let searchable = self.searchable;
        let is_focused = self.state.focus_handle.is_focused(window);
        let show_clean = self.state.cleanable && !self.state.selection.is_empty();
        let bounds = self.state.bounds;
        let allow_open = !self.state.disabled;
        let outline_visible = self.state.open || (is_focused && !self.state.disabled);
        let disabled = self.state.disabled;

        let (bg, fg) = input_style(disabled, cx);

        self.state.list.update(cx, |list, cx| {
            list.set_searchable(searchable, cx);
            list.delegate_mut().size = self.state.size;
            list.delegate_mut().check_icon = self.check_icon.clone();
        });

        let selection = &self.state.selection;
        let placeholder = self.state.placeholder.as_ref();
        let open = self.state.open;
        let size = self.state.size;
        let has_custom_trigger = self.render_trigger.is_some();

        let trigger_body = if let Some(render_trigger) = &self.render_trigger {
            let trigger = ComboboxTriggerContext {
                selection,
                placeholder,
                open,
                disabled,
                size,
            };

            render_trigger(&trigger, window, cx)
        } else {
            self.default_trigger_body(window, cx)
        };

        let trailing: AnyElement = if has_custom_trigger {
            div().into_any_element()
        } else if show_clean {
            clear_button(cx)
                .map(|this| {
                    if disabled {
                        this.disabled(true)
                    } else {
                        this.on_click(cx.listener(Self::clean))
                    }
                })
                .into_any_element()
        } else if let Some(icon) = self.trigger_icon.clone() {
            icon.xsmall()
                .text_color(cx.theme().muted_foreground)
                .into_any_element()
        } else {
            Caret::new(size)
                .text_color(cx.theme().muted_foreground)
                .into_any_element()
        };

        let toggle_handler: Option<Box<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>> =
            if allow_open {
                Some(Box::new(cx.listener(Self::toggle_menu)))
            } else {
                None
            };

        let footer_el = self.footer.as_ref().map(|f| f(window, cx));

        let dismiss_handler: Box<dyn Fn(&MouseDownEvent, &mut Window, &mut App) + 'static> =
            Box::new(cx.listener(Self::dismiss));

        div().size_full().relative().child(
            div()
                .relative()
                .on_prepaint({
                    let state = cx.entity();
                    move |bounds, _, cx| state.update(cx, |r, _| r.state.bounds = bounds)
                })
                .child(render_trigger_container(
                    disabled,
                    self.state.appearance,
                    self.focus_ring_enabled,
                    self.state.size,
                    &self.state.style,
                    bg,
                    fg,
                    outline_visible,
                    allow_open,
                    trigger_body,
                    trailing,
                    toggle_handler,
                    window,
                    cx,
                ))
                .when(self.state.open, |this| {
                    this.child(
                        deferred(render_popup_shell(
                            ("combobox-popup", cx.entity_id()),
                            &self.state.list,
                            self.state.menu_width,
                            self.state.search_placeholder.clone(),
                            self.state.size,
                            self.state.menu_max_h,
                            bounds,
                            footer_el,
                            dismiss_handler,
                            cx,
                        ))
                        .with_priority(gpui_base::POPUP_PRIORITY),
                    )
                }),
        )
    }
}

impl<D> EventEmitter<ComboboxEvent<D>> for ComboboxState<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
}
impl<D> EventEmitter<DismissEvent> for ComboboxState<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
}

impl<D> Focusable for ComboboxState<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    fn focus_handle(&self, cx: &App) -> FocusHandle {
        if self.state.open {
            self.state.list.focus_handle(cx)
        } else {
            self.state.focus_handle.clone()
        }
    }
}

// MARK: Combobox element

/// A combo box with support for single and multi-select.
///
/// Clicking an item toggles it in the selection; the dropdown stays open until the user
/// presses Escape or clicks outside.
#[derive(IntoElement)]
pub struct Combobox<D: SearchableListDelegate + 'static>
where
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    id: ElementId,
    state: Entity<ComboboxState<D>>,
    options: ComboboxOptions,
    render_trigger: Option<
        Box<dyn Fn(&ComboboxTriggerContext<D>, &mut Window, &mut App) -> AnyElement + 'static>,
    >,
    footer: Option<Box<dyn Fn(&mut Window, &mut App) -> AnyElement + 'static>>,
    empty: Option<Box<dyn Fn(&mut Window, &App) -> AnyElement + 'static>>,
}

impl<D> Combobox<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    pub fn new(state: &Entity<ComboboxState<D>>) -> Self {
        Self {
            id: ("multi-combo-box", state.entity_id()).into(),
            state: state.clone(),
            options: ComboboxOptions::default(),
            render_trigger: None,
            footer: None,
            empty: None,
        }
    }

    /// Set the width of the dropdown menu.
    pub fn menu_width(mut self, width: impl Into<Length>) -> Self {
        self.options.menu_width = width.into();
        self
    }

    /// Set the maximum height of the dropdown menu.
    pub fn menu_max_h(mut self, max_h: impl Into<Length>) -> Self {
        self.options.menu_max_h = max_h.into();
        self
    }

    /// Set the placeholder text shown when no items are selected.
    pub fn placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.options.placeholder = Some(placeholder.into());
        self
    }

    /// Override the trigger chevron icon.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.options.trigger_icon = Some(icon.into());
        self
    }

    /// Override the trailing check icon shown next to selected items.
    pub fn check_icon(mut self, icon: impl Into<Icon>) -> Self {
        self.options.check_icon = Some(icon.into());
        self
    }

    /// Set the placeholder text for the search input.
    pub fn search_placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.options.search_placeholder = Some(placeholder.into());
        self
    }

    /// Show a clear button when at least one item is selected.
    pub fn cleanable(mut self, cleanable: bool) -> Self {
        self.options.cleanable = cleanable;
        self
    }

    /// Set the disabled state.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.options.disabled = disabled;
        self
    }

    /// Set a custom closure that renders the empty-state element.
    pub fn empty<E: IntoElement + 'static>(
        mut self,
        builder: impl Fn(&mut Window, &App) -> E + 'static,
    ) -> Self {
        self.empty = Some(Box::new(move |window, cx| {
            builder(window, cx).into_any_element()
        }));
        self
    }

    /// Control whether the trigger shows a border and background.
    pub fn appearance(mut self, appearance: bool) -> Self {
        self.options.appearance = appearance;
        self
    }

    /// Override the entire trigger element.
    pub fn render_trigger<E: IntoElement + 'static>(
        mut self,
        f: impl Fn(&ComboboxTriggerContext<D>, &mut Window, &mut App) -> E + 'static,
    ) -> Self {
        self.render_trigger = Some(Box::new(move |trigger, window, cx| {
            f(trigger, window, cx).into_any_element()
        }));
        self
    }

    /// Render an element below a separator at the bottom of the dropdown.
    pub fn footer<E: IntoElement + 'static>(
        mut self,
        f: impl Fn(&mut Window, &mut App) -> E + 'static,
    ) -> Self {
        self.footer = Some(Box::new(move |window, cx| f(window, cx).into_any_element()));
        self
    }
}

impl<D> Sizable for Combobox<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.options.size = size.into();
        self
    }
}

impl<D> crate::FocusableExt for Combobox<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.options.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.options.focus_ring_enabled
    }
}

impl<D> Styled for Combobox<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.options.style
    }
}

impl<D> RenderOnce for Combobox<D>
where
    D: SearchableListDelegate + 'static,
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    fn render(self, _window: &mut Window, cx: &mut App) -> impl IntoElement {
        let disabled = self.options.disabled;
        let focus_handle = self.state.read(cx).state.focus_handle.clone();
        let render_trigger = self.render_trigger;
        let footer = self.footer;
        let empty = self.empty;
        let opts = self.options;

        self.state.update(cx, |this, _| {
            this.state.style = opts.style;
            this.state.size = opts.size;
            this.state.cleanable = opts.cleanable;
            this.state.placeholder = opts.placeholder;
            this.state.search_placeholder = opts.search_placeholder;
            this.state.menu_width = opts.menu_width;
            this.state.menu_max_h = opts.menu_max_h;
            this.state.disabled = opts.disabled;
            this.state.appearance = opts.appearance;
            this.focus_ring_enabled = opts.focus_ring_enabled;
            this.trigger_icon = opts.trigger_icon;
            this.check_icon = opts.check_icon;
            this.render_trigger = render_trigger;
            this.footer = footer;

            if let Some(empty) = empty {
                this.state.empty = Some(empty);
            }
        });

        let is_open = self.state.read(cx).state.open;
        let content_focus_handle = self.state.read(cx).state.list.focus_handle(cx);
        let open_state = self.state.clone();
        let confirm_state = self.state.clone();

        BaseCombobox::new(self.id)
            .open(is_open)
            .disabled(disabled)
            .focus_handle(&focus_handle)
            .content_focus_handle(&content_focus_handle)
            .on_open_change(move |open, _, cx| {
                open_state.update(cx, |state, cx| state.set_open(open, cx));
            })
            // This combobox commits its pending selection when the popup
            // closes, so it listens for dismissal rather than Confirm.
            .on_dismiss(move |_, cx| {
                confirm_state.update(cx, |state, cx| {
                    cx.emit(ComboboxEvent::Confirm(state.selected_values()));
                });
            })
            .size_full()
            .child(self.state)
    }
}

// MARK: Rendering helpers

/// Renders the styled trigger container.
#[allow(clippy::too_many_arguments)]
fn render_trigger_container(
    disabled: bool,
    appearance: bool,
    focus_ring_enabled: bool,
    size: Size,
    style: &StyleRefinement,
    bg: Hsla,
    fg: Hsla,
    outline_visible: bool,
    allow_open: bool,
    trigger_body: AnyElement,
    trailing: AnyElement,
    toggle_handler: Option<Box<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>>,
    window: &Window,
    cx: &mut App,
) -> impl IntoElement {
    div()
        .id("input")
        .relative()
        .flex()
        .items_center()
        .justify_between()
        .border_1()
        .border_color(cx.theme().transparent)
        .when(appearance, |this| {
            this.bg(bg)
                .text_color(fg)
                .when(disabled, |this| this.opacity(0.5))
                .border_color(cx.theme().input)
                .rounded(cx.theme().radius)
        })
        .input_size(size)
        .input_text_size(size)
        .refine_style(style)
        .when(outline_visible && appearance, |this| {
            this.border_1().border_color(cx.theme().ring)
        })
        .when(
            outline_visible && appearance && focus_ring_enabled,
            |this| this.focus_ring_style(window, cx),
        )
        .when(allow_open, |this| {
            this.when_some(toggle_handler, |this, handler| this.on_click(handler))
        })
        .child(
            h_flex()
                .id("inner")
                .w_full()
                .min_w_0()
                .overflow_hidden()
                .whitespace_nowrap()
                .items_center()
                .justify_between()
                .gap_1()
                .child(
                    div()
                        .flex_1()
                        .min_w_0()
                        .overflow_hidden()
                        .whitespace_nowrap()
                        .child(trigger_body),
                )
                .child(trailing),
        )
}

/// Renders the deferred anchored popup shell containing the searchable list and optional footer.
#[allow(clippy::too_many_arguments)]
fn render_popup_shell<D: SearchableListDelegate + 'static>(
    id: impl Into<ElementId>,
    list: &Entity<ListState<SearchableListAdapter<D>>>,
    menu_width: Length,
    search_placeholder: Option<SharedString>,
    size: Size,
    menu_max_h: Length,
    bounds: Bounds<Pixels>,
    footer_el: Option<AnyElement>,
    dismiss_handler: Box<dyn Fn(&MouseDownEvent, &mut Window, &mut App) + 'static>,
    cx: &mut App,
) -> AnyElement {
    let has_footer = footer_el.is_some();

    crate::popover::dropdown_popup(
        id,
        bounds,
        v_flex()
            .occlude()
            .map(|this| match menu_width {
                Length::Auto => this.w(bounds.size.width),
                Length::Definite(w) => this.w(w),
            })
            .popover_style(cx)
            .child(
                List::new(list)
                    .when_some(search_placeholder, |this, placeholder| {
                        this.search_placeholder(placeholder)
                    })
                    .with_size(size)
                    .max_h(menu_max_h)
                    .paddings(Edges::all(DROPDOWN_LIST_PADDING)),
            )
            .when(has_footer, |this| {
                this.child(
                    div()
                        .border_t_1()
                        .border_color(cx.theme().border)
                        .p_1()
                        .when_some(footer_el, |this, el| this.child(el)),
                )
            })
            .on_mouse_down_out(dismiss_handler),
        cx,
    )
    .into_any_element()
}

// MARK: Tests

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use gpui::{
        AppContext as _, Bounds, Context, Entity, Modifiers, MouseButton, MouseDownEvent, Pixels,
        Point, Subscription, TestAppContext, point, px, size,
    };

    use crate::{
        IndexPath,
        combobox::{Combobox, ComboboxEvent, ComboboxState},
        searchable_list::{
            SearchableListChange, SearchableListDelegate, SearchableListItem, SearchableListState,
            SearchableVec,
        },
    };

    struct TestComboboxEventCollector {
        event_count: Rc<Cell<usize>>,
        _subscription: Subscription,
    }

    impl TestComboboxEventCollector {
        fn new(
            state: &Entity<ComboboxState<SearchableVec<&'static str>>>,
            cx: &mut Context<Self>,
        ) -> Self {
            let event_count = Rc::new(Cell::new(0));
            let event_count_for_subscription = event_count.clone();
            let _subscription = cx.subscribe(
                state,
                move |_, _, _: &ComboboxEvent<SearchableVec<&'static str>>, _| {
                    event_count_for_subscription.set(event_count_for_subscription.get() + 1);
                },
            );

            Self {
                event_count,
                _subscription,
            }
        }
    }

    #[gpui::test]
    fn test_combo_box_builder(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["Rust", "Go", "C++"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).searchable(true));

            let _cb = Combobox::new(&state)
                .placeholder("Select language")
                .search_placeholder("Search...")
                .menu_width(gpui::px(300.))
                .menu_max_h(gpui::rems(15.))
                .cleanable(true)
                .disabled(false)
                .appearance(true);
        });
    }

    #[gpui::test]
    fn test_combo_box_search_filters_items(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["Rust", "Go", "C++"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).searchable(true));

            let count_before = state
                .read(cx)
                .state
                .list
                .read(cx)
                .delegate()
                .delegate
                .items_count(0);
            assert_eq!(count_before, 3);

            state.update(cx, |s, cx| {
                s.state.list.update(cx, |list, cx| {
                    let _ = list
                        .delegate_mut()
                        .delegate
                        .perform_search("Rust", window, cx);
                });
            });

            let count_after = state
                .read(cx)
                .state
                .list
                .read(cx)
                .delegate()
                .delegate
                .items_count(0);
            assert_eq!(count_after, 1);
        });
    }

    #[gpui::test]
    fn test_combo_box_set_query_updates_text_and_filters_items(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["Rust", "Go", "C++"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).searchable(true));

            state.update(cx, |state, cx| state.set_query(" Rust ", window, cx));

            assert_eq!(state.read(cx).query(cx).as_ref(), " Rust ");
            assert_eq!(
                state
                    .read(cx)
                    .state
                    .list
                    .read(cx)
                    .delegate()
                    .delegate
                    .items_count(0),
                1,
            );
        });
    }

    #[gpui::test]
    fn test_multi_combo_box_builder(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| {
                ComboboxState::new(items, vec![IndexPath::new(0)], window, cx)
                    .multiple(true)
                    .searchable(true)
            });

            let _cb = Combobox::new(&state)
                .placeholder("Select frameworks")
                .search_placeholder("Search...")
                .menu_width(gpui::px(300.))
                .cleanable(true)
                .disabled(false);

            assert_eq!(state.read(cx).selected_values(), vec!["React"]);
        });
    }

    #[gpui::test]
    fn test_combo_box_set_selected_values_uses_current_delegate(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true));

            state.update(cx, |state, cx| {
                state.set_selected_values(&["Vue", "Missing"], window, cx);

                assert_eq!(state.selected_values(), vec!["Vue"]);
                assert_eq!(
                    state
                        .selection()
                        .iter()
                        .map(|(index, _)| *index)
                        .collect::<Vec<_>>(),
                    vec![IndexPath::new(1)],
                );
                assert_eq!(
                    state
                        .state
                        .list
                        .read(cx)
                        .delegate()
                        .selection_snapshot
                        .as_slice(),
                    state.selection(),
                );

                state.set_items(SearchableVec::new(vec!["Vue", "Rust", "Go"]), window, cx);
                state.set_selected_values(&["Go", "Vue"], window, cx);

                assert_eq!(state.selected_values(), vec!["Go", "Vue"]);
                assert_eq!(
                    state
                        .selection()
                        .iter()
                        .map(|(index, _)| *index)
                        .collect::<Vec<_>>(),
                    vec![IndexPath::new(2), IndexPath::new(0)],
                );
                assert_eq!(
                    state
                        .state
                        .list
                        .read(cx)
                        .delegate()
                        .selection_snapshot
                        .as_slice(),
                    state.selection(),
                );

                state.set_selected_values(&[], window, cx);

                assert!(state.selection().is_empty());
                assert!(
                    state
                        .state
                        .list
                        .read(cx)
                        .delegate()
                        .selection_snapshot
                        .is_empty()
                );
            });
        });
    }

    /// A value projected in from outside is not a position in the filtered view,
    /// so an active search must not decide which values can be selected.
    #[gpui::test]
    fn test_combo_box_set_selected_values_keeps_values_hidden_by_the_search(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true));

            state.update(cx, |state, cx| {
                state.set_selected_values(&["React", "Vue"], window, cx);
                state.state.list.update(cx, |list, cx| {
                    list.set_query("Angular", window, cx);
                });

                state.set_selected_values(&["React", "Vue", "Angular"], window, cx);

                assert_eq!(
                    state.selected_values(),
                    vec!["React", "Vue", "Angular"],
                    "a value the search had hidden must survive being reapplied"
                );
                assert_eq!(
                    state
                        .selection()
                        .iter()
                        .map(|(index, _)| *index)
                        .collect::<Vec<_>>(),
                    vec![IndexPath::new(0), IndexPath::new(1), IndexPath::new(2)],
                    "clearing the query puts every selected item back in view"
                );
            });
        });
    }

    #[gpui::test]
    fn test_combo_box_set_selected_values_does_not_emit_events(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        let state = cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true))
        });
        let collector = cx.update(|_, cx| cx.new(|cx| TestComboboxEventCollector::new(&state, cx)));

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_selected_values(&["React", "Vue"], window, cx);
            });
        });

        cx.update(|_, cx| {
            assert_eq!(collector.read(cx).event_count.get(), 0);
        });
    }

    #[gpui::test]
    fn test_combo_box_initial_selection_seeds_cursor(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| {
                ComboboxState::new(items, vec![IndexPath::new(1)], window, cx).multiple(true)
            });

            let state_ref = state.read(cx);
            assert_eq!(
                state_ref.state.list.read(cx).selected_index(),
                Some(IndexPath::new(1)),
                "initial selected_indices should seed ListState.selected_index, not just the snapshot",
            );
            assert_eq!(state_ref.selected_values(), vec!["Vue"]);
        });
    }

    #[gpui::test]
    fn test_multi_combo_box_toggle(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true));

            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(0), cx));
            assert_eq!(state.read(cx).selected_values(), &["React"]);

            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(1), cx));
            assert_eq!(state.read(cx).selected_values(), &["React", "Vue"]);

            state.update(cx, |s, cx| s.remove_selected_index(IndexPath::new(0), cx));
            assert_eq!(state.read(cx).selected_values(), &["Vue"]);
        });
    }

    #[gpui::test]
    fn test_multi_combo_box_search_selection_uses_value_identity(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true));

            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(0), cx));
            assert_eq!(state.read(cx).selected_values(), &["React"]);

            state.update(cx, |s, cx| {
                s.state.list.update(cx, |list, cx| {
                    let _ = list
                        .delegate_mut()
                        .delegate
                        .perform_search("Vue", window, cx);
                });
            });

            state.read_with(cx, |s, cx| {
                let selection = s.state.selection.clone();
                let list = s.state.list.read(cx);
                let delegate = &list.delegate().delegate;
                let ix = IndexPath::new(0);
                let item = delegate.item(ix).expect("filtered item exists");

                assert_eq!(item.value(), &"Vue");
                assert!(
                    !delegate.is_item_checked(ix, item, &selection, cx),
                    "filtered row 0 should not inherit React's checked state",
                );
            });

            state.update(cx, |s, cx| {
                s.handle_item_select(IndexPath::new(0), window, cx);
            });
            assert_eq!(state.read(cx).selected_values(), &["React", "Vue"]);
        });
    }

    #[gpui::test]
    fn test_multi_combo_box_search_deselects_by_value(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true));

            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(0), cx));

            state.update(cx, |s, cx| {
                s.state.list.update(cx, |list, cx| {
                    let _ = list
                        .delegate_mut()
                        .delegate
                        .perform_search("React", window, cx);
                });
            });

            state.update(cx, |s, cx| {
                s.handle_item_select(IndexPath::new(0), window, cx);
            });
            assert!(state.read(cx).selected_values().is_empty());
        });
    }

    #[gpui::test]
    fn test_searchable_list_default_change_uses_value_identity(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let mut delegate = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let mut selection = vec![(IndexPath::new(1), "Vue")];

            let _ = delegate.perform_search("Vue", window, cx);
            delegate.on_will_change(
                &mut selection,
                &[SearchableListChange::Deselect {
                    index: IndexPath::new(0),
                }],
            );
            assert!(selection.is_empty());

            delegate.on_will_change(
                &mut selection,
                &[SearchableListChange::Select {
                    index: IndexPath::new(0),
                }],
            );
            assert_eq!(selection, vec![(IndexPath::new(0), "Vue")]);
        });
    }

    #[gpui::test]
    fn test_multi_combo_box_clear(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            let state = cx.new(|cx| {
                ComboboxState::new(
                    items,
                    vec![IndexPath::new(0), IndexPath::new(1)],
                    window,
                    cx,
                )
                .multiple(true)
            });

            assert_eq!(state.read(cx).selected_values().len(), 2);
            state.update(cx, |s, cx| s.clear_selection(cx));
            assert!(state.read(cx).selected_values().is_empty());
        });
    }

    #[gpui::test]
    fn test_single_combo_box_mode(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["Rust", "Go", "C++"]);
            let state = cx.new(|cx| ComboboxState::new(items, vec![], window, cx));

            // Default mode is Single.
            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(0), cx));
            assert_eq!(state.read(cx).selected_values(), &["Rust"]);

            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(1), cx));
            assert_eq!(state.read(cx).selected_values(), &["Rust", "Go"]);
        });
    }

    // Delegate that vetoes all selections via on_will_change by ignoring the changes.
    struct VetoDelegate(SearchableVec<&'static str>);

    impl SearchableListDelegate for VetoDelegate {
        type Item = &'static str;

        fn items_count(&self, section: usize) -> usize {
            self.0.items_count(section)
        }

        fn item(&self, ix: IndexPath) -> Option<&&'static str> {
            self.0.item(ix)
        }

        fn position<V>(&self, value: &V) -> Option<IndexPath>
        where
            &'static str: SearchableListItem<Value = V>,
            V: PartialEq,
        {
            self.0.position(value)
        }

        fn on_will_change(
            &mut self,
            _selection: &mut Vec<(IndexPath, &'static str)>,
            _changes: &[SearchableListChange],
        ) {
            // Leave selection unchanged — acts as a veto.
        }
    }

    #[gpui::test]
    fn test_on_will_change_veto(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let delegate = VetoDelegate(SearchableVec::new(vec!["Rust", "Go", "C++"]));
            let state = cx.new(|cx| ComboboxState::new(delegate, vec![], window, cx));

            // Pre-select an item directly so we can verify veto prevents changes.
            state.update(cx, |s, cx| s.add_selected_index(IndexPath::new(0), cx));
            assert_eq!(state.read(cx).selected_values(), &["Rust"]);

            // Simulate a click on index 1 via handle_item_select; on_will_change vetoes it.
            state.update(cx, |s, cx| {
                s.handle_item_select(IndexPath::new(1), window, cx);
            });

            // Selection must remain unchanged because on_will_change left it unmodified.
            assert_eq!(state.read(cx).selected_values(), &["Rust"]);
        });
    }

    struct RedirectDelegate {
        items: SearchableVec<&'static str>,
        confirmations: Rc<Cell<usize>>,
    }

    impl SearchableListDelegate for RedirectDelegate {
        type Item = &'static str;

        fn items_count(&self, section: usize) -> usize {
            self.items.items_count(section)
        }

        fn item(&self, ix: IndexPath) -> Option<&&'static str> {
            self.items.item(ix)
        }

        fn position<V>(&self, value: &V) -> Option<IndexPath>
        where
            &'static str: SearchableListItem<Value = V>,
            V: PartialEq,
        {
            self.items.position(value)
        }

        fn on_will_change(
            &mut self,
            selection: &mut Vec<(IndexPath, &'static str)>,
            _: &[SearchableListChange],
        ) {
            *selection = vec![(IndexPath::new(2), "C++")];
        }

        fn on_confirm(&mut self, selection: &[(IndexPath, &'static str)]) {
            assert_eq!(selection[0].1, "C++");
            self.confirmations.set(self.confirmations.get() + 1);
        }
    }

    #[gpui::test]
    fn single_select_confirms_delegate_replacement(cx: &mut TestAppContext) {
        use crate::list::ListDelegate as _;
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        for through_list in [false, true] {
            let confirmations = Rc::new(Cell::new(0));
            let state = cx.update(|window, cx| {
                cx.new(|cx| {
                    ComboboxState::new(
                        RedirectDelegate {
                            items: SearchableVec::new(vec!["Rust", "Go", "C++"]),
                            confirmations: confirmations.clone(),
                        },
                        vec![IndexPath::new(0)],
                        window,
                        cx,
                    )
                })
            });
            let events = Rc::new(Cell::new(0));
            let event_count = events.clone();
            let _subscription = cx.update(|_, cx| {
                cx.subscribe(&state, move |_, _: &ComboboxEvent<RedirectDelegate>, _| {
                    event_count.set(event_count.get() + 1);
                })
            });
            cx.update(|window, cx| {
                state.update(cx, |state, cx| {
                    state.set_open(true, cx);
                    if through_list {
                        state.state.list.update(cx, |list, cx| {
                            list.set_selected_index(Some(IndexPath::new(1)), window, cx);
                            list.delegate_mut().confirm(false, window, cx);
                        });
                    } else {
                        state.handle_item_select(IndexPath::new(1), window, cx);
                    }
                });
            });
            cx.run_until_parked();
            cx.update(|_, cx| {
                assert_eq!(state.read(cx).selected_values(), vec!["C++"]);
                assert!(!state.read(cx).state.open);
                assert_eq!(confirmations.get(), 1);
                assert_eq!(events.get(), 2, "one Change and one Confirm");
            });
        }
    }

    fn left_press(position: Point<Pixels>) -> MouseDownEvent {
        MouseDownEvent {
            button: MouseButton::Left,
            position,
            modifiers: Modifiers::default(),
            click_count: 1,
            first_mouse: false,
        }
    }

    #[gpui::test]
    fn test_combo_box_dismiss_ignores_press_on_trigger(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        let state = cx.update(|window, cx| {
            let items = SearchableVec::new(vec!["React", "Vue", "Angular"]);
            cx.new(|cx| ComboboxState::new(items, vec![], window, cx).multiple(true))
        });
        let collector = cx.update(|_, cx| cx.new(|cx| TestComboboxEventCollector::new(&state, cx)));

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.state.bounds = Bounds {
                    origin: point(px(10.), px(10.)),
                    size: size(px(200.), px(32.)),
                };
                state.set_open(true, cx);
                state.dismiss(&left_press(point(px(20.), px(20.))), window, cx);
            });
        });

        cx.update(|_, cx| {
            assert!(
                state.read(cx).state.open,
                "a press on the trigger must reach nested controls, so the menu stays open \
                 and `toggle_menu` closes it on release instead",
            );
            assert_eq!(collector.read(cx).event_count.get(), 0);
        });

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.dismiss(&left_press(point(px(20.), px(200.))), window, cx);
            });
        });

        cx.update(|_, cx| {
            assert!(!state.read(cx).state.open);
            assert_eq!(
                collector.read(cx).event_count.get(),
                1,
                "dismissing from outside the trigger emits Confirm",
            );
        });
    }

    // Suppress unused import warning for SearchableListState in test module.
    #[allow(unused)]
    fn _uses_state<D: SearchableListDelegate + 'static>(_: &SearchableListState<D>)
    where
        <D::Item as SearchableListItem>::Value: PartialEq + Clone,
    {
    }
    fn assert_filtered_row_replacement(cx: &mut TestAppContext, through_list: bool) {
        use crate::list::ListDelegate as _;

        cx.update(crate::init);
        let cx = cx.add_empty_window();
        let state = cx.update(|window, cx| {
            cx.new(|cx| {
                ComboboxState::new(
                    SearchableVec::new(vec!["React", "Vue"]),
                    vec![IndexPath::new(0)],
                    window,
                    cx,
                )
                .searchable(true)
            })
        });
        let collector = cx.update(|_, cx| cx.new(|cx| TestComboboxEventCollector::new(&state, cx)));

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_open(true, cx);
                state.state.list.update(cx, |list, cx| {
                    let _ = list
                        .delegate_mut()
                        .delegate
                        .perform_search("Vue", window, cx);
                    list.set_selected_index(Some(IndexPath::new(0)), window, cx);
                });
                assert_eq!(state.selected_values(), vec!["React"]);
                assert_eq!(
                    state
                        .state
                        .list
                        .read(cx)
                        .delegate()
                        .delegate
                        .item(IndexPath::new(0)),
                    Some(&"Vue"),
                );
                if through_list {
                    state.state.list.update(cx, |list, cx| {
                        list.delegate_mut().confirm(false, window, cx);
                    });
                } else {
                    state.handle_item_select(IndexPath::new(0), window, cx);
                }
            });
        });

        cx.update(|_, cx| {
            assert_eq!(state.read(cx).selected_values(), vec!["Vue"]);
            assert!(
                !state.read(cx).state.open,
                "single selection must close the popover"
            );
            assert_eq!(collector.read(cx).event_count.get(), 2);
        });
    }

    #[gpui::test]
    fn test_filtered_row_replacement_direct(cx: &mut TestAppContext) {
        assert_filtered_row_replacement(cx, false);
    }

    #[gpui::test]
    fn test_filtered_row_replacement_list_confirm(cx: &mut TestAppContext) {
        assert_filtered_row_replacement(cx, true);
    }

    #[gpui::test]
    fn current_item_acceptance_closes_without_change(cx: &mut TestAppContext) {
        use crate::list::ListDelegate as _;
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        for through_list in [false, true] {
            let state = cx.update(|window, cx| {
                cx.new(|cx| {
                    ComboboxState::new(
                        SearchableVec::new(vec!["React", "Vue"]),
                        vec![IndexPath::new(0)],
                        window,
                        cx,
                    )
                })
            });
            let collector =
                cx.update(|_, cx| cx.new(|cx| TestComboboxEventCollector::new(&state, cx)));
            cx.update(|window, cx| {
                state.update(cx, |state, cx| {
                    state.set_open(true, cx);
                    if through_list {
                        state.state.list.update(cx, |list, cx| {
                            list.delegate_mut().confirm(false, window, cx)
                        });
                    } else {
                        state.handle_item_select(IndexPath::new(0), window, cx);
                    }
                })
            });
            cx.run_until_parked();
            cx.update(|_, cx| {
                assert!(!state.read(cx).state.open);
                assert_eq!(state.read(cx).selected_values(), vec!["React"]);
                assert_eq!(
                    collector.read(cx).event_count.get(),
                    1,
                    "only Confirm, no Change"
                );
            });
        }
    }

    /// A page holding a combobox under retained views.
    #[cfg(feature = "gpui-fast")]
    mod retained {
        use std::{cell::Cell, rc::Rc};

        use gpui::{
            AppContext as _, Context, Entity, IntoElement, ParentElement as _, Render, Styled as _,
            TestAppContext, Window, div, px,
        };

        use crate::{
            combobox::{Combobox, ComboboxState},
            searchable_list::SearchableVec,
        };

        /// A page that shows a combobox and what it selected, counting its
        /// renders.
        struct Page {
            state: Entity<ComboboxState<SearchableVec<&'static str>>>,
            renders: Rc<Cell<usize>>,
        }

        impl Render for Page {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                self.renders.set(self.renders.get() + 1);
                let selected = self.state.read(cx).selected_values();
                div()
                    .w(px(240.))
                    .child(Combobox::new(&self.state))
                    .child(format!("{selected:?}"))
            }
        }

        /// Drawing a combobox again changes nothing in it: the page around
        /// it, which reads its selection, is not built again for it.
        #[gpui::test]
        fn drawing_a_combobox_again_leaves_the_page_around_it_retained(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let renders = Rc::new(Cell::new(0));
            let (_, cx) = cx.add_window_view({
                let renders = renders.clone();
                move |window, cx| {
                    let items = SearchableVec::new(vec!["Rust", "Go", "C++"]);
                    Page {
                        state: cx.new(|cx| ComboboxState::new(items, vec![], window, cx)),
                        renders,
                    }
                }
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let rendered = renders.get();
            for _ in 0..3 {
                cx.update(|window, cx| window.draw(cx).clear(cx));
            }
            assert_eq!(renders.get(), rendered, "the page was built again");
        }
    }
}
