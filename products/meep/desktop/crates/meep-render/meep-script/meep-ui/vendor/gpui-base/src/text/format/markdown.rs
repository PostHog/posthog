use std::{collections::BTreeMap, ops::Range, sync::Arc};

use gpui::SharedString;
use markdown::{
    ParseOptions,
    mdast::{self, Node},
    unist::Point,
};

use crate::text::{
    document::ParsedDocument,
    markdown_ext::MarkdownParseContext,
    node::{
        self, BlockNode, CodeBlock, ImageNode, InlineNode, LinkMark, NodeContext, Paragraph,
        SourceSegment, Span, Table, TableRow, TextMark,
    },
};

/// Parse Markdown into a tree of nodes.
pub(crate) fn parse(source: &str, cx: &mut NodeContext) -> Result<ParsedDocument, SharedString> {
    let options = cx.markdown_extensions.parse_options();
    let mut root =
        markdown::to_mdast(source, &options).map_err(|e| SharedString::from(e.to_string()))?;
    let mut prose = options;
    prose.constructs.math_text = false;
    prose.constructs.math_flow = false;
    flatten_unclaimed_math(&mut root, source, &prose, cx);
    Ok(ast_to_document(source, root, cx))
}

/// Math parsing is on by default, so prose that merely contains two dollar
/// signs ("$5 and $10") parses as an inline math node. When no plugin claims
/// such a node, the text between the dollars must stay ordinary Markdown:
/// emphasis, inline HTML and links inside it render as they would anywhere
/// else, and inline HTML tags may pair with tags outside the span. Re-parse
/// the node's source without the math constructs and, when it holds any
/// markup, splice the result into its parent with positions shifted back into
/// the document. Plain prose keeps the literal node, whose atomic source
/// mapping the selection tests rely on.
fn flatten_unclaimed_math(node: &mut Node, source: &str, options: &ParseOptions, cx: &NodeContext) {
    let Some(children) = node.children_mut() else {
        return;
    };
    let mut ix = 0;
    while ix < children.len() {
        let prose = match &children[ix] {
            Node::InlineMath(_) => {
                let parse_cx = MarkdownParseContext::new(source, cx.offset);
                if cx
                    .markdown_extensions
                    .parse_inline(&children[ix], &parse_cx)
                    .is_some()
                {
                    None
                } else {
                    reparse_as_prose(&children[ix], source, options)
                }
            }
            _ => None,
        };
        if let Some(prose) = prose {
            let count = prose.len();
            children.splice(ix..=ix, prose);
            ix += count;
            continue;
        }
        flatten_unclaimed_math(&mut children[ix], source, options, cx);
        ix += 1;
    }
}

fn reparse_as_prose(node: &Node, source: &str, options: &ParseOptions) -> Option<Vec<Node>> {
    let position = node.position()?.clone();
    let literal = source.get(position.start.offset..position.end.offset)?;
    if !may_hold_inline_markup(literal) {
        return None;
    }
    let Ok(Node::Root(mut root)) = markdown::to_mdast(literal, options) else {
        return None;
    };
    let [Node::Paragraph(paragraph)] = root.children.as_mut_slice() else {
        return None;
    };
    if paragraph
        .children
        .iter()
        .all(|child| matches!(child, Node::Text(_)))
    {
        return None;
    }
    let mut children = std::mem::take(&mut paragraph.children);
    for child in &mut children {
        shift_positions(child, &position.start);
    }
    Some(children)
}

/// A cheap gate before re-parsing: every inline construct starts with one of
/// these bytes (tags, emphasis, code, links, images, escapes, entities,
/// strikethrough) or is a GFM autolink literal.
fn may_hold_inline_markup(literal: &str) -> bool {
    literal.bytes().any(|byte| {
        matches!(
            byte,
            b'<' | b'*' | b'_' | b'[' | b'`' | b'~' | b'\\' | b'!' | b'&'
        )
    }) || literal.contains("://")
        || literal.contains("www.")
}

fn shift_positions(node: &mut Node, origin: &Point) {
    if let Some(position) = node.position_mut() {
        for point in [&mut position.start, &mut position.end] {
            let first_line = point.line == 1;
            point.offset += origin.offset;
            point.line += origin.line - 1;
            if first_line {
                point.column += origin.column - 1;
            }
        }
    }
    if let Some(children) = node.children_mut() {
        for child in children {
            shift_positions(child, origin);
        }
    }
}

enum InlineGroup<'a> {
    Node(&'a Node),
    Marked(TextMark, &'a [Node]),
}

/// CommonMark hands each raw inline tag over as its own `Html` node, so
/// `<strong>x</strong>` arrives as three siblings and the tags alone carry no
/// text. Pair the formatting tags this renderer knows with their closing tag
/// among the siblings and treat what lies between as a marked run, the same
/// way `**x**` is handled.
fn inline_groups(children: &[Node]) -> Vec<InlineGroup<'_>> {
    let mut groups = Vec::with_capacity(children.len());
    let mut ix = 0;
    while ix < children.len() {
        if let Some((false, name, attrs)) = inline_html_tag(&children[ix])
            && let Some(mark) = inline_html_mark(&name, attrs)
            && let Some(close) = matching_close_tag(children, ix, &name)
        {
            groups.push(InlineGroup::Marked(mark, &children[ix + 1..close]));
            ix = close + 1;
            continue;
        }
        groups.push(InlineGroup::Node(&children[ix]));
        ix += 1;
    }
    groups
}

fn inline_html_tag(node: &Node) -> Option<(bool, String, &str)> {
    let Node::Html(html) = node else {
        return None;
    };
    let inner = html.value.trim().strip_prefix('<')?.strip_suffix('>')?;
    if inner.ends_with('/') {
        return None;
    }
    let (closing, rest) = match inner.strip_prefix('/') {
        Some(rest) => (true, rest),
        None => (false, inner),
    };
    let name_len = rest.chars().take_while(char::is_ascii_alphanumeric).count();
    let name = rest[..name_len].to_ascii_lowercase();
    let attrs = rest[name_len..].trim();
    (!name.is_empty()).then_some((closing, name, attrs))
}

fn inline_html_attr<'a>(attrs: &'a str, name: &str) -> Option<&'a str> {
    let mut rest = attrs;
    while !rest.is_empty() {
        rest = rest.trim_start();
        let key_len = rest
            .find(|c: char| c.is_whitespace() || matches!(c, '=' | '/' | '>'))
            .unwrap_or(rest.len());
        if key_len == 0 {
            break;
        }
        let key = &rest[..key_len];
        rest = rest[key_len..].trim_start();
        let value = if let Some(after_eq) = rest.strip_prefix('=') {
            rest = after_eq.trim_start();
            if let Some(quote) = rest
                .as_bytes()
                .first()
                .copied()
                .filter(|b| *b == b'"' || *b == b'\'')
            {
                rest = &rest[1..];
                let end = rest.find(quote as char)?;
                let value = &rest[..end];
                rest = &rest[end + 1..];
                value
            } else {
                let end = rest.find(char::is_whitespace).unwrap_or(rest.len());
                let value = &rest[..end];
                rest = &rest[end..];
                value
            }
        } else {
            ""
        };
        if key.eq_ignore_ascii_case(name) {
            return Some(value);
        }
    }
    None
}

fn inline_html_mark(name: &str, attrs: &str) -> Option<TextMark> {
    Some(match name {
        "strong" | "b" => TextMark::default().bold(),
        "em" | "i" => TextMark::default().italic(),
        "u" => TextMark::default().underline(),
        "s" | "del" | "strike" => TextMark::default().strikethrough(),
        "mark" => {
            let color = super::html::mark_color_from_values(
                inline_html_attr(attrs, "color"),
                inline_html_attr(attrs, "style"),
            )
            .unwrap_or_else(super::html::default_mark_color);
            TextMark::default().highlight(color)
        }
        _ => return None,
    })
}

fn matching_close_tag(children: &[Node], open: usize, name: &str) -> Option<usize> {
    let mut depth = 0usize;
    for (ix, child) in children.iter().enumerate().skip(open + 1) {
        match inline_html_tag(child) {
            Some((false, tag, _)) if tag == name => depth += 1,
            Some((true, tag, _)) if tag == name => {
                if depth == 0 {
                    return Some(ix);
                }
                depth -= 1;
            }
            _ => {}
        }
    }
    None
}

fn parse_inline_children(
    source: &str,
    paragraph: &mut Paragraph,
    children: &[Node],
    cx: &mut NodeContext,
) -> String {
    let mut text = String::new();
    for group in inline_groups(children) {
        match group {
            InlineGroup::Node(child) => {
                text.push_str(&parse_paragraph(source, paragraph, child, cx));
            }
            InlineGroup::Marked(mark, nodes) => {
                text.push_str(&merge_children_with_mark(
                    source, paragraph, nodes, mark, cx,
                ));
            }
        }
    }
    text
}

fn parse_table_row(source: &str, table: &mut Table, node: &mdast::TableRow, cx: &mut NodeContext) {
    let mut row = TableRow::default();
    node.children.iter().for_each(|c| {
        match c {
            Node::TableCell(cell) => {
                parse_table_cell(source, &mut row, cell, cx);
            }
            _ => {}
        };
    });
    // GFM fixes the column count with the header/delimiter. Leave missing
    // cells implicit; the renderer places them on the shared column grid.
    row.children.truncate(table.column_aligns.len());
    table.children.push(row);
}

fn parse_table_cell(
    source: &str,
    row: &mut node::TableRow,
    node: &mdast::TableCell,
    cx: &mut NodeContext,
) {
    let mut paragraph = Paragraph::default();
    parse_inline_children(source, &mut paragraph, &node.children, cx);
    let table_cell = node::TableCell {
        children: paragraph,
        ..Default::default()
    };
    row.children.push(table_cell);
}

/// Push a text run with its existing `marks` plus `new_mark` across the full
/// run.
///
/// If the last mark already covers the full run, merge into it. Otherwise add a
/// new full-run mark. Empty runs are skipped so callers can flush freely.
fn push_merged(
    paragraph: &mut Paragraph,
    text: String,
    marks: Vec<(Range<usize>, TextMark)>,
    source_segments: Vec<SourceSegment>,
    new_mark: TextMark,
) {
    if text.is_empty() {
        return;
    }

    let mut node = InlineNode::new(text)
        .marks(marks)
        .source_segments(source_segments);
    let len = node.text.len();
    if let Some(last) = node.marks.last_mut()
        && last.0.start == 0
        && last.0.end == len
    {
        last.1.merge(new_mark);
    } else {
        node.marks.push((0..len, new_mark));
    }
    paragraph.push(node);
}

/// Parse `children` and apply `mark` across each emitted text run.
///
/// Nested child marks are kept and shifted to match the combined text for the
/// current run, which lets nested emphasis like `**_x_**` render as both bold
/// and italic. Inline images split the run and are emitted as sibling image
/// nodes. The return value is the plain text from all children, for callers that
/// need to pass text back to their parent node.
fn merge_children_with_mark(
    source: &str,
    paragraph: &mut Paragraph,
    children: &[mdast::Node],
    mark: TextMark,
    cx: &mut NodeContext,
) -> String {
    let mut text = String::new();
    let mut merged_text = String::new();
    let mut merged_marks = Vec::new();
    let mut merged_source_segments = Vec::new();

    for group in inline_groups(children) {
        let mut child_paragraph = Paragraph::default();
        let child_text = match group {
            InlineGroup::Node(child) => parse_paragraph(source, &mut child_paragraph, child, cx),
            InlineGroup::Marked(child_mark, nodes) => {
                merge_children_with_mark(source, &mut child_paragraph, nodes, child_mark, cx)
            }
        };
        text.push_str(&child_text);

        for mut node in child_paragraph.children {
            if node.custom.is_some() {
                push_merged(
                    paragraph,
                    std::mem::take(&mut merged_text),
                    std::mem::take(&mut merged_marks),
                    std::mem::take(&mut merged_source_segments),
                    mark.clone(),
                );
                if let Some((_, existing)) = node.marks.first_mut() {
                    existing.merge(mark.clone());
                } else {
                    node.marks.push((0..node.text.len(), mark.clone()));
                }
                paragraph.push(node);
                continue;
            }
            let merged_offset = merged_text.len();
            merged_text.push_str(&node.text);
            merged_source_segments.extend(node.source_segments.drain(..).map(|mut segment| {
                segment.rendered.start += merged_offset;
                segment.rendered.end += merged_offset;
                segment
            }));

            for (range, child_mark) in node.marks {
                merged_marks.push((
                    range.start + merged_offset..range.end + merged_offset,
                    child_mark,
                ));
            }

            if let Some(mut image) = node.image {
                if let Some(link_mark) = mark.link.clone() {
                    image.link = Some(link_mark);
                }

                // GPUI InteractiveText does not support inline images, so
                // flush the accumulated text run and emit the image as its
                // own sibling InlineNode.
                push_merged(
                    paragraph,
                    std::mem::take(&mut merged_text),
                    std::mem::take(&mut merged_marks),
                    std::mem::take(&mut merged_source_segments),
                    mark.clone(),
                );
                paragraph.push(InlineNode::image(image));
            }
        }
    }

    push_merged(
        paragraph,
        merged_text,
        merged_marks,
        merged_source_segments,
        mark,
    );
    text
}

fn source_segments(
    source: &str,
    rendered: &str,
    span: Option<Span>,
    source_offset: usize,
    include_preceding_escape: bool,
) -> Vec<SourceSegment> {
    let Some(span) = span else {
        return Vec::new();
    };
    let local_start = span.start.saturating_sub(source_offset);
    let local_end = span.end.saturating_sub(source_offset);
    let Some(raw) = source.get(local_start..local_end) else {
        return Vec::new();
    };

    let mut segments = aligned_source_segments(raw, rendered, span.start, true, true);

    // The text node of an escaped character starts after its backslash. The
    // backslash and the character map as a whole; the rest of the run stays
    // linear.
    if include_preceding_escape
        && let Some(previous) = local_start.checked_sub(1)
        && source.as_bytes().get(previous) == Some(&b'\\')
        && let Some(first) = segments.first_mut()
    {
        let first_char_len = rendered[first.rendered.start..]
            .chars()
            .next()
            .map_or(0, char::len_utf8);
        if first.linear && first.rendered.len() > first_char_len {
            let rest = SourceSegment {
                rendered: first.rendered.start + first_char_len..first.rendered.end,
                source: first.source.start + first_char_len..first.source.end,
                linear: true,
            };
            first.rendered.end = rest.rendered.start;
            first.source.end = rest.source.start;
            segments.insert(1, rest);
        }
        let first = &mut segments[0];
        first.source.start -= 1;
        first.linear = false;
    }
    segments
}

fn aligned_source_segments(
    raw: &str,
    rendered: &str,
    source_offset: usize,
    decode_entities: bool,
    decode_escapes: bool,
) -> Vec<SourceSegment> {
    let mut segments = Vec::new();
    let mut raw_cursor = 0;
    let mut rendered_start = 0;
    let mut whitespace_end = 0;
    let mut source_positions = None;
    let mut entity_cursor = None;
    let mut entity = None;
    // Only the final LF may absorb source-only text before it. Find the
    // preceding line boundary once instead of recounting the suffix per LF.
    let final_line_start = raw
        .strip_suffix('\n')
        .and_then(|prefix| prefix.rfind('\n'))
        .map_or(0, |newline| newline + 1);

    while rendered_start < rendered.len() {
        if decode_entities && entity_cursor != Some(raw_cursor) {
            entity = decoded_entity(&raw[raw_cursor..]);
            entity_cursor = Some(raw_cursor);
        }
        if let Some((decoded, source_len)) = &entity
            && rendered[rendered_start..].starts_with(decoded.as_str())
        {
            let rendered_end = rendered_start + decoded.len();
            push_source_segment(
                &mut segments,
                SourceSegment {
                    rendered: rendered_start..rendered_end,
                    source: (source_offset + raw_cursor)
                        ..(source_offset + raw_cursor + *source_len),
                    // Even when the decoded characters take as many bytes as the
                    // entity, as `∾̳` and `&acE;` do, they are not one for one.
                    linear: false,
                },
            );
            rendered_start = rendered_end;
            raw_cursor += *source_len;
            continue;
        }

        let rendered_char = rendered[rendered_start..]
            .chars()
            .next()
            .expect("rendered cursor must be on a character boundary");
        let rendered_end = rendered_start + rendered_char.len_utf8();
        let remainder = &raw[raw_cursor..];
        if rendered_char == ' ' && raw_cursor >= whitespace_end {
            // Reuse this boundary while consuming a run of literal spaces.
            // Otherwise a long horizontal-whitespace run also costs O(n^2).
            whitespace_end = raw_cursor
                + remainder
                    .bytes()
                    .position(|byte| !matches!(byte, b' ' | b'\t'))
                    .unwrap_or(remainder.len());
        }
        let (relative_start, source_len) = if rendered_char == ' '
            && matches!(raw.as_bytes().get(whitespace_end), Some(b'\n' | b'\r'))
        {
            let newline_len = if raw[whitespace_end..].starts_with("\r\n") {
                2
            } else {
                1
            };
            (whitespace_end - raw_cursor, newline_len)
        } else if rendered_char == '\n'
            && remainder.ends_with('\n')
            && raw_cursor >= final_line_start
        {
            (0, remainder.len())
        } else if decode_escapes
            && let Some(escaped) = remainder.strip_prefix('\\')
            && escaped.starts_with(rendered_char)
        {
            (0, 1 + rendered_char.len_utf8())
        } else if remainder.starts_with(rendered_char) {
            (0, rendered_char.len_utf8())
        } else if let Some(source_start) =
            source_char_offset(raw, raw_cursor, rendered_char, &mut source_positions)
        {
            (source_start - raw_cursor, rendered_char.len_utf8())
        } else {
            // Decoded entities and other source-only syntax have no exact
            // rendered-byte mapping. Leave a rendered gap for this
            // character, but keep aligning later characters in the node.
            rendered_start = rendered_end;
            continue;
        };
        let source_start = raw_cursor + relative_start;
        let source_end = source_start + source_len;
        push_source_segment(
            &mut segments,
            SourceSegment {
                rendered: rendered_start..rendered_end,
                source: (source_offset + source_start)..(source_offset + source_end),
                linear: source_len == rendered_char.len_utf8(),
            },
        );
        raw_cursor = source_end;
        rendered_start = rendered_end;
    }
    segments
}

fn source_char_offset(
    raw: &str,
    raw_cursor: usize,
    character: char,
    positions: &mut Option<BTreeMap<char, Vec<usize>>>,
) -> Option<usize> {
    if let Some(positions) = positions.as_ref() {
        let offsets = positions.get(&character)?;
        return offsets
            .get(offsets.partition_point(|&offset| offset < raw_cursor))
            .copied();
    }
    if let Some(offset) = raw[raw_cursor..].find(character) {
        return Some(raw_cursor + offset);
    }

    // Successful searches advance raw_cursor, so their scans do not overlap.
    // A missing character does not advance it. Index the remaining source only
    // after the first miss so later gaps cannot repeatedly scan that suffix.
    let mut indexed = BTreeMap::<char, Vec<usize>>::new();
    for (offset, character) in raw[raw_cursor..].char_indices() {
        indexed
            .entry(character)
            .or_default()
            .push(raw_cursor + offset);
    }
    *positions = Some(indexed);
    None
}

/// Pushes `segment`, merging it into the previous one when both are linear and
/// adjacent, so that a merged run still maps byte for byte. Any other segment
/// is kept whole on its own.
fn push_source_segment(segments: &mut Vec<SourceSegment>, segment: SourceSegment) {
    if let Some(previous) = segments.last_mut()
        && previous.linear
        && segment.linear
        && previous.rendered.end == segment.rendered.start
        && previous.source.end == segment.source.start
    {
        previous.rendered.end = segment.rendered.end;
        previous.source.end = segment.source.end;
    } else {
        segments.push(segment);
    }
}

fn decoded_entity(source: &str) -> Option<(String, usize)> {
    let candidate = source.strip_prefix('&')?;
    let candidate_end = candidate
        .bytes()
        .position(|byte| byte == b';' || !(byte.is_ascii_alphanumeric() || byte == b'#'))?;
    if candidate.as_bytes()[candidate_end] != b';' {
        return None;
    }
    let semicolon = candidate_end + 1;
    let name = &source[1..=semicolon];
    let decoded = if let Some(number) = name.strip_prefix("#x").or_else(|| name.strip_prefix("#X"))
    {
        char::from_u32(u32::from_str_radix(number.strip_suffix(';')?, 16).ok()?)?.to_string()
    } else if let Some(number) = name.strip_prefix('#') {
        char::from_u32(number.strip_suffix(';')?.parse().ok()?)?.to_string()
    } else {
        let &(first, second) = html5ever::data::NAMED_ENTITIES.get(name)?;
        let mut decoded = char::from_u32(first)?.to_string();
        if second != 0 {
            decoded.push(char::from_u32(second)?);
        }
        decoded
    };
    Some((decoded, semicolon + 1))
}

fn code_source_segments(
    source: &str,
    code: &str,
    span: Option<Span>,
    source_offset: usize,
) -> Vec<SourceSegment> {
    let Some(span) = span else {
        return Vec::new();
    };
    let Some(raw) = source
        .get(span.start.saturating_sub(source_offset)..span.end.saturating_sub(source_offset))
    else {
        return Vec::new();
    };
    let trimmed = raw.trim_start();
    let fence = trimmed
        .chars()
        .next()
        .filter(|character| matches!(character, '`' | '~'))
        .map(|character| {
            let len = trimmed
                .chars()
                .take_while(|candidate| candidate == &character)
                .count();
            (character, len)
        })
        .filter(|(_, len)| *len >= 3);
    let (body_start, body_end) = if let Some((fence, fence_len)) = fence {
        let start = raw.find('\n').map_or(raw.len(), |newline| newline + 1);
        let last_line = raw.rfind('\n').map_or(start, |newline| newline + 1);
        let closing = raw[last_line..].trim();
        let is_closing = closing.chars().count() >= fence_len
            && closing.chars().all(|character| character == fence);
        (start, if is_closing { last_line } else { raw.len() })
    } else {
        (0, raw.len())
    };

    aligned_source_segments(
        &raw[body_start..body_end],
        code,
        span.start + body_start,
        false,
        false,
    )
}

fn mapped_inline(
    source: &str,
    text: impl Into<SharedString>,
    node: &mdast::Node,
    cx: &NodeContext,
) -> InlineNode {
    let text = text.into();
    let span = node.position().map(|position| Span {
        start: cx.offset + position.start.offset,
        end: cx.offset + position.end.offset,
    });
    let segments = source_segments(
        source,
        &text,
        span,
        cx.offset,
        matches!(node, Node::Text(_)),
    );
    InlineNode::new(text).source_segments(segments)
}

fn append_inline_html_blocks(paragraph: &mut Paragraph, blocks: Vec<BlockNode>) -> Option<String> {
    let mut text = String::new();

    for block in blocks {
        match block {
            BlockNode::Root { children, .. } => {
                text.push_str(&append_inline_html_blocks(paragraph, children)?);
            }
            BlockNode::Paragraph(html_paragraph) => {
                text.push_str(&html_paragraph.text());
                for child in html_paragraph.children {
                    paragraph.push(child);
                }
            }
            BlockNode::Break { .. } => {
                text.push('\n');
                paragraph.push(InlineNode::new("\n"));
            }
            _ => return None,
        }
    }

    Some(text)
}

fn parse_paragraph(
    source: &str,
    paragraph: &mut Paragraph,
    node: &mdast::Node,
    cx: &mut NodeContext,
) -> String {
    let span = node.position().map(|pos| Span {
        start: cx.offset + pos.start.offset,
        end: cx.offset + pos.end.offset,
    });
    if let Some(span) = span {
        paragraph.set_span(span);
    }

    let parse_cx = MarkdownParseContext::new(source, cx.offset);
    if let Some(mut custom) = cx.markdown_extensions.parse_inline(node, &parse_cx) {
        custom.set_span(span);
        let custom = custom.with_inline_source(parse_cx.node_source(node).unwrap_or_default());
        let text = custom.as_text().to_string();
        paragraph.push(InlineNode::custom(custom));
        return text;
    }

    let mut text = String::new();

    match node {
        Node::Paragraph(val) => {
            text.push_str(&parse_inline_children(source, paragraph, &val.children, cx));
        }
        Node::Text(val) => {
            // A CommonMark *soft* break lives inside this value as a plain
            // line ending. The renderer treats a newline in a text run as a
            // line break, so a paragraph hard-wrapped in the source would
            // render one visual line per source line instead of reflowing to
            // the available width. Collapse soft breaks to spaces; *hard*
            // breaks never reach here, they arrive as their own Node::Break.
            //
            // mdast hands the line ending over exactly as the source wrote it,
            // so a CRLF document still carries its carriage return here. Take
            // the CR with the newline: dropping only the newline would strand
            // the CR in the middle of the reflowed line.
            text = val.value.replace("\r\n", " ").replace(['\n', '\r'], " ");
            paragraph.push(mapped_inline(source, text.clone(), node, cx))
        }
        Node::Emphasis(val) => {
            text = merge_children_with_mark(
                source,
                paragraph,
                &val.children,
                TextMark::default().italic(),
                cx,
            );
        }
        Node::Strong(val) => {
            text = merge_children_with_mark(
                source,
                paragraph,
                &val.children,
                TextMark::default().bold(),
                cx,
            );
        }
        Node::Delete(val) => {
            text = merge_children_with_mark(
                source,
                paragraph,
                &val.children,
                TextMark::default().strikethrough(),
                cx,
            );
        }
        Node::InlineCode(val) => {
            text = val.value.clone();
            let span = node.position().map(|position| Span {
                start: cx.offset + position.start.offset,
                end: cx.offset + position.end.offset,
            });
            paragraph.push(
                InlineNode::new(text.clone())
                    .source_segments(code_source_segments(source, &text, span, cx.offset))
                    .marks(vec![(0..text.len(), TextMark::default().code())]),
            );
        }
        Node::Link(val) => {
            let link_mark = Some(LinkMark {
                url: val.url.clone().into(),
                title: val.title.clone().map(|s| s.into()),
                ..Default::default()
            });

            text = merge_children_with_mark(
                source,
                paragraph,
                &val.children,
                TextMark {
                    link: link_mark,
                    ..Default::default()
                },
                cx,
            );
        }
        Node::Image(raw) => {
            paragraph.push_image(ImageNode {
                url: raw.url.clone().into(),
                title: raw.title.clone().map(|t| t.into()),
                alt: Some(raw.alt.clone().into()),
                span: raw.position.as_ref().map(|position| Span {
                    start: cx.offset + position.start.offset,
                    end: cx.offset + position.end.offset,
                }),
                ..Default::default()
            });
        }
        Node::ImageReference(raw) => {
            if let Some(definition) = cx.link_refs.get(raw.identifier.as_str()) {
                paragraph.push_image(ImageNode {
                    url: definition.url.clone().into(),
                    title: definition.title.clone(),
                    alt: Some(raw.alt.clone().into()),
                    span,
                    ..Default::default()
                });
            }
        }
        Node::Break(_) => {
            // Hard line break (trailing two spaces / backslash). Mirror the
            // inline-HTML <br> path: emit a newline inline node so the break
            // renders instead of silently concatenating adjacent lines.
            text.push('\n');
            paragraph.push(mapped_inline(source, "\n", node, cx));
        }
        Node::InlineMath(raw) => {
            // Math parsing is on by default, so ordinary prose that merely
            // contains dollar signs ("spent $5 and $10") arrives here as a
            // math node whenever no inline plugin claimed it. Emitting
            // `raw.value` would drop the delimiters and restyle the run as
            // code, silently rewriting what the author typed. Fall back to the
            // original source so unclaimed math stays literal.
            text = parse_cx
                .node_source(node)
                .map(str::to_string)
                .unwrap_or_else(|| raw.value.clone());
            paragraph.push(mapped_inline(source, text.clone(), node, cx));
        }
        Node::MdxTextExpression(raw) => {
            text = raw.value.clone();
            let span = node.position().map(|position| Span {
                start: cx.offset + position.start.offset,
                end: cx.offset + position.end.offset,
            });
            paragraph.push(
                InlineNode::new(text.clone())
                    .source_segments(code_source_segments(source, &text, span, cx.offset))
                    .marks(vec![(0..text.len(), TextMark::default())]),
            );
        }
        Node::Html(val) => match super::html::parse(&val.value, cx) {
            Ok(el) => {
                if let Some(inline_text) =
                    append_inline_html_blocks(paragraph, Arc::unwrap_or_clone(el.blocks))
                {
                    text = inline_text;
                } else {
                    if cfg!(debug_assertions) {
                        tracing::warn!("unsupported inline html tag: {:#?}", val.value);
                    }
                }
            }
            Err(err) => {
                if cfg!(debug_assertions) {
                    tracing::warn!("failed parsing html: {:#?}", err);
                }

                text.push_str(&val.value);
            }
        },
        Node::FootnoteReference(foot) => {
            let prefix = format!("[{}]", foot.identifier);
            paragraph.push(mapped_inline(source, prefix.clone(), node, cx).marks(vec![(
                0..prefix.len(),
                TextMark {
                    italic: true,
                    ..Default::default()
                },
            )]));
        }
        Node::LinkReference(link) => {
            let link_mark = LinkMark {
                url: "".into(),
                title: link.label.clone().map(Into::into),
                identifier: Some(link.identifier.clone().into()),
            };

            text = merge_children_with_mark(
                source,
                paragraph,
                &link.children,
                TextMark {
                    link: Some(link_mark),
                    ..Default::default()
                },
                cx,
            );
        }
        _ => {
            if cfg!(debug_assertions) {
                tracing::warn!("unsupported inline node: {:#?}", node);
            }
        }
    }

    text
}

/// Definitions may follow their references or live inside a container. The
/// parser normalizes identifiers; CommonMark uses the first definition.
fn collect_definitions(node: &Node, definitions: &mut BTreeMap<String, LinkMark>) {
    if let Node::Definition(def) = node {
        definitions
            .entry(def.identifier.clone())
            .or_insert_with(|| LinkMark {
                url: def.url.clone().into(),
                identifier: Some(def.identifier.clone().into()),
                title: def.title.clone().map(Into::into),
            });
    }
    if let Some(children) = node.children() {
        for child in children {
            collect_definitions(child, definitions);
        }
    }
}

fn ast_to_document(source: &str, root: mdast::Node, cx: &mut NodeContext) -> ParsedDocument {
    let mut definitions = BTreeMap::new();
    collect_definitions(&root, &mut definitions);
    for (identifier, definition) in definitions {
        cx.add_ref(identifier.into(), definition);
    }

    let root = match root {
        Node::Root(r) => r,
        _ => panic!("expected root node"),
    };

    let blocks = root
        .children
        .into_iter()
        .map(|c| ast_to_node(source, c, cx))
        .collect();
    ParsedDocument {
        source: source.to_string().into(),
        blocks: Arc::new(blocks),
    }
}

fn new_span(pos: Option<markdown::unist::Position>, cx: &NodeContext) -> Option<Span> {
    let pos = pos?;

    Some(Span {
        start: cx.offset + pos.start.offset,
        end: cx.offset + pos.end.offset,
    })
}

fn ast_to_node(source: &str, value: mdast::Node, cx: &mut NodeContext) -> BlockNode {
    let span = new_span(value.position().cloned(), cx);
    let parse_cx = MarkdownParseContext::new(source, cx.offset);
    if let Some(mut node) = cx.markdown_extensions.parse_block(&value, &parse_cx) {
        node.set_span(span);
        return BlockNode::Custom {
            node,
            state: Default::default(),
        };
    }

    match value {
        Node::Root(_) => unreachable!("node::Root should be handled separately"),
        Node::Paragraph(val) => {
            let mut paragraph = Paragraph::default();
            parse_inline_children(source, &mut paragraph, &val.children, cx);
            paragraph.span = new_span(val.position, cx);
            BlockNode::Paragraph(paragraph)
        }
        Node::Blockquote(val) => {
            let children = val
                .children
                .into_iter()
                .map(|c| ast_to_node(source, c, cx))
                .collect();
            BlockNode::Blockquote {
                children,
                span: new_span(val.position, cx),
            }
        }
        Node::List(list) => {
            let children = list
                .children
                .into_iter()
                .map(|c| ast_to_node(source, c, cx))
                .collect();
            BlockNode::List {
                ordered: list.ordered,
                start: list.start,
                children,
                span: new_span(list.position, cx),
            }
        }
        Node::ListItem(val) => {
            let children = val
                .children
                .into_iter()
                .map(|c| ast_to_node(source, c, cx))
                .collect();
            BlockNode::ListItem {
                children,
                spread: val.spread,
                checked: val.checked,
                span: new_span(val.position, cx),
            }
        }
        Node::Break(val) => BlockNode::Break {
            html: false,
            span: new_span(val.position, cx),
        },
        Node::Code(raw) => {
            let span = new_span(raw.position, cx);
            let segments = code_source_segments(source, &raw.value, span, cx.offset);
            BlockNode::CodeBlock(
                CodeBlock::new(raw.value.into(), raw.lang.map(Into::into), span)
                    .with_meta(raw.meta.map(Into::into))
                    .source_segments(segments),
            )
        }
        Node::Heading(val) => {
            let mut paragraph = Paragraph::default();
            parse_inline_children(source, &mut paragraph, &val.children, cx);

            BlockNode::Heading {
                level: val.depth,
                children: paragraph,
                span: new_span(val.position, cx),
            }
        }
        Node::Math(val) => {
            let span = new_span(val.position, cx);
            let segments = code_source_segments(source, &val.value, span, cx.offset);
            BlockNode::CodeBlock(
                CodeBlock::new(val.value.into(), None, span).source_segments(segments),
            )
        }
        Node::Html(val) => match super::html::parse(&val.value, cx) {
            Ok(el) => BlockNode::Root {
                children: Arc::unwrap_or_clone(el.blocks),
                span: new_span(val.position, cx),
            },
            Err(err) => {
                if cfg!(debug_assertions) {
                    tracing::warn!("error parsing html: {:#?}", err);
                }

                BlockNode::Paragraph(Paragraph::new(val.value))
            }
        },
        Node::MdxFlowExpression(val) => {
            let span = new_span(val.position, cx);
            let segments = code_source_segments(source, &val.value, span, cx.offset);
            BlockNode::CodeBlock(
                CodeBlock::new(val.value.into(), Some("mdx".into()), span)
                    .source_segments(segments),
            )
        }
        Node::Yaml(val) => BlockNode::CodeBlock(CodeBlock::new(
            val.value.into(),
            Some("yml".into()),
            new_span(val.position, cx),
        )),
        Node::Toml(val) => BlockNode::CodeBlock(CodeBlock::new(
            val.value.into(),
            Some("toml".into()),
            new_span(val.position, cx),
        )),
        Node::MdxJsxTextElement(val) => {
            let mut paragraph = Paragraph::default();
            parse_inline_children(source, &mut paragraph, &val.children, cx);
            paragraph.span = new_span(val.position, cx);
            BlockNode::Paragraph(paragraph)
        }
        Node::MdxJsxFlowElement(val) => {
            let mut paragraph = Paragraph::default();
            parse_inline_children(source, &mut paragraph, &val.children, cx);
            paragraph.span = new_span(val.position, cx);
            BlockNode::Paragraph(paragraph)
        }
        Node::ThematicBreak(val) => BlockNode::HorizontalRule {
            span: new_span(val.position, cx),
        },
        Node::Table(val) => {
            let mut table = Table::default();
            table.column_aligns = val
                .align
                .clone()
                .into_iter()
                .map(|align| align.into())
                .collect();
            val.children.iter().for_each(|c| {
                if let Node::TableRow(row) = c {
                    parse_table_row(source, &mut table, row, cx);
                }
            });
            table.span = new_span(val.position, cx);

            BlockNode::Table(table)
        }
        Node::FootnoteDefinition(def) => {
            let mut paragraph = Paragraph::default();
            let prefix = format!("[{}]: ", def.identifier);
            paragraph.push(InlineNode::new(&prefix).marks(vec![(
                0..prefix.len(),
                TextMark {
                    italic: true,
                    ..Default::default()
                },
            )]));

            parse_inline_children(source, &mut paragraph, &def.children, cx);
            paragraph.span = new_span(def.position, cx);
            BlockNode::Paragraph(paragraph)
        }
        Node::Definition(def) => BlockNode::Definition {
            identifier: def.identifier.clone().into(),
            url: def.url.clone().into(),
            title: def.title.clone().map(|s| s.into()),
            span: new_span(def.position, cx),
        },
        _ => {
            if cfg!(debug_assertions) {
                tracing::warn!("unsupported node: {:#?}", value);
            }
            BlockNode::Unknown
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::ParentElement;

    use crate::text::{MarkdownExtensions, MarkdownNode, MarkdownPlugin};

    fn first_paragraph(block: &BlockNode) -> Option<&Paragraph> {
        match block {
            BlockNode::Paragraph(paragraph)
            | BlockNode::Heading {
                children: paragraph,
                ..
            } => Some(paragraph),
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => children.iter().find_map(first_paragraph),
            _ => None,
        }
    }

    fn first_code_block(block: &BlockNode) -> Option<&CodeBlock> {
        match block {
            BlockNode::CodeBlock(code) => Some(code),
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => children.iter().find_map(first_code_block),
            _ => None,
        }
    }

    fn selected_rendered_range(source: &str, selection: Range<usize>) -> Option<Range<usize>> {
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let paragraph = document
            .blocks
            .iter()
            .find_map(first_paragraph)
            .expect("expected paragraph");
        let rendered = paragraph.text();
        let mut state = paragraph.state.lock().unwrap();
        state.set_text(rendered.into());
        state.selection = Some(selection.into());
        drop(state);
        document.selected_source_range()
    }

    fn select_rendered_range(source: &str, selection: Range<usize>) -> Range<usize> {
        selected_rendered_range(source, selection).expect("source range")
    }

    fn selected_code_range(source: &str, selection: Range<usize>) -> Option<Range<usize>> {
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let code = document
            .blocks
            .iter()
            .find_map(first_code_block)
            .expect("expected code block");
        code.set_selection(selection);
        document.selected_source_range()
    }

    fn selected_mdx_rendered_range(source: &str, selection: Range<usize>) -> Option<Range<usize>> {
        let mut cx = NodeContext {
            markdown_extensions: Arc::new(MarkdownExtensions::default().mdx()),
            ..Default::default()
        };
        let document = parse(source, &mut cx).unwrap();
        let paragraph = document
            .blocks
            .iter()
            .find_map(first_paragraph)
            .expect("expected MDX paragraph");
        let rendered = paragraph.text();
        let mut state = paragraph.state.lock().unwrap();
        state.set_text(rendered.into());
        state.selection = Some(selection.into());
        drop(state);
        document.selected_source_range()
    }

    fn selected_mdx_code(source: &str, selected_text: &str) -> Option<Range<usize>> {
        let mut cx = NodeContext {
            markdown_extensions: Arc::new(MarkdownExtensions::default().mdx()),
            ..Default::default()
        };
        let document = parse(source, &mut cx).unwrap();
        let code = document
            .blocks
            .iter()
            .find_map(first_code_block)
            .expect("expected MDX code block");
        let code_text = code.code();
        let start = code_text.find(selected_text).expect("selected MDX code");
        code.set_selection(start..start + selected_text.len());
        document.selected_source_range()
    }

    #[test]
    fn table_rows_keep_missing_cells_implicit() {
        let mut cx = NodeContext::default();
        let document = parse(
            "| A | B | C |\n| --- | --- | --- |\n| one |\n| two | three | four | ignored |\n| five | | six |\n",
            &mut cx,
        )
        .unwrap();
        let BlockNode::Table(table) = &document.blocks[0] else {
            panic!("expected table");
        };
        assert_eq!(table.column_aligns.len(), 3);
        assert_eq!(
            table
                .children
                .iter()
                .map(|row| row.children.len())
                .collect::<Vec<_>>(),
            [3, 1, 3, 3]
        );
        assert_eq!(table.children[1].children[0].children.text(), "one");
        assert_eq!(table.children[2].children[2].children.text(), "four");
        assert!(table.children[3].children[1].children.text().is_empty());
        assert_eq!(table.children[3].children[2].children.text(), "six");
    }

    #[test]
    fn sparse_table_cell_count_tracks_source_cells() {
        for (columns, rows) in [(32, 64), (64, 128)] {
            let source = format!(
                "{}|\n{}|\n{}",
                "|h".repeat(columns),
                "|---".repeat(columns),
                "|x|\n".repeat(rows),
            );
            let mut cx = NodeContext::default();
            let document = parse(&source, &mut cx).unwrap();
            let BlockNode::Table(table) = &document.blocks[0] else {
                panic!("expected table");
            };
            assert_eq!(table.column_aligns.len(), columns);
            assert_eq!(table.children.len(), rows + 1);
            assert_eq!(table.children[0].children.len(), columns);
            assert!(
                table.children[1..]
                    .iter()
                    .all(|row| row.children.len() == 1)
            );
            assert_eq!(
                table
                    .children
                    .iter()
                    .map(|row| row.children.len())
                    .sum::<usize>(),
                columns + rows
            );
        }
    }

    #[test]
    fn selected_source_range_uses_the_selected_identical_styled_occurrence() {
        let source = "**same** then **same**";
        assert_eq!(select_rendered_range(source, 10..14), 16..20);
    }

    #[test]
    fn selected_source_range_maps_partial_styled_text() {
        let source = "**same** then **same**";
        assert_eq!(select_rendered_range(source, 11..13), 17..19);
    }

    #[test]
    fn source_segments_compact_contiguous_one_to_one_mappings() {
        let source = "plain text";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let paragraph = first_paragraph(&document.blocks[0]).unwrap();
        assert_eq!(
            paragraph.children[0].source_segments,
            vec![SourceSegment {
                rendered: 0..source.len(),
                source: 0..source.len(),
                linear: true,
            }]
        );

        assert_eq!(select_rendered_range(source, 2..7), 2..7);
    }

    #[test]
    fn source_alignment_compacts_long_whitespace_runs() {
        for raw in [
            "a ".repeat(16_384),
            format!("a{}b", " ".repeat(32_768)),
            format!("a{}b\n", " \t".repeat(16_384)),
        ] {
            let segments = aligned_source_segments(&raw, &raw, 7, true, true);
            assert_eq!(
                segments,
                vec![SourceSegment {
                    rendered: 0..raw.len(),
                    source: 7..7 + raw.len(),
                    linear: true,
                }]
            );
            assert!(
                segments.capacity() < 64,
                "compaction must not retain a per-character allocation"
            );
        }
    }

    #[test]
    fn source_alignment_preserves_multiline_code_and_final_newline() {
        let raw = "x\n".repeat(16_384);
        let rendered = &raw[..raw.len() - 1];
        assert_eq!(
            aligned_source_segments(&raw, rendered, 4, false, false),
            vec![SourceSegment {
                rendered: 0..rendered.len(),
                source: 4..4 + rendered.len(),
                linear: true,
            }]
        );
        assert_eq!(
            aligned_source_segments("a\n> \n", "a\n\n", 0, false, false),
            vec![
                SourceSegment {
                    rendered: 0..2,
                    source: 0..2,
                    linear: true,
                },
                SourceSegment {
                    rendered: 2..3,
                    source: 2..5,
                    linear: false,
                },
            ]
        );
    }

    #[test]
    fn source_alignment_keeps_soft_breaks_and_entities_atomic() {
        assert_eq!(
            aligned_source_segments("a \r\nb", "a b", 9, true, true),
            vec![
                SourceSegment {
                    rendered: 0..1,
                    source: 9..10,
                    linear: true,
                },
                SourceSegment {
                    rendered: 1..2,
                    source: 11..13,
                    linear: false,
                },
                SourceSegment {
                    rendered: 2..3,
                    source: 13..14,
                    linear: true,
                },
            ]
        );
        let entity = "&NotEqualTilde;";
        let decoded = "\u{2242}\u{338}";
        assert_eq!(
            aligned_source_segments(entity, decoded, 3, true, true),
            vec![SourceSegment {
                rendered: 0..decoded.len(),
                source: 3..3 + entity.len(),
                linear: false,
            }]
        );
    }

    #[test]
    fn source_alignment_resumes_after_unmapped_characters() {
        let raw = "abc".repeat(4_096);
        let mut positions = None;
        assert_eq!(source_char_offset(&raw, 0, 'b', &mut positions), Some(1));
        assert!(positions.is_none(), "successful scans need no index");
        assert_eq!(
            source_char_offset(&raw, 0, '\u{fffd}', &mut positions),
            None
        );
        assert!(positions.is_some(), "failed scans must not be repeated");
        assert_eq!(source_char_offset(&raw, 2, 'b', &mut positions), Some(4));
        assert_eq!(
            source_char_offset(&raw, raw.len(), 'a', &mut positions),
            None
        );

        let missing = "\u{fffd}".repeat(4_096);
        assert_eq!(
            aligned_source_segments(&raw, &format!("{missing}abc"), 5, true, true),
            vec![SourceSegment {
                rendered: missing.len()..missing.len() + 3,
                source: 5..8,
                linear: true,
            }]
        );
        assert_eq!(
            aligned_source_segments("&amp;z", &format!("{missing}&z"), 0, true, true),
            vec![
                SourceSegment {
                    rendered: missing.len()..missing.len() + 1,
                    source: 0..5,
                    linear: false,
                },
                SourceSegment {
                    rendered: missing.len() + 1..missing.len() + 2,
                    source: 5..6,
                    linear: true,
                },
            ]
        );
    }

    #[test]
    fn source_alignment_parses_long_text_and_code_without_selection() {
        let source = format!("{}end", "a ".repeat(4_096));
        let mut cx = NodeContext::default();
        let document = parse(&source, &mut cx).unwrap();
        let paragraph = first_paragraph(&document.blocks[0]).unwrap();
        assert_eq!(paragraph.text(), source);
        let segments = &paragraph.children[0].source_segments;
        assert_eq!(segments.len(), 1);
        assert!(segments.capacity() < 64);
        assert_eq!(segments[0].source, 0..source.len());
        assert_eq!(
            selected_rendered_range(&source, source.len() - 3..source.len()),
            Some(source.len() - 3..source.len())
        );

        let body = "x\n".repeat(4_096);
        let source = format!("```\n{body}```");
        let document = parse(&source, &mut cx).unwrap();
        assert!(first_code_block(&document.blocks[0]).is_some());
        assert_eq!(
            selected_code_range(&source, body.len() - 2..body.len() - 1),
            Some(body.len() + 2..body.len() + 3)
        );
    }

    #[test]
    fn source_segments_keep_non_linear_mappings_atomic() {
        let source = r"a\* &amp; b";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let paragraph = first_paragraph(&document.blocks[0]).unwrap();
        let segments = &paragraph.children[0].source_segments;

        assert!(
            segments.len() < paragraph.children[0].text.chars().count(),
            "ordinary characters should be compacted into runs"
        );
        assert!(segments.contains(&SourceSegment {
            rendered: 1..2,
            source: 1..3,
            linear: false,
        }));
        assert!(segments.contains(&SourceSegment {
            rendered: 3..4,
            source: 4..9,
            linear: false,
        }));

        assert_eq!(select_rendered_range(source, 1..2), 1..3);
        assert_eq!(select_rendered_range(source, 3..4), 4..9);
    }

    #[test]
    fn source_segments_keep_an_entity_as_long_as_its_characters_atomic() {
        // `&acE;` decodes to `∾̳`: five bytes each, but not one for one.
        let source = "a &acE; b";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let paragraph = first_paragraph(&document.blocks[0]).unwrap();
        assert_eq!(paragraph.children[0].text.as_ref(), "a ∾̳ b");
        assert_eq!(
            paragraph.children[0].source_segments,
            vec![
                SourceSegment {
                    rendered: 0..2,
                    source: 0..2,
                    linear: true,
                },
                SourceSegment {
                    rendered: 2..7,
                    source: 2..7,
                    linear: false,
                },
                SourceSegment {
                    rendered: 7..9,
                    source: 7..9,
                    linear: true,
                },
            ]
        );
        // Selecting the combining mark alone reports the whole entity.
        assert_eq!(select_rendered_range(source, 5..7), 2..7);
    }

    #[test]
    fn selected_source_range_crosses_style_boundaries() {
        let source = "left **bold** right";
        assert_eq!(select_rendered_range(source, 2..12), 2..16);
    }

    #[test]
    fn selected_source_range_maps_inline_code_in_merged_styled_node() {
        let source = "**left `code` right**";
        assert_eq!(selected_rendered_range(source, 5..9), Some(8..12));
    }

    #[test]
    fn selected_source_range_maps_inline_code_delimiters_and_boundaries() {
        let source = "`code` x";
        assert_eq!(selected_rendered_range(source, 0..4), Some(1..5));
        assert_eq!(selected_rendered_range(source, 5..6), Some(7..8));
        assert_eq!(selected_rendered_range(source, 3..6), Some(4..8));

        let padded = "`` code ` value ``";
        assert_eq!(selected_rendered_range(padded, 0..4), Some(3..7));
        assert_eq!(selected_rendered_range(padded, 5..6), Some(8..9));

        let literal_entity = "`&amp;`";
        assert_eq!(selected_rendered_range(literal_entity, 0..5), Some(1..6));
    }

    #[test]
    fn selected_source_range_keeps_inline_code_escapes_literal() {
        assert_eq!(select_rendered_range("`a\\\\b`", 1..2), 2..3);
        assert_eq!(select_rendered_range("`a\\\\b`", 2..3), 3..4);
        assert_eq!(select_rendered_range(r"`a\*b`", 1..2), 2..3);
        assert_eq!(select_rendered_range(r"`a\*b`", 2..3), 3..4);
        // The same punctuation is still an escape outside code.
        assert_eq!(select_rendered_range(r"a\*b", 1..2), 1..3);
    }

    #[test]
    fn selected_source_range_maps_footnote_reference_syntax() {
        let source = "before[^note] after\n\n[^note]: body";
        assert_eq!(selected_rendered_range(source, 0..6), Some(0..6));
        assert_eq!(selected_rendered_range(source, 6..12), Some(6..13));
        assert_eq!(selected_rendered_range(source, 13..18), Some(14..19));
        assert_eq!(selected_rendered_range(source, 4..15), Some(4..16));
    }

    #[test]
    fn selected_source_range_maps_mdx_text_expression_body() {
        let source = "before {value + 1} after";
        assert_eq!(selected_mdx_rendered_range(source, 7..16), Some(8..17));
        assert_eq!(selected_mdx_rendered_range(source, 4..19), Some(4..21));
    }

    #[test]
    fn selected_source_range_maps_mdx_flow_expression_body() {
        let source = "{\n  value + 1\n}";
        assert_eq!(selected_mdx_code(source, "value + 1"), Some(4..13));
        assert_eq!(selected_mdx_code(source, "lue +"), Some(6..11));
    }

    #[test]
    fn selected_source_range_maps_math_block_body() {
        let source = "$$\nx + y\n$$";
        assert_eq!(selected_code_range(source, 0..5), Some(3..8));
        assert_eq!(selected_code_range(source, 2..3), Some(5..6));
    }

    #[test]
    fn selected_source_range_rejects_mapped_block_plus_unmappable_entity() {
        let source = "mapped\n\nA &amp; B";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let [BlockNode::Paragraph(mapped), BlockNode::Paragraph(entity)] =
            document.blocks.as_slice()
        else {
            panic!("expected two paragraphs");
        };
        mapped.state.lock().unwrap().selection = Some((0..6).into());

        entity.state.lock().unwrap().selection = Some((2..2).into());
        assert_eq!(document.selected_source_range(), Some(0..6));

        entity.state.lock().unwrap().selection = Some((2..3).into());
        assert_eq!(document.selected_source_range(), Some(0..15));
    }

    #[test]
    fn selected_source_range_maps_fenced_code_body_after_matching_info_string() {
        let source = "```rust\nrust\n```";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::CodeBlock(code) = &document.blocks[0] else {
            panic!("expected code block");
        };
        code.set_selection(0..4);

        assert_eq!(document.selected_source_range(), Some(8..12));
    }

    #[test]
    fn selected_source_range_maps_each_literal_backslash_in_fenced_code() {
        let source = "```\na\\\\b\n```";
        assert_eq!(selected_code_range(source, 1..2), Some(5..6));
        assert_eq!(selected_code_range(source, 2..3), Some(6..7));
        assert_eq!(selected_code_range(source, 1..3), Some(5..7));
        let punctuation = "```\na\\*b\n```";
        assert_eq!(selected_code_range(punctuation, 1..2), Some(5..6));
        assert_eq!(selected_code_range(punctuation, 2..3), Some(6..7));
        assert_eq!(selected_code_range("```\na\\\\b\r\n```", 1..3), Some(5..7));
        let multiline = "```\na\\\\\nb\n```";
        assert_eq!(selected_code_range(multiline, 1..2), Some(5..6));
        assert_eq!(selected_code_range(multiline, 2..3), Some(6..7));
        assert_eq!(selected_code_range(multiline, 3..4), Some(7..8));
        assert_eq!(selected_code_range(multiline, 4..5), Some(8..9));
    }

    #[test]
    fn selected_source_range_excludes_closing_fence_candidate() {
        let source = "````text\n```\n````";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::CodeBlock(code) = &document.blocks[0] else {
            panic!("expected code block");
        };
        code.set_selection(0..3);

        assert_eq!(document.selected_source_range(), Some(9..12));
    }

    #[test]
    fn selected_source_range_maps_indented_code_content() {
        let source = "    rust";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::CodeBlock(code) = &document.blocks[0] else {
            panic!("expected code block");
        };
        code.set_selection(0..4);

        assert_eq!(document.selected_source_range(), Some(4..8));
    }

    #[test]
    fn selected_source_range_maps_multiline_indented_code() {
        let source = "    one\n    two\n    three";
        assert_eq!(selected_code_range(source, 0..3), Some(4..7));
        assert_eq!(selected_code_range(source, 4..7), Some(12..15));
        assert_eq!(selected_code_range(source, 0..13), Some(4..25));
    }

    #[test]
    fn selected_source_range_maps_literal_backslashes_in_indented_code() {
        let source = "    one\n    a\\\\b";
        assert_eq!(selected_code_range(source, 5..6), Some(13..14));
        assert_eq!(selected_code_range(source, 6..7), Some(14..15));
        assert_eq!(selected_code_range(source, 5..7), Some(13..15));
    }

    #[test]
    fn selected_source_range_maps_fenced_code_nested_in_a_list() {
        let source = "- ```rust\n  one\n  two\n  ```";
        assert_eq!(selected_code_range(source, 0..3), Some(12..15));
        assert_eq!(selected_code_range(source, 4..7), Some(18..21));
        assert_eq!(selected_code_range(source, 0..7), Some(12..21));
    }

    #[test]
    fn selected_source_range_maps_literal_backslashes_in_nested_fences() {
        for source in ["- ```\n  a\\\\b\n  ```", "> ```\n> a\\\\b\n> ```"] {
            assert_eq!(selected_code_range(source, 1..2), Some(9..10));
            assert_eq!(selected_code_range(source, 2..3), Some(10..11));
        }
    }

    #[test]
    fn selected_source_range_maps_fenced_code_nested_in_a_blockquote() {
        let source = "> ```\n> one\n> two\n> ```";
        assert_eq!(selected_code_range(source, 0..3), Some(8..11));
        assert_eq!(selected_code_range(source, 4..7), Some(14..17));
        assert_eq!(selected_code_range(source, 0..7), Some(8..17));
    }

    #[test]
    fn selected_source_range_maps_fenced_code_with_blank_lines_and_repeated_text() {
        let source = "```\nsame\n\nsame\n```";
        assert_eq!(selected_code_range(source, 0..4), Some(4..8));
        assert_eq!(selected_code_range(source, 6..10), Some(10..14));
        assert_eq!(selected_code_range(source, 0..10), Some(4..14));
    }

    #[test]
    fn selected_source_range_maps_the_whole_markdown_escape() {
        assert_eq!(selected_rendered_range(r"\*", 0..1), Some(0..2));
    }

    #[test]
    fn selected_source_range_maps_text_after_an_escape_character_for_character() {
        let source = r"\*abc";
        assert_eq!(select_rendered_range(source, 0..1), 0..2);
        assert_eq!(select_rendered_range(source, 2..3), 3..4);
        assert_eq!(select_rendered_range(source, 0..2), 0..3);
        // Only punctuation escapes, so a backslash before a letter is text.
        let source = r"\été";
        assert_eq!(select_rendered_range(source, 0..1), 0..1);
        assert_eq!(select_rendered_range(source, 1..3), 1..3);
    }

    #[test]
    fn selected_source_range_maps_after_an_escaped_backslash() {
        let source = r"a\\b";
        assert_eq!(select_rendered_range(source, 1..2), 1..3);
        assert_eq!(select_rendered_range(source, 2..3), 3..4);
        assert_eq!(select_rendered_range(source, 1..3), 1..4);

        let repeated = r"\\\\b";
        assert_eq!(select_rendered_range(repeated, 2..3), 4..5);
    }

    #[test]
    fn selected_source_range_does_not_borrow_an_escape_from_the_previous_node() {
        let source = r"a\\$x$";
        assert_eq!(select_rendered_range(source, 2..3), 3..4);
        assert_eq!(select_rendered_range(source, 1..3), 1..4);
    }

    #[test]
    fn selected_source_range_does_not_shift_a_hard_break_after_an_escape() {
        let source = "a\\\\  \nb";
        assert_eq!(select_rendered_range(source, 2..3), 3..6);
        assert_eq!(select_rendered_range(source, 1..3), 1..6);
    }

    #[test]
    fn selected_source_range_includes_a_trailing_inline_image() {
        let source = "before ![alt](image.png)";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };
        let image = paragraph
            .children
            .iter()
            .find(|child| child.image.is_some())
            .expect("expected image");
        let mut state = image.state.lock().unwrap();
        state.set_text("before ".into());
        state.selection = Some((0..7).into());
        drop(state);

        assert_eq!(document.selected_source_range(), Some(0..source.len()));
    }

    #[test]
    fn selected_source_range_includes_a_leading_inline_image() {
        let source = "![alt](image.png) after";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };
        let mut state = paragraph.state.lock().unwrap();
        state.set_text(" after".into());
        state.selection = Some((0..6).into());
        drop(state);

        assert_eq!(document.selected_source_range(), Some(0..source.len()));
    }

    #[test]
    fn selected_source_range_includes_an_enclosed_inline_image() {
        let source = "before ![alt](image.png) after";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };
        let image = paragraph
            .children
            .iter()
            .find(|child| child.image.is_some())
            .expect("expected image");
        let mut before = image.state.lock().unwrap();
        before.set_text("before ".into());
        before.selection = Some((0..7).into());
        drop(before);
        let mut after = paragraph.state.lock().unwrap();
        after.set_text(" after".into());
        after.selection = Some((0..6).into());
        drop(after);

        assert_eq!(document.selected_source_range(), Some(0..source.len()));
    }

    #[test]
    fn selected_source_range_excludes_an_unreached_inline_image() {
        let source = "before ![alt](image.png) after";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };
        let image = paragraph
            .children
            .iter()
            .find(|child| child.image.is_some())
            .expect("expected image");
        let mut before = image.state.lock().unwrap();
        before.set_text("before ".into());
        before.selection = Some((0..3).into());
        drop(before);

        assert_eq!(document.selected_source_range(), Some(0..3));

        image.state.lock().unwrap().selection = None;
        let after_start = source.find("after").unwrap();
        let mut after = paragraph.state.lock().unwrap();
        after.set_text(" after".into());
        after.selection = Some((2..6).into());
        drop(after);

        assert_eq!(
            document.selected_source_range(),
            Some(after_start + 1..source.len())
        );
    }

    #[test]
    fn selected_source_range_includes_consecutive_inline_images() {
        let source = "![first](one.png)![second](two.png) after";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };
        let mut state = paragraph.state.lock().unwrap();
        state.set_text(" after".into());
        state.selection = Some((0..6).into());
        drop(state);

        assert_eq!(document.selected_source_range(), Some(0..source.len()));
    }

    #[test]
    fn selected_source_range_maps_decoded_entity_to_its_source_syntax() {
        let source = "A &amp; B";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };
        assert_eq!(paragraph.text(), "A & B");

        assert_eq!(selected_rendered_range(source, 2..3), Some(2..7));
    }

    #[test]
    fn selected_source_range_maps_around_named_and_numeric_entities() {
        let source = "Copyright &copy; &#x1F600; &#169; 2024";
        assert_eq!(selected_rendered_range(source, 0..9), Some(0..9));
        assert_eq!(selected_rendered_range(source, 10..12), Some(10..16));
        assert_eq!(selected_rendered_range(source, 13..17), Some(17..26));
        assert_eq!(selected_rendered_range(source, 18..20), Some(27..33));
        assert_eq!(selected_rendered_range(source, 21..25), Some(34..38));
        assert_eq!(selected_rendered_range(source, 8..22), Some(8..35));
    }

    #[test]
    fn selected_source_range_maps_soft_breaks_with_source_prefixes() {
        assert_eq!(selected_rendered_range("a\n   b", 0..1), Some(0..1));
        assert_eq!(selected_rendered_range("a\n   b", 2..3), Some(5..6));
        assert_eq!(selected_rendered_range("a\n   b", 0..3), Some(0..6));

        assert_eq!(selected_rendered_range("> a\n> b", 0..1), Some(2..3));
        assert_eq!(selected_rendered_range("> a\n> b", 2..3), Some(6..7));
        assert_eq!(selected_rendered_range("> a\n> b", 0..3), Some(2..7));

        assert_eq!(selected_rendered_range("- a\n  b", 0..1), Some(2..3));
        assert_eq!(selected_rendered_range("- a\n  b", 2..3), Some(6..7));
        assert_eq!(selected_rendered_range("- a\n  b", 0..3), Some(2..7));
    }

    #[test]
    fn selected_source_range_maps_soft_breaks_with_trailing_spaces_and_crlf() {
        assert_eq!(selected_rendered_range("a \nb", 0..1), Some(0..1));
        assert_eq!(selected_rendered_range("a \nb", 1..2), Some(2..3));
        assert_eq!(selected_rendered_range("a \nb", 2..3), Some(3..4));
        assert_eq!(selected_rendered_range("a \nb", 0..3), Some(0..4));

        assert_eq!(selected_rendered_range("a \r\nb", 1..2), Some(2..4));
        assert_eq!(selected_rendered_range("a \r\nb", 2..3), Some(4..5));

        assert_eq!(selected_rendered_range("a\r\nb", 0..1), Some(0..1));
        assert_eq!(selected_rendered_range("a\r\nb", 2..3), Some(3..4));
        assert_eq!(selected_rendered_range("a\r\nb", 0..3), Some(0..4));
    }

    #[test]
    fn test_nested_emphasis_merges_text_marks() {
        let mut cx = NodeContext::default();
        let document = parse("This has **_bold and italic_** text.", &mut cx).unwrap();

        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };

        let bold_italic = paragraph
            .children
            .iter()
            .find(|child| child.text.as_ref() == "bold and italic")
            .expect("expected emphasized text");

        assert!(
            bold_italic
                .marks
                .iter()
                .any(|(_, mark)| mark.bold && mark.italic),
            "nested emphasis should produce a bold and italic mark"
        );
    }

    #[test]
    fn test_reference_images() {
        for (reference, alt) in [
            ("![Alt &amp; text][PiCtUrE]", "Alt & text"),
            ("![picture][]", "picture"),
            ("![picture]", "picture"),
        ] {
            for destination in [
                "https://example.com/image.png",
                "./image.png",
                "file:///image.png",
                "data:image/png;base64,iVBORw0KGgo=",
            ] {
                let source =
                    format!("Before {reference} after.\n\n[picture]: {destination} \"Title\"\n");
                let mut cx = NodeContext {
                    offset: 17,
                    ..Default::default()
                };
                let document = parse(&source, &mut cx).unwrap();
                let paragraph = document.blocks.iter().find_map(first_paragraph).unwrap();
                assert_eq!(paragraph.children.len(), 3, "{source}");
                assert_eq!(paragraph.children[0].text.as_ref(), "Before ");
                assert_eq!(paragraph.children[2].text.as_ref(), " after.");
                let image = paragraph.children[1].as_image().expect("reference image");
                assert_eq!(image.url.as_ref(), destination);
                assert_eq!(image.alt.as_deref(), Some(alt));
                assert_eq!(image.title.as_deref(), Some("Title"));
                assert_eq!(
                    image.span,
                    Some(Span {
                        start: 24,
                        end: 24 + reference.len()
                    })
                );
                assert_eq!(image.width, None);
                assert_eq!(image.height, None);
                match image.source() {
                    gpui::ImageSource::Image(_) => assert!(destination.starts_with("data:")),
                    gpui::ImageSource::Resource(gpui::Resource::Uri(uri)) => {
                        assert!(!destination.starts_with("data:"));
                        assert_eq!(uri.as_ref(), destination);
                    }
                    _ => panic!("unexpected image source"),
                }
            }
        }
    }

    #[test]
    fn test_reference_image_definition_lookup() {
        let source = "![alt][Some   LABEL]\n\n> [some label]: first.png\n\n[some label]: second.png \"Ignored\"\n";
        let document = parse(source, &mut NodeContext::default()).unwrap();
        let paragraph = document.blocks.iter().find_map(first_paragraph).unwrap();
        let image = paragraph.children[0].as_image().expect("reference image");
        assert_eq!(image.url.as_ref(), "first.png");
        assert_eq!(image.title, None);
        assert_eq!(image.alt.as_deref(), Some("alt"));

        let source = "[picture]: image.png\n\n[![alt][picture]](https://example.com)";
        let document = parse(source, &mut NodeContext::default()).unwrap();
        let paragraph = document.blocks.iter().find_map(first_paragraph).unwrap();
        let image = paragraph.children[0]
            .as_image()
            .expect("linked reference image");
        assert_eq!(image.url.as_ref(), "image.png");
        assert_eq!(
            image.link.as_ref().unwrap().url.as_ref(),
            "https://example.com"
        );

        let source = "![missing][unknown] ![collapsed][] ![shortcut]";
        let document = parse(source, &mut NodeContext::default()).unwrap();
        let paragraph = document.blocks.iter().find_map(first_paragraph).unwrap();
        assert_eq!(paragraph.text(), source);
        assert!(
            paragraph
                .children
                .iter()
                .all(|child| child.as_image().is_none())
        );
    }

    #[test]
    fn test_inline_html_image_stays_in_markdown_paragraph() {
        let mut cx = NodeContext::default();
        let document = parse(
            r#"Before <img src="https://example.com/avatar.png" alt="Avatar" width="32" height="32" /> after."#,
            &mut cx,
        )
        .unwrap();

        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };

        assert_eq!(paragraph.children.len(), 3);
        assert_eq!(paragraph.children[0].text.as_ref(), "Before ");
        assert_eq!(paragraph.children[2].text.as_ref(), " after.");

        let image = paragraph.children[1]
            .image
            .as_ref()
            .expect("expected inline html image");
        assert_eq!(image.url.as_ref(), "https://example.com/avatar.png");
        assert_eq!(image.width, Some(gpui::px(32.).into()));
        assert_eq!(image.height, Some(gpui::px(32.).into()));
    }

    #[test]
    fn test_inline_html_image_without_size_stays_in_markdown_paragraph() {
        let mut cx = NodeContext::default();
        let document = parse(
            r#"Before <img src="https://avatars.githubusercontent.com/u/5518"> after."#,
            &mut cx,
        )
        .unwrap();

        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };

        assert_eq!(paragraph.children.len(), 3);
        assert_eq!(paragraph.children[0].text.as_ref(), "Before ");
        assert_eq!(paragraph.children[2].text.as_ref(), " after.");

        let image = paragraph.children[1]
            .image
            .as_ref()
            .expect("expected inline html image");
        assert_eq!(
            image.url.as_ref(),
            "https://avatars.githubusercontent.com/u/5518"
        );
        assert_eq!(image.width, None);
        assert_eq!(image.height, None);
    }

    /// A CommonMark soft break — a bare line ending inside a paragraph —
    /// reflows to a space, so prose hard-wrapped in the source fills the
    /// available width instead of keeping the source's line structure.
    ///
    /// Every line ending CommonMark recognises has to collapse, not just LF:
    /// mdast passes the source's bytes through, so a CRLF document would
    /// otherwise strand its carriage return in the middle of the line.
    #[test]
    fn test_soft_break_reflows_to_space() {
        for source in [
            "this sentence\ncontinues as a soft wrap",
            "this sentence\r\ncontinues as a soft wrap",
            "this sentence\rcontinues as a soft wrap",
        ] {
            let mut cx = NodeContext::default();
            let document = parse(source, &mut cx).unwrap();

            let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
                panic!("expected paragraph");
            };

            assert_eq!(paragraph.children.len(), 1, "source: {source:?}");
            assert_eq!(
                paragraph.children[0].text.as_ref(),
                "this sentence continues as a soft wrap",
                "source: {source:?}"
            );
        }
    }

    /// The two breaks stay distinguishable in one paragraph: the soft one
    /// reflows into the run, the hard one keeps its own newline node.
    ///
    /// This is the invariant the soft-break collapse rests on — a hard break
    /// arrives as `Node::Break` and never as a newline inside `Node::Text`.
    #[test]
    fn test_soft_break_reflows_while_hard_break_survives() {
        let mut cx = NodeContext::default();
        let document = parse("a\nb  \nc", &mut cx).unwrap();

        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected paragraph");
        };

        let texts: Vec<_> = paragraph
            .children
            .iter()
            .map(|child| child.text.as_ref())
            .collect();
        assert_eq!(texts, ["a b", "\n", "c"]);
    }

    /// A CommonMark hard break — two trailing spaces or a trailing backslash —
    /// renders as a newline, instead of joining the two lines.
    #[test]
    fn test_hard_break_renders_newline() {
        for source in [
            "Owner: Jane  \nPersona: assistant",
            "Owner: Jane\\\nPersona: assistant",
        ] {
            let mut cx = NodeContext::default();
            let document = parse(source, &mut cx).unwrap();

            let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
                panic!("expected paragraph");
            };

            assert_eq!(paragraph.children.len(), 3, "source: {source:?}");
            assert_eq!(paragraph.children[0].text.as_ref(), "Owner: Jane");
            assert_eq!(paragraph.children[1].text.as_ref(), "\n");
            assert_eq!(paragraph.children[2].text.as_ref(), "Persona: assistant");
        }
    }

    #[test]
    fn yaml_frontmatter_is_disabled_by_default() {
        let source = "---\nSome text\n---";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();

        assert!(matches!(
            document.blocks[0],
            BlockNode::HorizontalRule { .. }
        ));
        let BlockNode::Heading {
            level, children, ..
        } = &document.blocks[1]
        else {
            panic!("expected setext heading");
        };
        assert_eq!(*level, 2);
        assert_eq!(children.text(), "Some text");
    }

    #[test]
    fn non_mapping_yaml_frontmatter_falls_back_to_code_block() {
        let extensions = MarkdownExtensions::default().frontmatter();
        let mut cx = NodeContext {
            markdown_extensions: extensions.into(),
            ..NodeContext::default()
        };
        let document = parse("---\n- name: example\n---", &mut cx).unwrap();

        let BlockNode::CodeBlock(code_block) = &document.blocks[0] else {
            panic!("expected YAML code block fallback");
        };
        assert_eq!(code_block.lang().as_deref(), Some("yml"));
        assert_eq!(code_block.code().as_ref(), "- name: example");
    }

    #[test]
    fn fenced_yaml_remains_a_code_block() {
        let mut cx = NodeContext::default();
        let document = parse("```yaml\nname: example\n```", &mut cx).unwrap();

        let BlockNode::CodeBlock(code_block) = &document.blocks[0] else {
            panic!("expected fenced YAML code block");
        };
        assert_eq!(code_block.lang().as_deref(), Some("yaml"));
        assert_eq!(code_block.code().as_ref(), "name: example");
    }

    #[derive(Debug, Clone, PartialEq)]
    struct Ticker {
        symbol: String,
    }

    fn parse_ticker_block(node: &Node, cx: &MarkdownParseContext<'_>) -> Option<MarkdownNode> {
        let Node::Paragraph(paragraph) = node else {
            return None;
        };
        let [Node::Text(text)] = paragraph.children.as_slice() else {
            return None;
        };
        let symbol = text.value.strip_prefix('$')?.to_string();
        let node_text = format!("${symbol}");

        Some(
            MarkdownNode::new("ticker", Ticker { symbol })
                .text(node_text)
                .markdown(cx.node_source(node).unwrap_or_default()),
        )
    }

    #[test]
    fn custom_block_parser_converts_ticker_syntax_to_custom_node() {
        let extensions = MarkdownExtensions::default().block_parser(parse_ticker_block);

        let mut cx = NodeContext {
            markdown_extensions: extensions.into(),
            ..NodeContext::default()
        };
        let document = parse("$TSLA.US", &mut cx).unwrap();

        let BlockNode::Custom { node, .. } = &document.blocks[0] else {
            panic!("expected custom markdown node");
        };
        assert_eq!(node.name(), "ticker");
        assert_eq!(node.as_text(), "$TSLA.US");
        assert_eq!(node.as_markdown(), "$TSLA.US");
        assert_eq!(
            node.data::<Ticker>(),
            Some(&Ticker {
                symbol: "TSLA.US".to_string()
            })
        );
        assert_eq!(document.text(), "$TSLA.US\n");
        assert_eq!(document.to_markdown(), "$TSLA.US");
    }

    struct TickerPlugin {
        name: &'static str,
    }

    #[test]
    fn inline_math_is_enabled_by_default_and_respects_code_and_escapes() {
        let extensions = MarkdownExtensions::default().plugin(
            crate::text::markdown_ext::TestInlinePlugin::new("formula").parse_with(|node, _| {
                let Node::InlineMath(math) = node else {
                    return None;
                };
                assert_eq!(math.value, "x");
                Some(MarkdownNode::new("formula", ()).text("formula"))
            }),
        );
        let mut cx = NodeContext {
            markdown_extensions: extensions.into(),
            ..Default::default()
        };
        let document = parse(r"$x$ `$code$` \$escaped\$", &mut cx).unwrap();
        assert_eq!(document.text(), "formula $code$ $escaped$\n");
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        assert_eq!(
            paragraph
                .children
                .iter()
                .filter(|node| node.custom.is_some())
                .count(),
            1
        );
    }

    #[test]
    fn inline_extensions_preserve_nodes_inside_marks_and_global_source_ranges() {
        let source = "中文 **before $x^2$ after** and `$ignored$`";
        let extensions = MarkdownExtensions::default().plugin(
            crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(|node, cx| {
                let Node::InlineMath(math) = node else {
                    return None;
                };
                assert_eq!(cx.node_source(node), Some("$x^2$"));
                Some(MarkdownNode::new("formula", math.value.clone()).text("x²"))
            }),
        );
        let mut cx = NodeContext {
            offset: 50,
            markdown_extensions: extensions.into(),
            ..Default::default()
        };
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        let objects: Vec<_> = paragraph
            .children
            .iter()
            .filter_map(|node| node.custom.as_ref())
            .collect();
        assert_eq!(objects.len(), 1);
        let object = objects[0];
        let start = source.find("$x^2$").unwrap() + 50;
        assert_eq!(object.source_range(), Some(start..start + 5));
        assert_eq!(object.as_text(), "x²");
        assert_eq!(object.as_markdown(), "$x^2$");
        assert_eq!(object.accessibility_name(), "x²");
        assert_eq!(document.text(), "中文 before x² after and $ignored$\n");
        assert!(document.to_markdown().contains("**before $x^2$ after**"));
    }

    #[test]
    fn block_math_parses_as_a_block_and_falls_back_to_a_code_block() {
        // `$$` is a block fence. With only the inline construct enabled it was
        // swallowed as one long inline formula, so a block plugin matching
        // `Node::Math` never fired.
        let source = "$$\n\\sum_{i=1}^{n} i\n$$";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        let BlockNode::CodeBlock(code) = &document.blocks[0] else {
            panic!("expected a code block fallback")
        };
        assert_eq!(code.code(), "\\sum_{i=1}^{n} i");
        assert!(document.to_markdown().contains("\\sum_{i=1}^{n} i"));
    }

    fn bold_runs(paragraph: &Paragraph) -> Vec<String> {
        paragraph
            .children
            .iter()
            .flat_map(|node| {
                node.marks
                    .iter()
                    .filter(|(_, mark)| mark.bold)
                    .map(|(range, _)| node.text[range.clone()].to_string())
                    .collect::<Vec<_>>()
            })
            .collect()
    }

    #[test]
    fn unclaimed_inline_math_parses_its_span_as_prose() {
        // Two dollar amounts pair up into an unclaimed math span. What lies
        // between them is ordinary prose: inline HTML there must still pair
        // with the tags outside the span, and emphasis inside it must render.
        let source =
            "EPS of <strong>$1.56</strong> beat the <strong>$1.50</strong> consensus, *up $2*";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        assert_eq!(
            document.text(),
            "EPS of $1.56 beat the $1.50 consensus, up $2\n"
        );
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        assert_eq!(bold_runs(paragraph), ["$1.56", "$1.50"]);
        assert!(paragraph.children.iter().any(|node| {
            node.marks
                .iter()
                .any(|(range, mark)| mark.italic && node.text[range.clone()] == *"up $2")
        }));
        assert!(document.to_markdown().contains("$1.56"));
    }

    #[test]
    fn claimed_inline_math_survives_prose_flattening() {
        let extensions = MarkdownExtensions::default().plugin(
            crate::text::markdown_ext::TestInlinePlugin::new("formula").parse_with(|node, _| {
                let Node::InlineMath(math) = node else {
                    return None;
                };
                Some(MarkdownNode::new("formula", ()).text(format!("[{}]", math.value)))
            }),
        );
        let mut cx = NodeContext {
            markdown_extensions: extensions.into(),
            ..Default::default()
        };
        let document = parse("area $x^2$ costs $5 and $10", &mut cx).unwrap();
        assert_eq!(document.text(), "area [x^2] costs [5 and ]10\n");
    }

    #[test]
    fn inline_html_formatting_tags_pair_across_siblings() {
        let source = "a <strong>b *c* <em>d</em></strong> e <b>f</b> <i>g</i> <del>h</del> <br> <strong>unclosed";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        assert_eq!(document.text(), "a b c d e f g h \n unclosed\n");
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        assert_eq!(bold_runs(paragraph), ["b c d", "f"]);
        let marked = |predicate: fn(&TextMark) -> bool| -> Vec<String> {
            paragraph
                .children
                .iter()
                .flat_map(|node| {
                    node.marks
                        .iter()
                        .filter(|(_, mark)| predicate(mark))
                        .map(|(range, _)| node.text[range.clone()].to_string())
                        .collect::<Vec<_>>()
                })
                .collect()
        };
        assert_eq!(marked(|mark| mark.italic), ["c", "d", "g"]);
        assert_eq!(marked(|mark| mark.strikethrough), ["h"]);
    }

    fn highlight_runs(paragraph: &Paragraph) -> Vec<(String, gpui::Hsla)> {
        paragraph
            .children
            .iter()
            .flat_map(|node| {
                node.marks
                    .iter()
                    .filter_map(|(range, mark)| {
                        mark.highlight
                            .map(|color| (node.text[range.clone()].to_string(), color))
                    })
                    .collect::<Vec<_>>()
            })
            .collect()
    }

    /// Inline `<mark>` is paired like `<strong>` and keeps the same color
    /// rules as the block HTML path: default yellow, `color`, then
    /// `style="background-color"`.
    #[test]
    fn inline_html_mark_applies_highlight_colors() {
        let source = concat!(
            r#"Plain <mark>highlighted</mark> text and "#,
            r##"<mark data_id="1" color="#ff000059">red</mark> and "##,
            r#"<mark style="background-color: #336699">hex</mark>."#
        );
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        assert_eq!(document.text(), "Plain highlighted text and red and hex.\n");
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        assert_eq!(
            highlight_runs(paragraph),
            [
                ("highlighted".into(), gpui::rgb(0xfef08a).into()),
                (
                    "red".into(),
                    gpui::Rgba::try_from("#ff000059").unwrap().into()
                ),
                (
                    "hex".into(),
                    gpui::Rgba::try_from("#336699").unwrap().into()
                ),
            ]
        );
    }

    #[test]
    fn unclaimed_inline_math_keeps_its_literal_source() {
        // Math parsing is on by default, so prose that merely contains dollar
        // signs parses as a math node. With no plugin to render it, the text
        // must survive display and a Markdown round trip untouched.
        let source = "spent $5 and $10 today";
        let mut cx = NodeContext::default();
        let document = parse(source, &mut cx).unwrap();
        assert_eq!(document.text(), "spent $5 and $10 today\n");
        assert!(document.to_markdown().contains("spent $5 and $10 today"));
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        assert!(paragraph.children.iter().all(|node| node.custom.is_none()));
    }

    #[test]
    fn inline_object_markdown_roundtrip_preserves_nested_emphasis() {
        for source in [
            "*before $x$ after*",
            "*before **$x$** after*",
            "**before *$x$* after**",
        ] {
            let mut cx = NodeContext {
                markdown_extensions: MarkdownExtensions::default()
                    .plugin(
                        crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(
                            |node, _| match node {
                                Node::InlineMath(math) => {
                                    Some(MarkdownNode::new("math", ()).text(math.value.clone()))
                                }
                                _ => None,
                            },
                        ),
                    )
                    .into(),
                ..Default::default()
            };
            let original = parse(source, &mut cx).unwrap();
            let markdown = original.to_markdown();
            let reparsed = parse(&markdown, &mut cx).unwrap();
            let BlockNode::Paragraph(before) = &original.blocks[0] else {
                panic!()
            };
            let BlockNode::Paragraph(after) = &reparsed.blocks[0] else {
                panic!()
            };
            let before_object = before
                .children
                .iter()
                .find(|node| node.custom.is_some())
                .unwrap();
            let after_object = after
                .children
                .iter()
                .find(|node| node.custom.is_some())
                .unwrap();
            assert_eq!(before.text(), after.text(), "{source} -> {markdown}");
            assert_eq!(
                before_object.marks, after_object.marks,
                "{source} -> {markdown}"
            );
        }
    }

    #[test]
    fn inline_parser_without_metadata_falls_back_to_original_source() {
        let mut cx = NodeContext {
            markdown_extensions: MarkdownExtensions::default()
                .plugin(
                    crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(
                        |node, _| {
                            matches!(node, Node::InlineCode(_))
                                .then(|| MarkdownNode::new("opaque", ()))
                        },
                    ),
                )
                .into(),
            ..Default::default()
        };
        let document = parse("`原子`", &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!()
        };
        let node = paragraph.children[0].custom.as_ref().unwrap();
        assert_eq!(node.as_text(), "`原子`");
        assert_eq!(node.as_markdown(), "`原子`");
        assert_eq!(node.accessibility_name(), "`原子`");
    }

    impl TickerPlugin {
        fn new(name: &'static str) -> Self {
            Self { name }
        }
    }

    impl MarkdownPlugin for TickerPlugin {
        fn is_block(&self) -> bool {
            true
        }

        fn name(&self) -> &str {
            self.name
        }

        fn parse(&self, node: &Node, cx: &MarkdownParseContext<'_>) -> Option<MarkdownNode> {
            parse_ticker_block(node, cx)
        }

        fn render(
            &self,
            node: &MarkdownNode,
            _window: &mut gpui::Window,
            _cx: &mut gpui::App,
        ) -> impl gpui::IntoElement {
            gpui::div().child(node.as_text().to_string())
        }
    }

    #[test]
    fn custom_block_plugin_registers_parser_and_renderer() {
        let extensions = MarkdownExtensions::default().plugin(TickerPlugin::new("ticker"));

        let mut cx = NodeContext {
            markdown_extensions: extensions.into(),
            ..NodeContext::default()
        };
        let document = parse("$TSLA.US", &mut cx).unwrap();

        let BlockNode::Custom { node, .. } = &document.blocks[0] else {
            panic!("expected custom markdown node");
        };
        assert_eq!(node.name(), "ticker");
        assert_eq!(
            node.data::<Ticker>(),
            Some(&Ticker {
                symbol: "TSLA.US".to_string()
            })
        );
    }
}
