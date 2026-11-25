use gpui::{AnyElement, App, IntoElement, SharedString, Task, Window};

use crate::IndexPath;

use super::change::SearchableListChange;

/// An item that can appear in a searchable list (Select, ComboBox).
pub trait SearchableListItem: Clone {
    type Value: Clone + PartialEq;

    /// Short display label shown in the dropdown row and in the trigger by default.
    ///
    /// This is also what assistive technology reads as the committed value, so
    /// it has to stand on its own as text even when [`Self::display_title`]
    /// draws something richer.
    fn title(&self) -> SharedString;

    /// Override the trigger display element (e.g. "Country (US)" instead of just "United States").
    ///
    /// Returns `None` to fall back to `title()`.
    ///
    /// This is presentation only. An element is not text, so the accessible
    /// value keeps reporting [`Self::title`]; if the two would read
    /// differently, put the meaning a listener needs in `title()`.
    fn display_title(&self) -> Option<AnyElement> {
        None
    }

    /// Render this item's row content inside the dropdown.
    ///
    /// Override to add icons, avatars, secondary text, etc.
    /// The default renders `title()`.
    fn render(&self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.title()
    }

    /// The value that identifies this item.
    fn value(&self) -> &Self::Value;

    /// Whether this item matches the search query.
    ///
    /// Defaults to case-insensitive substring match on `title()`.
    fn matches(&self, query: &str) -> bool {
        self.title().to_lowercase().contains(&query.to_lowercase())
    }

    /// Whether this item should be shown as non-interactive (grayed-out, unclickable).
    fn disabled(&self) -> bool {
        false
    }
}

/// Provides data and search behaviour to a searchable list component.
pub trait SearchableListDelegate: Sized + 'static {
    type Item: SearchableListItem;

    /// Number of sections (groups) in the list.  Defaults to 1.
    fn sections_count(&self, _: &App) -> usize {
        1
    }

    /// Optional header element for the given section index.
    ///
    /// Deprecated: override [`render_section_header`] instead (provides `Window` + `App` access).
    #[deprecated]
    fn section(&self, _section: usize) -> Option<AnyElement> {
        None
    }

    /// Number of items in the given section.
    fn items_count(&self, section: usize) -> usize;

    /// Return a reference to the item at the given index path.
    fn item(&self, ix: IndexPath) -> Option<&Self::Item>;

    /// Find the index path of the item whose value equals `value`.
    fn position<V>(&self, _value: &V) -> Option<IndexPath>
    where
        Self::Item: SearchableListItem<Value = V>,
        V: PartialEq;

    /// Called when the search query changes.
    ///
    /// Implementations should filter or fetch items and may return an async `Task`.
    /// The `App` context allows spawning background work.
    fn perform_search(&mut self, _query: &str, _window: &mut Window, _cx: &mut App) -> Task<()> {
        Task::ready(())
    }

    // MARK: Rendering hooks

    /// Override the row content for the item at `ix`.
    ///
    /// When `Some(_)` is returned, the adapter suppresses its default `SearchableListItemElement`
    /// layout (including the automatic trailing check icon) — the returned element is rendered
    /// as-is. Return `None` to fall back to the standard rendering.
    ///
    /// `checked` is `true` when the item is in the current selection (as determined by
    /// `is_item_checked`), letting custom renderers show their own selection indicator.
    ///
    /// Replaces the `item_renderer` closure that was previously set on `SearchableListAdapter`.
    fn render_item(
        &self,
        _ix: IndexPath,
        _item: &Self::Item,
        _checked: bool,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Option<AnyElement> {
        None
    }

    /// Render the header element for the given section (full render access).
    ///
    /// When `Some(_)` is returned, it is rendered directly — the adapter's default div wrapper
    /// (padding, muted colour) is bypassed. Return `None` to fall back to the deprecated
    /// `section()` wrapped in the standard div (no visual change for existing delegates).
    fn render_section_header(
        &self,
        _section: usize,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Option<AnyElement> {
        None
    }

    // MARK: Item state hooks

    /// Whether the item at `ix` should be rendered as interactive.
    ///
    /// Default: `!item.disabled()`.
    fn is_item_enabled(&self, _ix: IndexPath, item: &Self::Item, _cx: &App) -> bool {
        !item.disabled()
    }

    /// Whether the item at `ix` should show a checkmark.
    ///
    /// `current_selection` is the slice of currently selected `(IndexPath, Item)` pairs.
    ///
    /// Default: checks whether the item's value is present in `current_selection`.
    fn is_item_checked(
        &self,
        _ix: IndexPath,
        item: &Self::Item,
        current_selection: &[(IndexPath, Self::Item)],
        _cx: &App,
    ) -> bool {
        current_selection
            .iter()
            .any(|(_, selected_item)| selected_item.value() == item.value())
    }

    // MARK: Lifecycle / selection hooks

    /// Called before a user-triggered selection change is committed.
    ///
    /// `selection` is the live selection vec — the delegate may freely mutate it: add items,
    /// remove items, reorder, or leave it unchanged to effectively veto the operation.
    ///
    /// `changes` is the slice of atomic changes the mode-strategy computed (e.g. Single
    /// replacement deselects all then selects one; Multi toggles the clicked item). The delegate
    /// is not required to apply them — they are informational. The default implementation applies
    /// every change in order.
    ///
    /// No `cx` is available: this hook runs synchronously during the item-click handler while
    /// the list entity is mutably borrowed. Side effects that need cx belong in `on_confirm`.
    fn on_will_change(
        &mut self,
        selection: &mut Vec<(IndexPath, Self::Item)>,
        changes: &[SearchableListChange],
    ) {
        for change in changes {
            match change {
                SearchableListChange::Select { index } => {
                    let Some(item) = self.item(*index) else {
                        continue;
                    };

                    if !selection
                        .iter()
                        .any(|(_, selected_item)| selected_item.value() == item.value())
                    {
                        selection.push((*index, item.clone()));
                    }
                }
                SearchableListChange::Deselect { index } => {
                    if let Some(item) = self.item(*index) {
                        let has_value = selection
                            .iter()
                            .any(|(_, selected_item)| selected_item.value() == item.value());

                        if has_value {
                            selection
                                .retain(|(_, selected_item)| selected_item.value() != item.value());
                            continue;
                        }
                    }

                    selection.retain(|(selected_ix, _)| selected_ix != index);
                }
            }
        }
    }

    /// Called when the dropdown/popover is committed (Escape, `close_on_select`, or explicit
    /// confirm). `final_selection` is the selection after the last committed change.
    fn on_confirm(&mut self, _final_selection: &[(IndexPath, Self::Item)]) {}
}
