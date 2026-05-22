//! `WITH` clause / Common Table Expression parsing.
//!
//! Two grammar shapes:
//!
//! - Subquery form:   `ident [USING KEY (cols)] AS [NOT? MATERIALIZED] LPAREN selectSet RPAREN`
//! - Column form:     `columnExpr AS ident`
//!
//! Disambiguation is done by a shadow-lexer probe: when the leading
//! token is an identifier-or-keyword-acting-as-identifier and the
//! follow-up sequence ends with `AS (`, we commit to subquery form.

use super::{identifier_text, kw_valid_as_identifier, Parser, BP_ALIAS};
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, TokenKind};

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    pub(crate) fn parse_with_expr_list(&mut self) -> Result<Vec<E::Value>, ParseError> {
        // The C++ visitor returns CTEs as a list; the Python deserialiser
        // turns it into a dict keyed by name. We follow the same shape.
        // ANTLR ALL(*) tolerates a trailing comma before the SELECT
        // that terminates the CTE list; mirror that. A bare `LPAREN`
        // following the comma can ALSO be the leading `(` of the next
        // CTE element (column-form `(SELECT 1) AS x` / `(a + b) AS y`),
        // so peek past the matching `)` to see if an `AS identifier`
        // pattern follows before terminating the loop.
        let mut out = Vec::new();
        loop {
            out.push(self.parse_with_expr()?);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if matches!(self.peek(), TokenKind::Keyword(Kw::Select)) {
                break;
            }
            if self.peek() == TokenKind::LParen && !self.paren_group_followed_by_as_identifier() {
                break;
            }
        }
        Ok(out)
    }

    /// `self.peek()` is `(`. Probe whether the matching `)` is followed
    /// by an `AS identifier` pattern — the shape that marks the paren
    /// group as the head of the next column-form CTE
    /// (`(SELECT 1) AS x`, `(a + b) AS y`) rather than the leading
    /// paren of the enclosing SELECT statement.
    fn paren_group_followed_by_as_identifier(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.end);
        let mut depth: i32 = 1;
        while depth > 0 {
            let tok = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
            match tok.kind {
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => depth -= 1,
                TokenKind::Eof => return false,
                _ => {}
            }
        }
        let after = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        if after.kind != TokenKind::Keyword(Kw::As) {
            return false;
        }
        let ident = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        matches!(
            ident.kind,
            TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
        )
    }

    fn parse_with_expr(&mut self) -> Result<E::Value, ParseError> {
        let cte_start = self.peek0.start;
        // The grammar's `identifier` rule accepts plain IDENTIFIERs,
        // QUOTED_IDENTIFIERs, and (most) reserved keywords — see
        // HogQLParser.g4's `identifier` and `keyword` rules — so we
        // include those keywords here too. Otherwise a CTE named
        // `final`, `date`, etc. would fall through to the expr-form
        // fallback and mis-parse. Use `kw_valid_as_identifier` rather
        // than `kw_acts_as_ident_in_primary` — the latter excludes the
        // primary-form heads (CASE / SELECT / CAST / NOT) that have
        // their own parse_primary branches, but those names ARE valid
        // CTE identifiers in cpp's grammar (CASE / CAST / SELECT / NOT
        // are all in the `keyword` rule).
        let head_is_identifierlike =
            matches!(self.peek(), TokenKind::Ident | TokenKind::QuotedIdent)
                || matches!(self.peek(), TokenKind::Keyword(kw) if kw_valid_as_identifier(kw));
        if head_is_identifierlike {
            let mut probe = Lexer::with_pos(self.src, self.peek0.start);
            drop(probe.next_token()); // ident
                                      // Optional column name list immediately after the ident.
            let mut after = probe.next_token().ok();
            if matches!(after.as_ref().map(|t| t.kind), Some(TokenKind::LParen)) {
                let mut depth = 1;
                loop {
                    let t = probe.next_token().ok();
                    match t.as_ref().map(|t| t.kind) {
                        Some(TokenKind::LParen) => depth += 1,
                        Some(TokenKind::RParen) => {
                            depth -= 1;
                            if depth == 0 {
                                break;
                            }
                        }
                        None | Some(TokenKind::Eof) => break,
                        _ => {}
                    }
                }
                after = probe.next_token().ok();
            }
            // After optional col list, `USING KEY (cols)`.
            if matches!(
                after.as_ref().map(|t| t.kind),
                Some(TokenKind::Keyword(Kw::Using))
            ) {
                if let Ok(next) = probe.next_token() {
                    if next.kind == TokenKind::Keyword(Kw::Key) {
                        drop(probe.next_token()); // LPAREN
                        let mut depth = 1;
                        loop {
                            let t = probe.next_token().ok();
                            match t.as_ref().map(|t| t.kind) {
                                Some(TokenKind::LParen) => depth += 1,
                                Some(TokenKind::RParen) => {
                                    depth -= 1;
                                    if depth == 0 {
                                        break;
                                    }
                                }
                                None | Some(TokenKind::Eof) => break,
                                _ => {}
                            }
                        }
                        after = probe.next_token().ok();
                    }
                }
            }
            // The shape is the CTE-with-subquery form if next is `AS` and
            // after-AS comes `(` (possibly after `NOT? MATERIALIZED`).
            if matches!(
                after.as_ref().map(|t| t.kind),
                Some(TokenKind::Keyword(Kw::As))
            ) {
                let mut nxt = probe.next_token().ok();
                if matches!(
                    nxt.as_ref().map(|t| t.kind),
                    Some(TokenKind::Keyword(Kw::Not))
                ) {
                    nxt = probe.next_token().ok();
                }
                if matches!(
                    nxt.as_ref().map(|t| t.kind),
                    Some(TokenKind::Keyword(Kw::Materialized))
                ) {
                    nxt = probe.next_token().ok();
                }
                if matches!(nxt.as_ref().map(|t| t.kind), Some(TokenKind::LParen)) {
                    let sub = self.parse_with_expr_subquery()?;
                    return Ok(self.wrap_pos(sub, cte_start));
                }
            }
        }
        // Fallback: `expr AS ident` form. Parse the expression at a min
        // binding power above BP_ALIAS so the CTE's `AS` doesn't get
        // swallowed by the Pratt-level Alias operator.
        let expr = self.parse_expr_bp(BP_ALIAS + 1)?;
        self.expect_kw(Kw::As, "AS")?;
        // `withExpr: columnExpr AS identifier` — the post-AS token must
        // be a valid identifier (`IDENTIFIER | QUOTED_IDENTIFIER |
        // interval | keyword`), NOT an arbitrary token. Without this
        // check rust accepted `WITH a AS 1` with name="1" (raw token
        // text) and `WITH ... AS 'foo'` with name="'foo'" (quotes
        // preserved).
        let id = self.bump()?;
        let name = match id.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => identifier_text(self.text(id), id.kind),
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                identifier_text(self.text(id), id.kind)
            }
            _ => {
                return Err(self.err(format!(
                    "expected identifier after AS in CTE, got {:?}",
                    id.kind
                )));
            }
        };
        Ok(self.wrap_pos(self.emit.cte(&name, expr, "column"), cte_start))
    }

    fn parse_with_expr_subquery(&mut self) -> Result<E::Value, ParseError> {
        let id = self.bump()?;
        let name = identifier_text(self.text(id), id.kind);
        // Optional column-name list (parenthesised idents).
        let mut columns: Option<Vec<String>> = None;
        if self.eat(TokenKind::LParen)? {
            let mut cols = Vec::new();
            loop {
                let t = self.bump()?;
                // Grammar's CTE column-name list elements are
                // `identifier` (`IDENTIFIER | QUOTED_IDENTIFIER |
                // interval | keyword`); exclude reserved keywords.
                let col_name = match t.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(t), t.kind)
                    }
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        identifier_text(self.text(t), t.kind)
                    }
                    _ => {
                        return Err(self.err(format!(
                            "expected identifier in CTE column-list, got {:?}",
                            t.kind
                        )));
                    }
                };
                cols.push(col_name);
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RParen {
                    break;
                }
            }
            self.expect(TokenKind::RParen, ")")?;
            columns = Some(cols);
        }
        // Optional `USING KEY (col, ...)` — recursive-CTE key.
        let using_key = if self.eat_kw(Kw::Using)? {
            self.expect_kw(Kw::Key, "KEY")?;
            self.expect(TokenKind::LParen, "(")?;
            let mut keys = Vec::new();
            loop {
                let t = self.bump()?;
                keys.push(identifier_text(self.text(t), t.kind));
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RParen {
                    break;
                }
            }
            self.expect(TokenKind::RParen, ")")?;
            Some(keys)
        } else {
            None
        };
        self.expect_kw(Kw::As, "AS")?;
        let materialized = if self.eat_kw(Kw::Not)? {
            self.expect_kw(Kw::Materialized, "MATERIALIZED")?;
            Some(false)
        } else if self.eat_kw(Kw::Materialized)? {
            Some(true)
        } else {
            None
        };
        self.expect(TokenKind::LParen, "(")?;
        let sub = self.parse_select_set_stmt()?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(self
            .emit
            .cte_subquery(&name, sub, columns, using_key, materialized))
    }
}
