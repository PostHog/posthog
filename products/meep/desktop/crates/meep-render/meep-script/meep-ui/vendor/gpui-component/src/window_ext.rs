use crate::root::WindowState;
use crate::{
    Placement,
    dialog::{AlertDialog, Dialog},
    input::AnyInputState,
    notification::Notification,
    sheet::Sheet,
};
use gpui::{App, ElementId, Entity, Window};
use std::rc::Rc;

/// Extension trait for [`Window`] to add dialog, sheet .. functionality.
pub trait WindowExt: Sized {
    /// Opens a Sheet at right placement.
    ///
    /// The builder follows the same rendering contract as
    /// [`WindowExt::open_dialog`]: it may run again when the sheet layer is
    /// rebuilt. Keep it cheap and create persistent entities before opening,
    /// not inside the builder.
    fn open_sheet<F>(&mut self, cx: &mut App, build: F)
    where
        F: Fn(Sheet, &mut Window, &mut App) -> Sheet + 'static;

    /// Opens a Sheet at the given placement.
    ///
    /// The builder follows the same rendering contract as
    /// [`WindowExt::open_dialog`]: it may run again when the sheet layer is
    /// rebuilt. Keep it cheap and create persistent entities before opening,
    /// not inside the builder.
    fn open_sheet_at<F>(&mut self, placement: Placement, cx: &mut App, build: F)
    where
        F: Fn(Sheet, &mut Window, &mut App) -> Sheet + 'static;

    /// Return true, if there is an active Sheet.
    fn has_active_sheet(&mut self, cx: &mut App) -> bool;

    /// Closes the active Sheet.
    fn close_sheet(&mut self, cx: &mut App);

    /// Opens a Dialog.
    ///
    /// The builder is a render closure, not a one-shot constructor. It may
    /// run again when the dialog layer is rebuilt while the dialog is open.
    /// View caching means a displayed frame need not rebuild the layer; the
    /// builder is not a periodic update callback. Keep it cheap and idempotent.
    ///
    /// Create persistent entities, such as an [`InputState`](crate::input::InputState)
    /// or a child view, before opening and capture their handles in the builder.
    /// Creating them with `cx.new(...)` inside the builder replaces them on
    /// each rebuild and loses their editing state.
    ///
    /// `open_dialog` initially focuses the dialog shell, replacing any focus
    /// set before the call. To choose initial content focus, set it only on
    /// the builder's first invocation, with a guard captured separately for
    /// each opening. Never focus unconditionally on subsequent rebuilds: that
    /// would steal focus from another control or a nested dialog.
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use std::cell::Cell;
    /// use gpui_kit::{AppContext as _, Focusable as _};
    /// use gpui_kit::component::{WindowExt as _, input::{Input, InputState}};
    ///
    /// // Both the input and the one-time focus guard belong to this opening.
    /// let input = cx.new(|cx| InputState::new(window, cx).placeholder("URL"));
    /// let initial_focus = Cell::new(true);
    /// window.open_dialog(cx, move |dialog, window, cx| {
    ///     if initial_focus.replace(false) {
    ///         input.focus_handle(cx).focus(window, cx);
    ///     }
    ///     dialog.title("Import").child(Input::new(&input))
    /// });
    /// ```
    fn open_dialog<F>(&mut self, cx: &mut App, build: F)
    where
        F: Fn(Dialog, &mut Window, &mut App) -> Dialog + 'static;

    /// Opens an AlertDialog.
    ///
    /// This is a convenience method for opening an alert dialog with opinionated defaults.
    /// The footer buttons are center-aligned and include an icon based on the variant.
    ///
    /// The builder follows the same rendering contract as
    /// [`WindowExt::open_dialog`]: it may run again when the dialog layer is
    /// rebuilt. Keep it cheap and create persistent entities before opening,
    /// not inside the builder.
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use gpui_kit::component::{AlertDialog, alert::AlertVariant};
    ///
    /// window.open_alert_dialog(cx, |alert, _, _| {
    ///     alert.warning()
    ///         .title("Unsaved Changes")
    ///         .description("You have unsaved changes. Are you sure you want to leave?")
    ///         .show_cancel(true)
    /// });
    /// ```
    fn open_alert_dialog<F>(&mut self, cx: &mut App, build: F)
    where
        F: Fn(AlertDialog, &mut Window, &mut App) -> AlertDialog + 'static;

    /// Return true, if there is an active Dialog.
    ///
    /// A dialog that is playing its exit transition is no longer active: it
    /// accepts no input and will unmount when the transition finishes.
    fn has_active_dialog(&mut self, cx: &mut App) -> bool;

    /// Closes the last active Dialog.
    fn close_dialog(&mut self, cx: &mut App);

    /// Closes all active Dialogs.
    fn close_all_dialogs(&mut self, cx: &mut App);

    /// Pushes a notification to the notification list.
    fn push_notification(&mut self, note: impl Into<Notification>, cx: &mut App);

    /// Removes all notifications whose id matches `T`, including ones registered with
    /// either `Notification::id` or `Notification::id1` (any key).
    fn remove_notification<T: Sized + 'static>(&mut self, cx: &mut App);

    /// Removes a single notification matching the given type `T` and `key` (paired with `Notification::id1`).
    fn remove_notification1<T: Sized + 'static>(&mut self, key: impl Into<ElementId>, cx: &mut App);

    /// Clears all notifications.
    fn clear_notifications(&mut self, cx: &mut App);

    /// Returns number of notifications.
    fn notifications(&mut self, cx: &mut App) -> Rc<Vec<Entity<Notification>>>;

    /// Return the currently focused input state.
    ///
    /// Covers `Input`, `Textarea`, `Editor` and `OtpInput`, use
    /// [`AnyInputState::as_input`] and friends to get the concrete state.
    /// A registration whose focus handle is no longer focused (e.g. the input
    /// was removed from the tree while focused) is treated as `None`.
    fn focused_input(&mut self, cx: &mut App) -> Option<AnyInputState>;
    /// Returns true if there is a focused Input entity.
    fn has_focused_input(&mut self, cx: &mut App) -> bool;
}

impl WindowExt for Window {
    #[inline]
    fn open_sheet<F>(&mut self, cx: &mut App, build: F)
    where
        F: Fn(Sheet, &mut Window, &mut App) -> Sheet + 'static,
    {
        self.open_sheet_at(Placement::Right, cx, build)
    }

    #[inline]
    fn open_sheet_at<F>(&mut self, placement: Placement, cx: &mut App, build: F)
    where
        F: Fn(Sheet, &mut Window, &mut App) -> Sheet + 'static,
    {
        WindowState::update(self, cx, move |root, window, cx| {
            root.open_sheet_at(placement, build, window, cx);
        })
    }

    #[inline]
    fn has_active_sheet(&mut self, cx: &mut App) -> bool {
        WindowState::read(self, cx).active_sheet.is_some()
    }

    #[inline]
    fn close_sheet(&mut self, cx: &mut App) {
        WindowState::update(self, cx, |root, window, cx| {
            root.close_sheet(window, cx);
        })
    }

    #[inline]
    fn open_dialog<F>(&mut self, cx: &mut App, build: F)
    where
        F: Fn(Dialog, &mut Window, &mut App) -> Dialog + 'static,
    {
        WindowState::update(self, cx, move |root, window, cx| {
            root.open_dialog(build, window, cx);
        })
    }

    #[inline]
    fn open_alert_dialog<F>(&mut self, cx: &mut App, build: F)
    where
        F: Fn(AlertDialog, &mut Window, &mut App) -> AlertDialog + 'static,
    {
        self.open_dialog(cx, move |_, window, cx| {
            build(AlertDialog::new(cx), window, cx).build_surface(window, cx)
        })
    }

    #[inline]
    fn has_active_dialog(&mut self, cx: &mut App) -> bool {
        WindowState::read(self, cx)
            .active_dialogs
            .iter()
            .any(|dialog| !dialog.closing)
    }

    #[inline]
    fn close_dialog(&mut self, cx: &mut App) {
        WindowState::update(self, cx, |root, window, cx| {
            root.close_dialog(window, cx);
        })
    }

    #[inline]
    fn close_all_dialogs(&mut self, cx: &mut App) {
        WindowState::update(self, cx, |root, window, cx| {
            root.close_all_dialogs(window, cx);
        })
    }

    #[inline]
    fn push_notification(&mut self, note: impl Into<Notification>, cx: &mut App) {
        let note = note.into();
        WindowState::update(self, cx, |root, window, cx| {
            root.push_notification(note, window, cx);
        })
    }

    #[inline]
    fn remove_notification<T: Sized + 'static>(&mut self, cx: &mut App) {
        WindowState::update(self, cx, |root, window, cx| {
            root.remove_notification::<T>(window, cx);
        })
    }

    #[inline]
    fn remove_notification1<T: Sized + 'static>(
        &mut self,
        key: impl Into<ElementId>,
        cx: &mut App,
    ) {
        let key = key.into();
        WindowState::update(self, cx, |root, window, cx| {
            root.remove_notification1::<T>(key, window, cx);
        })
    }

    #[inline]
    fn clear_notifications(&mut self, cx: &mut App) {
        WindowState::update(self, cx, |root, window, cx| {
            root.clear_notifications(window, cx);
        })
    }

    #[inline]
    fn notifications(&mut self, cx: &mut App) -> Rc<Vec<Entity<Notification>>> {
        Rc::new(
            WindowState::read(self, cx)
                .notification
                .read(cx)
                .notifications(),
        )
    }

    #[inline]
    fn has_focused_input(&mut self, cx: &mut App) -> bool {
        self.focused_input(cx).is_some()
    }

    fn focused_input(&mut self, cx: &mut App) -> Option<AnyInputState> {
        let state = WindowState::read(self, cx).focused_input.clone()?;
        if state.focus_handle(cx).is_focused(self) {
            return Some(state);
        }

        // An input removed from the tree while focused never re-renders to
        // unregister itself; drop the stale registration lazily.
        WindowState::try_update(self, cx, |root, _, cx| {
            if root.focused_input.as_ref() == Some(&state) {
                root.focused_input = None;
                cx.notify();
            }
        });
        None
    }
}
