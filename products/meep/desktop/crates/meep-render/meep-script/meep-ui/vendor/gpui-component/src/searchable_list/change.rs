use crate::IndexPath;

/// A single, atomic selection change proposed by the mode-strategy for a user interaction.
///
/// Passed as a slice to [`SearchableListDelegate::on_will_change`], giving the delegate
/// a description of what the default strategy intends to do. The delegate may apply all,
/// some, or none of the changes by mutating the `selection` argument directly.
pub enum SearchableListChange {
    /// Select the item at the given index path.
    Select { index: IndexPath },
    /// Deselect the item at the given index path.
    Deselect { index: IndexPath },
}
