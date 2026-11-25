//! The document a block editor edits: a flat list of blocks, each with its
//! text, inline marks and kind. Pure data and edits, no GPUI, so every rule
//! here is unit-tested and shared with the Markdown and JSON conversions.
//!
//! Blocks are reference-counted: an undo snapshot or a layout cache holds the
//! same `Rc<Block>`, and an edit copies only the block it changes
//! (`Rc::make_mut`). Every edit stamps the block with a new revision, which
//! is what the layout cache compares.
use serde_json::{Map, Value, json};
use std::cell::Cell;
use std::ops::Range;
use std::rc::Rc;
#[cfg(not(target_family = "wasm"))]
use std::time::{SystemTime, UNIX_EPOCH};
#[cfg(target_family = "wasm")]
use web_time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum Kind {
    Paragraph,
    H1,
    H2,
    H3,
    Bullet,
    Numbered,
    Todo,
    Quote,
    Code,
    Divider,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Paragraph => "paragraph",
            Kind::H1 => "h1",
            Kind::H2 => "h2",
            Kind::H3 => "h3",
            Kind::Bullet => "bullet",
            Kind::Numbered => "numbered",
            Kind::Todo => "todo",
            Kind::Quote => "quote",
            Kind::Code => "code",
            Kind::Divider => "divider",
        }
    }
    pub fn parse(name: &str) -> Option<Kind> {
        Some(match name {
            "paragraph" | "p" | "text" => Kind::Paragraph,
            "h1" | "heading1" => Kind::H1,
            "h2" | "heading2" => Kind::H2,
            "h3" | "heading3" => Kind::H3,
            "bullet" | "bulleted" | "ul" => Kind::Bullet,
            "numbered" | "ol" => Kind::Numbered,
            "todo" | "checkbox" => Kind::Todo,
            "quote" => Kind::Quote,
            "code" => Kind::Code,
            "divider" | "hr" => Kind::Divider,
            _ => return None,
        })
    }
    pub fn is_list(self) -> bool {
        matches!(self, Kind::Bullet | Kind::Numbered | Kind::Todo)
    }
    /// Blocks that hold editable text.
    pub fn has_text(self) -> bool {
        self != Kind::Divider
    }
    /// Whether Tab nests the block under the one above.
    pub fn indents(self) -> bool {
        matches!(
            self,
            Kind::Paragraph | Kind::Bullet | Kind::Numbered | Kind::Todo
        )
    }
    /// The kind a new block takes when Enter ends this one.
    pub fn continues_as(self) -> Kind {
        match self {
            Kind::Bullet | Kind::Numbered | Kind::Todo => self,
            _ => Kind::Paragraph,
        }
    }
}

#[derive(Clone, PartialEq, Eq, Debug, Hash)]
pub enum Style {
    Bold,
    Italic,
    Code,
    Strike,
    Link(Rc<str>),
}

impl Style {
    pub fn name(&self) -> &'static str {
        match self {
            Style::Bold => "bold",
            Style::Italic => "italic",
            Style::Code => "code",
            Style::Strike => "strike",
            Style::Link(_) => "link",
        }
    }
    /// Text typed right after the mark continues it (bold, italic, strike);
    /// code and links end where they end.
    pub fn extends(&self) -> bool {
        matches!(self, Style::Bold | Style::Italic | Style::Strike)
    }
    /// Same kind of mark, ignoring a link's URL.
    pub fn same_kind(&self, other: &Style) -> bool {
        std::mem::discriminant(self) == std::mem::discriminant(other)
    }
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub struct Mark {
    pub start: usize,
    pub end: usize,
    pub style: Style,
}

static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
thread_local! { static REVISION: Cell<u64> = const { Cell::new(1) }; }

fn next_revision() -> u64 {
    REVISION.with(|r| {
        let v = r.get() + 1;
        r.set(v);
        v
    })
}

/// A short unique block id: stable across edits so views and copies can
/// refer to blocks.
pub fn new_id() -> Rc<str> {
    let n = NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    let mut x = seed ^ n.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    let mut out = String::from("b");
    for _ in 0..8 {
        let digit = (x % 36) as u32;
        out.push(char::from_digit(digit, 36).unwrap_or('0'));
        x /= 36;
    }
    out.push_str(&format!("{n:x}"));
    out.into()
}

#[derive(Clone, Debug)]
pub struct Block {
    pub id: Rc<str>,
    pub kind: Kind,
    pub text: String,
    /// Sorted by start; marks of one style never overlap or touch.
    pub marks: Vec<Mark>,
    pub checked: bool,
    pub indent: u8,
    /// Bumped by every edit; the layout cache compares it.
    pub rev: u64,
}

impl PartialEq for Block {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
            && self.kind == other.kind
            && self.text == other.text
            && self.marks == other.marks
            && self.checked == other.checked
            && self.indent == other.indent
    }
}

pub const MAX_INDENT: u8 = 6;

impl Block {
    pub fn new(kind: Kind, text: impl Into<String>) -> Self {
        Self {
            id: new_id(),
            kind,
            text: text.into(),
            marks: Vec::new(),
            checked: false,
            indent: 0,
            rev: next_revision(),
        }
    }
    pub fn touch(&mut self) {
        self.rev = next_revision();
    }
    pub fn len(&self) -> usize {
        self.text.len()
    }
    pub fn is_empty(&self) -> bool {
        self.text.is_empty()
    }

    /// Styles a character typed at `at` takes on.
    pub fn styles_at(&self, at: usize) -> Vec<Style> {
        let mut styles: Vec<Style> = Vec::new();
        for mark in &self.marks {
            let inside = mark.start < at && at < mark.end;
            let at_end = at == mark.end && mark.start < at && mark.style.extends();
            if (inside || at_end) && !styles.contains(&mark.style) {
                styles.push(mark.style.clone());
            }
        }
        styles
    }

    /// Replaces `range` with `text`, which takes `styles`. Marks after the
    /// edit shift; marks inside it shrink.
    pub fn replace(&mut self, range: Range<usize>, text: &str, styles: &[Style]) {
        let range = self.clamp(range);
        let removed = range.end - range.start;
        let added = text.len();
        self.text.replace_range(range.clone(), text);
        let shift = |p: usize| -> usize {
            if p <= range.start {
                p
            } else if p >= range.end {
                p - removed + added
            } else {
                range.start
            }
        };
        for mark in &mut self.marks {
            mark.start = shift(mark.start);
            mark.end = shift(mark.end);
        }
        // Marks that surrounded the insertion now cover the new text; cut
        // them where the new text does not carry their style.
        if added > 0 {
            let new = range.start..range.start + added;
            let mut cut = Vec::new();
            for mark in &mut self.marks {
                if mark.start < new.end && mark.end > new.start && !styles.contains(&mark.style) {
                    if mark.start < new.start && mark.end > new.end {
                        cut.push(Mark {
                            start: new.end,
                            end: mark.end,
                            style: mark.style.clone(),
                        });
                        mark.end = new.start;
                    } else if mark.start < new.start {
                        mark.end = new.start;
                    } else if mark.end > new.end {
                        mark.start = new.end;
                    } else {
                        mark.end = mark.start;
                    }
                }
            }
            self.marks.extend(cut);
            for style in styles {
                self.marks.push(Mark {
                    start: new.start,
                    end: new.end,
                    style: style.clone(),
                });
            }
        }
        self.normalize();
        self.touch();
    }

    /// Adds or removes a mark over `range`.
    pub fn set_style(&mut self, range: Range<usize>, style: &Style, on: bool) {
        let range = self.clamp(range);
        if range.is_empty() {
            return;
        }
        // Remove the range from every mark of this kind (a link replaces
        // another link).
        let mut keep = Vec::new();
        for mark in self.marks.drain(..) {
            if !mark.style.same_kind(style) || mark.end <= range.start || mark.start >= range.end {
                keep.push(mark);
                continue;
            }
            if mark.start < range.start {
                keep.push(Mark {
                    start: mark.start,
                    end: range.start,
                    style: mark.style.clone(),
                });
            }
            if mark.end > range.end {
                keep.push(Mark {
                    start: range.end,
                    end: mark.end,
                    style: mark.style.clone(),
                });
            }
        }
        self.marks = keep;
        if on {
            self.marks.push(Mark {
                start: range.start,
                end: range.end,
                style: style.clone(),
            });
        }
        self.normalize();
        self.touch();
    }

    /// Whether every character in `range` carries a mark of this kind.
    pub fn has_style(&self, range: Range<usize>, style: &Style) -> bool {
        if range.is_empty() {
            return false;
        }
        let mut covered = range.start;
        let mut marks: Vec<&Mark> = self
            .marks
            .iter()
            .filter(|m| m.style.same_kind(style))
            .collect();
        marks.sort_by_key(|m| m.start);
        for mark in marks {
            if mark.start <= covered && mark.end > covered {
                covered = mark.end;
            }
        }
        covered >= range.end
    }

    pub fn link_at(&self, at: usize) -> Option<(Range<usize>, Rc<str>)> {
        self.marks.iter().find_map(|m| match &m.style {
            Style::Link(url) if m.start <= at && at <= m.end && m.start < m.end => {
                Some((m.start..m.end, url.clone()))
            }
            _ => None,
        })
    }

    /// The part of the block in `range`, as a new block with the same kind.
    pub fn slice(&self, range: Range<usize>) -> Block {
        let range = self.clamp(range);
        let mut out = self.clone();
        out.id = new_id();
        out.text = self.text[range.clone()].to_owned();
        out.marks = self
            .marks
            .iter()
            .filter(|m| m.end > range.start && m.start < range.end)
            .map(|m| Mark {
                start: m.start.max(range.start) - range.start,
                end: m.end.min(range.end) - range.start,
                style: m.style.clone(),
            })
            .collect();
        out.normalize();
        out.touch();
        out
    }

    /// Appends another block's text and marks.
    pub fn append(&mut self, other: &Block) {
        let base = self.text.len();
        self.text.push_str(&other.text);
        self.marks.extend(other.marks.iter().map(|m| Mark {
            start: m.start + base,
            end: m.end + base,
            style: m.style.clone(),
        }));
        self.normalize();
        self.touch();
    }

    pub fn clamp(&self, range: Range<usize>) -> Range<usize> {
        let end = floor_char(&self.text, range.end.min(self.text.len()));
        let start = floor_char(&self.text, range.start.min(end));
        start..end
    }

    /// Sorts marks, drops empty ones and merges touching marks of one style.
    pub fn normalize(&mut self) {
        let len = self.text.len();
        for m in &mut self.marks {
            m.end = floor_char(&self.text, m.end.min(len));
            m.start = floor_char(&self.text, m.start.min(m.end));
        }
        self.marks.retain(|m| m.start < m.end);
        self.marks.sort_by(|a, b| {
            (a.start, a.end, a.style.name()).cmp(&(b.start, b.end, b.style.name()))
        });
        let mut out: Vec<Mark> = Vec::with_capacity(self.marks.len());
        for mark in self.marks.drain(..) {
            if let Some(prev) = out
                .iter_mut()
                .rev()
                .find(|p| p.style == mark.style && p.end >= mark.start)
            {
                prev.end = prev.end.max(mark.end);
                continue;
            }
            out.push(mark);
        }
        // Marks of the same kind but a different link never overlap: the
        // later one wins.
        out.sort_by_key(|m| m.start);
        self.marks = out;
    }
}

pub fn floor_char(text: &str, mut at: usize) -> usize {
    at = at.min(text.len());
    while at > 0 && !text.is_char_boundary(at) {
        at -= 1;
    }
    at
}

/// A place in the document: a block index and a UTF-8 offset in its text.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, PartialOrd, Ord, Hash)]
pub struct Pos {
    pub block: usize,
    pub offset: usize,
}

impl Pos {
    pub fn new(block: usize, offset: usize) -> Self {
        Self { block, offset }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Selection {
    pub anchor: Pos,
    pub head: Pos,
    /// Whole blocks are selected (Esc, Shift-arrow past a block's edge,
    /// the second ⌘A): `anchor.block..=head.block`, in either order.
    pub blocks: bool,
}

impl Selection {
    pub fn caret(pos: Pos) -> Self {
        Self {
            anchor: pos,
            head: pos,
            blocks: false,
        }
    }
    pub fn range(anchor: Pos, head: Pos) -> Self {
        Self {
            anchor,
            head,
            blocks: false,
        }
    }
    pub fn block_range(anchor: usize, head: usize) -> Self {
        Self {
            anchor: Pos::new(anchor, 0),
            head: Pos::new(head, 0),
            blocks: true,
        }
    }
    pub fn is_caret(&self) -> bool {
        !self.blocks && self.anchor == self.head
    }
    pub fn start(&self) -> Pos {
        self.anchor.min(self.head)
    }
    pub fn end(&self) -> Pos {
        self.anchor.max(self.head)
    }
    pub fn block_span(&self) -> Range<usize> {
        let (a, b) = (self.anchor.block, self.head.block);
        a.min(b)..a.max(b) + 1
    }
}

/// The document: blocks shared with undo snapshots and layout caches.
#[derive(Clone, Debug, Default)]
pub struct Doc {
    pub blocks: Vec<Rc<Block>>,
}

impl PartialEq for Doc {
    fn eq(&self, other: &Self) -> bool {
        self.blocks.len() == other.blocks.len()
            && self
                .blocks
                .iter()
                .zip(&other.blocks)
                .all(|(a, b)| Rc::ptr_eq(a, b) || a == b)
    }
}

impl Doc {
    pub fn new(blocks: Vec<Block>) -> Self {
        let mut doc = Self {
            blocks: blocks.into_iter().map(Rc::new).collect(),
        };
        doc.ensure_nonempty();
        doc
    }
    pub fn ensure_nonempty(&mut self) {
        if self.is_empty() {
            self.blocks.push(Rc::new(Block::new(Kind::Paragraph, "")));
        }
    }
    pub fn len(&self) -> usize {
        self.blocks.len()
    }
    pub fn is_empty(&self) -> bool {
        self.blocks.is_empty()
    }
    pub fn block(&self, i: usize) -> &Block {
        &self.blocks[i]
    }
    pub fn block_mut(&mut self, i: usize) -> &mut Block {
        Rc::make_mut(&mut self.blocks[i])
    }
    pub fn clamp(&self, pos: Pos) -> Pos {
        let block = pos.block.min(self.blocks.len().saturating_sub(1));
        let text = &self.blocks[block].text;
        Pos::new(block, floor_char(text, pos.offset))
    }
    pub fn end(&self) -> Pos {
        let last = self.blocks.len() - 1;
        Pos::new(last, self.blocks[last].len())
    }

    /// Deletes the text between two positions, merging the blocks at either
    /// end. Returns where the caret goes.
    pub fn delete(&mut self, start: Pos, end: Pos) -> Pos {
        let (start, end) = (self.clamp(start.min(end)), self.clamp(start.max(end)));
        if start == end {
            return start;
        }
        if start.block == end.block {
            self.block_mut(start.block)
                .replace(start.offset..end.offset, "", &[]);
            return start;
        }
        let tail = self.blocks[end.block].slice(end.offset..self.blocks[end.block].len());
        {
            let first = self.block_mut(start.block);
            let len = first.len();
            first.replace(start.offset..len, "", &[]);
            first.append(&tail);
        }
        // A divider at the start has no text: the end block takes its place.
        if self.blocks[start.block].kind == Kind::Divider {
            let mut tail = tail;
            tail.kind = self.blocks[end.block].kind;
            tail.checked = self.blocks[end.block].checked;
            tail.indent = self.blocks[end.block].indent;
            self.blocks[start.block] = Rc::new(tail);
        }
        self.blocks.drain(start.block + 1..=end.block);
        start
    }

    /// Splits the block at `pos`; the new block after it gets `kind`.
    pub fn split(&mut self, pos: Pos, kind: Kind) -> Pos {
        let pos = self.clamp(pos);
        let source = &self.blocks[pos.block];
        let mut tail = source.slice(pos.offset..source.len());
        tail.kind = kind;
        tail.checked = false;
        tail.indent = if kind.indents() { source.indent } else { 0 };
        let len = source.len();
        self.block_mut(pos.block).replace(pos.offset..len, "", &[]);
        self.blocks.insert(pos.block + 1, Rc::new(tail));
        Pos::new(pos.block + 1, 0)
    }

    /// Joins block `i` onto the end of block `i - 1`. Returns the junction.
    pub fn merge_into_previous(&mut self, i: usize) -> Option<Pos> {
        if i == 0 || i >= self.blocks.len() {
            return None;
        }
        if self.blocks[i - 1].kind == Kind::Divider {
            self.blocks.remove(i - 1);
            return Some(Pos::new(i - 1, 0));
        }
        let next = self.blocks.remove(i);
        let prev = self.block_mut(i - 1);
        let at = prev.len();
        prev.append(&next);
        Some(Pos::new(i - 1, at))
    }

    #[cfg(test)]
    /// The number shown before a numbered item: counting restarts after any
    /// block that is not a numbered item at this depth.
    pub fn number_of(&self, i: usize) -> usize {
        let indent = self.blocks[i].indent;
        let mut n = 1;
        let mut j = i;
        while j > 0 {
            j -= 1;
            let b = &self.blocks[j];
            if b.indent > indent && (b.kind.is_list() || b.kind == Kind::Paragraph) {
                continue;
            }
            if b.kind == Kind::Numbered && b.indent == indent {
                n += 1;
                continue;
            }
            break;
        }
        n
    }

    /// The block and the blocks nested under it (deeper indent right after).
    pub fn subtree(&self, i: usize) -> Range<usize> {
        let indent = self.blocks[i].indent;
        let mut end = i + 1;
        while end < self.blocks.len() && self.blocks[end].indent > indent {
            end += 1;
        }
        i..end
    }

    // ---- JSON ---------------------------------------------------------------

    pub fn to_json(&self) -> Value {
        Value::Array(self.blocks.iter().map(|b| block_to_json(b)).collect())
    }

    pub fn from_json(value: &Value) -> Doc {
        let blocks = value
            .as_array()
            .map(|items| items.iter().filter_map(block_from_json).collect())
            .unwrap_or_default();
        Doc::new(blocks)
    }
}

pub fn block_to_json(b: &Block) -> Value {
    let mut map = Map::new();
    map.insert("id".into(), json!(&*b.id));
    map.insert("type".into(), json!(b.kind.name()));
    map.insert("text".into(), json!(b.text));
    if !b.marks.is_empty() {
        map.insert(
            "marks".into(),
            Value::Array(
                b.marks
                    .iter()
                    .map(|m| {
                        // Offsets in the JSON are UTF-16 code units, as in JS.
                        let start = utf16_len(&b.text[..m.start]);
                        let end = start + utf16_len(&b.text[m.start..m.end]);
                        let mut v = json!({"type": m.style.name(), "start": start, "end": end});
                        if let Style::Link(url) = &m.style {
                            v["url"] = json!(&**url);
                        }
                        v
                    })
                    .collect(),
            ),
        );
    }
    if b.kind == Kind::Todo {
        map.insert("checked".into(), json!(b.checked));
    }
    if b.indent > 0 {
        map.insert("indent".into(), json!(b.indent));
    }
    Value::Object(map)
}

pub fn block_from_json(v: &Value) -> Option<Block> {
    if let Some(text) = v.as_str() {
        return Some(Block::new(Kind::Paragraph, text));
    }
    let obj = v.as_object()?;
    let kind = obj
        .get("type")
        .or_else(|| obj.get("kind"))
        .and_then(Value::as_str)
        .and_then(Kind::parse)
        .unwrap_or(Kind::Paragraph);
    let text = if kind == Kind::Divider {
        String::new()
    } else {
        obj.get("text")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned()
    };
    let mut block = Block::new(kind, text);
    if let Some(id) = obj
        .get("id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
    {
        block.id = id.into();
    }
    block.checked = obj.get("checked").and_then(Value::as_bool).unwrap_or(false);
    block.indent = obj
        .get("indent")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        .min(MAX_INDENT as u64) as u8;
    if let Some(marks) = obj.get("marks").and_then(Value::as_array) {
        for m in marks {
            let style = match m["type"].as_str().unwrap_or("") {
                "bold" => Style::Bold,
                "italic" => Style::Italic,
                "code" => Style::Code,
                "strike" | "strikethrough" => Style::Strike,
                "link" => match m["url"].as_str() {
                    Some(url) => Style::Link(url.into()),
                    None => continue,
                },
                _ => continue,
            };
            let (Some(start), Some(end)) = (m["start"].as_u64(), m["end"].as_u64()) else {
                continue;
            };
            let start = utf8_offset(&block.text, start as usize);
            let end = utf8_offset(&block.text, end as usize);
            if start < end {
                block.marks.push(Mark { start, end, style });
            }
        }
        block.normalize();
    }
    Some(block)
}

pub fn utf16_len(text: &str) -> usize {
    text.chars().map(char::len_utf16).sum()
}

/// The UTF-8 offset of a UTF-16 offset, clamped to the text.
pub fn utf8_offset(text: &str, utf16: usize) -> usize {
    let mut count = 0;
    for (i, c) in text.char_indices() {
        if count >= utf16 {
            return i;
        }
        count += c.len_utf16();
    }
    text.len()
}

// ---- Words and characters ---------------------------------------------------

pub fn prev_char(text: &str, at: usize) -> usize {
    let at = floor_char(text, at);
    // Step over a whole grapheme-ish unit: a char plus following combining
    // marks, variation selectors and zero-width joiners.
    let mut i = at;
    loop {
        let Some((j, c)) = text[..i].char_indices().next_back() else {
            return 0;
        };
        i = j;
        if !is_joining(c) {
            // Emoji joined with ZWJ: keep going over the join.
            if let Some((k, p)) = text[..i].char_indices().next_back()
                && p == '\u{200d}'
            {
                i = k;
                continue;
            }
            return i;
        }
    }
}

pub fn next_char(text: &str, at: usize) -> usize {
    let at = floor_char(text, at);
    let mut chars = text[at..].char_indices().peekable();
    let Some((_, _)) = chars.next() else {
        return text.len();
    };
    let mut end = at + text[at..].chars().next().map(char::len_utf8).unwrap_or(0);
    while let Some(c) = text[end..].chars().next() {
        if is_joining(c) {
            end += c.len_utf8();
            if c == '\u{200d}'
                && let Some(n) = text[end..].chars().next()
            {
                end += n.len_utf8();
            }
        } else {
            break;
        }
    }
    end
}

fn is_joining(c: char) -> bool {
    matches!(c as u32,
        0x0300..=0x036F | 0x1AB0..=0x1AFF | 0x20D0..=0x20FF | 0xFE00..=0xFE0F | 0x200D
        | 0x1F3FB..=0x1F3FF | 0xE0020..=0xE007F)
}

fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '\''
}

/// Start of the word before `at` (Option-Left).
pub fn prev_word(text: &str, at: usize) -> usize {
    let mut i = floor_char(text, at);
    // Skip non-word characters, then the word.
    while i > 0 {
        let c = text[..i].chars().next_back().unwrap();
        if is_word(c) {
            break;
        }
        i -= c.len_utf8();
    }
    while i > 0 {
        let c = text[..i].chars().next_back().unwrap();
        if !is_word(c) {
            break;
        }
        i -= c.len_utf8();
    }
    i
}

/// End of the word after `at` (Option-Right).
pub fn next_word(text: &str, at: usize) -> usize {
    let mut i = floor_char(text, at);
    while i < text.len() {
        let c = text[i..].chars().next().unwrap();
        if is_word(c) {
            break;
        }
        i += c.len_utf8();
    }
    while i < text.len() {
        let c = text[i..].chars().next().unwrap();
        if !is_word(c) {
            break;
        }
        i += c.len_utf8();
    }
    i
}

/// The word around `at` (double-click).
pub fn word_at(text: &str, at: usize) -> Range<usize> {
    let at = floor_char(text, at);
    let after = text[at..].chars().next();
    let before = text[..at].chars().next_back();
    let word = match (before, after) {
        (_, Some(c)) if is_word(c) => true,
        (Some(c), _) if is_word(c) => true,
        _ => false,
    };
    if !word {
        // Whitespace or punctuation: select that run of characters.
        let Some(c) = after.or(before) else {
            return at..at;
        };
        let class = |x: char| x.is_whitespace() == c.is_whitespace() && !is_word(x);
        let mut s = at;
        while let Some(p) = text[..s].chars().next_back().filter(|p| class(*p)) {
            s -= p.len_utf8();
        }
        let mut e = at;
        while let Some(n) = text[e..].chars().next().filter(|n| class(*n)) {
            e += n.len_utf8();
        }
        return s..e;
    }
    let mut s = at;
    while let Some(p) = text[..s].chars().next_back().filter(|p| is_word(*p)) {
        s -= p.len_utf8();
    }
    let mut e = at;
    while let Some(n) = text[e..].chars().next().filter(|n| is_word(*n)) {
        e += n.len_utf8();
    }
    s..e
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bold(start: usize, end: usize) -> Mark {
        Mark {
            start,
            end,
            style: Style::Bold,
        }
    }

    #[test]
    fn typing_inside_and_after_a_mark_extends_it() {
        let mut b = Block::new(Kind::Paragraph, "hello world");
        b.set_style(0..5, &Style::Bold, true);
        let styles = b.styles_at(5);
        b.replace(5..5, "!", &styles);
        assert_eq!(b.text, "hello! world");
        assert_eq!(b.marks, vec![bold(0, 6)]);
        let styles = b.styles_at(8);
        b.replace(8..8, "x", &styles);
        assert_eq!(b.marks, vec![bold(0, 6)]);
    }

    #[test]
    fn plain_text_inside_a_mark_splits_it() {
        let mut b = Block::new(Kind::Paragraph, "abcd");
        b.set_style(0..4, &Style::Bold, true);
        b.replace(2..2, "X", &[]);
        assert_eq!(b.marks, vec![bold(0, 2), bold(3, 5)]);
    }

    #[test]
    fn deleting_shrinks_and_drops_marks() {
        let mut b = Block::new(Kind::Paragraph, "abcdef");
        b.set_style(1..3, &Style::Bold, true);
        b.set_style(4..6, &Style::Italic, true);
        b.replace(0..4, "", &[]);
        assert_eq!(b.text, "ef");
        assert_eq!(b.marks.len(), 1);
        assert_eq!(b.marks[0].style, Style::Italic);
        assert_eq!((b.marks[0].start, b.marks[0].end), (0, 2));
    }

    #[test]
    fn toggling_a_style_merges_and_splits() {
        let mut b = Block::new(Kind::Paragraph, "abcdef");
        b.set_style(0..2, &Style::Bold, true);
        b.set_style(2..4, &Style::Bold, true);
        assert_eq!(b.marks, vec![bold(0, 4)]);
        assert!(b.has_style(1..3, &Style::Bold));
        b.set_style(1..2, &Style::Bold, false);
        assert_eq!(b.marks, vec![bold(0, 1), bold(2, 4)]);
        assert!(!b.has_style(0..3, &Style::Bold));
    }

    #[test]
    fn split_and_merge_keep_marks() {
        let mut doc = Doc::new(vec![Block::new(Kind::Bullet, "hello world")]);
        doc.block_mut(0).set_style(3..8, &Style::Bold, true);
        let at = doc.split(Pos::new(0, 5), Kind::Bullet);
        assert_eq!(at, Pos::new(1, 0));
        assert_eq!(doc.block(0).text, "hello");
        assert_eq!(doc.block(1).text, " world");
        assert_eq!(doc.block(0).marks, vec![bold(3, 5)]);
        assert_eq!(doc.block(1).marks, vec![bold(0, 3)]);
        let junction = doc.merge_into_previous(1).unwrap();
        assert_eq!(junction, Pos::new(0, 5));
        assert_eq!(doc.block(0).text, "hello world");
        assert_eq!(doc.block(0).marks, vec![bold(3, 8)]);
    }

    #[test]
    fn cross_block_delete_merges_the_ends() {
        let mut doc = Doc::new(vec![
            Block::new(Kind::H1, "Title here"),
            Block::new(Kind::Paragraph, "middle"),
            Block::new(Kind::Bullet, "last item"),
        ]);
        let at = doc.delete(Pos::new(0, 5), Pos::new(2, 4));
        assert_eq!(at, Pos::new(0, 5));
        assert_eq!(doc.len(), 1);
        assert_eq!(doc.block(0).text, "Title item");
        assert_eq!(doc.block(0).kind, Kind::H1);
    }

    #[test]
    fn numbering_restarts_after_other_blocks() {
        let mut items = vec![
            Block::new(Kind::Numbered, "a"),
            Block::new(Kind::Numbered, "b"),
            Block::new(Kind::Bullet, "nested"),
            Block::new(Kind::Numbered, "c"),
            Block::new(Kind::Paragraph, "break"),
            Block::new(Kind::Numbered, "d"),
        ];
        items[2].indent = 1;
        let doc = Doc::new(items);
        assert_eq!(doc.number_of(0), 1);
        assert_eq!(doc.number_of(1), 2);
        assert_eq!(doc.number_of(3), 3);
        assert_eq!(doc.number_of(5), 1);
    }

    #[test]
    fn json_round_trips_with_utf16_offsets() {
        let mut b = Block::new(Kind::Todo, "😀 bold");
        b.checked = true;
        b.set_style(5..9, &Style::Bold, true);
        b.set_style(0..4, &Style::Link("https://x.dev".into()), true);
        let doc = Doc::new(vec![b]);
        let json = doc.to_json();
        assert_eq!(json[0]["marks"][1]["start"], 3);
        assert_eq!(json[0]["checked"], true);
        let back = Doc::from_json(&json);
        assert_eq!(back.block(0), doc.block(0));
    }

    #[test]
    fn words_and_characters() {
        assert_eq!(prev_word("hello big world", 15), 10);
        assert_eq!(prev_word("hello big world", 10), 6);
        assert_eq!(next_word("hello big world", 5), 9);
        assert_eq!(word_at("hello big world", 7), 6..9);
        let family = "a👨‍👩‍👧b";
        let end = family.len() - 1;
        assert_eq!(prev_char(family, end), 1);
        assert_eq!(next_char(family, 1), end);
    }
}
