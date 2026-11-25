use instant::{Duration, Instant};

/// A history of grouped undo transactions.
#[derive(Debug)]
pub struct UndoHistory<T> {
    undos: Vec<Vec<T>>,
    redos: Vec<Vec<T>>,
    last_changed_at: Option<Instant>,
    max_undos: usize,
    group_interval: Option<Duration>,
    grouping: bool,
    ignoring: bool,
}

impl<T> UndoHistory<T> {
    pub fn new() -> Self {
        Self {
            undos: Vec::new(),
            redos: Vec::new(),
            last_changed_at: None,
            max_undos: 1000,
            group_interval: None,
            grouping: false,
            ignoring: false,
        }
    }

    /// Set the maximum number of undo transactions to keep, defaults to 1000.
    ///
    /// Lowering the limit immediately removes the oldest undo transactions.
    pub fn max_undos(mut self, max_undos: usize) -> Self {
        self.max_undos = max_undos;
        self.enforce_max_undos();
        self
    }

    /// Set the interval in which consecutive changes are grouped.
    ///
    /// A successful undo or redo ends timed grouping. Explicit grouping is
    /// independent and can still append to the current transaction.
    pub fn group_interval(mut self, group_interval: Duration) -> Self {
        self.group_interval = Some(group_interval);
        self
    }

    /// Start explicitly grouping pushed changes into one transaction.
    pub fn start_grouping(&mut self) {
        self.grouping = true;
    }

    /// End explicit grouping of pushed changes.
    pub fn end_grouping(&mut self) {
        self.grouping = false;
    }

    /// Returns whether history recording is currently ignored.
    pub fn is_ignoring(&self) -> bool {
        self.ignoring
    }

    /// Sets whether history recording is currently ignored.
    pub fn set_ignoring(&mut self, ignoring: bool) {
        self.ignoring = ignoring;
    }

    /// Pushes a change into the current transaction or starts a new one.
    pub fn push(&mut self, item: T) {
        if self.ignoring || self.max_undos == 0 {
            return;
        }

        let group_with_previous = self.grouping
            || self.last_changed_at.is_some_and(|last_changed_at| {
                self.group_interval
                    .is_some_and(|interval| last_changed_at.elapsed() <= interval)
            });

        if group_with_previous && !self.undos.is_empty() {
            self.undos.last_mut().unwrap().push(item);
        } else {
            self.undos.push(vec![item]);
            self.enforce_max_undos();
        }

        self.last_changed_at = Some(Instant::now());
        self.redos.clear();
    }

    /// Undoes the latest transaction, returning changes newest first.
    pub fn undo(&mut self) -> Option<Vec<T>>
    where
        T: Clone,
    {
        let transaction = self.undos.pop()?;
        let changes = transaction.iter().rev().cloned().collect();
        self.redos.push(transaction);
        self.last_changed_at = None;
        Some(changes)
    }

    /// Redoes the latest undone transaction, returning changes oldest first.
    pub fn redo(&mut self) -> Option<Vec<T>>
    where
        T: Clone,
    {
        if self.max_undos == 0 {
            return None;
        }
        let transaction = self.redos.pop()?;
        let changes = transaction.clone();
        self.undos.push(transaction);
        self.enforce_max_undos();
        self.last_changed_at = None;
        Some(changes)
    }

    /// Returns whether an undo transaction is available.
    pub fn can_undo(&self) -> bool {
        !self.undos.is_empty()
    }

    /// Returns whether a redo transaction is available.
    pub fn can_redo(&self) -> bool {
        !self.redos.is_empty()
    }

    /// Clears both undo and redo transactions.
    pub fn clear(&mut self) {
        self.undos.clear();
        self.redos.clear();
        self.last_changed_at = None;
    }

    fn enforce_max_undos(&mut self) {
        let excess = self.undos.len().saturating_sub(self.max_undos);
        if excess > 0 {
            self.undos.drain(..excess);
        }
    }
}

impl<T> Default for UndoHistory<T> {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use instant::Duration;

    use super::UndoHistory;

    #[test]
    fn explicit_grouping_undoes_newest_first_and_redoes_oldest_first() {
        let mut history = UndoHistory::new();
        history.start_grouping();
        history.push(1);
        history.push(2);
        history.push(3);
        history.end_grouping();

        assert_eq!(history.undo(), Some(vec![3, 2, 1]));
        assert_eq!(history.redo(), Some(vec![1, 2, 3]));
    }

    #[test]
    fn ungrouped_pushes_form_separate_transactions() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);

        assert_eq!(history.undo(), Some(vec![2]));
        assert_eq!(history.undo(), Some(vec![1]));
    }

    #[test]
    fn group_interval_combines_immediate_pushes() {
        let mut history = UndoHistory::new().group_interval(Duration::from_secs(60));
        history.push(1);
        history.push(2);

        assert_eq!(history.undo(), Some(vec![2, 1]));
    }

    #[test]
    fn undo_breaks_timed_grouping_across_the_branch_boundary() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);
        history = history.group_interval(Duration::from_secs(60));
        assert_eq!(history.undo(), Some(vec![2]));

        history.push(3);

        assert_eq!(history.undo(), Some(vec![3]));
        assert_eq!(history.undo(), Some(vec![1]));
    }

    #[test]
    fn redo_breaks_timed_grouping_across_the_branch_boundary() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);
        assert_eq!(history.undo(), Some(vec![2]));
        assert_eq!(history.redo(), Some(vec![2]));
        history = history.group_interval(Duration::from_secs(60));

        history.push(3);

        assert_eq!(history.undo(), Some(vec![3]));
        assert_eq!(history.undo(), Some(vec![2]));
        assert_eq!(history.undo(), Some(vec![1]));
    }

    #[test]
    fn explicit_grouping_still_appends_after_undo() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);
        assert_eq!(history.undo(), Some(vec![2]));

        history.start_grouping();
        history.push(3);
        history.end_grouping();

        assert_eq!(history.undo(), Some(vec![3, 1]));
    }

    #[test]
    fn a_new_push_clears_redo() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);
        assert_eq!(history.undo(), Some(vec![2]));

        history.push(3);

        assert!(!history.can_redo());
        assert_eq!(history.redo(), None);
    }

    #[test]
    fn ignoring_drops_pushes() {
        let mut history = UndoHistory::new();
        history.set_ignoring(true);
        history.push(1);

        assert!(history.is_ignoring());
        assert!(!history.can_undo());
        assert_eq!(history.undo(), None);
    }

    #[test]
    fn clear_clears_both_directions() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.undo();

        history.clear();

        assert!(!history.can_undo());
        assert!(!history.can_redo());
    }

    #[test]
    fn max_undos_evicts_the_oldest_transaction() {
        let mut history = UndoHistory::new().max_undos(2);
        history.push(1);
        history.push(2);
        history.push(3);

        assert_eq!(history.undo(), Some(vec![3]));
        assert_eq!(history.undo(), Some(vec![2]));
        assert_eq!(history.undo(), None);
    }

    #[test]
    fn lowering_max_undos_evicts_oldest_populated_transactions_immediately() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);
        history.push(3);

        history = history.max_undos(2);

        assert_eq!(history.undo(), Some(vec![3]));
        assert_eq!(history.undo(), Some(vec![2]));
        assert_eq!(history.undo(), None);
    }

    #[test]
    fn redo_after_lowering_max_undos_preserves_the_cap() {
        let mut history = UndoHistory::new();
        history.push(1);
        history.push(2);
        history.push(3);
        assert_eq!(history.undo(), Some(vec![3]));

        history = history.max_undos(1);
        assert_eq!(history.redo(), Some(vec![3]));

        assert_eq!(history.undo(), Some(vec![3]));
        assert_eq!(history.undo(), None);
    }

    #[test]
    fn redo_at_zero_max_undos_keeps_the_transaction_available() {
        let mut history = UndoHistory::new();
        history.push(1);
        assert_eq!(history.undo(), Some(vec![1]));

        history = history.max_undos(0);

        assert_eq!(history.redo(), None);
        assert!(history.can_redo());
        history = history.max_undos(1);
        assert_eq!(history.redo(), Some(vec![1]));
    }

    #[test]
    fn zero_max_undos_retains_no_transactions() {
        let mut history = UndoHistory::new().max_undos(0);
        history.push(1);

        assert!(!history.can_undo());
        assert_eq!(history.undo(), None);
    }
}
