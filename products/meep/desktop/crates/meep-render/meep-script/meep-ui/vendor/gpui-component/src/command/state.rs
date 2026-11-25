use gpui_base::TestSupportExt as _;
use std::rc::Rc;

use gpui::{
    AbsoluteLength, AnyElement, App, AppContext as _, AvailableSpace, Context, Entity, FocusHandle,
    Focusable, FontFallbacks, FontFeatures, FontStyle, FontWeight, InteractiveElement, IntoElement,
    KeyBinding, Keystroke, ListSizingBehavior, ParentElement, Pixels, Render, Role, ScrollStrategy,
    SharedString, Size, StatefulInteractiveElement as _, StyleRefinement, Styled, Subscription,
    TextOverflow, WhiteSpace, Window, div, prelude::FluentBuilder as _, px, size,
};
use rust_i18n::t;

use crate::{
    ActiveTheme as _, ElementExt as _, Icon, IconName, IndexPath, StyledExt as _,
    VirtualListScrollHandle,
    actions::{Cancel, Confirm, SelectDown, SelectUp},
    command::{
        command::CommandOptions,
        item::{CommandEntry, CommandItem},
    },
    h_flex,
    input::{Input, InputEvent, InputState},
    kbd::Kbd,
    scroll::Scrollbar,
    v_flex, v_virtual_list,
};

pub(crate) const CONTEXT: &str = "Command";

/// The row a separator occupies: a one-pixel rule with a little air on
/// either side. Fixed, so that only the item and heading rows need measuring.
const SEPARATOR_ROW_HEIGHT: f32 = 9.;

pub(crate) type OnQuery = dyn Fn(&str, &mut Window, &mut App);
pub(crate) type OnIndex = dyn Fn(IndexPath, &mut Window, &mut App);
pub(crate) type OnCancel = dyn Fn(&mut Window, &mut App);

pub(crate) struct CommandModel {
    pub(crate) entries: Vec<CommandEntry>,
    pub(crate) searchable: bool,
    pub(crate) filterable: bool,
    pub(crate) on_query: Option<Rc<OnQuery>>,
    pub(crate) on_select: Option<Rc<OnIndex>>,
    pub(crate) on_confirm: Option<Rc<OnIndex>>,
    pub(crate) on_cancel: Option<Rc<OnCancel>>,
}

impl Default for CommandModel {
    fn default() -> Self {
        Self {
            entries: Vec::new(),
            searchable: true,
            filterable: true,
            on_query: None,
            on_select: None,
            on_confirm: None,
            on_cancel: None,
        }
    }
}

pub(crate) fn init(cx: &mut App) {
    let context: Option<&str> = Some(CONTEXT);
    cx.bind_keys([
        KeyBinding::new("escape", Cancel, context),
        KeyBinding::new("enter", Confirm { secondary: false }, context),
        KeyBinding::new("up", SelectUp, context),
        KeyBinding::new("down", SelectDown, context),
    ]);
}

/// One rendered line of the list.
///
/// Groups are flattened into headings and items so the list is a single
/// sequence of rows, which is what the virtual list scrolls over.
#[derive(Clone, PartialEq)]
enum CommandRow {
    Heading(SharedString),
    /// Holds the index into [`CommandState::matched`].
    Item(usize),
    Separator,
}

#[derive(Clone, PartialEq)]
struct TextShapeKey {
    font_family: SharedString,
    font_features: FontFeatures,
    font_fallbacks: Option<FontFallbacks>,
    font_size: AbsoluteLength,
    font_weight: FontWeight,
    font_style: FontStyle,
    white_space: WhiteSpace,
    text_overflow: Option<TextOverflow>,
    line_clamp: Option<usize>,
}

#[derive(Clone, PartialEq)]
struct ListMeasurementKey {
    content_width: Pixels,
    rem_size: Pixels,
    line_height: Pixels,
    text_shape: TextShapeKey,
}

/// An item that survived the current query, and where it landed.
#[derive(Clone)]
struct MatchedItem {
    entry_ix: usize,
    item_ix: usize,
    index_path: IndexPath,
    row_ix: usize,
    disabled: bool,
}

/// The interaction state of a [`crate::command::Command`] palette: its query,
/// focus, scrolling, and highlighted command.
pub struct CommandState {
    focus_handle: FocusHandle,
    query_input: Entity<InputState>,
    scroll_handle: VirtualListScrollHandle,
    model: CommandModel,
    rows: Vec<CommandRow>,
    row_sizes: Rc<Vec<Size<Pixels>>>,
    list_measurement_key: Option<ListMeasurementKey>,
    needs_measure: bool,
    /// The keybinding hint each matched item showed when the rows were last
    /// measured. Hints are looked up on every render, so a keymap change can
    /// resize a row while the model stays the same.
    measured_bindings: Vec<Option<Keystroke>>,
    matched: Vec<MatchedItem>,
    selected_index: Option<usize>,
    preserve_no_selection: bool,
    loading: bool,
    pending_scroll: Option<usize>,
    /// The placeholder last written to the query input, so that `render` only
    /// writes when it changed — `set_placeholder` notifies, and an
    /// unconditional notify from `render` would redraw every frame.
    applied_placeholder: SharedString,
    applied_query: SharedString,
    pub(crate) options: CommandOptions,
    _subscriptions: Vec<Subscription>,
}

impl CommandState {
    /// Create an empty palette.
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let query_input = cx.new(|cx| InputState::new(window, cx));

        let _subscriptions =
            vec![cx.subscribe_in(&query_input, window, Self::on_query_input_event)];

        Self {
            focus_handle: cx.focus_handle(),
            query_input,
            scroll_handle: VirtualListScrollHandle::new(),
            model: CommandModel::default(),
            rows: Vec::new(),
            row_sizes: Rc::new(Vec::new()),
            list_measurement_key: None,
            needs_measure: true,
            measured_bindings: Vec::new(),
            matched: Vec::new(),
            selected_index: None,
            preserve_no_selection: false,
            loading: false,
            pending_scroll: None,
            applied_placeholder: SharedString::default(),
            applied_query: SharedString::default(),
            options: CommandOptions::default(),
            _subscriptions,
        }
    }

    /// Apply the presentation of the latest [`crate::command::Command`] render.
    pub(crate) fn set_options(&mut self, options: CommandOptions) {
        if self.options.style.text != options.style.text {
            self.needs_measure = true;
        }
        self.options = options;
    }

    pub(crate) fn install_model(&mut self, model: CommandModel, cx: &mut Context<Self>) {
        let selected_index_path = self.selected_index();
        // The model reinstalls on every host re-render, usually unchanged.
        // Keep the rows and their measured sizes then: measuring lays out
        // every row, not only the visible ones.
        let same_layout = self.model.searchable == model.searchable
            && self.model.filterable == model.filterable
            && self.model.entries.len() == model.entries.len()
            && self
                .model
                .entries
                .iter()
                .zip(&model.entries)
                .all(|(entry, other)| entry.same_layout(other));
        self.model = model;
        if !same_layout {
            self.update_matches(cx);
        }

        let preserved_selection = selected_index_path.and_then(|selected_index_path| {
            self.matched
                .iter()
                .enumerate()
                .find_map(|(matched_ix, matched)| {
                    (!matched.disabled && matched.index_path == selected_index_path)
                        .then_some(matched_ix)
                })
        });

        if let Some(matched_ix) = preserved_selection {
            // Preserving the selection is not a navigation: the model
            // reinstalls on every host re-render, so scrolling here would
            // move the list one frame after a hover selection.
            self.selected_index = Some(matched_ix);
            self.preserve_no_selection = false;
        } else if self.preserve_no_selection {
            self.selected_index = None;
            self.pending_scroll = None;
        } else {
            self.reset_selection();
        }
    }

    /// The current search query.
    pub fn query(&self, cx: &App) -> SharedString {
        self.query_input.read(cx).value()
    }

    /// Replace the search query, as if it had been typed.
    ///
    /// The input suppresses its own change event for a programmatic write, so
    /// the re-filter and query callback happen here instead.
    pub fn set_query(
        &mut self,
        query: impl Into<SharedString>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let query = query.into();
        if self.query(cx) == query {
            return;
        }

        self.query_input
            .update(cx, |input, cx| input.set_value(query, window, cx));
        self.on_query_changed(window, cx);
    }

    /// The highlighted item's path in the model installed by the latest
    /// [`crate::command::Command`] render, before local filtering.
    ///
    /// Ungrouped items occupy section 0 and use their input position as the
    /// row. Explicit groups use their group and item positions; when a model
    /// mixes both forms, the implicit ungrouped section comes first.
    pub fn selected_index(&self) -> Option<IndexPath> {
        self.selected_index
            .and_then(|selected_index| self.matched.get(selected_index))
            .filter(|matched| !matched.disabled)
            .map(|matched| matched.index_path)
    }

    /// Highlight an item by its original, unfiltered model path, or clear the
    /// highlight with `None`.
    ///
    /// A path that is currently filtered out or disabled clears the
    /// highlight. A visible selection is scrolled into view.
    pub fn set_selected_index(
        &mut self,
        index: Option<IndexPath>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let matched_ix = index.and_then(|index| {
            self.matched
                .iter()
                .position(|matched| matched.index_path == index && !matched.disabled)
        });

        let preserve_no_selection = matched_ix.is_none();
        if self.selected_index == matched_ix {
            self.preserve_no_selection = preserve_no_selection;
            return;
        }

        let previous_index = self.selected_index();
        self.selected_index = matched_ix;
        self.preserve_no_selection = preserve_no_selection;
        self.pending_scroll = matched_ix
            .and_then(|matched_ix| self.matched.get(matched_ix))
            .map(|matched| matched.row_ix);

        if let Some((on_select, index)) = self.on_select_if_changed(previous_index) {
            window.defer(cx, move |window, cx| on_select(index, window, cx));
        }

        cx.notify();
    }

    /// The number of items matching the current query.
    pub fn matched_count(&self) -> usize {
        self.matched.len()
    }

    /// Move focus to the palette's active control.
    pub fn focus(&self, window: &mut Window, cx: &mut App) {
        if self.model.searchable {
            self.query_input.focus_handle(cx).focus(window, cx);
        } else {
            self.focus_handle.focus(window, cx);
        }
    }

    /// Show or hide the search field's spinner, and suppress the empty message
    /// while it spins.
    ///
    /// Turn it on while an `on_query` callback is being answered.
    pub fn set_loading(&mut self, loading: bool, window: &mut Window, cx: &mut Context<Self>) {
        self.loading = loading;
        self.query_input
            .update(cx, |input, cx| input.set_loading(loading, window, cx));
        cx.notify();
    }

    /// Whether the search field is showing its spinner.
    pub fn is_loading(&self) -> bool {
        self.loading
    }

    // MARK: Matching

    fn item_matches(&self, item: &CommandItem, query: &str) -> bool {
        if !self.model.searchable || !self.model.filterable || query.is_empty() {
            true
        } else {
            item.matches(query)
        }
    }

    fn item_at(&self, matched_ix: usize) -> Option<&CommandItem> {
        let matched = self.matched.get(matched_ix)?;

        match self.model.entries.get(matched.entry_ix)? {
            CommandEntry::Item(item) => Some(item),
            CommandEntry::Group(group) => group.items.get(matched.item_ix),
            CommandEntry::Separator => None,
        }
    }

    /// Recompute the visible rows and the matching items for the current query.
    ///
    fn update_matches(&mut self, cx: &App) {
        let query = self.query(cx);
        let query = query.trim();

        let mut rows: Vec<CommandRow> = Vec::new();
        let mut matched: Vec<MatchedItem> = Vec::new();
        let has_ungrouped_items = self
            .model
            .entries
            .iter()
            .any(|entry| matches!(entry, CommandEntry::Item(_)));
        let mut ungrouped_item_ix = 0;
        let mut group_ix = 0;
        // A separator is only drawn once something follows it, which drops the
        // leading, trailing and doubled separators a filtered list leaves behind.
        let mut pending_separator = false;

        for (entry_ix, entry) in self.model.entries.iter().enumerate() {
            match entry {
                CommandEntry::Separator => pending_separator = !rows.is_empty(),
                CommandEntry::Item(item) => {
                    let item_ix = ungrouped_item_ix;
                    ungrouped_item_ix += 1;
                    if !self.item_matches(item, query) {
                        continue;
                    }

                    if pending_separator {
                        rows.push(CommandRow::Separator);
                        pending_separator = false;
                    }

                    let index_path = IndexPath::new(item_ix).section(0);
                    matched.push(MatchedItem {
                        entry_ix,
                        item_ix: 0,
                        index_path,
                        row_ix: rows.len(),
                        disabled: item.is_disabled(),
                    });
                    rows.push(CommandRow::Item(matched.len() - 1));
                }
                CommandEntry::Group(group) => {
                    let section_ix = group_ix + usize::from(has_ungrouped_items);
                    group_ix += 1;
                    let visible = group
                        .items
                        .iter()
                        .enumerate()
                        .filter(|(_, item)| self.item_matches(item, query))
                        .map(|(item_ix, item)| (item_ix, item.is_disabled()))
                        .collect::<Vec<_>>();

                    if visible.is_empty() {
                        continue;
                    }

                    if pending_separator {
                        rows.push(CommandRow::Separator);
                        pending_separator = false;
                    }

                    if let Some(heading) = group.heading() {
                        rows.push(CommandRow::Heading(heading.clone()));
                    }

                    for (item_ix, disabled) in visible {
                        let index_path = IndexPath::new(item_ix).section(section_ix);
                        matched.push(MatchedItem {
                            entry_ix,
                            item_ix,
                            index_path,
                            row_ix: rows.len(),
                            disabled,
                        });
                        rows.push(CommandRow::Item(matched.len() - 1));
                    }
                }
            }
        }

        self.rows = rows;
        self.matched = matched;
        self.needs_measure = true;
        self.selected_index = self.selected_index.and_then(|selected_index| {
            (selected_index < self.matched.len()).then_some(selected_index)
        });
    }

    /// Move the highlight to the first item that can be confirmed.
    fn reset_selection(&mut self) {
        self.selected_index = self.matched.iter().position(|matched| !matched.disabled);
        self.preserve_no_selection = false;
        self.pending_scroll = self
            .selected_index
            .and_then(|selected_index| self.matched.get(selected_index))
            .map(|matched| matched.row_ix)
            .or(Some(0));
    }

    fn on_query_input_event(
        &mut self,
        _: &Entity<InputState>,
        event: &InputEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !matches!(event, InputEvent::Change) {
            return;
        }

        self.on_query_changed(window, cx);
    }

    /// Re-filter for the query that is now in the field, and report it.
    fn on_query_changed(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let query = self.query(cx);
        if query == self.applied_query {
            return;
        }

        let previous_selection = self.selected_index();
        self.applied_query = query.clone();
        self.update_matches(cx);
        self.reset_selection();
        let selection_callback = self.on_select_if_changed(previous_selection);
        let query_callback = self
            .model
            .searchable
            .then(|| self.model.on_query.clone())
            .flatten();

        if selection_callback.is_some() || query_callback.is_some() {
            window.defer(cx, move |window, cx| {
                if let Some((on_select, index)) = selection_callback {
                    on_select(index, window, cx);
                }
                if let Some(on_query) = query_callback {
                    on_query(query.as_ref(), window, cx);
                }
            });
        }

        cx.notify();
    }

    fn set_list_measurement_key(
        &mut self,
        measurement_key: ListMeasurementKey,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.list_measurement_key.as_ref() == Some(&measurement_key) {
            return;
        }

        self.list_measurement_key = Some(measurement_key);
        self.measure_on_next_frame(window, cx);
    }

    /// Measure the rows again on the next frame. Called while the list is
    /// drawn, where a plain notify schedules no new frame.
    fn measure_on_next_frame(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.needs_measure = true;
        let entity_id = cx.entity_id();
        window.on_next_frame(move |_, cx| cx.notify(entity_id));
    }

    // MARK: Actions

    fn on_select_if_changed(
        &self,
        previous_index: Option<IndexPath>,
    ) -> Option<(Rc<OnIndex>, IndexPath)> {
        let index = self.selected_index();
        if index == previous_index {
            return None;
        }

        self.model.on_select.clone().zip(index)
    }

    /// Highlight an item without scrolling it into view. Hover goes through
    /// here, and revealing a half-clipped edge row would slide the next row
    /// under the resting cursor, hover-selecting and scrolling in a loop.
    fn select(&mut self, matched_ix: usize, window: &mut Window, cx: &mut Context<Self>) {
        if self.selected_index == Some(matched_ix) {
            return;
        }

        let previous_index = self.selected_index();
        self.selected_index = Some(matched_ix);
        self.preserve_no_selection = false;

        if let Some((on_select, index)) = self.on_select_if_changed(previous_index) {
            window.defer(cx, move |window, cx| on_select(index, window, cx));
        }

        cx.notify();
    }

    /// Move the highlight by `step` items, wrapping around and skipping the
    /// disabled ones.
    fn select_by(&mut self, step: isize, window: &mut Window, cx: &mut Context<Self>) {
        let len = self.matched.len();
        if len == 0 {
            return;
        }

        let mut next = self
            .selected_index
            .unwrap_or_else(|| if step >= 0 { len.saturating_sub(1) } else { 0 });
        let mut enabled = None;
        for _ in 0..len {
            next = (next as isize + step).rem_euclid(len as isize) as usize;
            if !self.matched[next].disabled {
                enabled = Some(next);
                break;
            }
        }

        if let Some(next) = enabled
            && self.selected_index != Some(next)
        {
            self.pending_scroll = self.matched.get(next).map(|matched| matched.row_ix);
            self.select(next, window, cx);
        }
    }

    fn on_action_select_up(&mut self, _: &SelectUp, window: &mut Window, cx: &mut Context<Self>) {
        self.select_by(-1, window, cx);
    }

    fn on_action_select_down(
        &mut self,
        _: &SelectDown,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.select_by(1, window, cx);
    }

    fn on_action_confirm(&mut self, _: &Confirm, window: &mut Window, cx: &mut Context<Self>) {
        if let Some(selected_index) = self.selected_index {
            self.confirm(selected_index, window, cx);
        }
    }

    /// Escape clears a non-empty query first, and only then leaves the palette
    /// — the dialog that hosts it closes on the second press.
    fn on_action_cancel(&mut self, _: &Cancel, window: &mut Window, cx: &mut Context<Self>) {
        if self.model.searchable && !self.query(cx).is_empty() {
            self.set_query("", window, cx);
            return;
        }

        // Cancel is the one synchronous callback: propagation must continue in
        // this dispatch so a hosting Dialog observes it once and owns the pop.
        if let Some(on_cancel) = self.model.on_cancel.clone() {
            on_cancel(window, cx);
        }

        cx.propagate();
    }

    fn confirm(&mut self, matched_ix: usize, window: &mut Window, cx: &mut Context<Self>) {
        let Some(item) = self.item_at(matched_ix) else {
            return;
        };
        if item.is_disabled() {
            return;
        }

        let index_path = self.matched[matched_ix].index_path;
        let action = item.action.as_ref().map(|action| action.boxed_clone());
        let on_confirm = self.model.on_confirm.clone();

        if let Some(action) = action {
            window.dispatch_action(action, cx);
        }
        if let Some(on_confirm) = on_confirm {
            window.defer(cx, move |window, cx| {
                on_confirm(index_path, window, cx);
            });
        }
    }

    // MARK: Row sizing

    /// Measure each row before passing the sizes to the virtual list. Custom
    /// item elements can have independent intrinsic heights.
    fn measure_rows(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let available = size(
            self.list_measurement_key
                .as_ref()
                .map_or(AvailableSpace::MinContent, |key| {
                    AvailableSpace::Definite(key.content_width)
                }),
            AvailableSpace::MinContent,
        );
        let mut text_style = StyleRefinement::default();
        text_style.text = self.options.style.text.clone();
        let mut bindings = vec![None; self.matched.len()];

        let row_sizes = self
            .rows
            .iter()
            .enumerate()
            .map(|(row_ix, row)| {
                let row = match row {
                    CommandRow::Separator => return size(px(0.), px(SEPARATOR_ROW_HEIGHT)),
                    CommandRow::Heading(_) => self.render_row(row_ix, window, cx),
                    CommandRow::Item(matched_ix) => {
                        let binding = self.item_binding(*matched_ix, window, cx);
                        bindings[*matched_ix] = binding.as_ref().map(|kbd| kbd.keystroke().clone());
                        self.render_item_with_binding(*matched_ix, binding, window, cx)
                    }
                };
                let row_size = div()
                    .refine_style(&text_style)
                    .child(row)
                    .into_any_element()
                    .layout_as_root(available, window, cx);
                size(px(0.), row_size.height)
            })
            .collect::<Vec<_>>();

        self.row_sizes = Rc::new(row_sizes);
        self.measured_bindings = bindings;
    }

    // MARK: Rendering

    fn sync_placeholder(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let placeholder = self
            .options
            .placeholder
            .as_ref()
            .cloned()
            .unwrap_or_else(|| t!("Command.placeholder").to_string().into());

        if self.applied_placeholder == placeholder {
            return;
        }

        self.applied_placeholder = placeholder.clone();
        self.query_input.update(cx, |input, cx| {
            input.set_placeholder(placeholder, window, cx)
        });
    }

    /// Row corner radius, concentric with the frame: the list's `p_1` (plus the
    /// border when bordered) sits between a row and the frame's corner. A
    /// borderless command without its own radius keeps the theme radius, since
    /// its frame belongs to the host.
    fn item_radius(&self, window: &Window, cx: &App) -> Pixels {
        let theme = cx.theme();
        let rem_size = window.rem_size();
        let own_radius = self.options.style.corner_radii.top_left;
        let (outer, border) = match (self.options.bordered, own_radius) {
            (true, radius) => (
                radius.map_or(theme.radius_lg, |r| r.to_pixels(rem_size)),
                px(1.),
            ),
            (false, Some(radius)) => (radius.to_pixels(rem_size), px(0.)),
            (false, None) => return theme.radius,
        };
        (outer - rem_size * 0.25 - border).max(px(0.))
    }

    /// The frame every item row shares, so that the measured height matches the
    /// rendered one.
    fn item_row(&self, selected: bool, window: &Window, cx: &App) -> gpui::Div {
        div()
            .flex()
            .flex_row()
            .items_center()
            .w_full()
            .gap_2()
            .px_2()
            .py_1p5()
            .text_sm()
            .rounded(self.item_radius(window, cx))
            .when(selected, |this| {
                this.bg(cx.theme().accent)
                    .text_color(cx.theme().accent_foreground)
            })
    }

    fn heading_row(&self, heading: SharedString, cx: &App) -> gpui::Div {
        div()
            .w_full()
            .px_2()
            .py_1p5()
            .text_xs()
            .font_medium()
            .text_color(cx.theme().muted_foreground)
            .child(heading)
    }

    fn render_row(&self, row_ix: usize, window: &mut Window, cx: &mut Context<Self>) -> AnyElement {
        match self.rows.get(row_ix) {
            None => div().into_any_element(),
            Some(CommandRow::Separator) => div()
                .w_full()
                .py(px(4.))
                .child(div().h(px(1.)).w_full().bg(cx.theme().border))
                .into_any_element(),
            Some(CommandRow::Heading(heading)) => {
                self.heading_row(heading.clone(), cx).into_any_element()
            }
            Some(CommandRow::Item(matched_ix)) => self.render_item(*matched_ix, window, cx),
        }
    }

    /// Render a row the virtual list shows. When an item's keybinding hint no
    /// longer matches the one it was measured with, measure the rows again.
    fn render_visible_row(
        &mut self,
        row_ix: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let Some(&CommandRow::Item(matched_ix)) = self.rows.get(row_ix) else {
            return self.render_row(row_ix, window, cx);
        };

        let binding = self.item_binding(matched_ix, window, cx);
        let measured = self
            .measured_bindings
            .get(matched_ix)
            .and_then(Option::as_ref);
        if !self.needs_measure && measured != binding.as_ref().map(Kbd::keystroke) {
            self.measure_on_next_frame(window, cx);
        }

        self.render_item_with_binding(matched_ix, binding, window, cx)
    }

    /// The keybinding hint an item shows in its trailing slot. A custom child
    /// owns its complete presentation, so it has none.
    fn item_binding(&self, matched_ix: usize, window: &Window, cx: &App) -> Option<Kbd> {
        let item = self.item_at(matched_ix)?;
        if item.content.is_some() {
            return None;
        }

        let action = item.action.as_ref()?;
        Kbd::binding_for_action_in(action.as_ref(), &self.focus_handle(cx), window)
            .or_else(|| Kbd::binding_for_action(action.as_ref(), None, window))
    }

    fn render_item(
        &self,
        matched_ix: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let binding = self.item_binding(matched_ix, window, cx);
        self.render_item_with_binding(matched_ix, binding, window, cx)
    }

    fn render_item_with_binding(
        &self,
        matched_ix: usize,
        binding: Option<Kbd>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let Some(item) = self.item_at(matched_ix) else {
            return div().into_any_element();
        };

        let disabled = item.is_disabled();
        let selected = self.selected_index == Some(matched_ix) && !disabled;
        let muted_foreground = cx.theme().muted_foreground;
        let icon_color = if selected {
            cx.theme().accent_foreground
        } else {
            muted_foreground
        };
        let content = match &item.content {
            Some(render) => render(window, cx),
            None => h_flex()
                .flex_1()
                .gap_2()
                .items_center()
                .when_some(item.icon.clone(), |this, icon| {
                    this.child(icon.size_4().text_color(icon_color))
                })
                .when_some(item.label_text().cloned(), |this, label| this.child(label))
                .into_any_element(),
        };

        self.item_row(selected, window, cx)
            .id(self.matched[matched_ix].index_path)
            .test_support()
            .role(Role::ListBoxOption)
            // The row's text is drawn by a child that isn't an accessibility
            // node, so the row names itself.
            .when_some(item.label_text().cloned(), |this, label| {
                this.aria_label(label)
            })
            .aria_selected(selected)
            .when(disabled, |this| this.text_color(muted_foreground))
            .when(!disabled, |this| {
                this.cursor_default()
                    .on_hover(cx.listener(move |this, hovered: &bool, window, cx| {
                        if *hovered {
                            this.select(matched_ix, window, cx);
                        }
                    }))
                    .on_click(cx.listener(move |this, _, window, cx| {
                        this.confirm(matched_ix, window, cx);
                    }))
            })
            .child(content)
            .map(|this| match binding {
                Some(binding) => this.child(binding.ml_auto()),
                // The binding owns the trailing slot, so only an item without
                // one can show its check there.
                None => this.when(item.checked, |this| {
                    this.child(crate::Sizable::xsmall(Icon::new(IconName::Check).ml_auto()))
                }),
            })
            .into_any_element()
    }

    fn render_empty(&self, window: &mut Window, cx: &mut App) -> AnyElement {
        if let Some(empty) = self.options.empty.as_ref() {
            return empty(self, window, cx);
        }

        let message: SharedString = t!("Command.empty").to_string().into();

        div()
            .py_6()
            .w_full()
            .text_center()
            .text_sm()
            .text_color(cx.theme().muted_foreground)
            .child(message)
            .into_any_element()
    }
}

impl Focusable for CommandState {
    fn focus_handle(&self, cx: &App) -> FocusHandle {
        if self.model.searchable {
            self.query_input.focus_handle(cx)
        } else {
            self.focus_handle.clone()
        }
    }
}

impl Render for CommandState {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        self.sync_placeholder(window, cx);

        if self.needs_measure {
            self.needs_measure = false;
            self.measure_rows(window, cx);
        }

        if let Some(row_ix) = self.pending_scroll.take() {
            self.scroll_handle
                .scroll_to_item(row_ix, ScrollStrategy::Nearest);
        }

        let rows_count = self.rows.len();
        let row_sizes = self.row_sizes.clone();
        let command_state = cx.entity();

        v_flex()
            .id("command")
            .test_support()
            .key_context(CONTEXT)
            .track_focus(&self.focus_handle)
            .on_action(cx.listener(Self::on_action_select_up))
            .on_action(cx.listener(Self::on_action_select_down))
            .on_action(cx.listener(Self::on_action_confirm))
            .on_action(cx.listener(Self::on_action_cancel))
            .w_full()
            .overflow_hidden()
            .bg(cx.theme().popover)
            .text_color(cx.theme().popover_foreground)
            .when(self.options.bordered, |this| {
                this.rounded(cx.theme().radius_lg)
                    .border_1()
                    .border_color(cx.theme().border)
            })
            .refine_style(&self.options.style)
            .when_some(self.options.header.as_ref(), |this, header| {
                this.child(header(self, window, cx))
            })
            .when(self.model.searchable, |this| {
                this.child(
                    div()
                        .flex_none()
                        .px_3()
                        .border_b_1()
                        .border_color(cx.theme().border)
                        .child(
                            Input::new(&self.query_input)
                                .prefix(
                                    Icon::new(IconName::Search)
                                        .text_color(cx.theme().muted_foreground),
                                )
                                .appearance(false)
                                .p_0(),
                        ),
                )
            })
            .child(
                v_flex()
                    .id("command-list-container")
                    .role(Role::ListBox)
                    .relative()
                    .flex_1()
                    // The rows carry their inset on the virtual list itself so
                    // that a mid-scroll clip edge sits flush against the
                    // surrounding dividers; only the empty slot needs the
                    // container padding, and only while it is shown, so a
                    // loading list leaves no blank strip under the query.
                    .when(rows_count == 0 && !self.loading, |this| this.p_1())
                    .on_prepaint({
                        let measure_state = command_state.clone();
                        move |bounds, window, cx| {
                            measure_state.update(cx, |state, cx| {
                                // The list's `p_1` is one quarter rem on each
                                // side. Its rem-dependent padding and inherited
                                // layout-relevant text style participate in
                                // the row-size cache key.
                                let text_style = window.text_style();
                                state.set_list_measurement_key(
                                    ListMeasurementKey {
                                        content_width: (bounds.size.width
                                            - window.rem_size() * 0.5)
                                            .max(px(0.)),
                                        rem_size: window.rem_size(),
                                        line_height: window.line_height(),
                                        text_shape: TextShapeKey {
                                            font_family: text_style.font_family,
                                            font_features: text_style.font_features,
                                            font_fallbacks: text_style.font_fallbacks,
                                            font_size: text_style.font_size,
                                            font_weight: text_style.font_weight,
                                            font_style: text_style.font_style,
                                            white_space: text_style.white_space,
                                            text_overflow: text_style.text_overflow,
                                            line_clamp: text_style.line_clamp,
                                        },
                                    },
                                    window,
                                    cx,
                                )
                            })
                        }
                    })
                    .max_h(self.options.max_h)
                    .overflow_hidden()
                    // While a search is in flight the list is empty because the
                    // answer has not arrived, which is not the same as no match.
                    .when(rows_count == 0 && !self.loading, |this| {
                        this.child(self.render_empty(window, cx))
                    })
                    .when(rows_count > 0, |this| {
                        this.child(
                            v_virtual_list(
                                command_state.clone(),
                                "command-list",
                                row_sizes,
                                move |this, visible_range, window, cx| {
                                    visible_range
                                        .map(|row_ix| this.render_visible_row(row_ix, window, cx))
                                        .collect::<Vec<_>>()
                                },
                            )
                            // Padding on the virtual list acts like CSS
                            // scroll-padding: the scroll ends keep their inset
                            // while scrolled-under rows paint and clip at the
                            // list edge.
                            .p_1()
                            .with_sizing_behavior(ListSizingBehavior::Infer)
                            .track_scroll(&self.scroll_handle)
                            .map(|list| {
                                gpui_base::ScrollBounce::new(
                                    "command-scroll-bounce",
                                    &self.scroll_handle,
                                    list,
                                )
                                .when_some(self.options.scroll_bounce, |bounce, on| {
                                    bounce.enabled(on)
                                })
                            }),
                        )
                        .child(Scrollbar::vertical(&self.scroll_handle))
                    }),
            )
            .when_some(self.options.footer.as_ref(), |this, footer| {
                this.child(footer(self, window, cx))
            })
    }
}

// MARK: Tests

#[cfg(test)]
mod tests {
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
    };

    use gpui::{
        AppContext as _, AvailableSpace, Entity, InteractiveElement as _, IntoElement, KeyBinding,
        Modifiers, ParentElement as _, Pixels, Render, Styled as _, TestAppContext, Window,
        actions, div, point, prelude::FluentBuilder as _, px,
    };

    use super::{CONTEXT, CommandModel, CommandRow, CommandState, SEPARATOR_ROW_HEIGHT};
    use crate::{
        Disableable as _, Icon, IconName, IndexPath,
        actions::{Cancel, Confirm, SelectDown},
        command::{Command, CommandEntry, CommandGroup, CommandItem},
    };

    actions!(
        command_test,
        [GlobalTestItem, OpenTestItem, RemovePaletteTestItem]
    );

    struct CommandActionsHarness {
        state: Entity<CommandState>,
        events: Rc<RefCell<Vec<String>>>,
    }

    impl Render for CommandActionsHarness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            let action_events = self.events.clone();
            let propagated_cancel_events = self.events.clone();
            let query_events = self.events.clone();
            let select_events = self.events.clone();
            let confirm_events = self.events.clone();
            let cancel_events = self.events.clone();

            div()
                .size_full()
                .on_action(move |_: &OpenTestItem, _, _| {
                    action_events.borrow_mut().push("action".into());
                })
                .on_action(move |_: &Cancel, _, _| {
                    propagated_cancel_events
                        .borrow_mut()
                        .push("propagated_cancel".into());
                })
                .child(
                    Command::new(&self.state)
                        .item(
                            CommandItem::new()
                                .label("Item")
                                .keywords(["needle"])
                                .action(Box::new(OpenTestItem)),
                        )
                        .item(CommandItem::new().label("Item"))
                        .item(
                            CommandItem::new()
                                .label("Item")
                                .action(Box::new(GlobalTestItem)),
                        )
                        .on_query(move |query, _, _| {
                            query_events.borrow_mut().push(format!("query:{query}"));
                        })
                        .on_select(move |index, _, _| {
                            select_events
                                .borrow_mut()
                                .push(format!("select:{}:{}", index.section, index.row));
                        })
                        .on_confirm(move |index, _, _| {
                            confirm_events
                                .borrow_mut()
                                .push(format!("confirm:{}:{}", index.section, index.row));
                        })
                        .on_cancel(move |_, _| {
                            cancel_events.borrow_mut().push("cancel".into());
                        }),
                )
        }
    }

    struct ReentrantCallbackHarness {
        state: Entity<CommandState>,
        events: Vec<String>,
    }

    impl Render for ReentrantCallbackHarness {
        fn render(&mut self, _: &mut Window, cx: &mut gpui::Context<Self>) -> impl IntoElement {
            let select_owner = cx.weak_entity();
            let query_owner = cx.weak_entity();
            let confirm_owner = cx.weak_entity();

            Command::new(&self.state)
                .item(CommandItem::new().label("alpha"))
                .item(CommandItem::new().label("beta"))
                .on_select(move |index, _, cx| {
                    _ = select_owner.update(cx, |harness, cx| {
                        assert_eq!(harness.state.read(cx).selected_index(), Some(index));
                        harness
                            .events
                            .push(format!("select:{}:{}", index.section, index.row));
                    });
                })
                .on_query(move |query, _, cx| {
                    _ = query_owner.update(cx, |harness, cx| {
                        assert_eq!(harness.state.read(cx).query(cx).as_ref(), query);
                        harness.events.push(format!("query:{query}"));
                    });
                })
                .on_confirm(move |index, _, cx| {
                    _ = confirm_owner.update(cx, |harness, cx| {
                        assert_eq!(harness.state.read(cx).selected_index(), Some(index));
                        harness
                            .events
                            .push(format!("confirm:{}:{}", index.section, index.row));
                    });
                })
        }
    }

    #[gpui::test]
    fn query_and_selection_callbacks_run_after_the_state_lease_in_defined_order(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let (harness, cx) = cx.add_window_view(|window, cx| ReentrantCallbackHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            events: Vec::new(),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| {
            _ = window.draw(cx);
            state.update(cx, |state, cx| {
                state.selected_index = Some(1);
                state.set_query("alpha", window, cx);
            });
        });

        assert_eq!(
            harness.read_with(cx, |harness, _| harness.events.clone()),
            ["select:0:0", "query:alpha"]
        );
    }

    #[gpui::test]
    fn actionless_confirm_callback_runs_after_the_state_lease(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (harness, cx) = cx.add_window_view(|window, cx| ReentrantCallbackHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            events: Vec::new(),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| {
            _ = window.draw(cx);
            state.update(cx, |state, cx| state.confirm(0, window, cx));
        });

        assert_eq!(
            harness.read_with(cx, |harness, _| harness.events.clone()),
            ["confirm:0:0"]
        );
    }

    struct CommandItemWidthHarness {
        state: Entity<CommandState>,
        matched_ix: usize,
        width: Rc<Cell<Option<Pixels>>>,
    }

    impl Render for CommandItemWidthHarness {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            let width = self.width.clone();
            let item = self.state.update(cx, |state, cx| {
                state.render_item(self.matched_ix, window, cx)
            });

            div()
                .on_children_prepainted(move |bounds, _, _| width.set(Some(bounds[0].size.width)))
                .child(item)
        }
    }

    #[gpui::test]
    fn action_that_removes_command_state_still_confirms_after_dispatch(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let events = Rc::new(RefCell::new(Vec::new()));
        let state_owner: Rc<RefCell<Option<Entity<CommandState>>>> = Rc::new(RefCell::new(None));
        let action_events = events.clone();
        let action_state_owner = state_owner.clone();
        cx.update(|cx| {
            cx.on_action(move |_: &RemovePaletteTestItem, _| {
                action_events.borrow_mut().push("action".into());
                action_state_owner.borrow_mut().take();
            });
        });
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let confirm_events = events.clone();
            let state = cx.new(|cx| {
                let mut state = CommandState::new(window, cx);
                state.install_model(
                    CommandModel {
                        entries: vec![CommandEntry::Item(
                            CommandItem::new()
                                .label("removed")
                                .action(Box::new(RemovePaletteTestItem)),
                        )],
                        searchable: false,
                        on_confirm: Some(Rc::new(move |index, _, _| {
                            confirm_events
                                .borrow_mut()
                                .push(format!("confirm:{}:{}", index.section, index.row));
                        })),
                        ..CommandModel::default()
                    },
                    cx,
                );
                state
            });
            *state_owner.borrow_mut() = Some(state.clone());
            state.update(cx, |state, cx| state.confirm(0, window, cx));
        });
        cx.run_until_parked();

        assert!(state_owner.borrow().is_none());
        assert_eq!(events.borrow().as_slice(), ["action", "confirm:0:0"]);
    }

    #[gpui::test]
    fn command_actions_and_callbacks_follow_defined_order(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
            cx.bind_keys([
                KeyBinding::new("ctrl-o", OpenTestItem, Some(CONTEXT)),
                KeyBinding::new("ctrl-g", GlobalTestItem, None),
            ]);
        });
        let events = Rc::new(RefCell::new(Vec::new()));
        let (harness, cx) = cx.add_window_view(|window, cx| CommandActionsHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            events: events.clone(),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| {
            _ = window.draw(cx);
            state.update(cx, |state, cx| state.focus(window, cx));
            _ = window.draw(cx);
        });

        let action_width = Rc::new(Cell::new(None));
        let plain_width = Rc::new(Cell::new(None));
        let global_width = Rc::new(Cell::new(None));
        let (action_probe, plain_probe, global_probe) = cx.update(|_, cx| {
            (
                cx.new(|_| CommandItemWidthHarness {
                    state: state.clone(),
                    matched_ix: 0,
                    width: action_width.clone(),
                }),
                cx.new(|_| CommandItemWidthHarness {
                    state: state.clone(),
                    matched_ix: 1,
                    width: plain_width.clone(),
                }),
                cx.new(|_| CommandItemWidthHarness {
                    state: state.clone(),
                    matched_ix: 2,
                    width: global_width.clone(),
                }),
            )
        });
        cx.draw(
            point(px(0.), px(0.)),
            AvailableSpace::min_size(),
            move |_, _| action_probe.into_any_element(),
        );
        cx.draw(
            point(px(0.), px(0.)),
            AvailableSpace::min_size(),
            move |_, _| plain_probe.into_any_element(),
        );
        cx.draw(
            point(px(0.), px(0.)),
            AvailableSpace::min_size(),
            move |_, _| global_probe.into_any_element(),
        );
        let action_width = action_width.get().unwrap();
        let plain_width = plain_width.get().unwrap();
        let global_width = global_width.get().unwrap();
        assert!(
            action_width > plain_width,
            "the scoped Action binding should add a visible Kbd ({action_width:?} vs {plain_width:?})",
        );
        assert!(
            global_width > plain_width,
            "the app-level fallback binding should add a visible Kbd ({global_width:?} vs {plain_width:?})",
        );

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_query("needle", window, cx);
                state.set_query("needle", window, cx);
                state.set_query("", window, cx);
            });
            window.dispatch_action(Box::new(SelectDown), cx);
            window.dispatch_action(Box::new(crate::actions::SelectUp), cx);
            window.dispatch_action(Box::new(Confirm { secondary: false }), cx);
        });
        cx.run_until_parked();

        assert_eq!(
            events.borrow().as_slice(),
            [
                "query:needle",
                "query:",
                "select:0:1",
                "select:0:0",
                "action",
                "confirm:0:0",
            ]
        );

        cx.simulate_click(point(px(20.), px(52.)), Modifiers::default());
        cx.run_until_parked();
        cx.update(|window, cx| window.dispatch_action(Box::new(Cancel), cx));
        cx.run_until_parked();

        assert_eq!(
            events.borrow().as_slice(),
            [
                "query:needle",
                "query:",
                "select:0:1",
                "select:0:0",
                "action",
                "confirm:0:0",
                "action",
                "confirm:0:0",
                "cancel",
                "propagated_cancel",
            ]
        );
    }

    struct CommandOwnedEntriesHarness {
        state: Entity<CommandState>,
    }

    impl Render for CommandOwnedEntriesHarness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            Command::new(&self.state)
                .searchable(false)
                .item(CommandItem::new().label("alpha"))
                .group(
                    CommandGroup::new()
                        .label("Settings")
                        .item(CommandItem::new().label("beta")),
                )
                .separator()
                .item(
                    CommandItem::new()
                        .label("custom")
                        .child(|_, _| div().h(px(72.)).child("Custom")),
                )
        }
    }

    #[gpui::test]
    fn command_owns_entries_and_lazy_item_content(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (harness, cx) = cx.add_window_view(|window, cx| CommandOwnedEntriesHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));

        let (labels, rows, row_sizes) = cx.update(|_, cx| {
            let state = harness.read(cx).state.read(cx);
            (
                (0..state.matched_count())
                    .map(|matched_ix| {
                        state
                            .item_at(matched_ix)
                            .unwrap()
                            .label_text()
                            .unwrap()
                            .clone()
                    })
                    .collect::<Vec<_>>(),
                state.rows.clone(),
                state.row_sizes.clone(),
            )
        });

        assert_eq!(labels, ["alpha", "beta", "custom"]);
        assert!(matches!(
            rows.as_slice(),
            [
                CommandRow::Item(_),
                CommandRow::Heading(heading),
                CommandRow::Item(_),
                CommandRow::Separator,
                CommandRow::Item(_),
            ] if heading == "Settings"
        ));
        assert_eq!(row_sizes[4].height, px(84.));
    }

    fn command_with_entries(
        state: &Entity<CommandState>,
        entries: impl IntoIterator<Item = CommandEntry>,
    ) -> Command {
        entries
            .into_iter()
            .fold(Command::new(state), |command, entry| match entry {
                CommandEntry::Item(item) => command.item(item),
                CommandEntry::Group(group) => command.group(group),
                CommandEntry::Separator => command.separator(),
            })
    }

    fn command_state(
        window: &mut Window,
        cx: &mut gpui::Context<CommandState>,
        entries: impl IntoIterator<Item = CommandEntry>,
    ) -> CommandState {
        let mut state = CommandState::new(window, cx);
        state.install_model(
            CommandModel {
                entries: entries.into_iter().collect(),
                ..CommandModel::default()
            },
            cx,
        );
        state
    }

    fn command_state_with_options(
        window: &mut Window,
        cx: &mut gpui::Context<CommandState>,
        entries: impl IntoIterator<Item = CommandEntry>,
        searchable: bool,
    ) -> CommandState {
        let mut state = CommandState::new(window, cx);
        state.install_model(
            CommandModel {
                entries: entries.into_iter().collect(),
                searchable,
                ..CommandModel::default()
            },
            cx,
        );
        state
    }

    fn suggestion_entries() -> Vec<CommandEntry> {
        vec![
            CommandGroup::new()
                .label("Suggestions")
                .item(CommandItem::new().label("Calendar"))
                .item(CommandItem::new().label("Search Emoji"))
                .item(CommandItem::new().label("Calculator").disabled(true))
                .into(),
            CommandEntry::Separator,
            CommandGroup::new()
                .label("Settings")
                .item(CommandItem::new().label("Profile"))
                .item(CommandItem::new().label("Billing"))
                .into(),
        ]
    }

    #[gpui::test]
    fn query_hides_the_groups_that_have_no_match(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| command_state(window, cx, suggestion_entries()));

            state.update(cx, |state, cx| {
                state.update_matches(cx);
                assert_eq!(state.matched_count(), 5);
                assert_eq!(
                    state
                        .rows
                        .iter()
                        .filter(|row| matches!(row, CommandRow::Heading(_)))
                        .count(),
                    2,
                );
                assert_eq!(
                    state
                        .rows
                        .iter()
                        .filter(|row| matches!(row, CommandRow::Separator))
                        .count(),
                    1,
                );

                // "Bil" only matches an item of the second group, so the first
                // group's heading and the separator between them both go.
                state.set_query("Bil", window, cx);
                state.update_matches(cx);

                assert_eq!(state.matched_count(), 1);
                assert_eq!(state.selected_index(), Some(IndexPath::new(1).section(1)));
                assert_eq!(
                    state
                        .rows
                        .iter()
                        .filter(|row| matches!(row, CommandRow::Separator))
                        .count(),
                    0,
                );
                assert!(matches!(state.rows.first(), Some(CommandRow::Heading(_))));
            });
        });
    }

    fn custom_entries() -> Vec<CommandEntry> {
        vec![CommandEntry::Item(
            CommandItem::new().label("Custom").child(|_, _| div()),
        )]
    }

    #[gpui::test]
    fn reinstalling_an_unchanged_model_keeps_the_measured_rows(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| command_state(window, cx, suggestion_entries()));

            state.update(cx, |state, cx| {
                // A host re-render rebuilds an equal model: nothing to lay out again.
                state.needs_measure = false;
                state.install_model(
                    CommandModel {
                        entries: suggestion_entries(),
                        ..CommandModel::default()
                    },
                    cx,
                );
                assert!(!state.needs_measure);
                assert_eq!(state.matched_count(), 5);

                // A custom child can read state outside the item, so it is
                // always measured again.
                state.install_model(
                    CommandModel {
                        entries: custom_entries(),
                        ..CommandModel::default()
                    },
                    cx,
                );
                assert!(state.needs_measure);
                assert_eq!(state.matched_count(), 1);

                // Even when the host clones entries it built once, which
                // keeps the same closure.
                state.needs_measure = false;
                let entries = state.model.entries.clone();
                state.install_model(
                    CommandModel {
                        entries,
                        ..CommandModel::default()
                    },
                    cx,
                );
                assert!(state.needs_measure);

                // A changed label or icon style changes how the label wraps,
                // and a changed disabled flag changes what can be highlighted.
                let item = || CommandItem::new().label("Renamed");
                let icon = || Icon::new(IconName::Check);
                for entries in [
                    vec![CommandEntry::Item(item())],
                    vec![CommandEntry::Item(item().icon(icon()))],
                    vec![CommandEntry::Item(item().icon(icon().ml_2()))],
                    vec![CommandEntry::Item(
                        item().icon(icon().ml_2()).disabled(true),
                    )],
                ] {
                    state.needs_measure = false;
                    state.install_model(
                        CommandModel {
                            entries,
                            ..CommandModel::default()
                        },
                        cx,
                    );
                    assert!(state.needs_measure);
                }
                assert_eq!(state.selected_index(), None);
            });
        });
    }

    #[gpui::test]
    fn a_query_that_matches_nothing_leaves_no_rows(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| command_state(window, cx, suggestion_entries()));

            state.update(cx, |state, cx| {
                state.set_query("zzz", window, cx);
                state.update_matches(cx);

                assert_eq!(state.matched_count(), 0);
                assert!(state.rows.is_empty());
                assert_eq!(state.selected_index(), None);
            });
        });
    }

    #[gpui::test]
    fn filterable_off_keeps_every_item_and_resets_the_highlight(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| {
                let mut state = CommandState::new(window, cx);
                state.install_model(
                    CommandModel {
                        entries: suggestion_entries(),
                        filterable: false,
                        ..CommandModel::default()
                    },
                    cx,
                );
                state
            });

            state.update(cx, |state, cx| {
                state.set_selected_index(Some(IndexPath::new(1).section(1)), window, cx);

                // "Bil" would locally match only "Billing"; an unfiltered
                // palette keeps every row and hands the highlight back to the
                // first item instead of the textual match.
                state.set_query("Bil", window, cx);

                assert_eq!(state.matched_count(), 5);
                assert_eq!(state.selected_index(), Some(IndexPath::new(0).section(0)));
            });
        });
    }

    #[gpui::test]
    fn keywords_match_when_the_label_does_not(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| {
                command_state(
                    window,
                    cx,
                    [CommandEntry::Item(
                        CommandItem::new().label("Profile").keywords(["account"]),
                    )],
                )
            });

            state.update(cx, |state, cx| {
                state.set_query("account", window, cx);
                state.update_matches(cx);

                assert_eq!(state.matched_count(), 1);
            });
        });
    }

    #[gpui::test]
    fn non_searchable_command_keeps_every_item(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let state = cx.new(|cx| {
                command_state_with_options(
                    window,
                    cx,
                    [
                        CommandEntry::Item(CommandItem::new().label("alpha")),
                        CommandEntry::Item(CommandItem::new().label("beta")),
                    ],
                    false,
                )
            });
            state.update(cx, |state, cx| {
                state.set_query("missing", window, cx);
                assert_eq!(state.matched_count(), 2);
            });
        });
    }

    #[gpui::test]
    fn non_searchable_command_uses_frame_focus(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let confirmed = Rc::new(RefCell::new(None));
        let confirmed_for_render = confirmed.clone();
        let (harness, cx) = cx.add_window_view(move |window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                let confirmed = confirmed_for_render.clone();
                Command::new(state)
                    .searchable(false)
                    .item(CommandItem::new().label("alpha"))
                    .item(CommandItem::new().label("beta"))
                    .on_confirm(move |index_path, _, _| {
                        *confirmed.borrow_mut() = Some(index_path);
                    })
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.focus(window, cx));
            assert!(state.read(cx).focus_handle.is_focused(window));
            window.dispatch_action(Box::new(SelectDown), cx);
            window.dispatch_action(Box::new(Confirm { secondary: false }), cx);
        });

        assert_eq!(*confirmed.borrow(), Some(IndexPath::new(1).section(0)));
    }

    #[gpui::test]
    fn filtered_ungrouped_item_keeps_its_input_row(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let confirmed = Rc::new(RefCell::new(None));
        let confirmed_for_render = confirmed.clone();
        let (harness, cx) = cx.add_window_view(move |window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                let confirmed = confirmed_for_render.clone();
                Command::new(state)
                    .items([
                        CommandItem::new().label("alpha"),
                        CommandItem::new().label("beta"),
                        CommandItem::new().label("gamma"),
                    ])
                    .on_confirm(move |index_path, _, _| {
                        *confirmed.borrow_mut() = Some(index_path);
                    })
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_query("gamma", window, cx);
                state.focus(window, cx);
            });
            window.dispatch_action(Box::new(Confirm { secondary: false }), cx);
        });

        assert_eq!(*confirmed.borrow(), Some(IndexPath::new(2).section(0)));
    }

    #[gpui::test]
    fn initially_rendered_disabled_first_item_selects_and_confirms_the_first_enabled_item(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let confirmed = Rc::new(RefCell::new(None));
        let confirmed_for_render = confirmed.clone();
        let (harness, cx) = cx.add_window_view(move |window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                let confirmed = confirmed_for_render.clone();
                Command::new(state)
                    .item(CommandItem::new().label("disabled").disabled(true))
                    .item(CommandItem::new().label("enabled"))
                    .on_confirm(move |index_path, _, _| {
                        *confirmed.borrow_mut() = Some(index_path);
                    })
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.focus(window, cx));
            window.dispatch_action(Box::new(Confirm { secondary: false }), cx);
        });

        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(IndexPath::new(1).section(0))
        );
        assert_eq!(*confirmed.borrow(), Some(IndexPath::new(1).section(0)));
    }

    #[gpui::test]
    fn initially_rendered_all_disabled_items_have_no_selected_index_and_ignore_enter(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let confirmed = Rc::new(RefCell::new(None));
        let confirmed_for_render = confirmed.clone();
        let (harness, cx) = cx.add_window_view(move |window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                let confirmed = confirmed_for_render.clone();
                Command::new(state)
                    .item(CommandItem::new().label("one").disabled(true))
                    .item(CommandItem::new().label("two").disabled(true))
                    .on_confirm(move |index_path, _, _| {
                        *confirmed.borrow_mut() = Some(index_path);
                    })
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.focus(window, cx));
            window.dispatch_action(Box::new(Confirm { secondary: false }), cx);
        });

        assert_eq!(state.read_with(cx, |state, _| state.selected_index()), None);
        assert_eq!(*confirmed.borrow(), None);
    }

    #[gpui::test]
    fn non_searchable_command_cancels_without_clearing_a_hidden_query(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cancelled = Rc::new(Cell::new(false));
        let cancelled_for_render = cancelled.clone();
        let query_calls = Rc::new(Cell::new(0));
        let query_calls_for_render = query_calls.clone();
        let (harness, cx) = cx.add_window_view(move |window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                let cancelled = cancelled_for_render.clone();
                let query_calls = query_calls_for_render.clone();
                Command::new(state)
                    .searchable(false)
                    .item(CommandItem::new().label("alpha"))
                    .on_query(move |_, _, _| query_calls.set(query_calls.get() + 1))
                    .on_cancel(move |_, _| cancelled.set(true))
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_query("hidden query", window, cx);
                state.focus(window, cx);
            });
            window.dispatch_action(Box::new(Cancel), cx);
        });

        assert!(cancelled.get());
        assert_eq!(query_calls.get(), 0);
        assert_eq!(
            state.read_with(cx, |state, cx| state.query(cx)),
            "hidden query"
        );
    }

    #[gpui::test]
    fn moving_the_highlight_skips_disabled_items_and_wraps(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| command_state(window, cx, suggestion_entries()));

            state.update(cx, |state, cx| {
                state.update_matches(cx);
                state.reset_selection();
                assert_eq!(state.selected_index(), Some(IndexPath::new(0).section(0)));

                state.select_by(1, window, cx);
                assert_eq!(state.selected_index(), Some(IndexPath::new(1).section(0)));

                // "Calculator" is disabled, so it is stepped over.
                state.select_by(1, window, cx);
                assert_eq!(state.selected_index(), Some(IndexPath::new(0).section(1)));

                state.select_by(-1, window, cx);
                assert_eq!(state.selected_index(), Some(IndexPath::new(1).section(0)));

                // Wraps around the end, skipping the disabled item again.
                state.select_by(-1, window, cx);
                assert_eq!(state.selected_index(), Some(IndexPath::new(0).section(0)));
                state.select_by(-1, window, cx);
                assert_eq!(state.selected_index(), Some(IndexPath::new(1).section(1)));
            });
        });
    }

    #[gpui::test]
    fn owner_can_set_and_clear_selection_by_original_index_path(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let initially_empty = cx.new(|cx| CommandState::new(window, cx));
            initially_empty.update(cx, |state, cx| {
                state.set_selected_index(None, window, cx);
                state.install_model(
                    CommandModel {
                        entries: suggestion_entries().into_iter().collect(),
                        ..CommandModel::default()
                    },
                    cx,
                );
                assert_eq!(state.selected_index(), None);
            });

            let state = cx.new(|cx| command_state(window, cx, suggestion_entries()));

            state.update(cx, |state, cx| {
                let target = IndexPath::new(1).section(1);
                state.set_selected_index(Some(target), window, cx);
                assert_eq!(state.selected_index(), Some(target));

                state.set_selected_index(None, window, cx);
                assert_eq!(state.selected_index(), None);

                state.install_model(
                    CommandModel {
                        entries: suggestion_entries().into_iter().collect(),
                        ..CommandModel::default()
                    },
                    cx,
                );
                assert_eq!(state.selected_index(), None);

                state.set_query("calendar", window, cx);
                state.set_selected_index(Some(target), window, cx);
                assert_eq!(state.selected_index(), None);
            });
        });
    }

    #[gpui::test]
    fn confirming_a_disabled_item_does_nothing(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();

        cx.update(|window, cx| {
            let state = cx.new(|cx| {
                command_state(
                    window,
                    cx,
                    [
                        CommandEntry::Item(CommandItem::new().label("enabled")),
                        CommandEntry::Item(CommandItem::new().label("disabled").disabled(true)),
                    ],
                )
            });

            state.update(cx, |state, cx| {
                state.update_matches(cx);

                assert_eq!(state.matched_count(), 2);
                // Reaching the disabled row is only possible with the mouse or
                // an explicit index; confirming it must be a no-op.
                state.confirm(1, window, cx);
                assert_eq!(state.selected_index, Some(0));
            });
        });
    }

    #[gpui::test]
    fn a_checked_item_uses_an_xsmall_trailing_check_icon(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let cx = cx.add_empty_window();
        let unchecked_width = Rc::new(Cell::new(None));
        let checked_width = Rc::new(Cell::new(None));
        let (unchecked, checked) = cx.update(|window, cx| {
            let unchecked_state = cx.new(|cx| {
                command_state(
                    window,
                    cx,
                    [CommandEntry::Item(CommandItem::new().label("theme"))],
                )
            });
            let checked_state = cx.new(|cx| {
                command_state(
                    window,
                    cx,
                    [CommandEntry::Item(
                        CommandItem::new().label("theme").checked(true),
                    )],
                )
            });
            let unchecked_width = unchecked_width.clone();
            let checked_width = checked_width.clone();
            (
                cx.new(|_| CheckIconWidthHarness {
                    state: unchecked_state,
                    width: unchecked_width,
                }),
                cx.new(|_| CheckIconWidthHarness {
                    state: checked_state,
                    width: checked_width,
                }),
            )
        });

        cx.draw(
            gpui::point(px(0.), px(0.)),
            gpui::AvailableSpace::min_size(),
            move |_, _| unchecked.into_any_element(),
        );

        cx.draw(
            gpui::point(px(0.), px(0.)),
            gpui::AvailableSpace::min_size(),
            move |_, _| checked.into_any_element(),
        );

        assert_eq!(
            checked_width.get().unwrap() - unchecked_width.get().unwrap(),
            px(20.)
        );
    }

    struct CheckIconWidthHarness {
        state: Entity<CommandState>,
        width: Rc<Cell<Option<gpui::Pixels>>>,
    }

    impl Render for CheckIconWidthHarness {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            let width = self.width.clone();
            let item = self.state.update(cx, |state, cx| {
                state.update_matches(cx);
                state.render_item(0, window, cx)
            });

            div()
                .on_children_prepainted(move |bounds, _, _| width.set(Some(bounds[0].size.width)))
                .child(item)
        }
    }

    struct Harness {
        state: Entity<CommandState>,
        command: Rc<dyn Fn(&Entity<CommandState>) -> Command>,
    }

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .child((self.command)(&self.state).max_h(px(200.)))
        }
    }

    #[gpui::test]
    fn header_and_footer_render_with_current_state(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let header_calls = Rc::new(Cell::new(0));
        let footer_calls = Rc::new(Cell::new(0));
        let header_matched_count = Rc::new(Cell::new(None));
        let footer_matched_count = Rc::new(Cell::new(None));

        let (harness, cx) = cx.add_window_view(|window, cx| HeaderFooterHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            header_calls,
            footer_calls,
            header_matched_count,
            footer_matched_count,
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));

        let (header_calls, footer_calls, header_matched_count, footer_matched_count) =
            cx.update(|_, cx| {
                let harness = harness.read(cx);
                (
                    harness.header_calls.get(),
                    harness.footer_calls.get(),
                    harness.header_matched_count.get(),
                    harness.footer_matched_count.get(),
                )
            });
        assert!(header_calls > 0);
        assert!(footer_calls > 0);
        assert_eq!(header_matched_count, Some(2));
        assert_eq!(footer_matched_count, Some(2));
    }

    #[gpui::test]
    fn custom_empty_slot_renders_with_current_state(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let empty_calls = Rc::new(Cell::new(0));
        let empty_matched_count = Rc::new(Cell::new(None));
        let calls = empty_calls.clone();
        let matched_count = empty_matched_count.clone();
        let (_harness, cx) = cx.add_window_view(move |window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                let calls = calls.clone();
                let matched_count = matched_count.clone();
                Command::new(state).empty(
                    move |state: &CommandState, _: &mut Window, _: &mut gpui::App| {
                        calls.set(calls.get() + 1);
                        matched_count.set(Some(state.matched_count()));
                        div().child("Custom empty")
                    },
                )
            }),
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));

        assert!(empty_calls.get() > 0);
        assert_eq!(empty_matched_count.get(), Some(0));
    }

    fn entries_with_late_first_enabled_item() -> Vec<CommandEntry> {
        vec![
            CommandGroup::new()
                .label("Disabled")
                .items((0..30).map(|ix| {
                    CommandItem::new()
                        .label(format!("disabled-{ix}"))
                        .keywords(["match"])
                        .disabled(true)
                }))
                .into(),
            CommandEntry::Separator,
            CommandGroup::new()
                .label("Enabled")
                .item(CommandItem::new().label("enabled").keywords(["match"]))
                .into(),
        ]
    }

    fn assert_first_enabled_row_is_scrolled_into_view(
        state: &Entity<CommandState>,
        cx: &mut TestAppContext,
    ) {
        let (selected_row, offset) = state.read_with(cx, |state, _| {
            (
                state.matched[state.selected_index.unwrap()].row_ix,
                state.scroll_handle.base_handle().offset().y,
            )
        });

        assert!(selected_row > 30);
        assert!(
            offset < px(-900.),
            "the list should scroll to the selected row, not row zero ({offset:?})",
        );
    }

    #[gpui::test]
    fn first_enabled_selection_resets_scroll_to_its_late_row(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (harness, cx) = cx.add_window_view(|window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(|state| {
                command_with_entries(state, entries_with_late_first_enabled_item())
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        assert_first_enabled_row_is_scrolled_into_view(&state, cx);

        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.set_query("match", window, cx));
            _ = window.draw(cx);
        });
        assert_first_enabled_row_is_scrolled_into_view(&state, cx);

        cx.update(|window, cx| {
            harness.update(cx, |_, cx| {
                cx.notify();
            });
            _ = window.draw(cx);
        });
        assert_first_enabled_row_is_scrolled_into_view(&state, cx);
    }

    struct HeaderFooterHarness {
        state: Entity<CommandState>,
        header_calls: Rc<Cell<usize>>,
        footer_calls: Rc<Cell<usize>>,
        header_matched_count: Rc<Cell<Option<usize>>>,
        footer_matched_count: Rc<Cell<Option<usize>>>,
    }

    impl Render for HeaderFooterHarness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            let header_calls = self.header_calls.clone();
            let header_matched_count = self.header_matched_count.clone();
            let footer_calls = self.footer_calls.clone();
            let footer_matched_count = self.footer_matched_count.clone();

            div().size_full().child(
                Command::new(&self.state)
                    .items([
                        CommandItem::new().label("Calendar"),
                        CommandItem::new().label("Calculator"),
                    ])
                    .max_h(px(200.))
                    .header(move |state, _, _| {
                        header_calls.set(header_calls.get() + 1);
                        header_matched_count.set(Some(state.matched_count()));
                        div()
                    })
                    .footer(move |state, _, _| {
                        footer_calls.set(footer_calls.get() + 1);
                        footer_matched_count.set(Some(state.matched_count()));
                        div()
                    }),
            )
        }
    }

    struct PaddedHarness {
        state: Entity<CommandState>,
    }

    impl Render for PaddedHarness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            div().size_full().child(
                Command::new(&self.state)
                    .item(
                        CommandItem::new()
                            .label("fixed")
                            .child(|_, _| div().h(px(32.))),
                    )
                    .max_h(px(200.))
                    .p_4(),
            )
        }
    }

    struct WrappingHarness {
        state: Entity<CommandState>,
        width: Pixels,
        no_wrap: bool,
    }

    impl Render for WrappingHarness {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            div().size_full().child(
                div().w(self.width).child(
                    Command::new(&self.state)
                        .item(CommandItem::new().label("wrapped").child(|_, _| {
                            div()
                                .w_full()
                                .child("A command row whose content wraps at narrow list widths")
                        }))
                        .max_h(px(200.))
                        .when(self.no_wrap, |this| this.whitespace_nowrap()),
                ),
            )
        }
    }

    #[gpui::test]
    fn wrapping_rows_remeasure_for_the_list_content_width(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| WrappingHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            width: px(360.),
            no_wrap: false,
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));

        let wide = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);

        cx.update(|_, cx| {
            harness.update(cx, |harness, cx| {
                harness.width = px(120.);
                cx.notify();
            })
        });
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let narrow = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);

        assert!(
            narrow > wide,
            "the narrow list should cache a taller wrapped row ({narrow:?} vs {wide:?})",
        );
    }

    #[gpui::test]
    fn wrapping_rows_remeasure_when_rem_size_changes(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| {
            window.set_rem_size(px(20.));
            WrappingHarness {
                state: cx.new(|cx| CommandState::new(window, cx)),
                width: px(160.),
                no_wrap: false,
            }
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let smaller_rem = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);

        cx.update(|window, cx| {
            window.set_rem_size(px(28.));
            _ = window.draw(cx);
        });
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let larger_rem = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);

        assert!(
            larger_rem > smaller_rem,
            "a larger rem should remeasure the fixed-width wrapped row ({larger_rem:?} vs {smaller_rem:?})",
        );
    }

    #[gpui::test]
    fn wrapping_rows_remeasure_when_inherited_typography_changes(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| WrappingHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            width: px(160.),
            no_wrap: false,
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let wrapped_height = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);

        cx.update(|window, cx| {
            harness.update(cx, |harness, cx| {
                harness.no_wrap = true;
                cx.notify();
            });
            _ = window.draw(cx);
        });
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let no_wrap_height = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);
        assert!(
            no_wrap_height < wrapped_height,
            "a changed inherited typography should remeasure the fixed-width row ({no_wrap_height:?} vs {wrapped_height:?})",
        );
    }

    #[gpui::test]
    fn outer_command_padding_does_not_inflate_measured_row_heights(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| PaddedHarness {
            state: cx.new(|cx| CommandState::new(window, cx)),
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let height = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes[0].height);

        assert_eq!(height, px(44.));
    }

    #[gpui::test]
    fn custom_rows_keep_independent_heights(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(|state| {
                Command::new(state)
                    .group(
                        CommandGroup::new().label("Short").item(
                            CommandItem::new()
                                .label("short")
                                .child(|_, _| div().h(px(32.))),
                        ),
                    )
                    .separator()
                    .group(
                        CommandGroup::new().label("Tall").item(
                            CommandItem::new()
                                .label("tall")
                                .child(|_, _| div().h(px(72.))),
                        ),
                    )
            }),
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        let row_sizes = cx.update(|_, cx| harness.read(cx).state.read(cx).row_sizes.clone());

        assert_eq!(row_sizes.len(), 5);
        assert!(row_sizes[0].height > px(0.));
        assert_eq!(row_sizes[1].height, px(44.));
        assert_eq!(row_sizes[2].height, px(SEPARATOR_ROW_HEIGHT));
        assert!(row_sizes[3].height > px(0.));
        assert_eq!(row_sizes[4].height, px(84.));
    }

    #[gpui::test]
    fn reinstalling_a_model_preserves_selection_by_index_path_and_remeasures_rows(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let reversed = Rc::new(Cell::new(false));
        let reversed_for_render = reversed.clone();
        let (harness, cx) = cx.add_window_view(|window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(move |state| {
                if reversed_for_render.get() {
                    Command::new(state)
                        .item(
                            CommandItem::new()
                                .label("beta")
                                .child(|_, _| div().h(px(72.))),
                        )
                        .item(
                            CommandItem::new()
                                .label("alpha")
                                .child(|_, _| div().h(px(32.))),
                        )
                } else {
                    Command::new(state)
                        .item(
                            CommandItem::new()
                                .label("alpha")
                                .child(|_, _| div().h(px(32.))),
                        )
                        .item(
                            CommandItem::new()
                                .label("beta")
                                .child(|_, _| div().h(px(72.))),
                        )
                }
            }),
        });
        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.select_by(1, window, cx));
        });
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(IndexPath::new(1).section(0)),
        );

        reversed.set(true);
        cx.update(|window, cx| {
            harness.update(cx, |_, cx| cx.notify());
            _ = window.draw(cx);
        });

        let (selected_matched_index, selected_index, row_sizes) =
            state.read_with(cx, |state, _| {
                (
                    state.selected_index,
                    state.selected_index(),
                    state.row_sizes.clone(),
                )
            });
        assert_eq!(selected_matched_index, Some(1));
        assert_eq!(selected_index, Some(IndexPath::new(1).section(0)));
        assert_eq!(row_sizes[0].height, px(84.));
        assert_eq!(row_sizes[1].height, px(44.));
    }

    #[gpui::test]
    fn a_state_redraw_reuses_the_installed_custom_row_measurement(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let renders = Rc::new(Cell::new(0));
        let count = renders.clone();
        let cx = cx.add_empty_window();
        let state = cx.update(|window, cx| {
            cx.new(|cx| {
                command_state(
                    window,
                    cx,
                    [CommandEntry::Item(
                        CommandItem::new().label("custom").child(move |_, _| {
                            count.set(count.get() + 1);
                            div().child("Custom")
                        }),
                    )],
                )
            })
        });

        let first_state = state.clone();
        cx.draw(
            gpui::point(px(0.), px(0.)),
            gpui::AvailableSpace::min_size(),
            move |_, _| first_state.into_any_element(),
        );
        let settled_state = state.clone();
        cx.draw(
            gpui::point(px(0.), px(0.)),
            gpui::AvailableSpace::min_size(),
            move |_, _| settled_state.into_any_element(),
        );
        let after_first_draw = renders.get();
        cx.draw(
            gpui::point(px(0.), px(0.)),
            gpui::AvailableSpace::min_size(),
            move |_, _| state.into_any_element(),
        );

        assert_eq!(renders.get() - after_first_draw, 2);
    }

    #[gpui::test]
    fn moving_past_the_visible_rows_scrolls_the_list(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(|state| {
                Command::new(state)
                    .items((0..50).map(|ix| CommandItem::new().label(format!("Item {ix}"))))
            }),
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));

        let state = cx.update(|_, cx| harness.read(cx).state.clone());
        assert_eq!(
            state.read_with(cx, |state, _| state.scroll_handle.base_handle().offset().y),
            px(0.),
        );

        // The list is capped well below 50 rows, so walking to the last one has
        // to bring the viewport with it.
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                for _ in 0..49 {
                    state.select_by(1, window, cx);
                }
            })
        });
        cx.update(|window, cx| _ = window.draw(cx));

        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(IndexPath::new(49).section(0))
        );
        assert!(
            state.read_with(cx, |state, _| state.scroll_handle.base_handle().offset().y) < px(0.),
            "selecting the last row should have scrolled the list",
        );
    }

    #[gpui::test]
    fn a_reinstalled_model_does_not_scroll_a_preserved_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (harness, cx) = cx.add_window_view(|window, cx| Harness {
            state: cx.new(|cx| CommandState::new(window, cx)),
            command: Rc::new(|state| {
                Command::new(state)
                    .items((0..50).map(|ix| CommandItem::new().label(format!("Item {ix}"))))
            }),
        });

        cx.run_until_parked();
        cx.update(|window, cx| _ = window.draw(cx));

        let state = cx.update(|_, cx| harness.read(cx).state.clone());

        // Hover selection does not scroll, and the host re-render it notifies
        // reinstalls the model with the selection preserved. That reinstall
        // must not scroll either, or the hover still moves the list one frame
        // later.
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.select(10, window, cx));
        });
        cx.update(|window, cx| _ = window.draw(cx));

        assert_eq!(
            state.read_with(cx, |state, _| state.scroll_handle.base_handle().offset().y),
            px(0.),
            "reinstalling the model must keep the scroll position",
        );
    }
}
