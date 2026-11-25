/// A browser-style linear trail with a current entry.
///
/// Entries before the current one can be revisited with [`back`](Self::back),
/// and entries left behind by going back can be restored with
/// [`forward`](Self::forward). Pushing after going back starts a new branch
/// and drops the forward entries.
#[derive(Debug)]
pub struct History<T> {
    entries: Vec<T>,
    forward_entries: Vec<T>,
    max_entries: usize,
}

impl<T> History<T> {
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
            forward_entries: Vec::new(),
            max_entries: 1000,
        }
    }

    /// Sets the maximum number of root-to-current entries to keep, defaults to 1000.
    ///
    /// Lowering the limit immediately removes the oldest entries.
    pub fn max_entries(mut self, max_entries: usize) -> Self {
        self.max_entries = max_entries;
        self.enforce_max_entries();
        self
    }

    /// Pushes an entry and drops the forward branch.
    pub fn push(&mut self, entry: T) {
        self.forward_entries.clear();
        if self.max_entries == 0 {
            return;
        }
        self.entries.push(entry);
        self.enforce_max_entries();
    }

    /// Returns the current entry.
    pub fn current(&self) -> Option<&T> {
        self.entries.last()
    }

    /// Replaces the current entry, or pushes when the trail is empty.
    pub fn replace_current(&mut self, entry: T) {
        match self.entries.last_mut() {
            Some(current) => *current = entry,
            None => self.push(entry),
        }
    }

    /// Removes and returns the current entry without changing the forward branch.
    pub fn remove_current(&mut self) -> Option<T> {
        self.entries.pop()
    }

    /// Returns whether moving back would keep a root entry current.
    pub fn can_back(&self) -> bool {
        self.entries.len() > 1
    }

    /// Returns whether a forward entry is available.
    pub fn can_forward(&self) -> bool {
        !self.forward_entries.is_empty()
    }

    /// Moves back one entry and returns the new current entry.
    pub fn back(&mut self) -> Option<T>
    where
        T: Clone,
    {
        if self.entries.len() <= 1 {
            return None;
        }
        self.forward_entries.push(self.entries.pop().unwrap());
        self.current().cloned()
    }

    /// Moves forward one entry and returns the restored entry.
    pub fn forward(&mut self) -> Option<T>
    where
        T: Clone,
    {
        if self.max_entries == 0 {
            return None;
        }
        let entry = self.forward_entries.pop()?;
        self.entries.push(entry);
        self.enforce_max_entries();
        self.current().cloned()
    }

    /// Iterates from the root entry to the current entry.
    pub fn entries(&self) -> impl DoubleEndedIterator<Item = &T> + ExactSizeIterator {
        self.entries.iter()
    }

    /// Iterates from the nearest forward entry to the furthest.
    pub fn forward_entries(&self) -> impl DoubleEndedIterator<Item = &T> + ExactSizeIterator {
        self.forward_entries.iter().rev()
    }

    /// Keeps only entries accepted by `keep` on both sides of the current position.
    pub fn retain(&mut self, mut keep: impl FnMut(&T) -> bool) {
        self.entries.retain(&mut keep);
        self.forward_entries.retain(&mut keep);
    }

    /// Clears current, back, and forward entries.
    pub fn clear(&mut self) {
        self.entries.clear();
        self.forward_entries.clear();
    }

    fn enforce_max_entries(&mut self) {
        let excess = self.entries.len().saturating_sub(self.max_entries);
        if excess > 0 {
            self.entries.drain(..excess);
        }
    }
}

impl<T> Default for History<T> {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn navigation_moves_between_entries_without_backing_past_the_root() {
        let mut history = History::new().max_entries(3);
        history.push(1);
        history.push(2);
        history.push(3);

        assert_eq!(history.current(), Some(&3));
        assert_eq!(history.back(), Some(2));
        assert_eq!(history.back(), Some(1));
        assert_eq!(history.back(), None);
        assert_eq!(history.forward(), Some(2));
        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [1, 2]);
        assert_eq!(history.entries().rev().copied().collect::<Vec<_>>(), [2, 1]);
        assert_eq!(history.forward_entries().copied().collect::<Vec<_>>(), [3]);
        assert!(history.can_back());
        assert!(history.can_forward());
    }

    #[test]
    fn pushing_after_back_truncates_the_forward_branch() {
        let mut history = History::new();
        history.push(1);
        history.push(2);
        history.push(3);
        assert_eq!(history.back(), Some(2));

        history.push(4);

        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [1, 2, 4]);
        assert!(!history.can_forward());
        assert_eq!(history.forward(), None);
    }

    #[test]
    fn repeated_entries_preserve_every_navigation_step() {
        let mut history = History::new();
        history.push(1);
        history.push(2);
        history.push(1);

        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [1, 2, 1]);
        assert_eq!(history.back(), Some(2));
        assert_eq!(history.back(), Some(1));
    }

    #[test]
    fn max_entries_evicts_the_oldest_entry() {
        let mut history = History::new().max_entries(2);
        history.push(1);
        history.push(2);
        history.push(3);

        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [2, 3]);
        assert_eq!(history.back(), Some(2));
        assert_eq!(history.back(), None);
    }

    #[test]
    fn lowering_max_entries_truncates_populated_entries_and_caps_forward_restores() {
        let mut history = History::new();
        history.push(1);
        history.push(2);
        history.push(3);
        assert_eq!(history.back(), Some(2));

        history = history.max_entries(1);

        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [2]);
        assert_eq!(history.forward(), Some(3));
        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [3]);
        assert_eq!(history.back(), None);
    }

    #[test]
    fn zero_max_entries_retains_nothing() {
        let mut history = History::new().max_entries(0);
        history.push(1);

        assert_eq!(history.current(), None);
        assert_eq!(history.entries().len(), 0);
        assert!(!history.can_back());
        assert!(!history.can_forward());
    }

    #[test]
    fn replace_current_updates_in_place_and_pushes_when_empty() {
        let mut history = History::new();
        history.replace_current(1);
        history.push(2);
        history.replace_current(3);

        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [1, 3]);
    }

    #[test]
    fn remove_current_preserves_forward_entries() {
        let mut history = History::new();
        history.push(1);
        history.push(2);
        history.push(3);
        assert_eq!(history.back(), Some(2));

        assert_eq!(history.remove_current(), Some(2));

        assert_eq!(history.current(), Some(&1));
        assert_eq!(history.forward_entries().copied().collect::<Vec<_>>(), [3]);
        assert_eq!(history.forward(), Some(3));
    }

    #[test]
    fn retain_filters_back_and_forward_entries_without_reordering() {
        let mut history = History::new();
        for entry in 1..=8 {
            history.push(entry);
        }
        history.back();
        history.back();
        history.back();
        history.back();

        history.retain(|entry| entry % 2 == 0);

        assert_eq!(history.entries().copied().collect::<Vec<_>>(), [2, 4]);
        assert_eq!(
            history.forward_entries().copied().collect::<Vec<_>>(),
            [6, 8]
        );
        assert_eq!(history.forward(), Some(6));
        assert_eq!(history.forward(), Some(8));
    }

    #[test]
    fn clear_removes_back_and_forward_entries() {
        let mut history = History::new();
        history.push(1);
        history.push(2);
        history.back();

        history.clear();

        assert_eq!(history.current(), None);
        assert_eq!(history.entries().len(), 0);
        assert_eq!(history.forward_entries().len(), 0);
        assert!(!history.can_back());
        assert!(!history.can_forward());
    }
}
