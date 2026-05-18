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

use serde_json::{json, Value};

use super::{identifier_text, unquote_single_string, Parser};
use crate::emit;
use crate::error::ParseError;
use crate::lex::TokenKind;

impl<'a> Parser<'a> {
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
    pub(crate) fn parse_hogqlx_tag_element(&mut self) -> Result<Value, ParseError> {
        self.expect(TokenKind::Lt, "<")?;
        let kind = self.parse_hogqlx_identifier("tag name")?;
        let mut attributes: Vec<Value> = Vec::new();
        loop {
            match self.peek() {
                TokenKind::SlashGt => {
                    self.bump()?;
                    return Ok(json!({
                        "node": "HogQLXTag",
                        "kind": kind,
                        "attributes": attributes,
                    }));
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
                            a.as_object()
                                .and_then(|o| o.get("name").and_then(Value::as_str))
                                == Some("children")
                        }) {
                            return Err(self.err(
                                "Can't have a HogQLX tag with both children and a 'children' attribute",
                            ));
                        }
                        attributes.push(json!({
                            "node": "HogQLXAttribute",
                            "name": "children",
                            "value": children,
                        }));
                    }
                    return Ok(json!({
                        "node": "HogQLXTag",
                        "kind": kind,
                        "attributes": attributes,
                    }));
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
    fn parse_hogqlx_attribute(&mut self) -> Result<Value, ParseError> {
        let name = self.parse_hogqlx_identifier("attribute name")?;
        // No `=` → bare attribute, value is Constant(true).
        if self.peek() != TokenKind::EqDouble {
            return Ok(json!({
                "node": "HogQLXAttribute",
                "name": name,
                "value": emit::constant(Value::Bool(true)),
            }));
        }
        self.bump()?; // `=`
        let value = match self.peek() {
            TokenKind::String => {
                let t = self.bump()?;
                emit::constant(Value::String(unquote_single_string(self.text(t))))
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
        Ok(json!({
            "node": "HogQLXAttribute",
            "name": name,
            "value": value,
        }))
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
    fn parse_hogqlx_children(&mut self) -> Result<Vec<Value>, ParseError> {
        let mut children: Vec<Value> = Vec::new();
        loop {
            let text = self.consume_hogqlx_text()?;
            if !text.is_empty() {
                children.push(emit::constant(Value::String(text)));
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
        // Skip if peek0 is already at a tag/expr boundary (no text to
        // consume) — avoids the empty-string + needless re-seek.
        if matches!(
            self.peek(),
            TokenKind::Lt | TokenKind::LtSlash | TokenKind::LBrace | TokenKind::Eof
        ) && self.peek0.start == start
        {
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
        if i == start {
            return Ok(String::new());
        }
        let text = self.src[start..i].to_string();
        self.set_lexer_pos(i)?;
        Ok(text)
    }

    /// Read a single tag-name / attribute-name token. cpp's `identifier`
    /// rule accepts plain idents, quoted idents, and most keywords;
    /// mirror that here so `<from a='1' />` (`from` is a keyword) parses
    /// cleanly.
    fn parse_hogqlx_identifier(&mut self, what: &str) -> Result<String, ParseError> {
        let t = self.bump()?;
        match t.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => Ok(identifier_text(self.text(t), t.kind)),
            TokenKind::Keyword(_) => Ok(identifier_text(self.text(t), t.kind)),
            _ => Err(self.err(format!(
                "expected {} (identifier or keyword), got {:?}",
                what, t.kind
            ))),
        }
    }
}
