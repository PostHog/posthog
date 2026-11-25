/// An element or component that exposes controlled selected state.
///
/// `selected` is the application's own meaning of selection: the current
/// view, the active item, the chosen option. `open` is a separate state a
/// popover, menu or dropdown puts on its trigger for as long as it is open.
/// The two coincide on a plain button, which paints both the same way, so
/// `open` falls back to `selected` by default and a trigger that only
/// implements `selected` keeps working unchanged. A trigger whose selection
/// means something else, such as a sidebar row that is selected when it is
/// the current view, overrides `open` and `is_open` to keep the two apart.
#[allow(patterns_in_fns_without_body)]
pub trait Selectable: Sized {
    fn selected(mut self, selected: bool) -> Self;
    fn is_selected(&self) -> bool;

    fn secondary_selected(self, _: bool) -> Self {
        self
    }

    /// Sets the open state a popover, menu or dropdown holds on its trigger
    /// while it is open.
    ///
    /// Defaults to `selected`, so a trigger only overrides this when its
    /// selected state means something other than "my popup is open".
    fn open(self, open: bool) -> Self {
        self.selected(open)
    }

    /// Whether the trigger is currently marked open.
    ///
    /// Defaults to `is_selected`, matching the default of [`Self::open`].
    fn is_open(&self) -> bool {
        self.is_selected()
    }
}

/// An element or component that can be disabled.
#[allow(patterns_in_fns_without_body)]
pub trait Disableable {
    fn disabled(mut self, disabled: bool) -> Self;
}

/// A component that exposes whether its UI layer should draw a focus ring.
///
/// This trait carries state only. Focus-ring geometry and presentation belong
/// to the component's visual layer.
pub trait FocusableExt: Sized {
    fn focus_ring(self, enabled: bool) -> Self;
    fn is_focus_ring_enabled(&self) -> bool;
}

/// An element or component that exposes collapsed state.
pub trait Collapsible {
    fn collapsed(self, collapsed: bool) -> Self;
    fn is_collapsed(&self) -> bool;
}

#[cfg(test)]
mod tests {
    use super::{FocusableExt, Selectable};

    struct CustomControl {
        focus_ring_enabled: bool,
    }

    /// A trigger that only knows about selection, the way every trigger did
    /// before `open` existed.
    struct SelectedOnlyTrigger {
        selected: bool,
    }

    impl Selectable for SelectedOnlyTrigger {
        fn selected(mut self, selected: bool) -> Self {
            self.selected = selected;
            self
        }

        fn is_selected(&self) -> bool {
            self.selected
        }
    }

    #[test]
    fn open_falls_back_to_selected_unless_overridden() {
        let trigger = SelectedOnlyTrigger { selected: false }.open(true);
        assert!(trigger.is_selected());
        assert!(trigger.is_open());

        let trigger = SelectedOnlyTrigger { selected: true }.open(false);
        assert!(!trigger.is_selected());
        assert!(!trigger.is_open());
    }

    impl FocusableExt for CustomControl {
        fn focus_ring(mut self, enabled: bool) -> Self {
            self.focus_ring_enabled = enabled;
            self
        }

        fn is_focus_ring_enabled(&self) -> bool {
            self.focus_ring_enabled
        }
    }

    #[test]
    fn focus_ring_api_carries_state_without_visuals() {
        let control = CustomControl {
            focus_ring_enabled: true,
        }
        .focus_ring(false);

        assert!(!control.is_focus_ring_enabled());
    }
}
