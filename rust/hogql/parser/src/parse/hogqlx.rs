//! HogQLX tag-element parsing — JSX-like `<Tag attr='v' >children</Tag>`
//! and self-closing `<Tag />` syntax (grammar rules `hogqlxTagElement` /
//! `hogqlxTagAttribute` / `hogqlxChildElement` / `hogqlxText`).
//!
//! Three contexts admit a tag:
//!   - top of a SELECT (`select: hogqlxTagElement`)
//!   - FROM table position (`tableExpr: hogqlxTagElement`)
//!   - column position (`columnExpr: hogqlxTagElement`)
//!
//! All three route to `parse_hogqlx_tag_element` after detecting
//! `<Ident` at peek. Text content between tag bracket-`>` and the next
//! `<` / `{` is scanned at the byte level (the lexer's whitespace skip
//! would otherwise eat significant inter-token spaces in things like
//! `<span>Hello World</span>`).
//!
//! cpp's emit:
//!   - `<Tag a='v' />`   → HogQLXTag(kind="Tag", attributes=[Attr(a, Constant("v"))])
//!   - `<Tag a={e} />`   → HogQLXTag(kind="Tag", attributes=[Attr(a, e)])
//!   - `<Tag a />`       → HogQLXTag(kind="Tag", attributes=[Attr(a, Constant(true))])
//!   - `<Tag>x</Tag>`    → HogQLXTag(..., attributes=[Attr("children", [Constant("x")])])
//!   - `<Tag></Tag>`     → HogQLXTag(..., attributes=[])  (no children attr when empty)
//!
//! Ported verbatim from `parser_backtrack/src/parse/hogqlx.rs`; the
//! Parser API is identical across the two backends so no rewrites are
//! needed here.

use super::template::parse_template_body;
use super::{identifier_text, kw_valid_as_identifier, unquote_single_string, Parser};
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::{Lexer, Token, TokenKind};

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    /// True when peek/peek_next look like the start of a HogQLX tag —
    /// `<` followed by an identifier-or-keyword-acting-as-identifier.
    /// `<` followed by anything else (most commonly an expression for
    /// the `<` comparison operator) is NOT a tag.
    pub(crate) fn peek_starts_hogqlx_tag(&self) -> bool {
        if self.peek() != TokenKind::Lt {
            return false;
        }
        matches!(
            self.peek_next(),
            TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
        )
    }

    /// Like `peek_starts_hogqlx_tag`, but one token further ahead: is the
    /// token at `peek_next` (peek1) a `<` that begins a tag? Used by prefix
    /// operators (`not <tag>`) and operator disambiguation (`1 % <tag>`) where
    /// the `<` sits one token past the cursor and a probe lexer must resolve
    /// the token after it.
    pub(crate) fn peek_next_starts_hogqlx_tag(&self) -> bool {
        if self.peek_next() != TokenKind::Lt {
            return false;
        }
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        matches!(
            probe.next_token().map(|t| t.kind),
            Ok(TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_))
        )
    }

    /// cpp's `isOpeningTag()` lexer predicate (`HogQLLexer.cpp.g4`). It decides
    /// whether a `<` enters cpp's dedicated HogQLX tag lexer mode ("tight": tag
    /// tokens, whitespace hidden, `>` opens a TEXT mode that captures child
    /// text) or stays a plain `LT` that the grammar still matches as a tag in
    /// the default lexer mode ("loose": default-mode tokens, whitespace skipped,
    /// child *text* is not lexable so only nested tags / `{expr}` are valid
    /// children, but attribute values may be `f'…'` templates).
    ///
    /// `lt_end` is the byte offset just past the `<`. Tight requires `<`
    /// immediately followed by an identifier-start char, then — after the
    /// `[A-Za-z0-9_-]*` tag name — either an immediate `>` / `/`, or whitespace
    /// then `[A-Za-z0-9_]` / `>` / `/`.
    fn hogqlx_tag_is_tight(&self, lt_end: usize) -> bool {
        let bytes = self.src.as_bytes();
        let is_name_start = |c: u8| c.is_ascii_alphabetic() || c == b'_';
        let is_name_part = |c: u8| c.is_ascii_alphanumeric() || c == b'_' || c == b'-';
        match bytes.get(lt_end) {
            Some(&c) if is_name_start(c) => {}
            _ => return false,
        }
        let mut i = lt_end + 1;
        while bytes.get(i).is_some_and(|&c| is_name_part(c)) {
            i += 1;
        }
        match bytes.get(i) {
            Some(b'>') | Some(b'/') => true,
            Some(&c) if c.is_ascii_whitespace() => {
                let j = self.hogqlx_skip_ws_and_comments(i);
                matches!(bytes.get(j), Some(&c) if c.is_ascii_alphanumeric() || c == b'_' || c == b'>' || c == b'/')
            }
            _ => false,
        }
    }

    /// Byte-level skip of whitespace and `/* … */` / `--` / `//` comments,
    /// mirroring cpp's `skipWsAndComments` used inside `isOpeningTag`.
    fn hogqlx_skip_ws_and_comments(&self, mut i: usize) -> usize {
        let bytes = self.src.as_bytes();
        loop {
            while bytes.get(i).is_some_and(|&c| c.is_ascii_whitespace()) {
                i += 1;
            }
            if bytes.get(i) == Some(&b'/') && bytes.get(i + 1) == Some(&b'*') {
                i += 2;
                while i + 1 < bytes.len() && !(bytes[i] == b'*' && bytes[i + 1] == b'/') {
                    i += 1;
                }
                i += 2;
                continue;
            }
            if (bytes.get(i) == Some(&b'-') && bytes.get(i + 1) == Some(&b'-'))
                || (bytes.get(i) == Some(&b'/') && bytes.get(i + 1) == Some(&b'/'))
            {
                while bytes.get(i).is_some_and(|&c| c != b'\n' && c != b'\r') {
                    i += 1;
                }
                continue;
            }
            return i;
        }
    }

    /// Parse a HogQLX tag element starting at `<`.
    ///
    /// Handles both `<Tag attr* />` (self-closing) and
    /// `<Tag attr*>children</Tag>` (nested). For nested form, validates
    /// that opening and closing tag names match (cpp emits an
    /// "Opening and closing HogQLX tags must match" error otherwise)
    /// and auto-injects the `children` attribute from any parsed child
    /// elements.
    ///
    /// Tolerate peek1 lex errors while parsing the tag (and any nested
    /// tags): cpp's `HOGQLX_TEXT` lexer mode admits any byte except
    /// `<` / `{` inside the body, but rust's mode-less lexer rejects
    /// punctuation like `&` / `!` / `@` when pre-loading peek1 across
    /// a `>` / `/>` / `</…>` boundary. `parse_hogqlx_children`
    /// byte-walks the body directly and re-seeks the lexer via
    /// `consume_hogqlx_text`, so peek1's transient invalid state is
    /// recoverable.
    pub(crate) fn parse_hogqlx_tag_element(&mut self) -> Result<E::Value, ParseError> {
        self.hogqlx_text_lookahead_depth += 1;
        // cpp pushes HOGQLX_TAG_OPEN at `<`; those tag modes have no
        // HASH_COMMENT rule, so a `#` between attributes must reject
        // (TAG_UNEXPECTED) instead of being skipped as a comment. The
        // flag covers the whole element — attributes, children, closing
        // tag — and the `{ … }` arms flip it back off, matching
        // TAG_LBRACE's pushMode(DEFAULT_MODE).
        let was_in_tag = self.lexer.in_hogqlx_tag();
        self.lexer.set_in_hogqlx_tag(true);
        let result = self.parse_hogqlx_tag_element_inner();
        self.lexer.set_in_hogqlx_tag(was_in_tag);
        if result.is_ok() && !was_in_tag {
            // The peek window past the element was pre-loaded under tag
            // mode; re-lex it so a `#` comment after the tag is skipped
            // again.
            self.reseek_peek_window(self.last_consumed_end);
        }
        self.hogqlx_text_lookahead_depth -= 1;
        result
    }

    /// Re-lex `peek0` / `peek1` from `pos` after a tag-mode flip changed
    /// how the upcoming bytes tokenise. A lex failure parks a synthetic
    /// `Eof` in the failing slot — the same recovery `bump()` applies
    /// inside tag bodies — so raw text bytes (`&`, `!`, …) right after
    /// the boundary stay recoverable for the byte-walking text consumer.
    fn reseek_peek_window(&mut self, pos: usize) {
        let in_tag = self.lexer.in_hogqlx_tag();
        self.lexer = Lexer::with_pos(self.src, pos);
        self.lexer.set_in_hogqlx_tag(in_tag);
        self.peek0 = self.next_token_or_synthetic_eof();
        self.peek1 = self.next_token_or_synthetic_eof();
    }

    fn next_token_or_synthetic_eof(&mut self) -> Token {
        match self.lexer.next_token() {
            Ok(t) => t,
            Err(_) => Token::eof(self.lexer.pos()),
        }
    }

    fn parse_hogqlx_tag_element_inner(&mut self) -> Result<E::Value, ParseError> {
        let tag_start = self.peek0.start;
        self.expect(TokenKind::Lt, "<")?;
        // cpp lexes `<ident…` tags ("tight") through dedicated tag/text modes,
        // and `< ident…` ("loose") through the default mode — they differ on
        // child text (tight captures it, loose admits only nested tags / `{…}`)
        // and on attribute values (loose also admits an `f'…'` template).
        let tight = self.hogqlx_tag_is_tight(self.last_consumed_end);
        // A loose opening name lexes in the default mode and may be a
        // QUOTED_IDENTIFIER (`< "x" />` accepts); a tight name is a bare
        // TAG_IDENT. The CLOSING name, by contrast, always lexes in
        // HOGQLX_TAG_CLOSE mode (bare only — see the `false` below), so a quoted
        // opening can only ever pair with a self-closing `/>`, never `</"x">`.
        let kind = self.parse_hogqlx_identifier("tag name", !tight)?;
        let mut attributes: Vec<E::Value> = Vec::new();
        loop {
            match self.peek() {
                TokenKind::SlashGt => {
                    self.bump()?;
                    return Ok(self.wrap_pos(self.emit.hogqlx_tag(&kind, attributes), tag_start));
                }
                TokenKind::Gt => {
                    self.bump()?;
                    let children = self.parse_hogqlx_children(tight)?;
                    self.expect(TokenKind::LtSlash, "</")?;
                    let close = self.parse_hogqlx_identifier("closing tag name", false)?;
                    if close != kind {
                        return Err(self.err(format!(
                            "Opening and closing HogQLX tags must match. Got {} and {}",
                            kind, close
                        )));
                    }
                    self.expect(TokenKind::Gt, ">")?;
                    if !children.is_empty() {
                        if attributes.iter().any(|a| {
                            self.emit
                                .get_field(a, "name")
                                .and_then(|v| self.emit.as_str(&v).map(|s| s.into_owned()))
                                .as_deref()
                                == Some("children")
                        }) {
                            return Err(self.err(
                                "Can't have a HogQLX tag with both children and a 'children' attribute",
                            ));
                        }
                        let kids = self.emit.list_value(children);
                        attributes.push(self.emit.hogqlx_attribute("children", kids));
                    }
                    return Ok(self.wrap_pos(self.emit.hogqlx_tag(&kind, attributes), tag_start));
                }
                TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
                    attributes.push(self.parse_hogqlx_attribute(tight)?);
                }
                TokenKind::Eof => {
                    return Err(self.err("unexpected end of input inside HogQLX tag"));
                }
                _ => {
                    return Err(self.err(format!(
                        "expected attribute name, `>`, or `/>` inside HogQLX tag, got {:?}",
                        self.peek()
                    )));
                }
            }
        }
    }

    /// Parse one of:
    ///   - `name = 'string'` → HogQLXAttribute(name, Constant(string))
    ///   - `name = { expr }` → HogQLXAttribute(name, expr)
    ///   - `name`            → HogQLXAttribute(name, Constant(true))
    fn parse_hogqlx_attribute(&mut self, tight: bool) -> Result<E::Value, ParseError> {
        // cpp positions the HogQLXAttribute from the name start to the value end
        // (or the name end for a bare attribute), and the string value Constant
        // over the string token. The bare-attribute `Constant(true)` stays
        // position-less (cpp leaves it null too).
        let name_start = self.peek0.start;
        let name = self.parse_hogqlx_identifier("attribute name", true)?;
        let name_end = self.last_consumed_end;
        // No `=` → bare attribute, value is Constant(true).
        if self.peek() != TokenKind::EqDouble {
            let attr = self
                .emit
                .hogqlx_attribute(&name, self.emit.constant(self.emit.bool(true)));
            return Ok(self.wrap_pos_to(attr, name_start, name_end));
        }
        self.bump()?; // `=`
        let value = match self.peek() {
            TokenKind::String => {
                let t = self.bump()?;
                let c = self
                    .emit
                    .constant(self.emit.string(&unquote_single_string(self.text(t))));
                self.wrap_pos_to(c, t.start, t.end)
            }
            TokenKind::LBrace => {
                self.bump()?;
                // cpp's TAG_LBRACE pushes DEFAULT_MODE — `#` comments
                // apply again inside the braced value. Re-lex the peek
                // window on both edges; it was pre-loaded under the
                // other mode.
                self.lexer.set_in_hogqlx_tag(false);
                self.reseek_peek_window(self.last_consumed_end);
                let expr = self.parse_expr_bp(0)?;
                self.expect(TokenKind::RBrace, "}")?;
                self.lexer.set_in_hogqlx_tag(true);
                self.reseek_peek_window(self.last_consumed_end);
                expr
            }
            // A loose tag lexes attribute values in the default mode, where the
            // grammar's `string` is STRING_LITERAL | templateString — so
            // `< a b=f'x' />` admits an `f'…'` template. A tight tag lexes in
            // TAG mode (TAG_STRING is STRING_LITERAL only), so `<a b=f'x'/>` has
            // no template token and cpp rejects it: fall through to the error.
            TokenKind::TemplateString if !tight => {
                let t = self.bump()?;
                if self.text(t).starts_with("F'") {
                    return Err(self.err("mismatched input 'F''"));
                }
                parse_template_body(&self.emit, self.src, t.start + 2, t.end - 1)?
            }
            _ => {
                return Err(self.err(format!(
                    "expected string literal{} or `{{expr}}` for attribute value, got {:?}",
                    if tight { "" } else { ", `f'…'` template," },
                    self.peek()
                )));
            }
        };
        let value_end = self.last_consumed_end;
        let attr = self.emit.hogqlx_attribute(&name, value);
        Ok(self.wrap_pos_to(attr, name_start, value_end))
    }

    /// Read tag-body children until the closing `</`. Children are:
    ///   - nested tag elements (`<Inner ... >...</Inner>` / `<Inner />`)
    ///   - `{ expr }` blocks
    ///   - raw text — everything between tag-end-`>` (or the previous
    ///     child boundary) and the next `<` or `{`, byte-for-byte
    ///
    /// Text scanning uses the source's byte stream directly because the
    /// lexer's whitespace skip would otherwise destroy significant
    /// inter-token spacing (e.g. `Hello World`).
    fn parse_hogqlx_children(&mut self, tight: bool) -> Result<Vec<E::Value>, ParseError> {
        let mut children: Vec<E::Value> = Vec::new();
        loop {
            // A tight tag's `>` opens cpp's HOGQLX_TEXT lexer mode, which captures
            // child text (incl. whitespace). A loose tag's `>` is a plain GT in the
            // default mode — there is no HOGQLX_TEXT token, so child text isn't
            // lexable and only nested tags / `{…}` are valid children (the `_` arm
            // below rejects stray text, matching cpp's `< a >x</a>` reject), and
            // whitespace between children is skipped by the lexer, not kept.
            if tight {
                // `consume_hogqlx_text` scans from `last_consumed_end`, so that is
                // the text run's start; its byte length gives the end. cpp positions
                // each kept text Constant over its raw byte span.
                let text_start = self.last_consumed_end;
                let text = self.consume_hogqlx_text()?;
                // cpp's `VISIT(HogqlxTagElementNested)` drops child text
                // runs that contain a newline AND are entirely whitespace —
                // any pretty-printed multi-line HOGQLX literal lands here.
                // Pure-space / pure-tab runs (no newline) are kept. Mixed
                // whitespace-with-content runs are also kept verbatim.
                let drop_for_newline_ws = !text.is_empty()
                    && text.bytes().all(|b| b.is_ascii_whitespace())
                    && text.bytes().any(|b| b == b'\n' || b == b'\r');
                if !text.is_empty() && !drop_for_newline_ws {
                    let text_end = text_start + text.len();
                    let c = self.emit.constant(self.emit.string(&text));
                    children.push(self.wrap_pos_to(c, text_start, text_end));
                }
            }
            match self.peek() {
                TokenKind::LtSlash => return Ok(children),
                TokenKind::Lt => {
                    if !matches!(
                        self.peek_next(),
                        TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
                    ) {
                        return Err(self.err(format!(
                            "expected nested tag name or `</` after `<`, got {:?}",
                            self.peek_next()
                        )));
                    }
                    let nested = self.parse_hogqlx_tag_element()?;
                    children.push(nested);
                }
                TokenKind::LBrace => {
                    self.bump()?;
                    // TAG_LBRACE → DEFAULT_MODE, same as the
                    // attribute-value arm. No re-lex after the `}` —
                    // the loop's `consume_hogqlx_text` byte-walks from
                    // `last_consumed_end` and re-seeks the window
                    // itself.
                    self.lexer.set_in_hogqlx_tag(false);
                    self.reseek_peek_window(self.last_consumed_end);
                    let expr = self.parse_expr_bp(0)?;
                    self.expect(TokenKind::RBrace, "}")?;
                    self.lexer.set_in_hogqlx_tag(true);
                    children.push(expr);
                }
                TokenKind::Eof => {
                    return Err(self.err("unexpected end of input inside HogQLX tag children"));
                }
                _ => {
                    // Tight: unreachable — `consume_hogqlx_text` advances past
                    // anything except `<` / `{` / Eof. Loose: a stray default-mode
                    // token (bare text like `x`) — not a valid loose child, so
                    // reject, matching cpp's `< a >x</a>`.
                    return Err(self.err(format!(
                        "unexpected token in HogQLX tag children: {:?}",
                        self.peek()
                    )));
                }
            }
        }
    }

    /// Scan source bytes from the position immediately after the last
    /// consumed token up to the next `<` or `{` (or EOF). Returns the
    /// raw text — empty when peek is already at `<` / `{`. Re-seeks the
    /// lexer to the boundary position so subsequent token-based parsing
    /// continues from there.
    fn consume_hogqlx_text(&mut self) -> Result<String, ParseError> {
        let start = self.last_consumed_end;
        let bytes = self.src.as_bytes();
        // Truth-of-the-bytes check: are we already at a real
        // tag-body boundary? Don't trust peek0 alone — when
        // `hogqlx_text_lookahead_depth > 0` the parser may carry a
        // synthetic `Eof` token in peek0/peek1 because the default-mode
        // lexer choked on a text-only byte. Look at the actual source
        // byte at `start`.
        if start >= bytes.len() {
            return Ok(String::new());
        }
        let head_byte = bytes[start];
        if head_byte == b'<' || head_byte == b'{' {
            return Ok(String::new());
        }
        let mut i = start;
        while i < bytes.len() {
            let c = bytes[i];
            if c == b'<' || c == b'{' {
                break;
            }
            i += 1;
        }
        let text = self.src[start..i].to_string();
        self.set_lexer_pos(i)?;
        Ok(text)
    }

    /// Read a single tag-name / attribute-name token. cpp's
    /// `HOGQLX_TAG_OPEN` / `HOGQLX_TAG_CLOSE` lexer modes
    /// (`HogQLLexer.common.g4:315 + 326`) admit
    /// `[a-zA-Z_][a-zA-Z0-9_-]*` — hyphens are part of the identifier
    /// inside tag-open / tag-close modes. Rust's lexer doesn't have
    /// modes, so `a-b` lexes as `Ident a`, `Dash`, `Ident b`; stitch
    /// them back together here when the dash is followed immediately
    /// by an ident-like token with no intervening whitespace.
    fn parse_hogqlx_identifier(
        &mut self,
        what: &str,
        allow_quoted: bool,
    ) -> Result<String, ParseError> {
        let head = self.bump()?;
        // A tag/attr name is an `identifier` (grammar `hogqlxTagElement` /
        // `hogqlxTagAttribute`), so a keyword head is only valid when it is a
        // grammar-`keyword`-rule member. The Hog-statement keywords (fn/let/…),
        // set-op keywords (intersect/except) and literal keywords (null/inf/nan)
        // are omitted from that rule, so cpp rejects `<fn/>` / `<a let/>` with
        // "no viable alternative"; gate them out here to match.
        //
        // A quoted head (`` `x` `` / `"x"`) is rejected for TAG names — cpp's tag
        // lexer modes never yield QUOTED_IDENTIFIER there, and the loose default
        // mode rejects `< "x" >` / `` < `x` > `` too. Attribute names DO admit a
        // quoted form (`< c "h" >`), so `allow_quoted` gates only the name kind.
        let mut name = match head.kind {
            TokenKind::Ident => identifier_text(self.text(head), head.kind),
            TokenKind::QuotedIdent if allow_quoted => identifier_text(self.text(head), head.kind),
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                identifier_text(self.text(head), head.kind)
            }
            _ => {
                return Err(self.err(format!(
                    "expected {} (identifier or keyword), got {:?}",
                    what, head.kind
                )));
            }
        };
        let mut last_end = head.end;
        // Greedy hyphen-stitch loop. Per the grammar, hyphens may
        // appear anywhere AFTER the leading char and must be
        // immediately followed by another `[a-zA-Z0-9_]` character.
        // Require a zero-byte gap on either side of the dash so we
        // don't paper over actual whitespace-separated tokens.
        while self.peek() == TokenKind::Dash && self.peek0.start == last_end {
            let cont_start = self.peek_next_start();
            if self.peek0.end != cont_start {
                break;
            }
            if !matches!(
                self.peek_next(),
                TokenKind::Ident | TokenKind::Keyword(_) | TokenKind::Number,
            ) {
                break;
            }
            self.bump()?; // dash
            let next = self.bump()?;
            name.push('-');
            name.push_str(self.text(next));
            last_end = next.end;
        }
        Ok(name)
    }

    fn peek_next_start(&self) -> usize {
        self.peek1.start
    }
}
