use std::rc::Rc;

use gpui::{Action, AnyElement, App, IntoElement, SharedString, Window};

use crate::{Disableable, Icon};

/// A single command in a [`crate::command::Command`] palette.
///
pub struct CommandItem {
    label: Option<SharedString>,
    keywords: Vec<SharedString>,
    /// Boxed: an [`Icon`] carries a whole `StyleRefinement`, which would make
    /// every item — and so the palette's item vector — kilobytes wide.
    pub(crate) icon: Option<Box<Icon>>,
    pub(crate) action: Option<Box<dyn Action>>,
    pub(crate) checked: bool,
    disabled: bool,
    pub(crate) content: Option<Rc<CommandItemContent>>,
}

impl Clone for CommandItem {
    fn clone(&self) -> Self {
        Self {
            label: self.label.clone(),
            keywords: self.keywords.clone(),
            icon: self.icon.clone(),
            action: self.action.as_ref().map(|action| action.boxed_clone()),
            checked: self.checked,
            disabled: self.disabled,
            content: self.content.clone(),
        }
    }
}

impl CommandItem {
    /// Create an empty command item.
    pub fn new() -> Self {
        Self {
            label: None,
            keywords: Vec::new(),
            icon: None,
            action: None,
            checked: false,
            disabled: false,
            content: None,
        }
    }

    /// Set the label to display and search.
    pub fn label(mut self, label: impl Into<SharedString>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Set the leading icon.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.icon = Some(Box::new(icon.into()));
        self
    }

    /// Set the Action dispatched when this item is clicked or confirmed.
    ///
    /// The Action's active keybinding is also shown by the default row.
    pub fn action(mut self, action: Box<dyn Action>) -> Self {
        self.action = Some(action);
        self
    }

    /// Mark this item as the chosen one, drawing a check at the right end of
    /// the row.
    ///
    /// A resolved Action binding takes that slot, so an item with one shows no
    /// check.
    pub fn checked(mut self, checked: bool) -> Self {
        self.checked = checked;
        self
    }

    /// Add extra terms the search matches against, besides the label.
    pub fn keywords<I, S>(mut self, keywords: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<SharedString>,
    {
        self.keywords
            .extend(keywords.into_iter().map(|keyword| keyword.into()));
        self
    }

    /// Replace the row content (icon and label) with a lazily built child.
    ///
    /// The builder may run more than once for measurement and rendering, so it
    /// must be side-effect-free. Custom children own their complete visual
    /// presentation, including any keybinding hint.
    pub fn child<F, E>(mut self, builder: F) -> Self
    where
        F: Fn(&mut Window, &mut App) -> E + 'static,
        E: IntoElement,
    {
        self.content = Some(Rc::new(move |window, cx| {
            builder(window, cx).into_any_element()
        }));
        self
    }

    /// Whether this item is non-interactive.
    pub(crate) fn is_disabled(&self) -> bool {
        self.disabled
    }

    /// Whether this item matches the search query, ignoring case.
    ///
    /// An empty query matches everything.
    pub(crate) fn matches(&self, query: &str) -> bool {
        if query.is_empty() {
            return true;
        }

        let query = query.to_lowercase();

        self.label
            .as_ref()
            .is_some_and(|label| label.to_lowercase().contains(&query))
            || self
                .keywords
                .iter()
                .any(|keyword| keyword.to_lowercase().contains(&query))
    }

    pub(crate) fn label_text(&self) -> Option<&SharedString> {
        self.label.as_ref()
    }

    /// Whether `other` filters and measures exactly like this item, so a
    /// palette can keep its rows and row sizes when a host re-render rebuilds
    /// an unchanged model.
    ///
    /// An item with a custom child never counts as unchanged, even when it is
    /// a clone sharing the same closure: the child can read state outside the
    /// item, so only laying it out again tells whether its height changed.
    pub(crate) fn same_layout(&self, other: &Self) -> bool {
        self.content.is_none()
            && other.content.is_none()
            && self.label == other.label
            && self.keywords == other.keywords
            && match (&self.icon, &other.icon) {
                (Some(icon), Some(other)) => icon.same_layout(other),
                (None, None) => true,
                _ => false,
            }
            && self.checked == other.checked
            && self.disabled == other.disabled
            && match (&self.action, &other.action) {
                (Some(action), Some(other)) => action.partial_eq(other.as_ref()),
                (None, None) => true,
                _ => false,
            }
    }
}

impl Default for CommandItem {
    fn default() -> Self {
        Self::new()
    }
}

pub(crate) type CommandItemContent = dyn Fn(&mut Window, &mut App) -> AnyElement;

impl Disableable for CommandItem {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

/// A titled section of [`CommandItem`]s.
///
/// The heading is hidden while every item in the group is filtered out.
pub struct CommandGroup {
    heading: Option<SharedString>,
    pub(crate) items: Vec<CommandItem>,
}

impl Clone for CommandGroup {
    fn clone(&self) -> Self {
        Self {
            heading: self.heading.clone(),
            items: self.items.clone(),
        }
    }
}

impl CommandGroup {
    /// Create a new group without a label.
    pub fn new() -> Self {
        Self {
            heading: None,
            items: Vec::new(),
        }
    }

    /// Set the label displayed above the group's items.
    pub fn label(mut self, label: impl Into<SharedString>) -> Self {
        self.heading = Some(label.into());
        self
    }

    /// Add an item to the group.
    pub fn item(mut self, item: CommandItem) -> Self {
        self.items.push(item);
        self
    }

    /// Add multiple items to the group.
    pub fn items(mut self, items: impl IntoIterator<Item = CommandItem>) -> Self {
        self.items.extend(items);
        self
    }

    /// The heading of the group, when it has one.
    pub fn heading(&self) -> Option<&SharedString> {
        self.heading.as_ref()
    }

    fn same_layout(&self, other: &Self) -> bool {
        self.heading == other.heading
            && self.items.len() == other.items.len()
            && self
                .items
                .iter()
                .zip(&other.items)
                .all(|(item, other)| item.same_layout(other))
    }
}

/// A top-level entry in a [`crate::command::Command`].
pub enum CommandEntry {
    /// A single ungrouped item.
    Item(CommandItem),
    /// A titled group of items.
    Group(CommandGroup),
    /// A divider between groups.
    ///
    /// A separator that ends up leading, trailing, or next to another
    /// separator once the query has filtered the list is not rendered.
    Separator,
}

impl CommandEntry {
    /// Whether `other` produces the same rows and row sizes as this entry for
    /// any query. See [`CommandItem::same_layout`].
    pub(crate) fn same_layout(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Item(item), Self::Item(other)) => item.same_layout(other),
            (Self::Group(group), Self::Group(other)) => group.same_layout(other),
            (Self::Separator, Self::Separator) => true,
            _ => false,
        }
    }
}

impl Clone for CommandEntry {
    fn clone(&self) -> Self {
        match self {
            Self::Item(item) => Self::Item(item.clone()),
            Self::Group(group) => Self::Group(group.clone()),
            Self::Separator => Self::Separator,
        }
    }
}

impl From<CommandItem> for CommandEntry {
    fn from(item: CommandItem) -> Self {
        Self::Item(item)
    }
}

impl From<CommandGroup> for CommandEntry {
    fn from(group: CommandGroup) -> Self {
        Self::Group(group)
    }
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use gpui::{TestAppContext, actions, div};

    use super::*;

    actions!(command_item_test, [CloneAction]);

    #[gpui::test]
    fn cloned_entries_keep_actions_and_lazy_children_usable(cx: &mut TestAppContext) {
        let action_count = Rc::new(Cell::new(0));
        let child_count = Rc::new(Cell::new(0));
        let action_count_for_handler = action_count.clone();
        cx.update(|cx| {
            cx.on_action(move |_: &CloneAction, _| {
                action_count_for_handler.set(action_count_for_handler.get() + 1);
            });
        });

        let child_count_for_builder = child_count.clone();
        let entry = CommandEntry::Group(
            CommandGroup::new().label("Group").item(
                CommandItem::new()
                    .label("cloneable")
                    .action(Box::new(CloneAction))
                    .child(move |_, _| {
                        child_count_for_builder.set(child_count_for_builder.get() + 1);
                        div()
                    }),
            ),
        );
        let cloned = entry.clone();
        let CommandEntry::Group(group) = cloned else {
            panic!("the cloned entry should remain a group");
        };
        let cloned_item = group.items.into_iter().next().unwrap();

        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let child = cloned_item.content.as_ref().unwrap().clone();
            _ = child(window, cx);
            window.dispatch_action(cloned_item.action.as_ref().unwrap().boxed_clone(), cx);
        });

        assert_eq!(child_count.get(), 1);
        assert_eq!(action_count.get(), 1);
    }

    #[test]
    fn label_is_optional_for_custom_content() {
        assert_eq!(CommandItem::new().label_text(), None);
        assert_eq!(
            CommandItem::new().label("Calendar").label_text(),
            Some(&"Calendar".into())
        );
    }

    #[test]
    fn matches_label_and_keywords() {
        let item = CommandItem::new()
            .label("Profile")
            .keywords(["account", "user"]);

        assert!(item.matches(""));
        assert!(item.matches("PRO"));
        assert!(item.matches("Account"));
        assert!(!item.matches("billing"));
    }
}
