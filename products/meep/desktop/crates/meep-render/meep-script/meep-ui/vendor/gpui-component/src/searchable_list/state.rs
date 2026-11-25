use gpui::{
    AnyElement, App, AppContext as _, Bounds, Context, Entity, FocusHandle, Focusable as _, Length,
    Pixels, StyleRefinement, Subscription, Window,
};

use gpui_base::DeferredPopover;

use crate::{IndexPath, Size, list::ListState, searchable_list::adapter::SearchableListAdapter};

use super::delegate::{SearchableListDelegate, SearchableListItem};

/// Shared infrastructure for all searchable-list-based components (`SelectState`, `ComboBoxState`).
///
/// This struct is a plain nested value inside a GPUI entity — it has no entity context of its
/// own and cannot call `cx.notify()` or `cx.emit()`. Callers are responsible for those after
/// calling mutable methods.
pub struct SearchableListState<D: SearchableListDelegate + 'static>
where
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    pub focus_handle: FocusHandle,
    pub(crate) list: Entity<ListState<SearchableListAdapter<D>>>,
    pub(crate) selection: Vec<(IndexPath, D::Item)>,
    pub(crate) open: bool,
    /// Held while the popup is open, so that a component dropped without
    /// closing it first takes its registration with it.
    pub(crate) deferred_context: Option<DeferredPopover>,
    pub(crate) bounds: Bounds<Pixels>,

    // Shared options
    pub(crate) size: Size,
    pub(crate) style: StyleRefinement,
    pub(crate) cleanable: bool,
    pub(crate) placeholder: Option<gpui::SharedString>,
    pub(crate) search_placeholder: Option<gpui::SharedString>,
    pub(crate) menu_width: Length,
    pub(crate) menu_max_h: Length,
    pub(crate) scroll_bounce: Option<bool>,
    pub(crate) disabled: bool,
    pub(crate) appearance: bool,
    pub(crate) empty: Option<Box<dyn Fn(&mut Window, &App) -> AnyElement + 'static>>,

    pub(crate) _subscriptions: Vec<Subscription>,
}

#[allow(private_bounds)]
impl<D: SearchableListDelegate + 'static> SearchableListState<D>
where
    <D::Item as SearchableListItem>::Value: PartialEq + Clone,
{
    /// Create a new `SearchableListState`, creating the list entity in the given parent context.
    ///
    /// `on_confirm`, `on_cancel`, and `on_render_empty` are forwarded to the underlying adapter.
    /// `on_blur` is a function pointer invoked on the parent entity when focus leaves any of the
    /// list's focus handles.
    #[allow(clippy::too_many_arguments)]
    pub fn new<P: 'static>(
        delegate: D,
        selected_indices: Vec<IndexPath>,
        on_confirm: impl Fn(
            Option<IndexPath>,
            bool,
            &mut Window,
            &mut Context<ListState<SearchableListAdapter<D>>>,
        ) + 'static,
        on_cancel: impl Fn(
            Option<IndexPath>,
            &mut Window,
            &mut Context<ListState<SearchableListAdapter<D>>>,
        ) + 'static,
        on_render_empty: impl Fn(&mut Window, &mut App) -> AnyElement + 'static,
        on_blur: fn(&mut P, &mut Window, &mut Context<P>),
        window: &mut Window,
        cx: &mut Context<P>,
    ) -> Self {
        let focus_handle = cx.focus_handle();

        let adapter = SearchableListAdapter::new(delegate, on_confirm, on_cancel, on_render_empty);
        let list = cx.new(|cx| ListState::new(adapter, window, cx).reset_on_cancel(false));

        let list_focus_handle = list.read(cx).focus_handle.clone();
        let list_search_focus_handle = list.read(cx).query_input.focus_handle(cx);

        let selection = {
            let delegate = &list.read(cx).delegate().delegate;

            selected_indices
                .iter()
                .copied()
                .filter_map(|ix| delegate.item(ix).map(|i| (ix, i.clone())))
                .collect::<Vec<_>>()
        };

        if let Some(cursor) = selected_indices.first().copied() {
            list.update(cx, |l, cx| {
                l.set_selected_index(Some(cursor), window, cx);
            });
        }

        // Prime the adapter's snapshot so the very first render pass sees correct check state.
        let initial_snapshot = selection.clone();
        list.update(cx, |l, _| {
            l.delegate_mut().update_selection_snapshot(initial_snapshot);
        });

        let _subscriptions = vec![
            cx.on_blur(&list_focus_handle, window, on_blur),
            cx.on_blur(&list_search_focus_handle, window, on_blur),
            cx.on_blur(&focus_handle, window, on_blur),
        ];

        Self {
            focus_handle,
            list,
            selection,
            open: false,
            deferred_context: None,
            bounds: Bounds::default(),
            size: Size::default(),
            style: StyleRefinement::default(),
            cleanable: false,
            placeholder: None,
            search_placeholder: None,
            menu_width: Length::Auto,
            menu_max_h: gpui::rems(20.).into(),
            scroll_bounce: None,
            disabled: false,
            appearance: true,
            empty: None,
            _subscriptions,
        }
    }

    // MARK: Read-only accessors

    pub fn selection(&self) -> &[(IndexPath, D::Item)] {
        &self.selection
    }

    pub fn selected_values(&self) -> Vec<<D::Item as SearchableListItem>::Value> {
        self.selection
            .iter()
            .map(|(_ix, i)| i.value().clone())
            .collect()
    }

    pub fn is_open(&self) -> bool {
        self.open
    }

    pub fn focus_handle(&self) -> &FocusHandle {
        &self.focus_handle
    }

    /// Drop the search query, if there is one, so that a value lookup resolves
    /// against every item rather than the filtered view.
    ///
    /// A delegate's `position` answers for the list as it is currently
    /// displayed, which is what a click or a keyboard cursor needs. Projecting
    /// an authoritative value in from outside is not a position in that view:
    /// the value's item may be filtered out, and dropping it would let whatever
    /// the user last typed decide which values can be selected at all.
    ///
    /// Search runs synchronously for a delegate holding its own items, so a
    /// lookup right after this call sees the full set. One that fetches its
    /// items cannot answer for a value it has not fetched, and this cannot make
    /// it.
    pub(crate) fn clear_query(&mut self, window: &mut Window, cx: &mut App) {
        self.list.update(cx, |list, cx| {
            if !list.query_input.read(cx).value().is_empty() {
                list.set_query("", window, cx);
            }
        });
    }

    // MARK: Mutation (no cx — callers emit events and notify)

    /// Add an index+item pair to the selection; no-op if already present.
    pub(crate) fn add_by_item(&mut self, index: IndexPath, item: D::Item) {
        if self.selection.iter().any(|(ix, _)| ix == &index) {
            return;
        }

        self.selection.push((index, item));
    }

    /// Remove an index from the selection by index path.
    pub(crate) fn remove_by_index(&mut self, index: &IndexPath) -> bool {
        if let Some(pos) = self.selection.iter().position(|(ix, _)| ix == index) {
            self.selection.remove(pos);

            return true;
        }

        false
    }

    /// Add a single index to the selection by looking up the item in the list.
    ///
    /// Requires `cx` only to read the list entity; does not notify.
    pub fn add_selected_index(&mut self, index: IndexPath, cx: &App) -> bool {
        if self.selection.iter().any(|(ix, _)| ix == &index) {
            return false;
        }

        let Some(item) = self.list.read(cx).delegate().delegate.item(index) else {
            return false;
        };

        self.add_by_item(index, item.clone());

        true
    }

    /// Remove a single index from the selection.
    pub fn remove_selected_index(&mut self, index: IndexPath) -> bool {
        self.remove_by_index(&index)
    }

    /// Replace the entire selection, looking up items from the list.
    pub fn set_selected_indices(&mut self, indices: impl IntoIterator<Item = IndexPath>, cx: &App) {
        let indices: Vec<IndexPath> = indices.into_iter().collect();

        self.selection = indices
            .into_iter()
            .filter_map(|ix| {
                self.list
                    .read(cx)
                    .delegate()
                    .delegate
                    .item(ix)
                    .map(|i| (ix, i.clone()))
            })
            .collect();
    }

    /// Push the current selection into the adapter's snapshot so the next render pass sees
    /// up-to-date check state. Call after every mutation that changes `self.selection`.
    pub(crate) fn sync_snapshot<P: 'static>(&self, cx: &mut Context<P>) {
        let snapshot = self.selection.clone();
        self.list.update(cx, |l, _| {
            l.delegate_mut().update_selection_snapshot(snapshot);
        });
    }
}
