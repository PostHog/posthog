//! Crate-private plumbing behind [`editor_host`](super::editor_host).
//!
//! A text leaf whose [`InlineState`](super::inline::InlineState) carries an
//! `editor_key` reports its laid-out [`TextLayout`] to the sink installed for
//! the duration of `collect_leaf_geometry`, and takes extra range backgrounds
//! (the host's selection and decorations) from it. `TextView` never sets a key
//! or installs a sink, so read-only rendering is unchanged: outside a scope the
//! only cost is one thread-local read per laid-out text element.
//!
//! The sink is frame-local: it is written during prepaint and read by the
//! host afterwards; nothing here reaches back into an entity.

use std::{cell::RefCell, ops::Range, rc::Rc};

use gpui::{Bounds, Hsla, Pixels, TextLayout};

pub(crate) trait EditorSink {
    /// The leaf `key` was laid out this frame as one `TextLayout`.
    fn report(&self, key: u64, layout: &TextLayout);
    /// The leaf `key` is laid out in pieces this frame (a mixed text /
    /// image / custom-inline paragraph rendered by `InlineFlow`); drops
    /// pieces reported for it earlier in the frame.
    fn begin_pieces(&self, key: u64);
    /// One single-line text fragment of `key`, whose index 0 is the leaf's
    /// byte `start`.
    fn report_text_piece(&self, key: u64, start: usize, layout: &TextLayout);
    /// An inline atom (image, custom node) of `key` covering the leaf bytes
    /// `range`, drawn in `bounds`.
    fn report_box_piece(&self, key: u64, range: Range<usize>, bounds: Bounds<Pixels>);
    /// A line with no fragment (e.g. after a trailing hard break).
    fn report_empty_piece(&self, key: u64, start: usize, bounds: Bounds<Pixels>);
    /// Extra backgrounds to paint behind the leaf `key`, in its text's bytes.
    fn backgrounds(&self, key: u64) -> Vec<(Range<usize>, Hsla)>;
}

thread_local! {
    static SINK: RefCell<Option<Rc<dyn EditorSink>>> = const { RefCell::new(None) };
}

/// Run `f` with `sink` installed; restores the previous sink afterwards.
pub(crate) fn with_sink<R>(sink: Rc<dyn EditorSink>, f: impl FnOnce() -> R) -> R {
    /// Restores the previous sink on drop, so a panic inside `f` cannot leave
    /// a stale sink installed for later frames.
    struct Restore(Option<Rc<dyn EditorSink>>);
    impl Drop for Restore {
        fn drop(&mut self) {
            let previous = self.0.take();
            SINK.with(|s| *s.borrow_mut() = previous);
        }
    }
    let _restore = Restore(SINK.with(|s| s.replace(Some(sink))));
    f()
}

pub(crate) fn current() -> Option<Rc<dyn EditorSink>> {
    SINK.with(|s| s.borrow().clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Nop;
    impl EditorSink for Nop {
        fn report(&self, _: u64, _: &TextLayout) {}
        fn begin_pieces(&self, _: u64) {}
        fn report_text_piece(&self, _: u64, _: usize, _: &TextLayout) {}
        fn report_box_piece(&self, _: u64, _: Range<usize>, _: Bounds<Pixels>) {}
        fn report_empty_piece(&self, _: u64, _: usize, _: Bounds<Pixels>) {}
        fn backgrounds(&self, _: u64) -> Vec<(Range<usize>, Hsla)> {
            Vec::new()
        }
    }

    #[test]
    fn with_sink_restores_on_panic() {
        let result = std::panic::catch_unwind(|| {
            with_sink(Rc::new(Nop), || {
                assert!(current().is_some());
                panic!("boom");
            })
        });
        assert!(result.is_err());
        assert!(current().is_none(), "sink is cleared after a panic");
    }
}
