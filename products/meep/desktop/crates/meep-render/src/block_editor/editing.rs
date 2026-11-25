//! Text edits, Markdown shortcuts, inline formatting and undo.
use super::model::*;
use super::*;

#[derive(Clone, Copy)]
pub(crate) enum Unit {
    Word,
    Line,
}

impl BlockEditor {
    // ---- Transactions -------------------------------------------------------

    /// Runs an edit as one undoable step. Typing and deleting coalesce into
    /// the step before while the caret keeps going, as Notion does.
    pub(crate) fn transact(
        &mut self,
        kind: EditKind,
        window: &mut Window,
        cx: &mut Context<Self>,
        edit: impl FnOnce(&mut Self, &mut Window, &mut Context<Self>),
    ) -> bool {
        if self.read_only {
            return false;
        }
        let before = Snapshot {
            blocks: self.doc.blocks.clone(),
            selection: self.sel,
        };
        let before_sel = self.sel;
        edit(self, window, cx);
        self.doc.ensure_nonempty();
        let changed = self.doc.blocks.len() != before.blocks.len()
            || self
                .doc
                .blocks
                .iter()
                .zip(&before.blocks)
                .any(|(a, b)| !Rc::ptr_eq(a, b));
        if !changed {
            if self.sel != before_sel {
                self.after_move(window, cx);
            }
            return false;
        }
        let now = Instant::now();
        let coalesce = matches!(kind, EditKind::Typing | EditKind::Deleting)
            && self.history.undo.last().is_some_and(|last| {
                last.kind == kind
                    && last.after == before_sel
                    && now.duration_since(last.at) < Duration::from_millis(1500)
            })
            && !self.word_break(kind, &before);
        if coalesce {
            let last = self.history.undo.last_mut().unwrap();
            last.after = self.sel;
            last.at = now;
        } else {
            self.history.undo.push(Entry {
                before,
                after: self.sel,
                kind,
                at: now,
            });
            if self.history.undo.len() > HISTORY {
                self.history.undo.remove(0);
            }
        }
        self.history.redo.clear();
        self.after_edit(window, cx);
        true
    }

    /// Typing groups by word: a new word after a space starts a new step.
    fn word_break(&self, kind: EditKind, before: &Snapshot) -> bool {
        if kind != EditKind::Typing || !self.sel.is_caret() {
            return false;
        }
        let pos = before.selection.head;
        let Some(block) = before.blocks.get(pos.block) else {
            return false;
        };
        let prev = block.text[..pos.offset.min(block.text.len())]
            .chars()
            .next_back();
        let typed = self.doc.blocks.get(self.sel.head.block).and_then(|b| {
            b.text
                .get(pos.offset.min(b.text.len())..self.sel.head.offset.min(b.text.len()))
                .and_then(|s| s.chars().next())
        });
        matches!((prev, typed), (Some(p), Some(t)) if p.is_whitespace() && !t.is_whitespace())
    }

    pub(crate) fn after_edit(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.bump();
        self.schedule_change(cx);
        self.typing = true;
        self.hover = None;
        self.goal_x = None;
        self.autoscroll = true;
        self.sync_slash();
        self.restart_blink(cx);
        window.notify_text_input_changed(&self.focus);
        cx.notify();
    }

    pub(crate) fn after_move(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.autoscroll = true;
        self.sync_slash();
        self.restart_blink(cx);
        window.notify_text_selection_changed(&self.focus);
        cx.notify();
    }

    pub(crate) fn set_selection(
        &mut self,
        sel: Selection,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let sel = Selection {
            anchor: self.doc.clamp(sel.anchor),
            head: self.doc.clamp(sel.head),
            blocks: sel.blocks,
        };
        if sel != self.sel {
            self.pending = None;
            self.upstream = false;
            self.marked = None;
        }
        self.sel = sel;
        self.after_move(window, cx);
    }

    pub fn undo(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        if self.menu.is_some() {
            self.menu = None;
        }
        let Some(entry) = self.history.undo.pop() else {
            return;
        };
        let current = Snapshot {
            blocks: self.doc.blocks.clone(),
            selection: entry.after,
        };
        self.doc.blocks = entry.before.blocks.clone();
        self.sel = entry.before.selection;
        self.history.redo.push(Entry {
            before: current,
            after: entry.before.selection,
            kind: EditKind::Other,
            at: Instant::now(),
        });
        self.pending = None;
        self.marked = None;
        self.after_edit(window, cx);
    }

    pub fn redo(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        let Some(entry) = self.history.redo.pop() else {
            return;
        };
        let current = Snapshot {
            blocks: self.doc.blocks.clone(),
            selection: entry.after,
        };
        self.doc.blocks = entry.before.blocks.clone();
        self.sel = entry.before.selection;
        self.history.undo.push(Entry {
            before: current,
            after: entry.before.selection,
            kind: EditKind::Other,
            at: Instant::now(),
        });
        self.pending = None;
        self.marked = None;
        self.after_edit(window, cx);
    }

    // ---- Deleting the selection -------------------------------------------------

    /// Deletes whatever is selected, leaving a caret. Returns false when
    /// nothing was selected.
    pub(crate) fn delete_selection(&mut self) -> bool {
        if self.sel.blocks {
            let span = self.sel.block_span();
            let at = span.start;
            self.doc.blocks.drain(span);
            if self.doc.blocks.is_empty() || at >= self.doc.len() {
                self.doc.blocks.insert(
                    at.min(self.doc.len()),
                    Rc::new(Block::new(Kind::Paragraph, "")),
                );
            }
            let at = at.min(self.doc.len() - 1);
            let at = if self.doc.block(at).kind == Kind::Divider {
                self.doc
                    .blocks
                    .insert(at, Rc::new(Block::new(Kind::Paragraph, "")));
                at
            } else {
                at
            };
            self.sel = Selection::caret(Pos::new(at, 0));
            return true;
        }
        if self.sel.is_caret() {
            return false;
        }
        let at = self.doc.delete(self.sel.start(), self.sel.end());
        self.sel = Selection::caret(at);
        true
    }

    // ---- Typing ------------------------------------------------------------------

    /// Inserts typed or composed text at the selection. `typed` runs the
    /// Markdown shortcuts and the slash menu.
    pub(crate) fn insert_text(
        &mut self,
        text: &str,
        typed: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.read_only || text.is_empty() {
            return;
        }
        let text = text.replace("\r\n", "\n").replace('\r', "\n");
        let pending = self.pending.take();
        let replaced_range = !self.sel.is_caret();
        let kind = if replaced_range {
            EditKind::Other
        } else {
            EditKind::Typing
        };
        let mut inserted_at = None;
        self.transact(kind, window, cx, |e, _, _| {
            e.delete_selection();
            let mut at = e.sel.head;
            if e.doc.block(at.block).kind == Kind::Divider {
                e.doc
                    .blocks
                    .insert(at.block + 1, Rc::new(Block::new(Kind::Paragraph, "")));
                at = Pos::new(at.block + 1, 0);
            }
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
                .replace(at.offset..at.offset, &text, &styles);
            e.sel = Selection::caret(Pos::new(at.block, at.offset + text.len()));
            inserted_at = Some(at);
        });
        let Some(at) = inserted_at else { return };
        if typed {
            if text == "/" {
                self.maybe_open_slash(at, cx);
            }
            self.markdown_shortcuts(&text, window, cx);
        }
    }

    fn maybe_open_slash(&mut self, at: Pos, cx: &mut Context<Self>) {
        let block = self.doc.block(at.block);
        if block.kind == Kind::Code {
            return;
        }
        let before = block.text[..at.offset].chars().next_back();
        if before.is_none_or(char::is_whitespace) {
            self.menu = Some(Menu::Slash {
                block: at.block,
                offset: at.offset,
                selected: 0,
            });
            cx.notify();
        }
    }

    /// Block shortcuts at the start of a block (`# `, `- `, `1. `, `[] `,
    /// `> `, ```` ``` ````, `---`) and inline marks (`**b**`, `*i*`,
    /// `` `c` ``, `~~s~~`). Each runs as its own step, so ⌘Z brings the
    /// typed characters back.
    fn markdown_shortcuts(&mut self, typed: &str, window: &mut Window, cx: &mut Context<Self>) {
        if !self.sel.is_caret() {
            return;
        }
        let pos = self.sel.head;
        let block = self.doc.block(pos.block).clone();
        if block.kind == Kind::Code || block.kind == Kind::Divider {
            return;
        }
        let before = &block.text[..pos.offset];
        // Block shortcuts: the whole text before the caret is the prefix.
        let convert: Option<(Kind, bool, usize)> = match typed {
            " " => {
                let prefix = before.trim_end_matches(' ');
                if before.len() != prefix.len() + 1 {
                    None
                } else {
                    match prefix {
                        "#" => Some((Kind::H1, false, 2)),
                        "##" => Some((Kind::H2, false, 3)),
                        "###" => Some((Kind::H3, false, 4)),
                        "-" | "*" | "+" => Some((Kind::Bullet, false, 2)),
                        "[]" => Some((Kind::Todo, false, 3)),
                        "[ ]" => Some((Kind::Todo, false, 4)),
                        "[x]" | "[X]" => Some((Kind::Todo, true, 4)),
                        ">" | "\"" => Some((Kind::Quote, false, 2)),
                        p if p.len() <= 4
                            && p.ends_with('.')
                            && p.len() > 1
                            && p[..p.len() - 1].bytes().all(|b| b.is_ascii_digit()) =>
                        {
                            Some((Kind::Numbered, false, p.len() + 1))
                        }
                        _ => None,
                    }
                }
            }
            "`" if before == "```" => Some((Kind::Code, false, 3)),
            "-" if before == "---" && block.text == "---" => Some((Kind::Divider, false, 3)),
            _ => None,
        };
        if let Some((kind, checked, len)) = convert {
            if block.kind == kind && kind != Kind::Divider {
                return;
            }
            // Headings and quotes don't nest; lists keep their depth.
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                let i = pos.block;
                let b = e.doc.block_mut(i);
                b.replace(0..len, "", &[]);
                if kind == Kind::Divider {
                    b.kind = Kind::Divider;
                    b.text.clear();
                    b.marks.clear();
                    b.indent = 0;
                    e.doc
                        .blocks
                        .insert(i + 1, Rc::new(Block::new(Kind::Paragraph, "")));
                    e.sel = Selection::caret(Pos::new(i + 1, 0));
                    return;
                }
                b.kind = kind;
                b.checked = checked;
                if !kind.indents() {
                    b.indent = 0;
                }
                if kind == Kind::Code {
                    b.marks.clear();
                }
                e.sel = Selection::caret(Pos::new(i, 0));
            });
            self.menu = None;
            return;
        }
        // Inline marks, when the closing delimiter was just typed.
        let found = match typed {
            "*" => close_mark(before, "**", Style::Bold)
                .or_else(|| close_mark(before, "*", Style::Italic)),
            "_" => close_mark(before, "__", Style::Bold)
                .or_else(|| close_mark(before, "_", Style::Italic)),
            "`" => close_mark(before, "`", Style::Code),
            "~" => close_mark(before, "~~", Style::Strike),
            _ => None,
        };
        if let Some((open, inner, delim, style)) = found {
            let i = pos.block;
            let d = delim.len();
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                let b = e.doc.block_mut(i);
                // Closing delimiter first, so the opening offsets hold.
                b.replace(inner.end..inner.end + d, "", &[]);
                b.replace(open..open + d, "", &[]);
                let range = inner.start - d..inner.end - d;
                b.set_style(range.clone(), &style, true);
                e.sel = Selection::caret(Pos::new(i, range.end));
            });
            // Text typed next starts outside the mark.
            let styles: Vec<Style> = self
                .doc
                .block(i)
                .styles_at(self.sel.head.offset)
                .into_iter()
                .filter(|s| !s.same_kind(&style))
                .collect();
            self.pending = Some(styles);
        }
    }

    // ---- Enter, Backspace, Delete ---------------------------------------------

    pub(crate) fn enter(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.menu_confirm(window, cx) {
            return;
        }
        if self.read_only {
            return;
        }
        if self.sel.blocks {
            // Enter on selected blocks edits the last one.
            let i = self.sel.head.block;
            let end = Pos::new(i, self.doc.block(i).len());
            self.set_selection(Selection::caret(end), window, cx);
            return;
        }
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            e.delete_selection();
            let pos = e.sel.head;
            let block = e.doc.block(pos.block).clone();
            if block.kind == Kind::Code {
                // Keep the current line's indentation.
                let line_start = block.text[..pos.offset]
                    .rfind('\n')
                    .map(|i| i + 1)
                    .unwrap_or(0);
                let indent: String = block.text[line_start..]
                    .chars()
                    .take_while(|c| *c == ' ' || *c == '\t')
                    .collect();
                let insert = format!("\n{indent}");
                e.doc
                    .block_mut(pos.block)
                    .replace(pos.offset..pos.offset, &insert, &[]);
                e.sel = Selection::caret(Pos::new(pos.block, pos.offset + insert.len()));
                return;
            }
            if block.kind == Kind::Divider {
                e.doc
                    .blocks
                    .insert(pos.block + 1, Rc::new(Block::new(Kind::Paragraph, "")));
                e.sel = Selection::caret(Pos::new(pos.block + 1, 0));
                return;
            }
            if block.is_empty() && (block.kind.is_list() || block.kind == Kind::Quote) {
                // An empty list item steps out: up a level, then to text.
                let b = e.doc.block_mut(pos.block);
                if b.indent > 0 && b.kind.is_list() {
                    b.indent -= 1;
                } else {
                    b.kind = Kind::Paragraph;
                    b.checked = false;
                }
                b.touch();
                return;
            }
            if pos.offset == 0 && !block.is_empty() {
                // At the start: an empty block above, the caret stays.
                let mut above = Block::new(
                    if block.kind.is_list() {
                        block.kind
                    } else {
                        Kind::Paragraph
                    },
                    "",
                );
                above.indent = if above.kind.indents() {
                    block.indent
                } else {
                    0
                };
                e.doc.blocks.insert(pos.block, Rc::new(above));
                e.sel = Selection::caret(Pos::new(pos.block + 1, 0));
                return;
            }
            let next = if pos.offset >= block.len() {
                block.kind.continues_as()
            } else {
                block.kind
            };
            let at = e.doc.split(pos, next);
            e.sel = Selection::caret(at);
        });
    }

    pub(crate) fn soft_break(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.menu.is_some() {
            self.menu = None;
        }
        if self.sel.blocks {
            return;
        }
        self.insert_text("\n", false, window, cx);
    }

    /// ⌘Enter: toggles a to-do; leaves a code block for a new paragraph.
    pub(crate) fn mod_enter(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let span = self.sel.block_span();
        let todos: Vec<usize> = span
            .clone()
            .filter(|i| self.doc.block(*i).kind == Kind::Todo)
            .collect();
        if !todos.is_empty() {
            let all = todos.iter().all(|i| self.doc.block(*i).checked);
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                for i in &todos {
                    let b = e.doc.block_mut(*i);
                    b.checked = !all;
                    b.touch();
                }
            });
            return;
        }
        let i = self.sel.head.block;
        if self.doc.block(i).kind == Kind::Code {
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                e.doc
                    .blocks
                    .insert(i + 1, Rc::new(Block::new(Kind::Paragraph, "")));
                e.sel = Selection::caret(Pos::new(i + 1, 0));
            });
        }
    }

    pub(crate) fn backspace(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        if !self.sel.is_caret() {
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                e.delete_selection();
            });
            return;
        }
        let pos = self.sel.head;
        if pos.offset > 0 {
            self.transact(EditKind::Deleting, window, cx, |e, _, _| {
                let text = &e.doc.block(pos.block).text;
                let from = prev_char(text, pos.offset);
                e.doc
                    .block_mut(pos.block)
                    .replace(from..pos.offset, "", &[]);
                e.sel = Selection::caret(Pos::new(pos.block, from));
            });
            return;
        }
        let block = self.doc.block(pos.block).clone();
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            let i = pos.block;
            if block.kind != Kind::Paragraph && block.kind != Kind::Divider {
                // A heading, list item, quote or code block becomes text first.
                let b = e.doc.block_mut(i);
                b.kind = Kind::Paragraph;
                b.checked = false;
                if !block.kind.is_list() {
                    b.indent = 0;
                }
                b.touch();
                return;
            }
            if block.indent > 0 {
                let b = e.doc.block_mut(i);
                b.indent -= 1;
                b.touch();
                return;
            }
            if let Some(at) = e.doc.merge_into_previous(i) {
                e.sel = Selection::caret(at);
            }
        });
    }

    pub(crate) fn delete_forward(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        if !self.sel.is_caret() {
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                e.delete_selection();
            });
            return;
        }
        let pos = self.sel.head;
        let len = self.doc.block(pos.block).len();
        if pos.offset < len {
            self.transact(EditKind::Deleting, window, cx, |e, _, _| {
                let text = &e.doc.block(pos.block).text;
                let to = next_char(text, pos.offset);
                e.doc.block_mut(pos.block).replace(pos.offset..to, "", &[]);
            });
            return;
        }
        if pos.block + 1 >= self.doc.len() {
            return;
        }
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            let next = pos.block + 1;
            if e.doc.block(next).kind == Kind::Divider {
                e.doc.blocks.remove(next);
                return;
            }
            if let Some(at) = e.doc.merge_into_previous(next) {
                e.sel = Selection::caret(at);
            }
        });
    }

    pub(crate) fn delete_by(
        &mut self,
        unit: Unit,
        forward: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !self.sel.is_caret() {
            self.backspace(window, cx);
            return;
        }
        let pos = self.sel.head;
        let text = self.doc.block(pos.block).text.clone();
        let target = match (unit, forward) {
            (Unit::Word, false) => prev_word(&text, pos.offset),
            (Unit::Word, true) => next_word(&text, pos.offset),
            (Unit::Line, false) => self.line_bound(pos, false),
            (Unit::Line, true) => self.line_bound(pos, true),
        };
        if target == pos.offset {
            if forward {
                self.delete_forward(window, cx);
            } else {
                self.backspace(window, cx);
            }
            return;
        }
        let range = target.min(pos.offset)..target.max(pos.offset);
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            e.doc.block_mut(pos.block).replace(range.clone(), "", &[]);
            e.sel = Selection::caret(Pos::new(pos.block, range.start));
        });
    }

    // ---- Formatting ---------------------------------------------------------------

    /// Ranges of text the selection covers, per block (code blocks skipped).
    pub(crate) fn selected_ranges(&self) -> Vec<(usize, Range<usize>)> {
        let mut out = Vec::new();
        if self.sel.blocks {
            for i in self.sel.block_span() {
                let b = self.doc.block(i);
                if b.kind.has_text() && b.kind != Kind::Code && !b.is_empty() {
                    out.push((i, 0..b.len()));
                }
            }
            return out;
        }
        let (s, e) = (self.sel.start(), self.sel.end());
        for i in s.block..=e.block {
            let b = self.doc.block(i);
            if !b.kind.has_text() || b.kind == Kind::Code {
                continue;
            }
            let a = if i == s.block { s.offset } else { 0 };
            let z = if i == e.block { e.offset } else { b.len() };
            if a < z {
                out.push((i, a..z));
            }
        }
        out
    }

    pub(crate) fn style_active(&self, style: &Style) -> bool {
        let ranges = self.selected_ranges();
        if ranges.is_empty() {
            let pos = self.sel.head;
            return self
                .pending
                .clone()
                .unwrap_or_else(|| self.doc.block(pos.block).styles_at(pos.offset))
                .iter()
                .any(|s| s.same_kind(style));
        }
        ranges
            .iter()
            .all(|(i, r)| self.doc.block(*i).has_style(r.clone(), style))
    }

    pub fn toggle_style(&mut self, style: Style, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        let ranges = self.selected_ranges();
        let on = !self.style_active(&style);
        if ranges.is_empty() {
            // Nothing selected: the next typed text takes the style.
            let pos = self.sel.head;
            let mut styles = self
                .pending
                .clone()
                .unwrap_or_else(|| self.doc.block(pos.block).styles_at(pos.offset));
            styles.retain(|s| !s.same_kind(&style));
            if on {
                styles.push(style);
            }
            self.pending = Some(styles);
            cx.notify();
            return;
        }
        let sel = self.sel;
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            for (i, r) in &ranges {
                e.doc.block_mut(*i).set_style(r.clone(), &style, on);
            }
            e.sel = sel;
        });
    }

    pub(crate) fn apply_link(
        &mut self,
        ranges: Vec<(usize, Range<usize>)>,
        url: &str,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let url = normalize_url(url);
        let sel = self.sel;
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            if ranges.is_empty() {
                // No text selected: insert the URL itself as a link.
                if let Some(url) = &url {
                    let pos = e.sel.head;
                    let style = Style::Link(url.as_str().into());
                    e.doc
                        .block_mut(pos.block)
                        .replace(pos.offset..pos.offset, url, &[style]);
                    e.sel = Selection::caret(Pos::new(pos.block, pos.offset + url.len()));
                }
                return;
            }
            for (i, r) in &ranges {
                match &url {
                    Some(url) => e.doc.block_mut(*i).set_style(
                        r.clone(),
                        &Style::Link(url.as_str().into()),
                        true,
                    ),
                    None => {
                        e.doc
                            .block_mut(*i)
                            .set_style(r.clone(), &Style::Link("".into()), false)
                    }
                }
            }
            e.sel = sel;
        });
        let pos = self.sel.end();
        self.set_selection(Selection::caret(pos), window, cx);
    }
}

fn close_mark(
    before: &str,
    delim: &str,
    style: Style,
) -> Option<(usize, Range<usize>, &'static str, Style)> {
    let d = delim.len();
    if !before.ends_with(delim) || before.len() < 2 * d + 1 {
        return None;
    }
    let close = before.len() - d;
    // A single `*` right after another `*` belongs to `**`.
    if d == 1 && before[..close].ends_with(delim) {
        return None;
    }
    let open = before[..close].rfind(delim)?;
    let inner = open + d..close;
    if inner.is_empty() {
        return None;
    }
    let text = &before[inner.clone()];
    if text.starts_with(char::is_whitespace) || text.ends_with(char::is_whitespace) {
        return None;
    }
    // `*` inside `**…` is not italic; `_` inside a word is not italic.
    if d == 1 && open > 0 {
        let prev = before[..open].chars().next_back().unwrap();
        if prev.to_string() == delim || (delim == "_" && prev.is_alphanumeric()) {
            return None;
        }
    }
    if delim.contains('*') && text.contains(delim) {
        return None;
    }
    let delim: &'static str = match delim {
        "**" => "**",
        "__" => "__",
        "*" => "*",
        "_" => "_",
        "`" => "`",
        _ => "~~",
    };
    Some((open, inner, delim, style))
}

fn normalize_url(url: &str) -> Option<String> {
    let url = url.trim();
    if url.is_empty() {
        return None;
    }
    let lower = url.to_ascii_lowercase();
    if lower.starts_with("http://") || lower.starts_with("https://") || lower.starts_with("mailto:")
    {
        Some(url.to_owned())
    } else if url.contains('@') && !url.contains('/') {
        Some(format!("mailto:{url}"))
    } else {
        Some(format!("https://{url}"))
    }
}
