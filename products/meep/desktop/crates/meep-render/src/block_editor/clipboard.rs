use super::model::*;
use super::*;
/// The clipboard metadata that carries blocks between editors losslessly.
const CLIP_KEY: &str = "viewBlocks";

impl BlockEditor {
    /// The selection as blocks: partial blocks at either end are cut down.
    pub(crate) fn selected_blocks(&self) -> Vec<Rc<Block>> {
        if self.sel.blocks {
            return self
                .sel
                .block_span()
                .map(|i| self.doc.blocks[i].clone())
                .collect();
        }
        let (s, e) = (self.sel.start(), self.sel.end());
        (s.block..=e.block)
            .map(|i| {
                let b = self.doc.block(i);
                let a = if i == s.block { s.offset } else { 0 };
                let z = if i == e.block { e.offset } else { b.len() };
                if a == 0 && z == b.len() {
                    self.doc.blocks[i].clone()
                } else {
                    Rc::new(b.slice(a..z))
                }
            })
            .collect()
    }

    pub(crate) fn copy(&mut self, cut: bool, window: &mut Window, cx: &mut Context<Self>) {
        if self.sel.is_caret() {
            return;
        }
        let blocks = self.selected_blocks();
        let single_text = !self.sel.blocks && blocks.len() == 1;
        // Plain text for a fragment of one block; Markdown across blocks,
        // as Notion copies.
        let text = if single_text {
            blocks[0].text.clone()
        } else {
            markdown::to_markdown(&blocks)
        };
        let json: Vec<serde_json::Value> = blocks.iter().map(|b| block_to_json(b)).collect();
        let metadata = serde_json::json!({ CLIP_KEY: json, "partial": single_text }).to_string();
        cx.write_to_clipboard(ClipboardItem {
            entries: vec![ClipboardEntry::String(ClipboardString {
                text,
                metadata: Some(metadata),
            })],
        });
        #[cfg(target_os = "macos")]
        {
            use objc2_app_kit::{NSPasteboard, NSPasteboardTypeHTML};
            use objc2_foundation::NSString;
            let html = NSString::from_str(&markdown::to_html(&blocks));
            NSPasteboard::generalPasteboard()
                .setString_forType(&html, unsafe { NSPasteboardTypeHTML });
        }
        if cut && !self.read_only {
            self.transact(EditKind::Other, window, cx, |e, _, _| {
                e.delete_selection();
            });
        }
    }

    pub(crate) fn paste(&mut self, plain: bool, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        let Some(item) = cx.read_from_clipboard() else {
            return;
        };
        let mut text = String::new();
        let mut metadata = None;
        #[cfg(target_os = "macos")]
        let html = objc2_app_kit::NSPasteboard::generalPasteboard()
            .stringForType(unsafe { objc2_app_kit::NSPasteboardTypeHTML })
            .map(|s| s.to_string());
        #[cfg(not(target_os = "macos"))]
        let html: Option<String> = None;
        for entry in &item.entries {
            match entry {
                ClipboardEntry::String(s) => {
                    text.push_str(s.text());
                    if metadata.is_none() {
                        metadata = s.metadata.clone();
                    }
                }
                _ => {}
            }
        }
        let head_kind = self.doc.block(self.sel.head.block).kind;
        if head_kind == Kind::Code && !self.sel.blocks {
            self.insert_text(&text, false, window, cx);
            return;
        }
        // A URL pasted over selected text links it.
        let trimmed = text.trim();
        if !plain
            && !self.sel.is_caret()
            && !self.sel.blocks
            && self.sel.anchor.block == self.sel.head.block
            && (trimmed.starts_with("https://") || trimmed.starts_with("http://"))
            && !trimmed.contains(char::is_whitespace)
        {
            let ranges = self.selected_ranges();
            self.apply_link(ranges, trimmed, window, cx);
            return;
        }
        let ours = (!plain)
            .then_some(metadata.as_deref())
            .flatten()
            .and_then(|m| m.parse::<serde_json::Value>().ok())
            .filter(|v| v[CLIP_KEY].is_array());
        let blocks: Vec<Block> = if let Some(v) = ours {
            let partial = v["partial"] == true;
            let mut blocks: Vec<Block> = v[CLIP_KEY]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(block_from_json)
                .collect();
            if partial {
                for b in &mut blocks {
                    b.kind = Kind::Paragraph;
                    b.indent = 0;
                }
            }
            blocks
        } else if plain {
            plain_paragraphs(&text)
        } else if let Some(html) = html.filter(|h| !h.trim().is_empty()) {
            let blocks = markdown::from_html(&html);
            if blocks.is_empty() {
                markdown::from_plain(&text)
            } else {
                blocks
            }
        } else if !text.contains('\n') {
            vec![Block::new(Kind::Paragraph, text.clone())]
        } else {
            markdown::from_plain(&text)
        };
        if blocks.is_empty() {
            return;
        }
        self.insert_blocks(blocks, window, cx);
    }

    /// Inserts pasted blocks at the selection: the first merges into the
    /// caret's block, the rest follow, and the text after the caret ends up
    /// after the last.
    pub(crate) fn insert_blocks(
        &mut self,
        mut blocks: Vec<Block>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        for b in &mut blocks {
            b.id = new_id();
            b.touch();
        }
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            e.delete_selection();
            let pos = e.sel.head;
            let i = pos.block;
            let current = e.doc.block(i).clone();
            let tail = current.slice(pos.offset..current.len());
            let len = current.len();
            e.doc.block_mut(i).replace(pos.offset..len, "", &[]);
            let mut blocks = blocks.into_iter();
            let first = blocks.next().unwrap();
            let rest: Vec<Block> = blocks.collect();
            let mut last = i;
            if current.kind == Kind::Divider {
                last = i + 1;
                e.doc.blocks.insert(last, Rc::new(first));
            } else if e.doc.block(i).is_empty()
                && (first.kind != Kind::Paragraph || current.kind == Kind::Paragraph)
            {
                // An empty block takes the pasted block's kind.
                let mut first = first;
                first.id = current.id.clone();
                if first.kind.indents() {
                    first.indent = (first.indent + current.indent).min(MAX_INDENT);
                }
                e.doc.blocks[i] = Rc::new(first);
            } else {
                e.doc.block_mut(i).append(&first);
            }
            let base = current.indent;
            for mut b in rest {
                if b.kind.indents() {
                    b.indent = (b.indent + base).min(MAX_INDENT);
                }
                last += 1;
                e.doc.blocks.insert(last, Rc::new(b));
            }
            let caret = if e.doc.block(last).kind == Kind::Divider {
                let mut p = Block::new(Kind::Paragraph, "");
                p.append(&tail);
                e.doc.blocks.insert(last + 1, Rc::new(p));
                Pos::new(last + 1, 0)
            } else {
                let at = e.doc.block(last).len();
                e.doc.block_mut(last).append(&tail);
                Pos::new(last, at)
            };
            e.sel = Selection::caret(caret);
        });
    }
}

/// ⌘⇧V: paragraphs split on blank lines, no Markdown.
fn plain_paragraphs(text: &str) -> Vec<Block> {
    let text = text.replace("\r\n", "\n");
    text.split("\n\n")
        .filter(|p| !p.trim().is_empty())
        .map(|p| Block::new(Kind::Paragraph, p.trim_matches('\n')))
        .collect()
}
