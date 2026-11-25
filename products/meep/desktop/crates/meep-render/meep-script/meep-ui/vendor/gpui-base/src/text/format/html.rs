use std::cell::RefCell;
use std::collections::HashMap;
use std::ops::Range;
use std::rc::Rc;
use std::sync::Arc;

use gpui::{DefiniteLength, Hsla, SharedString, px, relative};
use html5ever::tendril::TendrilSink;
use html5ever::{LocalName, ParseOpts, local_name, parse_document};
use markup5ever_rcdom::{Node, NodeData, RcDom};

use crate::text::document::ParsedDocument;
use crate::text::node::{
    self, BlockNode, ImageNode, InlineNode, LinkMark, NodeContext, Paragraph, Table, TableRow,
    TextMark,
};

const BLOCK_ELEMENTS: [&str; 35] = [
    "html",
    "body",
    "head",
    "address",
    "article",
    "aside",
    "blockquote",
    "details",
    "summary",
    "dialog",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
    "style",
    "script",
];

/// A paragraph under construction. A literal line feed is content; only a
/// trailing HTML break is removed when the complete text block is taken.
#[derive(Default)]
struct HtmlParagraph {
    content: Paragraph,
    ends_with_break: bool,
}

impl HtmlParagraph {
    fn push(&mut self, node: InlineNode) {
        self.content.push(node);
        self.ends_with_break = false;
    }

    fn push_str(&mut self, text: &str) {
        if !text.is_empty() {
            self.content.push_str(text);
            self.ends_with_break = false;
        }
    }

    fn push_image(&mut self, image: ImageNode) {
        self.push(InlineNode::image(image));
    }

    fn push_break(&mut self) {
        self.content.push(InlineNode::new("\n"));
        self.ends_with_break = true;
    }

    fn take(&mut self) -> Paragraph {
        if self.ends_with_break {
            trim_trailing_break(&mut self.content);
        }
        self.ends_with_break = false;
        self.content.take()
    }
}

/// Parse HTML into AST Node.
pub(crate) fn parse(source: &str, cx: &mut NodeContext) -> Result<ParsedDocument, SharedString> {
    let opts = ParseOpts {
        ..Default::default()
    };

    let bytes = cleanup_html(&source);
    let mut cursor = std::io::Cursor::new(bytes);
    // Ref
    // https://github.com/servo/html5ever/blob/main/rcdom/examples/print-rcdom.rs
    let dom = parse_document(RcDom::default(), opts)
        .from_utf8()
        .read_from(&mut cursor)
        .map_err(|e| SharedString::from(format!("{:?}", e)))?;

    let mut paragraph = HtmlParagraph::default();
    // NOTE: The outer paragraph is not used.
    let node: BlockNode =
        parse_node(&dom.document, &mut paragraph, cx).unwrap_or(BlockNode::Unknown);
    let node = node.compact();

    Ok(ParsedDocument {
        source: source.to_string().into(),
        blocks: Arc::new(vec![node]),
    })
}

fn cleanup_html(source: &str) -> Vec<u8> {
    let mut w = std::io::Cursor::new(vec![]);
    let mut r = std::io::Cursor::new(source);
    let mut minify = super::html5minify::Minifier::new(&mut w);
    minify.omit_doctype(true);
    if let Ok(()) = minify.minify(&mut r) {
        w.into_inner()
    } else {
        source.bytes().collect()
    }
}

fn attr_value(attrs: &RefCell<Vec<html5ever::Attribute>>, name: LocalName) -> Option<String> {
    attrs.borrow().iter().find_map(|attr| {
        if attr.name.local == name {
            Some(attr.value.to_string())
        } else {
            None
        }
    })
}

/// Default `<mark>` background when the tag has no usable color.
pub(super) fn default_mark_color() -> Hsla {
    gpui::rgb(0xfef08a).into()
}

/// Get the highlight background color for a `<mark>` element.
///
/// Reads the `color` attribute first, then the `background-color` declaration
/// from the `style` attribute. Base accepts CSS hex plus common named colors.
fn mark_color(attrs: &RefCell<Vec<html5ever::Attribute>>) -> Option<Hsla> {
    mark_color_from_values(
        attr_value(attrs, local_name!("color")).as_deref(),
        attr_value(attrs, local_name!("style")).as_deref(),
    )
}

/// Resolve a `<mark>` color from raw `color` / `style` attribute values.
///
/// Same rules as the block HTML path: `color` wins, then
/// `style="background-color: …"`.
pub(super) fn mark_color_from_values(color: Option<&str>, style: Option<&str>) -> Option<Hsla> {
    if let Some(value) = color
        && let Some(color) = parse_mark_color(value.trim())
    {
        return Some(color);
    }

    style.and_then(|css_text| parse_mark_color(style_attrs(css_text).get("background-color")?))
}

fn parse_mark_color(value: &str) -> Option<Hsla> {
    if value.starts_with('#') {
        return gpui::Rgba::try_from(value).ok().map(Into::into);
    }
    match value.to_ascii_lowercase().as_str() {
        "black" => Some(gpui::rgb(0x000000).into()),
        "white" => Some(gpui::rgb(0xffffff).into()),
        "blue" => Some(gpui::rgb(0x3b82f6).into()),
        "yellow" => Some(gpui::rgb(0xfacc15).into()),
        _ => None,
    }
}

/// Get style properties to HashMap
/// TODO: Use cssparser to parse style attribute.
fn style_attrs(css_text: &str) -> HashMap<String, String> {
    let mut styles = HashMap::new();
    for decl in css_text.split(';') {
        let mut parts = decl.splitn(2, ':');
        if let (Some(key), Some(value)) = (parts.next(), parts.next()) {
            styles.insert(
                key.trim().to_lowercase().to_string(),
                value.trim().to_string(),
            );
        }
    }

    styles
}

/// Parse length value from style attribute.
///
/// When is percentage, it will be converted to relative length.
/// Else, it will be converted to pixels.
fn value_to_length(value: &str) -> Option<DefiniteLength> {
    if value.ends_with("%") {
        value
            .trim_end_matches("%")
            .parse::<f32>()
            .ok()
            .map(|v| relative(v / 100.))
    } else {
        value
            .trim_end_matches("px")
            .parse()
            .ok()
            .map(|v| px(v).into())
    }
}

/// Get width, height from attributes or parse them from style attribute.
fn attr_width_height(
    attrs: &RefCell<Vec<html5ever::Attribute>>,
) -> (Option<DefiniteLength>, Option<DefiniteLength>) {
    let mut width = None;
    let mut height = None;

    if let Some(value) = attr_value(attrs, local_name!("width")) {
        width = value_to_length(&value);
    }

    if let Some(value) = attr_value(attrs, local_name!("height")) {
        height = value_to_length(&value);
    }

    if width.is_none() || height.is_none() {
        let styles = attr_value(attrs, local_name!("style"))
            .map(|css_text| style_attrs(&css_text))
            .unwrap_or_default();
        if width.is_none() {
            width = styles.get("width").and_then(|v| value_to_length(&v));
        }
        if height.is_none() {
            height = styles.get("height").and_then(|v| value_to_length(&v));
        }
    }

    (width, height)
}

fn parse_table_row(table: &mut Table, node: &Rc<Node>) {
    let mut row = TableRow::default();
    let mut count = 0;
    for child in node.children.borrow().iter() {
        match child.data {
            NodeData::Element {
                ref name,
                ref attrs,
                ..
            } if name.local == local_name!("td") || name.local == local_name!("th") => {
                if child.children.borrow().is_empty() {
                    continue;
                }

                count += 1;
                parse_table_cell(&mut row, child, attrs);
            }
            _ => {}
        }
    }

    if count > 0 {
        table.children.push(row);
    }
}

fn parse_table_cell(
    row: &mut node::TableRow,
    node: &Rc<Node>,
    attrs: &RefCell<Vec<html5ever::Attribute>>,
) {
    let mut paragraph = HtmlParagraph::default();
    for child in node.children.borrow().iter() {
        parse_paragraph(&mut paragraph, child);
    }
    let width = attr_width_height(attrs).0;
    let table_cell = node::TableCell {
        children: paragraph.take(),
        width,
    };
    row.children.push(table_cell);
}

/// Trim text but leave at least one space.
///
/// - Before: " \r\n Hello world \t "
/// - After: " Hello world "
#[allow(dead_code)]
fn trim_text(text: &str) -> String {
    let mut out = String::with_capacity(text.len());

    for (i, c) in text.chars().enumerate() {
        if c.is_whitespace() {
            if i > 0 && out.ends_with(' ') {
                continue;
            }
        }
        out.push(c);
    }

    out
}

fn parse_paragraph(paragraph: &mut HtmlParagraph, node: &Rc<Node>) {
    fn push_merged(
        paragraph: &mut HtmlParagraph,
        text: String,
        marks: Vec<(Range<usize>, TextMark)>,
        new_mark: Option<TextMark>,
    ) {
        if text.is_empty() {
            return;
        }
        let mut node = InlineNode::new(text).marks(marks);
        if let Some(new_mark) = new_mark {
            let len = node.text.len();
            if let Some(last) = node.marks.last_mut()
                && last.0.start == 0
                && last.0.end == len
            {
                last.1.merge(new_mark);
            } else {
                node.marks.push((0..node.text.len(), new_mark));
            }
        }
        paragraph.push(node);
    }

    fn merge_children_with_mark(
        node: &Node,
        paragraph: &mut HtmlParagraph,
        new_mark: Option<TextMark>,
    ) {
        let mut merged_text = String::new();
        let mut merged_marks = Vec::new();
        let mut ends_with_break = None;

        for child in node.children.borrow().iter() {
            let mut child_paragraph = HtmlParagraph::default();
            parse_paragraph(&mut child_paragraph, &child);

            if !child_paragraph.content.is_empty() {
                ends_with_break = Some(child_paragraph.ends_with_break);
            }
            for node in child_paragraph.content.children {
                let offset = merged_text.len();
                merged_text.push_str(&node.text);
                for (range, child_mark) in node.marks {
                    merged_marks.push((range.start + offset..range.end + offset, child_mark));
                }

                if let Some(mut image) = node.image {
                    if let Some(link_mark) = new_mark.as_ref().and_then(|mark| mark.link.clone()) {
                        image.link = Some(link_mark);
                    }

                    push_merged(
                        paragraph,
                        std::mem::take(&mut merged_text),
                        std::mem::take(&mut merged_marks),
                        new_mark.clone(),
                    );

                    paragraph.push(InlineNode::image(image));
                }
            }
        }

        push_merged(paragraph, merged_text, merged_marks, new_mark.clone());
        if let Some(ends_with_break) = ends_with_break {
            paragraph.ends_with_break = ends_with_break;
        }
    }

    match &node.data {
        NodeData::Text { contents } => {
            let part = &contents.borrow();
            paragraph.push_str(&part);
        }
        NodeData::Element { name, attrs, .. } => match name.local {
            local_name!("em") | local_name!("i") => {
                merge_children_with_mark(node, paragraph, Some(TextMark::default().italic()));
            }
            local_name!("strong") | local_name!("b") => {
                merge_children_with_mark(node, paragraph, Some(TextMark::default().bold()));
            }
            local_name!("del") | local_name!("s") => {
                merge_children_with_mark(
                    node,
                    paragraph,
                    Some(TextMark::default().strikethrough()),
                );
            }
            local_name!("u") => {
                merge_children_with_mark(node, paragraph, Some(TextMark::default().underline()));
            }
            local_name!("code") => {
                merge_children_with_mark(node, paragraph, Some(TextMark::default().code()));
            }
            local_name!("mark") => {
                let color = mark_color(&attrs).unwrap_or_else(default_mark_color);
                merge_children_with_mark(
                    node,
                    paragraph,
                    Some(TextMark::default().highlight(color)),
                );
            }
            local_name!("a") => {
                let link_mark = LinkMark {
                    url: attr_value(&attrs, local_name!("href"))
                        .unwrap_or_default()
                        .into(),
                    title: attr_value(&attrs, local_name!("title")).map(Into::into),
                    ..Default::default()
                };

                merge_children_with_mark(
                    node,
                    paragraph,
                    Some(TextMark::default().link(link_mark)),
                );
            }
            local_name!("br") => {
                paragraph.push_break();
            }
            local_name!("img") => {
                let Some(src) = attr_value(attrs, local_name!("src")) else {
                    if cfg!(debug_assertions) {
                        tracing::warn!("Image node missing src attribute");
                    }
                    return;
                };

                let alt = attr_value(attrs, local_name!("alt"));
                let title = attr_value(attrs, local_name!("title"));
                let (width, height) = attr_width_height(attrs);

                paragraph.push_image(ImageNode {
                    url: src.into(),
                    alt: alt.map(Into::into),
                    width,
                    height,
                    title: title.map(Into::into),
                    ..Default::default()
                });
            }
            _ => {
                merge_children_with_mark(node, paragraph, None);
            }
        },
        _ => {
            merge_children_with_mark(node, paragraph, None);
        }
    }
}

fn parse_node(
    node: &Rc<Node>,
    paragraph: &mut HtmlParagraph,
    cx: &mut NodeContext,
) -> Option<BlockNode> {
    match node.data {
        NodeData::Text { ref contents } => {
            let text = contents.borrow().to_string();
            if text.len() > 0 {
                paragraph.push_str(&text);
            }

            None
        }
        NodeData::Element {
            ref name,
            ref attrs,
            ..
        } => match name.local {
            // A line break inside the paragraph being built, as a markdown
            // hard break becomes. As a block of its own it landed apart from
            // the text on both sides, which then stayed on one line.
            local_name!("br") => {
                paragraph.push_break();
                None
            }
            local_name!("h1")
            | local_name!("h2")
            | local_name!("h3")
            | local_name!("h4")
            | local_name!("h5")
            | local_name!("h6") => {
                let mut children = vec![];
                consume_paragraph(&mut children, paragraph);

                let level = name
                    .local
                    .chars()
                    .last()
                    .unwrap_or('6')
                    .to_digit(10)
                    .unwrap_or(6) as u8;

                let mut paragraph = HtmlParagraph::default();
                for child in node.children.borrow().iter() {
                    parse_paragraph(&mut paragraph, child);
                }

                let heading = BlockNode::Heading {
                    level,
                    children: paragraph.take(),
                    span: None,
                };
                if children.len() > 0 {
                    children.push(heading);

                    Some(BlockNode::Root {
                        children,
                        span: None,
                    })
                } else {
                    Some(heading)
                }
            }
            local_name!("img") => {
                let mut children = vec![];
                consume_paragraph(&mut children, paragraph);

                let Some(src) = attr_value(attrs, local_name!("src")) else {
                    if cfg!(debug_assertions) {
                        tracing::warn!("image node missing src attribute");
                    }
                    return None;
                };

                let alt = attr_value(&attrs, local_name!("alt"));
                let title = attr_value(&attrs, local_name!("title"));
                let (width, height) = attr_width_height(&attrs);

                let mut paragraph = HtmlParagraph::default();
                paragraph.push_image(ImageNode {
                    url: src.into(),
                    title: title.map(Into::into),
                    alt: alt.map(Into::into),
                    width,
                    height,
                    ..Default::default()
                });

                if children.len() > 0 {
                    children.push(BlockNode::Paragraph(paragraph.take()));
                    Some(BlockNode::Root {
                        children,
                        span: None,
                    })
                } else {
                    Some(BlockNode::Paragraph(paragraph.take()))
                }
            }
            local_name!("ul") | local_name!("ol") => {
                let ordered = name.local == local_name!("ol");
                let children = consume_children_nodes(node, paragraph, cx);
                Some(BlockNode::List {
                    children,
                    ordered,
                    start: None,
                    span: None,
                })
            }
            local_name!("li") => {
                let mut children = vec![];
                consume_paragraph(&mut children, paragraph);

                let mut ends_with_break = false;
                for child in node.children.borrow().iter() {
                    let mut child_paragraph = HtmlParagraph::default();
                    if let Some(child_node) = parse_node(child, &mut child_paragraph, cx) {
                        children.push(child_node);
                        ends_with_break = false;
                    }
                    if child_paragraph.content.text_len() > 0 {
                        ends_with_break = child_paragraph.ends_with_break;
                        // If last child is paragraph, merge child
                        if let Some(last_child) = children.last_mut() {
                            if let BlockNode::Paragraph(last_paragraph) = last_child {
                                last_paragraph.merge(child_paragraph.content);
                                continue;
                            }
                        }

                        children.push(BlockNode::Paragraph(child_paragraph.content));
                    }
                }

                if ends_with_break && let Some(BlockNode::Paragraph(last)) = children.last_mut() {
                    trim_trailing_break(last);
                }
                consume_paragraph(&mut children, paragraph);

                Some(BlockNode::ListItem {
                    children,
                    spread: false,
                    checked: None,
                    span: None,
                })
            }
            local_name!("table") => {
                let mut children = vec![];
                consume_paragraph(&mut children, paragraph);

                let mut table = Table::default();
                for child in node.children.borrow().iter() {
                    match child.data {
                        NodeData::Element { ref name, .. }
                            if name.local == local_name!("tbody")
                                || name.local == local_name!("thead") =>
                        {
                            for sub_child in child.children.borrow().iter() {
                                parse_table_row(&mut table, &sub_child);
                            }
                        }
                        _ => {
                            parse_table_row(&mut table, &child);
                        }
                    }
                }
                consume_paragraph(&mut children, paragraph);

                let table = BlockNode::Table(table);
                if children.len() > 0 {
                    children.push(table);
                    Some(BlockNode::Root {
                        children,
                        span: None,
                    })
                } else {
                    Some(table)
                }
            }
            local_name!("blockquote") => {
                let children = consume_children_nodes(node, paragraph, cx);
                Some(BlockNode::Blockquote {
                    children,
                    span: None,
                })
            }
            local_name!("style") | local_name!("script") => None,
            _ => {
                if BLOCK_ELEMENTS.contains(&name.local.trim()) {
                    let mut children: Vec<BlockNode> = vec![];

                    // Case:
                    //
                    // Hello <p>Inner text of block element</p> World

                    // Insert before text as a node -- The "Hello"
                    consume_paragraph(&mut children, paragraph);

                    // Inner of the block element -- The "Inner text of block element"
                    for child in node.children.borrow().iter() {
                        if let Some(child_node) = parse_node(child, paragraph, cx) {
                            children.push(child_node);
                        }
                    }
                    consume_paragraph(&mut children, paragraph);

                    if children.is_empty() {
                        None
                    } else {
                        Some(BlockNode::Root {
                            children,
                            span: None,
                        })
                    }
                } else {
                    // Others to as Inline
                    parse_paragraph(paragraph, node);

                    if paragraph.content.is_image() {
                        Some(BlockNode::Paragraph(paragraph.take()))
                    } else {
                        None
                    }
                }
            }
        },
        NodeData::Document => {
            let children = consume_children_nodes(node, paragraph, cx);
            Some(BlockNode::Root {
                children,
                span: None,
            })
        }
        NodeData::Doctype { .. }
        | NodeData::Comment { .. }
        | NodeData::ProcessingInstruction { .. } => None,
    }
}

fn consume_children_nodes(
    node: &Node,
    paragraph: &mut HtmlParagraph,
    cx: &mut NodeContext,
) -> Vec<BlockNode> {
    let mut children = vec![];
    consume_paragraph(&mut children, paragraph);
    for child in node.children.borrow().iter() {
        if let Some(child_node) = parse_node(child, paragraph, cx) {
            children.push(child_node);
        }
        consume_paragraph(&mut children, paragraph);
    }

    children
}

fn consume_paragraph(children: &mut Vec<BlockNode>, paragraph: &mut HtmlParagraph) {
    if paragraph.content.is_empty() {
        return;
    }

    children.push(BlockNode::Paragraph(paragraph.take()));
}

/// Drops one trailing HTML break after the parser has established its
/// provenance. The break may be a separate node or part of a marked run.
/// A standalone break is retained for Markdown's inline-HTML parser.
fn trim_trailing_break(paragraph: &mut Paragraph) {
    if let [only] = paragraph.children.as_slice()
        && only.text == "\n"
    {
        return;
    }
    let Some(last) = paragraph.children.last_mut() else {
        return;
    };
    let Some(text) = last.text.strip_suffix('\n').map(str::to_string) else {
        return;
    };
    if text.is_empty() {
        paragraph.children.pop();
        return;
    }
    let len = text.len();
    last.text = text.into();
    last.marks.retain_mut(|(range, _)| {
        range.end = range.end.min(len);
        range.start < range.end
    });
}

#[cfg(test)]
mod tests {
    use gpui::{px, relative};
    use std::sync::Arc;

    use crate::text::{
        document::ParsedDocument,
        node::{BlockNode, ImageNode, InlineNode, NodeContext, Paragraph},
    };

    use super::trim_text;

    #[test]
    fn test_cleanup_html() {
        let html = r#"<p>
            and
            <code>code</code>
            text
        </p>"#;
        let cleaned = super::cleanup_html(html);
        assert_eq!(
            String::from_utf8(cleaned).unwrap(),
            "<p>and <code>code</code> text"
        );

        let html = r#"<p>
            and
            <em>   <code>code</code>   <i>italic</i>   </em>
            text
        </p>"#;
        let cleaned = super::cleanup_html(html);
        assert_eq!(
            String::from_utf8(cleaned).unwrap(),
            "<p>and <em><code>code</code> <i>italic</i></em> text"
        );
    }

    #[test]
    fn test_pre_text_stays_text() {
        let mut cx = NodeContext::default();
        for (html, text) in [
            // Escaped markup is text, not elements.
            (
                "<pre>&lt;b&gt;bold&lt;/b&gt; &amp;amp;</pre>",
                "<b>bold</b> &amp;",
            ),
            // Spaces, tabs and line feeds stay as they are.
            ("<pre>  one\n\n\ttwo  </pre>", "  one\n\n\ttwo  "),
            // The parser drops only the line feed right after `<pre>`.
            ("<pre>\none</pre>", "one"),
            ("<pre>\n\none</pre>", "\none"),
            // A comment is left out, and the line feed after it kept.
            ("<pre><!-- note -->\none</pre>", "\none"),
        ] {
            let document = super::parse(html, &mut cx).unwrap();
            let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
                panic!("expected one paragraph, got {:?}", document.blocks);
            };
            assert_eq!(paragraph.text(), text, "{html}");
        }
    }

    #[test]
    fn test_pre_keeps_whitespace_in_nested_elements() {
        let mut cx = NodeContext::default();
        for (html, text) in [
            // Code in `<pre><code>` keeps its line feeds and indent.
            (
                "<pre><code>fn main() {\n    one();\n}</code></pre>",
                "fn main() {\n    one();\n}",
            ),
            // So does text deeper down, and the space between elements.
            (
                "<pre><code><b>one</b>  <i>two\n\tthree</i></code></pre>",
                "one  two\n\tthree",
            ),
            // The parser keeps a line feed after `<code>`, unlike `<pre>`.
            ("<pre><code>\none</code></pre>", "\none"),
            // Escaped markup is still text.
            ("<pre><code>&lt;b&gt; &amp;amp;</code></pre>", "<b> &amp;"),
            // Outside `<pre>`, whitespace is collapsed as before.
            ("<p><code>one\n   two</code></p>", "one two"),
        ] {
            let document = super::parse(html, &mut cx).unwrap();
            let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
                panic!("expected one paragraph, got {:?}", document.blocks);
            };
            assert_eq!(paragraph.text(), text, "{html}");
        }
    }

    #[test]
    fn test_trim_text() {
        assert_eq!(trim_text("  \n\tHello world \t\r "), " Hello world ",);
    }

    #[test]
    fn test_mark() {
        let mut cx = NodeContext::default();

        // `<mark>` is rendered as a highlight, kept as `==...==` in markdown.
        let html = r#"<p>Hello <mark>world</mark></p>"#;
        let node = super::parse(html, &mut cx).unwrap();
        assert_eq!(node.to_markdown(), "Hello ==world==");

        let html = r#"<p><mark color="blue">blue</mark> and <mark style="background-color: #336699">hex</mark></p>"#;
        let node = super::parse(html, &mut cx).unwrap();
        assert_eq!(node.to_markdown(), "==blue== and ==hex==");
    }

    #[test]
    fn test_keep_spaces() {
        let html = r#"<p>and <code>code</code> text</p>"#;
        let mut cx = NodeContext::default();
        let node = super::parse(html, &mut cx).unwrap();
        assert_eq!(node.to_markdown(), "and `code` text");

        let html = r#"
            <div>
            <p>
                and
                <em>   <code>code</code>   <i>italic</i>   </em>
                text
            </p>
            <p>
                <img src="https://example.com/image.png" alt="Example" width="100" height="200" title="Example Image" />
            </p>
            <ul>
                <li>Item 1</li>
                <li>Item 2
                </li>
            </ul>
            </div>
        "#;
        let node = super::parse(html, &mut cx).unwrap();
        assert_eq!(
            node.to_markdown(),
            indoc::indoc! {r#"
            and *code italic* text

            ![Example](https://example.com/image.png "Example Image")

            - Item 1
            - Item 2
            "#}
            .trim()
        );
    }

    /// The text of the one paragraph `html` parses to.
    fn paragraph_text(html: &str) -> String {
        let mut cx = NodeContext::default();
        let document = super::parse(html, &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected one paragraph, got {:?}", document.blocks);
        };
        paragraph.text()
    }

    #[test]
    fn test_br_breaks_the_line_where_it_stands() {
        assert_eq!(paragraph_text("<p>one<br>two</p>"), "one\ntwo");
        assert_eq!(
            paragraph_text("one<br>two<br><br>three"),
            "one\ntwo\n\nthree"
        );
        assert_eq!(paragraph_text("<b>one<br>two</b>"), "one\ntwo");
        // The minifier trims the spaces around it.
        assert_eq!(paragraph_text("<p>one <br> two</p>"), "one\ntwo");
        // As in a browser, a break that ends a block adds no line.
        assert_eq!(paragraph_text("<p>one<br></p>"), "one");
        assert_eq!(paragraph_text("<p>one<br><br></p>"), "one\n");
        // Markdown parses inline HTML one tag at a time and needs the break.
        assert_eq!(paragraph_text("<br>"), "\n");
    }

    #[test]
    fn test_br_that_ends_inline_markup() {
        // Inside inline markup the break joins the text before it in one
        // run; at the end of the block it still adds no line.
        for tag in ["b", "span"] {
            assert_eq!(
                paragraph_text(&format!("<p><{tag}>one<br></{tag}></p>")),
                "one",
                "{tag}"
            );
            assert_eq!(
                paragraph_text(&format!("<p><{tag}>one<br><br></{tag}></p>")),
                "one\n",
                "{tag}"
            );
            assert_eq!(
                paragraph_text(&format!("<p><{tag}>one<br>two</{tag}></p>")),
                "one\ntwo",
                "{tag}"
            );
        }
        assert_eq!(paragraph_text("<p>one<b><br></b></p>"), "one");
        assert_eq!(paragraph_text("<p><b>one<br></b><br></p>"), "one\n");

        // The marks end with the text they kept.
        let mut cx = NodeContext::default();
        let document = super::parse("<p><b>one<br></b></p>", &mut cx).unwrap();
        let BlockNode::Paragraph(paragraph) = &document.blocks[0] else {
            panic!("expected one paragraph, got {:?}", document.blocks);
        };
        let [node] = paragraph.children.as_slice() else {
            panic!("expected one node, got {:?}", paragraph.children);
        };
        assert!(
            node.marks.iter().all(|(range, _)| *range == (0..3)),
            "{:?}",
            node.marks
        );
        assert!(node.marks.iter().any(|(_, mark)| mark.bold));
    }

    #[test]
    fn test_literal_trailing_line_feeds_are_preserved() {
        for (html, expected) in [
            ("<pre>one\n</pre>", "one\n"),
            ("<pre>one\n\n</pre>", "one\n\n"),
            ("<pre>one\n<br></pre>", "one\n"),
            ("<pre>one<br>\n</pre>", "one\n\n"),
            ("<textarea>one\n</textarea>", "one\n"),
        ] {
            assert_eq!(paragraph_text(html), expected, "{html}");
        }
    }

    #[test]
    fn test_trailing_breaks_at_text_block_boundaries() {
        for tag in ["p", "h1", "h6", "td", "th", "li"] {
            for (content, expected) in [
                ("one<br>", "one"),
                ("one<br><br>", "one\n"),
                ("<b>one<br></b>", "one"),
                ("<span>one<br><br></span>", "one\n"),
                ("one<br>two", "one\ntwo"),
                ("one<br><span></span>", "one"),
            ] {
                let html = match tag {
                    "td" | "th" => format!("<table><tr><{tag}>{content}</{tag}></tr></table>"),
                    "li" => format!("<ul><li>{content}</li></ul>"),
                    _ => format!("<{tag}>{content}</{tag}>"),
                };
                let mut cx = NodeContext::default();
                let document = super::parse(&html, &mut cx).unwrap();
                let paragraph = match &document.blocks[0] {
                    BlockNode::Paragraph(paragraph)
                    | BlockNode::Heading {
                        children: paragraph,
                        ..
                    } => paragraph,
                    BlockNode::Table(table) => &table.children[0].children[0].children,
                    BlockNode::List { children, .. } => {
                        let BlockNode::ListItem { children, .. } = &children[0] else {
                            panic!("expected list item: {html}");
                        };
                        let [BlockNode::Paragraph(paragraph)] = children.as_slice() else {
                            panic!("expected one paragraph: {html}");
                        };
                        paragraph
                    }
                    _ => panic!("expected text block: {html}"),
                };
                assert_eq!(paragraph.text(), expected, "{html}");
                for node in &paragraph.children {
                    assert!(
                        node.marks
                            .iter()
                            .all(|(range, _)| range.start < range.end
                                && range.end <= node.text.len()),
                        "mark outside text: {html}"
                    );
                }
            }
        }
    }

    #[test]
    fn test_value_to_length() {
        assert_eq!(super::value_to_length("100px"), Some(px(100.).into()));
        assert_eq!(super::value_to_length("100%"), Some(relative(1.)));
        assert_eq!(super::value_to_length("56%"), Some(relative(0.56)));
        assert_eq!(super::value_to_length("240"), Some(px(240.).into()));
    }

    #[test]
    fn test_image() {
        let html = r#"<img src="https://example.com/image.png" alt="Example" width="100" height="200" title="Example Image" />"#;
        let mut cx = NodeContext::default();
        let node = super::parse(html, &mut cx).unwrap();
        assert_eq!(
            node,
            ParsedDocument {
                source: html.to_string().into(),
                blocks: Arc::new(vec![BlockNode::Paragraph(Paragraph {
                    span: None,
                    children: vec![InlineNode::image(ImageNode {
                        url: "https://example.com/image.png".to_string().into(),
                        alt: Some("Example".to_string().into()),
                        width: Some(px(100.).into()),
                        height: Some(px(200.).into()),
                        title: Some("Example Image".to_string().into()),
                        ..Default::default()
                    })],
                    ..Default::default()
                })])
            }
        );

        let html = r#"<img src="https://example.com/image.png" alt="Example" style="width: 80%" title="Example Image" />"#;
        let node = super::parse(html, &mut cx).unwrap();
        assert_eq!(
            node,
            ParsedDocument {
                source: html.to_string().into(),
                blocks: Arc::new(vec![BlockNode::Paragraph(Paragraph {
                    span: None,
                    children: vec![InlineNode::image(ImageNode {
                        url: "https://example.com/image.png".to_string().into(),
                        alt: Some("Example".to_string().into()),
                        width: Some(relative(0.8)),
                        height: None,
                        title: Some("Example Image".to_string().into()),
                        ..Default::default()
                    })],
                    ..Default::default()
                })])
            }
        );
    }
}
