//! Text input from the system: typing, IME composition (Japanese, Chinese,
//! Korean), dictation and the emoji picker. The input system sees the
//! caret's block as its document, in UTF-16 offsets.
use super::model::*;
use super::*;

impl BlockEditor {
    fn input_block(&self) -> usize {
        self.sel.head.block
    }
    fn to_utf16(&self, block: usize, offset: usize) -> usize {
        utf16_len(&self.doc.block(block).text[..offset.min(self.doc.block(block).len())])
    }
    fn to_utf8(&self, block: usize, utf16: usize) -> usize {
        utf8_offset(&self.doc.block(block).text, utf16)
    }
    fn range_to_utf8(&self, block: usize, r: &Range<usize>) -> Range<usize> {
        self.to_utf8(block, r.start)..self.to_utf8(block, r.end)
    }

    /// Replaces text from the input system: `range` is in the caret's block
    /// (UTF-16); without one, the marked text or the selection is replaced.
    fn replace_from_input(
        &mut self,
        range: Option<Range<usize>>,
        text: &str,
        mark: Option<Option<Range<usize>>>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.read_only {
            return;
        }
        let block = self.input_block();
        let target = range
            .map(|r| (block, self.range_to_utf8(block, &r)))
            .or_else(|| self.marked.clone());
        let composing = mark.is_some();
        if let Some((b, r)) = target {
            // Replace a range in one block: select it, then insert.
            let r = self.doc.block(b).clamp(r);
            self.sel = Selection::range(Pos::new(b, r.start), Pos::new(b, r.end));
        }
        let was_marked = self.marked.take();
        if text.is_empty() && self.sel.is_caret() {
            if composing {
                self.marked = None;
                cx.notify();
            }
            return;
        }
        let kind_typed = !composing && was_marked.is_none();
        if text.is_empty() {
            self.transact(EditKind::Typing, window, cx, |e, _, _| {
                e.delete_selection();
            });
        } else if composing {
            // Composition updates are one undo step with the final text.
            let pending = self.pending.clone();
            self.transact(EditKind::Typing, window, cx, |e, _, _| {
                e.delete_selection();
                let at = e.sel.head;
                let block = e.doc.block(at.block);
                let styles = if block.kind == Kind::Code {
                    vec![]
                } else {
                    pending
                        .clone()
                        .unwrap_or_else(|| block.styles_at(at.offset))
                };
                e.doc
                    .block_mut(at.block)
                    .replace(at.offset..at.offset, text, &styles);
                e.sel = Selection::caret(Pos::new(at.block, at.offset + text.len()));
            });
            let start = self.sel.head.offset - text.len();
            let b = self.sel.head.block;
            self.marked = Some((b, start..start + text.len()));
            if let Some(Some(selected)) = mark {
                let s = utf8_offset(text, selected.start);
                let e = utf8_offset(text, selected.end);
                self.sel = Selection::range(Pos::new(b, start + s), Pos::new(b, start + e));
            }
            self.bump();
            cx.notify();
        } else {
            self.insert_text(text, kind_typed || was_marked.is_some(), window, cx);
        }
    }
}

impl EntityInputHandler for BlockEditor {
    fn text_for_range(
        &mut self,
        range: Range<usize>,
        adjusted: &mut Option<Range<usize>>,
        _: &mut Window,
        _: &mut Context<Self>,
    ) -> Option<String> {
        let b = self.input_block();
        let r = self.range_to_utf8(b, &range);
        let r = self.doc.block(b).clamp(r);
        *adjusted = Some(self.to_utf16(b, r.start)..self.to_utf16(b, r.end));
        Some(self.doc.block(b).text[r].to_owned())
    }

    fn selected_text_range(
        &mut self,
        _ignore_disabled: bool,
        _: &mut Window,
        _: &mut Context<Self>,
    ) -> Option<UTF16Selection> {
        if self.sel.blocks {
            return None;
        }
        let b = self.input_block();
        let head = self.to_utf16(b, self.sel.head.offset);
        let anchor = if self.sel.anchor.block == b {
            self.to_utf16(b, self.sel.anchor.offset)
        } else {
            head
        };
        Some(UTF16Selection {
            range: anchor.min(head)..anchor.max(head),
            reversed: head < anchor,
        })
    }

    fn marked_text_range(&self, _: &mut Window, _: &mut Context<Self>) -> Option<Range<usize>> {
        let (b, r) = self.marked.clone()?;
        Some(self.to_utf16(b, r.start)..self.to_utf16(b, r.end))
    }

    fn unmark_text(&mut self, _: &mut Window, cx: &mut Context<Self>) {
        if self.marked.take().is_some() {
            self.bump();
            cx.notify();
        }
    }

    fn replace_text_in_range(
        &mut self,
        range: Option<Range<usize>>,
        text: &str,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.replace_from_input(range, text, None, window, cx);
    }

    fn replace_and_mark_text_in_range(
        &mut self,
        range: Option<Range<usize>>,
        new_text: &str,
        new_selected_range: Option<Range<usize>>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.replace_from_input(range, new_text, Some(new_selected_range), window, cx);
    }

    fn bounds_for_range(
        &mut self,
        range_utf16: Range<usize>,
        element_bounds: Bounds<Pixels>,
        _: &mut Window,
        _: &mut Context<Self>,
    ) -> Option<Bounds<Pixels>> {
        let b = self.input_block();
        let offset = self.to_utf8(b, range_utf16.start);
        let caret = self.caret_rect(Pos::new(b, offset), self.upstream)?;
        let l = self.geo.layouts.get(b)?;
        let origin = element_bounds.origin + caret.origin;
        Some(Bounds::new(
            point(
                origin.x,
                origin.y - (l.line_height - caret.size.height) / 2.,
            ),
            size(px(2.), l.line_height),
        ))
    }

    fn character_index_for_point(
        &mut self,
        point: Point<Pixels>,
        _: &mut Window,
        _: &mut Context<Self>,
    ) -> Option<usize> {
        let local = point - self.bounds.origin;
        let (pos, _) = self.pos_at(local);
        (pos.block == self.input_block()).then(|| self.to_utf16(pos.block, pos.offset))
    }

    fn text_length_utf16(&mut self, _: &mut Window, _: &mut Context<Self>) -> Option<usize> {
        let b = self.input_block();
        Some(utf16_len(&self.doc.block(b).text))
    }

    fn accepts_text_input(&self, _: &mut Window, _: &mut Context<Self>) -> bool {
        !self.read_only
    }
}
