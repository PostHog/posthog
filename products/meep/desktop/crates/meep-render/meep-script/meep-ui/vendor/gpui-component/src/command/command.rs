use std::rc::Rc;

use gpui::{
    AnyElement, App, DefiniteLength, Entity, IntoElement, RenderOnce, SharedString,
    StyleRefinement, Styled, Window, rems,
};

use crate::IndexPath;
use crate::command::{
    item::{CommandEntry, CommandGroup, CommandItem},
    state::{CommandModel, CommandState, OnCancel, OnIndex, OnQuery},
};

pub(crate) type CommandSlot = dyn Fn(&CommandState, &mut Window, &mut App) -> AnyElement;

/// Presentation of a [`Command`], pushed into its state on every render.
#[derive(Clone)]
pub(crate) struct CommandOptions {
    pub(crate) style: StyleRefinement,
    pub(crate) placeholder: Option<SharedString>,
    pub(crate) empty: Option<Rc<CommandSlot>>,
    pub(crate) max_h: DefiniteLength,
    pub(crate) scroll_bounce: Option<bool>,
    pub(crate) bordered: bool,
    pub(crate) header: Option<Rc<CommandSlot>>,
    pub(crate) footer: Option<Rc<CommandSlot>>,
}

impl Default for CommandOptions {
    fn default() -> Self {
        Self {
            style: StyleRefinement::default(),
            placeholder: None,
            empty: None,
            max_h: rems(18.75).into(),
            scroll_bounce: None,
            bordered: true,
            header: None,
            footer: None,
        }
    }
}

/// A command palette: a search field over a filtered list of commands.
///
/// Entries and rendering policy are configured on each `Command`; interaction
/// state such as the query and highlighted item lives in [`CommandState`].
///
/// ```ignore
/// let state = cx.new(|cx| CommandState::new(window, cx));
///
/// Command::new(&state)
///     .group(
///         CommandGroup::new().label("Suggestions")
///             .item(CommandItem::new().label("Calendar").icon(IconName::Calendar)),
///     )
///     .placeholder("Type a command or search...")
/// ```
#[derive(IntoElement)]
pub struct Command {
    state: Entity<CommandState>,
    entries: Vec<CommandEntry>,
    searchable: bool,
    filterable: bool,
    on_query: Option<Rc<OnQuery>>,
    on_select: Option<Rc<OnIndex>>,
    on_confirm: Option<Rc<OnIndex>>,
    on_cancel: Option<Rc<OnCancel>>,
    options: CommandOptions,
}

impl Command {
    /// Render the palette held by `state`.
    pub fn new(state: &Entity<CommandState>) -> Self {
        Self {
            state: state.clone(),
            entries: Vec::new(),
            searchable: true,
            filterable: true,
            on_query: None,
            on_select: None,
            on_confirm: None,
            on_cancel: None,
            options: CommandOptions::default(),
        }
    }

    /// Add an ungrouped command item.
    pub fn item(mut self, item: CommandItem) -> Self {
        self.entries.push(CommandEntry::Item(item));
        self
    }

    /// Add multiple ungrouped command items.
    pub fn items(mut self, items: impl IntoIterator<Item = CommandItem>) -> Self {
        self.entries
            .extend(items.into_iter().map(CommandEntry::Item));
        self
    }

    /// Add a group of command items.
    pub fn group(mut self, group: CommandGroup) -> Self {
        self.entries.push(CommandEntry::Group(group));
        self
    }

    /// Add a separator between the preceding and following entries.
    pub fn separator(mut self) -> Self {
        self.entries.push(CommandEntry::Separator);
        self
    }

    /// Show or hide the query field and local filtering.
    pub fn searchable(mut self, searchable: bool) -> Self {
        self.searchable = searchable;
        self
    }

    /// Keep the query field but toggle the local filtering, default: `true`.
    ///
    /// Turn it off when an external source already answers the query, such as
    /// an async search: every supplied item stays visible, the query still
    /// reports through [`Self::on_query`], and a query change hands the
    /// highlight back to the first item instead of a local textual match.
    pub fn filterable(mut self, filterable: bool) -> Self {
        self.filterable = filterable;
        self
    }

    /// Run a callback after a searchable query actually changes and the
    /// current [`CommandState`] update releases its lease.
    pub fn on_query<F>(mut self, callback: F) -> Self
    where
        F: Fn(&str, &mut Window, &mut App) + 'static,
    {
        self.on_query = Some(Rc::new(callback));
        self
    }

    /// Run a callback after the highlighted item's original index path changes and the current
    /// [`CommandState`] update releases its lease.
    ///
    /// For [`Self::items`], `section` is 0 and `row` is the item's position in
    /// the supplied iterator. Explicit groups use their group and item
    /// positions and follow the implicit ungrouped section when both forms are
    /// mixed. Local filtering never changes these coordinates.
    pub fn on_select<F>(mut self, callback: F) -> Self
    where
        F: Fn(IndexPath, &mut Window, &mut App) + 'static,
    {
        self.on_select = Some(Rc::new(callback));
        self
    }

    /// Run a callback with the confirmed item's original index path after its Action is dispatched,
    /// provided the source window remains live. The callback runs after the
    /// current [`CommandState`] update releases its lease.
    /// The path follows the same input-model coordinates as [`Self::on_select`].
    pub fn on_confirm<F>(mut self, callback: F) -> Self
    where
        F: Fn(IndexPath, &mut Window, &mut App) + 'static,
    {
        self.on_confirm = Some(Rc::new(callback));
        self
    }

    /// Run a callback synchronously before an empty-query Cancel action
    /// propagates. A hosting Dialog should perform the dismissal after this
    /// callback instead of being closed by the callback itself.
    pub fn on_cancel<F>(mut self, callback: F) -> Self
    where
        F: Fn(&mut Window, &mut App) + 'static,
    {
        self.on_cancel = Some(Rc::new(callback));
        self
    }

    /// Set the placeholder of the search field.
    pub fn placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.options.placeholder = Some(placeholder.into());
        self
    }

    /// Render custom content when no command matches the query.
    pub fn empty<F, E>(mut self, f: F) -> Self
    where
        F: Fn(&CommandState, &mut Window, &mut App) -> E + 'static,
        E: IntoElement,
    {
        self.options.empty = Some(Rc::new(move |state, window, cx| {
            f(state, window, cx).into_any_element()
        }));
        self
    }

    /// Set the max height of the list, default: 18.75rem (300px).
    pub fn max_h(mut self, height: impl Into<DefiniteLength>) -> Self {
        self.options.max_h = height.into();
        self
    }

    /// Bounce the command list at its vertical boundaries. On by default on iOS,
    /// Android and macOS, off elsewhere; reduced motion disables displacement.
    pub fn scroll_bounce(mut self, enabled: bool) -> Self {
        self.options.scroll_bounce = Some(enabled);
        self
    }

    /// Set whether to draw the surrounding border and rounding, default: `true`.
    ///
    /// Turn it off when the palette already sits inside a frame of its own,
    /// such as a [`crate::Dialog`].
    pub fn bordered(mut self, bordered: bool) -> Self {
        self.options.bordered = bordered;
        self
    }

    /// Render a custom element above the search field and command list.
    pub fn header<F, E>(mut self, f: F) -> Self
    where
        F: Fn(&CommandState, &mut Window, &mut App) -> E + 'static,
        E: IntoElement,
    {
        self.options.header = Some(Rc::new(move |state, window, cx| {
            f(state, window, cx).into_any_element()
        }));
        self
    }

    /// Render a custom element below the command list.
    pub fn footer<F, E>(mut self, f: F) -> Self
    where
        F: Fn(&CommandState, &mut Window, &mut App) -> E + 'static,
        E: IntoElement,
    {
        self.options.footer = Some(Rc::new(move |state, window, cx| {
            f(state, window, cx).into_any_element()
        }));
        self
    }
}

impl Styled for Command {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.options.style
    }
}

impl RenderOnce for Command {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let options = self.options;
        let model = CommandModel {
            entries: self.entries,
            searchable: self.searchable,
            filterable: self.filterable,
            on_query: self.on_query,
            on_select: self.on_select,
            on_confirm: self.on_confirm,
            on_cancel: self.on_cancel,
        };
        self.state.update(cx, |state, cx| {
            state.set_options(options);
            state.install_model(model, cx);
        });

        self.state
    }
}
