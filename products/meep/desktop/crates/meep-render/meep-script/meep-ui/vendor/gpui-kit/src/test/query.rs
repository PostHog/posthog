use super::{ElementSnapshot, ScopedWindow, observation};
use crate::{ElementId, Role, Window};

/// Queries native accessibility properties from the last completed frame.
/// Labels are exact accessible names, not rendered text. Only observed
/// elements are returned, including registered elements outside the visible area.
pub trait TestQueryExt {
    /// Lists observed elements by bounds origin (y, then x), with path order for ties.
    fn elements(&self) -> Vec<ElementSnapshot>;
    /// Requires one element with this accessible label; missing or ambiguous labels panic.
    fn find_by_label(&self, label: &str) -> ElementSnapshot;
    /// Returns `None` when absent; ambiguous labels panic with their matching paths.
    fn try_find_by_label(&self, label: &str) -> Option<ElementSnapshot>;
    /// Returns every exact accessible-label match in the same order as `elements`.
    fn find_all_by_label(&self, label: &str) -> Vec<ElementSnapshot>;
    /// Returns every native accessibility-role match in the same order as `elements`.
    fn find_all_by_role(&self, role: Role) -> Vec<ElementSnapshot>;
}

fn elements(window: &Window, scope: &[ElementId]) -> Vec<ElementSnapshot> {
    let mut elements: Vec<_> = observation::snapshots(window)
        .into_iter()
        .filter(|element| element.path().starts_with(scope) && element.path().len() > scope.len())
        .collect();
    elements.sort_by_cached_key(|element| {
        (
            element.bounds().origin.y,
            element.bounds().origin.x,
            format!("{:?}", element.path()),
        )
    });
    elements
}

fn by_label(window: &Window, scope: &[ElementId], label: &str) -> Vec<ElementSnapshot> {
    elements(window, scope)
        .into_iter()
        .filter(|element| element.label() == Some(label))
        .collect()
}

fn unique_label(window: &Window, scope: &[ElementId], label: &str) -> Option<ElementSnapshot> {
    let mut matches = by_label(window, scope, label);
    assert!(
        matches.len() <= 1,
        "ambiguous accessible label {label:?} in scope {scope:?}. Matching paths: {:?}",
        matches
            .iter()
            .map(ElementSnapshot::path)
            .collect::<Vec<_>>()
    );
    matches.pop()
}

fn require_label(window: &Window, scope: &[ElementId], label: &str) -> ElementSnapshot {
    unique_label(window, scope, label).unwrap_or_else(|| {
        panic!(
            "missing accessible label {label:?} in scope {scope:?}. Registered paths: {}. Check the accessible label, observation, and completed frame.",
            observation::registered_paths(window)
        )
    })
}

impl TestQueryExt for Window {
    fn elements(&self) -> Vec<ElementSnapshot> {
        elements(self, &[])
    }
    fn find_by_label(&self, label: &str) -> ElementSnapshot {
        require_label(self, &[], label)
    }
    fn try_find_by_label(&self, label: &str) -> Option<ElementSnapshot> {
        unique_label(self, &[], label)
    }
    fn find_all_by_label(&self, label: &str) -> Vec<ElementSnapshot> {
        by_label(self, &[], label)
    }
    fn find_all_by_role(&self, role: Role) -> Vec<ElementSnapshot> {
        self.elements()
            .into_iter()
            .filter(|element| element.role() == Some(role))
            .collect()
    }
}

impl ScopedWindow<'_> {
    /// Lists strict observed descendants by bounds origin, with path order for ties.
    pub fn elements(&self) -> Vec<ElementSnapshot> {
        elements(self.window, &self.scope)
    }
    /// Requires one descendant with this exact accessible label.
    pub fn find_by_label(&self, label: &str) -> ElementSnapshot {
        require_label(self.window, &self.scope, label)
    }
    /// Returns `None` when absent; ambiguous descendant labels panic.
    pub fn try_find_by_label(&self, label: &str) -> Option<ElementSnapshot> {
        unique_label(self.window, &self.scope, label)
    }
    /// Returns every descendant with this exact accessible label, including invisible ones.
    pub fn find_all_by_label(&self, label: &str) -> Vec<ElementSnapshot> {
        by_label(self.window, &self.scope, label)
    }
    /// Returns every descendant with this native accessibility role.
    pub fn find_all_by_role(&self, role: Role) -> Vec<ElementSnapshot> {
        self.elements()
            .into_iter()
            .filter(|element| element.role() == Some(role))
            .collect()
    }
}
