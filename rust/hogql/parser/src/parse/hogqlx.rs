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

use super::{identifier_text, unquote_single_string, Parser};
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::TokenKind;

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
        let result = self.parse_hogqlx_tag_element_inner();
        self.hogqlx_text_lookahead_depth -= 1;
        result
    }

    fn parse_hogqlx_tag_element_inner(&mut self) -> Result<E::Value, ParseError> {
        let tag_start = self.peek0.start;
        self.expect(TokenKind::Lt, "<")?;
        let kind = self.parse_hogqlx_identifier("tag name")?;
        let mut attributes: Vec<E::Value> = Vec::new();
        loop {
            match self.peek() {
                TokenKind::SlashGt => {
                    self.bump()?;
                    return Ok(self.wrap_pos(self.emit.hogqlx_tag(&kind, attributes), tag_start));
                }
                TokenKind::Gt => {
                    self.bump()?;
                    let children = self.parse_hogqlx_children()?;
                    self.expect(TokenKind::LtSlash, "</")?;
                    let close = self.parse_hogqlx_identifier("closing tag name")?;
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
                    attributes.push(self.parse_hogqlx_attribute()?);
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
    fn parse_hogqlx_attribute(&mut self) -> Result<E::Value, ParseError> {
        let name = self.parse_hogqlx_identifier("attribute name")?;
        // No `=` → bare attribute, value is Constant(true).
        if self.peek() != TokenKind::EqDouble {
            return Ok(self
                .emit
                .hogqlx_attribute(&name, self.emit.constant(self.emit.bool(true))));
        }
        self.bump()?; // `=`
        let value = match self.peek() {
            TokenKind::String => {
                let t = self.bump()?;
                self.emit
                    .constant(self.emit.string(&unquote_single_string(self.text(t))))
            }
            TokenKind::LBrace => {
                self.bump()?;
                let expr = self.parse_expr_bp(0)?;
                self.expect(TokenKind::RBrace, "}")?;
                expr
            }
            _ => {
                return Err(self.err(format!(
                    "expected string literal or `{{expr}}` for attribute value, got {:?}",
                    self.peek()
                )));
            }
        };
        Ok(self.emit.hogqlx_attribute(&name, value))
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
    fn parse_hogqlx_children(&mut self) -> Result<Vec<E::Value>, ParseError> {
        let mut children: Vec<E::Value> = Vec::new();
        loop {
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
                children.push(self.emit.constant(self.emit.string(&text)));
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
                    let expr = self.parse_expr_bp(0)?;
                    self.expect(TokenKind::RBrace, "}")?;
                    children.push(expr);
                }
                TokenKind::Eof => {
                    return Err(self.err("unexpected end of input inside HogQLX tag children"));
                }
                _ => {
                    // Should be unreachable — text consumption advances
                    // past anything except `<` / `{` / Eof.
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
    fn parse_hogqlx_identifier(&mut self, what: &str) -> Result<String, ParseError> {
        let head = self.bump()?;
        let mut name = match head.kind {
            TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
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
