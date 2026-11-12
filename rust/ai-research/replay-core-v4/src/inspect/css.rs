//! Image URLs in CSS: the `url()`s of an image property, or of a custom property that reaches one through `var()`.
//! Font URLs are the `url()`s in the `src` descriptor of an `@font-face` rule. `cssparser` tokenizes as CSS Syntax 3 does, so a name, an escape, a comment or a bad URL reads here as the renderer reads it.

use std::borrow::Cow;
use std::ops::Range;
use std::sync::atomic::{AtomicUsize, Ordering};

use cssparser::{
    match_ignore_ascii_case, AtRuleParser, CowRcStr, DeclarationParser, Delimiter, ParseError,
    Parser, ParserState, QualifiedRuleParser, RuleBodyItemParser, RuleBodyParser, SourcePosition,
    Token,
};
use url::Url;

use super::dom::{RemoteKind, RemoteUrl};
use crate::fonts::bundled_font;
use crate::refs::{unnamed_url, UrlAsset};
use crate::url_policy::{
    as_parsed, is_fetched_image_type, is_protocol_relative, is_remote, needs_redaction,
    parsed_start, try_canonicalize, MAX_URL_LEN,
};

/// Each resolution copies the page's origin, so one event resolves at most this many relative URLs.
pub const MAX_RESOLVED_URLS: usize = 1024;
/// Far more than a real `image-set()` lists. A longer set gets no rewrite, so the inspector never holds its candidates.
const MAX_IMAGE_SET_CANDIDATES: usize = 32;
/// The depth at which `cssparser` enters no more blocks, to keep the stack bounded. Its default, set here so that the scan knows where it stops.
const NESTED_BLOCK_LIMIT: u8 = 75;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CssUrl<'a> {
    Image(&'a str),
    Unshown(&'a str),
    /// A URL that the block holds only as other text, root-relative or written with CSS escapes, which its rewrite replaces.
    Resolved(&'a str),
    /// A root-relative `url()` that did not resolve. Its text keeps no rewrite, which another window would apply here.
    Unresolved(&'a str),
    /// `function` is a slice of the scanned text, so that the writer replaces the function where the scan read it.
    Rewrite {
        rewrite: CssRewrite,
        function: &'a str,
    },
    /// A `src` URL of an `@font-face` rule, with the raw value of that rule's `font-family` descriptor.
    Font {
        url: &'a str,
        family: Option<&'a str>,
    },
    /// A [`CssUrl::Resolved`] font URL of a family that the renderer does not ship.
    ResolvedFont(&'a str),
    /// A URL with a credential in a CSS property that shows no image, or in an `@import`, which no fetch takes.
    Link(&'a str),
    /// Rules or functions nest to [`NESTED_BLOCK_LIMIT`], where `cssparser` enters no block, so a URL there goes unnamed.
    NestedTooDeep,
    /// A URL that the scan names but cannot find in the text it read, so the writer could not replace it there.
    Unplaced,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CssRewrite {
    pub text: String,
    pub replacement: String,
    pub dropped: Vec<String>,
    /// The URL that `replacement` holds in place of a relative one, for the writer to replace with the reference of its kind.
    pub resolved: Option<RemoteUrl>,
    /// Where `replacement` holds its one URL, so that the edit finds the URL without a search.
    pub url_at: Option<Range<usize>>,
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
    edit_budget: Option<&'p AtomicUsize>,
}

impl<'p> Resolver<'p> {
    pub fn new(base: Option<&'p Url>, budget: Option<&'p AtomicUsize>) -> Self {
        Self {
            base,
            remaining: MAX_RESOLVED_URLS,
            budget,
            edit_budget: None,
        }
    }

    pub fn with_edit_budget(self, edit_budget: Option<&'p AtomicUsize>) -> Self {
        Self {
            edit_budget,
            ..self
        }
    }

    pub fn edit_budget(&self) -> Option<&'p AtomicUsize> {
        self.edit_budget
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

/// Calls `found` with each URL and rewrite in `css`: a `style` attribute, `<style>` text or `_cssText`.
pub fn urls(css: &str, resolver: &mut Resolver<'_>, found: &mut impl FnMut(CssUrl<'_>)) {
    let Declarations {
        found: declarations,
        nested_too_deep,
        ..
    } = declarations(css);
    if nested_too_deep {
        found(CssUrl::NestedTooDeep);
    }
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
            DeclarationKind::Image => value_urls(value, resolver, found),
            DeclarationKind::FontSrc(face) => {
                let family = families.get(face).copied().flatten();
                let resolved_kind = match family.and_then(bundled_font) {
                    Some(slug) => RemoteKind::BundledFont(slug),
                    None => RemoteKind::Font,
                };
                value_urls(value, resolver, &mut |url| match url {
                    CssUrl::Image(url) => found(CssUrl::Font { url, family }),
                    CssUrl::Resolved(url) if resolved_kind == RemoteKind::Font => {
                        found(CssUrl::ResolvedFont(url))
                    }
                    CssUrl::Rewrite {
                        mut rewrite,
                        function,
                    } => {
                        if let Some(resolved) = &mut rewrite.resolved {
                            resolved.kind = resolved_kind;
                        }
                        found(CssUrl::Rewrite { rewrite, function });
                    }
                    CssUrl::Unresolved(text) => found(CssUrl::Unresolved(text)),
                    CssUrl::NestedTooDeep => found(CssUrl::NestedTooDeep),
                    CssUrl::Unplaced => found(CssUrl::Unplaced),
                    CssUrl::Resolved(_)
                    | CssUrl::Unshown(_)
                    | CssUrl::Font { .. }
                    | CssUrl::ResolvedFont(_)
                    | CssUrl::Link(_) => {}
                });
            }
            DeclarationKind::FontFamily(_) => {}
            DeclarationKind::Link if may_hold_url(value) => link_urls(value, found),
            DeclarationKind::Link => {}
            DeclarationKind::Import => {
                import_string(value, found);
                link_urls(value, found);
            }
        }
    }
}

/// A URL needs the `(` of a `url()` or an `image-set()`, and that name or an escape, so a value with neither holds no URL.
fn may_hold_url(value: &str) -> bool {
    let holds = |name: &[u8]| {
        value
            .as_bytes()
            .windows(name.len())
            .any(|at| at.eq_ignore_ascii_case(name))
    };
    value.contains('(') && (value.contains('\\') || holds(b"url") || holds(b"image-set"))
}

/// The URLs of a text that shows no image, which no fetch takes. Only a URL with a credential changes, so the rest of
/// the text stays as the page wrote it, with every candidate of an `image-set()`.
fn link_urls(value: &str, found: &mut impl FnMut(CssUrl<'_>)) {
    let mut input = Parser::new(value);
    input.set_nested_block_limit(NESTED_BLOCK_LIMIT);
    if !link_tokens(&mut input, 0, false, found) {
        found(CssUrl::NestedTooDeep);
    }
}

/// Reads each `url()` at any depth, and each string that an `image-set()` holds as a candidate. Returns false when it
/// skipped a block too deep to read whole.
fn link_tokens<'i>(
    input: &mut Parser<'i>,
    depth: u8,
    in_image_set: bool,
    found: &mut impl FnMut(CssUrl<'_>),
) -> bool {
    let mut whole = true;
    loop {
        let start = input.position();
        let token = match input.next_including_whitespace_and_comments() {
            Err(_) => return whole,
            Ok(token) => token.clone(),
        };
        let opens_block = matches!(
            token,
            Token::Function(_)
                | Token::ParenthesisBlock
                | Token::SquareBracketBlock
                | Token::CurlyBracketBlock
        );
        if opens_block && depth + 1 >= NESTED_BLOCK_LIMIT {
            whole = false;
            continue;
        }
        let source = match token {
            Token::UnquotedUrl(url) => unquoted_url_source(url, input.slice_from(start)),
            Token::Function(name) if name.eq_ignore_ascii_case("url") => {
                match quoted_url_source(input) {
                    Some(source) => source,
                    None => continue,
                }
            }
            Token::QuotedString(url) if in_image_set => string_source(url, input.slice_from(start)),
            _ if opens_block => {
                let image_set = matches!(&token, Token::Function(name) if is_image_set(name));
                let _ = input.parse_nested_block(|input| {
                    whole &= link_tokens(input, depth + 1, image_set, found);
                    Ok::<_, ParseError<()>>(())
                });
                continue;
            }
            _ => continue,
        };
        link_url(&source, input.slice_from(start), found);
    }
}

/// `token` is the `url()` or string that holds `source`. A browser loads the URL that its escapes decode to, which the
/// block does not hold as the page wrote it, so then the whole token changes.
fn link_url<'t>(source: &UrlSource<'t>, token: &'t str, found: &mut impl FnMut(CssUrl<'_>)) {
    let url = source.url.trim();
    let Some(kept) = unnamed_url(url, UrlAsset::Image) else {
        return;
    };
    match located(source.written, url).filter(|_| !source.escaped) {
        Some(url) => found(CssUrl::Link(url)),
        None => found(redacted(token, &kept)),
    }
}

/// `@import "…"` names its sheet with a string, not a `url()`.
fn import_string(prelude: &str, found: &mut impl FnMut(CssUrl<'_>)) {
    let mut input = Parser::new(prelude);
    input.skip_whitespace();
    let start = input.position();
    if let Ok(Token::QuotedString(url)) = input.next() {
        let url = url.clone();
        let token = input.slice_from(start);
        link_url(&string_source(url, token), token, found);
    }
}

fn string_source<'i>(url: CowRcStr<'i>, token: &'i str) -> UrlSource<'i> {
    UrlSource {
        escaped: token.contains('\\'),
        written: between_quotes(token),
        url,
    }
}

/// The URLs with a credential in a text that may not be CSS, such as the text of a node the window does not know.
pub fn text_link_urls(text: &str, found: &mut impl FnMut(CssUrl<'_>)) {
    if may_hold_url(text) {
        link_urls(text, found);
    }
    // An `@import` names its sheet with a string, which holds no `(`, and its keyword can hold an escape.
    let may_import = text.contains('\\')
        || text
            .as_bytes()
            .windows(7)
            .any(|at| at.eq_ignore_ascii_case(b"@import"));
    if may_import {
        for declaration in &declarations(text).found {
            if declaration.kind == DeclarationKind::Import {
                import_string(&text[declaration.start..declaration.end], found);
            }
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
        value_urls(value, resolver, found);
    } else if may_hold_url(value) {
        link_urls(value, found);
    }
}

fn can_hold_image(property: &str) -> bool {
    property.starts_with("--") || is_image_property(property)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DeclarationKind {
    Image,
    FontSrc(usize),
    FontFamily(usize),
    Link,
    Import,
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
fn declarations(css: &str) -> Declarations {
    let mut declarations = Declarations {
        found: Vec::new(),
        font_faces: 0,
        block: Block::Style,
        depth: 0,
        nested_too_deep: false,
    };
    let mut input = Parser::new(css);
    input.set_nested_block_limit(NESTED_BLOCK_LIMIT);
    declarations.read_block(&mut input, Block::Style);
    declarations
}

struct Declarations {
    found: Vec<Declaration>,
    font_faces: usize,
    block: Block,
    depth: u8,
    nested_too_deep: bool,
}

impl Declarations {
    fn read_block(&mut self, input: &mut Parser<'_>, block: Block) {
        let outer = std::mem::replace(&mut self.block, block);
        self.nested_too_deep |= self.depth >= NESTED_BLOCK_LIMIT;
        let body: RuleBodyParser<'_, '_, Self, (), ()> = RuleBodyParser::new(input, self);
        for _ in body {}
        self.block = outer;
    }

    fn read_nested_block(&mut self, input: &mut Parser<'_>, block: Block) {
        self.depth += 1;
        self.read_block(input, block);
        self.depth -= 1;
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
            Block::Style if can_hold_image(&name) => Some(DeclarationKind::Image),
            Block::Style => Some(DeclarationKind::Link),
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
        let start = input.position().byte_index();
        while input.next().is_ok() {}
        if name.eq_ignore_ascii_case("import") {
            self.found.push(Declaration {
                start,
                end: input.position().byte_index(),
                kind: DeclarationKind::Import,
            });
        }
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
        self.read_nested_block(input, block);
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
        self.read_nested_block(input, Block::Style);
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

enum Opened<'i> {
    UnquotedUrl(CowRcStr<'i>),
    UrlFunction,
    ImageSet,
}

/// Calls `each` at each `url()` and `image-set()` in `input`, at any depth. Returns false when it skipped a block too deep to read whole, as `each` enters one more block for an `image-set()` candidate.
fn each_function<'i>(
    input: &mut Parser<'i>,
    depth: u8,
    each: &mut impl FnMut(&mut Parser<'i>, SourcePosition, Opened<'i>),
) -> bool {
    let mut whole = true;
    loop {
        let start = input.position();
        let token = match input.next_including_whitespace_and_comments() {
            Err(_) => return whole,
            Ok(token) => token,
        };
        let opens_block = matches!(
            token,
            Token::Function(_)
                | Token::ParenthesisBlock
                | Token::SquareBracketBlock
                | Token::CurlyBracketBlock
        );
        if opens_block && depth + 1 >= NESTED_BLOCK_LIMIT {
            whole = false;
            continue;
        }
        let opened = match token {
            Token::UnquotedUrl(url) => Opened::UnquotedUrl(url.clone()),
            Token::Function(name) if name.eq_ignore_ascii_case("url") => Opened::UrlFunction,
            Token::Function(name) if is_image_set(name) => Opened::ImageSet,
            _ if opens_block => {
                let _ = input.parse_nested_block(|input| {
                    whole &= each_function(input, depth + 1, each);
                    Ok::<_, ParseError<()>>(())
                });
                continue;
            }
            _ => continue,
        };
        each(input, start, opened);
    }
}

fn is_image_set(name: &str) -> bool {
    name.eq_ignore_ascii_case("image-set") || name.eq_ignore_ascii_case("-webkit-image-set")
}

fn value_urls(value: &str, resolver: &mut Resolver<'_>, found: &mut impl FnMut(CssUrl<'_>)) {
    let mut input = Parser::new(value);
    input.set_nested_block_limit(NESTED_BLOCK_LIMIT);
    let whole = each_function(&mut input, 0, &mut |input, start, opened| {
        let source = match opened {
            Opened::ImageSet => return image_set_urls(input, start, resolver, found),
            Opened::UnquotedUrl(url) => Some(unquoted_url_source(url, input.slice_from(start))),
            Opened::UrlFunction => quoted_url_source(input),
        };
        let Some(source) = source else { return };
        let function = input.slice_from(start);
        match collectable(&source) {
            Some(url) => match located(source.written, url) {
                Some(url) => url_function_urls(function, url, resolver, found),
                None => found(CssUrl::Unplaced),
            },
            // A browser loads the URL its escapes decode to, so the block must not keep it as the page wrote it.
            None if source.escaped => {
                escaped_url_function_urls(function, &source.url, resolver, found)
            }
            None => {}
        }
    });
    if !whole {
        found(CssUrl::NestedTooDeep);
    }
}

struct UrlSource<'i> {
    url: CowRcStr<'i>,
    /// The URL as the page wrote it, between its quotes or parentheses. A comment in the function can hold a copy of its decoded spelling, so the URL is looked for only here.
    written: &'i str,
    escaped: bool,
}

/// The name before the `(` can be escaped, as in `\75 rl(`, and still read as `url`, so only the text after it counts.
fn unquoted_url_source<'i>(url: CowRcStr<'i>, token: &'i str) -> UrlSource<'i> {
    let contents = token
        .split_once('(')
        .map_or(token, |(_, contents)| contents);
    UrlSource {
        escaped: contents.contains('\\'),
        written: contents.strip_suffix(')').unwrap_or(contents).trim(),
        url,
    }
}

fn quoted_url_source<'i>(input: &mut Parser<'i>) -> Option<UrlSource<'i>> {
    input
        .parse_nested_block(|input| {
            input.skip_whitespace();
            let start = input.position();
            let url = input.expect_string_cloned()?;
            let token = input.slice_from(start);
            Ok::<_, ParseError<()>>(UrlSource {
                escaped: token.contains('\\'),
                written: between_quotes(token),
                url,
            })
        })
        .ok()
}

/// The contents of a string token, whose closing quote is missing when the text ends inside the string.
fn between_quotes(token: &str) -> &str {
    let mut chars = token.chars();
    match chars.next() {
        Some(quote @ ('"' | '\'')) => {
            let rest = chars.as_str();
            rest.strip_suffix(quote).unwrap_or(rest)
        }
        _ => token,
    }
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
            let (replacement, url_at) = url_function(&absolute);
            found(CssUrl::Rewrite {
                rewrite: CssRewrite {
                    text: function.to_owned(),
                    replacement,
                    dropped: Vec::new(),
                    resolved: Some(RemoteUrl {
                        url: absolute,
                        kind: RemoteKind::Image,
                    }),
                    url_at: Some(url_at),
                },
                function,
            });
        }
        None if is_root_relative(source) => match unnamed_url(source, UrlAsset::Image) {
            Some(kept) => found(redacted(function, &kept)),
            None => found(CssUrl::Unresolved(function)),
        },
        None => found(CssUrl::Image(source)),
    }
}

fn redacted<'f>(function: &'f str, kept: &str) -> CssUrl<'f> {
    let replacement = format!("{URL_FUNCTION_OPEN}{}\")", in_css_string(kept));
    CssUrl::Rewrite {
        rewrite: CssRewrite {
            text: function.to_owned(),
            replacement,
            dropped: Vec::new(),
            resolved: None,
            url_at: None,
        },
        function,
    }
}

/// The block does not hold the URL a browser reads from an escaped source, so the rewrite replaces the whole `url()`.
fn escaped_url_function_urls(
    function: &str,
    decoded: &str,
    resolver: &mut Resolver<'_>,
    found: &mut impl FnMut(CssUrl<'_>),
) {
    let written = decoded.trim();
    if is_root_relative(written) {
        return url_function_urls(function, written, resolver, found);
    }
    let decoded = if is_protocol_relative(written) {
        Cow::Owned(format!("https:{}", as_parsed(written).trim()))
    } else {
        Cow::Borrowed(written)
    };
    let Some(absolute) = Url::parse(&decoded)
        .ok()
        .filter(|url| matches!(url.scheme(), "http" | "https"))
        .map(String::from)
    else {
        if is_remote(written) {
            found(CssUrl::Unplaced);
        } else if let Some(kept) = unnamed_url(written, UrlAsset::Image) {
            found(redacted(function, &kept));
        }
        return;
    };
    found(CssUrl::Resolved(&absolute));
    let (replacement, url_at) = url_function(&absolute);
    found(CssUrl::Rewrite {
        rewrite: CssRewrite {
            text: function.to_owned(),
            replacement,
            dropped: Vec::new(),
            resolved: Some(RemoteUrl {
                url: absolute,
                kind: RemoteKind::Image,
            }),
            url_at: Some(url_at),
        },
        function,
    });
}

fn is_root_relative(source: &str) -> bool {
    parsed_start(source, 1) == "/" && !is_protocol_relative(source)
}

const URL_FUNCTION_OPEN: &str = "url(\"";

/// `text` as a quoted CSS string holds it. A serialized URL keeps a `\\` in its query and fragment, which would escape
/// the closing quote.
pub fn in_css_string(text: &str) -> Cow<'_, str> {
    if !text.contains(|ch: char| matches!(ch, '"' | '\\' | '\0'..='\u{1f}' | '\u{7f}')) {
        return Cow::Borrowed(text);
    }
    let mut escaped = String::with_capacity(text.len() + 8);
    for ch in text.chars() {
        match ch {
            '"' | '\\' => {
                escaped.push('\\');
                escaped.push(ch);
            }
            '\0'..='\u{1f}' | '\u{7f}' => escaped.push_str(&format!("\\{:x} ", u32::from(ch))),
            _ => escaped.push(ch),
        }
    }
    Cow::Owned(escaped)
}

/// The writer writes the URL that this `url()` holds with [`in_css_string`].
fn url_function(url: &str) -> (String, Range<usize>) {
    (
        format!("{URL_FUNCTION_OPEN}{url}\")"),
        URL_FUNCTION_OPEN.len()..URL_FUNCTION_OPEN.len() + url.len(),
    )
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
    if candidates.iter().any(|candidate| candidate.unplaced) {
        found(CssUrl::Unplaced);
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
            let source = candidate.source.filter(|source| loads(source))?;
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
        let source = candidate.source.unwrap_or_default();
        if kept.is_some_and(|kept| kept.0 == index) {
            continue;
        }
        if is_remote(source) {
            found(CssUrl::Unshown(source));
            dropped.push(source.to_owned());
        } else if needs_redaction(source) {
            found(CssUrl::Link(source));
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
    let (candidate, url_in_candidate) = match &resolved {
        Some(absolute) => {
            let (function, url_at) = url_function(absolute);
            let candidate = format!("{function} {}", kept.descriptors.trim());
            (candidate.trim_end().to_owned(), Some(url_at))
        }
        None => (kept.text.to_owned(), range_in(kept.text, source)),
    };
    let opening = name.len() + 1;
    // The writer moves an inline image out of the block before it rewrites CSS, so a set that holds one never matches.
    let holds_data_url = candidates
        .iter()
        .any(|candidate| candidate.source.is_some_and(is_data_url));
    if !holds_data_url && (candidates.len() > 1 || resolved.is_some()) {
        found(CssUrl::Rewrite {
            rewrite: CssRewrite {
                text: function.to_owned(),
                replacement: format!("{name}({candidate})"),
                dropped,
                resolved: resolved.map(|url| RemoteUrl {
                    url,
                    kind: RemoteKind::Image,
                }),
                url_at: url_in_candidate.map(|at| at.start + opening..at.end + opening),
            },
            function,
        });
    }
}

fn is_data_url(source: &str) -> bool {
    source
        .get(..5)
        .is_some_and(|scheme| scheme.eq_ignore_ascii_case("data:"))
}

struct ImageSetCandidate<'a> {
    text: &'a str,
    /// A slice of the scanned text, so that the writer finds the URL where the page wrote it.
    source: Option<&'a str>,
    unplaced: bool,
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
            for candidate in held.into_iter().chain(candidate) {
                if candidate.unplaced {
                    found(CssUrl::Unplaced);
                }
                if let Some(source) = candidate.source.filter(|source| is_remote(source)) {
                    found(CssUrl::Unshown(source));
                } else if let Some(source) =
                    candidate.source.filter(|source| needs_redaction(source))
                {
                    found(CssUrl::Link(source));
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
    /// Such as `cross-fade()`, which can hold a `url()` that the set keeps as the page wrote it.
    Other {
        holds_url: bool,
    },
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
        Ok(Token::Function(_)) => CandidateStart::Other {
            holds_url: input
                .parse_nested_block(|input| {
                    let mut holds_url = false;
                    let whole = each_function(input, 1, &mut |_, _, _| holds_url = true);
                    Ok::<_, ParseError<()>>(holds_url || !whole)
                })
                .unwrap_or(true),
        },
        Ok(_) => CandidateStart::Other { holds_url: false },
    };
    let holds_url = matches!(first, CandidateStart::Other { holds_url: true });
    let source = match first {
        CandidateStart::Url(url) => Some(unquoted_url_source(url, input.slice_from(start))),
        CandidateStart::String(url) => Some(string_source(url, input.slice_from(start))),
        CandidateStart::UrlFunction => quoted_url_source(input),
        CandidateStart::Other { .. } => None,
    };
    let source_end = input.position();
    let written = source.as_ref().and_then(collectable);
    // A set keeps a candidate as the page wrote it, so an escaped remote URL, or an escaped relative one with a credential, which the block does not hold as a browser reads it, has no place.
    let escaped_remote = source.as_ref().is_some_and(|source| {
        let url = source.url.trim();
        source.escaped && (is_remote(url) || needs_redaction(url))
    });
    let source = source
        .as_ref()
        .zip(written)
        .and_then(|(source, url)| located(source.written, url));
    let resolution_dppx = parse_descriptors(input);
    Some(ImageSetCandidate {
        text: input.slice_from(start).trim_end(),
        source,
        unplaced: escaped_remote || holds_url || (written.is_some() && source.is_none()),
        descriptors: input.slice(source_end..input.position()),
        resolution_dppx,
    })
}

/// `url` as a slice of `text`. A source with no escape reads as the page wrote it, so it is always there.
fn located<'t>(text: &'t str, url: &str) -> Option<&'t str> {
    text.find(url).map(|at| &text[at..at + url.len()])
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CssPart {
    Text(String),
    Url(RemoteUrl),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CssPiece {
    pub range: Range<usize>,
    pub parts: Vec<CssPart>,
}

/// The parts of one CSS text that the writer replaces, in order, by byte range in the text that [`urls`] read.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CssEdit {
    pub pieces: Vec<CssPiece>,
}

impl CssUrl<'_> {
    /// An estimate of the memory that [`CssEditBuilder::observe`] adds to an edit for this URL.
    pub fn edit_bytes(&self) -> usize {
        let piece = std::mem::size_of::<CssPiece>() + std::mem::size_of::<CssPart>();
        match self {
            // The builder keeps only a remote URL, so a relative one takes nothing.
            CssUrl::Image(url)
            | CssUrl::Unshown(url)
            | CssUrl::Font { url, .. }
            | CssUrl::Link(url) => {
                if is_remote(url.trim()) || needs_redaction(url) {
                    piece + url.len()
                } else {
                    0
                }
            }
            CssUrl::Rewrite { rewrite, .. } => {
                let resolved = rewrite.resolved.as_ref().map_or(0, |url| url.url.len());
                piece + std::mem::size_of::<CssPart>() + rewrite.replacement.len() + resolved
            }
            CssUrl::Resolved(_)
            | CssUrl::ResolvedFont(_)
            | CssUrl::Unresolved(_)
            | CssUrl::NestedTooDeep
            | CssUrl::Unplaced => 0,
        }
    }
}

/// Turns what [`urls`] reports for one text into its [`CssEdit`], so that the writer searches the text for nothing.
pub struct CssEditBuilder<'c> {
    css: &'c str,
    pieces: Vec<CssPiece>,
    /// URLs that the next rewrite holds, such as the kept candidate of an `image-set()`.
    pending: Vec<RemoteUrl>,
    unplaced: bool,
}

impl<'c> CssEditBuilder<'c> {
    pub fn new(css: &'c str) -> Self {
        Self {
            css,
            pieces: Vec::new(),
            pending: Vec::new(),
            unplaced: false,
        }
    }

    pub fn observe(&mut self, found: &CssUrl<'_>) {
        match found {
            CssUrl::Image(url) | CssUrl::Unshown(url) => self.place(url, RemoteKind::Image),
            CssUrl::Font { url, family } => {
                let kind = match family.and_then(bundled_font) {
                    Some(slug) => RemoteKind::BundledFont(slug),
                    None => RemoteKind::Font,
                };
                self.place(url, kind);
            }
            CssUrl::Rewrite { rewrite, function } => self.rewrite(rewrite, function),
            CssUrl::Link(url) => self.place(url, RemoteKind::Link),
            CssUrl::Unplaced => self.unplaced = true,
            CssUrl::Resolved(_)
            | CssUrl::ResolvedFont(_)
            | CssUrl::Unresolved(_)
            | CssUrl::NestedTooDeep => {}
        }
    }

    /// A URL that no fetch takes is placed only when it holds a credential, so that the rest of the text keeps its bytes.
    fn place(&mut self, url: &str, kind: RemoteKind) {
        let url = url.trim();
        let kind = match kind {
            RemoteKind::Link => RemoteKind::Link,
            _ if is_remote(url) => kind,
            _ => RemoteKind::Link,
        };
        if kind == RemoteKind::Link && !needs_redaction(url) {
            return;
        }
        let named = RemoteUrl {
            url: url.to_owned(),
            kind,
        };
        match range_in(self.css, url) {
            Some(range) => self.pieces.push(CssPiece {
                range,
                parts: vec![CssPart::Url(named)],
            }),
            None => self.pending.push(named),
        }
    }

    /// The rewrite replaces the whole function, so the URLs placed inside it go into its replacement, or out with what it drops.
    fn rewrite(&mut self, rewrite: &CssRewrite, function: &str) {
        let Some(range) = range_in(self.css, function) else {
            self.unplaced = true;
            return;
        };
        let mut urls = std::mem::take(&mut self.pending);
        // The scan reports a function's URLs right before its rewrite, so they are the last pieces placed.
        while let Some(piece) = self
            .pieces
            .pop_if(|piece| range.start <= piece.range.start && piece.range.end <= range.end)
        {
            urls.extend(piece.parts.into_iter().filter_map(|part| match part {
                CssPart::Url(url) => Some(url),
                CssPart::Text(_) => None,
            }));
        }
        urls.extend(rewrite.resolved.clone());
        let url = rewrite.url_at.clone().and_then(|at| {
            let written = rewrite.replacement.get(at.clone())?;
            let url = urls.into_iter().rev().find(|url| url.url == written)?;
            Some((at, url))
        });
        self.pieces.push(CssPiece {
            range,
            parts: parts_around_url(&rewrite.replacement, url),
        });
    }

    /// The edit, or `None` when the text keeps every byte. `Err` when a URL has no place in the text.
    pub fn finish(mut self) -> Result<Option<CssEdit>, Unplaced> {
        self.pieces.sort_by_key(|piece| piece.range.start);
        let overlaps = self
            .pieces
            .windows(2)
            .any(|pair| pair[0].range.end > pair[1].range.start);
        if self.unplaced || !self.pending.is_empty() || overlaps {
            return Err(Unplaced);
        }
        Ok((!self.pieces.is_empty()).then_some(CssEdit {
            pieces: self.pieces,
        }))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Unplaced;

fn range_in(text: &str, part: &str) -> Option<Range<usize>> {
    let start = (part.as_ptr() as usize).checked_sub(text.as_ptr() as usize)?;
    (start + part.len() <= text.len()).then_some(start..start + part.len())
}

fn parts_around_url(replacement: &str, url: Option<(Range<usize>, RemoteUrl)>) -> Vec<CssPart> {
    let Some((at, url)) = url else {
        return vec![CssPart::Text(replacement.to_owned())];
    };
    let mut parts = Vec::with_capacity(3);
    if at.start > 0 {
        parts.push(CssPart::Text(replacement[..at.start].to_owned()));
    }
    parts.push(CssPart::Url(url));
    if at.end < replacement.len() {
        parts.push(CssPart::Text(replacement[at.end..].to_owned()));
    }
    parts
}

pub fn write_css_edit(
    text: &str,
    edit: &CssEdit,
    reference: &mut impl FnMut(&RemoteUrl) -> String,
) -> String {
    let mut out = String::with_capacity(text.len());
    let mut copied_to = 0;
    for piece in &edit.pieces {
        out.push_str(&text[copied_to..piece.range.start]);
        for part in &piece.parts {
            match part {
                CssPart::Text(literal) => out.push_str(literal),
                CssPart::Url(url) => out.push_str(&reference(url)),
            }
        }
        copied_to = piece.range.end;
    }
    out.push_str(&text[copied_to..]);
    out
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
                CssUrl::Rewrite { rewrite, .. } => format!(
                    "rewrite {} => {} dropping {:?}",
                    rewrite.text, rewrite.replacement, rewrite.dropped
                ),
                CssUrl::Font { url, family } => format!("font {url} {family:?}"),
                CssUrl::ResolvedFont(url) => format!("resolved font {url}"),
                CssUrl::Link(url) => format!("link {url}"),
                CssUrl::NestedTooDeep => "nested too deep".to_owned(),
                CssUrl::Unplaced => "unplaced".to_owned(),
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
                r#".a{background:-webkit-image-set(url(/a.jxl) type("image/jxl") 2x, url(/a.jpg) type("image/jpeg") 1x, linear-gradient(red, blue) 3x)}"#,
                vec![
                    "resolved https://app.example.com/a.jpg",
                    r#"rewrite -webkit-image-set(url(/a.jxl) type("image/jxl") 2x, url(/a.jpg) type("image/jpeg") 1x, linear-gradient(red, blue) 3x) => -webkit-image-set(url("https://app.example.com/a.jpg") type("image/jpeg") 1x) dropping []"#,
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
