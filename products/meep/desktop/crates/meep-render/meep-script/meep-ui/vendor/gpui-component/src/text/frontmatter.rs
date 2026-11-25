use gpui::{App, IntoElement, SharedString, Window};
use markdown::mdast;

use crate::description_list::{DescriptionItem, DescriptionList};

use super::{MarkdownNode, MarkdownParseContext, MarkdownPlugin};

const NODE_NAME: &str = "frontmatter";

#[derive(Debug, Clone, PartialEq)]
struct FrontmatterEntry {
    key: SharedString,
    value: SharedString,
}

#[derive(Debug, Clone, PartialEq)]
struct Frontmatter {
    entries: Vec<FrontmatterEntry>,
}

impl Frontmatter {
    fn text(&self) -> String {
        self.entries
            .iter()
            .map(|entry| format!("{}: {}", entry.key, entry.value))
            .collect::<Vec<_>>()
            .join("\n")
    }
}

/// Renders top-level YAML frontmatter mappings as a description list.
///
/// Enable frontmatter parsing with [`super::MarkdownExtensions::frontmatter`]
/// before registering this plugin. Values are rendered as plain text; YAML
/// block scalars with `|-` and `>-` are supported. Quoted/compound values,
/// comments after values, other block headers, and more-indented folded lines
/// use TextView's YAML code block fallback.
#[derive(Default)]
pub struct FrontmatterPlugin;

impl FrontmatterPlugin {
    pub fn new() -> Self {
        Self
    }
}

impl MarkdownPlugin for FrontmatterPlugin {
    fn is_block(&self) -> bool {
        true
    }

    fn name(&self) -> &str {
        NODE_NAME
    }

    fn parse(&self, node: &mdast::Node, cx: &MarkdownParseContext<'_>) -> Option<MarkdownNode> {
        let mdast::Node::Yaml(yaml) = node else {
            return None;
        };
        let frontmatter = parse_frontmatter(&yaml.value)?;
        let text = frontmatter.text();

        Some(
            MarkdownNode::new(NODE_NAME, frontmatter)
                .text(text)
                .markdown(cx.node_source(node).unwrap_or(yaml.value.as_str())),
        )
    }

    fn render(&self, node: &MarkdownNode, _window: &mut Window, _cx: &mut App) -> impl IntoElement {
        let frontmatter = node.data::<Frontmatter>().expect("frontmatter node data");

        DescriptionList::horizontal()
            .label_width(gpui::rems(12.))
            .columns(1)
            .children(
                frontmatter.entries.iter().map(|entry| {
                    DescriptionItem::new(entry.key.clone()).value(entry.value.clone())
                }),
            )
    }
}

fn parse_frontmatter(value: &str) -> Option<Frontmatter> {
    #[derive(Clone, Copy)]
    enum ScalarStyle {
        Plain,
        Folded,
        Literal,
        Empty,
    }

    struct Entry {
        key: String,
        value: String,
        style: ScalarStyle,
        indent: Option<usize>,
        lines: usize,
    }

    fn push_continuation(entry: &mut Entry, line: &str) -> Option<()> {
        // Remove only the structural indentation, never scalar content spaces.
        let line = if line.is_empty() {
            ""
        } else {
            let indent = line.bytes().take_while(|byte| *byte == b' ').count();
            if indent == line.len() && entry.indent.is_none() {
                // Its significance depends on the indentation of a later line.
                return None;
            }
            let required = *entry.indent.get_or_insert(indent);
            if required == 0 || (indent < required && indent != line.len()) {
                return None;
            }
            &line[required.min(line.len())..]
        };
        match entry.style {
            ScalarStyle::Folded => {
                // Folding more-indented lines requires a wider YAML grammar.
                if line.starts_with([' ', '\t']) {
                    return None;
                }
                if line.is_empty() {
                    entry.value.push('\n');
                    entry.lines += 1;
                    return Some(());
                }
                if !entry.value.is_empty() && !entry.value.ends_with('\n') {
                    entry.value.push(' ');
                }
            }
            ScalarStyle::Literal => {
                if entry.lines > 0 {
                    entry.value.push('\n');
                }
            }
            ScalarStyle::Plain | ScalarStyle::Empty => return None,
        }
        entry.value.push_str(line);
        entry.lines += 1;
        Some(())
    }

    fn is_plain_key(key: &str) -> bool {
        !key.is_empty()
            && key
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_'))
    }

    let mut entries = Vec::new();
    let mut current: Option<Entry> = None;

    for line in value.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            if current.as_ref().is_some_and(|entry| {
                matches!(entry.style, ScalarStyle::Folded | ScalarStyle::Literal)
            }) {
                push_continuation(current.as_mut()?, line)?;
            }
            continue;
        }

        let is_top_level = !line.starts_with([' ', '\t']);
        if trimmed.starts_with('#')
            && (is_top_level
                || !current.as_ref().is_some_and(|entry| {
                    matches!(entry.style, ScalarStyle::Folded | ScalarStyle::Literal)
                }))
        {
            continue;
        }

        if is_top_level {
            let (key, raw_value) = line.split_once(':')?;
            if !raw_value.is_empty() && !raw_value.starts_with([' ', '\t']) {
                return None;
            }
            let key = key.trim();
            if !is_plain_key(key) {
                return None;
            }

            if let Some(entry) = current.take() {
                entries.push(entry);
            }

            let raw_value = raw_value.trim();
            let (value, style) = match raw_value {
                ">-" => (String::new(), ScalarStyle::Folded),
                "|-" => (String::new(), ScalarStyle::Literal),
                "" => (String::new(), ScalarStyle::Empty),
                _ => {
                    // Decline syntax we cannot interpret faithfully. The caller
                    // preserves it using the existing YAML code block fallback.
                    if raw_value.starts_with([
                        '\'', '"', '[', ']', '{', '}', '&', '*', '!', '|', '>', '#', '%', '@', '`',
                    ]) || ["- ", "? ", ": ", "-\t", "?\t", ":\t"]
                        .iter()
                        .any(|prefix| raw_value.starts_with(prefix))
                        || raw_value.ends_with(':')
                        || [" #", "\t#", ": ", ":\t"]
                            .iter()
                            .any(|pattern| raw_value.contains(pattern))
                    {
                        return None;
                    }
                    (raw_value.to_string(), ScalarStyle::Plain)
                }
            };
            current = Some(Entry {
                key: key.to_string(),
                value,
                style,
                indent: None,
                lines: 0,
            });
        } else if current
            .as_ref()
            .is_some_and(|entry| matches!(entry.style, ScalarStyle::Folded | ScalarStyle::Literal))
        {
            push_continuation(current.as_mut()?, line)?;
        } else {
            return None;
        }
    }

    if let Some(entry) = current {
        entries.push(entry);
    }
    if entries.is_empty() {
        return None;
    }

    Some(Frontmatter {
        entries: entries
            .into_iter()
            .map(|entry| FrontmatterEntry {
                key: entry.key.into(),
                value: if matches!(entry.style, ScalarStyle::Folded | ScalarStyle::Literal) {
                    entry.value.trim_end_matches('\n').to_owned().into()
                } else {
                    entry.value.into()
                },
            })
            .collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_plain_mapping_as_metadata() {
        let frontmatter = parse_frontmatter(
            "name: gpui-component-dev\ndescription: Contributing to `crates/ui`.",
        )
        .expect("frontmatter mapping");

        assert_eq!(frontmatter.entries.len(), 2);
        assert_eq!(frontmatter.entries[0].key.as_ref(), "name");
        assert_eq!(frontmatter.entries[0].value.as_ref(), "gpui-component-dev");
        assert_eq!(
            frontmatter.entries[1].value.as_ref(),
            "Contributing to `crates/ui`."
        );
    }

    #[test]
    fn parses_block_scalars() {
        let frontmatter = parse_frontmatter(
            "description: >-\n  First line\n  second line.\nnotes: |-\n  # literal content\n\n  second line",
        )
        .expect("frontmatter mapping");

        assert_eq!(
            frontmatter.entries[0].value.as_ref(),
            "First line second line."
        );
        assert_eq!(
            frontmatter.entries[1].value.as_ref(),
            "# literal content\n\nsecond line"
        );
    }

    #[test]
    fn preserves_blank_lines_in_folded_scalars() {
        let frontmatter =
            parse_frontmatter("description: >-\n  First paragraph.\n\n  Second paragraph.")
                .expect("frontmatter mapping");

        assert_eq!(
            frontmatter.entries[0].value.as_ref(),
            "First paragraph.\nSecond paragraph."
        );
    }

    #[test]
    fn preserves_indented_hashes_in_folded_scalars() {
        let frontmatter =
            parse_frontmatter("description: >-\n  First line\n  # not a comment\n  last line")
                .expect("frontmatter mapping");

        assert_eq!(
            frontmatter.entries[0].value.as_ref(),
            "First line # not a comment last line"
        );
    }

    #[test]
    fn rejects_nested_mappings() {
        assert!(parse_frontmatter("config:\n  theme: dark").is_none());
    }

    #[test]
    fn rejects_non_mapping_yaml() {
        assert!(parse_frontmatter("- name: example").is_none());
    }

    #[test]
    fn preserves_literal_scalar_whitespace() {
        let parsed = parse_frontmatter("notes: |-\n\n  first  \n    indented\n    \n  last\n\n")
            .expect("literal scalar");
        assert_eq!(
            parsed.entries[0].value.as_ref(),
            "\nfirst  \n  indented\n  \nlast"
        );
    }

    #[test]
    fn rejects_unsupported_scalar_syntax() {
        for source in [
            "title: Hello # comment",
            "title: \"Hello\\nworld\"",
            "title: 'Hello'",
            "tags: [one, two]",
            "config: {theme: dark}",
            "value: &anchor hello",
            "value: *anchor",
            "value: !!str hello",
            "value: a: b",
            "notes: >-\n  first\n    indented\n  last",
            "notes: |-\n    first\n  invalid indentation",
            "notes: |2-\n  text",
            "notes: |\n  text",
            "notes: >+\n  text",
        ] {
            assert!(parse_frontmatter(source).is_none(), "{source:?}");
        }
    }

    #[test]
    fn preserves_plain_scalar_punctuation() {
        let parsed = parse_frontmatter("url: https://example.com/#section\nvalue: -42")
            .expect("plain values");
        assert_eq!(
            parsed.entries[0].value.as_ref(),
            "https://example.com/#section"
        );
        assert_eq!(parsed.entries[1].value.as_ref(), "-42");
    }
}
