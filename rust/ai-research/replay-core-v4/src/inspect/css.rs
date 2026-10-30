//! Image URLs in CSS: the `url()`s in the value of a property that shows an image, or of a custom property, which a page
//! passes to such a property through `var()`. An offline render loads only the images the block refers to, so an
//! `image-set()` is rewritten to hold the one candidate the fetcher takes, and a relative URL to its absolute form.

use url::Url;

use crate::url_policy::{is_fetched_image_type, is_remote};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CssUrl<'a> {
    Image(&'a str),
    /// The writer replaces this `image-set()` candidate too, so that it does not stay when no [`CssRewrite`] removes it.
    Unshown(&'a str),
    Rewrite(CssRewrite),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CssRewrite {
    pub text: String,
    pub replacement: String,
    pub dropped: Vec<String>,
}

/// Calls `found` with each image URL in `css`, a `style` attribute, `<style>` text or `_cssText`, and with each rewrite
/// that the block needs. A relative URL resolves against `page_url`.
pub fn image_urls(css: &str, page_url: Option<&str>, found: &mut impl FnMut(CssUrl<'_>)) {
    for (start, end) in image_value_ranges(css) {
        value_urls(&css[start..end], page_url, found);
    }
}

pub fn declaration_image_urls(
    property: &str,
    value: &str,
    page_url: Option<&str>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    if can_hold_image(property.trim()) {
        value_urls(value, page_url, found);
    }
}

fn can_hold_image(property: &str) -> bool {
    property.starts_with("--") || is_image_property(property)
}

/// The value ranges of the declarations in `css` that can hold an image.
fn image_value_ranges(css: &str) -> Vec<(usize, usize)> {
    let bytes = css.as_bytes();
    let mut ranges: Vec<(usize, usize)> = Vec::new();
    // Where the text of the current declaration starts, after the whitespace that leads it.
    let mut segment_start: Option<usize> = None;
    let mut brace_depth = 0usize;
    let mut paren_depth = 0usize;
    let mut bracket_depth = 0usize;
    let mut position = 0;
    while position < bytes.len() {
        if segment_start.is_none() && !bytes[position].is_ascii_whitespace() {
            segment_start = Some(position);
        }
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
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
                segment_start = None;
            }
            b'}' if paren_depth == 0 && bracket_depth == 0 => {
                brace_depth = brace_depth.saturating_sub(1);
                segment_start = None;
            }
            b';' if paren_depth == 0 && bracket_depth == 0 => segment_start = None,
            // A colon in a custom property value, as in `--link: https://…`, is not a new declaration.
            b':' if paren_depth == 0
                && bracket_depth == 0
                && ranges.last().is_none_or(|previous| position >= previous.1) =>
            {
                // Each colon trims only the whitespace before it, so a long selector list stays linear.
                let property = css[segment_start.unwrap_or(position)..position].trim_end();
                if can_hold_image(property) {
                    ranges.push((
                        position + 1,
                        declaration_end(bytes, position + 1, brace_depth),
                    ));
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
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
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

/// The longest name [`is_image_property`] accepts, so that a longer text is not lowercased.
const MAX_IMAGE_PROPERTY_LEN: usize = "-webkit-mask-box-image-source".len();

fn is_image_property(property: &str) -> bool {
    property.len() <= MAX_IMAGE_PROPERTY_LEN
        && matches!(
            property.to_ascii_lowercase().as_str(),
            "background"
                | "background-image"
                | "border-image"
                | "border-image-source"
                | "content"
                | "cursor"
                | "list-style"
                | "list-style-image"
                | "mask"
                | "mask-border"
                | "mask-border-source"
                | "mask-image"
                | "shape-outside"
                | "symbols"
                | "-webkit-border-image"
                | "-webkit-border-image-source"
                | "-webkit-box-reflect"
                | "-webkit-mask"
                | "-webkit-mask-box-image"
                | "-webkit-mask-box-image-source"
                | "-webkit-mask-image"
        )
}

fn value_urls(value: &str, page_url: Option<&str>, found: &mut impl FnMut(CssUrl<'_>)) {
    let bytes = value.as_bytes();
    let mut position = 0;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        let image_set = if function_at(bytes, position, b"image-set") {
            Some(b"image-set".len())
        } else if function_at(bytes, position, b"-webkit-image-set") {
            Some(b"-webkit-image-set".len())
        } else {
            None
        };
        if let Some(name_len) = image_set {
            let Some(end) = matching_paren(bytes, position + name_len) else {
                return;
            };
            image_set_urls(&value[position..end], name_len, page_url, found);
            position = end;
            continue;
        }
        if function_at(bytes, position, b"url") {
            let (resume_at, source) = scan_url_function(value, position);
            if let Some(source) = source.as_deref().and_then(collectable) {
                url_function_urls(&value[position..resume_at], source, page_url, found);
            }
            position = resume_at;
            continue;
        }
        position += 1;
    }
}

/// v3 collects neither a fragment nor a source with an escape in it.
fn collectable(source: &str) -> Option<&str> {
    let source = source.trim();
    (!source.starts_with('#') && !source.contains('\\')).then_some(source)
}

fn url_function_urls(
    function: &str,
    source: &str,
    page_url: Option<&str>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    match resolve(source, page_url) {
        Some(absolute) => {
            found(CssUrl::Image(&absolute));
            found(CssUrl::Rewrite(CssRewrite {
                text: function.to_owned(),
                replacement: url_function(&absolute),
                dropped: Vec::new(),
            }));
        }
        None => found(CssUrl::Image(source)),
    }
}

/// The absolute URL of a relative `source` on `page_url`, with `https` as its scheme because the fetcher loads nothing
/// else. `None` when `source` is not relative or there is no page to resolve it against.
fn resolve(source: &str, page_url: Option<&str>) -> Option<String> {
    // A protocol-relative URL names its host, so the URL policy takes it as it is.
    if is_remote(source)
        || Url::parse(source).err() != Some(url::ParseError::RelativeUrlWithoutBase)
    {
        return None;
    }
    let mut base = Url::parse(page_url?).ok()?;
    if base.scheme() != "https" {
        base.set_scheme("https").ok()?;
    }
    base.join(source).ok().map(String::from)
}

/// A serialized URL percent-encodes `"`, so the quotes hold any URL that [`resolve`] returns.
fn url_function(url: &str) -> String {
    format!("url(\"{url}\")")
}

/// The renderer shows only the `image-set()` candidate that fits its pixel ratio, and fails offline on any candidate
/// the fetcher did not take. So the set is rewritten to hold one candidate: the highest resolution of a type the
/// fetcher stores. The other remote candidates are named but not fetched, so that one set costs its host one fetch.
fn image_set_urls(
    function: &str,
    name_len: usize,
    page_url: Option<&str>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let Some(candidates) = image_set_candidates(&function[name_len + 1..function.len() - 1]) else {
        return;
    };
    let kept = candidates
        .iter()
        .enumerate()
        .filter_map(|(index, candidate)| {
            Some((index, candidate.source.as_deref()?, candidate.resolution?))
        })
        .fold(None, |best: Option<(usize, &str, f64)>, candidate| {
            if best.is_none_or(|best| candidate.2 > best.2) {
                Some(candidate)
            } else {
                best
            }
        });
    let mut dropped = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        let source = candidate.source.as_deref().unwrap_or_default();
        if kept.is_none_or(|kept| kept.0 != index) && is_remote(source) {
            found(CssUrl::Unshown(source));
            dropped.push(source.to_owned());
        }
    }
    let Some((index, source, _)) = kept else {
        return;
    };
    let kept = &candidates[index];
    let resolved = resolve(source, page_url);
    found(CssUrl::Image(resolved.as_deref().unwrap_or(source)));
    // A candidate kept as the page wrote it holds its URL as the writer's URL pass looks for it.
    let candidate = match &resolved {
        Some(absolute) => format!("{} {}", url_function(absolute), kept.descriptors.trim())
            .trim_end()
            .to_owned(),
        None => kept.text.to_owned(),
    };
    if candidates.len() > 1 || resolved.is_some() {
        found(CssUrl::Rewrite(CssRewrite {
            text: function.to_owned(),
            replacement: format!("{}({candidate})", &function[..name_len]),
            dropped,
        }));
    }
}

struct ImageSetCandidate<'a> {
    text: &'a str,
    /// The image's URL when it is a `url()` or a string that [`collectable`] keeps.
    source: Option<String>,
    descriptors: &'a str,
    /// In dppx. `None` when the descriptors do not parse, or name a type the fetcher does not store.
    resolution: Option<f64>,
}

fn image_set_candidates(contents: &str) -> Option<Vec<ImageSetCandidate<'_>>> {
    let bytes = contents.as_bytes();
    let mut candidates = Vec::new();
    let mut start = 0;
    let mut position = 0;
    let mut depth = 0usize;
    while position <= bytes.len() {
        if position == bytes.len() || (bytes[position] == b',' && depth == 0) {
            candidates.push(image_set_candidate(&contents[start..position])?);
            start = position + 1;
            position += 1;
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
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
            _ => {}
        }
        position += 1;
    }
    Some(candidates)
}

fn image_set_candidate(candidate: &str) -> Option<ImageSetCandidate<'_>> {
    let candidate = candidate.trim();
    if candidate.is_empty() {
        return None;
    }
    let bytes = candidate.as_bytes();
    let (source, descriptors) = if function_at(bytes, 0, b"url") {
        let (resume_at, source) = scan_url_function(candidate, 0);
        (source, &candidate[resume_at..])
    } else if matches!(bytes[0], b'\'' | b'"') {
        let end = skip_quoted(bytes, 0)?;
        (Some(candidate[1..end - 1].to_owned()), &candidate[end..])
    } else {
        // Another image, such as a gradient, which nothing fetches.
        (None, "")
    };
    Some(ImageSetCandidate {
        text: candidate,
        source: source.as_deref().and_then(collectable).map(str::to_owned),
        descriptors,
        resolution: parse_descriptors(descriptors),
    })
}

fn parse_descriptors(descriptors: &str) -> Option<f64> {
    let bytes = descriptors.as_bytes();
    let mut resolution = None;
    let mut position = 0;
    loop {
        skip_whitespace(bytes, &mut position);
        if position == bytes.len() {
            break;
        }
        if function_at(bytes, position, b"type") {
            let end = matching_paren(bytes, position + 4)?;
            let media_type = descriptors[position + 5..end - 1]
                .trim()
                .trim_matches(['"', '\'']);
            if !is_fetched_image_type(media_type) {
                return None;
            }
            position = end;
            continue;
        }
        let token_end = bytes[position..]
            .iter()
            .position(u8::is_ascii_whitespace)
            .map_or(bytes.len(), |length| position + length);
        if resolution
            .replace(parse_resolution(&descriptors[position..token_end])?)
            .is_some()
        {
            return None;
        }
        position = token_end;
    }
    let value = resolution.unwrap_or(1.0);
    (value.is_finite() && value > 0.0).then_some(value)
}

fn parse_resolution(token: &str) -> Option<f64> {
    if let Some(value) = token.strip_suffix("dppx") {
        value.parse::<f64>().ok()
    } else if let Some(value) = token.strip_suffix("dpi") {
        value.parse::<f64>().ok().map(|value| value / 96.0)
    } else if let Some(value) = token.strip_suffix("dpcm") {
        value.parse::<f64>().ok().map(|value| value * 2.54 / 96.0)
    } else {
        token.strip_suffix('x')?.parse::<f64>().ok()
    }
}

fn scan_url_function(value: &str, start: usize) -> (usize, Option<String>) {
    let bytes = value.as_bytes();
    let Some(resume_at) = matching_paren(bytes, start + 3) else {
        return (bytes.len(), None);
    };
    let contents_end = resume_at - 1;
    let mut position = start + 4;
    skip_whitespace(bytes, &mut position);
    let source = if matches!(bytes.get(position), Some(b'\'' | b'"')) {
        let content_start = position + 1;
        let Some(end) = skip_quoted(bytes, position) else {
            return (resume_at, None);
        };
        position = end;
        skip_whitespace(bytes, &mut position);
        if position != contents_end {
            return (resume_at, None);
        }
        &value[content_start..end - 1]
    } else {
        &value[position..contents_end]
    };
    let source = source.trim();
    (
        resume_at,
        (!source.is_empty() && !source.contains('\\')).then(|| source.to_owned()),
    )
}

fn function_at(bytes: &[u8], start: usize, name: &[u8]) -> bool {
    bytes
        .get(start..start + name.len())
        .is_some_and(|candidate| candidate.eq_ignore_ascii_case(name))
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
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
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

/// The position after the escape at `start` and the character it escapes, so that an escaped quote, bracket or
/// parenthesis does not count as one.
fn skip_escape(bytes: &[u8], start: usize) -> usize {
    let width = match bytes.get(start + 1) {
        Some(0xf0..) => 4,
        Some(0xe0..) => 3,
        Some(0xc0..) => 2,
        _ => 1,
    };
    (start + 1 + width).min(bytes.len())
}

fn skip_comment(bytes: &[u8], start: usize) -> Option<usize> {
    let relative = bytes
        .get(start + 2..)?
        .windows(2)
        .position(|pair| pair == b"*/")?;
    Some(start + 2 + relative + 2)
}

fn skip_whitespace(bytes: &[u8], position: &mut usize) {
    while bytes.get(*position).is_some_and(u8::is_ascii_whitespace) {
        *position += 1;
    }
}

fn starts_with(bytes: &[u8], start: usize, needle: &[u8]) -> bool {
    bytes.get(start..start + needle.len()) == Some(needle)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn found(css: &str, page_url: Option<&str>) -> Vec<String> {
        let mut found = Vec::new();
        image_urls(css, page_url, &mut |url| {
            found.push(match url {
                CssUrl::Image(url) => format!("image {url}"),
                CssUrl::Unshown(url) => format!("unshown {url}"),
                CssUrl::Rewrite(rewrite) => format!(
                    "rewrite {} => {} dropping {:?}",
                    rewrite.text, rewrite.replacement, rewrite.dropped
                ),
            })
        });
        found
    }

    #[test]
    fn reads_past_escapes_outside_strings() {
        // Tailwind escapes brackets, parentheses and quotes in its arbitrary value class names.
        let css = r".bg-\[url\(\'\/hero\.png\'\)\]{background-image:url('/hero.png')}.a{background:url(https://cdn.example.com/a.png)}";
        assert_eq!(
            found(css, None),
            ["image /hero.png", "image https://cdn.example.com/a.png"]
        );
    }

    #[test]
    fn scans_a_long_selector_list_in_linear_time() {
        let css = format!(
            "{} a:hover {{ background: url(https://cdn.example.com/a.png) }}",
            "a:hover, b:focus-visible,\n".repeat(50_000)
        );
        assert_eq!(found(&css, None), ["image https://cdn.example.com/a.png"]);
    }

    #[test]
    fn rewrites_what_an_offline_render_cannot_load() {
        let page = Some("http://app.example.com/shop/item?id=1");
        for (css, expected) in [
            (
                ":root{--hero:url(https://cdn.example.com/hero.png)}",
                vec!["image https://cdn.example.com/hero.png"],
            ),
            (
                ".a{background:url(../img/a.png)}",
                vec![
                    "image https://app.example.com/img/a.png",
                    r#"rewrite url(../img/a.png) => url("https://app.example.com/img/a.png") dropping []"#,
                ],
            ),
            (
                r#".a{background-image:image-set("https://cdn.example.com/1x.png" 1x, url(https://cdn.example.com/2x.png) 2x)}"#,
                vec![
                    "unshown https://cdn.example.com/1x.png",
                    "image https://cdn.example.com/2x.png",
                    r#"rewrite image-set("https://cdn.example.com/1x.png" 1x, url(https://cdn.example.com/2x.png) 2x) => image-set(url(https://cdn.example.com/2x.png) 2x) dropping ["https://cdn.example.com/1x.png"]"#,
                ],
            ),
            (
                r#".a{background:-webkit-image-set(url(/a.avif) type("image/avif") 2x, url(/a.jpg) type("image/jpeg") 1x, linear-gradient(red, blue) 3x)}"#,
                vec![
                    "image https://app.example.com/a.jpg",
                    r#"rewrite -webkit-image-set(url(/a.avif) type("image/avif") 2x, url(/a.jpg) type("image/jpeg") 1x, linear-gradient(red, blue) 3x) => -webkit-image-set(url("https://app.example.com/a.jpg") type("image/jpeg") 1x) dropping []"#,
                ],
            ),
            (
                ".a{background:image-set(url(https://cdn.example.com/a.png))}",
                vec!["image https://cdn.example.com/a.png"],
            ),
        ] {
            assert_eq!(found(css, page), expected, "{css}");
        }
        assert_eq!(found(".a{background:url(a.png)}", None), ["image a.png"]);
    }
}
