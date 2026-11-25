//! Common actions shared by keyboard-driven GPUI controls.

use gpui::{Action, actions};
use serde::Deserialize;

#[derive(Clone, Action, PartialEq, Eq, Deserialize)]
#[action(namespace = ui, no_json)]
pub struct Confirm {
    /// Whether the confirmation uses the secondary action.
    pub secondary: bool,
}

actions!(
    ui,
    [
        Cancel,
        SelectUp,
        SelectDown,
        SelectLeft,
        SelectRight,
        SelectFirst,
        SelectLast,
        SelectPrevColumn,
        SelectNextColumn,
        SelectPageUp,
        SelectPageDown
    ]
);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confirm_keeps_its_secondary_payload() {
        assert!(Confirm { secondary: true }.secondary);
        assert!(!Confirm { secondary: false }.secondary);
    }
}
