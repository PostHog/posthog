use super::model::*;
use super::*;

impl BlockEditor {
    pub(crate) fn tab(&mut self, outdent: bool, window: &mut Window, cx: &mut Context<Self>) {
        if self.menu_navigate(!outdent, cx) {
            return;
        }
        let head = self.sel.head;
        if !self.sel.blocks && self.doc.block(head.block).kind == Kind::Code {
            self.code_tab(outdent, window, cx);
            return;
        }
        let span = self.sel.block_span();
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            for i in span.clone() {
                let kind = e.doc.block(i).kind;
                if !kind.indents() {
                    continue;
                }
                let indent = e.doc.block(i).indent;
                let next = if outdent {
                    indent.saturating_sub(1)
                } else {
                    let max = if i == 0 {
                        0
                    } else {
                        e.doc.block(i - 1).indent.saturating_add(1)
                    };
                    (indent + 1).min(max).min(MAX_INDENT)
                };
                if next != indent {
                    let b = e.doc.block_mut(i);
                    b.indent = next;
                    b.touch();
                }
            }
        });
    }

    /// Tab in code: two spaces at the caret, or on every selected line.
    fn code_tab(&mut self, outdent: bool, window: &mut Window, cx: &mut Context<Self>) {
        let (start, end) = (self.sel.start(), self.sel.end());
        let i = start.block;
        if end.block != i {
            return;
        }
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            let text = e.doc.block(i).text.clone();
            let first_line = text[..start.offset].rfind('\n').map(|p| p + 1).unwrap_or(0);
            if !outdent && start == end {
                e.doc
                    .block_mut(i)
                    .replace(start.offset..start.offset, "  ", &[]);
                e.sel = Selection::caret(Pos::new(i, start.offset + 2));
                return;
            }
            // Every line touched by the selection.
            let mut line_starts = vec![first_line];
            for (p, c) in text[first_line..end.offset].char_indices() {
                if c == '\n' {
                    line_starts.push(first_line + p + 1);
                }
            }
            let mut anchor = e.sel.anchor.offset as isize;
            let mut head = e.sel.head.offset as isize;
            for &ls in line_starts.iter().rev() {
                if outdent {
                    let current = &e.doc.block(i).text;
                    let n = current[ls..]
                        .chars()
                        .take(2)
                        .take_while(|c| *c == ' ')
                        .count();
                    if n == 0 {
                        continue;
                    }
                    e.doc.block_mut(i).replace(ls..ls + n, "", &[]);
                    for p in [&mut anchor, &mut head] {
                        if *p > ls as isize {
                            *p = (*p - n as isize).max(ls as isize);
                        }
                    }
                } else {
                    e.doc.block_mut(i).replace(ls..ls, "  ", &[]);
                    for p in [&mut anchor, &mut head] {
                        if *p >= ls as isize {
                            *p += 2;
                        }
                    }
                }
            }
            e.sel = Selection::range(Pos::new(i, anchor as usize), Pos::new(i, head as usize));
        });
    }

    /// Turns the selected blocks (or the caret's block) into another kind.
    pub fn turn_into(&mut self, kind: Kind, window: &mut Window, cx: &mut Context<Self>) {
        self.menu = None;
        let span = self.sel.block_span();
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            for i in span.clone() {
                let b = e.doc.block_mut(i);
                if b.kind == Kind::Divider && kind != Kind::Divider {
                    continue;
                }
                b.kind = kind;
                if kind != Kind::Todo {
                    b.checked = false;
                }
                if !kind.indents() {
                    b.indent = 0;
                }
                if kind == Kind::Code {
                    b.marks.clear();
                }
                if kind == Kind::Divider {
                    b.text.clear();
                    b.marks.clear();
                }
                b.touch();
            }
            e.sel = Selection {
                anchor: e.doc.clamp(e.sel.anchor),
                head: e.doc.clamp(e.sel.head),
                blocks: e.sel.blocks,
            };
        });
    }

    pub(crate) fn duplicate(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let span = self.sel.block_span();
        let was_blocks = self.sel.blocks;
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            let copies: Vec<Rc<Block>> = span
                .clone()
                .map(|i| {
                    let mut b = e.doc.block(i).clone();
                    b.id = new_id();
                    b.touch();
                    Rc::new(b)
                })
                .collect();
            let at = span.end;
            let n = copies.len();
            e.doc.blocks.splice(at..at, copies);
            e.sel = if was_blocks {
                Selection::block_range(at, at + n - 1)
            } else {
                let offset = e.sel.head.offset;
                Selection::caret(e.doc.clamp(Pos::new(e.sel.head.block + n, offset)))
            };
        });
    }

    /// ⌘⇧↑/↓: moves the selected blocks (with their nested blocks) past
    /// the neighbouring block.
    pub(crate) fn move_blocks(&mut self, down: bool, window: &mut Window, cx: &mut Context<Self>) {
        let span = self.sel.block_span();
        let span = span.start..self.doc.subtree(span.end - 1).end;
        let n = self.doc.len();
        if (!down && span.start == 0) || (down && span.end >= n) {
            return;
        }
        let target = if down {
            // After the next block and its nested blocks.
            self.doc.subtree(span.end).end
        } else {
            // Before the previous sibling at this depth.
            let indent = self.doc.block(span.start).indent;
            let mut i = span.start - 1;
            while i > 0 && self.doc.block(i).indent > indent {
                i -= 1;
            }
            i
        };
        self.move_span(span, target, window, cx);
    }

    /// Moves `span` so it starts at `target` (an index in the current
    /// document). Keeps the selection on the moved blocks.
    pub(crate) fn move_span(
        &mut self,
        span: Range<usize>,
        target: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if target >= span.start && target <= span.end {
            return;
        }
        let sel = self.sel;
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            let moved: Vec<Rc<Block>> = e.doc.blocks.drain(span.clone()).collect();
            let len = moved.len();
            let at = if target > span.end {
                target - len
            } else {
                target
            };
            e.doc.blocks.splice(at..at, moved);
            let map = |i: usize| {
                if span.contains(&i) {
                    at + (i - span.start)
                } else {
                    i
                }
            };
            e.sel = if sel.blocks {
                Selection::block_range(map(sel.anchor.block), map(sel.head.block))
            } else if span.contains(&sel.head.block) && span.contains(&sel.anchor.block) {
                Selection::range(
                    Pos::new(map(sel.anchor.block), sel.anchor.offset),
                    Pos::new(map(sel.head.block), sel.head.offset),
                )
            } else {
                Selection::block_range(at, at + len - 1)
            };
        });
    }

    pub(crate) fn toggle_checked(&mut self, i: usize, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only || self.doc.block(i).kind != Kind::Todo {
            return;
        }
        let sel = self.sel;
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            let b = e.doc.block_mut(i);
            b.checked = !b.checked;
            b.touch();
            e.sel = sel;
        });
    }

    pub(crate) fn insert_block_after(
        &mut self,
        i: usize,
        kind: Kind,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> usize {
        let mut at = i + 1;
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            // Reuse an empty paragraph right below, as Notion's + does.
            let indent = e.doc.block(i).indent;
            at = e.doc.subtree(i).end;
            let mut b = Block::new(kind, "");
            b.indent = if kind.indents() { indent } else { 0 };
            e.doc.blocks.insert(at, Rc::new(b));
            e.sel = Selection::caret(Pos::new(at, 0));
        });
        at
    }
}
