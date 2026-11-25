use std::ops::Range;

/// Delimiters inserted by the editor, retained across edits and history replay.
#[derive(Debug, Clone, Default)]
pub(crate) struct AutoClosedPairs {
    pairs: Vec<(Range<usize>, Range<usize>)>,
}

impl AutoClosedPairs {
    pub(crate) fn empty() -> &'static Self {
        static EMPTY: AutoClosedPairs = AutoClosedPairs { pairs: Vec::new() };
        &EMPTY
    }

    pub(crate) fn record(&mut self, open: Range<usize>, close: Range<usize>) {
        self.pairs.push((open, close));
    }

    pub(crate) fn contains(&self, open: Range<usize>, close: Range<usize>) -> bool {
        self.pairs
            .iter()
            .any(|(begin, end)| *begin == open && *end == close)
    }

    pub(crate) fn contains_closer(&self, cursor: usize, index: usize, len: usize) -> bool {
        self.pairs
            .iter()
            .any(|(_, close)| close.start + index == cursor && close.len() == len)
    }

    pub(crate) fn adjust(&mut self, edit: &Range<usize>, new_len: usize) {
        let delta = new_len as isize - edit.len() as isize;
        let shift = |range: &mut Range<usize>| {
            range.start = range.start.saturating_add_signed(delta);
            range.end = range.end.saturating_add_signed(delta);
        };
        self.pairs.retain_mut(|(open, close)| {
            if edit.end <= open.start {
                shift(open);
                shift(close);
            } else if edit.start >= open.end && edit.end <= close.start {
                shift(close);
            } else if edit.start < close.end {
                return false;
            }
            true
        });
    }
}
