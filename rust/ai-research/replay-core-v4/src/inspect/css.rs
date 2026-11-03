//! Image URLs in CSS: the `url()`s of an image property, or of a custom property that reaches one through `var()`.
//! Font URLs are the `url()`s in the `src` descriptor of an `@font-face` rule. `cssparser` tokenizes as CSS Syntax 3 does, so a name, an escape, a comment or a bad URL reads here as the renderer reads it.

use std::borrow::Cow;
use std::sync::atomic::{AtomicUsize, Ordering};

use cssparser::{
    match_ignore_ascii_case, AtRuleParser, CowRcStr, DeclarationParser, Delimiter, ParseError,
    Parser, ParserState, QualifiedRuleParser, RuleBodyItemParser, RuleBodyParser, SourcePosition,
    Token,
};
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
    let mut out: Option<String> = None;
    let mut copied_to = 0;
    each_function(&mut Parser::new(css), &mut |input, start, opened| {
        if !matches!(opened, Opened::UnquotedUrl(_)) {
            skip_block(input);
        }
        let start = start.byte_index();
        let end = input.position().byte_index();
        if let Some(replaced) = replacement(&css[start..end]) {
            let out = out.get_or_insert_with(|| String::with_capacity(css.len()));
            out.push_str(&css[copied_to..start]);
            out.push_str(&replaced);
            copied_to = end;
        }
    });
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
    if can_hold_image(property.trim()) {
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

struct Declaration {
    start: usize,
    end: usize,
    kind: DeclarationKind,
}

#[derive(Clone, Copy)]
enum Block {
    Style,
    FontFace(usize),
}

/// The text can be a style attribute, a style sheet or one rule, so its top level reads as a rule body, which holds declarations and rules alike.
fn declarations(css: &str) -> Vec<Declaration> {
    let mut declarations = Declarations {
        found: Vec::new(),
        font_faces: 0,
        block: Block::Style,
    };
    declarations.read_block(&mut Parser::new(css), Block::Style);
    declarations.found
}

struct Declarations {
    found: Vec<Declaration>,
    font_faces: usize,
    block: Block,
}

impl Declarations {
    fn read_block(&mut self, input: &mut Parser<'_>, block: Block) {
        let outer = std::mem::replace(&mut self.block, block);
        let body: RuleBodyParser<'_, '_, Self, (), ()> = RuleBodyParser::new(input, self);
        for _ in body {}
        self.block = outer;
    }
}

impl<'i> DeclarationParser<'i> for Declarations {
    type Declaration = ();
    type Error = ();

    /// A value that holds a `{}` block is a nested rule, as `a:hover{…}` is, unless the property is a custom one.
    fn parse_value(
        &mut self,
        name: CowRcStr<'i>,
        input: &mut Parser<'i>,
        _: &ParserState,
    ) -> Result<(), ParseError<()>> {
        let start = input.position();
        let custom = name.starts_with("--");
        while let Ok(token) = input.next() {
            if !custom && matches!(token, Token::CurlyBracketBlock) {
                return Err(ParseError::unexpected_token());
            }
        }
        let kind = match self.block {
            Block::FontFace(face) => font_descriptor(&name, face),
            Block::Style => can_hold_image(&name).then_some(DeclarationKind::Image),
        };
        if let Some(kind) = kind {
            self.found.push(Declaration {
                start: start.byte_index(),
                end: input.position().byte_index(),
                kind,
            });
        }
        Ok(())
    }
}

impl<'i> AtRuleParser<'i> for Declarations {
    type Prelude = Block;
    type AtRule = ();
    type Error = ();

    fn parse_prelude(
        &mut self,
        name: CowRcStr<'i>,
        input: &mut Parser<'i>,
    ) -> Result<Block, ParseError<()>> {
        let font_face = name.eq_ignore_ascii_case("font-face") && input.is_exhausted();
        while input.next().is_ok() {}
        if !font_face {
            return Ok(Block::Style);
        }
        self.font_faces += 1;
        Ok(Block::FontFace(self.font_faces - 1))
    }

    fn rule_without_block(&mut self, _: Block, _: &ParserState) -> Result<(), ()> {
        Ok(())
    }

    fn parse_block(
        &mut self,
        block: Block,
        _: &ParserState,
        input: &mut Parser<'i>,
    ) -> Result<(), ParseError<()>> {
        self.read_block(input, block);
        Ok(())
    }
}

impl<'i> QualifiedRuleParser<'i> for Declarations {
    type Prelude = ();
    type QualifiedRule = ();
    type Error = ();

    fn parse_prelude(&mut self, input: &mut Parser<'i>) -> Result<(), ParseError<()>> {
        while input.next().is_ok() {}
        Ok(())
    }

    fn parse_block(
        &mut self,
        _: (),
        _: &ParserState,
        input: &mut Parser<'i>,
    ) -> Result<(), ParseError<()>> {
        self.read_block(input, Block::Style);
        Ok(())
    }
}

impl<'i> RuleBodyItemParser<'i, (), ()> for Declarations {
    fn parse_declarations(&self) -> bool {
        true
    }

    fn parse_qualified(&self) -> bool {
        matches!(self.block, Block::Style)
    }
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

fn is_image_property(property: &str) -> bool {
    match_ignore_ascii_case! { property,
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
        | "-webkit-mask-image" => true,
        _ => false,
    }
}

/// An image source that holds a CSS escape is skipped, as v3 skips it. A font has no v3 to match, and its URL must not stay.
#[derive(Clone, Copy, PartialEq, Eq)]
enum EscapedSources {
    Skipped,
    Decoded,
}

enum Opened<'i> {
    UnquotedUrl(CowRcStr<'i>),
    UrlFunction,
    ImageSet,
}

/// Calls `each` at each `url()` and `image-set()` in `input`, at any depth. A block deeper than `cssparser`'s nesting limit reads as flat tokens, to keep the stack bounded.
fn each_function<'i>(
    input: &mut Parser<'i>,
    each: &mut impl FnMut(&mut Parser<'i>, SourcePosition, Opened<'i>),
) {
    loop {
        let start = input.position();
        let opened = match input.next_including_whitespace_and_comments() {
            Err(_) => return,
            Ok(Token::UnquotedUrl(url)) => Opened::UnquotedUrl(url.clone()),
            Ok(Token::Function(name)) if name.eq_ignore_ascii_case("url") => Opened::UrlFunction,
            Ok(Token::Function(name)) if is_image_set(name) => Opened::ImageSet,
            Ok(
                Token::Function(_)
                | Token::ParenthesisBlock
                | Token::SquareBracketBlock
                | Token::CurlyBracketBlock,
            ) => {
                let _ = input.parse_nested_block(|input| {
                    each_function(input, each);
                    Ok::<_, ParseError<()>>(())
                });
                continue;
            }
            Ok(_) => continue,
        };
        each(input, start, opened);
    }
}

fn is_image_set(name: &str) -> bool {
    name.eq_ignore_ascii_case("image-set") || name.eq_ignore_ascii_case("-webkit-image-set")
}

fn skip_block(input: &mut Parser<'_>) {
    let _ = input.parse_nested_block(|_| Ok::<_, ParseError<()>>(()));
}

fn value_urls(
    value: &str,
    resolver: &mut Resolver<'_>,
    escaped: EscapedSources,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    each_function(&mut Parser::new(value), &mut |input, start, opened| {
        let source = match opened {
            Opened::ImageSet => return image_set_urls(input, start, resolver, found),
            Opened::UnquotedUrl(url) => Some(unquoted_url_source(url, input.slice_from(start))),
            Opened::UrlFunction => quoted_url_source(input),
        };
        let Some(source) = source else { return };
        let function = input.slice_from(start);
        match collectable(&source) {
            Some(url) => url_function_urls(function, url, resolver, found),
            None if source.escaped && escaped == EscapedSources::Decoded => {
                escaped_url_function_urls(function, &source.url, resolver, found)
            }
            None => {}
        }
    });
}

struct UrlSource<'i> {
    url: CowRcStr<'i>,
    escaped: bool,
}

/// The name before the `(` can be escaped, as in `\75 rl(`, and still read as `url`, so only the text after it counts.
fn unquoted_url_source<'i>(url: CowRcStr<'i>, token: &str) -> UrlSource<'i> {
    let contents = token
        .split_once('(')
        .map_or(token, |(_, contents)| contents);
    UrlSource {
        escaped: contents.contains('\\'),
        url,
    }
}

fn quoted_url_source<'i>(input: &mut Parser<'i>) -> Option<UrlSource<'i>> {
    input
        .parse_nested_block(|input| {
            input.skip_whitespace();
            let start = input.position();
            let url = input.expect_string_cloned()?;
            Ok::<_, ParseError<()>>(UrlSource {
                escaped: input.slice_from(start).contains('\\'),
                url,
            })
        })
        .ok()
}

/// v3 collects neither a fragment nor a source with an escape in it.
fn collectable<'s>(source: &'s UrlSource<'_>) -> Option<&'s str> {
    let url = source.url.trim();
    (!source.escaped && !url.is_empty() && !url.starts_with('#')).then_some(url)
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
    decoded: &str,
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let decoded = decoded.trim();
    if is_root_relative(decoded) {
        return url_function_urls(function, decoded, resolver, found);
    }
    let decoded = if is_protocol_relative(decoded) {
        Cow::Owned(format!("https:{decoded}"))
    } else {
        Cow::Borrowed(decoded)
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
    input: &mut Parser<'_>,
    start: SourcePosition,
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let opening = input.slice_from(start);
    let name = &opening[..opening.len() - 1];
    let candidates = input
        .parse_nested_block(|input| {
            Ok::<_, ParseError<()>>(image_set_candidates(input, &mut *found))
        })
        .ok()
        .flatten();
    let function = input.slice_from(start);
    let Some(candidates) = candidates else {
        return;
    };
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
            replacement: format!("{name}({candidate})"),
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

/// `None` when a candidate is empty, or when the set lists more than [`MAX_IMAGE_SET_CANDIDATES`]. Then each remote candidate is reported as unshown, as the set is read, so that a long set is never held.
fn image_set_candidates<'i>(
    input: &mut Parser<'i>,
    found: &mut impl FnMut(CssUrl<'_>),
) -> Option<Vec<ImageSetCandidate<'i>>> {
    let mut candidates = Vec::new();
    let mut count = 0;
    let mut readable = true;
    loop {
        let candidate = input
            .parse_until_before(Delimiter::Comma, |input| {
                Ok::<_, ParseError<()>>(image_set_candidate(input))
            })
            .ok()
            .flatten();
        count += 1;
        if count <= MAX_IMAGE_SET_CANDIDATES {
            match candidate {
                Some(candidate) => candidates.push(candidate),
                None => readable = false,
            }
        } else if readable {
            let held = std::mem::take(&mut candidates);
            for source in held.into_iter().chain(candidate).filter_map(|c| c.source) {
                if is_remote(&source) {
                    found(CssUrl::Unshown(&source));
                }
            }
        }
        if input.next().is_err() {
            break;
        }
    }
    (readable && count <= MAX_IMAGE_SET_CANDIDATES).then_some(candidates)
}

enum CandidateStart<'i> {
    Url(CowRcStr<'i>),
    String(CowRcStr<'i>),
    UrlFunction,
    Other,
}

fn image_set_candidate<'i>(input: &mut Parser<'i>) -> Option<ImageSetCandidate<'i>> {
    input.skip_whitespace();
    let start = input.position();
    let first = match input.next() {
        Err(_) => return None,
        Ok(Token::UnquotedUrl(url)) => CandidateStart::Url(url.clone()),
        Ok(Token::QuotedString(url)) => CandidateStart::String(url.clone()),
        Ok(Token::Function(name)) if name.eq_ignore_ascii_case("url") => {
            CandidateStart::UrlFunction
        }
        Ok(_) => CandidateStart::Other,
    };
    let source = match first {
        CandidateStart::Url(url) => Some(unquoted_url_source(url, input.slice_from(start))),
        CandidateStart::String(url) => Some(UrlSource {
            escaped: input.slice_from(start).contains('\\'),
            url,
        }),
        CandidateStart::UrlFunction => quoted_url_source(input),
        CandidateStart::Other => None,
    };
    let source_end = input.position();
    let resolution_dppx = parse_descriptors(input);
    Some(ImageSetCandidate {
        text: input.slice_from(start).trim_end(),
        source: source.as_ref().and_then(collectable).map(str::to_owned),
        descriptors: input.slice(source_end..input.position()),
        resolution_dppx,
    })
}

enum Descriptor {
    Resolution(f64),
    Type,
}

fn parse_descriptors(input: &mut Parser<'_>) -> Option<f64> {
    let mut resolution = None;
    let mut readable = true;
    loop {
        let descriptor = match input.next() {
            Err(_) => break,
            Ok(Token::Dimension { value, unit, .. }) => {
                resolution_dppx(f64::from(*value), unit).map(Descriptor::Resolution)
            }
            Ok(Token::Function(name)) if name.eq_ignore_ascii_case("type") => {
                Some(Descriptor::Type)
            }
            Ok(_) => None,
        };
        readable &= match descriptor {
            Some(Descriptor::Resolution(dppx)) => resolution.replace(dppx).is_none(),
            Some(Descriptor::Type) => input
                .parse_nested_block(|input| {
                    Ok::<_, ParseError<()>>(is_fetched_image_type(input.expect_string()?.trim()))
                })
                .unwrap_or(false),
            None => false,
        };
    }
    let value = resolution.unwrap_or(1.0);
    (readable && value.is_finite() && value > 0.0).then_some(value)
}

fn resolution_dppx(value: f64, unit: &str) -> Option<f64> {
    match_ignore_ascii_case! { unit,
        "x" | "dppx" => Some(value),
        "dpi" => Some(value / 96.0),
        "dpcm" => Some(value * 2.54 / 96.0),
        _ => None,
    }
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
            "@font-face{font-family:Commented;/* lead */src/**/:url(\"https://cdn.example.com/commented.woff2\"/* tail */)}",
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
                "font https://cdn.example.com/commented.woff2 Some(\"Commented\")",
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
                ".a{/* lead */background/**/:url(\"https://cdn.example.com/c.png\"/* tail */)}",
                vec!["image https://cdn.example.com/c.png"],
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
            (
                ".a{background:url(https://cdn.example.com/unclosed.png",
                vec!["image https://cdn.example.com/unclosed.png"],
            ),
            (
                ".a{background:url(https://cdn.example.com/a(1).png)}",
                vec![],
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
