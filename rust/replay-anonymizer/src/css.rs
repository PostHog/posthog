use std::borrow::Cow;
use std::collections::BTreeMap;

use simd_json::borrowed::{Object, Value};

use crate::assets::{
    is_numbered_placeholder, numbered_placeholder, CSS_IMAGE_REFS_ATTR_PREFIX, PLACEHOLDER_SRC,
};
use crate::blur::is_image_data_uri;
use crate::collect::{is_image_ref, is_image_ref_strict};
use crate::context::{Ctx, ImageSource};
use crate::images::ImageFallback;
use crate::json::{as_array_mut, as_object_mut, as_str, string_value};

pub const INLINED_STYLESHEET_ATTR: &str = "_cssText";

#[derive(Clone, Copy)]
pub enum CssContext<'a> {
    DeclarationList,
    Property(&'a str),
    Stylesheet,
}

pub struct CssRewrite {
    pub css: String,
    pub refs: BTreeMap<String, String>,
}

struct DeclarationRange {
    start: usize,
    end: usize,
    property: &'static str,
}

pub fn is_strict_css_refs(value: &Value<'_>) -> bool {
    let Some(encoded) = as_str(value) else {
        return false;
    };
    let Ok(refs) = serde_json::from_str::<BTreeMap<String, String>>(encoded) else {
        return false;
    };
    !refs.is_empty()
        && refs
            .values()
            .all(|reference| is_image_ref_strict(reference))
        && (0..refs.len()).all(|slot| refs.contains_key(&slot.to_string()))
}

pub fn scrub_css_images(
    ctx: &Ctx<'_>,
    container: &mut Object<'_>,
    key: &str,
    context: CssContext<'_>,
) -> bool {
    let Some(css) = container.get(key).and_then(as_str).map(str::to_string) else {
        return false;
    };
    let Some(rewrite) = rewrite(ctx, &css, context) else {
        return false;
    };
    container.insert(Cow::Owned(key.to_string()), string_value(rewrite.css));
    if !rewrite.refs.is_empty() {
        let encoded = serde_json::to_string(&rewrite.refs).expect("string map serializes");
        container.insert(
            Cow::Owned(format!("{CSS_IMAGE_REFS_ATTR_PREFIX}{key}")),
            string_value(encoded),
        );
    }
    true
}

pub fn scrub_style_sheet_rule(ctx: &Ctx<'_>, data: &mut Object<'_>) -> bool {
    let mut changed = scrub_css_images(ctx, data, "replace", CssContext::Stylesheet);
    changed |= scrub_css_images(ctx, data, "replaceSync", CssContext::Stylesheet);
    if let Some(adds) = data.get_mut("adds").and_then(as_array_mut) {
        changed |= scrub_rule_list(ctx, adds);
    }
    changed
}

pub fn scrub_style_declaration(ctx: &Ctx<'_>, data: &mut Object<'_>) -> bool {
    let Some(set) = data.get_mut("set").and_then(as_object_mut) else {
        return false;
    };
    let property = set
        .get("property")
        .and_then(as_str)
        .unwrap_or("")
        .to_string();
    scrub_css_images(ctx, set, "value", CssContext::Property(&property))
}

pub fn scrub_adopted_style_sheet(ctx: &Ctx<'_>, data: &mut Object<'_>) -> bool {
    let Some(styles) = data.get_mut("styles").and_then(as_array_mut) else {
        return false;
    };
    let mut changed = false;
    for style in styles.iter_mut() {
        if let Some(style) = as_object_mut(style) {
            if let Some(rules) = style.get_mut("rules").and_then(as_array_mut) {
                changed |= scrub_rule_list(ctx, rules);
            }
        }
    }
    changed
}

fn scrub_rule_list(ctx: &Ctx<'_>, rules: &mut Vec<Value<'_>>) -> bool {
    let mut changed = false;
    for rule in rules.iter_mut() {
        if let Some(rule) = as_object_mut(rule) {
            changed |= scrub_css_images(ctx, rule, "rule", CssContext::Stylesheet);
        }
    }
    changed
}

pub(crate) fn rewrite(ctx: &Ctx<'_>, css: &str, context: CssContext<'_>) -> Option<CssRewrite> {
    let ranges = declaration_value_ranges(css, context);
    if ranges.is_empty() {
        return None;
    }
    let mut refs = BTreeMap::new();
    let mut output = String::with_capacity(css.len());
    let mut copied_to = 0;
    let mut changed = false;
    for range in ranges {
        output.push_str(&css[copied_to..range.start]);
        let (rewritten, value_changed) =
            rewrite_value(ctx, &css[range.start..range.end], range.property, &mut refs);
        output.push_str(&rewritten);
        copied_to = range.end;
        changed |= value_changed;
    }
    if !changed {
        return None;
    }
    output.push_str(&css[copied_to..]);
    Some(CssRewrite { css: output, refs })
}

fn declaration_value_ranges(css: &str, context: CssContext<'_>) -> Vec<DeclarationRange> {
    if let CssContext::Property(property) = context {
        return image_property(property)
            .map(|property| DeclarationRange {
                start: 0,
                end: css.len(),
                property,
            })
            .into_iter()
            .collect();
    }

    let bytes = css.as_bytes();
    let mut ranges = Vec::new();
    let mut segment_start = 0;
    let mut brace_depth = 0usize;
    let mut paren_depth = 0usize;
    let mut bracket_depth = 0usize;
    let mut position = 0;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        match bytes[position] {
            b'(' => paren_depth += 1,
            b')' => paren_depth = paren_depth.saturating_sub(1),
            b'[' => bracket_depth += 1,
            b']' => bracket_depth = bracket_depth.saturating_sub(1),
            b'{' if paren_depth == 0 && bracket_depth == 0 => {
                brace_depth += 1;
                segment_start = position + 1;
            }
            b'}' if paren_depth == 0 && bracket_depth == 0 => {
                brace_depth = brace_depth.saturating_sub(1);
                segment_start = position + 1;
            }
            b';' if paren_depth == 0 && bracket_depth == 0 => {
                segment_start = position + 1;
            }
            b':' if paren_depth == 0 && bracket_depth == 0 => {
                if let Some(property) = image_property(css[segment_start..position].trim()) {
                    ranges.push(DeclarationRange {
                        start: position + 1,
                        end: declaration_end(bytes, position + 1, brace_depth),
                        property,
                    });
                }
            }
            _ => {}
        }
        position += 1;
    }
    ranges
}

fn declaration_end(bytes: &[u8], start: usize, brace_depth: usize) -> usize {
    let mut position = start;
    let mut paren_depth = 0usize;
    let mut bracket_depth = 0usize;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        match bytes[position] {
            b'(' => paren_depth += 1,
            b')' => paren_depth = paren_depth.saturating_sub(1),
            b'[' => bracket_depth += 1,
            b']' => bracket_depth = bracket_depth.saturating_sub(1),
            b';' if paren_depth == 0 && bracket_depth == 0 => return position,
            b'}' if paren_depth == 0 && bracket_depth == 0 && brace_depth > 0 => return position,
            _ => {}
        }
        position += 1;
    }
    bytes.len()
}

fn image_property(property: &str) -> Option<&'static str> {
    match property.trim().to_ascii_lowercase().as_str() {
        "background" => Some("background"),
        "background-image" => Some("background-image"),
        "border-image" => Some("border-image"),
        "border-image-source" => Some("border-image-source"),
        "content" => Some("content"),
        "cursor" => Some("cursor"),
        "list-style" => Some("list-style"),
        "list-style-image" => Some("list-style-image"),
        "mask" => Some("mask"),
        "mask-border" => Some("mask-border"),
        "mask-border-source" => Some("mask-border-source"),
        "mask-image" => Some("mask-image"),
        "shape-outside" => Some("shape-outside"),
        "symbols" => Some("symbols"),
        "-webkit-border-image" => Some("-webkit-border-image"),
        "-webkit-border-image-source" => Some("-webkit-border-image-source"),
        "-webkit-box-reflect" => Some("-webkit-box-reflect"),
        "-webkit-mask" => Some("-webkit-mask"),
        "-webkit-mask-box-image" => Some("-webkit-mask-box-image"),
        "-webkit-mask-box-image-source" => Some("-webkit-mask-box-image-source"),
        "-webkit-mask-image" => Some("-webkit-mask-image"),
        _ => None,
    }
}

fn rewrite_value(
    ctx: &Ctx<'_>,
    value: &str,
    property: &'static str,
    refs: &mut BTreeMap<String, String>,
) -> (String, bool) {
    let bytes = value.as_bytes();
    let mut output = String::with_capacity(value.len());
    let mut copied_to = 0;
    let mut position = 0;
    let mut changed = false;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if function_at(bytes, position, b"image-set")
            || function_at(bytes, position, b"-webkit-image-set")
        {
            let name_len = if bytes[position] == b'-' {
                b"-webkit-image-set".len()
            } else {
                b"image-set".len()
            };
            let open = position + name_len;
            let Some(end) = matching_paren(bytes, open) else {
                break;
            };
            let selected = select_image_set_candidate(&value[open + 1..end - 1]);
            let replacement = selected
                .as_deref()
                .map(|source| replacement_url(ctx, source, property, refs))
                .unwrap_or_else(|| format!("url(\"{PLACEHOLDER_SRC}\")"));
            output.push_str(&value[copied_to..position]);
            output.push_str(&replacement);
            copied_to = end;
            position = end;
            changed = true;
            continue;
        }
        if function_at(bytes, position, b"url") {
            let Some((end, source)) = parse_url_function(value, position) else {
                break;
            };
            let replacement = replacement_url(ctx, &source, property, refs);
            let original = &value[position..end];
            if replacement != original {
                output.push_str(&value[copied_to..position]);
                output.push_str(&replacement);
                copied_to = end;
                changed = true;
            }
            position = end;
            continue;
        }
        position += 1;
    }
    if !changed {
        return (value.to_string(), false);
    }
    output.push_str(&value[copied_to..]);
    (output, true)
}

fn replacement_url(
    ctx: &Ctx<'_>,
    source: &str,
    property: &'static str,
    refs: &mut BTreeMap<String, String>,
) -> String {
    let source = source.trim();
    if source == PLACEHOLDER_SRC || is_numbered_placeholder(source) {
        return format!("url(\"{source}\")");
    }
    if source.starts_with('#') {
        return format!("url(\"{source}\")");
    }
    if ctx.keeps_image_refs() && is_image_ref_strict(source) {
        return format!("url(\"{source}\")");
    }
    let reference = if is_image_data_uri(source) {
        let replacement = ctx.scrub_image_from(
            source,
            ImageFallback::Blank,
            ImageSource::CssProperty(property),
        );
        if is_image_ref(&replacement) {
            Some(replacement)
        } else {
            return format!("url(\"{replacement}\")");
        }
    } else if source.contains('\\') {
        None
    } else {
        ctx.collect_url_from(source, ImageSource::CssProperty(property))
    };
    match reference {
        Some(reference) => {
            let slot = refs.len();
            refs.insert(slot.to_string(), reference);
            format!("url(\"{}\")", numbered_placeholder(slot))
        }
        None => format!("url(\"{PLACEHOLDER_SRC}\")"),
    }
}

fn parse_url_function(value: &str, start: usize) -> Option<(usize, String)> {
    let bytes = value.as_bytes();
    let mut position = start + 4;
    skip_whitespace(bytes, &mut position);
    let source = if matches!(bytes.get(position), Some(b'\'' | b'"')) {
        let content_start = position + 1;
        let end = skip_quoted(bytes, position)?;
        let content_end = end - 1;
        position = end;
        skip_whitespace(bytes, &mut position);
        if bytes.get(position) != Some(&b')') {
            return None;
        }
        let source = value[content_start..content_end].to_string();
        if source.as_bytes().contains(&b'\\') {
            return None;
        }
        source
    } else {
        let content_start = position;
        while !matches!(bytes.get(position), None | Some(b')')) {
            position += 1;
        }
        let source = value[content_start..position].trim().to_string();
        if source.is_empty() || source.as_bytes().contains(&b'\\') {
            return None;
        }
        source
    };
    (bytes.get(position) == Some(&b')')).then_some((position + 1, source))
}

fn select_image_set_candidate(contents: &str) -> Option<String> {
    let mut best: Option<(f64, String)> = None;
    for candidate in split_image_set_candidates(contents)? {
        let (source, remainder) = parse_image_set_source(candidate.trim())?;
        let resolution = parse_resolution(remainder)?;
        if best
            .as_ref()
            .is_none_or(|(best_resolution, _)| resolution > *best_resolution)
        {
            best = Some((resolution, source));
        }
    }
    best.map(|(_, source)| source)
}

fn split_image_set_candidates(contents: &str) -> Option<Vec<&str>> {
    let bytes = contents.as_bytes();
    let mut candidates = Vec::new();
    let mut start = 0;
    let mut position = 0;
    let mut depth = 0usize;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position)?;
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position)?;
            continue;
        }
        match bytes[position] {
            b'(' => depth += 1,
            b')' => depth = depth.saturating_sub(1),
            b',' if depth == 0 => {
                candidates.push(&contents[start..position]);
                start = position + 1;
            }
            _ => {}
        }
        position += 1;
    }
    candidates.push(&contents[start..]);
    (!candidates
        .iter()
        .any(|candidate| candidate.trim().is_empty()))
    .then_some(candidates)
}

fn parse_image_set_source(candidate: &str) -> Option<(String, &str)> {
    let bytes = candidate.as_bytes();
    if function_at(bytes, 0, b"url") {
        let (end, source) = parse_url_function(candidate, 0)?;
        return Some((source, &candidate[end..]));
    }
    if matches!(bytes.first(), Some(b'\'' | b'"')) {
        let end = skip_quoted(bytes, 0)?;
        let source = candidate[1..end - 1].to_string();
        if source.as_bytes().contains(&b'\\') {
            return None;
        }
        return Some((source, &candidate[end..]));
    }
    None
}

fn parse_resolution(remainder: &str) -> Option<f64> {
    let mut resolution = None;
    for token in remainder.split_ascii_whitespace() {
        let parsed = if let Some(value) = token.strip_suffix("dppx") {
            value.parse::<f64>().ok()
        } else if let Some(value) = token.strip_suffix("dpi") {
            value.parse::<f64>().ok().map(|value| value / 96.0)
        } else if let Some(value) = token.strip_suffix("dpcm") {
            value.parse::<f64>().ok().map(|value| value * 2.54 / 96.0)
        } else if let Some(value) = token.strip_suffix('x') {
            value.parse::<f64>().ok()
        } else if token.starts_with("type(") {
            continue;
        } else {
            return None;
        };
        let value = parsed?;
        if resolution.replace(value).is_some() {
            return None;
        }
    }
    let value = resolution.unwrap_or(1.0);
    (value.is_finite() && value > 0.0).then_some(value)
}

fn function_at(bytes: &[u8], start: usize, name: &[u8]) -> bool {
    let Some(candidate) = bytes.get(start..start + name.len()) else {
        return false;
    };
    candidate.eq_ignore_ascii_case(name)
        && bytes.get(start + name.len()) == Some(&b'(')
        && (start == 0
            || !matches!(bytes[start - 1], b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'_' | b'-'))
}

fn matching_paren(bytes: &[u8], open: usize) -> Option<usize> {
    if bytes.get(open) != Some(&b'(') {
        return None;
    }
    let mut position = open + 1;
    let mut depth = 1usize;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position)?;
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position)?;
            continue;
        }
        match bytes[position] {
            b'(' => depth += 1,
            b')' => {
                depth -= 1;
                if depth == 0 {
                    return Some(position + 1);
                }
            }
            _ => {}
        }
        position += 1;
    }
    None
}

fn skip_quoted(bytes: &[u8], start: usize) -> Option<usize> {
    let quote = *bytes.get(start)?;
    let mut position = start + 1;
    while position < bytes.len() {
        match bytes[position] {
            b'\\' => position += 2,
            value if value == quote => return Some(position + 1),
            _ => position += 1,
        }
    }
    None
}

fn skip_comment(bytes: &[u8], start: usize) -> Option<usize> {
    let relative = bytes
        .get(start + 2..)?
        .windows(2)
        .position(|pair| pair == b"*/")?;
    Some(start + 2 + relative + 2)
}

fn skip_whitespace(bytes: &[u8], position: &mut usize) {
    while matches!(bytes.get(*position), Some(value) if value.is_ascii_whitespace()) {
        *position += 1;
    }
}

fn starts_with(bytes: &[u8], start: usize, needle: &[u8]) -> bool {
    bytes.get(start..start + needle.len()) == Some(needle)
}

#[cfg(test)]
mod tests {
    use super::{rewrite, CssContext};
    use crate::allow_lists::AllowLists;
    use crate::collect::ImageCollection;
    use crate::context::{Ctx, ImageSourceCount};
    use crate::testkit::png_data_uri;
    use crate::url_collect::UrlCollection;

    #[test]
    fn remote_urls_use_valid_placeholders() {
        let allow = AllowLists::default();
        let ctx = Ctx::new(&allow);
        let css = "color:red;background-image:url('https://example.com/a.png');mask-image:url(https://example.com/b.png);content:url(\"https://example.com/<metadata id='anon-image-slot-7'/>\")";
        let rewritten = rewrite(&ctx, css, CssContext::DeclarationList).expect("images change");
        assert!(rewritten.refs.is_empty());
        assert_eq!(rewritten.css.matches("data:image/svg+xml").count(), 3);
        assert!(!rewritten.css.contains("https://example.com"));
    }

    #[test]
    fn non_image_css_urls_are_left_alone() {
        let allow = AllowLists::default();
        let ctx = Ctx::new(&allow);
        let css = "@import url('https://example.com/a.css');@font-face{src:url('https://example.com/a.woff2')}";
        assert!(rewrite(&ctx, css, CssContext::Stylesheet).is_none());
    }

    #[test]
    fn inline_images_still_use_the_inline_scrubber() {
        let allow = AllowLists::default();
        let ctx = Ctx::new(&allow);
        let original = png_data_uri(8, 8, [10, 20, 30, 255]);
        let css = format!("background-image:url('{original}')");
        let rewritten = rewrite(&ctx, &css, CssContext::DeclarationList).expect("image changes");
        assert!(!rewritten.css.contains(&original));
        assert!(rewritten.css.contains("data:image/"));
    }

    #[test]
    fn collected_inline_images_use_numbered_placeholders() {
        let allow = AllowLists::default();
        let ctx = Ctx::with_image_collection(
            &allow,
            Some(ImageCollection {
                pseudo_team: "0123456789abcdef0123456789abcdef".to_string(),
                content_key: "fedcba9876543210fedcba9876543210".to_string(),
            }),
        );
        let original = png_data_uri(8, 8, [10, 20, 30, 255]);
        let css = format!("background-image:url('{original}')");
        let rewritten = rewrite(&ctx, &css, CssContext::DeclarationList).expect("image changes");
        assert!(rewritten.css.contains("anon-image-slot-0"));
        assert_eq!(rewritten.refs.len(), 1);
        assert!(rewritten.refs["0"].starts_with("image:"));
        assert_eq!(
            ctx.take_image_source_counts(),
            vec![ImageSourceCount {
                source: "css",
                property: "background-image",
                kind: "inline",
                count: 1,
            }]
        );
    }

    #[test]
    fn collected_remote_images_record_the_css_property() {
        let allow = AllowLists::default();
        let ctx = Ctx::new(&allow).collecting_urls(Some(UrlCollection {
            url_key: "0123456789abcdef0123456789abcdef".to_string(),
        }));
        let css = "mask-image:url('https://cdn.example.com/mask.png')";
        let rewritten = rewrite(&ctx, css, CssContext::DeclarationList).expect("image changes");
        assert!(rewritten.refs["0"].starts_with("imageurl:"));
        assert_eq!(
            ctx.take_image_source_counts(),
            vec![ImageSourceCount {
                source: "css",
                property: "mask-image",
                kind: "url",
                count: 1,
            }]
        );
    }

    #[test]
    fn inline_svg_in_css_stays_out_of_the_collection_lane() {
        let allow = AllowLists::default();
        let ctx = Ctx::with_image_collection(
            &allow,
            Some(ImageCollection {
                pseudo_team: "0123456789abcdef0123456789abcdef".to_string(),
                content_key: "fedcba9876543210fedcba9876543210".to_string(),
            }),
        );
        let original = "data:image/svg+xml;base64,PHN2Zz48dGV4dD5qb2huLmZha2VuYW1lQGV4YW1wbGUuY29tPC90ZXh0Pjwvc3ZnPg==";
        let css = format!("background-image:url('{original}')");
        let rewritten = rewrite(&ctx, &css, CssContext::DeclarationList).expect("image changes");
        assert!(rewritten.refs.is_empty());
        assert!(!rewritten.css.contains(original));
        assert!(rewritten.css.contains("data:image/png;base64"));
        assert!(ctx.take_image_source_counts().is_empty());
    }

    #[test]
    fn image_set_uses_the_largest_candidate() {
        let allow = AllowLists::default();
        let ctx = Ctx::new(&allow);
        let css = "background-image:image-set(url('https://example.com/a.png') 1x, url('https://example.com/b.png') 2x)";
        let rewritten = rewrite(&ctx, css, CssContext::DeclarationList).expect("image changes");
        assert_eq!(rewritten.css.matches("data:image/svg+xml").count(), 1);
        assert!(!rewritten.css.contains("example.com"));
    }

    #[test]
    fn strings_and_comments_do_not_create_image_fetches() {
        let allow = AllowLists::default();
        let ctx = Ctx::new(&allow);
        let css = "content:'url(https://example.com/a.png)';background-image:/* url(https://example.com/b.png) */none";
        assert!(rewrite(&ctx, css, CssContext::DeclarationList).is_none());
    }
}
