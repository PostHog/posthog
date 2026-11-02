//! Image URLs in CSS: the `url()`s of an image property, or of a custom property that reaches one through `var()`.
//! Font URLs are the `url()`s in the `src` descriptor of an `@font-face` rule.

use std::borrow::Cow;
use std::sync::atomic::{AtomicUsize, Ordering};

use url::Url;

use super::dom::{RemoteKind, RemoteUrl};
use crate::fonts::bundled_font;
use crate::url_policy::{
    is_fetched_image_type, is_protocol_relative, is_remote, try_canonicalize, MAX_URL_LEN,
};

/// Each resolution copies the page's origin, so one event resolves at most this many relative URLs.
pub const MAX_RESOLVED_URLS: usize = 1024;
/// Far more than a real `image-set()` lists. A longer set gets no rewrite, so the inspector never holds its candidates.
const MAX_IMAGE_SET_CANDIDATES: usize = 32;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CssUrl<'a> {
    Image(&'a str),
    Unshown(&'a str),
    /// A URL that the block holds only as other text, root-relative or written with CSS escapes, which its rewrite replaces.
    Resolved(&'a str),
    /// A root-relative `url()` that did not resolve. Its text keeps no rewrite, which another window would apply here.
    Unresolved(&'a str),
    Rewrite(CssRewrite),
    /// A `src` URL of an `@font-face` rule, with the raw value of that rule's `font-family` descriptor.
    Font {
        url: &'a str,
        family: Option<&'a str>,
    },
    /// A [`CssUrl::Resolved`] font URL of a family that the renderer does not ship.
    ResolvedFont(&'a str),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CssRewrite {
    pub text: String,
    pub replacement: String,
    pub dropped: Vec<String>,
    /// The URL that `replacement` holds in place of a relative one, for the writer to replace with the reference of its kind.
    pub resolved: Option<RemoteUrl>,
}

/// The origin that a root-relative URL on `page_url` resolves against, as `https` because the fetcher loads nothing else.
pub fn page_base(page_url: &str) -> Option<Url> {
    if page_url.len() > MAX_URL_LEN {
        return None;
    }
    let mut base = Url::parse(page_url).ok()?;
    if base.scheme() != "https" {
        base.set_scheme("https").ok()?;
    }
    base.set_path("/");
    base.set_query(None);
    base.set_fragment(None);
    Some(base)
}

#[derive(Default)]
pub struct Resolver<'p> {
    base: Option<&'p Url>,
    remaining: usize,
    budget: Option<&'p AtomicUsize>,
}

impl<'p> Resolver<'p> {
    pub fn new(base: Option<&'p Url>, budget: Option<&'p AtomicUsize>) -> Self {
        Self {
            base,
            remaining: MAX_RESOLVED_URLS,
            budget,
        }
    }

    /// Only a root-relative URL, as `/a.png`, resolves. It needs the page's origin and nothing else, so no part of a page
    /// path, which can hold a token, reaches a fetch, and a `<base>` or a style sheet's own URL cannot change it.
    fn resolves(&self, source: &str) -> bool {
        self.base.is_some() && self.remaining > 0 && is_root_relative(source)
    }

    fn resolve(&mut self, source: &str) -> Option<String> {
        if !self.resolves(source) {
            return None;
        }
        let absolute = String::from(self.base?.join(source).ok()?);
        let within_budget = self.budget.is_none_or(|budget| {
            budget
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |left| {
                    left.checked_sub(absolute.len())
                })
                .is_ok()
        });
        if !within_budget {
            self.remaining = 0;
            return None;
        }
        self.remaining -= 1;
        Some(absolute)
    }
}

/// `css` with each `url()` and `image-set()` that `replacement` names replaced, found as the inspector finds them, so
/// that a quoted string, a comment or an escaped selector never matches. `None` when nothing changed.
pub fn rewrite_functions(
    css: &str,
    replacement: &mut impl FnMut(&str) -> Option<String>,
) -> Option<String> {
    let bytes = css.as_bytes();
    let mut out: Option<String> = None;
    let mut copied_to = 0;
    let mut position = 0;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        let end = match function_at(bytes, position) {
            Some(CssFunction::ImageSet(name_len)) => {
                // The inspector stops at an unterminated set, and each later opener would scan to the end again.
                let Some(end) = matching_paren(bytes, position + name_len) else {
                    break;
                };
                end
            }
            Some(CssFunction::Url(name_len)) => scan_url_function(css, position, name_len).0,
            None => {
                position = skip_token(bytes, position);
                continue;
            }
        };
        if let Some(replaced) = replacement(&css[position..end]) {
            let out = out.get_or_insert_with(|| String::with_capacity(css.len()));
            out.push_str(&css[copied_to..position]);
            out.push_str(&replaced);
            copied_to = end;
        }
        position = end;
    }
    let mut out = out?;
    out.push_str(&css[copied_to..]);
    Some(out)
}

pub fn rewrite_font_src_functions(
    css: &str,
    replacement: &mut impl FnMut(&str) -> Option<String>,
) -> Option<String> {
    let mut out: Option<String> = None;
    let mut copied_to = 0;
    for declaration in declarations(css) {
        if !matches!(declaration.kind, DeclarationKind::FontSrc(_)) {
            continue;
        }
        let value = &css[declaration.start..declaration.end];
        if let Some(rewritten) = rewrite_functions(value, replacement) {
            let out = out.get_or_insert_with(|| String::with_capacity(css.len()));
            out.push_str(&css[copied_to..declaration.start]);
            out.push_str(&rewritten);
            copied_to = declaration.end;
        }
    }
    let mut out = out?;
    out.push_str(&css[copied_to..]);
    Some(out)
}

/// Calls `found` with each URL and rewrite in `css`: a `style` attribute, `<style>` text or `_cssText`.
pub fn urls(css: &str, resolver: &mut Resolver<'_>, found: &mut impl FnMut(CssUrl<'_>)) {
    let declarations = declarations(css);
    let mut families: Vec<Option<&str>> = Vec::new();
    for declaration in &declarations {
        if let DeclarationKind::FontFamily(face) = declaration.kind {
            if families.len() <= face {
                families.resize(face + 1, None);
            }
            families[face] = Some(&css[declaration.start..declaration.end]);
        }
    }
    for declaration in &declarations {
        let value = &css[declaration.start..declaration.end];
        match declaration.kind {
            DeclarationKind::Image => value_urls(value, resolver, EscapedSources::Skipped, found),
            DeclarationKind::FontSrc(face) => {
                let family = families.get(face).copied().flatten();
                let resolved_kind = match family.and_then(bundled_font) {
                    Some(slug) => RemoteKind::BundledFont(slug),
                    None => RemoteKind::Font,
                };
                value_urls(
                    value,
                    resolver,
                    EscapedSources::Decoded,
                    &mut |url| match url {
                        CssUrl::Image(url) => found(CssUrl::Font { url, family }),
                        CssUrl::Resolved(url) if resolved_kind == RemoteKind::Font => {
                            found(CssUrl::ResolvedFont(url))
                        }
                        CssUrl::Rewrite(mut rewrite) => {
                            if let Some(resolved) = &mut rewrite.resolved {
                                resolved.kind = resolved_kind;
                            }
                            found(CssUrl::Rewrite(rewrite));
                        }
                        CssUrl::Unresolved(text) => found(CssUrl::Unresolved(text)),
                        CssUrl::Resolved(_)
                        | CssUrl::Unshown(_)
                        | CssUrl::Font { .. }
                        | CssUrl::ResolvedFont(_) => {}
                    },
                );
            }
            DeclarationKind::FontFamily(_) => {}
        }
    }
}

pub fn declaration_image_urls(
    property: &str,
    value: &str,
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    if can_hold_image(&declaration_name(property.trim())) {
        value_urls(value, resolver, EscapedSources::Skipped, found);
    }
}

/// `text` as CSSOM writes it inside an identifier, as a selector holds the URL of a class like `bg-[url(https://…)]`.
pub fn escape_in_identifier(text: &str) -> String {
    let mut escaped = String::with_capacity(text.len() * 2);
    for character in text.chars() {
        match character {
            '\0' => escaped.push('\u{fffd}'),
            '\u{1}'..='\u{1f}' | '\u{7f}' => {
                escaped.push_str(&format!("\\{:x} ", u32::from(character)));
            }
            'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' => escaped.push(character),
            _ if !character.is_ascii() => escaped.push(character),
            _ => {
                escaped.push('\\');
                escaped.push(character);
            }
        }
    }
    escaped
}

fn can_hold_image(property: &str) -> bool {
    property.starts_with("--") || is_image_property(property)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DeclarationKind {
    Image,
    FontSrc(usize),
    FontFamily(usize),
}

#[derive(Clone, Copy)]
struct OpenFontFace {
    inner_brace_depth: usize,
    index: usize,
}

struct Declaration {
    start: usize,
    end: usize,
    kind: DeclarationKind,
}

fn declarations(css: &str) -> Vec<Declaration> {
    let bytes = css.as_bytes();
    let mut ranges: Vec<Declaration> = Vec::new();
    // Where the text of the current declaration starts, after the whitespace that leads it.
    let mut segment_start: Option<usize> = None;
    let mut brace_depth = 0usize;
    let mut paren_depth = 0usize;
    let mut bracket_depth = 0usize;
    let mut open_font_face: Option<OpenFontFace> = None;
    let mut font_faces = 0usize;
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
                if open_font_face.is_none()
                    && is_font_face_prelude(&css[segment_start.unwrap_or(position)..position])
                {
                    open_font_face = Some(OpenFontFace {
                        inner_brace_depth: brace_depth,
                        index: font_faces,
                    });
                    font_faces += 1;
                }
                segment_start = None;
            }
            b'}' if paren_depth == 0 && bracket_depth == 0 => {
                if open_font_face.is_some_and(|face| face.inner_brace_depth == brace_depth) {
                    open_font_face = None;
                }
                brace_depth = brace_depth.saturating_sub(1);
                segment_start = None;
            }
            b';' if paren_depth == 0 && bracket_depth == 0 => segment_start = None,
            // A colon in a custom property value, as in `--link: https://…`, is not a new declaration.
            b':' if paren_depth == 0
                && bracket_depth == 0
                && ranges
                    .last()
                    .is_none_or(|previous| position >= previous.end) =>
            {
                // Each colon trims only the whitespace before it, so a long selector list stays linear.
                let property =
                    declaration_name(css[segment_start.unwrap_or(position)..position].trim_end());
                let kind = match open_font_face {
                    Some(face) if face.inner_brace_depth == brace_depth => {
                        font_descriptor(&property, face.index)
                    }
                    _ => can_hold_image(&property).then_some(DeclarationKind::Image),
                };
                if let Some(kind) = kind {
                    ranges.push(Declaration {
                        start: position + 1,
                        end: declaration_end(bytes, position + 1, brace_depth),
                        kind,
                    });
                }
            }
            _ => {}
        }
        position += 1;
    }
    ranges
}

fn font_descriptor(descriptor: &str, face: usize) -> Option<DeclarationKind> {
    if descriptor.eq_ignore_ascii_case("src") {
        Some(DeclarationKind::FontSrc(face))
    } else if descriptor.eq_ignore_ascii_case("font-family") {
        Some(DeclarationKind::FontFamily(face))
    } else {
        None
    }
}

/// Only the at-keyword, with whitespace and comments around it, opens a font face. A browser reads it through CSS escapes,
/// as in `@\66 ont-face`, but a selector such as `.\@font-face` holds an escaped `@`, and the image URLs of its rule must
/// still be named.
fn is_font_face_prelude(prelude: &str) -> bool {
    let bytes = prelude.as_bytes();
    let start = skip_space_and_comments(bytes, 0);
    bytes.get(start) == Some(&b'@')
        && name_end(bytes, start + 1, b"font-face")
            .is_some_and(|end| skip_space_and_comments(bytes, end) == bytes.len())
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

/// An image source that holds a CSS escape is skipped, as v3 skips it. A font has no v3 to match, and its URL must not stay.
#[derive(Clone, Copy, PartialEq, Eq)]
enum EscapedSources {
    Skipped,
    Decoded,
}

fn value_urls(
    value: &str,
    resolver: &mut Resolver<'_>,
    escaped: EscapedSources,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let bytes = value.as_bytes();
    let mut position = 0;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        match function_at(bytes, position) {
            Some(CssFunction::ImageSet(name_len)) => {
                let Some(end) = matching_paren(bytes, position + name_len) else {
                    return;
                };
                image_set_urls(&value[position..end], name_len, resolver, found);
                position = end;
            }
            Some(CssFunction::Url(name_len)) => {
                let (resume_at, source) = scan_url_function(value, position, name_len);
                let function = &value[position..resume_at];
                if let Some(source) = source.as_deref() {
                    match collectable(source) {
                        Some(source) => url_function_urls(function, source, resolver, found),
                        None if escaped == EscapedSources::Decoded => {
                            escaped_url_function_urls(function, name_len, source, resolver, found)
                        }
                        None => {}
                    }
                }
                position = resume_at;
            }
            None => position = skip_token(bytes, position),
        }
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
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    match resolver.resolve(source) {
        Some(absolute) => {
            found(CssUrl::Resolved(&absolute));
            found(CssUrl::Rewrite(CssRewrite {
                text: function.to_owned(),
                replacement: url_function(&absolute),
                dropped: Vec::new(),
                resolved: Some(RemoteUrl {
                    url: absolute,
                    kind: RemoteKind::Image,
                }),
            }));
        }
        None if is_root_relative(source) => found(CssUrl::Unresolved(function)),
        None => found(CssUrl::Image(source)),
    }
}

/// The block does not hold the URL a browser reads from an escaped source, so the rewrite replaces the whole `url()`.
fn escaped_url_function_urls(
    function: &str,
    name_len: usize,
    source: &str,
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let source = source.trim();
    if !source.contains('\\') {
        return;
    }
    let quoted = function[name_len + 1..]
        .trim_start_matches(|c: char| c.is_ascii_whitespace())
        .starts_with(['"', '\'']);
    let Some(decoded) = unescape_css(source, quoted) else {
        return;
    };
    if is_root_relative(&decoded) {
        return url_function_urls(function, &decoded, resolver, found);
    }
    let decoded = if is_protocol_relative(&decoded) {
        format!("https:{decoded}")
    } else {
        decoded
    };
    // A serialized URL percent-encodes `"` and holds no backslash, so the quotes of the rewrite hold it.
    let Some(absolute) = Url::parse(&decoded)
        .ok()
        .filter(|url| matches!(url.scheme(), "http" | "https"))
        .map(String::from)
    else {
        return;
    };
    found(CssUrl::Resolved(&absolute));
    found(CssUrl::Rewrite(CssRewrite {
        text: function.to_owned(),
        replacement: url_function(&absolute),
        dropped: Vec::new(),
        resolved: Some(RemoteUrl {
            url: absolute,
            kind: RemoteKind::Image,
        }),
    }));
}

/// A quoted URL drops an escaped newline, as a line continuation. An unquoted URL with one is a bad URL, which no browser
/// loads, so it is `None`.
fn unescape_css(text: &str, quoted: bool) -> Option<String> {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(at) = rest.find('\\') {
        out.push_str(&rest[..at]);
        let escape = &rest[at + 1..];
        let digits = escape
            .bytes()
            .take(6)
            .take_while(u8::is_ascii_hexdigit)
            .count();
        if digits == 0 {
            if let Some(after) = escape
                .strip_prefix("\r\n")
                .or_else(|| escape.strip_prefix(['\n', '\r', '\x0c']))
            {
                if !quoted {
                    return None;
                }
                rest = after;
                continue;
            }
            let escaped = escape.chars().next().unwrap_or('\u{FFFD}');
            out.push(escaped);
            rest = &escape[escaped.len_utf8().min(escape.len())..];
        } else {
            let value = u32::from_str_radix(&escape[..digits], 16).ok()?;
            out.push(
                char::from_u32(value)
                    .filter(|&ch| ch != '\0')
                    .unwrap_or('\u{FFFD}'),
            );
            let after = &escape[digits..];
            rest = after
                .strip_prefix("\r\n")
                .or_else(|| after.strip_prefix([' ', '\t', '\n', '\r', '\x0c']))
                .unwrap_or(after);
        }
    }
    out.push_str(rest);
    Some(out)
}

fn is_root_relative(source: &str) -> bool {
    source.starts_with('/') && !is_protocol_relative(source)
}

/// A serialized URL percent-encodes `"`, so the quotes hold any URL that [`Resolver`] returns.
fn url_function(url: &str) -> String {
    format!("url(\"{url}\")")
}

/// A renderer picks the candidate for its pixel ratio and fails offline on any the fetcher did not take, so the set keeps
/// one: the highest resolution of a stored type. Fetching one candidate per set limits the load on the image's host.
fn image_set_urls(
    function: &str,
    name_len: usize,
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let contents = &function[name_len + 1..function.len() - 1];
    let mut candidates = Vec::new();
    let mut count = 0;
    let mut readable = true;
    let split = split_image_set(contents, &mut |text| {
        count += 1;
        if count <= MAX_IMAGE_SET_CANDIDATES {
            match image_set_candidate(text) {
                Some(candidate) => candidates.push(candidate),
                None => readable = false,
            }
        }
    });
    if split.is_none() || !readable {
        return;
    }
    if count > MAX_IMAGE_SET_CANDIDATES {
        split_image_set(contents, &mut |text| {
            if let Some(source) = image_set_candidate(text).and_then(|candidate| candidate.source) {
                if is_remote(&source) {
                    found(CssUrl::Unshown(&source));
                }
            }
        });
        return;
    }
    let loads = |source: &str| {
        is_data_url(source)
            || (is_remote(source) && try_canonicalize(source).is_ok())
            || resolver.resolves(source)
    };
    let kept = candidates
        .iter()
        .enumerate()
        .filter_map(|(index, candidate)| {
            let source = candidate.source.as_deref().filter(|source| loads(source))?;
            Some((index, source, candidate.resolution_dppx?))
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
    let resolved = resolver.resolve(source);
    match &resolved {
        Some(absolute) => found(CssUrl::Resolved(absolute)),
        None => found(CssUrl::Image(source)),
    }
    // A candidate kept as the page wrote it holds its URL as the writer's URL pass looks for it.
    let candidate = match &resolved {
        Some(absolute) => format!("{} {}", url_function(absolute), kept.descriptors.trim())
            .trim_end()
            .to_owned(),
        None => kept.text.to_owned(),
    };
    // The writer moves an inline image out of the block before it rewrites CSS, so a set that holds one never matches.
    let holds_data_url = candidates
        .iter()
        .any(|candidate| candidate.source.as_deref().is_some_and(is_data_url));
    if !holds_data_url && (candidates.len() > 1 || resolved.is_some()) {
        found(CssUrl::Rewrite(CssRewrite {
            text: function.to_owned(),
            replacement: format!("{}({candidate})", &function[..name_len]),
            dropped,
            resolved: resolved.map(|url| RemoteUrl {
                url,
                kind: RemoteKind::Image,
            }),
        }));
    }
}

fn is_data_url(source: &str) -> bool {
    source
        .get(..5)
        .is_some_and(|scheme| scheme.eq_ignore_ascii_case("data:"))
}

struct ImageSetCandidate<'a> {
    text: &'a str,
    source: Option<String>,
    descriptors: &'a str,
    resolution_dppx: Option<f64>,
}

fn split_image_set<'a>(contents: &'a str, each: &mut impl FnMut(&'a str)) -> Option<()> {
    let bytes = contents.as_bytes();
    let mut start = 0;
    let mut position = 0;
    let mut depth = 0usize;
    while position <= bytes.len() {
        if position == bytes.len() || (bytes[position] == b',' && depth == 0) {
            each(&contents[start..position]);
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
    Some(())
}

fn image_set_candidate(candidate: &str) -> Option<ImageSetCandidate<'_>> {
    let candidate = candidate.trim();
    if candidate.is_empty() {
        return None;
    }
    let bytes = candidate.as_bytes();
    let (source, descriptors) = if let Some(name_len) = function_name_len(bytes, 0, b"url") {
        let (resume_at, source) = scan_url_function(candidate, 0, name_len);
        (source, &candidate[resume_at..])
    } else if matches!(bytes[0], b'\'' | b'"') {
        let end = skip_quoted(bytes, 0)?;
        (Some(candidate[1..end - 1].to_owned()), &candidate[end..])
    } else {
        (None, "")
    };
    Some(ImageSetCandidate {
        text: candidate,
        source: source.as_deref().and_then(collectable).map(str::to_owned),
        descriptors,
        resolution_dppx: parse_descriptors(descriptors),
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
        if let Some(name_len) = function_name_len(bytes, position, b"type") {
            let end = matching_paren(bytes, position + name_len)?;
            let media_type = descriptors[position + name_len + 1..end - 1]
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

fn scan_url_function(value: &str, start: usize, name_len: usize) -> (usize, Option<String>) {
    let bytes = value.as_bytes();
    let Some(resume_at) = matching_paren(bytes, start + name_len) else {
        return (bytes.len(), None);
    };
    let contents_end = resume_at - 1;
    let mut position = start + name_len + 1;
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
    (resume_at, (!source.is_empty()).then(|| source.to_owned()))
}

enum CssFunction {
    /// The length of its name, which CSS escapes can make longer than `image-set`.
    ImageSet(usize),
    Url(usize),
}

fn function_at(bytes: &[u8], start: usize) -> Option<CssFunction> {
    function_name_len(bytes, start, b"image-set")
        .or_else(|| function_name_len(bytes, start, b"-webkit-image-set"))
        .map(CssFunction::ImageSet)
        .or_else(|| function_name_len(bytes, start, b"url").map(CssFunction::Url))
}

/// So that `\75 rl(` is a `url(`, as a browser reads it.
fn function_name_len(bytes: &[u8], start: usize, name: &[u8]) -> Option<usize> {
    if start > 0
        && matches!(bytes[start - 1], b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'_' | b'-')
    {
        return None;
    }
    let end = name_end(bytes, start, name)?;
    (bytes.get(end) == Some(&b'(')).then_some(end - start)
}

/// Where the text at `start` ends if it spells `name`, a lowercase ASCII name, in any letter case and through CSS
/// escapes.
fn name_end(bytes: &[u8], start: usize, name: &[u8]) -> Option<usize> {
    let mut position = start;
    for &expected in name {
        let (byte, next) = match *bytes.get(position)? {
            b'\\' => escaped_ascii(bytes, position)?,
            byte => (byte, position + 1),
        };
        if !byte.eq_ignore_ascii_case(&expected) {
            return None;
        }
        position = next;
    }
    Some(position)
}

/// The character that the CSS escape at `start` names, and where the escape ends, as CSS Syntax 4.3.7 reads it. `None`
/// for an escaped newline, which ends a name, and for a non-ASCII character, which no name here holds.
fn escaped_ascii(bytes: &[u8], start: usize) -> Option<(u8, usize)> {
    let digits_start = start + 1;
    let digits = bytes
        .get(digits_start..)?
        .iter()
        .take(6)
        .take_while(|byte| byte.is_ascii_hexdigit())
        .count();
    if digits == 0 {
        let byte = *bytes.get(digits_start)?;
        return (byte.is_ascii() && !matches!(byte, b'\n' | b'\r' | b'\x0c'))
            .then_some((byte, digits_start + 1));
    }
    let digits_end = digits_start + digits;
    let value = u32::from_str_radix(
        std::str::from_utf8(&bytes[digits_start..digits_end]).ok()?,
        16,
    )
    .ok()?;
    let end = match bytes.get(digits_end..) {
        Some([b'\r', b'\n', ..]) => digits_end + 2,
        Some([b' ' | b'\t' | b'\n' | b'\r' | b'\x0c', ..]) => digits_end + 1,
        _ => digits_end,
    };
    let byte = u8::try_from(value)
        .ok()
        .filter(|byte| byte.is_ascii() && *byte != 0)?;
    Some((byte, end))
}

/// A longer declaration name stays as written, so that a long selector before a colon costs no decoding.
const MAX_ESCAPED_NAME_LEN: usize = 256;

fn declaration_name(property: &str) -> Cow<'_, str> {
    if property.len() > MAX_ESCAPED_NAME_LEN || !property.contains('\\') {
        return Cow::Borrowed(property);
    }
    let bytes = property.as_bytes();
    let mut name = Vec::with_capacity(bytes.len());
    let mut position = 0;
    while position < bytes.len() {
        let (byte, next) = match bytes[position] {
            b'\\' => match escaped_ascii(bytes, position) {
                Some(decoded) => decoded,
                None => return Cow::Borrowed(property),
            },
            byte => (byte, position + 1),
        };
        name.push(byte);
        position = next;
    }
    String::from_utf8(name).map_or(Cow::Borrowed(property), Cow::Owned)
}

/// Past an escape or a quoted string as one token, so that neither can start a function.
fn skip_token(bytes: &[u8], position: usize) -> usize {
    match bytes[position] {
        b'\\' => skip_escape(bytes, position),
        b'\'' | b'"' => skip_quoted(bytes, position).unwrap_or(bytes.len()),
        _ => position + 1,
    }
}

fn skip_space_and_comments(bytes: &[u8], mut position: usize) -> usize {
    loop {
        skip_whitespace(bytes, &mut position);
        if !starts_with(bytes, position, b"/*") {
            return position;
        }
        position = skip_comment(bytes, position).unwrap_or(bytes.len());
    }
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
        let base = page_url.and_then(page_base);
        let mut found = Vec::new();
        urls(css, &mut Resolver::new(base.as_ref(), None), &mut |url| {
            found.push(match url {
                CssUrl::Image(url) => format!("image {url}"),
                CssUrl::Unshown(url) => format!("unshown {url}"),
                CssUrl::Resolved(url) => format!("resolved {url}"),
                CssUrl::Unresolved(text) => format!("unresolved {text}"),
                CssUrl::Rewrite(rewrite) => format!(
                    "rewrite {} => {} dropping {:?}",
                    rewrite.text, rewrite.replacement, rewrite.dropped
                ),
                CssUrl::Font { url, family } => format!("font {url} {family:?}"),
                CssUrl::ResolvedFont(url) => format!("resolved font {url}"),
            })
        });
        found
    }

    #[test]
    fn reports_each_font_face_src_url_with_its_rules_family() {
        let css = concat!(
            "/* fonts */@FONT-FACE{font-family:'Brand Sans';src:url(https://cdn.example.com/brand.woff2) format('woff2'),local(Arial),url(\"https://cdn.example.com/brand.woff\")}",
            "@media print{@font-face{src:url(https://cdn.example.com/print.woff2);font-family:Print}}",
            "@font-face{src:url(https://cdn.example.com/nameless.woff2)}",
            "@font-face{font-family:Self;src:url(/fonts/self.woff2)}",
            ".a{font-family:Inter;src:url(https://cdn.example.com/not-a-face.woff2);background:url(https://cdn.example.com/a.png)}",
            ".\\@font-face{src:url(https://cdn.example.com/escaped.woff2);background:url(https://cdn.example.com/escaped.png)}",
            "@font-face/* trailing */{font-family:Trail;src:url(https://cdn.example.com/trail.woff2)}",
            "@\\66 ont-face{font-family:Keyword;src:url(https://cdn.example.com/keyword.woff2)}",
            "@font-face{font-family:Descriptor;\\73 rc:url(https://cdn.example.com/descriptor.woff2)}",
            "@font-face{font-family:Function;src:\\75 rl(https://cdn.example.com/function.woff2)}",
            "@font-face{font-family:Source;src:url(https://cdn.example.com/source\\2e woff2)}",
            "@font-face{font-family:Relative;src:url(//cdn.example.com/relative\\2e woff2)}",
            "@font-face{font-family:Continued;src:url(\"https://cdn.example.com/continued.\\\nwoff2\")}",
            "@font-face{font-family:Broken;src:url(https://cdn.example.com/broken.\\\nwoff2)}",
        );
        assert_eq!(
            found(css, Some("https://app.example.com/")),
            [
                "font https://cdn.example.com/brand.woff2 Some(\"'Brand Sans'\")",
                "font https://cdn.example.com/brand.woff Some(\"'Brand Sans'\")",
                "font https://cdn.example.com/print.woff2 Some(\"Print\")",
                "font https://cdn.example.com/nameless.woff2 None",
                "resolved font https://app.example.com/fonts/self.woff2",
                "rewrite url(/fonts/self.woff2) => url(\"https://app.example.com/fonts/self.woff2\") dropping []",
                "image https://cdn.example.com/a.png",
                "image https://cdn.example.com/escaped.png",
                "font https://cdn.example.com/trail.woff2 Some(\"Trail\")",
                "font https://cdn.example.com/keyword.woff2 Some(\"Keyword\")",
                "font https://cdn.example.com/descriptor.woff2 Some(\"Descriptor\")",
                "font https://cdn.example.com/function.woff2 Some(\"Function\")",
                "resolved font https://cdn.example.com/source.woff2",
                "rewrite url(https://cdn.example.com/source\\2e woff2) => url(\"https://cdn.example.com/source.woff2\") dropping []",
                "resolved font https://cdn.example.com/relative.woff2",
                "rewrite url(//cdn.example.com/relative\\2e woff2) => url(\"https://cdn.example.com/relative.woff2\") dropping []",
                "resolved font https://cdn.example.com/continued.woff2",
                "rewrite url(\"https://cdn.example.com/continued.\\\nwoff2\") => url(\"https://cdn.example.com/continued.woff2\") dropping []",
            ]
        );
    }

    #[test]
    fn reads_past_escapes_outside_strings() {
        // Tailwind escapes brackets, parentheses and quotes in its arbitrary value class names.
        let css = r".bg-\[url\(\'\/hero\.png\'\)\]{background-image:url('/hero.png')}.a{background:url(https://cdn.example.com/a.png)}.p{background-\69mage:url(https://cdn.example.com/p.png)}.f{background:\75 rl(https://cdn.example.com/f.png)}";
        assert_eq!(
            found(css, None),
            [
                "unresolved url('/hero.png')",
                "image https://cdn.example.com/a.png",
                "image https://cdn.example.com/p.png",
                "image https://cdn.example.com/f.png",
            ]
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
                ".a{background:url(/img/a.png)}",
                vec![
                    "resolved https://app.example.com/img/a.png",
                    r#"rewrite url(/img/a.png) => url("https://app.example.com/img/a.png") dropping []"#,
                ],
            ),
            (
                ".a{background:url(../img/a.png)}",
                vec!["image ../img/a.png"],
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
                    "resolved https://app.example.com/a.jpg",
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
        let base = page_base("https://app.example.com/shop/item");
        let budget = AtomicUsize::new("https://app.example.com/img/a.png".len());
        let mut named = Vec::new();
        urls(
            ".a{background:url(/img/a.png)} .b{background:url(/img/b.png)}",
            &mut Resolver::new(base.as_ref(), Some(&budget)),
            &mut |url| {
                if let CssUrl::Resolved(url) | CssUrl::Unresolved(url) = url {
                    named.push(url.to_owned());
                }
            },
        );
        assert_eq!(
            named,
            ["https://app.example.com/img/a.png", "url(/img/b.png)"]
        );
        let rewritten = rewrite_functions("url(/a.png) image-set( url(/a.png)", &mut |function| {
            (function == "url(/a.png)").then(|| "url(x)".to_owned())
        });
        assert_eq!(rewritten.as_deref(), Some("url(x) image-set( url(/a.png)"));
        let many: Vec<String> = (1..=MAX_IMAGE_SET_CANDIDATES + 1)
            .map(|i| format!("url(https://cdn.example.com/{i}.png) {i}x"))
            .collect();
        let named = found(
            &format!(".a{{background:image-set({})}}", many.join(", ")),
            page,
        );
        assert_eq!(named.len(), many.len());
        assert!(
            named.iter().all(|url| url.starts_with("unshown ")),
            "{named:?}"
        );
    }
}
