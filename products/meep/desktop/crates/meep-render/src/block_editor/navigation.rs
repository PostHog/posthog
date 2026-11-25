use super::model::*;
use super::*;

impl BlockEditor {
    /// Start or end of the visual row holding `pos`.
    pub(super) fn line_bound(&self, pos: Pos, end: bool) -> usize {
        let Some(l) = self.geo.layouts.get(pos.block) else {
            return if end {
                self.doc.block(pos.block).len()
            } else {
                0
            };
        };
        let row = l.row_of(pos.offset, self.upstream);
        let v = &l.visual[row];
        if end { v.end } else { v.start }
    }

    // ---- Moving -------------------------------------------------------------------

    /// The next caret position with text to the left or right, crossing
    /// into the neighbouring block (dividers are stepped over).
    fn step(&self, pos: Pos, forward: bool, word: bool) -> Pos {
        let text = &self.doc.block(pos.block).text;
        if forward {
            if pos.offset < text.len() {
                let to = if word {
                    next_word(text, pos.offset)
                } else {
                    next_char(text, pos.offset)
                };
                return Pos::new(pos.block, to);
            }
            let mut i = pos.block + 1;
            while i < self.doc.len() && !self.doc.block(i).kind.has_text() {
                i += 1;
            }
            if i < self.doc.len() {
                Pos::new(i, 0)
            } else {
                pos
            }
        } else {
            if pos.offset > 0 {
                let to = if word {
                    prev_word(text, pos.offset)
                } else {
                    prev_char(text, pos.offset)
                };
                return Pos::new(pos.block, to);
            }
            let mut i = pos.block;
            while i > 0 {
                i -= 1;
                if self.doc.block(i).kind.has_text() {
                    return Pos::new(i, self.doc.block(i).len());
                }
            }
            pos
        }
    }

    pub(crate) fn horizontal(
        &mut self,
        forward: bool,
        extend: bool,
        word: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.menu_close_slash();
        self.goal_x = None;
        if self.sel.blocks {
            let span = self.sel.block_span();
            let i = if forward { span.end - 1 } else { span.start };
            let pos = if forward {
                Pos::new(i, self.doc.block(i).len())
            } else {
                Pos::new(i, 0)
            };
            self.set_selection(Selection::caret(pos), window, cx);
            return;
        }
        if !extend && !self.sel.is_caret() {
            let pos = if forward {
                self.sel.end()
            } else {
                self.sel.start()
            };
            self.set_selection(Selection::caret(pos), window, cx);
            return;
        }
        let head = self.step(self.sel.head, forward, word);
        let anchor = if extend { self.sel.anchor } else { head };
        self.set_selection(Selection::range(anchor, head), window, cx);
    }

    /// The caret's x from the content's left edge.
    fn caret_x(&self, pos: Pos) -> Pixels {
        self.caret_rect(pos, self.upstream)
            .map(|r| r.origin.x)
            .unwrap_or_default()
    }

    /// One row up or down at the goal column, across blocks.
    fn row_step(&self, pos: Pos, down: bool, x: Pixels) -> Option<Pos> {
        let l = self.geo.layouts.get(pos.block)?;
        let row = l.row_of(pos.offset, self.upstream);
        let (block, row) = if down {
            if row + 1 < l.visual.len() {
                (pos.block, row + 1)
            } else {
                let mut i = pos.block + 1;
                while i < self.doc.len() && !self.doc.block(i).kind.has_text() {
                    i += 1;
                }
                if i >= self.doc.len() {
                    return None;
                }
                (i, 0)
            }
        } else if row > 0 {
            (pos.block, row - 1)
        } else {
            let mut i = pos.block;
            loop {
                if i == 0 {
                    return None;
                }
                i -= 1;
                if self.doc.block(i).kind.has_text() {
                    break;
                }
            }
            (i, self.geo.layouts[i].visual.len() - 1)
        };
        let origin = self.text_origin(block);
        let (offset, _) = self.geo.layouts[block].offset_at(row, x - origin.x);
        Some(Pos::new(block, offset))
    }

    pub(crate) fn vertical(
        &mut self,
        down: bool,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.menu_navigate(down, cx) {
            return;
        }
        if !self.geo.valid && self.bounds.size.width > px(0.) {
            self.ensure_layout(self.bounds.size.width, window);
        }
        if self.sel.blocks {
            let span = self.sel.block_span();
            let n = self.doc.len();
            if extend {
                let head = if down {
                    (self.sel.head.block + 1).min(n - 1)
                } else {
                    self.sel.head.block.saturating_sub(1)
                };
                self.set_selection(
                    Selection::block_range(self.sel.anchor.block, head),
                    window,
                    cx,
                );
            } else {
                let i = if down {
                    (span.end).min(n - 1)
                } else {
                    span.start.saturating_sub(1)
                };
                self.set_selection(Selection::block_range(i, i), window, cx);
            }
            return;
        }
        let from = if extend || self.sel.is_caret() {
            self.sel.head
        } else if down {
            self.sel.end()
        } else {
            self.sel.start()
        };
        let x = self.goal_x.unwrap_or_else(|| self.caret_x(from));
        let target = self.row_step(from, down, x);
        if extend {
            // Shift-arrow past a block's edge: first to the edge, then whole
            // blocks.
            let head = self.sel.head;
            let len = self.doc.block(head.block).len();
            let crossing = target.is_none_or(|t| t.block != head.block);
            if crossing && self.sel.anchor.block == head.block {
                let edge = if down { len } else { 0 };
                if head.offset != edge {
                    let goal = x;
                    self.set_selection(
                        Selection::range(self.sel.anchor, Pos::new(head.block, edge)),
                        window,
                        cx,
                    );
                    self.goal_x = Some(goal);
                    return;
                }
                let n = self.doc.len();
                let next = if down {
                    (head.block + 1).min(n - 1)
                } else {
                    head.block.saturating_sub(1)
                };
                self.set_selection(Selection::block_range(head.block, next), window, cx);
                return;
            }
        }
        let target = target.unwrap_or_else(|| {
            if down {
                Pos::new(from.block, self.doc.block(from.block).len())
            } else {
                Pos::new(from.block, 0)
            }
        });
        let anchor = if extend { self.sel.anchor } else { target };
        self.set_selection(Selection::range(anchor, target), window, cx);
        self.goal_x = Some(x);
    }

    pub(crate) fn line_edge(
        &mut self,
        end: bool,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.goal_x = None;
        if self.sel.blocks {
            self.horizontal(end, false, false, window, cx);
            return;
        }
        let head = self.sel.head;
        let offset = self.line_bound(head, end);
        let pos = Pos::new(head.block, offset);
        let anchor = if extend { self.sel.anchor } else { pos };
        let wraps = self
            .geo
            .layouts
            .get(head.block)
            .map(|l| l.visual[l.row_of(head.offset, self.upstream)].wraps)
            .unwrap_or(false);
        self.set_selection(Selection::range(anchor, pos), window, cx);
        // The end of a wrapped row is drawn on that row.
        self.upstream = end && wraps;
    }

    pub(crate) fn doc_edge(
        &mut self,
        end: bool,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let pos = if end { self.doc.end() } else { Pos::new(0, 0) };
        let anchor = if extend { self.sel.anchor } else { pos };
        self.set_selection(Selection::range(anchor, pos), window, cx);
    }

    pub(crate) fn block_edge(
        &mut self,
        end: bool,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let head = self.sel.head;
        let len = self.doc.block(head.block).len();
        let pos = if end {
            if head.offset < len || head.block + 1 >= self.doc.len() {
                Pos::new(head.block, len)
            } else {
                Pos::new(head.block + 1, self.doc.block(head.block + 1).len())
            }
        } else if head.offset > 0 || head.block == 0 {
            Pos::new(head.block, 0)
        } else {
            Pos::new(head.block - 1, 0)
        };
        let anchor = if extend { self.sel.anchor } else { pos };
        self.set_selection(Selection::range(anchor, pos), window, cx);
    }

    pub(crate) fn select_all(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.menu = None;
        let n = self.doc.len();
        if self.sel.blocks {
            self.set_selection(Selection::block_range(0, n - 1), window, cx);
            return;
        }
        let head = self.sel.head;
        let len = self.doc.block(head.block).len();
        let whole_block = self.sel.start() == Pos::new(head.block, 0)
            && self.sel.end() == Pos::new(head.block, len);
        let spans_blocks = self.sel.anchor.block != self.sel.head.block;
        if whole_block || spans_blocks || len == 0 {
            self.set_selection(Selection::block_range(0, n - 1), window, cx);
        } else {
            self.set_selection(
                Selection::range(Pos::new(head.block, 0), Pos::new(head.block, len)),
                window,
                cx,
            );
        }
    }

    pub(crate) fn escape(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.menu.is_some() {
            let link = matches!(self.menu, Some(Menu::Link { .. }));
            self.menu = None;
            if link {
                self.focus.focus(window, cx);
            }
            cx.notify();
            return;
        }
        if self.sel.blocks {
            let i = self.sel.head.block;
            self.set_selection(
                Selection::caret(Pos::new(i, self.doc.block(i).len())),
                window,
                cx,
            );
            return;
        }
        // Esc selects the block being edited, as in Notion.
        let span = self.sel.block_span();
        self.set_selection(Selection::block_range(span.start, span.end - 1), window, cx);
    }
}
