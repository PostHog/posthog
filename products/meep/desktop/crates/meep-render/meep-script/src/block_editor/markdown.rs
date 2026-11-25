//! Markdown and HTML in and out of blocks: copy writes Markdown, paste reads
//! Markdown, plain text or HTML, and scripts convert with `toMarkdown` and
//! `fromMarkdown`. Deliberately small: the block kinds and marks the editor
//! has, nothing more.
use super::model::{Block, Kind, Mark, Style};
use std::rc::Rc;

// ---- Blocks to Markdown -------------------------------------------------------

pub fn to_markdown(blocks: &[Rc<Block>]) -> String {
    let mut out = String::new();
    let mut numbers: Vec<usize> = Vec::new();
    for (i, block) in blocks.iter().enumerate() {
        if i > 0 {
            let prev = &blocks[i - 1];
            let tight = prev.kind.is_list() && block.kind.is_list();
            out.push_str(if tight { "\n" } else { "\n\n" });
        }
        let depth = block.indent as usize;
        numbers.truncate(depth + 1);
        while numbers.len() <= depth {
            numbers.push(0);
        }
        if block.kind == Kind::Numbered {
            numbers[depth] += 1;
        } else {
            numbers[depth] = 0;
        }
        let pad = "    ".repeat(depth);
        let body = inline_markdown(block);
        let lines = |prefix: &str, cont: &str| -> String {
            body.split('\n')
                .enumerate()
                .map(|(i, l)| format!("{}{}{l}", pad, if i == 0 { prefix } else { cont }))
                .collect::<Vec<_>>()
                .join("\n")
        };
        match block.kind {
            Kind::Paragraph => {
                let text = lines("", "");
                // A paragraph that looks like another block keeps its text.
                out.push_str(&escape_line_start(&text));
            }
            Kind::H1 => out.push_str(&lines("# ", "")),
            Kind::H2 => out.push_str(&lines("## ", "")),
            Kind::H3 => out.push_str(&lines("### ", "")),
            Kind::Bullet => out.push_str(&lines("- ", "  ")),
            Kind::Numbered => {
                let marker = format!("{}. ", numbers[depth]);
                let cont = " ".repeat(marker.len());
                out.push_str(&lines(&marker, &cont));
            }
            Kind::Todo => {
                let marker = if block.checked { "- [x] " } else { "- [ ] " };
                out.push_str(&lines(marker, "      "));
            }
            Kind::Quote => out.push_str(&lines("> ", "> ")),
            Kind::Code => {
                let fence = if block.text.contains("```") {
                    "~~~~"
                } else {
                    "```"
                };
                out.push_str(&format!("{pad}{fence}\n"));
                for line in block.text.split('\n') {
                    out.push_str(&format!("{pad}{line}\n"));
                }
                out.push_str(&format!("{pad}{fence}"));
            }
            Kind::Divider => out.push_str(&format!("{pad}---")),
        }
    }
    out
}

fn escape_line_start(text: &str) -> String {
    text.split('\n')
        .map(|line| {
            let t = line.trim_start();
            let risky = t.starts_with('#')
                || t.starts_with("- ")
                || t.starts_with("+ ")
                || t.starts_with("> ")
                || t == "---"
                || t.starts_with("```")
                || numbered_marker(t).is_some();
            if risky {
                format!("\\{line}")
            } else {
                line.to_owned()
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn escape_inline(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        if matches!(c, '\\' | '*' | '`' | '[' | ']' | '~' | '_') {
            out.push('\\');
        }
        out.push(c);
    }
    out
}

fn delimiter(style: &Style) -> &'static str {
    match style {
        Style::Bold => "**",
        Style::Italic => "*",
        Style::Code => "`",
        Style::Strike => "~~",
        Style::Link(_) => "[",
    }
}

/// A block's text with its marks as Markdown delimiters.
pub fn inline_markdown(block: &Block) -> String {
    if block.kind == Kind::Code {
        return block.text.clone();
    }
    let text = &block.text;
    let mut cuts: Vec<usize> = vec![0, text.len()];
    for m in &block.marks {
        cuts.push(m.start);
        cuts.push(m.end);
    }
    cuts.sort_unstable();
    cuts.dedup();
    let mut out = String::new();
    let mut open: Vec<Style> = Vec::new();
    let close = |style: &Style, out: &mut String| match style {
        Style::Link(url) => out.push_str(&format!("]({url})")),
        other => out.push_str(delimiter(other)),
    };
    for w in cuts.windows(2) {
        let (a, b) = (w[0], w[1]);
        let mut active: Vec<Style> = block
            .marks
            .iter()
            .filter(|m| m.start <= a && m.end >= b)
            .map(|m| m.style.clone())
            .collect();
        // Links outermost, code innermost.
        active.sort_by_key(|s| match s {
            Style::Link(_) => 0,
            Style::Bold => 1,
            Style::Italic => 2,
            Style::Strike => 3,
            Style::Code => 4,
        });
        // Close everything above the first style no longer active.
        let keep = open.iter().take_while(|s| active.contains(s)).count();
        while open.len() > keep {
            let s = open.pop().unwrap();
            close(&s, &mut out);
        }
        for s in active {
            if !open.contains(&s) {
                out.push_str(delimiter(&s));
                open.push(s);
            }
        }
        let segment = &text[a..b];
        if open.contains(&Style::Code) {
            out.push_str(segment);
        } else {
            out.push_str(&escape_inline(segment));
        }
    }
    while let Some(s) = open.pop() {
        close(&s, &mut out);
    }
    out
}

// ---- Markdown to blocks -------------------------------------------------------

fn numbered_marker(t: &str) -> Option<usize> {
    let digits = t.bytes().take_while(u8::is_ascii_digit).count();
    if digits == 0 || digits > 9 {
        return None;
    }
    let rest = &t[digits..];
    if rest.starts_with(". ") || rest.starts_with(") ") {
        Some(digits + 2)
    } else {
        None
    }
}

fn leading_spaces(line: &str) -> usize {
    let mut n = 0;
    for c in line.chars() {
        match c {
            ' ' => n += 1,
            '\t' => n += 4,
            _ => break,
        }
    }
    n
}

/// Parses Markdown into blocks. Blank lines separate paragraphs; lines
/// inside a paragraph stay as soft line breaks.
pub fn from_markdown(source: &str) -> Vec<Block> {
    let source = source.replace("\r\n", "\n").replace('\r', "\n");
    let lines: Vec<&str> = source.split('\n').collect();
    let mut blocks: Vec<Block> = Vec::new();
    // Indentation columns of the open list items, for nesting.
    let mut stack: Vec<usize> = Vec::new();
    let mut i = 0;
    // Whether the last block can take a continuation line.
    let mut open_paragraph = false;
    while i < lines.len() {
        let raw = lines[i];
        let line = raw.trim_end();
        let spaces = leading_spaces(line);
        let t = line.trim_start();
        i += 1;
        if t.is_empty() {
            open_paragraph = false;
            continue;
        }
        // Fenced code.
        if t.starts_with("```") || t.starts_with("~~~") {
            let fence: String = t.chars().take_while(|c| *c == '`' || *c == '~').collect();
            let mut body = Vec::new();
            while i < lines.len() {
                let l = lines[i];
                i += 1;
                if l.trim_start().starts_with(&fence) {
                    break;
                }
                // Drop the fence's indentation from the body.
                let strip = leading_spaces(l).min(spaces);
                body.push(l.chars().skip(strip).collect::<String>());
            }
            blocks.push(Block::new(Kind::Code, body.join("\n")));
            open_paragraph = false;
            stack.clear();
            continue;
        }
        if matches!(t, "---" | "***" | "___" | "- - -" | "* * *") {
            blocks.push(Block::new(Kind::Divider, ""));
            open_paragraph = false;
            stack.clear();
            continue;
        }
        let heading = t.bytes().take_while(|b| *b == b'#').count();
        if (1..=6).contains(&heading) && t[heading..].starts_with(' ') {
            let kind = match heading {
                1 => Kind::H1,
                2 => Kind::H2,
                _ => Kind::H3,
            };
            blocks.push(inline_block(kind, t[heading..].trim()));
            open_paragraph = false;
            stack.clear();
            continue;
        }
        if let Some(rest) = t.strip_prefix('>') {
            let rest = rest.strip_prefix(' ').unwrap_or(rest);
            // Consecutive quote lines are one quote.
            if let Some(last) = blocks.last_mut()
                && last.kind == Kind::Quote
                && open_paragraph
            {
                let extra = inline_block(Kind::Quote, rest);
                let mut joined = Block::new(Kind::Quote, "\n");
                joined.append(&extra);
                last.append(&joined);
            } else {
                blocks.push(inline_block(Kind::Quote, rest));
            }
            open_paragraph = true;
            stack.clear();
            continue;
        }
        let list = if let Some(rest) = t
            .strip_prefix("- ")
            .or_else(|| t.strip_prefix("* "))
            .or_else(|| t.strip_prefix("+ "))
        {
            let (kind, checked, rest) = if let Some(r) = rest.strip_prefix("[ ] ") {
                (Kind::Todo, false, r)
            } else if let Some(r) = rest
                .strip_prefix("[x] ")
                .or_else(|| rest.strip_prefix("[X] "))
            {
                (Kind::Todo, true, r)
            } else if rest == "[ ]" {
                (Kind::Todo, false, "")
            } else if rest == "[x]" || rest == "[X]" {
                (Kind::Todo, true, "")
            } else {
                (Kind::Bullet, false, rest)
            };
            Some((kind, checked, rest.to_owned()))
        } else if matches!(t, "-" | "*" | "+") {
            Some((Kind::Bullet, false, String::new()))
        } else {
            numbered_marker(t).map(|n| (Kind::Numbered, false, t[n..].to_owned()))
        };
        if let Some((kind, checked, rest)) = list {
            while stack.last().is_some_and(|col| *col > spaces) {
                stack.pop();
            }
            if stack.last() != Some(&spaces) {
                stack.push(spaces);
            }
            let mut block = inline_block(kind, rest.trim());
            block.checked = checked;
            block.indent = (stack.len() - 1).min(super::model::MAX_INDENT as usize) as u8;
            blocks.push(block);
            open_paragraph = true;
            continue;
        }
        // A continuation line of a paragraph, list item or quote.
        let continues = open_paragraph
            && blocks.last().is_some_and(|b| {
                matches!(b.kind, Kind::Paragraph | Kind::Quote) || b.kind.is_list()
            });
        if continues {
            let last = blocks.last_mut().unwrap();
            let extra = inline_block(Kind::Paragraph, t);
            let mut joined = Block::new(Kind::Paragraph, "\n");
            joined.append(&extra);
            last.append(&joined);
            continue;
        }
        let text = t.strip_prefix('\\').unwrap_or(t);
        let mut block = inline_block(Kind::Paragraph, text);
        if !stack.is_empty() && spaces > 0 {
            block.indent = stack.len().min(super::model::MAX_INDENT as usize) as u8;
        } else {
            stack.clear();
        }
        blocks.push(block);
        open_paragraph = true;
    }
    blocks
}

fn inline_block(kind: Kind, source: &str) -> Block {
    let (text, marks) = parse_inline(source);
    let mut block = Block::new(kind, text);
    block.marks = marks;
    block.normalize();
    block
}

/// Inline Markdown: `**bold**`, `__bold__`, `*italic*`, `_italic_`,
/// `` `code` ``, `~~strike~~`, `[text](url)` and backslash escapes.
pub fn parse_inline(source: &str) -> (String, Vec<Mark>) {
    let chars: Vec<char> = source.chars().collect();
    let mut text = String::new();
    let mut marks = Vec::new();
    // Open delimiters: (delimiter, byte offset in `text`).
    let mut open: Vec<(&'static str, usize)> = Vec::new();
    let mut links: Vec<usize> = Vec::new();
    let mut i = 0;
    let at = |i: usize, s: &str| -> bool {
        let n = s.chars().count();
        i + n <= chars.len() && chars[i..i + n].iter().copied().eq(s.chars())
    };
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' && i + 1 < chars.len() && chars[i + 1].is_ascii_punctuation() {
            text.push(chars[i + 1]);
            i += 2;
            continue;
        }
        if c == '`' {
            // Code spans take everything up to the closing backtick.
            if let Some(close) = (i + 1..chars.len()).find(|j| chars[*j] == '`') {
                let start = text.len();
                text.extend(&chars[i + 1..close]);
                if text.len() > start {
                    marks.push(Mark {
                        start,
                        end: text.len(),
                        style: Style::Code,
                    });
                }
                i = close + 1;
                continue;
            }
        }
        if c == '[' {
            links.push(text.len());
            i += 1;
            continue;
        }
        if c == ']'
            && !links.is_empty()
            && i + 1 < chars.len()
            && chars[i + 1] == '('
            && let Some(close) = (i + 2..chars.len()).find(|j| chars[*j] == ')')
        {
            let url: String = chars[i + 2..close].iter().collect();
            let start = links.pop().unwrap();
            if !url.trim().is_empty() && text.len() > start {
                marks.push(Mark {
                    start,
                    end: text.len(),
                    style: Style::Link(url.trim().into()),
                });
            }
            i = close + 1;
            continue;
        }
        let mut matched = false;
        for (delim, style) in [
            ("**", Style::Bold),
            ("__", Style::Bold),
            ("~~", Style::Strike),
            ("*", Style::Italic),
            ("_", Style::Italic),
        ] {
            if !at(i, delim) {
                continue;
            }
            let len = delim.chars().count();
            if let Some(pos) = open.iter().rposition(|(d, _)| *d == delim) {
                let (_, start) = open.remove(pos);
                if text.len() > start {
                    marks.push(Mark {
                        start,
                        end: text.len(),
                        style,
                    });
                }
                i += len;
                matched = true;
                break;
            }
            // Opening only if a closing delimiter follows and the next
            // character is not whitespace (so "2 * 3" stays text). An
            // underscore inside a word is text.
            let next = chars.get(i + len).copied();
            let prev = if i > 0 { Some(chars[i - 1]) } else { None };
            let intraword = delim.starts_with('_') && prev.is_some_and(char::is_alphanumeric);
            let closes = (i + len..chars.len()).any(|j| at(j, delim));
            if closes && next.is_some_and(|n| !n.is_whitespace()) && !intraword {
                open.push((delim, text.len()));
                i += len;
                matched = true;
                break;
            }
        }
        if matched {
            continue;
        }
        if c == '[' || c == ']' {
            text.push(c);
            i += 1;
            continue;
        }
        text.push(c);
        i += 1;
    }
    // Unclosed brackets were literal text; their positions are already in
    // the text because `[` was skipped: put them back.
    if !links.is_empty() {
        let mut fixed = String::new();
        let mut shift: Vec<(usize, usize)> = Vec::new();
        let mut last = 0;
        for (n, at) in links.iter().enumerate() {
            fixed.push_str(&text[last..*at]);
            fixed.push('[');
            shift.push((*at, n + 1));
            last = *at;
        }
        fixed.push_str(&text[last..]);
        let moved = |p: usize, end: bool| -> usize {
            p + shift
                .iter()
                .filter(|(at, _)| if end { *at < p } else { *at <= p })
                .count()
        };
        for m in &mut marks {
            m.start = moved(m.start, false);
            m.end = moved(m.end, true);
        }
        text = fixed;
    }
    (text, marks)
}

/// Pasted plain text: Markdown when it looks like Markdown, otherwise
/// paragraphs separated by blank lines.
pub fn from_plain(text: &str) -> Vec<Block> {
    from_markdown(text)
}

// ---- HTML to blocks -----------------------------------------------------------

/// Rich text from a browser or another editor: the block structure and the
/// marks the editor knows, everything else as plain text.
pub fn from_html(html: &str) -> Vec<Block> {
    let mut p = HtmlParser::default();
    p.run(html);
    p.flush();
    p.blocks
        .into_iter()
        .filter(|b| b.kind == Kind::Divider || b.kind == Kind::Code || !b.text.trim().is_empty())
        .map(|mut b| {
            if b.kind != Kind::Code {
                trim_block(&mut b);
            }
            b
        })
        .collect()
}

fn trim_block(b: &mut Block) {
    let start = b.text.len() - b.text.trim_start().len();
    let end = b.text.trim_end().len();
    if start > 0 || end < b.text.len() {
        let mut out = b.slice(start..end.max(start));
        out.id = b.id.clone();
        *b = out;
    }
}

#[derive(Default)]
struct HtmlParser {
    blocks: Vec<Block>,
    current: Option<Block>,
    styles: Vec<(String, Option<Style>)>,
    lists: Vec<Kind>,
    pre: usize,
    quote: usize,
    skip: usize,
    pending_check: Option<bool>,
    heading: Option<Kind>,
}

impl HtmlParser {
    fn kind_here(&self) -> Kind {
        if self.pre > 0 {
            Kind::Code
        } else if let Some(h) = self.heading {
            h
        } else if self.quote > 0 {
            Kind::Quote
        } else {
            Kind::Paragraph
        }
    }
    fn flush(&mut self) {
        if let Some(b) = self.current.take() {
            self.blocks.push(b);
        }
    }
    fn start_block(&mut self, kind: Kind) {
        self.flush();
        let mut b = Block::new(kind, "");
        if kind.is_list() || kind == Kind::Paragraph {
            b.indent = self.lists.len().saturating_sub(1) as u8;
        }
        self.current = Some(b);
    }
    fn text(&mut self, s: &str) {
        if self.skip > 0 {
            return;
        }
        let s = if self.pre > 0 {
            s.to_owned()
        } else {
            collapse_ws(s)
        };
        if s.is_empty() {
            return;
        }
        if self.current.is_none() {
            if s.trim().is_empty() {
                return;
            }
            let kind = self.kind_here();
            self.start_block(kind);
        }
        let b = self.current.as_mut().unwrap();
        // Collapse whitespace across element boundaries.
        let s = if self.pre == 0 && (b.text.is_empty() || b.text.ends_with([' ', '\n'])) {
            s.trim_start().to_owned()
        } else {
            s
        };
        if s.is_empty() {
            return;
        }
        if let Some(checked) = self.pending_check.take() {
            b.kind = Kind::Todo;
            b.checked = checked;
        }
        let styles: Vec<Style> = self.styles.iter().filter_map(|(_, s)| s.clone()).collect();
        let at = b.text.len();
        b.replace(at..at, &s, &styles);
    }
    fn run(&mut self, html: &str) {
        let mut rest = html;
        while !rest.is_empty() {
            if let Some(lt) = rest.find('<') {
                if lt > 0 {
                    let t = decode_entities(&rest[..lt]);
                    self.text(&t);
                }
                rest = &rest[lt..];
                if rest.starts_with("<!--") {
                    rest = rest.find("-->").map(|e| &rest[e + 3..]).unwrap_or("");
                    continue;
                }
                let Some(gt) = rest.find('>') else {
                    break;
                };
                let tag = &rest[1..gt];
                rest = &rest[gt + 1..];
                self.tag(tag);
            } else {
                let t = decode_entities(rest);
                self.text(&t);
                break;
            }
        }
    }
    fn tag(&mut self, raw: &str) {
        let closing = raw.starts_with('/');
        let body = raw.trim_start_matches('/').trim_end_matches('/');
        let name: String = body
            .chars()
            .take_while(|c| c.is_ascii_alphanumeric())
            .collect::<String>()
            .to_ascii_lowercase();
        let attrs = &body[name.len().min(body.len())..];
        match (name.as_str(), closing) {
            ("script" | "style" | "head" | "title", false) => self.skip += 1,
            ("script" | "style" | "head" | "title", true) => {
                self.skip = self.skip.saturating_sub(1)
            }
            ("p" | "div" | "section" | "article" | "header" | "footer", false) => {
                if self.pre == 0
                    && !self
                        .current
                        .as_ref()
                        .is_some_and(|b| b.kind.is_list() && b.text.is_empty())
                {
                    self.flush();
                }
            }
            ("p" | "div" | "section" | "article" | "header" | "footer", true) => {
                if self.pre == 0 && self.lists.is_empty() {
                    self.flush();
                }
            }
            ("h1" | "h2" | "h3" | "h4" | "h5" | "h6", false) => {
                let kind = match name.as_str() {
                    "h1" => Kind::H1,
                    "h2" => Kind::H2,
                    _ => Kind::H3,
                };
                self.heading = Some(kind);
                self.start_block(kind);
            }
            ("h1" | "h2" | "h3" | "h4" | "h5" | "h6", true) => {
                self.heading = None;
                self.flush();
            }
            ("ul", false) => self.lists.push(Kind::Bullet),
            ("ol", false) => self.lists.push(Kind::Numbered),
            ("ul" | "ol", true) => {
                self.lists.pop();
                self.flush();
            }
            ("li", false) => {
                let kind = self.lists.last().copied().unwrap_or(Kind::Bullet);
                self.start_block(kind);
                if attrs.contains("task-list-item") || attrs.contains("checked") {
                    // GitHub task lists put the checkbox inside.
                }
            }
            ("li", true) => self.flush(),
            ("input", false) if attrs.contains("checkbox") => {
                self.pending_check = Some(attrs.contains("checked"));
                if let Some(b) = self.current.as_mut() {
                    b.kind = Kind::Todo;
                    b.checked = attrs.contains("checked");
                    self.pending_check = None;
                }
            }
            ("blockquote", false) => {
                self.quote += 1;
                self.start_block(Kind::Quote);
            }
            ("blockquote", true) => {
                self.quote = self.quote.saturating_sub(1);
                self.flush();
            }
            ("pre", false) => {
                self.pre += 1;
                self.start_block(Kind::Code);
            }
            ("pre", true) => {
                self.pre = self.pre.saturating_sub(1);
                if let Some(b) = self.current.as_mut() {
                    let trimmed = b.text.trim_end_matches('\n').len();
                    let len = b.text.len();
                    b.replace(trimmed..len, "", &[]);
                }
                self.flush();
            }
            ("hr", _) => {
                self.flush();
                self.blocks.push(Block::new(Kind::Divider, ""));
            }
            ("br", _) => {
                if let Some(b) = self.current.as_mut() {
                    let at = b.text.len();
                    b.replace(at..at, "\n", &[]);
                } else if self.pre == 0 {
                    self.flush();
                }
            }
            ("b" | "strong", false) => self.styles.push((name, Some(Style::Bold))),
            ("i" | "em", false) => self.styles.push((name, Some(Style::Italic))),
            ("s" | "del" | "strike", false) => self.styles.push((name, Some(Style::Strike))),
            ("code" | "kbd" | "samp", false) if self.pre == 0 => {
                self.styles.push((name, Some(Style::Code)))
            }
            ("a", false) => {
                let url = attr(attrs, "href").map(|u| Style::Link(decode_entities(&u).into()));
                self.styles.push((name, url));
            }
            ("span", false) => {
                let style = attr(attrs, "style")
                    .unwrap_or_default()
                    .to_ascii_lowercase();
                let compact: String = style.chars().filter(|c| !c.is_whitespace()).collect();
                let s = if compact.contains("font-weight:700")
                    || compact.contains("font-weight:bold")
                    || compact.contains("font-weight:600")
                {
                    Some(Style::Bold)
                } else if compact.contains("font-style:italic") {
                    Some(Style::Italic)
                } else if compact.contains("line-through") {
                    Some(Style::Strike)
                } else {
                    None
                };
                self.styles.push((name, s));
            }
            (n, true) if !n.is_empty() => {
                if let Some(pos) = self.styles.iter().rposition(|(t, _)| t == n) {
                    self.styles.remove(pos);
                }
            }
            _ => {}
        }
    }
}

fn attr(attrs: &str, name: &str) -> Option<String> {
    let lower = attrs.to_ascii_lowercase();
    let mut from = 0;
    while let Some(found) = lower[from..].find(name) {
        let at = from + found;
        from = at + name.len();
        let before_ok = at == 0 || lower.as_bytes()[at - 1].is_ascii_whitespace();
        let rest = attrs[at + name.len()..].trim_start();
        if !before_ok || !rest.starts_with('=') {
            continue;
        }
        let rest = rest[1..].trim_start();
        let (quote, rest) = match rest.chars().next() {
            Some(q @ ('"' | '\'')) => (Some(q), &rest[1..]),
            _ => (None, rest),
        };
        let end = match quote {
            Some(q) => rest.find(q).unwrap_or(rest.len()),
            None => rest.find(char::is_whitespace).unwrap_or(rest.len()),
        };
        return Some(rest[..end].to_owned());
    }
    None
}

fn collapse_ws(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut space = false;
    for c in s.chars() {
        if c.is_whitespace() && c != '\u{a0}' {
            if !space {
                out.push(' ');
            }
            space = true;
        } else {
            out.push(if c == '\u{a0}' { ' ' } else { c });
            space = false;
        }
    }
    out
}

fn decode_entities(s: &str) -> String {
    if !s.contains('&') {
        return s.to_owned();
    }
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(amp) = rest.find('&') {
        out.push_str(&rest[..amp]);
        rest = &rest[amp..];
        let Some(semi) = rest[..rest.len().min(12)].find(';') else {
            out.push('&');
            rest = &rest[1..];
            continue;
        };
        let entity = &rest[1..semi];
        let decoded = match entity {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" | "#39" => Some('\''),
            "nbsp" => Some('\u{a0}'),
            "mdash" => Some('—'),
            "ndash" => Some('–'),
            "hellip" => Some('…'),
            "lsquo" => Some('‘'),
            "rsquo" => Some('’'),
            "ldquo" => Some('“'),
            "rdquo" => Some('”'),
            e if e.starts_with("#x") || e.starts_with("#X") => u32::from_str_radix(&e[2..], 16)
                .ok()
                .and_then(char::from_u32),
            e if e.starts_with('#') => e[1..].parse::<u32>().ok().and_then(char::from_u32),
            _ => None,
        };
        match decoded {
            Some(c) => {
                out.push(c);
                rest = &rest[semi + 1..];
            }
            None => {
                out.push('&');
                rest = &rest[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

/// HTML for rich paste targets (Mail, Pages, Notion, Docs).
pub fn to_html(blocks: &[Rc<Block>]) -> String {
    let mut out = String::new();
    let mut lists: Vec<(Kind, u8)> = Vec::new();
    for b in blocks {
        let list_kind = match b.kind {
            Kind::Bullet | Kind::Todo => Some(Kind::Bullet),
            Kind::Numbered => Some(Kind::Numbered),
            _ => None,
        };
        // Close lists that end here or are deeper than this block.
        while let Some((kind, depth)) = lists.last().copied() {
            let keep =
                list_kind.is_some_and(|k| depth < b.indent || (depth == b.indent && k == kind));
            if keep {
                break;
            }
            out.push_str(if kind == Kind::Numbered {
                "</ol>"
            } else {
                "</ul>"
            });
            lists.pop();
        }
        if let Some(kind) = list_kind
            && lists.last().is_none_or(|(_, d)| *d < b.indent)
        {
            out.push_str(if kind == Kind::Numbered {
                "<ol>"
            } else {
                "<ul>"
            });
            lists.push((kind, b.indent));
        }
        let inner = inline_html(b);
        match b.kind {
            Kind::Paragraph => out.push_str(&format!("<p>{inner}</p>")),
            Kind::H1 => out.push_str(&format!("<h1>{inner}</h1>")),
            Kind::H2 => out.push_str(&format!("<h2>{inner}</h2>")),
            Kind::H3 => out.push_str(&format!("<h3>{inner}</h3>")),
            Kind::Bullet | Kind::Numbered => out.push_str(&format!("<li>{inner}</li>")),
            Kind::Todo => out.push_str(&format!(
                "<li><input type=\"checkbox\"{} disabled> {inner}</li>",
                if b.checked { " checked" } else { "" }
            )),
            Kind::Quote => out.push_str(&format!("<blockquote>{inner}</blockquote>")),
            Kind::Code => {
                out.push_str(&format!("<pre><code>{}</code></pre>", escape_html(&b.text)))
            }
            Kind::Divider => out.push_str("<hr>"),
        }
    }
    while let Some((kind, _)) = lists.pop() {
        out.push_str(if kind == Kind::Numbered {
            "</ol>"
        } else {
            "</ul>"
        });
    }
    out
}

fn escape_html(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn inline_html(b: &Block) -> String {
    let text = &b.text;
    let mut cuts: Vec<usize> = vec![0, text.len()];
    for m in &b.marks {
        cuts.push(m.start);
        cuts.push(m.end);
    }
    cuts.sort_unstable();
    cuts.dedup();
    let mut out = String::new();
    for w in cuts.windows(2) {
        let (a, z) = (w[0], w[1]);
        let mut seg = escape_html(&text[a..z]).replace('\n', "<br>");
        for m in b.marks.iter().filter(|m| m.start <= a && m.end >= z) {
            seg = match &m.style {
                Style::Bold => format!("<strong>{seg}</strong>"),
                Style::Italic => format!("<em>{seg}</em>"),
                Style::Code => format!("<code>{seg}</code>"),
                Style::Strike => format!("<s>{seg}</s>"),
                Style::Link(url) => format!("<a href=\"{}\">{seg}</a>", escape_html(url)),
            };
        }
        out.push_str(&seg);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kinds(blocks: &[Block]) -> Vec<(Kind, &str, u8)> {
        blocks
            .iter()
            .map(|b| (b.kind, b.text.as_str(), b.indent))
            .collect()
    }

    #[test]
    fn parses_every_block_kind() {
        let md = "# Title\n\n## Sub\n\n### Small\n\nPlain **bold** and *it* and `code` and ~~gone~~ [link](https://a.b)\n\n- one\n- two\n    - nested\n1. first\n2. second\n- [ ] todo\n- [x] done\n\n> quoted\n> more\n\n```\nlet x = 1;\n\nlet y = 2;\n```\n\n---";
        let blocks = from_markdown(md);
        assert_eq!(
            kinds(&blocks),
            vec![
                (Kind::H1, "Title", 0),
                (Kind::H2, "Sub", 0),
                (Kind::H3, "Small", 0),
                (
                    Kind::Paragraph,
                    "Plain bold and it and code and gone link",
                    0
                ),
                (Kind::Bullet, "one", 0),
                (Kind::Bullet, "two", 0),
                (Kind::Bullet, "nested", 1),
                (Kind::Numbered, "first", 0),
                (Kind::Numbered, "second", 0),
                (Kind::Todo, "todo", 0),
                (Kind::Todo, "done", 0),
                (Kind::Quote, "quoted\nmore", 0),
                (Kind::Code, "let x = 1;\n\nlet y = 2;", 0),
                (Kind::Divider, "", 0),
            ]
        );
        let p = &blocks[3];
        let styles: Vec<_> = p
            .marks
            .iter()
            .map(|m| (&p.text[m.start..m.end], m.style.name()))
            .collect();
        assert_eq!(
            styles,
            vec![
                ("bold", "bold"),
                ("it", "italic"),
                ("code", "code"),
                ("gone", "strike"),
                ("link", "link")
            ]
        );
        assert!(blocks[10].checked);
    }

    #[test]
    fn markdown_round_trips() {
        let md = "# Title\n\nSome **bold *both*** text with `a*b` and [x](https://x.dev)\n\n- a\n    - b\n1. one\n2. two\n- [x] done\n\n> q\n\n```\ncode\n```\n\n---\n\n\\# not a heading";
        let blocks: Vec<Rc<Block>> = from_markdown(md).into_iter().map(Rc::new).collect();
        let out = to_markdown(&blocks);
        let again: Vec<Rc<Block>> = from_markdown(&out).into_iter().map(Rc::new).collect();
        assert_eq!(blocks.len(), again.len(), "{out}");
        for (a, b) in blocks.iter().zip(&again) {
            assert_eq!(
                (a.kind, &a.text, &a.marks, a.indent, a.checked),
                (b.kind, &b.text, &b.marks, b.indent, b.checked),
                "{out}"
            );
        }
        assert_eq!(blocks.last().unwrap().text, "# not a heading");
    }

    #[test]
    fn plain_text_paragraphs_split_on_blank_lines() {
        let blocks = from_plain("first line\nsecond line\n\nnext paragraph\n\n\nlast");
        assert_eq!(
            kinds(&blocks),
            vec![
                (Kind::Paragraph, "first line\nsecond line", 0),
                (Kind::Paragraph, "next paragraph", 0),
                (Kind::Paragraph, "last", 0),
            ]
        );
        assert_eq!(
            kinds(&from_plain("2 * 3 = 6 and snake_case")),
            vec![(Kind::Paragraph, "2 * 3 = 6 and snake_case", 0)]
        );
    }

    #[test]
    fn html_becomes_blocks() {
        let html = r#"<meta charset="utf-8"><h1>Head &amp; more</h1><p>Some <b>bold</b> and <span style="font-style: italic">it</span> <a href="https://a.b?x=1&amp;y=2">link</a></p><ul><li>one</li><li>two<ul><li>deep</li></ul></li></ul><ol><li>n</li></ol><blockquote>q</blockquote><pre><code>a &lt; b
c</code></pre><hr><p>end<br>line</p>"#;
        let blocks = from_html(html);
        assert_eq!(
            kinds(&blocks),
            vec![
                (Kind::H1, "Head & more", 0),
                (Kind::Paragraph, "Some bold and it link", 0),
                (Kind::Bullet, "one", 0),
                (Kind::Bullet, "two", 0),
                (Kind::Bullet, "deep", 1),
                (Kind::Numbered, "n", 0),
                (Kind::Quote, "q", 0),
                (Kind::Code, "a < b\nc", 0),
                (Kind::Divider, "", 0),
                (Kind::Paragraph, "end\nline", 0),
            ]
        );
        let p = &blocks[1];
        assert!(
            p.marks
                .iter()
                .any(|m| m.style == Style::Link("https://a.b?x=1&y=2".into()))
        );
        let back = to_html(&blocks.into_iter().map(Rc::new).collect::<Vec<_>>());
        assert!(back.contains("<strong>bold</strong>"));
        assert!(back.contains("<ul><li>one</li><li>two</li><ul><li>deep</li></ul></ul>"));
    }
}
