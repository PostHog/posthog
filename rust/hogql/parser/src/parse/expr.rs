//! Expression parsing: Pratt loop, prefix/primary forms, postfix
//! handlers, special infix operators (BETWEEN, IS NULL, NOT IN, etc.).
//!
//! All operator binding powers come from `bp.rs`. The parser body lives
//! here as additional `impl<'a> Parser<'a>` blocks; the few utility
//! methods (`set_lexer_pos`, `parse_expr_list_until_*`,
//! `parse_order_expr_list`, `peek_is_clause_terminator`) stay in
//! `parse.rs` because both the SELECT/JOIN/CTE modules and the
//! expression parser reach them.

use super::template::parse_template_body;
use super::{
    build_infix, fold_call_or_exprcall, identifier_text, infix_bp, interval_call_name,
    interval_call_name_case_sensitive, is_reserved_alias_name, kw_acts_as_ident_in_primary,
    kw_valid_as_identifier, kw_valid_type_cast_ident, parse_number_literal, postfix_bp,
    unquote_single_string, Parser, BP_ADDITIVE, BP_ALIAS, BP_BETWEEN, BP_COMPARE, BP_IGNORE_NULLS,
    BP_IS_DISTINCT_FROM, BP_IS_NULL, BP_NOT, BP_OR, BP_POSTFIX, BP_TERNARY, BP_UNARY_MINUS,
};
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, Token, TokenKind};

/// Return value of [`Parser::parse_columns_decorators`]: optional
/// `EXCLUDE` name list, plus an optional `REPLACE` `(expr AS name, …)`
/// list as (name, expr) pairs in declaration order.
type ColumnsDecorators<V> = (Option<Vec<String>>, Option<Vec<(String, V)>>);

/// Return value of [`Parser::parse_function_args_inner`]: the
/// `DISTINCT` flag, the positional args, and an optional in-arg
/// `ORDER BY` list.
type FunctionArgs<V> = (bool, Vec<V>, Option<Vec<V>>);

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    pub(crate) fn parse_expr_bp(&mut self, min_bp: u8) -> Result<E::Value, ParseError> {
        // Cap the central recursive entry so deeply-nested input (`((…))` with thousands of nests) surfaces as a syntax error rather than stack OOM. Bound rationale on `MAX_EXPR_RECURSION_DEPTH`.
        self.expr_recursion_depth += 1;
        let result = if self.expr_recursion_depth > crate::parse::MAX_EXPR_RECURSION_DEPTH {
            Err(ParseError::syntax(
                "expression too deeply nested",
                self.peek0.start,
                self.peek0.end,
            ))
        } else {
            let lhs_start = self.peek0.start;
            self.parse_prefix()
                .map(|lhs| self.wrap_pos(lhs, lhs_start))
                .and_then(|lhs| self.pratt_continue_with_lhs(lhs, min_bp, lhs_start))
        };
        self.expr_recursion_depth -= 1;
        result
    }

    /// Run the Pratt infix/postfix loop with an externally-provided
    /// LHS. Used by code paths that already have a partial expression
    /// to extend (e.g. modulo-promoted LIMIT expressions chaining into
    /// trailing `* …` arithmetic).
    pub(crate) fn pratt_continue_with_lhs(
        &mut self,
        mut lhs: E::Value,
        min_bp: u8,
        lhs_start: usize,
    ) -> Result<E::Value, ParseError> {
        loop {
            let kind = self.peek();
            if let Some((lbp, rbp, op)) = infix_bp(kind) {
                if lbp < min_bp {
                    break;
                }
                // `%` doubles as the modulo operator and the
                // LIMIT/SAMPLE `PERCENT` clause marker. Bind it as
                // modulo only when an operand actually follows; a `%`
                // with no right-hand side (clause boundary, EOF) is the
                // PERCENT marker and belongs to the enclosing clause.
                // cpp's ALL(*) makes the same call — it won't take
                // `columnExpr % columnExpr` when the right operand
                // can't be matched (e.g. `LIMIT lambda x : 1 %`, where
                // the lambda body is `1` and `%` marks LIMIT PERCENT).
                if kind == TokenKind::Percent {
                    // Inside a LIMIT body the modulo-vs-PERCENT call
                    // can't be made from the next token alone (a `%`
                    // followed by a keyword may be modulo on a
                    // keyword-Field or the PERCENT marker). Resolve it
                    // with the same speculative parse cpp's ALL(*)
                    // uses: `Some` → modulo extension committed; `None`
                    // → the `%` is the PERCENT marker, left for the
                    // enclosing LIMIT clause.
                    if self.limit_body_depth > 0 {
                        match self.try_limit_modulo_extension(lhs.clone(), lhs_start)? {
                            Some(extended) => {
                                lhs = extended;
                                continue;
                            }
                            None => break,
                        }
                    }
                    let next = self.peek_next();
                    if !peek_can_start_clause_body(next) || is_pure_infix_op(next) {
                        break;
                    }
                }
                // Statement-rhs recovery: when this Pratt loop is the
                // rhs of a statement-level `:=` / `let X := …` /
                // `return …` parse, an infix operator whose RHS fails
                // to parse (e.g. `{} * ()` where `()` is an empty
                // paren) is cpp's "split into two statements" shape:
                // the rhs ends at the LHS so far, and the operator +
                // failing RHS becomes the next statement. Mirror that
                // via checkpoint-restore — without the flag the
                // behaviour is the historical immediate error.
                if self.stmt_rhs_recover_on_pratt_rhs_failure {
                    let cp = self.checkpoint();
                    self.bump()?;
                    match self.parse_expr_bp(rbp) {
                        Ok(rhs) => {
                            lhs = self.wrap_pos(build_infix(&self.emit, op, lhs, rhs), lhs_start);
                            continue;
                        }
                        Err(_) => {
                            self.restore(cp)?;
                            break;
                        }
                    }
                }
                self.bump()?;
                let rhs = self.parse_expr_bp(rbp)?;
                lhs = self.wrap_pos(build_infix(&self.emit, op, lhs, rhs), lhs_start);
                continue;
            }
            if let Some(handled) = self.try_special_infix(kind, &mut lhs, min_bp, lhs_start)? {
                if handled {
                    // `try_special_infix` mutates `lhs` in place with a fresh
                    // unpositioned JSON node (`CompareOperation`, `BetweenExpr`,
                    // `IsDistinctFrom`, etc.). Wrap with the pratt loop's
                    // running span so the new outer node carries `start` /
                    // `end` matching cpp's `addPositionInfo` calls.
                    lhs = self.wrap_pos(lhs, lhs_start);
                    continue;
                }
            }
            if let Some(lbp) = postfix_bp(kind) {
                if lbp < min_bp {
                    break;
                }
                // Statement-RHS guard: `(a) := (b) (c) := (d)` — when
                // parsing the first assignment's RHS, the postfix `(`
                // of `(c)` would greedily fold as a `(…)`-call onto
                // `(b)`, stranding the second `:=`. cpp's ALL(*)
                // backtracks; we stop the fold when a `:=` follows the
                // matching `)`, leaving `(c)` to start the next
                // statement.
                if kind == TokenKind::LParen
                    && self.stop_postfix_call_before_colon_equals
                    && self.paren_block_then_colon_equals(self.peek0.end)
                {
                    break;
                }
                lhs = self.parse_postfix(kind, lhs)?;
                lhs = self.wrap_pos(lhs, lhs_start);
                continue;
            }
            break;
        }
        Ok(self.wrap_pos(lhs, lhs_start))
    }

    pub(crate) fn parse_prefix(&mut self) -> Result<E::Value, ParseError> {
        // `IDENT (, IDENT)* -> body` — a bare-list arrow lambda may
        // appear as the RHS of any binary operator (e.g. `x =~* y, z ->
        // body` parses as `x =~* (lambda y, z -> body)`). The probe is
        // cheap and only commits on a confirmed `id (, id)* ->` run.
        // A lambda parameter is an `identifier`, which the grammar lets
        // any keyword fill (`name -> 1`, `select -> 1`), so a leading
        // keyword is a candidate head too.
        if matches!(
            self.peek(),
            TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
        ) {
            if let Some(lambda) = self.try_bare_list_lambda()? {
                return Ok(lambda);
            }
        }
        match self.peek() {
            TokenKind::Dash => {
                // `-<number>` / `-.<number>` / `-inf` / `-nan` is a signed
                // Constant per grammar's `numberLiteral: (PLUS | DASH)?
                // (... | floatingLiteral)` and `floatingLiteral: DOT
                // DECIMAL_LITERAL`. Treat all four as a single negative
                // literal, not a unary minus.
                match self.peek_next() {
                    TokenKind::Number => {
                        self.bump()?;
                        let n = self.bump()?;
                        let src = self.consume_optional_fractional(self.text(n));
                        return parse_number_literal(&self.emit, &src, true);
                    }
                    TokenKind::Dot => {
                        // `-.<digits>` — leading-dot float. Peek one
                        // ahead to confirm `<digits>` actually follows;
                        // otherwise fall through to unary-minus.
                        if let Some(num) = self.consume_signed_dot_float(true)? {
                            return Ok(num);
                        }
                    }
                    TokenKind::Keyword(Kw::Inf) => {
                        // cpp 1.3.45's `VISIT(NumberLiteral)` lowercases
                        // the `(PLUS|DASH)? INF` text, strips a leading
                        // `+`, then string-compares: `-inf` / `-infinity`
                        // → "-Infinity"; `inf` / `infinity` → "Infinity".
                        // The INF lexer token only ever matches `inf` /
                        // `infinity`, so a signed-DASH INF is always
                        // "-Infinity" (no NaN fallback reachable here).
                        self.bump()?;
                        self.bump()?;
                        return Ok(self.emit.constant_special_number("-Infinity"));
                    }
                    TokenKind::Keyword(Kw::Nan) => {
                        // -NaN is still NaN — match the C++ behaviour of
                        // emitting "NaN".
                        self.bump()?;
                        self.bump()?;
                        return Ok(self.emit.constant_special_number("NaN"));
                    }
                    _ => {}
                }
                self.bump()?;
                let rhs = self.parse_expr_bp(BP_UNARY_MINUS)?;
                Ok(self
                    .emit
                    .arith(self.emit.constant(self.emit.int(0)), "-", rhs))
            }
            TokenKind::Plus => {
                // `+` is only a sign on a `numberLiteral` per grammar
                // (`(PLUS | DASH)? (floatingLiteral | … | INF |
                // NAN_SQL)`). There is no general unary-plus rule on
                // columnExpr, so `+a`, `+f(x)`, `+(a)` etc. should all
                // reject — only the numeric / INF / NAN forms below are
                // valid.
                match self.peek_next() {
                    TokenKind::Number => {
                        self.bump()?;
                        let n = self.bump()?;
                        let src = self.consume_optional_fractional(self.text(n));
                        parse_number_literal(&self.emit, &src, false)
                    }
                    TokenKind::Dot => {
                        if let Some(num) = self.consume_signed_dot_float(false)? {
                            return Ok(num);
                        }
                        Err(self.err("unary `+` only applies to a number literal"))
                    }
                    TokenKind::Keyword(Kw::Inf) => {
                        // cpp 1.3.45 strips a leading `+` before the
                        // text-equality check, so `+inf` → "inf" and
                        // `+infinity` → "infinity" — both → "Infinity".
                        self.bump()?;
                        self.bump()?;
                        Ok(self.emit.constant_special_number("Infinity"))
                    }
                    TokenKind::Keyword(Kw::Nan) => {
                        self.bump()?;
                        self.bump()?;
                        Ok(self.emit.constant_special_number("NaN"))
                    }
                    _ => Err(self.err("unary `+` only applies to a number literal")),
                }
            }
            TokenKind::Keyword(Kw::Not) => {
                // `NOT <X>` competes between three grammar rules:
                //   ColumnExprFunction:   not(args) - cpp Call('not', args)
                //   ColumnExprNot:        NOT <expr> - cpp Not(<expr>)
                //   parens-arrow lambda primary with NOT as param name
                //     (per the `keyword` rule).
                //
                // ANTLR prefers ColumnExprFunction (line 236) when the
                // parens content is a valid columnExprList. It backtracks
                // to ColumnExprNot only when ColumnExprFunction can't
                // fit — the content is a SELECT/WITH/placeholder-set-op
                // selectSetStmt, OR the parens are part of a parens-arrow
                // lambda head with `->` after the matching `)`.
                //
                // Bounded probes detect those two cases (cheaper than a
                // try_alt with an expr-parse for the false-positive case
                // `not ((a,) -> 1)` where the lambda is fully wrapped in
                // outer parens — function-call form, not NOT-prefix).
                if self.peek_next() == TokenKind::LParen
                    && (self.parens_open_select_or_set_stmt()
                        || self.parens_followed_by_arrow()
                        || self.parens_open_self_contained_columns_expr())
                {
                    self.bump()?; // NOT
                    let rhs = self.parse_expr_bp(BP_NOT)?;
                    return Ok(self.emit.not_(rhs));
                }
                if self.peek_next() == TokenKind::LParen {
                    return self.parse_ident_lead();
                }
                // `NOT -> body` is a single-arg arrow lambda with NOT
                // as the parameter name (the `keyword` rule admits NOT
                // as identifier). The single-arg lambda primary at
                // parse_prefix only fires for Ident; route the keyword
                // case here so the lambda head consumes both NOT and
                // the Arrow.
                if self.peek_next() == TokenKind::Arrow {
                    return self.parse_single_arg_arrow_lambda();
                }
                // Bare `NOT` followed by a token that can't start an
                // expression (alias / list-terminator / EOF) is the
                // identifier "not" — cpp's `keyword` rule admits NOT
                // as an identifier and falls back to a Field. Without
                // this check, parse_prefix would eagerly consume NOT
                // and then error on the unexpected following token.
                if matches!(
                    self.peek_next(),
                    TokenKind::Keyword(Kw::As)
                        | TokenKind::Comma
                        | TokenKind::RParen
                        | TokenKind::RBracket
                        | TokenKind::RBrace
                        | TokenKind::Eof
                        // Postfix operators that take Field as LHS:
                        // `not ?. x`, `not .x`, `not :: type` — cpp's
                        // ALL(*) reads NOT as the LHS Field rather than
                        // a unary prefix here.
                        | TokenKind::NullProperty
                        | TokenKind::Dot
                        | TokenKind::DoubleColon
                        // *Pure* binary operators (other than `+`/`-`,
                        // which double as unary prefixes) that need a
                        // LHS: NOT becomes a Field identifier and the
                        // operator joins it to its RHS. Note this set
                        // excludes IS / BETWEEN / IN / LIKE / ILIKE:
                        // those keywords are also valid `identifier`s,
                        // so at expression start cpp reads `NOT` as the
                        // unary prefix and the keyword as a Field
                        // operand (`not like` → `Not(Field('like'))`,
                        // `not in(1,2)` → `Not(Call('in', …))`). The
                        // genuine `x NOT IN y` infix form has a real
                        // LHS and is handled by the Pratt loop instead.
                        | TokenKind::Nullish
                        | TokenKind::Concat
                        | TokenKind::EqDouble
                        | TokenKind::EqSingle
                        | TokenKind::NotEq
                        | TokenKind::Lt
                        | TokenKind::LtEq
                        | TokenKind::Gt
                        | TokenKind::GtEq
                        | TokenKind::RegexSingle
                        | TokenKind::RegexDouble
                        | TokenKind::IRegexSingle
                        | TokenKind::IRegexDouble
                        | TokenKind::NotRegex
                        | TokenKind::NotIRegex
                        | TokenKind::Slash
                        | TokenKind::Percent
                        // `not := value` — NamedArgument with NOT as the
                        // parameter name (the `keyword` rule admits NOT
                        // as an identifier). parse_ident_lead handles
                        // the `:=` postfix.
                        | TokenKind::ColonEquals
                ) {
                    return self.parse_ident_lead();
                }
                // `not <kw-infix> <rhs>`: cpp's ALL(*) prefers
                // `Field([not]) <kw-infix> <rhs>` over `Not(Field([kw]))`
                // when the infix has a valid trailing RHS. `not like 'a'`
                // → `Compare(Field(not), "like", 'a')`, but `not like`
                // alone → `Not(Field(like))`. Probe the post-keyword
                // token to decide. Applies to LIKE / ILIKE / BETWEEN
                // (which take an expression on the right) and IS
                // (which takes NULL / NOT NULL / DISTINCT FROM).
                if matches!(
                    self.peek_next(),
                    TokenKind::Keyword(Kw::Like | Kw::Ilike | Kw::Between)
                ) {
                    let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                    if let Ok(after) = probe.next_token() {
                        if !matches!(
                            after.kind,
                            TokenKind::Eof
                                | TokenKind::Comma
                                | TokenKind::RParen
                                | TokenKind::RBracket
                                | TokenKind::RBrace
                                | TokenKind::Semicolon
                                // `NOT ilike(args)` / `NOT like(a, b)` /
                                // `NOT between(a, b, c)` are function-call
                                // forms — cpp treats the `(args)` as a
                                // Call (ANTLR's `ColumnExprFunction` alt
                                // wins because the keyword reads as an
                                // identifier function-name), so NOT
                                // applies as a unary prefix to the whole
                                // call: `Not(Call(ilike, [a, b]))`.
                                // Treating LParen as a "terminator" here
                                // keeps the unary-NOT path so we recurse
                                // into parse_ident_lead → Call rather
                                // than falling through to the binary
                                // `Field(not) NOT-ILIKE rhs` interpretation.
                                | TokenKind::LParen
                        ) {
                            return self.parse_ident_lead();
                        }
                    }
                }
                if matches!(self.peek_next(), TokenKind::Keyword(Kw::Is)) {
                    let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                    if let Ok(after) = probe.next_token() {
                        if matches!(
                            after.kind,
                            TokenKind::Keyword(Kw::Null)
                                | TokenKind::Keyword(Kw::Not)
                                | TokenKind::Keyword(Kw::Distinct)
                        ) {
                            return self.parse_ident_lead();
                        }
                    }
                }
                // `not * <rhs>`: cpp picks unary-NOT when `* <rhs>` is a
                // valid columnExpr (i.e. `*` is a complete primary
                // Field('*') and what follows is a postfix op, infix op,
                // EXCLUDE/COLUMNS decoration, or an expression
                // terminator). Otherwise (`*` followed by a primary atom
                // like a Number / Ident / String / primary keyword) it's
                // multiplication and NOT becomes a Field. Probe one more
                // token past the `*` to disambiguate.
                if self.peek_next() == TokenKind::Asterisk
                    && !self.asterisk_after_not_starts_columnexpr()
                {
                    return self.parse_ident_lead();
                }
                // `NOT AND <expr>` / `NOT OR <expr>` — when a binary
                // boolean keyword has a real RHS, cpp's ALL(*) reads
                // NOT as the LHS Field and the keyword as the binary
                // op (the unary-NOT path would leave the RHS trailing).
                // Probe one more token via the shadow lexer; only flip
                // to identifier-NOT when the third token can begin an
                // expression.
                if matches!(
                    self.peek_next(),
                    TokenKind::Keyword(Kw::And) | TokenKind::Keyword(Kw::Or)
                ) {
                    let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                    if let Ok(t) = probe.next_token() {
                        if peek_can_start_clause_body(t.kind) {
                            return self.parse_ident_lead();
                        }
                    }
                }
                // `NOT IGNORE NULLS …`: cpp's ANTLR reads NOT as a
                // Field (via the `keyword` rule), then the
                // `ColumnExprIgnoreNulls` postfix (`<expr> IGNORE
                // NULLS`) consumes-and-drops the IGNORE NULLS pair on
                // the resulting Field. Without this flip, the
                // unary-NOT path would consume NOT, then the inner
                // recursion would parse `ignore` as a Field and leave
                // `nulls` as a trailing reserved keyword (rust would
                // then reject; cpp accepts because Field-then-postfix
                // is the only complete parse).
                //
                // Distinguishing IGNORE NULLS (pair) from a bare
                // `NOT IGNORE` (single Field) requires a 3-token
                // peek: only flip when the third token is NULLS.
                // RESPECT NULLS is grammar-parallel but cpp doesn't
                // actually accept `NOT RESPECT NULLS . ...`
                // (rejected with "mismatched input 'nulls'") — so
                // the flip only fires for IGNORE.
                if self.peek_next() == TokenKind::Keyword(Kw::Ignore) {
                    let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                    if matches!(
                        probe.next_token().map(|t| t.kind),
                        Ok(TokenKind::Keyword(Kw::Nulls))
                    ) {
                        return self.parse_ident_lead();
                    }
                }
                self.bump()?;
                let rhs = self.parse_expr_bp(BP_NOT)?;
                Ok(self.emit.not_(rhs))
            }
            _ => {
                // `<Tag ...>` — HogQLX tag in column position (cpp's
                // `ColumnExprTagElement` alt). Distinguish from `<`
                // comparison by peek_next: a tag's first inner token
                // is an identifier (or keyword-as-ident); a `<` infix
                // doesn't reach this prefix branch in the first place
                // (it fires later via `infix_bp`).
                if self.peek_starts_hogqlx_tag() {
                    return self.parse_hogqlx_tag_element();
                }
                self.parse_primary()
            }
        }
    }

    fn parse_primary(&mut self) -> Result<E::Value, ParseError> {
        let tok = self.peek0;
        match tok.kind {
            TokenKind::Number => {
                self.bump()?;
                let src = self.consume_optional_fractional(self.text(tok));
                Ok(parse_number_literal(&self.emit, &src, false)?)
            }
            // `.<digits>` — bare-decimal float per the grammar's
            // `floatingLiteral: DOT (DECIMAL_LITERAL | ...)`.
            TokenKind::Dot if matches!(self.peek_next(), TokenKind::Number) => {
                self.bump()?;
                let n = self.bump()?;
                let src = format!(".{}", self.text(n));
                Ok(parse_number_literal(&self.emit, &src, false)?)
            }
            TokenKind::String => {
                self.bump()?;
                Ok(self
                    .emit
                    .constant(self.emit.string(&unquote_single_string(self.text(tok)))))
            }
            TokenKind::TemplateString => {
                // Lexer captured the whole `f'…'` or `F'…'` span. The
                // grammar has two distinct tokens:
                //   `QUOTE_SINGLE_TEMPLATE: 'f\'' -> pushMode(IN_TEMPLATE_STRING);`
                //   `QUOTE_SINGLE_TEMPLATE_FULL: 'F\'' -> pushMode(IN_FULL_TEMPLATE_STRING);`
                // The lowercase `f'` is the regular template string —
                // valid as a `columnExpr` per the `templateString` rule.
                // The uppercase `F'` is the "full" template-string-only
                // form reached only from `fullTemplateString` (an
                // entry-rule for `parse_string_template`); it is *not*
                // a `columnExpr`. Reject it here.
                let raw = self.text(tok);
                debug_assert!(raw.len() >= 3 && (raw.starts_with("f'") || raw.starts_with("F'")));
                if raw.starts_with("F'") {
                    return Err(self.err("mismatched input 'F''"));
                }
                let body_offset = tok.start + 2; // past `f'`
                let body_end = tok.end - 1; // before closing `'`
                self.bump()?;
                parse_template_body(&self.emit, self.src, body_offset, body_end)
            }
            TokenKind::Keyword(Kw::True | Kw::False)
                if self.peek_next() == TokenKind::LParen || self.peek_next() == TokenKind::Dot =>
            {
                // `true`/`false` are not lexer tokens in the grammar —
                // they are ordinary identifiers, and become Bool
                // Constants only as a bare `columnIdentifier`. cpp
                // treats them as identifiers in two columnExpr-leading
                // postfix positions:
                //   `true(…)`     → Call(name='true')          (function call)
                //   `true.x`      → Field(['true', 'x'])       (chain)
                // The Pratt loop would otherwise wrap a `Constant(true)`
                // in an `ArrayAccess` for the `.x`, diverging from cpp's
                // Field shape. Route both shapes through ident-lead so
                // the chain accumulates correctly. `null` differs —
                // `NULL` is a real keyword, so `null(…)` stays an
                // `ExprCall` on the Null constant.
                self.parse_ident_lead()
            }
            TokenKind::Keyword(Kw::True) => {
                self.bump()?;
                Ok(self.emit.constant(self.emit.bool(true)))
            }
            TokenKind::Keyword(Kw::False) => {
                self.bump()?;
                Ok(self.emit.constant(self.emit.bool(false)))
            }
            TokenKind::Keyword(Kw::Null) => {
                self.bump()?;
                Ok(self.emit.constant(self.emit.null()))
            }
            TokenKind::Keyword(Kw::Inf) => {
                // cpp 1.3.45's `VISIT(NumberLiteral)` maps both `inf`
                // and `infinity` (the two spellings the INF lexer token
                // matches, any case) to "Infinity". (Pre-1.3.45 cpp
                // collapsed bare `infinity` to NaN — that's been fixed
                // upstream, so unsigned INF is unconditionally Infinity.)
                self.bump()?;
                Ok(self.emit.constant_special_number("Infinity"))
            }
            TokenKind::Keyword(Kw::Nan) => {
                self.bump()?;
                Ok(self.emit.constant_special_number("NaN"))
            }

            // CASE/CAST/TRY_CAST/INTERVAL/LAMBDA — special grammar
            // forms when followed by their expected continuation; bare
            // (no continuation) parses as a Field identifier per cpp's
            // `keyword`-fallthrough rule.
            TokenKind::Keyword(Kw::Case)
                if can_start_case_body(self.peek_next())
                    // Skip when peek_next is empty `()` UNLESS the `()` is a
                    // lambda head — `case () -> 1 when ... end` is valid in
                    // cpp because `() -> 1` is the case's value expression.
                    && !(self.peek_next() == TokenKind::LParen
                        && self.peek_lparen_is_empty()
                        && !self.parens_followed_by_arrow())
                    && !(self.peek_next() == TokenKind::LParen
                        && self.peek_lparen_starts_with_order_or_distinct()) =>
            {
                // `case(args)` (no WHEN) is a regular function call —
                // cpp falls back to ColumnExprFunction via the keyword
                // rule. try_alt: parse_case_expr first; if it bails
                // (typically "requires at least one WHEN"), retry as
                // ident_lead so the function-call path picks up.
                self.try_alt(&[&Self::parse_case_expr, &Self::parse_ident_lead])
            }
            // Grammar (lines 208-209): CAST/TRY_CAST special form
            // `LPAREN columnExpr AS columnTypeExpr RPAREN` vs the
            // function-call alternative `cast(args)` per the keyword
            // rule. The disambiguator is `AS` at the outer paren's
            // depth, which `parse_cast_expr` checks for naturally as
            // it consumes the body — when it fails (no AS, or the
            // body doesn't fit `columnExpr AS columnTypeExpr`),
            // try_alt rolls back and reroutes through `parse_ident_lead`
            // so CAST becomes a Field. Fast-path: skip the try when
            // peek_next isn't `(` or is empty `()` — neither form fits
            // the CAST special form, so the ident-lead path is the
            // only option.
            TokenKind::Keyword(Kw::Cast) | TokenKind::Keyword(Kw::TryCast)
                if self.peek_next() == TokenKind::LParen && !self.peek_lparen_is_empty() =>
            {
                let is_try = matches!(self.peek(), TokenKind::Keyword(Kw::TryCast));
                self.try_alt(&[&|p| p.parse_cast_expr(is_try), &Self::parse_ident_lead])
            }
            // ColumnExprInterval (`INTERVAL columnExpr interval-unit`) vs
            // ColumnExprFunction (`interval LPAREN args RPAREN ...`). cpp's
            // ANTLR ALL(*) tries both and picks the longest match: with a
            // valid unit at end it's INTERVAL, otherwise the keyword falls
            // back to identifier and parses as a function call (which also
            // covers `interval(distinct …)`, `interval(a, b) within group …`,
            // `interval(a, b) over …`, and the empty `interval()` no-args
            // form). Mirror with `try_alt`.
            TokenKind::Keyword(Kw::Interval) if can_start_interval_value(self.peek_next()) => {
                self.try_alt(&[&Self::parse_interval_expr, &Self::parse_ident_lead])
            }
            // Grammar (line 289): LAMBDA identifier (COMMA identifier)* COMMA? COLON columnExpr
            // vs the keyword rule's "LAMBDA as identifier in primary position."
            // Try the lambda form first; if it fails (no params, no `:`,
            // or malformed body header), `try_alt` rolls back to the
            // ident-lead path and LAMBDA becomes a Field.
            TokenKind::Keyword(Kw::Lambda) => {
                self.try_alt(&[&Self::parse_lambda_keyword, &Self::parse_ident_lead])
            }
            // CAST / TRY_CAST without `(<expr> AS …)` shape, plus CASE
            // / INTERVAL / SELECT when their own special-form guards
            // didn't fire. `SELECT` is here because cpp's `keyword`
            // rule admits it as a function-call name, e.g. `select(1)`;
            // subquery dispatch happens at parse_paren_or_tuple where
            // the leading `(` is consumed BEFORE parse_primary sees
            // SELECT.
            TokenKind::Keyword(Kw::Case)
            | TokenKind::Keyword(Kw::Cast)
            | TokenKind::Keyword(Kw::TryCast)
            | TokenKind::Keyword(Kw::Interval)
            | TokenKind::Keyword(Kw::Select) => self.parse_ident_lead(),
            // `COLUMNS(...)` is the ColumnsExpr keyword form; bare
            // `columns` (no `(`) is accepted by the grammar as a
            // plain identifier per the `keyword` rule. Route to the
            // ident-lead path so it ends up as a Field, matching cpp.
            //
            // Empty `columns()` is *not* a columns-expr — none of the
            // columns-special grammar rules admit an empty inner. cpp's
            // ANTLR backs off to ColumnExprFunction (Call with no
            // parametric, empty args). Skip the columns-expr dispatch
            // in that case so it falls through to ident-lead.
            //
            // `columns(...) OVER ...` — the trailing OVER tail means
            // cpp's ANTLR pivots to the window-function alt with
            // `columns` as the function name (not the ColumnsExpr
            // spread-companion). Route to ident-lead so the
            // function-call path picks up the OVER postfix.
            //
            // `columns(ORDER BY …)` / `columns(DISTINCT …)` — same
            // routing: an ORDER BY or DISTINCT at the head of the
            // parens belongs to the function-call form's argument
            // list (cpp's `ColumnExprFunction` with the `DISTINCT?`
            // and `orderByClause?` slots), not the COLUMNS spread.
            // Falling through to ident-lead here matches cpp's
            // ColumnExprFunction-over-ColumnExprColumns preference
            // when the inner has those function-only tokens.
            TokenKind::Keyword(Kw::Columns)
                if self.peek_next() == TokenKind::LParen
                    && !self.peek_lparen_is_empty()
                    && !self.peek_columns_paren_followed_by_over() =>
            {
                // ColumnsExpr (`ColumnExprColumnsList` etc.) vs the
                // plain function-call form (`columns(args)` → Call) is
                // an ALL(*) ambiguity. cpp's ANTLR tries `ColumnsList`
                // first and backs off to `ColumnExprFunction` only when
                // the paren content can't parse as a `columnExprList`:
                //   - `columns(DISTINCT (a, b))` → ColumnsExpr —
                //     `distinct` is a soft-keyword Field and `(a, b)` a
                //     postfix call, so the content IS one columnExpr.
                //   - `columns(distinct x)` → Call — `distinct x` is
                //     two bare idents with no operator between, NOT a
                //     columnExpr; DISTINCT is the call distinct-marker.
                //   - `columns(ORDER BY 1)` → Call — `ORDER BY` can't
                //     open a columnExpr; it's the call's orderByClause.
                // Mirror with `try_alt`: parse_columns_expr first (it
                // `expect`s the closing `)`, so a non-columnExprList
                // body fails cleanly and rolls back), ident-lead next.
                self.try_alt(&[&Self::parse_columns_expr, &Self::parse_ident_lead])
            }
            // `TRIM (LEADING|TRAILING|BOTH 'str' FROM expr)` — special
            // syntax form that rewrites to `Call("trimLeft"|"trimRight"|
            // "trim", [expr, str])`. A leading directional keyword only
            // makes the special form *possible*: `LEADING` / `TRAILING`
            // / `BOTH` are also valid `keyword`-rule identifiers, so
            // `trim(leading)` is a plain call. try_alt the special form
            // first, then fall back to the `trim(args)` call.
            TokenKind::Keyword(Kw::Trim)
                if self.peek_next() == TokenKind::LParen && self.is_trim_keyword_form() =>
            {
                self.try_alt(&[&Self::parse_trim_keyword_form, &Self::parse_ident_lead])
            }

            TokenKind::Hash => self.parse_positional(),

            TokenKind::LParen => self.parse_paren_or_lambda(),
            TokenKind::LBracket => self.parse_array_literal(),
            TokenKind::LBrace => self.parse_brace_dict_or_placeholder(),
            // `ARRAY [ … ]` — the optional-keyword form of the array
            // literal per the grammar's `ARRAY? LBRACKET columnExprList?
            // RBRACKET` alt. Strip the keyword and delegate to the
            // bracket-only path so both shapes produce the same Array node.
            TokenKind::Keyword(Kw::Array) if self.peek_next() == TokenKind::LBracket => {
                self.bump()?;
                self.parse_array_literal()
            }
            // Bare `*` at primary position is the columns-asterisk form, which
            // can carry `EXCLUDE (...)` / `REPLACE (...)` decorations.
            TokenKind::Asterisk => self.parse_top_level_asterisk(),

            // Single-identifier arrow lambda: `x -> body`.
            TokenKind::Ident if self.peek_next() == TokenKind::Arrow => {
                self.parse_single_arg_arrow_lambda()
            }

            TokenKind::Ident | TokenKind::QuotedIdent => self.parse_ident_lead(),

            // Almost every keyword can stand in for an identifier in
            // expression positions per the grammar's `identifier` rule.
            // The `kw_acts_as_ident_in_primary` predicate filters out the
            // few that would shadow primary forms (e.g. `case`, `select`).
            TokenKind::Keyword(k) if kw_acts_as_ident_in_primary(k) => self.parse_ident_lead(),

            // Orphan `}` outside any brace-grouping: cpp's lexer emits
            // a specific "Unmatched curly bracket" error here.
            TokenKind::RBrace => Err(self.err("Unmatched curly bracket")),
            _ => Err(self.err(format!("unexpected token in expression: {:?}", tok.kind))),
        }
    }

    // ====================================================================
    // Primary-form helpers
    // ====================================================================

    /// `CASE [scrutinee] WHEN c1 THEN r1 [WHEN c2 THEN r2 ...] [ELSE r] END`
    /// rewrites to `Call("if"|"multiIf"|"transform", ...)` per the C++
    /// visitor's [`VISIT(ColumnExprCase)`] logic.
    fn parse_case_expr(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Case, "CASE")?;
        // Optional scrutinee. The simple case (peek != WHEN) parses
        // greedy and uses the result. The WHEN-first case is more
        // subtle: cpp's ANTLR ALL(*) prefers the WITH-scrutinee alt
        // whenever the greedy columnExpr starting with `when` as a
        // soft identifier can extend through an infix operator into
        // a full expression AND land on a real WHEN keyword for the
        // CASE-WHEN structure that follows. Speculatively try the
        // scrutinee alt; commit only when it consumed beyond a bare
        // `when` Field AND peek lands on WHEN.
        //
        // Examples:
        //   `case when * then(1)() when 2 then 3 end`
        //     → scrutinee = Mul(Field(when), Call(then, [1])).
        //     CASE-WHEN follows: `when 2 then 3 end`. transform.
        //   `case when 1 then 2 when 3 then 4 end`
        //     → speculation returns bare Field(when) at peek=`1`; not
        //     WHEN, so roll back. No scrutinee. multiIf.
        let scrutinee = if self.peek() != TokenKind::Keyword(Kw::When) {
            Some(self.parse_expr_bp(0)?)
        } else {
            let cp = self.checkpoint();
            match self.parse_expr_bp(0) {
                Ok(s)
                    if self.peek() == TokenKind::Keyword(Kw::When)
                        && !is_bare_field(&self.emit, &s) =>
                {
                    Some(s)
                }
                _ => {
                    self.restore(cp)?;
                    None
                }
            }
        };
        let mut whens: Vec<E::Value> = Vec::new();
        let mut thens: Vec<E::Value> = Vec::new();
        while self.eat_kw(Kw::When)? {
            whens.push(self.parse_expr_bp(0)?);
            self.expect_kw(Kw::Then, "THEN")?;
            thens.push(self.parse_expr_bp(0)?);
        }
        if whens.is_empty() {
            return Err(self.err("CASE expression requires at least one WHEN"));
        }
        let else_branch = if self.eat_kw(Kw::Else)? {
            Some(self.parse_expr_bp(0)?)
        } else {
            None
        };
        self.expect_kw(Kw::End, "END")?;

        if let Some(scrut) = scrutinee {
            // `case S when v then r [else d] end` → `transform(S,
            // [whens], [thens], else)`. The cpp visitor builds a flat
            // column list and unconditionally treats the LAST item as
            // the else-position default — so when ELSE is omitted, the
            // final THEN value migrates into the else slot and the
            // `thens` array loses its last element. Mirror that quirk
            // exactly:
            //
            //   case S when v then r end         → transform(S, [v], [], r)
            //   case S when v then r else d end  → transform(S, [v], [r], d)
            //   case S when v1 then r1 when v2 then r2 end
            //                                    → transform(S, [v1, v2], [r1], r2)
            let mut flat: Vec<E::Value> = Vec::with_capacity(whens.len() * 2 + 2);
            for (w, t) in whens.into_iter().zip(thens) {
                flat.push(w);
                flat.push(t);
            }
            if let Some(d) = else_branch {
                flat.push(d);
            }
            let else_arg = flat
                .pop()
                .unwrap_or_else(|| self.emit.constant(self.emit.null()));
            let mut whens_arr: Vec<E::Value> = Vec::new();
            let mut thens_arr: Vec<E::Value> = Vec::new();
            for (i, col) in flat.into_iter().enumerate() {
                if i % 2 == 0 {
                    whens_arr.push(col);
                } else {
                    thens_arr.push(col);
                }
            }
            return Ok(self.emit.call(
                "transform",
                vec![
                    scrut,
                    self.emit.array_(whens_arr),
                    self.emit.array_(thens_arr),
                    else_arg,
                ],
            ));
        }

        // No scrutinee. Build the flat column list the C++ visitor
        // sees: when/then pairs interleaved, optionally followed by
        // the ELSE value. The visitor dispatches purely on length:
        //   3 items → `if(c, r, d)`
        //   anything else → `multiIf(...)`
        // Notably an implicit-NULL else is NOT synthesised here, so
        // `case when c then r end` produces `multiIf(c, r)`, not
        // `if(c, r, null)`.
        let mut columns: Vec<E::Value> = Vec::with_capacity(whens.len() * 2 + 1);
        for (w, t) in whens.into_iter().zip(thens) {
            columns.push(w);
            columns.push(t);
        }
        if let Some(d) = else_branch {
            columns.push(d);
        }
        if columns.len() == 3 {
            Ok(self.emit.call("if", columns))
        } else {
            Ok(self.emit.call("multiIf", columns))
        }
    }

    /// `CAST(expr AS type)` / `TRY_CAST(expr AS type)`.
    fn parse_cast_expr(&mut self, is_try: bool) -> Result<E::Value, ParseError> {
        self.bump()?; // consume CAST / TRY_CAST
        self.expect(TokenKind::LParen, "(")?;
        // cpp grammar: `castFunction: CAST LPAREN columnExpr AS
        // columnTypeExpr RPAREN`. columnExpr greedily absorbs Alias
        // forms (`expr AS ident`), so when the argument itself carries
        // aliases the AS that belongs to CAST is the *last* AS at
        // paren-depth zero before the matching `)`. Pre-scan to find
        // that position and gate the AS-infix on it for the inner
        // parse. `parse_expr_bp(0)` then naturally consumes the
        // earlier aliases as Alias nodes and stops before the CAST AS.
        let cast_as_pos = self.find_cast_separator_pos()?;
        let prev_stop = std::mem::replace(&mut self.cast_as_stop, cast_as_pos);
        let expr_result = self.parse_expr_bp(0);
        self.cast_as_stop = prev_stop;
        let expr = expr_result?;
        self.expect_kw(Kw::As, "AS")?;
        let type_name = self.parse_type_expr()?;
        self.expect(TokenKind::RParen, ")")?;
        if is_try {
            Ok(self.emit.try_cast(expr, &type_name))
        } else {
            Ok(self.emit.type_cast(expr, &type_name))
        }
    }

    /// Scan forward from the current position to find the matching
    /// close paren for the enclosing CAST, returning the byte offset
    /// of the *last* `AS` keyword at paren-depth zero before it. The
    /// scan uses a shadow lexer so it does not advance our own cursor.
    /// Returns `None` if no AS is found (degenerate input — the parser
    /// will error on the missing AS later).
    fn find_cast_separator_pos(&self) -> Result<Option<usize>, ParseError> {
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let mut depth: i32 = 0;
        let mut last_as: Option<usize> = None;
        loop {
            let tok = probe.next_token()?;
            match tok.kind {
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    if depth == 0 {
                        break;
                    }
                    depth -= 1;
                }
                TokenKind::Keyword(Kw::As) if depth == 0 => {
                    last_as = Some(tok.start);
                }
                TokenKind::Eof => break,
                _ => {}
            }
        }
        Ok(last_as)
    }

    /// Like `find_cast_separator_pos`, but for a `columnsReplaceItem`
    /// (`columnExpr AS identifier`) inside a `REPLACE (…)` list. The
    /// `identifier` replacement name is the item's *last* token and the
    /// separator `AS` is the token immediately before it. The last
    /// `AS`-token of the item is NOT a reliable separator: the name can
    /// itself be the keyword `as` (`a AS as`), so the trailing `Kw::As`
    /// is the name, not the separator.
    ///
    /// The item terminates at a depth-0 `)` / `]` / `}` or — once the
    /// item has shown an `AS` — a depth-0 `,`. The `AS`-gate keeps the
    /// scan blind to lambda-parameter commas: `lambda x, y : …` and the
    /// bare `a, b -> …` arrow form place their commas before the item's
    /// `AS`, so they are treated as internal rather than as a boundary.
    fn find_replace_item_as_pos(&self) -> Result<Option<usize>, ParseError> {
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let mut depth: i32 = 0;
        let mut seen_as = false;
        let mut prev_start: Option<usize> = None;
        let mut last_start: Option<usize> = None;
        loop {
            let tok = probe.next_token()?;
            let terminator = match tok.kind {
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace if depth == 0 => true,
                TokenKind::Comma if depth == 0 && seen_as => true,
                TokenKind::Eof => true,
                _ => false,
            };
            if terminator {
                break;
            }
            match tok.kind {
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => depth -= 1,
                TokenKind::Keyword(Kw::As) if depth == 0 => seen_as = true,
                _ => {}
            }
            prev_start = last_start;
            last_start = Some(tok.start);
        }
        // The separator `AS` is the second-to-last token of the item.
        Ok(prev_start)
    }

    /// `INTERVAL <expr> <unit>` or `INTERVAL '<n> <unit>'`. Both forms
    /// rewrite to `Call("toInterval<Unit>", [expr])` per the C++ visitor.
    fn parse_interval_expr(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Interval, "INTERVAL")?;
        // `INTERVAL '5 day'` — a single string literal carrying both
        // count and unit. Only take this branch when the string is the
        // *entire* interval value: if a unit keyword follows the
        // string, cpp uses the string as the expr in the
        // `INTERVAL <expr> <unit>` form (e.g. `interval '1' hour` →
        // `Call(toIntervalHour, [Constant("1")])`).
        //
        // Also: only commit to the combined-string form when the string
        // contains a space. cpp's ALL(*) backtracks to expr+unit when
        // the string can't be split (e.g. `interval 'ef' … month` —
        // 'ef' is the start of a longer expression and `month` is the
        // unit). The literal-only `interval 'ef'` form errors in cpp
        // too, so falling through here doesn't mask any acceptances.
        if matches!(self.peek(), TokenKind::String) && !self.peek_next_is_interval_unit() {
            let str_tok = self.peek0;
            let raw = unquote_single_string(self.text(str_tok));
            if let Some((count_str, unit)) = raw.split_once(' ') {
                // cpp's `visitColumnExprIntervalString` requires the
                // count to be a non-negative decimal integer (`isdigit`
                // per char, `stoi` for the convert), and matches the
                // unit against a literal-lowercase set (so `SECOND`
                // rejects with "Unsupported interval unit: SECOND").
                // Rust used to lowercase the unit and silently
                // substitute `Constant(0)` for any unparseable count
                // — `INTERVAL 'twenty days'` quietly became "0 days".
                let count_valid =
                    !count_str.is_empty() && count_str.bytes().all(|b| b.is_ascii_digit());
                if !count_valid {
                    self.bump()?;
                    return Err(ParseError::not_implemented_fatal(
                        format!("Unsupported interval count: {count_str}"),
                        str_tok.start,
                        str_tok.end,
                    ));
                }
                let count: i64 = match count_str.parse() {
                    Ok(n) => n,
                    Err(_) => {
                        self.bump()?;
                        return Err(ParseError::not_implemented_fatal(
                            "Unknown error: stoi: out of range",
                            str_tok.start,
                            str_tok.end,
                        ));
                    }
                };
                // cpp's unit check is literal-lowercase — case-sensitive
                // against the lowercase singular / plural forms. Match
                // that here rather than `interval_call_name`'s
                // case-insensitive helper.
                let unit_name = interval_call_name_case_sensitive(unit);
                if let Some(unit_name) = unit_name {
                    self.bump()?;
                    return Ok(self
                        .emit
                        .call(unit_name, vec![self.emit.constant(self.emit.int(count))]));
                }
                // Unit not lowercase / not recognised — cpp errors
                // here even though the count was valid.
                self.bump()?;
                return Err(ParseError::not_implemented_fatal(
                    format!("Unsupported interval unit: {unit}"),
                    str_tok.start,
                    str_tok.end,
                ));
            }
            // Fall through to the expr+unit form: parse the string as
            // the value expression and let the trailing unit keyword
            // close the INTERVAL.
        }
        // `INTERVAL <expr> <unit>` — the grammar admits a full
        // columnExpr for the value, so we parse at BP=0 (greedy).
        // The unit-keyword tokens (SECOND/MINUTE/…/YEAR) aren't binary
        // or postfix operators, so the Pratt loop naturally halts
        // before them. AND/OR/BETWEEN that surround the INTERVAL in
        // an outer expression bind correctly because the SECOND
        // keyword terminates the interval value before they're seen
        // — the outer call gets to those operators after parse_interval_expr
        // returns.
        let expr = self.parse_expr_bp(0)?;
        // The grammar's `interval` rule is the eight singular unit
        // *keyword* tokens (`SECOND | MINUTE | HOUR | DAY | WEEK |
        // MONTH | QUARTER | YEAR`, with `YYYY` lexed as `YEAR`). A
        // plural (`hours`) lexes as an identifier and an arbitrary
        // identifier / quoted identifier is never a unit — cpp rejects
        // all of those (`INTERVAL 1 hours`, `INTERVAL 1 "hour"`). The
        // plural-tolerant `INTERVAL '5 days'` form is the *string*
        // branch above, handled before this point.
        let unit_tok = self.bump()?;
        let unit_name = match unit_tok.kind {
            TokenKind::Keyword(
                Kw::Second
                | Kw::Minute
                | Kw::Hour
                | Kw::Day
                | Kw::Week
                | Kw::Month
                | Kw::Quarter
                | Kw::Year,
            ) => interval_call_name(self.text(unit_tok)).ok_or_else(|| {
                self.err(format!(
                    "unsupported INTERVAL unit: {}",
                    self.text(unit_tok)
                ))
            })?,
            _ => {
                return Err(self.err(format!(
                    "expected interval unit keyword, got {:?}",
                    unit_tok.kind
                )))
            }
        };
        Ok(self.emit.call(unit_name, vec![expr]))
    }

    /// Is `peek_next` a recognised INTERVAL unit keyword? Used by
    /// parse_interval_expr to decide between the combined-string form
    /// (`INTERVAL '5 day'`) and the expr-plus-unit form (`INTERVAL '1'
    /// HOUR`). When a unit keyword immediately follows the string,
    /// cpp treats the string as the value expression.
    fn peek_next_is_interval_unit(&self) -> bool {
        match self.peek_next() {
            TokenKind::Keyword(_) | TokenKind::Ident | TokenKind::QuotedIdent => {
                interval_call_name(self.text(self.peek1)).is_some()
            }
            _ => false,
        }
    }

    /// Is the current token a `WITH` that begins a `WITH (LOCAL)? TIME
    /// ZONE` type-cast suffix? Used by the `::` cast handler so a bare
    /// `WITH` (e.g. a trailing `WITH FILL` order-by modifier) is left
    /// for the enclosing clause rather than mis-parsed as a timezone
    /// type. Mirrors cpp's ALL(*) lookahead on `columnTypeCastExpr`.
    fn peek_is_with_time_zone(&self) -> bool {
        if !matches!(self.peek(), TokenKind::Keyword(Kw::With)) {
            return false;
        }
        // Resolve the TIME token and the byte offset just past it,
        // skipping an optional LOCAL right after WITH.
        let (time_kind, time_end) = match self.peek_next() {
            TokenKind::Keyword(Kw::Local) => {
                let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                match probe.next_token() {
                    Ok(t) => (t.kind, t.end),
                    Err(_) => return false,
                }
            }
            other => (other, self.peek1.end),
        };
        if !matches!(time_kind, TokenKind::Keyword(Kw::Time)) {
            return false;
        }
        let mut probe = Lexer::with_pos(self.src, time_end);
        matches!(
            probe.next_token().map(|t| t.kind),
            Ok(TokenKind::Keyword(Kw::Zone))
        )
    }

    /// Peek past `TRIM (` to check whether the next token is a
    /// directional keyword (LEADING / TRAILING / BOTH). If so, this is
    /// the special TRIM grammar form; otherwise it's a regular function
    /// call to a function literally named `trim`.
    fn is_trim_keyword_form(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        drop(probe.next_token()); // TRIM
        drop(probe.next_token()); // (
        match probe.next_token() {
            Ok(t) => matches!(
                t.kind,
                TokenKind::Keyword(Kw::Leading)
                    | TokenKind::Keyword(Kw::Trailing)
                    | TokenKind::Keyword(Kw::Both),
            ),
            Err(_) => false,
        }
    }

    fn parse_trim_keyword_form(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Trim, "TRIM")?;
        self.expect(TokenKind::LParen, "(")?;
        let name = if self.eat_kw(Kw::Leading)? {
            "trimLeft"
        } else if self.eat_kw(Kw::Trailing)? {
            "trimRight"
        } else if self.eat_kw(Kw::Both)? {
            "trim"
        } else {
            // Caller (parse_primary) only routes here when one of these
            // keywords is present, so this branch is unreachable.
            return Err(self.err("expected LEADING / TRAILING / BOTH after TRIM("));
        };
        // Trim substring: per grammar
        // `TRIM (LEADING|TRAILING|BOTH string FROM columnExpr)`, where
        // `string: STRING_LITERAL | templateString`. cpp rejects any
        // other expression (Field, Call, etc.) here. The earlier comment
        // claiming `string` resolves to columnExpr was wrong.
        if !matches!(self.peek(), TokenKind::String | TokenKind::TemplateString,) {
            return Err(self.err("TRIM substring must be a string literal or template string"));
        }
        let str_value = self.parse_expr_bp(0)?;
        self.expect_kw(Kw::From, "FROM")?;
        let expr = self.parse_expr_bp(0)?;
        self.expect(TokenKind::RParen, ")")?;
        // Args order matches the C++ visitor: expr first, then the trim
        // substring.
        Ok(self.emit.call(name, vec![expr, str_value]))
    }

    /// `lambda IDENT (, IDENT)* : body`. The body admits a bare-list
    /// arrow lambda (`a, b -> body`) as a full columnExpr, so we try
    /// that form first before falling back to the regular Pratt parse.
    fn parse_lambda_keyword(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Lambda, "lambda")?;
        let mut params: Vec<String> = Vec::new();
        loop {
            let t = self.bump()?;
            let name = match t.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => identifier_text(self.text(t), t.kind),
                // Lambda params route through the grammar's
                // `identifier` rule, which omits NULL / INF / NAN and
                // the Hog-statement keywords.
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                    identifier_text(self.text(t), t.kind)
                }
                _ => return Err(self.err(format!("expected lambda parameter, got {:?}", t.kind))),
            };
            params.push(name);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if self.peek() == TokenKind::Colon {
                break;
            }
        }
        self.expect(TokenKind::Colon, ":")?;
        let body = if let Some(inner) = self.try_bare_list_lambda()? {
            inner
        } else {
            self.parse_lambda_body()?
        };
        Ok(self.emit.lambda(params, body))
    }

    /// `COLUMNS('regex')` / `COLUMNS(expr, …)` / `COLUMNS(*)` with optional
    /// `EXCLUDE (…)` / `REPLACE (…)` decoration and an optional
    /// `IDENT.*` qualifier. Plus the leading-`ASTERISK COLUMNS(…)` spread
    /// forms. Covers the full ColumnExprColumns* family from the grammar.
    fn parse_columns_expr(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Columns, "COLUMNS")?;
        self.expect(TokenKind::LParen, "(")?;
        // Three shapes inside the parens:
        //   1. `'regex'` → ColumnsRegex
        //   2. `*` [EXCLUDE (...)] [REPLACE (...)]
        //   3. `ident DOT *` [EXCLUDE (...)] [REPLACE (...)]
        //   4. `expr_list` → ColumnsList
        let result = if matches!(self.peek(), TokenKind::String)
            && self.peek_next() == TokenKind::RParen
        {
            let str_tok = self.bump()?;
            let s = unquote_single_string(self.text(str_tok));
            self.emit.columns_expr(Some(s), None, false, None, None)
        } else if self.peek() == TokenKind::Asterisk
            && matches!(
                self.peek_next(),
                TokenKind::Keyword(Kw::Exclude) | TokenKind::Keyword(Kw::Replace)
            )
        {
            let asterisk_pos = self.peek0.start;
            self.bump()?;
            let (exclude, replace) = self.parse_columns_decorators()?;
            // ANTLR resolves `COLUMNS(* …)` against five alternatives in
            // declared order. The interesting split:
            //
            //   `COLUMNS(* EXCLUDE …)` only
            //     → matches `ColumnExprColumnsList` first because
            //       `ColumnExprAsterisk` admits a trailing EXCLUDE
            //       (line 288 of HogQLParser.g4). cpp wraps the asterisk
            //       columns-expr inside an outer `ColumnsExpr(columns=…)`.
            //
            //   `COLUMNS(* REPLACE …)`
            //   `COLUMNS(* EXCLUDE … REPLACE …)`
            //     → list path can't match (REPLACE isn't a valid trailing
            //       decoration on `ColumnExprAsterisk`), so ANTLR falls
            //       through to the specialised `ColumnExprColumnsReplace`
            //       / `…ExcludeReplace` rule, which returns the
            //       UNWRAPPED `ColumnsExpr(all_columns=True, …)` shape.
            //
            // Mirror that split here.
            if replace.is_some() {
                self.emit.columns_expr(None, None, true, exclude, replace)
            } else {
                // cpp's `ColumnExprAsterisk` ctx covers `*` plus the
                // optional `EXCLUDE(...)` trailer. Wrap the inner
                // ColumnsExpr from the `*` position so it carries the
                // span before the outer columns_list_from_first picks
                // it up as `columns[0]`.
                let inner = self.wrap_pos(
                    self.emit.columns_expr(None, None, true, exclude, None),
                    asterisk_pos,
                );
                self.columns_list_from_first(inner)?
            }
        } else {
            // Could be `ident . *` or an expression list.
            // Peek for the qualified-asterisk pattern: IDENT DOT ASTERISK.
            if matches!(
                self.peek(),
                TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
            ) && self.peek_next() == TokenKind::Dot
            {
                // Try to consume `IDENT.*` (or longer dotted chain ending in `*`).
                let saved_pos = self.peek0.start;
                let mut chain: Vec<String> = Vec::new();
                let mut probe = Lexer::with_pos(self.src, saved_pos);
                let first = probe.next_token()?;
                chain.push(identifier_text(
                    &self.src[first.start..first.end],
                    first.kind,
                ));
                let mut ok = true;
                let mut saw_star = false;
                loop {
                    let dot = probe.next_token()?;
                    if dot.kind != TokenKind::Dot {
                        ok = false;
                        break;
                    }
                    let nxt = probe.next_token()?;
                    if nxt.kind == TokenKind::Asterisk {
                        saw_star = true;
                        break;
                    }
                    if matches!(
                        nxt.kind,
                        TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
                    ) {
                        chain.push(identifier_text(&self.src[nxt.start..nxt.end], nxt.kind));
                    } else {
                        ok = false;
                        break;
                    }
                }
                if ok && saw_star {
                    // Capture the end of the `*` token before committing
                    // the cursor — we want the Field span to cover the
                    // qualified asterisk (`table.*`), matching cpp's
                    // `ColumnExprColumnsQualifiedAll` ctx span.
                    let asterisk_end = probe.pos();
                    // Commit the qualified-asterisk consumption.
                    self.set_lexer_pos(probe.pos())?;
                    let (exclude, replace) = self.parse_columns_decorators()?;
                    let mut chain_values: Vec<E::Value> =
                        chain.into_iter().map(|s| self.emit.string(&s)).collect();
                    chain_values.push(self.emit.string("*"));
                    let qualified_field =
                        self.wrap_pos_to(self.emit.field(chain_values), saved_pos, asterisk_end);
                    // Four C++-visitor shapes, all reachable here:
                    //   QualifiedAll:           ColumnsExpr(columns=[Field(table.*)])
                    //   QualifiedExclude:       ColumnsExpr(columns=[ColumnsExpr(all_columns=True, exclude=...)])
                    //   QualifiedReplace:       ColumnsExpr(all_columns=True, replace=...)  // qualifier dropped
                    //   QualifiedExcludeReplace: ColumnsExpr(all_columns=True, exclude=..., replace=...)  // qualifier dropped
                    match (exclude, replace) {
                        (None, None) => self.columns_list_from_first(qualified_field)?,
                        (Some(ex), None) => {
                            // cpp's `ColumnExprColumnsQualifiedExclude`
                            // ctx covers `IDENT.* EXCLUDE(...)`; the
                            // inner ColumnsExpr inherits that span.
                            // Wrap before passing to the outer list.
                            let inner = self.wrap_pos(
                                self.emit.columns_expr(None, None, true, Some(ex), None),
                                saved_pos,
                            );
                            self.columns_list_from_first(inner)?
                        }
                        (ex, repl @ Some(_)) => {
                            // cpp's `ColumnExprColumnsQualifiedReplace` /
                            // `…QualifiedExcludeReplace` ctx covers the
                            // full `COLUMNS LPAREN IDENT.* [EXCLUDE(...)]
                            // REPLACE(...) RPAREN`. The outer
                            // `parse_expr_bp` wrap captures positions
                            // from the COLUMNS keyword, so emit the
                            // ColumnsExpr without a local wrap and let
                            // that outer wrap stamp the span.
                            self.emit.columns_expr(None, None, true, ex, repl)
                        }
                    }
                } else {
                    let list = self.parse_arg_list(TokenKind::RParen)?;
                    self.emit.columns_expr(None, Some(list), false, None, None)
                }
            } else {
                let list = self.parse_arg_list(TokenKind::RParen)?;
                self.emit.columns_expr(None, Some(list), false, None, None)
            }
        };
        self.expect(TokenKind::RParen, ")")?;
        Ok(result)
    }

    /// An asterisk-form (`*`, `id.*`, `* EXCLUDE (...)`) inside
    /// `COLUMNS (...)` has already been parsed into `first`. cpp's
    /// ANTLR resolves the `COLUMNS LPAREN columnExprList RPAREN`
    /// alternative before the dedicated `* …` / `id.* …` ones, so when
    /// a `)` follows immediately this was the sole list element. When
    /// anything else follows, the asterisk-form is the head of a
    /// larger `columnExpr` (a postfix `(…)` call etc.) and may be the
    /// first of a comma list — continue it through the Pratt loop and
    /// collect the rest as `ColumnExprColumnsList`.
    fn columns_list_from_first(&mut self, first: E::Value) -> Result<E::Value, ParseError> {
        if self.peek() == TokenKind::RParen {
            return Ok(self
                .emit
                .columns_expr(None, Some(vec![first]), false, None, None));
        }
        let cont_start = self.peek0.start;
        let first = self.pratt_continue_with_lhs(first, 0, cont_start)?;
        let mut list = vec![first];
        while self.eat(TokenKind::Comma)? {
            if self.peek() == TokenKind::RParen {
                break;
            }
            list.push(self.parse_expr_bp(0)?);
        }
        Ok(self.emit.columns_expr(None, Some(list), false, None, None))
    }

    fn parse_columns_decorators(&mut self) -> Result<ColumnsDecorators<E::Value>, ParseError> {
        let exclude = if self.eat_kw(Kw::Exclude)? {
            self.expect(TokenKind::LParen, "(")?;
            let mut names = Vec::new();
            loop {
                // Each entry is a `nestedIdentifier`: identifier
                // (DOT identifier)*. The cpp `visitNestedIdentifier`
                // joins the parts with `.` into a single string.
                let mut parts: Vec<String> = Vec::new();
                let first = self.bump()?;
                parts.push(match first.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(first), first.kind)
                    }
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        identifier_text(self.text(first), first.kind)
                    }
                    _ => {
                        return Err(self.err(format!(
                            "expected identifier in EXCLUDE list, got {:?}",
                            first.kind
                        )))
                    }
                });
                while self.peek() == TokenKind::Dot {
                    self.bump()?;
                    let part = self.bump()?;
                    parts.push(match part.kind {
                        TokenKind::Ident | TokenKind::QuotedIdent => {
                            identifier_text(self.text(part), part.kind)
                        }
                        TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                            identifier_text(self.text(part), part.kind)
                        }
                        _ => {
                            return Err(self.err(format!(
                                "expected identifier after `.` in EXCLUDE list, got {:?}",
                                part.kind
                            )))
                        }
                    });
                }
                names.push(parts.join("."));
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RParen {
                    break;
                }
            }
            self.expect(TokenKind::RParen, ")")?;
            Some(names)
        } else {
            None
        };

        let replace = if self.eat_kw(Kw::Replace)? {
            self.expect(TokenKind::LParen, "(")?;
            let mut items = Vec::new();
            loop {
                // `columnsReplaceItem: columnExpr AS identifier`. The
                // separator `AS` is the item's second-to-last token
                // (the last token is the replacement `identifier`).
                // Gate the alias-infix on that offset (same mechanism
                // as CAST) so the inner `columnExpr` parse takes any
                // earlier aliases and stops before the separator.
                let item_as = self.find_replace_item_as_pos()?;
                let prev_stop = std::mem::replace(&mut self.cast_as_stop, item_as);
                let expr_result = self.parse_expr_bp(0);
                self.cast_as_stop = prev_stop;
                let expr = expr_result?;
                self.expect_kw(Kw::As, "AS")?;
                let t = self.bump()?;
                let name = match t.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(t), t.kind)
                    }
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        identifier_text(self.text(t), t.kind)
                    }
                    _ => {
                        return Err(self.err(format!(
                            "expected identifier in REPLACE clause, got {:?}",
                            t.kind
                        )))
                    }
                };
                items.push((name, expr));
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                // `columnsReplaceList: columnsReplaceItem (COMMA
                // columnsReplaceItem)*` — no trailing comma; cpp rejects
                // `REPLACE (b AS c,)`.
                if self.peek() == TokenKind::RParen {
                    return Err(self.err("trailing comma in REPLACE clause"));
                }
            }
            self.expect(TokenKind::RParen, ")")?;
            Some(items)
        } else {
            None
        };

        Ok((exclude, replace))
    }

    /// Bare `*` at primary position. Three forms, in grammar-declared
    /// order:
    ///
    /// - `* COLUMNS(…)` → `SpreadExpr(ColumnsExpr(…))` (the spread form,
    ///   either regex or list)
    /// - `* EXCLUDE (…)` / `* REPLACE (…)` → `ColumnsExpr(all_columns=True, …)`
    /// - bare `*` → `Field(["*"])` (C++ visitor's `ColumnExprAsterisk`)
    fn parse_top_level_asterisk(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::Asterisk, "*")?;
        // `* COLUMNS(…)` — spread-columns form. The inner is whatever
        // parse_columns_expr produces (regex / list / qualified-all);
        // we wrap it in a SpreadExpr to match the visitor's
        // `ColumnExprSpreadColumns*` family. Only enter this branch
        // when COLUMNS is actually followed by `(` — bare `* COLUMNS`
        // is rejected by cpp / falls back to a bare `*` Field.
        if matches!(self.peek(), TokenKind::Keyword(Kw::Columns))
            && self.peek_next() == TokenKind::LParen
        {
            let inner = self.parse_columns_expr()?;
            return Ok(self.emit.spread_expr(inner));
        }
        // `ColumnExprAsterisk` (grammar line 289) admits ONLY an
        // optional trailing EXCLUDE on a bare `*`. `REPLACE` after `*`
        // is valid only inside the paren-wrapped forms (lines 220-225)
        // — `(* REPLACE (…))`, `(* EXCLUDE (…) REPLACE (…))`, and the
        // `COLUMNS(* … REPLACE …)` family. We detect the paren-wrapped
        // case by looking at what follows the REPLACE-list's closing
        // `)`: if it's `)` we're inside a wrapping paren (cpp's
        // ColumnExprColumnsReplace alt); anything else means the bare-
        // `*` REPLACE attempted at top level, which cpp rejects.
        let cp_before_decorators = self.checkpoint();
        let (exclude, replace) = self.parse_columns_decorators()?;
        if replace.is_some() && self.peek() != TokenKind::RParen {
            self.restore(cp_before_decorators)?;
            return Err(self.err(
                "REPLACE after a bare `*` is only valid inside `(* REPLACE …)` / `COLUMNS(* REPLACE …)`",
            ));
        }
        if exclude.is_none() && replace.is_none() {
            Ok(self.emit.field(vec![self.emit.string("*")]))
        } else {
            Ok(self.emit.columns_expr(None, None, true, exclude, replace))
        }
    }

    /// `#<integer>` — positional column reference from a SELECT.
    fn parse_positional(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::Hash, "#")?;
        let tok = self.bump()?;
        if tok.kind != TokenKind::Number {
            return Err(self.err(format!("expected integer after '#', got {:?}", tok.kind)));
        }
        let n: i64 = self.text(tok).parse().unwrap_or(0);
        Ok(self.emit.positional_ref(n))
    }

    pub(crate) fn parse_brace_dict_or_placeholder(&mut self) -> Result<E::Value, ParseError> {
        // Capture the `{` start so the resulting Dict / Placeholder carries
        // a span from `{` through `}`. Callers reached via `parse_expr_bp`
        // also wrap, but `parse_table_expr` and the join-expr placeholder
        // arm call this directly without an outer Pratt wrap — without
        // wrapping here the resulting table-position is None.
        let brace_start = self.peek0.start;
        self.expect(TokenKind::LBrace, "{")?;
        if self.peek() == TokenKind::RBrace {
            self.bump()?;
            return Ok(self.wrap_pos(self.emit.dict_(vec![]), brace_start));
        }
        let first = self.parse_expr_bp(0)?;
        if self.eat(TokenKind::Colon)? {
            let v = self.parse_expr_bp(0)?;
            let mut items = vec![(first, v)];
            while self.eat(TokenKind::Comma)? {
                if self.peek() == TokenKind::RBrace {
                    break;
                }
                let k = self.parse_expr_bp(0)?;
                self.expect(TokenKind::Colon, ":")?;
                let v = self.parse_expr_bp(0)?;
                items.push((k, v));
            }
            self.expect(TokenKind::RBrace, "}")?;
            Ok(self.wrap_pos(self.emit.dict_(items), brace_start))
        } else {
            self.expect(TokenKind::RBrace, "}")?;
            Ok(self.wrap_pos(self.emit.placeholder(first), brace_start))
        }
    }

    fn parse_single_arg_arrow_lambda(&mut self) -> Result<E::Value, ParseError> {
        let ident = self.bump()?;
        let name = identifier_text(self.text(ident), ident.kind);
        self.expect(TokenKind::Arrow, "->")?;
        let body = self.parse_lambda_body()?;
        Ok(self.emit.lambda(vec![name], body))
    }

    /// Lambda body — either a single expression (`(x) -> expr`) or a
    /// Hog block (`(x) -> { stmt stmt }`). The block form lets a
    /// lambda contain imperative statements with the trailing
    /// expression / return statement as the value.
    ///
    /// A `{…}` body is genuinely ambiguous: `{1: 2}` is a Dict, `{x}`
    /// is a Placeholder, `{ a b }` / `{ let x }` is a Block. cpp's
    /// ALL(*) prefers the expression and falls back to the block. We
    /// mirror that with bounded backtracking rather than a heuristic
    /// scan: try to parse the brace as one whole expression, and if it
    /// does not parse as one, parse it as a block. This is faithful at
    /// any nesting depth — a heuristic that pattern-matches the brace
    /// contents inevitably misses shapes (e.g. a block of juxtaposed
    /// `exprStmt`s carries no `;`, keyword, or `:=` to key on).
    pub(crate) fn parse_lambda_body(&mut self) -> Result<E::Value, ParseError> {
        if self.peek() == TokenKind::LBrace {
            return self.try_alt(&[&Self::parse_brace_expr_body, &Self::parse_block]);
        }
        self.parse_expr_bp(0)
    }

    /// `try_alt` arm: parse a `{…}` lambda body as a single Dict /
    /// Placeholder expression. Fails (so the block arm takes over) when
    /// the brace contents are not one whole `columnExpr`.
    fn parse_brace_expr_body(&mut self) -> Result<E::Value, ParseError> {
        self.parse_expr_bp(0)
    }

    /// Try the bare-list arrow lambda form: `IDENT (, IDENT)* -> body`.
    /// Only valid at the outermost expression level (inside argument lists
    /// the commas are separators, so we never need to detect it there).
    pub(crate) fn try_bare_list_lambda(&mut self) -> Result<Option<E::Value>, ParseError> {
        // `IDENT (, IDENT)* COMMA? -> body`. A lambda parameter is an
        // `identifier`: a plain Ident, a QuotedIdent, or any keyword
        // admitted by `kw_valid_as_identifier` (`name -> 1`,
        // `select -> 1`; but not `null -> 1` — cpp's `identifier`
        // rule omits NULL / INF / NAN and the Hog-statement keywords).
        let is_ident_kind = |k: TokenKind| -> bool {
            matches!(k, TokenKind::Ident | TokenKind::QuotedIdent)
                || matches!(k, TokenKind::Keyword(kw) if kw_valid_as_identifier(kw))
        };
        if !is_ident_kind(self.peek()) {
            return Ok(None);
        }
        // Probe with a shadow lexer that doesn't disturb the parser state.
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let mut names: Vec<String> = Vec::new();
        let first = probe.next_token()?;
        if !is_ident_kind(first.kind) {
            return Ok(None);
        }
        names.push(identifier_text(
            &self.src[first.start..first.end],
            first.kind,
        ));
        loop {
            let t = probe.next_token()?;
            match t.kind {
                TokenKind::Arrow => {
                    // Confirmed; commit the consumption.
                    self.set_lexer_pos(probe.pos())?;
                    let body = self.parse_lambda_body()?;
                    return Ok(Some(self.emit.lambda(names, body)));
                }
                TokenKind::Comma => {
                    // Peek past the comma to handle the trailing-comma
                    // case (`a, -> body`): if the next token is the
                    // arrow itself we still want to commit.
                    let after = probe.next_token()?;
                    match after.kind {
                        TokenKind::Arrow => {
                            self.set_lexer_pos(probe.pos())?;
                            let body = self.parse_lambda_body()?;
                            return Ok(Some(self.emit.lambda(names, body)));
                        }
                        k if is_ident_kind(k) => {
                            names.push(identifier_text(
                                &self.src[after.start..after.end],
                                after.kind,
                            ));
                        }
                        _ => return Ok(None),
                    }
                }
                _ => return Ok(None),
            }
        }
    }

    /// `(...)` may be a paren-wrapped expression, a tuple, or a lambda
    /// head followed by `->`. We probe for the lambda shape first because
    /// it's the only one that needs to refuse non-identifier contents.
    fn parse_paren_or_lambda(&mut self) -> Result<E::Value, ParseError> {
        // Probe for `( [IDENT (, IDENT)* COMMA?]? ) ARROW`.
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let lp = probe.next_token()?;
        debug_assert_eq!(lp.kind, TokenKind::LParen);
        let mut names: Vec<String> = Vec::new();
        let mut next = probe.next_token()?;
        let mut ok = true;
        if next.kind == TokenKind::RParen {
            // Empty `()` — only valid as a lambda head.
        } else {
            loop {
                // The grammar's lambda head admits any `identifier` —
                // plain IDENT, quoted idents (`"x"`), or any keyword
                // admitted by `kw_valid_as_identifier` (`(name) -> body`,
                // `(select) -> body`; but not `(null) -> body` — cpp's
                // `identifier` rule omits NULL / INF / NAN and the
                // Hog-statement keywords).
                let is_ident_kind = matches!(next.kind, TokenKind::Ident | TokenKind::QuotedIdent)
                    || matches!(next.kind, TokenKind::Keyword(kw) if kw_valid_as_identifier(kw));
                if !is_ident_kind {
                    ok = false;
                    break;
                }
                names.push(identifier_text(&self.src[next.start..next.end], next.kind));
                let after = probe.next_token()?;
                match after.kind {
                    TokenKind::Comma => {
                        next = probe.next_token()?;
                        if next.kind == TokenKind::RParen {
                            break;
                        } // trailing comma
                    }
                    TokenKind::RParen => break,
                    _ => {
                        ok = false;
                        break;
                    }
                }
            }
        }
        if ok {
            let arrow = probe.next_token()?;
            if arrow.kind == TokenKind::Arrow {
                self.set_lexer_pos(probe.pos())?;
                let body = self.parse_lambda_body()?;
                return Ok(self.emit.lambda(names, body));
            }
        }
        // Not a lambda — fall through to the normal paren/tuple parse.
        self.parse_paren_or_tuple()
    }

    /// If the just-consumed numeric token is followed by `.<digits>`,
    /// consume the dot + fractional and return the combined source text.
    /// Implements the grammar's `floatingLiteral: DECIMAL_LITERAL DOT
    /// (DECIMAL_LITERAL | OCTAL_LITERAL)?` assembled at parse time so that
    /// `t.1.2` can lex as 5 tokens instead of mis-folding into `t .<float>`.
    /// On any lex error during the fractional consumption we return the
    /// leading text unchanged — the parser will encounter the error on
    /// its next token fetch.
    fn consume_optional_fractional(&mut self, leading: &str) -> String {
        if self.peek() != TokenKind::Dot {
            return leading.to_string();
        }
        // Hex / `0b` binary literals never carry a fractional —
        // `0xc.5` is hex-12 then `.5`, `0b10.5` is binary-2 then `.5`
        // (a tuple access / float-chain fragment), not a hex-/binary-
        // float. Stop here so the Pratt postfix loop can take the dot.
        if leading.starts_with("0x")
            || leading.starts_with("0X")
            || leading.starts_with("0b")
            || leading.starts_with("0B")
        {
            return leading.to_string();
        }
        // Same for C-style leading-zero octal: cpp's ANTLR lexer
        // tokenizes `017.5` as OCTAL_LITERAL `017` then DOT then
        // DECIMAL_LITERAL `5` (TupleAccess), not as a float `17.5`.
        // Recognize "valid octal" as leading-`0` plus only octal
        // digits — `08.5` (with a non-octal `8`) IS a float in cpp
        // because the OCTAL_LITERAL rule doesn't match.
        if leading.len() > 1
            && leading.starts_with('0')
            && leading.chars().all(|c| ('0'..='7').contains(&c))
        {
            return leading.to_string();
        }
        // Trailing-dot float: `1.` with no digit/ident after — cpp's
        // FLOATING_LITERAL grammar admits the empty fractional. Don't
        // consume the dot if it's followed by a Number (full `.5`,
        // handled below) or an Ident (could be a tuple-access /
        // field-chain dot, handled by the Pratt postfix loop).
        //
        // Exception: when peek_next is an INFIX-only keyword (AND,
        // OR, IS, LIKE, IN, BETWEEN, etc.) that needs an LHS, cpp's
        // ANTLR ALL(*) absorbs the dot as the float's empty
        // fractional (`123 .` → `123.0`) so the keyword can apply
        // to the resulting float. Without the dot absorbed our Pratt
        // postfix loop takes `.` as a property access, then errors
        // when the keyword can't be a property name.
        let consume_as_float = match self.peek_next() {
            TokenKind::Number | TokenKind::Ident | TokenKind::QuotedIdent => false,
            // `<n> . IGNORE NULLS` — `IGNORE NULLS` is a postfix
            // modifier (the cpp visitor drops it), not a `.property`
            // access. cpp's ALL(*) absorbs the dot as the float's
            // empty fractional so IGNORE NULLS applies to the float;
            // the `.ignore` property reading would strand `nulls` as
            // a trailing reserved keyword. Needs a 3-token probe:
            // only absorb when `nulls` actually follows `ignore`
            // (`<n> . ignore` alone IS a `.ignore` property access).
            TokenKind::Keyword(Kw::Ignore) => {
                let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                matches!(
                    probe.next_token().map(|t| t.kind),
                    Ok(TokenKind::Keyword(Kw::Nulls))
                )
            }
            // Soft identifier keywords — would be valid property
            // names. Leave the dot for postfix-property access.
            TokenKind::Keyword(kw) => matches!(
                kw,
                // Infix-only keywords: each needs an LHS, so the
                // preceding number must be the float-with-empty-
                // fractional rather than the `.kw` property-access
                // chain head.
                Kw::And | Kw::Or | Kw::Is | Kw::Like | Kw::Ilike | Kw::In | Kw::Between | Kw::Not
            ),
            _ => true,
        };
        if consume_as_float {
            // Consume the dot as part of the float and emit `<n>.0`.
            if self.bump().is_ok() {
                return format!("{leading}.0");
            }
            return leading.to_string();
        }
        if !matches!(self.peek_next(), TokenKind::Number) {
            return leading.to_string();
        }
        match self.bump() {
            Err(_) => return leading.to_string(),
            Ok(_dot) => {}
        }
        match self.bump() {
            Err(_) => leading.to_string(),
            Ok(frac) => format!("{leading}.{}", self.text(frac)),
        }
    }

    /// Consume a leading-dot float (`.<digits>`) prefixed by an
    /// optional sign — the `-.<digits>` / `+.<digits>` shape that
    /// pairs with the unsigned `.<digits>` branch in `parse_primary`.
    /// Caller has confirmed `peek()` is the sign token and
    /// `peek_next()` is `Dot`; here we additionally check that the
    /// token after the dot is `Number` before committing. Returns
    /// `Ok(None)` (without moving the cursor) when the lookahead
    /// doesn't fit, so the caller can fall through to unary-minus.
    fn consume_signed_dot_float(&mut self, negative: bool) -> Result<Option<E::Value>, ParseError> {
        // Probe the token after `.` via a shadow lexer; only commit if
        // it's a Number.
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let after_dot = probe.next_token()?;
        if after_dot.kind != TokenKind::Number {
            return Ok(None);
        }
        self.bump()?; // sign
        self.bump()?; // dot
        let n = self.bump()?; // digits
        let src = format!(".{}", self.text(n));
        Ok(Some(parse_number_literal(&self.emit, &src, negative)?))
    }

    pub(crate) fn set_lexer_pos(&mut self, pos: usize) -> Result<(), ParseError> {
        self.lexer = Lexer::with_pos(self.src, pos);
        self.peek0 = self.lexer.next_token()?;
        self.peek1 = self.lexer.next_token()?;
        Ok(())
    }

    fn parse_paren_or_tuple(&mut self) -> Result<E::Value, ParseError> {
        // Capture the outer-LParen start before consuming it. cpp's
        // `ColumnExprColumnsReplace` / `ColumnExprColumnsExcludeReplace`
        // grammar alts (`LPAREN ASTERISK [EXCLUDE(...)]? REPLACE(...) RPAREN`)
        // include the outer parens in the ctx span, but our inner parser
        // wraps the ColumnsExpr at the `*` position only. We override the
        // span with the outer paren bounds for those shapes after parsing.
        let outer_start = self.peek0.start;
        self.expect(TokenKind::LParen, "(")?;
        // Empty `()` isn't a valid expression form (lambdas use `() -> ...`).
        if self.peek() == TokenKind::RParen {
            return Err(self.err("empty parentheses are not a valid expression"));
        }
        // Three competing grammar arms when the inner is non-empty:
        //   ColumnExprSubquery: LPAREN selectSetStmt RPAREN
        //   ColumnExprParens:   LPAREN columnExpr RPAREN
        //   ColumnExprTuple:    LPAREN columnExprList RPAREN
        //
        // The subquery alt covers (SELECT …), (WITH … SELECT …), the
        // bare placeholder ({x}) used as selectStmtWithParens, and
        // arbitrarily-nested `((SELECT …) OFFSET n)` shapes whose inner
        // is itself paren-wrapped.
        //
        // The parens/tuple alts share the same prefix (columnExpr); the
        // tuple arm fires when a comma appears at depth 0 after the
        // first expression. Encoded as a single arm with a runtime
        // comma probe.
        let result = self.try_alt(&[
            // Alt 1: subquery
            &|p| {
                let sub = p.parse_select_set_stmt()?;
                p.expect(TokenKind::RParen, ")")?;
                Ok(sub)
            },
            // Alt 2: parens / tuple
            &Self::parse_paren_expr_or_tuple_arm,
        ])?;
        // Re-wrap ColumnsExpr-with-REPLACE shapes whose grammar rule
        // (`LPAREN ASTERISK [EXCLUDE(...)]? REPLACE(...) RPAREN`) makes the
        // outer parens part of the ctx span — the inner wrap missed them.
        // Exclude-only `(* EXCLUDE (...))` is a regular ColumnExprAsterisk
        // inside ColumnExprParens (pass-through), so REPLACE is the
        // distinguishing marker.
        if is_paren_form_columns_replace(&self.emit, &result) {
            let end = self.last_consumed_end;
            return Ok(self.replace_pos_to(result, outer_start, end));
        }
        Ok(result)
    }

    /// `parse_paren_or_tuple` arm: ColumnExprParens or ColumnExprTuple
    /// after the leading `(` has been consumed.
    fn parse_paren_expr_or_tuple_arm(&mut self) -> Result<E::Value, ParseError> {
        let first = self.parse_expr_bp(0)?;
        if self.eat(TokenKind::Comma)? {
            let mut exprs = vec![first];
            if self.peek() != TokenKind::RParen {
                loop {
                    exprs.push(self.parse_expr_bp(0)?);
                    if !self.eat(TokenKind::Comma)? {
                        break;
                    }
                    if self.peek() == TokenKind::RParen {
                        break;
                    }
                }
            }
            self.expect(TokenKind::RParen, ")")?;
            Ok(self.emit.tuple_(exprs))
        } else {
            self.expect(TokenKind::RParen, ")")?;
            Ok(first)
        }
    }

    /// Probe: after `NOT *`, does `*` head a spread-columns expression
    /// (`* COLUMNS(...)` / `* EXCLUDE(...)` / `* REPLACE(...)`)?
    /// Used to keep NOT as a unary prefix when a spread operand
    /// follows; otherwise (`*` followed by anything else, including
    /// COLUMNS without `(`) NOT falls back to a Field identifier and
    /// `*` becomes the multiplication operator.
    /// Probe: when NOT is followed by ASTERISK, can the ASTERISK plus what
    /// follows it start a valid columnExpr? If yes, cpp's ANTLR picks
    /// `ColumnExprNot` (unary NOT) with `*` as the Field('*') head of the
    /// inner columnExpr. If no, the asterisk is treated as multiplication
    /// and NOT becomes a Field identifier via the keyword rule.
    ///
    /// `* X` is a valid columnExpr when X is:
    ///   - End-of-expression (bare `*` is the whole columnExpr).
    ///   - A postfix op on Field('*'): `(` (call), `[` (array access),
    ///     `.` (chain → ArrayAccess split), `::` (typecast), `?.`.
    ///   - A binary infix op or infix keyword (Field('*') OP X is valid).
    ///   - `EXCLUDE` / `COLUMNS` keyword (ColumnExprAsterisk's optional
    ///     EXCLUDE decoration, or `* COLUMNS(...)` spread form).
    ///
    /// `* X` is NOT a valid columnExpr when X is a primary atom that can
    /// only start a fresh expression (Number, String, Ident, LBrace,
    /// primary keywords like CASE / CAST / TRUE / etc.). In that case
    /// `* X` would be two adjacent primaries with no operator between
    /// them, so cpp falls back to `Field('not') * <primary>`.
    fn asterisk_after_not_starts_columnexpr(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::Asterisk);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let p2 = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return true, // EOF → bare `*` is the columnExpr.
        };
        match p2.kind {
            // End-of-expression markers — bare `*` is the entire columnExpr.
            TokenKind::Eof
            | TokenKind::RParen
            | TokenKind::RBracket
            | TokenKind::RBrace
            | TokenKind::Comma
            | TokenKind::Semicolon => true,
            // Postfix operators that extend Field('*'):
            TokenKind::LParen
            | TokenKind::LBracket
            | TokenKind::Dot
            | TokenKind::DoubleColon
            | TokenKind::NullProperty => true,
            // Binary infix operators (Field('*') OP X is a valid columnExpr):
            TokenKind::Plus
            | TokenKind::Dash
            | TokenKind::Slash
            | TokenKind::Percent
            | TokenKind::Asterisk
            | TokenKind::Concat
            | TokenKind::Nullish
            | TokenKind::EqDouble
            | TokenKind::EqSingle
            | TokenKind::NotEq
            | TokenKind::Lt
            | TokenKind::LtEq
            | TokenKind::Gt
            | TokenKind::GtEq
            | TokenKind::RegexSingle
            | TokenKind::RegexDouble
            | TokenKind::IRegexSingle
            | TokenKind::IRegexDouble
            | TokenKind::NotRegex
            | TokenKind::NotIRegex
            | TokenKind::QMark
            | TokenKind::Colon => true,
            // Binary infix keywords:
            TokenKind::Keyword(
                Kw::And
                | Kw::Or
                | Kw::Is
                | Kw::In
                | Kw::Like
                | Kw::Ilike
                | Kw::Between
                | Kw::Not
                | Kw::As,
            ) => true,
            // ColumnExprAsterisk's `EXCLUDE (...)` decoration and the
            // `* COLUMNS(...)` spread form. (REPLACE alone after a bare
            // `*` is NOT a valid columnExpr in cpp's grammar — only the
            // surrounded `(* REPLACE ...)` form matches, which is handled
            // separately by `parens_open_self_contained_columns_expr`.)
            TokenKind::Keyword(Kw::Exclude | Kw::Columns) => true,
            // `* IGNORE NULLS` — the postfix that cpp's visitor
            // drops, leaving Field('*') unchanged. So `* IGNORE
            // NULLS` IS a complete columnExpr, and NOT applies to it
            // as unary prefix per ColumnExprNot. (cpp's grammar
            // pairs IGNORE with NULLS; we accept IGNORE as a
            // single-token lookahead here and let the postfix
            // handler enforce the NULLS pairing.)
            TokenKind::Keyword(Kw::Ignore) => true,
            // Anything else (Number, String, Ident, primary keywords) is
            // a pure primary that doesn't extend Field('*') — multiplication
            // wins and NOT becomes a Field.
            _ => false,
        }
    }

    /// Probe: do the parens at peek1 hold a `selectSetStmt` shape — i.e.
    /// either a SELECT/WITH-led statement, or a placeholder-led set-stmt
    /// (`{X} UNION/INTERSECT/EXCEPT …`)? Used by the NOT-prefix
    /// disambiguator: cpp picks `ColumnExprFunction` (Call) over
    /// `ColumnExprNot` (Not) for `not(args)`, but backtracks to NOT-prefix
    /// when the content isn't a valid `columnExprList` — bare SELECT/WITH
    /// and placeholder + set-op are the two shapes that don't fit.
    fn parens_open_select_or_set_stmt(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::LParen);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let first = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        // (a) Immediate SELECT/WITH after the `(`.
        if matches!(
            first.kind,
            TokenKind::Keyword(Kw::Select) | TokenKind::Keyword(Kw::With)
        ) {
            return true;
        }
        // (b) The outer paren content contains a SET-OP (UNION /
        // INTERSECT / EXCEPT) at depth 0 — that's a selectSetStmt
        // shape regardless of whether the first token is a `{X}`
        // placeholder, a nested `(` paren-wrapped subquery, or any
        // other paren-wrapped/placeholder-led selectStmtWithParens.
        // Also recognize selectSetStmt's trailing decorators
        // (ORDER BY / LIMIT / OFFSET / SETTINGS) at depth 0 — cpp's
        // grammar (line 65) admits `selectStmtWithParens
        // (subsequentSelectSetClause)* orderByClause?
        // limitAndOffsetClauseOptional?` so a trailing LIMIT etc.
        // after a paren-wrapped subquery still means selectSetStmt.
        // Scan tokens at depth 0 of the outer paren.
        let mut depth: i32 = 0; // depth relative to outer paren's interior
        let mut tok = first;
        loop {
            match tok.kind {
                TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                    if depth == 0 =>
                {
                    return true;
                }
                // Trailing decorators at depth 0 of the outer paren
                // mean the inside is a selectStmtWithParens whose
                // tail extends — still selectSetStmt territory. cpp
                // includes LIMIT / OFFSET / SETTINGS here but NOT
                // ORDER: an `order by` inside the parens can also
                // appear as a windowExpr / function-arg-with-order
                // (e.g. inside `not ((select 1) order by 1)` cpp
                // dispatches to Call with the order_by absorbed
                // into the function arg's expression), so ORDER
                // alone doesn't disambiguate.
                TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Settings)
                    if depth == 0 =>
                {
                    return true;
                }
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    if depth == 0 {
                        return false; // closed the outer paren without finding SET-OP
                    }
                    depth -= 1;
                }
                TokenKind::Eof => return false,
                _ => {}
            }
            tok = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
        }
    }

    /// Probe: do the parens at peek1 hold a self-contained
    /// `* REPLACE (...)` or `* EXCLUDE (...) REPLACE (...)` columnExpr?
    /// cpp's grammar (HogQLParser.g4:219-225) has these as bare-LPAREN
    /// `ColumnExprColumnsExcludeReplace` / `ColumnExprColumnsReplace`
    /// alts — the LPAREN is part of the columnExpr itself, not a
    /// function-call's args. `NOT (* REPLACE …)` is therefore
    /// `Not(ColumnsExpr)` (cpp picks ColumnExprNot wrapping the
    /// bare-LPAREN columnExpr), not `Call('not', [ColumnsExpr])`.
    ///
    /// Plain `* EXCLUDE (…)` (no REPLACE) is NOT a self-contained
    /// bare-LPAREN form — it stays a valid `ColumnExprAsterisk` arg
    /// inside `(args)`, so `NOT (* EXCLUDE (…))` is a function call.
    /// Returns true only for shapes that consume the outer parens
    /// as part of the columnExpr.
    fn parens_open_self_contained_columns_expr(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::LParen);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let first = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        if first.kind != TokenKind::Asterisk {
            return false;
        }
        let second = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        match second.kind {
            TokenKind::Keyword(Kw::Replace) => true,
            TokenKind::Keyword(Kw::Exclude) => {
                // `* EXCLUDE ( identList )` then look for REPLACE at
                // depth 1. Skip the balanced EXCLUDE paren-group first.
                if !matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::LParen)) {
                    return false;
                }
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
                // After EXCLUDE's closing `)`, REPLACE should follow.
                matches!(
                    probe.next_token().map(|t| t.kind),
                    Ok(TokenKind::Keyword(Kw::Replace))
                )
            }
            _ => false,
        }
    }

    /// Probe: is the LParen at `peek0` followed (after its matching
    /// `)`) by another `(`? Used by `parse_ident_lead` to detect the
    /// `name(params)(args)` parametric-function form: cpp's ANTLR
    /// commits to the parametric alternative when the second paren is
    /// present, parsing the first paren as a plain `columnExprList?`
    /// (no DISTINCT / no ORDER BY). The args-inner parser would
    /// otherwise eagerly consume `DISTINCT` or choke on a comma after
    /// it (`(distinct, x)`).
    fn peek0_paren_followed_by_lparen(&self) -> bool {
        debug_assert_eq!(self.peek(), TokenKind::LParen);
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
        matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::LParen))
    }

    /// Probe: are the parens at peek1 followed (after their matching
    /// `)`) by `->`? Used by the NOT-prefix disambiguator: `(params) ->
    /// body` is the parens-arrow form of a `columnLambdaExpr` — a single
    /// columnExpr — so `NOT (...) -> body` is `Not(Lambda(...))`, not a
    /// function call `not(...)` followed by a stray `->`.
    fn parens_followed_by_arrow(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::LParen);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
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
        matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::Arrow))
    }

    /// Probe: is the LParen at peek1 immediately followed by RParen?
    /// `()` is a function-call form with no args, not a cast/case
    /// special-form opener.
    pub(crate) fn peek_lparen_is_empty(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::LParen);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::RParen))
    }

    /// Probe: does the LParen at peek1 close with a matching RParen
    /// followed by `OVER`, OR by another `(...)` paren block then
    /// `OVER`? Used by the COLUMNS-vs-function dispatch:
    /// - `columns(...) OVER ...` is a window function (cpp's
    ///   `ColumnExprWinFunction` with `columns` as the function name).
    /// - `columns(...)(...) OVER ...` matches the parametric form of
    ///   ColumnExprFunction (`identifier (LPAREN list RPAREN)? LPAREN
    ///   args RPAREN`) with the OVER tail. Both alts dispatch through
    ///   the function-call path with `columns` as the function name,
    ///   NOT the SpreadExpr-companion ColumnsExpr form. Mirrors ANTLR's
    ///   adaptive lookahead which picks the alt that allows the rest
    ///   of the input (the OVER tail) to parse cleanly.
    fn peek_columns_paren_followed_by_over(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::LParen);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        if !Self::probe_skip_balanced_paren_block(&mut probe) {
            return false;
        }
        // After the first paren block, look at the next token. OVER
        // directly → window function. Another LPAREN means we have a
        // parametric-form function call; skip that block too and then
        // check for OVER.
        let next = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        match next.kind {
            TokenKind::Keyword(Kw::Over) => true,
            TokenKind::LParen => {
                if !Self::probe_skip_balanced_paren_block(&mut probe) {
                    return false;
                }
                matches!(
                    probe.next_token().map(|t| t.kind),
                    Ok(TokenKind::Keyword(Kw::Over))
                )
            }
            _ => false,
        }
    }

    /// Consume tokens from `probe` until the currently-open LParen
    /// closes. Returns `true` if the matching RParen was found, `false`
    /// on lex error / EOF before close. The caller is expected to be
    /// positioned just past the opening LParen.
    fn probe_skip_balanced_paren_block(probe: &mut Lexer<'_>) -> bool {
        let mut depth: i32 = 1;
        loop {
            let tok = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
            match tok.kind {
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    depth -= 1;
                    if depth == 0 {
                        return true;
                    }
                }
                TokenKind::Eof => return false,
                _ => {}
            }
        }
    }

    /// Probe: does the `(…)` group whose interior starts at byte
    /// `content_start`, followed by any `.ident` / `.DECIMAL` / `[…]`
    /// access suffixes, lead into a `:=`? Used by the Pratt loop's
    /// statement-RHS guard — a `(…)<chain> :=` run opens the next
    /// statement's `<assignmentTarget> :=`, so the current postfix `(`
    /// must NOT fold it into this expression as a call. The suffix
    /// chain matters because `assignmentTarget` admits `.`/`[]` access
    /// after the parenthesised primary (`(a).b[0] := …`).
    fn paren_block_then_colon_equals(&self, content_start: usize) -> bool {
        let mut probe = Lexer::with_pos(self.src, content_start);
        if !Self::probe_skip_balanced_paren_block(&mut probe) {
            return false;
        }
        loop {
            let tok = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
            match tok.kind {
                TokenKind::ColonEquals => return true,
                // `.ident` / `.DECIMAL` tuple-or-property access.
                TokenKind::Dot => match probe.next_token().map(|t| t.kind) {
                    Ok(
                        TokenKind::Ident
                        | TokenKind::QuotedIdent
                        | TokenKind::Keyword(_)
                        | TokenKind::Number,
                    ) => {}
                    _ => return false,
                },
                // `[ … ]` subscript access — skip the balanced block.
                TokenKind::LBracket => {
                    if !Self::probe_skip_balanced_paren_block(&mut probe) {
                        return false;
                    }
                }
                _ => return false,
            }
        }
    }

    /// Probe: does the LParen at peek1 start with ORDER or DISTINCT?
    /// Those tokens belong inside the function-call form's arg list
    /// (\`fn(DISTINCT a, b ORDER BY c)\`), so when we see them at the
    /// head of a CAST / TRY_CAST paren list the surrounding keyword is
    /// being used as a function-call name rather than the special form.
    fn peek_lparen_starts_with_order_or_distinct(&self) -> bool {
        debug_assert_eq!(self.peek_next(), TokenKind::LParen);
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        matches!(
            probe.next_token().map(|t| t.kind),
            Ok(TokenKind::Keyword(Kw::Order) | TokenKind::Keyword(Kw::Distinct))
        )
    }

    fn parse_array_literal(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::LBracket, "[")?;
        let mut exprs = Vec::new();
        if self.peek() != TokenKind::RBracket {
            loop {
                exprs.push(self.parse_expr_bp(0)?);
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RBracket {
                    break;
                }
            }
        }
        self.expect(TokenKind::RBracket, "]")?;
        Ok(self.emit.array_(exprs))
    }

    /// Identifier-led primary: either a function call (`IDENT (args)`) or
    /// a Field whose chain greedily consumes `.IDENT...` segments. The
    /// function-call form covers the full grammar shape: parametric calls
    /// (`quantile(0.95)(x)`), DISTINCT, in-arg ORDER BY, trailing FILTER,
    /// and WITHIN GROUP (which forces the first paren list to be params).
    pub(crate) fn parse_ident_lead(&mut self) -> Result<E::Value, ParseError> {
        let head = self.bump()?;
        let name = identifier_text(self.text(head), head.kind);

        // `name := value` — the `ColumnExprNamedArg` form (passed as
        // an alternative shape into call argument lists, but also
        // valid as a standalone column expression).
        if self.peek() == TokenKind::ColonEquals {
            self.bump()?;
            // Value is parsed at BP_ALIAS so an AS-alias trailer
            // becomes part of the named argument's value rather than
            // wrapping the whole NamedArgument node. Matches cpp's
            // `name := <columnExpr>` where columnExpr admits AS.
            let value = self.parse_expr_bp(BP_ALIAS)?;
            // cpp's `ColumnExprNamedArg` visitor emits the node without
            // `addPositionInfo`, so NamedArgument has no `start`/`end`.
            // Mark via `no_pos` so the outer `parse_expr_bp` pratt-loop
            // wrap leaves it bare.
            return Ok(self.emit.named_argument(&name, value));
        }

        // Statement-RHS guard: `f (x) := y` is `f` (an exprStmt) then
        // `(x) := y` (a varAssignment) — the `(…)` opens the next
        // statement's parenthesised `assignmentTarget`, not a call on
        // `f`. The Pratt-loop postfix guard can't catch this because
        // `IDENT (` is folded into a call here, before the loop runs.
        if self.peek() == TokenKind::LParen
            && self.stop_postfix_call_before_colon_equals
            && self.paren_block_then_colon_equals(self.peek0.end)
        {
            return Ok(self.emit.field(vec![self.emit.string(&name)]));
        }

        if self.peek() == TokenKind::LParen {
            // Probe: is there a SECOND `(` after the matching `)` of this
            // first one? If yes, cpp's ANTLR prefers the ColumnExprFunction
            // alternative with parametric+args, parsing the first paren as
            // a plain `columnExprList?` (no DISTINCT, no ORDER BY). The
            // args-inner parser would consume DISTINCT eagerly and choke
            // on `(distinct, x)` or pick the wrong AST shape for
            // `foo(distinct)()`. Try the parametric form first; on failure
            // (e.g. `(order by x)` or `(distinct x)` — neither a valid
            // columnExprList), fall back to the args-inner parse and let
            // any trailing `(` become a postfix `ColumnExprCall` via the
            // Pratt loop.
            let parametric_likely = self.peek0_paren_followed_by_lparen();
            if parametric_likely {
                let cp = self.checkpoint();
                if let Ok(v) = self.try_parametric_call(&name) {
                    return Ok(v);
                }
                self.restore(cp)?;
            }
            self.bump()?;
            // Parse the first paren list with full args-shape awareness
            // (DISTINCT, in-arg ORDER BY).
            let (first_distinct, first_args, first_order_by) = self.parse_function_args_inner()?;
            self.expect(TokenKind::RParen, ")")?;

            // `name(args) [FILTER (WHERE …)] OVER (windowExpr | name)` —
            // window function form. Distinguishable from the plain-call
            // case by the trailing `OVER` keyword.
            // Optional `FILTER (WHERE …)` between the args and OVER.
            let filter_expr_for_window = self.parse_optional_filter()?;
            if matches!(self.peek(), TokenKind::Keyword(Kw::Over)) {
                // `ColumnExprWinFunction` (grammar line 235) takes a
                // plain `columnExprList` — NO DISTINCT, NO in-arg
                // ORDER BY. cpp rejects `foo(DISTINCT a) OVER ()` /
                // `foo(a ORDER BY b) OVER ()`. Surface the divergence
                // instead of silently dropping the DISTINCT / ORDER BY.
                if first_distinct {
                    return Err(self.err(
                        "DISTINCT in window-function args — ColumnExprWinFunction takes a plain columnExprList",
                    ));
                }
                if first_order_by.is_some() {
                    return Err(self.err(
                        "ORDER BY inside window-function args — ColumnExprWinFunction takes a plain columnExprList",
                    ));
                }
                self.bump()?;
                drop(filter_expr_for_window);
                let (over_expr, over_identifier) = if self.peek() == TokenKind::LParen {
                    self.bump()?;
                    let we = self.parse_window_expr()?;
                    self.expect(TokenKind::RParen, ")")?;
                    (Some(we), None)
                } else {
                    let tok = self.bump()?;
                    let id = match tok.kind {
                        TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
                            identifier_text(self.text(tok), tok.kind)
                        }
                        _ => {
                            return Err(self.err(format!(
                                "expected window name or `(` after OVER, got {:?}",
                                tok.kind,
                            )))
                        }
                    };
                    (None, Some(id))
                };
                return Ok(self.emit.window_function(
                    &name,
                    first_args.clone(),
                    Vec::new(),
                    over_expr,
                    over_identifier,
                ));
            }

            // `name(params) WITHIN GROUP (ORDER BY ... [INTERPOLATE (...)])`.
            // The grammar's `ColumnExprFunctionWithinGroup` (line 234)
            // is `identifier LPAREN columnExprList? RPAREN
            // withinGroupClause` — NO FILTER slot. cpp rejects
            // `f(args) FILTER (WHERE …) WITHIN GROUP (…)`. If the
            // `parse_optional_filter` above ate a FILTER we have to
            // surface the divergence instead of silently dropping it.
            if matches!(self.peek(), TokenKind::Keyword(Kw::Within))
                && self.peek_next() == TokenKind::Keyword(Kw::Group)
            {
                if filter_expr_for_window.is_some() {
                    return Err(self.err(
                        "FILTER (WHERE ...) is not valid before WITHIN GROUP — the grammar's ColumnExprFunctionWithinGroup has no FILTER slot",
                    ));
                }
                self.bump()?;
                self.bump()?;
                self.expect(TokenKind::LParen, "(")?;
                self.expect_kw(Kw::Order, "ORDER")?;
                self.expect_kw(Kw::By, "BY")?;
                let order_by = self.parse_order_expr_list()?;
                // Skip an optional `INTERPOLATE [( … )]` clause without
                // recording it — the AST has no slot for it here.
                if self.eat_kw(Kw::Interpolate)? && self.eat(TokenKind::LParen)? {
                    let mut depth = 1;
                    while depth > 0 {
                        match self.peek() {
                            TokenKind::LParen => {
                                self.bump()?;
                                depth += 1;
                            }
                            TokenKind::RParen => {
                                self.bump()?;
                                depth -= 1;
                            }
                            TokenKind::Eof => {
                                return Err(
                                    self.err("unterminated INTERPOLATE clause inside WITHIN GROUP")
                                )
                            }
                            _ => {
                                self.bump()?;
                            }
                        }
                    }
                }
                self.expect(TokenKind::RParen, ")")?;
                return Ok(self.emit.call_full(
                    &name,
                    Some(first_args),
                    vec![],
                    false,
                    None,
                    None,
                    Some(order_by),
                ));
            }

            // Trailing `(` here is a ColumnExprCall postfix → ExprCall.
            // The parametric form was already handled by the lookahead
            // probe + `try_parametric_call` above; if we got here with a
            // trailing `(`, parametric was either ruled out (no second
            // paren) or attempted and rejected (e.g. `(distinct x)` —
            // not a valid columnExprList). Returning here lets the Pratt
            // postfix loop fold it as ExprCall via `fold_call_or_exprcall`.

            // Single-paren call. `filter_expr_for_window` was consumed
            // by the window-function probe above; re-use it so we don't
            // double-parse the FILTER.
            return Ok(self.emit.call_full(
                &name,
                None,
                first_args,
                first_distinct,
                first_order_by,
                filter_expr_for_window,
                None,
            ));
        }

        let mut chain: Vec<E::Value> = vec![self.emit.string(&name)];
        let mut ended_with_star = false;
        while self.peek() == TokenKind::Dot {
            // `.<number>` is a tuple access, handled by the postfix loop.
            if self.peek_next() == TokenKind::Number {
                break;
            }
            self.bump()?; // consume '.'
            let part = self.bump()?;
            match part.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => {}
                // Grammar's `identifier` rule excludes NULL/INF/NAN/
                // EXCEPT/INTERSECT and Hog-statement keywords; gate
                // chain links through `kw_valid_as_identifier`.
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {}
                TokenKind::Asterisk => {
                    // cpp's grammar splits `a.b.*.c` into
                    // ColumnExprAsterisk(tableIdentifier=a.b) followed by
                    // ColumnExprPropertyAccess(.c) — the visitor emits
                    // `ArrayAccess(Field([a, b, *]), Constant('c'))`.
                    // Stop the chain at the `*` and let the outer Pratt
                    // postfix loop apply DOT → ArrayAccess to whatever
                    // follows.
                    chain.push(self.emit.string("*"));
                    ended_with_star = true;
                    break;
                }
                _ => {
                    return Err(self.err(format!(
                        "expected identifier after '.', got {:?}",
                        part.kind
                    )))
                }
            }
            chain.push(
                self.emit
                    .string(&identifier_text(self.text(part), part.kind)),
            );
            ended_with_star = false;
        }
        // `IDENT(.IDENT)*.* EXCLUDE (…)` — the grammar's `ColumnExprAsterisk`
        // alt admits a trailing EXCLUDE, and the cpp visitor drops the
        // qualifier in that branch (returning `ColumnsExpr(all_columns=True,
        // exclude=[…])`, NOT a Field chain).
        if ended_with_star && matches!(self.peek(), TokenKind::Keyword(Kw::Exclude)) {
            let (exclude, _) = self.parse_columns_decorators()?;
            return Ok(self.emit.columns_expr(None, None, true, exclude, None));
        }
        Ok(self.emit.field(chain))
    }

    /// Parse a function-call argument list with the grammar's
    /// `DISTINCT? args (ORDER BY orderExprList)?` shape. Caller has
    /// already consumed the opening `(` and must consume the closing one.
    /// Parametric function call: `name(params)(args) [FILTER(…)] [OVER …]`.
    /// Caller must have verified (via `peek0_paren_followed_by_lparen`)
    /// that two paren pairs are present, then wrapped this call in
    /// checkpoint / restore so the caller can fall back to the args-only
    /// path when the first paren content isn't a valid `columnExprList`
    /// (e.g. `(order by x)`, `(distinct x)`).
    ///
    /// First paren is parsed as a plain `columnExprList` (`parse_arg_list`,
    /// no DISTINCT / ORDER BY recognition). Second paren is parsed as the
    /// args paren (full DISTINCT / ORDER BY semantics).
    /// Probe: after consuming the first paren-pair of a parametric
    /// call (cursor at peek = LParen for the second paren), does the
    /// second paren OPEN with a bare `selectSetStmt`? cpp's grammar
    /// matches that shape via `ColumnExprCallSelect` (postfix →
    /// ExprCall) rather than the parametric `ColumnExprFunction` (Call).
    /// A bare selectSetStmt is: SELECT / WITH starting at the LPAREN's
    /// inside, OR a `{X}`-led placeholder set-stmt where the
    /// placeholder is immediately followed (at outer-paren depth) by a
    /// UNION / INTERSECT / EXCEPT keyword. A paren-wrapped subquery
    /// (`((select 1))`) does NOT count — that's a regular columnExpr.
    fn peek_next_paren_opens_bare_select_set_stmt(&self) -> bool {
        debug_assert_eq!(self.peek(), TokenKind::LParen);
        // Reuse the existing scanner that walks tokens at depth 0
        // looking for SELECT / WITH first OR a SET-OP later. The probe
        // is keyed off `peek_next` being LParen, so temporarily shift
        // perspective: scan from `self.peek0.end` as if the LParen at
        // peek0 was at peek1.
        let mut probe = Lexer::with_pos(self.src, self.peek0.end);
        let first = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        if matches!(
            first.kind,
            TokenKind::Keyword(Kw::Select) | TokenKind::Keyword(Kw::With)
        ) {
            return true;
        }
        let mut depth: i32 = 0;
        let mut tok = first;
        loop {
            match tok.kind {
                TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                    if depth == 0 =>
                {
                    return true;
                }
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    if depth == 0 {
                        return false;
                    }
                    depth -= 1;
                }
                TokenKind::Eof => return false,
                _ => {}
            }
            tok = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
        }
    }

    fn try_parametric_call(&mut self, name: &str) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::LParen, "(")?;
        let params = self.parse_arg_list(TokenKind::RParen)?;
        // A bare `selectSetStmt` inside the first paren means this is
        // actually a `ColumnExprCallSelect` (subquery-as-arg) followed
        // by a postfix `ColumnExprCall`, not a parametric
        // `ColumnExprFunction` — cpp's ANTLR backs off Function
        // because its first paren slot is `columnExprList`, which a
        // bare select-set-stmt isn't. Bail so the caller's fallback
        // path runs `parse_function_args_inner` (with subquery
        // support) for the first paren and lets the Pratt loop append
        // the second paren as `ExprCall`.
        if params.iter().any(|p| {
            matches!(
                self.emit.node_kind(p).as_deref(),
                Some("SelectQuery") | Some("SelectSetQuery")
            )
        }) {
            return Err(self.err(
                "first paren opens a bare select-set-stmt — caller falls back to CallSelect + Call postfix",
            ));
        }
        self.expect(TokenKind::RParen, ")")?;
        // Peek the SECOND paren's content. cpp's grammar prefers
        // ColumnExprCallSelect (postfix → ExprCall) over the parametric
        // ColumnExprFunction (Call) ONLY when the second paren's
        // content is a BARE selectSetStmt — `(select ...)`,
        // `(with ...)`, or `({X} <SETOP> ...)`. When the content is a
        // paren-wrapped subquery (`((select 1))`) or anything else,
        // Function wins → Call. Mirror by rejecting parametric only
        // when the bare-select-set-stmt shape is detected.
        if self.peek_next_paren_opens_bare_select_set_stmt() {
            return Err(self.err(
                "second paren opens a bare select-set-stmt — caller falls back to CallSelect postfix",
            ));
        }
        self.expect(TokenKind::LParen, "(")?;
        let (distinct, args, order_by) = self.parse_function_args_inner()?;
        self.expect(TokenKind::RParen, ")")?;
        let filter_expr = self.parse_optional_filter()?;
        if matches!(self.peek(), TokenKind::Keyword(Kw::Over)) {
            self.bump()?;
            drop((distinct, order_by, filter_expr));
            let (over_expr, over_identifier) = if self.peek() == TokenKind::LParen {
                self.bump()?;
                let we = self.parse_window_expr()?;
                self.expect(TokenKind::RParen, ")")?;
                (Some(we), None)
            } else {
                let tok = self.bump()?;
                let id = match tok.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
                        identifier_text(self.text(tok), tok.kind)
                    }
                    _ => {
                        return Err(self.err(format!(
                            "expected window name or `(` after OVER, got {:?}",
                            tok.kind,
                        )))
                    }
                };
                (None, Some(id))
            };
            return Ok(self
                .emit
                .window_function(name, params, args, over_expr, over_identifier));
        }
        Ok(self.emit.call_full(
            name,
            Some(params),
            args,
            distinct,
            order_by,
            filter_expr,
            None,
        ))
    }

    /// Does the cursor sit on an in-argument `ORDER BY` clause —
    /// `ORDER` immediately followed by `BY`? `ORDER` on its own is a
    /// `keyword`-rule identifier (`fn(x, order?.items)` passes `order`
    /// as a plain Field argument), so the arg-list scan must require
    /// the `BY` before treating `ORDER` as the clause introducer.
    fn peek_starts_in_arg_order_by(&self) -> bool {
        matches!(self.peek(), TokenKind::Keyword(Kw::Order))
            && matches!(self.peek_next(), TokenKind::Keyword(Kw::By))
    }

    fn parse_function_args_inner(&mut self) -> Result<FunctionArgs<E::Value>, ParseError> {
        // Only consume DISTINCT as the args-keyword when what follows can
        // legitimately continue the rule (`RPAREN`, `ORDER`, or the start
        // of a columnExpr). cpp's ANTLR otherwise parses DISTINCT as a
        // Field (via the keyword rule) inside the args list — e.g.
        // `(distinct, x)` and `(distinct.x)` and `(distinct ?. y)`
        // all keep DISTINCT as a Field. The follow-set heuristic here
        // mirrors that: bail out when peek_next is Comma or any pure
        // infix/postfix op that can't start a fresh expression.
        let distinct = if self.peek() == TokenKind::Keyword(Kw::Distinct)
            && !matches!(self.peek_next(), TokenKind::Comma)
            && !is_pure_infix_op(self.peek_next())
        {
            self.bump()?;
            true
        } else {
            false
        };
        let mut args: Vec<E::Value> = Vec::new();
        if self.peek() != TokenKind::RParen && !self.peek_starts_in_arg_order_by() {
            loop {
                args.push(self.parse_call_argument_for_function()?);
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RParen || self.peek_starts_in_arg_order_by() {
                    break;
                }
            }
        }
        let order_by = if self.peek_starts_in_arg_order_by() {
            self.bump()?;
            self.bump()?;
            Some(self.parse_order_expr_list()?)
        } else {
            None
        };
        Ok((distinct, args, order_by))
    }

    fn parse_optional_filter(&mut self) -> Result<Option<E::Value>, ParseError> {
        if !matches!(self.peek(), TokenKind::Keyword(Kw::Filter)) {
            return Ok(None);
        }
        self.bump()?;
        self.expect(TokenKind::LParen, "(")?;
        self.expect_kw(Kw::Where, "WHERE")?;
        // cpp's `VISIT(ColumnExprWinFunction)` parses the FILTER
        // where-expression at the grammar level but never visits it
        // into the AST — so the SelectStmt-visitor semantic checks
        // (ARRAY JOIN without FROM / unaliased ARRAY JOIN arrays)
        // never fire for a subquery nested in here. Suppress them
        // during this parse so `f() FILTER (WHERE (SELECT 1 ARRAY
        // JOIN 2)) OVER w` is accepted the same way.
        let prev = self.suppress_array_join_checks;
        self.suppress_array_join_checks = true;
        let result = self.parse_expr_bp(0);
        self.suppress_array_join_checks = prev;
        let expr = result?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(Some(expr))
    }

    /// Parse a comma-separated list of `orderExpr` items — `expr [ASC|DESC]
    /// [NULLS FIRST|LAST] [COLLATE STRING_LITERAL] [WITH FILL …]`.
    pub(crate) fn parse_order_expr_list(&mut self) -> Result<Vec<E::Value>, ParseError> {
        let mut out = Vec::new();
        loop {
            let order_start = self.peek0.start;
            let expr = self.parse_expr_bp(0)?;
            let order = if self.eat_kw(Kw::Ascending)? {
                "ASC"
            } else if self.eat_kw(Kw::Desc)? || self.eat_kw(Kw::Descending)? {
                "DESC"
            } else {
                "ASC"
            };
            if self.eat_kw(Kw::Nulls)? {
                let _ = self.eat_kw(Kw::First)? || self.eat_kw(Kw::Last)?;
            }
            // `COLLATE 'name'` — swallow; no AST slot yet.
            if self.eat_kw(Kw::Collate)? {
                if !matches!(self.peek(), TokenKind::String) {
                    return Err(self.err(format!(
                        "expected string literal after COLLATE, got {:?}",
                        self.peek(),
                    )));
                }
                self.bump()?;
            }
            // `WITH FILL [FROM e] [TO e] [STEP e]` — postfix decorator on
            // a single OrderExpr.
            let with_fill = if matches!(self.peek(), TokenKind::Keyword(Kw::With))
                && self.peek_next() == TokenKind::Keyword(Kw::Fill)
            {
                let with_fill_start = self.peek0.start;
                self.bump()?;
                self.bump()?;
                let from_value = if self.eat_kw(Kw::From)? {
                    Some(self.parse_expr_bp(0)?)
                } else {
                    None
                };
                let to_value = if self.eat_kw(Kw::To)? {
                    Some(self.parse_expr_bp(0)?)
                } else {
                    None
                };
                let step_value = if self.eat_kw(Kw::Step)? {
                    Some(self.parse_expr_bp(0)?)
                } else {
                    None
                };
                let wfe = self.emit.with_fill_expr(from_value, to_value, step_value);
                // cpp's `WithFill` visitor calls `addPositionInfo(json, ctx)`,
                // so the JSON has `start` / `end` spanning the `WITH FILL ...`
                // tokens. Wrap before stuffing into OrderExpr.
                Some(self.wrap_pos(wfe, with_fill_start))
            } else {
                None
            };
            out.push(self.wrap_pos(self.emit.order_expr(expr, order, with_fill), order_start));
            if !self.eat(TokenKind::Comma)? {
                break;
            }
        }
        Ok(out)
    }

    fn parse_type_expr(&mut self) -> Result<String, ParseError> {
        // Parse `columnTypeExpr` greedy: base ident (or compound `IDENT
        // IDENT+`) followed by optional `LPAREN ...types... RPAREN` or
        // `LBRACKET [size] RBRACKET` suffixes.
        let mut name = self.parse_type_atom()?;
        // Trailing `[...]` / `[N]` array suffixes.
        while self.peek() == TokenKind::LBracket {
            self.bump()?;
            let mut suffix = String::from("[");
            if self.peek() == TokenKind::Number {
                let n = self.bump()?;
                suffix.push_str(self.text(n));
            }
            self.expect(TokenKind::RBracket, "]")?;
            suffix.push(']');
            name.push_str(&suffix);
        }
        Ok(name)
    }

    fn parse_type_atom(&mut self) -> Result<String, ParseError> {
        // Decode a single type-name token, unquoting quoted-idents and
        // lowercasing the rest. The grammar's `columnTypeExpr` resolves
        // through `identifier`, so a `"foo"` type token is semantically
        // the bare ident `foo`; cpp `visitIdentifier` strips the quotes.
        fn token_text<E: Emitter + Clone>(parser: &Parser<'_, E>, t: Token) -> String {
            let raw = parser.text(t);
            match t.kind {
                TokenKind::QuotedIdent => identifier_text(raw, t.kind).to_ascii_lowercase(),
                _ => raw.to_ascii_lowercase(),
            }
        }

        let head = self.bump()?;
        // cpp's `columnTypeExpr` routes through `identifier`, which
        // excludes NULL / INF / NAN — so a bare `NULL` is not a type
        // name. Use `kw_valid_as_identifier` to gate the keyword arm.
        let mut head_name = match head.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => token_text(self, head),
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => token_text(self, head),
            _ => return Err(self.err(format!("expected type identifier, got {:?}", head.kind))),
        };

        // Parametric / nested / complex form: `IDENT ( … )`.
        if self.peek() == TokenKind::LParen {
            self.bump()?;
            // `ColumnTypeExprEnum` matches `IDENT LPAREN enumValue (COMMA
            // enumValue)* COMMA? RPAREN` where `enumValue: STRING_LITERAL
            // EQ_SINGLE numberLiteral`. cpp/python both reject the visit
            // with "Unsupported rule: ColumnTypeExprEnum", so rust must
            // also error rather than fall through to the Param raw-text
            // path (which would happily emit `enum8('a'=1)`).
            // Detect the enumValue shape at the head of the paren body —
            // STRING `=` Number — and short-circuit with the same error.
            if matches!(self.peek(), TokenKind::String)
                && matches!(self.peek_next(), TokenKind::EqDouble | TokenKind::EqSingle)
            {
                let start = self.peek0.start;
                let end = self.peek0.end;
                // Fatal so the outer `try_alt`'s parse_ident_lead
                // fallback doesn't mask the error by re-parsing
                // `cast(...)` as a function call.
                return Err(ParseError::not_implemented_fatal(
                    "Unsupported rule: ColumnTypeExprEnum",
                    start,
                    end,
                ));
            }
            // Pre-classify the whole paren group. cpp's ANTLR ALL(*) commits the
            // entire `IDENT(...)` to a single alt (Nested/Complex/Param/Enum). If
            // ANY depth-0 token forces Param (e.g. `#1`, `{}`, a bare literal,
            // or a top-level operator like `a+b`), then every sibling item also
            // takes the Param path — visited via `ctx->getText()` which keeps
            // case + quoting and concatenates spacelessly. Otherwise Complex/
            // Nested kicks in per-item (recursive visit, lowercased + `, `).
            let raw_mode = self.group_is_param_mode();
            let mut parts: Vec<String> = Vec::new();
            if self.peek() != TokenKind::RParen {
                loop {
                    if raw_mode {
                        parts.push(self.consume_raw_type_param_text()?);
                    } else {
                        parts.push(self.parse_type_param_item()?);
                    }
                    if !self.eat(TokenKind::Comma)? {
                        break;
                    }
                    if self.peek() == TokenKind::RParen {
                        break;
                    }
                }
            }
            self.expect(TokenKind::RParen, ")")?;
            return Ok(format!("{head_name}({})", parts.join(", ")));
        }

        // Compound form: `IDENT IDENT+` (e.g. `TIME WITH TIME ZONE`).
        // cpp's `ColumnTypeExprCompound: identifier identifier+` routes
        // through the grammar's `identifier` rule, which omits NULL /
        // INF / NAN — so trailing `Int NULL` / `Int NOT NULL` does NOT
        // form a compound type in cpp (it errors at the outer `)`). The
        // Rust loop used to admit any Keyword, silently eating the
        // trailing `NULL` and emitting `int null` as the type name.
        while {
            let p = self.peek();
            matches!(p, TokenKind::Ident | TokenKind::QuotedIdent)
                || matches!(p, TokenKind::Keyword(kw) if kw_valid_as_identifier(kw))
        } && !matches!(self.peek(), TokenKind::Keyword(Kw::As))
        {
            // Stop at LPAREN / LBRACKET / RPAREN / comma — those are
            // structural separators rather than parts of the type name.
            // Also stop on AS so we don't gobble outer alias keywords.
            let next = self.bump()?;
            head_name.push(' ');
            head_name.push_str(&token_text(self, next));
        }
        Ok(head_name)
    }

    // ========================================================================
    // SELECT statement parser
    // ========================================================================

    /// Top-level entry for `select : selectSetStmt | selectStmt`. Handles
    /// `UNION`/`INTERSECT`/`EXCEPT` chains plus top-level `ORDER BY` /
    /// `LIMIT` / `OFFSET` that decorate the whole set.
    pub(crate) fn peek_is_clause_terminator(&self) -> bool {
        // Group/Order on their own are identifier-like per the grammar
        // (e.g. a column literally named `group`); they only terminate a
        // column list when followed by `BY`. The two-token form lives
        // in `peek_is_two_token_clause_terminator`.
        let is_clause_kw = matches!(
            self.peek(),
            TokenKind::Keyword(Kw::From)
                | TokenKind::Keyword(Kw::Where)
                | TokenKind::Keyword(Kw::Prewhere)
                | TokenKind::Keyword(Kw::Having)
                | TokenKind::Keyword(Kw::Qualify)
                | TokenKind::Keyword(Kw::Window)
                | TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                | TokenKind::Keyword(Kw::Settings)
        );
        // A clause keyword that has no valid body following it isn't
        // actually starting a clause — cpp falls back to parsing it as
        // a Field identifier in column position. We mirror that by not
        // terminating on the keyword. The "no valid body" set covers:
        // - explicit list-terminators (Eof / `)` / `,` / `;`)
        // - another clause keyword (its own body would have to start
        //   with that, which it can't — clause keywords aren't
        //   expression / table-reference starters)
        // - select-level keywords like `WITH (TOTALS|CUBE|ROLLUP)` /
        //   `GROUP BY` / `USING SAMPLE` that lead with what would
        //   otherwise be a clause keyword.
        if is_clause_kw && !peek_can_start_clause_body(self.peek_next()) {
            return false;
        }
        // Even when peek_next looks like it could begin a body, the
        // *combined* peek_next + the token after may form a known
        // two-token clause introducer (`WITH ROLLUP`, `GROUP BY`,
        // `WITH FILL`, `USING SAMPLE`, `ARRAY JOIN`). When that
        // happens, the current clause keyword has no body of its own
        // and should be parsed as a Field. Use a shadow-lexer probe
        // to peek one more token ahead.
        if is_clause_kw && self.peek_after_starts_two_token_clause() {
            return false;
        }
        // `OFFSET *`: bare-asterisk OFFSET only sticks as the actual
        // OFFSET clause when `*` ends cleanly (end-of-clause, or
        // followed by COLUMNS|EXCLUDE|REPLACE + `(`). With anything
        // else following the `*`, cpp reads `OFFSET * <rhs>` as
        // `offset_field * <rhs>` arithmetic, so OFFSET is a Field
        // identifier rather than a clause introducer.
        // `<clause-kw> *`: bare-asterisk only sticks as the clause body
        // when `*` ends cleanly (end-of-clause / asterisk-companion).
        // With a multiplication-RHS following, the clause-kw is a Field
        // identifier instead. Applies to OFFSET / WHERE / PREWHERE /
        // HAVING / QUALIFY / FROM — any clause taking a single columnExpr
        // as its body.
        if matches!(
            self.peek(),
            TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Where)
                | TokenKind::Keyword(Kw::Prewhere)
                | TokenKind::Keyword(Kw::Having)
                | TokenKind::Keyword(Kw::Qualify)
                | TokenKind::Keyword(Kw::From)
        ) && self.peek_next() == TokenKind::Asterisk
            && self.asterisk_after_offset_continues_arith()
        {
            return false;
        }
        // `WINDOW` only opens the WINDOW clause when a `<name> AS
        // LParen` (the windowExpr definition) follows. Otherwise the
        // WINDOW keyword is a Field identifier in the column list.
        // The probe covers any name token (`window x …`, `window from
        // …`) — `WINDOW from events` is `window` the Field followed by
        // a FROM clause, not a malformed WINDOW clause.
        if self.peek() == TokenKind::Keyword(Kw::Window)
            && !self.window_ident_followed_by_as_lparen()
        {
            return false;
        }
        // `FROM`'s clause body is a `joinExpr` — a table reference,
        // not a `columnExpr` — so it only opens the FROM clause when a
        // table-reference starter follows: an identifier, `(`
        // subquery, `{}` placeholder, or a hogqlx `<` tag. `from + 1`
        // / `from 5` keep `from` as a Field column. (Empty `from ()`
        // is already caught as a call by the two-token probe above.)
        if self.peek() == TokenKind::Keyword(Kw::From)
            && !matches!(
                self.peek_next(),
                TokenKind::Ident
                    | TokenKind::QuotedIdent
                    | TokenKind::Keyword(_)
                    | TokenKind::LParen
                    | TokenKind::LBrace
                    | TokenKind::Lt
            )
        {
            return false;
        }
        is_clause_kw || self.peek_is_two_token_clause_terminator()
    }

    /// Probe: after `WINDOW <ident>`, do `AS LParen` follow? cpp's
    /// WINDOW clause requires the windowExpr in parens, so without
    /// that pair the WINDOW keyword falls back to a Field identifier
    /// in the column list (and the ident is its alias).
    fn window_ident_followed_by_as_lparen(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let t = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        if t.kind != TokenKind::Keyword(Kw::As) {
            return false;
        }
        let next = match probe.next_token() {
            Ok(t) => t,
            Err(_) => return false,
        };
        next.kind == TokenKind::LParen
    }

    /// Probe: after `OFFSET *`, does the token after `*` mean the
    /// asterisk is the LHS of arithmetic (so OFFSET is a Field) rather
    /// than a clean asterisk-spread expression terminating the clause?
    fn asterisk_after_offset_continues_arith(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let p3 = match probe.next_token() {
            Ok(t) => t.kind,
            Err(_) => return false,
        };
        match p3 {
            TokenKind::Eof
            | TokenKind::RParen
            | TokenKind::RBracket
            | TokenKind::RBrace
            | TokenKind::Comma
            | TokenKind::Semicolon => false,
            TokenKind::Keyword(Kw::Columns)
            | TokenKind::Keyword(Kw::Exclude)
            | TokenKind::Keyword(Kw::Replace) => {
                let p4 = match probe.next_token() {
                    Ok(t) => t.kind,
                    Err(_) => return false,
                };
                p4 != TokenKind::LParen
            }
            // A pure infix / postfix operator after `*` cannot be a
            // multiplication RHS — `* ?.` / `* ::` is the asterisk
            // spread extended by the postfix op, so the `*` does NOT
            // continue arithmetic and the clause keyword stays a
            // clause (`qualify * ?. q`).
            _ if is_pure_infix_op(p3) => false,
            // A clause-starting keyword after `*` also can't be a
            // multiplication RHS — it's the next clause beginning, and
            // the `*` here is a bare-asterisk clause body
            // (`where * limit 1`, `having * with totals`, …).
            TokenKind::Keyword(
                Kw::From
                | Kw::Where
                | Kw::Prewhere
                | Kw::Having
                | Kw::Qualify
                | Kw::Window
                | Kw::Limit
                | Kw::Offset
                | Kw::Group
                | Kw::Order
                | Kw::Union
                | Kw::Intersect
                | Kw::Except
                | Kw::Settings
                | Kw::With,
            ) => false,
            _ => true,
        }
    }

    /// Probe: do peek_next + the token after it form one of the
    /// two-token clause introducers? Same set as
    /// `peek_is_two_token_clause_terminator` checks, but with the
    /// match offset by one — used to decide whether the *current*
    /// clause keyword has a real body or whether the body's leading
    /// token is itself the start of a sibling clause.
    fn peek_after_starts_two_token_clause(&self) -> bool {
        let p1 = self.peek_next();
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let p2 = match probe.next_token() {
            Ok(t) => t.kind,
            Err(_) => return false,
        };
        // GROUP BY / ORDER BY
        if matches!(
            p1,
            TokenKind::Keyword(Kw::Group) | TokenKind::Keyword(Kw::Order)
        ) && p2 == TokenKind::Keyword(Kw::By)
        {
            return true;
        }
        // WITH (TOTALS | CUBE | ROLLUP | FILL)
        if p1 == TokenKind::Keyword(Kw::With)
            && matches!(
                p2,
                TokenKind::Keyword(Kw::Totals)
                    | TokenKind::Keyword(Kw::Cube)
                    | TokenKind::Keyword(Kw::Rollup)
                    | TokenKind::Keyword(Kw::Fill),
            )
        {
            return true;
        }
        // USING SAMPLE
        if p1 == TokenKind::Keyword(Kw::Using) && p2 == TokenKind::Keyword(Kw::Sample) {
            return true;
        }
        // ARRAY JOIN, LEFT/INNER ARRAY
        if p1 == TokenKind::Keyword(Kw::Array) && p2 == TokenKind::Keyword(Kw::Join) {
            return true;
        }
        if matches!(
            p1,
            TokenKind::Keyword(Kw::Left) | TokenKind::Keyword(Kw::Inner)
        ) && p2 == TokenKind::Keyword(Kw::Array)
        {
            return true;
        }
        // `SAMPLE <ratio>` — the SELECT-level sampleClause slot. cpp's
        // visitor silently drops it but still recognises the clause
        // boundary, so the preceding clause keyword should be a Field.
        if p1 == TokenKind::Keyword(Kw::Sample)
            && matches!(
                p2,
                TokenKind::Number
                    | TokenKind::Plus
                    | TokenKind::Dash
                    | TokenKind::Dot
                    | TokenKind::LBrace
                    | TokenKind::Keyword(Kw::Inf)
                    | TokenKind::Keyword(Kw::Nan),
            )
        {
            return true;
        }
        // `LIMIT <expr>` / `OFFSET <expr>` — single-token clause
        // introducers when followed by a real expression starter that's
        // not itself another clause keyword. cpp's ALL(*) prefers the
        // FROM-clause + trailing-clause shape when the third token is
        // itself a clause-introducer (e.g. `FROM limit prewhere x` parses
        // as `FROM table=limit PREWHERE x`, not `FROM identifier + LIMIT
        // expr=prewhere + leftover x`). For a non-clause expression
        // starter (Number, Ident, `*`, `#`, etc.) the LIMIT/OFFSET path
        // wins.
        if matches!(
            p1,
            TokenKind::Keyword(Kw::Limit) | TokenKind::Keyword(Kw::Offset)
        ) && peek_can_start_clause_body(p2)
            && !is_clause_introducer_kw(p2)
        {
            return true;
        }
        // `WHERE`/`PREWHERE`/`HAVING`/`QUALIFY` followed by a token
        // that can't be an alias on the FROM table (Hash, Asterisk,
        // Number, String, LBrace, …). cpp's ALL(*) drops the FROM-as-
        // table interpretation in this case (no valid alias slot for
        // the predicate-clause's first token) and treats the prior FROM
        // as a Field, with WHERE/etc. as the actual clause.
        if matches!(
            p1,
            TokenKind::Keyword(Kw::Where)
                | TokenKind::Keyword(Kw::Prewhere)
                | TokenKind::Keyword(Kw::Having)
                | TokenKind::Keyword(Kw::Qualify)
        ) && !can_be_table_continuation(p2)
            && peek_can_start_clause_body(p2)
            && !is_clause_introducer_kw(p2)
        {
            return true;
        }
        // `<clause-kw> ( )` — empty parens after a clause keyword
        // is a function-call form on the keyword as identifier (cpp's
        // ALL(*) emits `Call(name="from", args=[])` etc.). Empty parens
        // can't open a valid clause body for FROM / WHERE / etc., so
        // the surrounding clause keyword falls back to a Field.
        // Exception: `( ) ->` is a zero-arg lambda parameter list — a
        // valid clause body (`LIMIT () -> 2`) — so the keyword stays a
        // clause introducer there.
        if p1 == TokenKind::LParen && p2 == TokenKind::RParen {
            let p3 = probe.next_token().map(|t| t.kind).unwrap_or(TokenKind::Eof);
            if p3 != TokenKind::Arrow {
                return true;
            }
        }
        // `UNION` / `INTERSECT` / `EXCEPT` followed by a select-stmt
        // starter or set-op modifier — the set operator binds the
        // preceding clause keyword (FROM, etc.) to a Field identifier
        // so the set op can chain a sibling select. cpp's ALL(*) for
        // \`from UNION select 2\` produces a SelectSetQuery with FROM
        // promoted into the column list.
        if matches!(
            p1,
            TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
        ) && matches!(
            p2,
            TokenKind::Keyword(Kw::Select)
                | TokenKind::Keyword(Kw::With)
                | TokenKind::Keyword(Kw::All)
                | TokenKind::Keyword(Kw::Distinct)
                | TokenKind::Keyword(Kw::By)
                | TokenKind::LParen
                | TokenKind::LBrace
        ) {
            return true;
        }
        false
    }

    /// Two-token sequences that introduce a SELECT-stmt clause and
    /// thus terminate a column-expression list when seen after a
    /// trailing comma. Kept separate from the single-token cases above
    /// because the FIRST token of each pair (`USING`, `ARRAY`, `LEFT`,
    /// etc.) is also legitimately usable as a bare identifier or
    /// expression in other contexts.
    pub(crate) fn peek_is_two_token_clause_terminator(&self) -> bool {
        let p0 = self.peek();
        let p1 = self.peek_next();
        // `USING SAMPLE` — second select-level SAMPLE position.
        if p0 == TokenKind::Keyword(Kw::Using) && p1 == TokenKind::Keyword(Kw::Sample) {
            return true;
        }
        // `ARRAY JOIN`, `LEFT ARRAY`, `INNER ARRAY` — array-join prefix.
        if p0 == TokenKind::Keyword(Kw::Array) && p1 == TokenKind::Keyword(Kw::Join) {
            return true;
        }
        if matches!(
            p0,
            TokenKind::Keyword(Kw::Left) | TokenKind::Keyword(Kw::Inner)
        ) && p1 == TokenKind::Keyword(Kw::Array)
        {
            return true;
        }
        // ORDER BY / GROUP BY — when the second token is `BY`, the
        // first token introduces a clause. Bare `Group`/`Order` may
        // appear as identifiers in column position (e.g. a literally-
        // named `group` column), so we require the pair.
        if matches!(
            p0,
            TokenKind::Keyword(Kw::Group) | TokenKind::Keyword(Kw::Order)
        ) && p1 == TokenKind::Keyword(Kw::By)
        {
            return true;
        }
        // `SAMPLE <ratio>` — the selectStmt-level sampleClause slot
        // (silently dropped by cpp's visitor). ANTLR's ALL(*)
        // disambiguates `sample` as a Field vs the start of the
        // sampleClause by the second token: a ratio-value starter
        // (number, sign, `.<digits>`, `{placeholder}`, `inf`/`nan`)
        // means clause.
        if p0 == TokenKind::Keyword(Kw::Sample)
            && matches!(
                p1,
                TokenKind::Number
                    | TokenKind::Plus
                    | TokenKind::Dash
                    | TokenKind::Dot
                    | TokenKind::LBrace
                    | TokenKind::Keyword(Kw::Inf)
                    | TokenKind::Keyword(Kw::Nan)
            )
        {
            return true;
        }
        // `WITH TOTALS`, `WITH CUBE`, `WITH ROLLUP`, `WITH FILL` —
        // selectStmt's `(WITH (CUBE|ROLLUP))? (WITH TOTALS)?` trailers
        // and orderBy's `WITH FILL`. The bare `WITH` token also starts
        // a CTE list, but only at the *very* start of a SELECT — by
        // the time we're past the column list, a `WITH <ident>` after
        // it can't be a CTE.
        if p0 == TokenKind::Keyword(Kw::With)
            && matches!(
                p1,
                TokenKind::Keyword(Kw::Totals)
                    | TokenKind::Keyword(Kw::Cube)
                    | TokenKind::Keyword(Kw::Rollup)
                    | TokenKind::Keyword(Kw::Fill),
            )
        {
            return true;
        }
        false
    }

    pub(crate) fn parse_expr_list_until_paren(&mut self) -> Result<Vec<E::Value>, ParseError> {
        let mut out = Vec::new();
        if self.peek() == TokenKind::RParen {
            return Ok(out);
        }
        loop {
            out.push(self.parse_expr_bp(0)?);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if self.peek() == TokenKind::RParen {
                break;
            }
        }
        Ok(out)
    }

    pub(crate) fn parse_expr_list_until_terminators(
        &mut self,
    ) -> Result<Vec<E::Value>, ParseError> {
        let mut out = Vec::new();
        out.push(self.parse_expr_bp(0)?);
        // cpp's `columnExprList: columnExpr (COMMA columnExpr)*` — after
        // each comma ANTLR's adaptive lookahead decides whether the
        // upcoming tokens form another columnExpr or whether the comma
        // was trailing (and the next clause starts).
        //
        // When `peek_is_clause_terminator()` fires after a comma the
        // keyword can still be the next list item — cpp resolves the
        // ambiguity in favour of another `columnExpr`, even a bare
        // keyword-as-Field one (`GROUP BY a, window` keeps `window` as
        // the second column, not the start of a WINDOW clause). The
        // comma is only trailing when treating the keyword as a column
        // would strand a clause body — which the post-parse boundary
        // check below catches: `, FROM t` parses `from` as a Field but
        // leaves the cursor on `t` (not a list boundary), and
        // `, LIMIT (1) by (2)` parses `LIMIT(1)` but leaves it on `by`.
        while self.eat(TokenKind::Comma)? {
            if matches!(
                self.peek(),
                TokenKind::Eof | TokenKind::RParen | TokenKind::Semicolon
            ) {
                break;
            }
            if self.peek_is_clause_terminator() {
                // Speculatively parse the next item; accept it only
                // when the post-parse cursor lands on a clean
                // `columnExprList` boundary. Otherwise cpp's adaptive
                // prediction would have treated the comma as trailing
                // and dispatched the keyword as the next clause.
                let cp = self.checkpoint();
                let speculated = match self.parse_expr_bp(0) {
                    Ok(_) if !self.peek_is_column_expr_list_boundary() => {
                        self.restore(cp)?;
                        None
                    }
                    Ok(expr) => Some(expr),
                    Err(_) => {
                        self.restore(cp)?;
                        None
                    }
                };
                match speculated {
                    Some(expr) => out.push(expr),
                    None => break,
                }
            } else {
                out.push(self.parse_expr_bp(0)?);
            }
        }
        Ok(out)
    }

    /// True when peek is a valid boundary AFTER a generic
    /// `columnExprList` item in a SELECT context: structural
    /// terminator, comma (next item), or any keyword that cpp's
    /// adaptive prediction would consider as the start of a sibling
    /// clause (FROM, WHERE, HAVING, ORDER, GROUP, LIMIT, OFFSET,
    /// WINDOW, QUALIFY, SETTINGS, set operators). Crucially does NOT
    /// include `BY` alone — that token following a successfully-
    /// parsed expression item indicates the speculative parse
    /// over-consumed (e.g. `LIMIT (1)` absorbed `LIMIT` as a Field
    /// when `LIMIT (1) by (2)` was the intended LIMIT-BY clause).
    pub(crate) fn peek_is_column_expr_list_boundary(&self) -> bool {
        matches!(
            self.peek(),
            TokenKind::Eof
                | TokenKind::RParen
                | TokenKind::RBracket
                | TokenKind::RBrace
                | TokenKind::Comma
                | TokenKind::Semicolon
                | TokenKind::Keyword(Kw::From)
                | TokenKind::Keyword(Kw::Where)
                | TokenKind::Keyword(Kw::Prewhere)
                | TokenKind::Keyword(Kw::Having)
                | TokenKind::Keyword(Kw::Qualify)
                | TokenKind::Keyword(Kw::Window)
                | TokenKind::Keyword(Kw::Order)
                | TokenKind::Keyword(Kw::Group)
                | TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Settings)
                | TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                | TokenKind::Keyword(Kw::With)
                // USING is included for the SELECT-level USING SAMPLE
                // clause that can follow GROUP BY (per the grammar's
                // `sampleClause` at line 144). It's also the JOIN-USING
                // and ARRAY-JOIN-USING introducer, both of which end
                // any columnExprList that was being parsed.
                | TokenKind::Keyword(Kw::Using)
        )
    }

    // parse_with_expr_list / parse_with_expr / parse_with_expr_subquery
    // live in `cte.rs`.

    /// One item inside a parametric type's paren list: either a nested type
    /// (`Tuple(Int, String)`), a `field type` pair (`Struct(a Int, b
    /// String)`), or a numeric / expression parameter (`Decimal(10, 2)`,
    /// `FixedString(8)`).
    fn parse_type_param_item(&mut self) -> Result<String, ParseError> {
        // `IDENT TYPE` nested struct field: an ident at peek0 followed
        // by another type-starting token at peek1 (but not a `(` —
        // that's a parametric type, not a field). Speculative — the
        // shape `case when …`, `if expr …` etc. trips this matcher
        // (both `case` and `when` are admissible identifiers), so we
        // require the inner type-parse to land cleanly at a `,` / `)`
        // terminator before committing. On failure, restore and fall
        // through to the heuristic + speculative-type-expr branches
        // below, which route the expression form to spaceless raw
        // text.
        // The nested-struct heuristic (`field type`) routes through cpp's
        // `identifier identifier+` grammar, which excludes NULL / INF /
        // NAN from the keyword alternative. Filter both peek positions.
        let is_type_ident_kind = |k: TokenKind| -> bool {
            matches!(k, TokenKind::Ident | TokenKind::QuotedIdent)
                || matches!(k, TokenKind::Keyword(kw) if kw_valid_as_identifier(kw))
        };
        if is_type_ident_kind(self.peek())
            && is_type_ident_kind(self.peek_next())
            && self.peek_next() != TokenKind::LParen
        {
            let cp = self.checkpoint();
            let name_tok = self.bump()?;
            let raw = self.text(name_tok);
            // Unquote QuotedIdents the same way parse_type_atom does
            // for the head token — the cpp visitor resolves both
            // through `visitIdentifier`, so quotes are stripped.
            let field_name = match name_tok.kind {
                TokenKind::QuotedIdent => identifier_text(raw, name_tok.kind).to_ascii_lowercase(),
                _ => raw.to_ascii_lowercase(),
            };
            match self.parse_type_expr() {
                Ok(type_str) if matches!(self.peek(), TokenKind::Comma | TokenKind::RParen) => {
                    return Ok(format!("{field_name} {type_str}"));
                }
                _ => self.restore(cp)?,
            }
        }
        // The grammar declares the parametric-type alternatives in this
        // order: Nested, Complex, Param. ANTLR tries each alt in turn.
        // The group-level `group_is_param_mode` pre-classifier has already
        // routed obvious Param shapes (any depth-0 `#1` / `{}` / literal /
        // operator across the whole paren group) to the raw-text path;
        // by the time we reach here we know the group "looks like Complex/
        // Nested", so we try `parse_type_expr` first.
        //
        // A type-expr success only counts when it consumes the whole
        // param — i.e. lands on a `,` / `)` terminator. `case when (c)
        // then d end` happens to start `case when (c)` in a way that
        // `parse_type_expr`'s compound + param-list loops accept as a
        // pseudo-type `case when(c)`, then chokes on `then` instead of
        // a terminator. Restore and treat as expression in that case,
        // matching cpp's ANTLR fallback to the Param alt.
        let cp = self.checkpoint();
        match self.parse_type_expr() {
            Ok(name) if matches!(self.peek(), TokenKind::Comma | TokenKind::RParen) => Ok(name),
            _ => {
                self.restore(cp)?;
                self.consume_raw_type_param_text()
            }
        }
    }

    /// Scan the whole `IDENT(...)` group and decide whether ANTLR would
    /// commit to `ColumnTypeExprParam` (items are `columnExpr`, visited
    /// via `ctx->getText()`) vs Complex/Nested (items are recursive
    /// `columnTypeExpr`, visited with `, ` joining). Looks for **depth-0
    /// only** expression markers — markers at deeper levels belong to a
    /// nested sub-type's own classification (e.g. `Foo(FixedString(8))`
    /// keeps Foo in Complex even though `8` appears at depth 1).
    fn group_is_param_mode(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let mut depth: i32 = 0;
        for _ in 0..4096 {
            let Ok(t) = probe.next_token() else {
                return false;
            };
            match t.kind {
                TokenKind::Eof => return false,
                // End of this group — no Param markers found, stay in
                // Complex/Nested mode. Commas at depth 0 are item
                // separators; we keep scanning for the next item.
                TokenKind::RParen if depth == 0 => return false,
                TokenKind::LBrace if depth == 0 => return true,
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => depth -= 1,
                // Depth-0 expression-only tokens force Param mode for the
                // whole group: literals, positional refs, and any binary
                // / unary operator surrounded by item tokens.
                TokenKind::String
                | TokenKind::TemplateString
                | TokenKind::Number
                | TokenKind::Hash
                | TokenKind::Plus
                | TokenKind::Dash
                | TokenKind::Slash
                | TokenKind::Percent
                | TokenKind::Asterisk
                | TokenKind::Dot
                | TokenKind::EqDouble
                | TokenKind::EqSingle
                | TokenKind::NotEq
                | TokenKind::Lt
                | TokenKind::LtEq
                | TokenKind::Gt
                | TokenKind::GtEq
                | TokenKind::Arrow
                | TokenKind::ColonEquals
                | TokenKind::Concat
                | TokenKind::Nullish
                    if depth == 0 =>
                {
                    return true;
                }
                _ => {}
            }
        }
        false
    }

    /// Collect the concatenated token text of a single type-param
    /// entry, with paren-depth tracking; stop at the next top-level
    /// comma or closing paren. Mirrors the cpp visitor's recursive
    /// output for parametric types:
    ///
    /// - Tokens are concatenated without intervening whitespace,
    ///   matching ANTLR's `getText()` (which sees the hidden-channel
    ///   whitespace as absent).
    /// - **Except** between two adjacent identifier-like tokens, where
    ///   we insert a single space. This preserves `Compound`-form CTs
    ///   like `a b` / `time with time zone` whose visitor explicitly
    ///   joins parts with spaces.
    /// - Trailing commas at any depth (i.e. immediately before a
    ///   matching close) are dropped, since the cpp visitor's
    ///   columnExprList iteration never emits the separator token.
    fn consume_raw_type_param_text(&mut self) -> Result<String, ParseError> {
        // Mirrors ANTLR's `ctx.getText()` on `ColumnTypeExprParam`:
        // join every token verbatim with no separator at all
        // (whitespace is on a hidden channel and dropped). So
        // `case when (c) then d end` → `casewhen(c)thendend`,
        // `if((c), d, e)` → `if((c),d,e)`. Stops at the param's own
        // depth-0 `,` or `)` terminator. Trailing commas at any depth
        // (i.e. immediately before a matching close) are dropped,
        // since the cpp recursive visit skips them. Every token's
        // original input text is used verbatim — case is preserved
        // (`ABC` stays `ABC`) and QuotedIdents keep their quotes
        // (`"a"` stays `"a"`).
        let mut out = String::new();
        let mut depth: i32 = 0;
        loop {
            let kind = self.peek();
            match kind {
                TokenKind::Eof => break,
                TokenKind::Comma | TokenKind::RParen if depth == 0 => break,
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => {
                    depth += 1;
                    let t = self.bump()?;
                    out.push_str(self.text(t));
                }
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    depth -= 1;
                    let t = self.bump()?;
                    out.push_str(self.text(t));
                }
                TokenKind::Comma => {
                    self.bump()?;
                    if !matches!(
                        self.peek(),
                        TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace
                    ) {
                        out.push(',');
                    }
                }
                // The cpp `columnTypeExpr` grammar routes identifier-
                // shaped tokens through the `identifier` rule, which
                // omits NULL / INF / NAN. A bare `Int NULL` inside
                // `Tuple(Int NULL)` would error at the outer paren in
                // cpp because the inner type couldn't extend through
                // the NULL keyword. Rust's raw-text fallback used to
                // happily concatenate `IntNULL` and emit a malformed
                // type name. Reject the forbidden keywords as soon as
                // they appear at any depth.
                TokenKind::Keyword(kw) if !kw_valid_as_identifier(kw) => {
                    return Err(
                        self.err(format!("unexpected `{:?}` keyword in type expression", kw))
                    );
                }
                _ => {
                    let t = self.bump()?;
                    out.push_str(self.text(t));
                }
            }
        }
        Ok(out)
    }

    pub(crate) fn parse_arg_list(
        &mut self,
        terminator: TokenKind,
    ) -> Result<Vec<E::Value>, ParseError> {
        let mut args = Vec::new();
        if self.peek() == terminator {
            return Ok(args);
        }
        loop {
            args.push(self.parse_call_argument()?);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if self.peek() == terminator {
                break;
            }
        }
        Ok(args)
    }

    /// One argument in a function call's argument list. Supports the named
    /// argument shape `ident := expr` which is grammar-bound to call sites,
    /// and a `SELECT …` subquery (`f(select 1)`) which the grammar's
    /// `ColumnExprCallSelect` allows.
    fn parse_call_argument(&mut self) -> Result<E::Value, ParseError> {
        // Default caller: `parse_arg_list`, which is the postfix `(...)`
        // form (cpp's `ColumnExprCallSelect`). The grammar there admits
        // a selectSetStmt as the entire body — including its
        // wrapper-level `orderByClause?` — so DON'T suppress trailing
        // ORDER BY consumption. The named-call form
        // (`parse_function_args_inner`) uses `parse_call_argument_for_function`
        // instead, which DOES suppress so the ORDER BY surfaces on the
        // outer `Call.order_by` per cpp's `ColumnExprFunction`
        // preference.
        self.parse_call_argument_with(false)
    }

    /// Call-argument parse used by `parse_function_args_inner` — the
    /// named-function-call form (cpp's `ColumnExprFunction`). Here
    /// cpp's ANTLR prefers Function over CallSelect (grammar lines 236
    /// vs 237), so a trailing `ORDER BY` after the inner paren-wrapped
    /// SELECT belongs to the outer `Call.order_by`, not the inner
    /// SetStmt wrapper.
    fn parse_call_argument_for_function(&mut self) -> Result<E::Value, ParseError> {
        self.parse_call_argument_with(true)
    }

    fn parse_call_argument_with(
        &mut self,
        suppress_inner_trailing_order_by: bool,
    ) -> Result<E::Value, ParseError> {
        // cpp's `ColumnExprNamedArg: identifier COLONEQUALS columnExpr`
        // admits the full `identifier` rule — IDENT / QUOTED_IDENTIFIER /
        // any keyword accepted by `kw_valid_as_identifier`. That includes
        // `true` / `false` (which cpp lexes as plain IDENTIFIERs) plus
        // any soft keyword that doubles as an identifier. The fast-path
        // here used to gate on IDENT / QUOTED_IDENTIFIER only, so
        // `f(true := 1)` fell through to `parse_expr_bp` and choked on
        // the trailing `:=`.
        let name_kw_ok =
            matches!(self.peek(), TokenKind::Keyword(kw) if kw_valid_as_identifier(kw));
        if (matches!(self.peek(), TokenKind::Ident | TokenKind::QuotedIdent) || name_kw_ok)
            && self.peek_next() == TokenKind::ColonEquals
        {
            let name_tok = self.bump()?;
            let name = identifier_text(self.text(name_tok), name_tok.kind);
            self.bump()?; // consume `:=`
            let value = self.parse_expr_bp(0)?;
            return Ok(self.emit.named_argument(&name, value));
        }
        // A function-call argument is either a selectSetStmt (cpp's
        // ColumnExprCallSelect) or a regular columnExpr. The grammar
        // arms overlap on leading `(` (paren-wrapped SELECT vs
        // paren-wrapped expression); try_alt commits to whichever
        // parses to a clean comma/RParen boundary.
        //
        // `parse_select_set_stmt` is permissive: a bare `{}` (empty
        // braces — Dict) hits the LBrace branch and returns a Dict
        // node, then the set-stmt's trailing-decorators handler
        // silently consumes any `ORDER BY` / `LIMIT` / `OFFSET` that
        // follows. cpp's grammar doesn't admit `{} ORDER BY ...` as
        // a valid selectSetStmt, so this misreads function-call
        // arg-list ORDER BY (`foo(x, {} order by z)`) as belonging to
        // the inner. Validate the result: only commit when it's an
        // actual select-set-stmt shape (SelectQuery, SelectSetQuery,
        // or a real Placeholder `{name}`).
        self.try_alt(&[
            &|p| p.parse_call_argument_select(suppress_inner_trailing_order_by),
            &|p| p.parse_expr_bp(0),
        ])
    }

    fn parse_call_argument_select(
        &mut self,
        suppress_trailing_order_by: bool,
    ) -> Result<E::Value, ParseError> {
        // Selectively suppress the SetStmt-wrapper-level ORDER BY when
        // the caller is the named-function-call path (cpp's
        // `ColumnExprFunction`). For the postfix call-select form
        // (`<expr>(<set-stmt>)`), cpp's `ColumnExprCallSelect` lets the
        // ORDER BY ride on the inner set-stmt's wrapper, so we leave
        // it alone in that path.
        let prev = self.suppress_setstmt_trailing_order_by;
        if suppress_trailing_order_by {
            self.suppress_setstmt_trailing_order_by = true;
        }
        let result = self.parse_select_set_stmt();
        self.suppress_setstmt_trailing_order_by = prev;
        let v = result?;
        let kind = self.emit.node_kind(&v);
        let kind = kind.as_deref();
        if matches!(
            kind,
            Some("SelectQuery") | Some("SelectSetQuery") | Some("Placeholder")
        ) {
            // The select-set-stmt arg must be complete here. If an infix
            // or postfix operator follows, the `{…}` placeholder or
            // `(…)` was only the operand of a larger columnExpr (e.g.
            // `f({x} = 1)`, `f((select 1) + 2)`, `f({x}[0])`, `f({x} as a)`),
            // so fail and let try_alt fall back to the columnExpr parse.
            // `infix_bp` covers the symbolic / AND / OR infixes; the
            // keyword infixes (`IN`, `LIKE`, `ILIKE`, `IS`, `BETWEEN`,
            // plus the `NOT <kw>` shapes) and the `AS alias` postfix
            // are dispatched directly out of the Pratt loop, so call
            // them out here too.
            let starts_kw_infix = matches!(
                self.peek(),
                TokenKind::Keyword(Kw::In | Kw::Like | Kw::Ilike | Kw::Is | Kw::Between | Kw::As)
            ) || (matches!(self.peek(), TokenKind::Keyword(Kw::Not))
                && matches!(
                    self.peek_next(),
                    TokenKind::Keyword(Kw::In | Kw::Like | Kw::Ilike | Kw::Between)
                ));
            if infix_bp(self.peek()).is_some()
                || postfix_bp(self.peek()).is_some()
                || starts_kw_infix
            {
                return Err(self.err("select-set-stmt call argument is followed by an operator"));
            }
            Ok(v)
        } else {
            // Bare Dict / anything else — let parse_expr_bp take over so
            // the trailing ORDER BY / LIMIT / OFFSET belong to the outer
            // function-args parser, not to a fake set-stmt.
            Err(self.err(format!(
                "parse_select_set_stmt returned {kind:?}, expected SelectQuery/SelectSetQuery/Placeholder"
            )))
        }
    }

    // ---- Postfix --------------------------------------------------------

    fn parse_postfix(&mut self, kind: TokenKind, lhs: E::Value) -> Result<E::Value, ParseError> {
        match kind {
            TokenKind::LParen => {
                self.bump()?;
                let args = self.parse_arg_list(TokenKind::RParen)?;
                self.expect(TokenKind::RParen, ")")?;
                Ok(fold_call_or_exprcall(&self.emit, lhs, args))
            }
            TokenKind::LBracket => {
                self.bump()?;
                // `arr[a:b]` / `arr[:b]` / `arr[a:]` / `arr[:]` — array
                // slice. Detected by a `:` either at the immediate start
                // or after the first expression.
                if self.peek() == TokenKind::Colon {
                    self.bump()?;
                    let end = if self.peek() == TokenKind::RBracket {
                        None
                    } else {
                        Some(self.parse_expr_bp(0)?)
                    };
                    self.expect(TokenKind::RBracket, "]")?;
                    return Ok(self.emit.array_slice(lhs, None, end));
                }
                let first = self.parse_expr_bp(0)?;
                if self.eat(TokenKind::Colon)? {
                    let end = if self.peek() == TokenKind::RBracket {
                        None
                    } else {
                        Some(self.parse_expr_bp(0)?)
                    };
                    self.expect(TokenKind::RBracket, "]")?;
                    return Ok(self.emit.array_slice(lhs, Some(first), end));
                }
                self.expect(TokenKind::RBracket, "]")?;
                Ok(self.emit.array_access(lhs, first, false))
            }
            TokenKind::DoubleColon => {
                self.bump()?;
                // The grammar's `columnTypeCastExpr` only admits a
                // restricted keyword set (IDENTIFIER, QUOTED_IDENTIFIER,
                // the eight `interval` unit keywords, and DATE / TIME /
                // TIMESTAMP / INTERVAL), optionally followed by
                // `WITH (LOCAL)? TIME ZONE`. Reject anything outside
                // that — otherwise `1::with` would silently parse as a
                // TypeCast to a `with` type name.
                let tok = self.bump()?;
                let name = match tok.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(tok), tok.kind).to_ascii_lowercase()
                    }
                    TokenKind::Keyword(kw) if kw_valid_type_cast_ident(kw) => {
                        self.text(tok).to_ascii_lowercase()
                    }
                    _ => {
                        return Err(ParseError::syntax(
                            format!(
                                "invalid type cast target {:?} (a reserved keyword cannot be used as a type name here)",
                                tok.kind,
                            ),
                            tok.start, tok.end,
                        ));
                    }
                };
                // Only consume `WITH` for the cast suffix when the full
                // `WITH (LOCAL)? TIME ZONE` shape follows. cpp's ALL(*)
                // lookahead rejects this alternative on a bare `WITH`,
                // leaving e.g. a trailing `WITH FILL` (an ORDER BY
                // modifier) for the enclosing clause to claim.
                let full = if self.peek_is_with_time_zone() {
                    self.bump()?; // WITH
                    let mut suffix = String::from(" with");
                    if self.eat_kw(Kw::Local)? {
                        suffix.push_str(" local");
                    }
                    self.expect_kw(Kw::Time, "TIME")?;
                    self.expect_kw(Kw::Zone, "ZONE")?;
                    suffix.push_str(" time zone");
                    format!("{name}{suffix}")
                } else {
                    name
                };
                Ok(self.emit.type_cast(lhs, &full))
            }
            TokenKind::Dot => {
                self.bump()?;
                let part = self.bump()?;
                match part.kind {
                    TokenKind::Number => {
                        // cpp's lexer matches `0123` as OCTAL_PREFIX_LITERAL,
                        // not DECIMAL_LITERAL — so a leading-zero multi-digit
                        // index is grammatically rejected at the tuple-access
                        // alt. Rust's lexer collapses both forms into one
                        // `Number` token and used to silently re-parse it as
                        // decimal (`a.0123` → TupleAccess(a, 123)).
                        let text = self.text(part);
                        if text.len() > 1 && text.starts_with('0') && !text.contains('.') {
                            return Err(self
                                .err(format!("expected decimal integer after '.', got {text:?}")));
                        }
                        let n: i64 = text.parse().map_err(|_| {
                            self.err(format!("expected integer after '.', got {:?}", text))
                        })?;
                        Ok(self.emit.tuple_access(lhs, n, false))
                    }
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        let name = identifier_text(self.text(part), part.kind);
                        Ok(self.emit.array_access(
                            lhs,
                            self.emit.constant(self.emit.string(&name)),
                            false,
                        ))
                    }
                    // Grammar (`identifier: IDENTIFIER | QUOTED_IDENTIFIER |
                    // interval | keyword`) — `keyword` excludes NULL/INF/
                    // NAN/EXCEPT/INTERSECT and the Hog-statement keywords
                    // (FN/FUN/LET/WHILE/THROW/TRY/CATCH/FINALLY). Gate
                    // every chain-link keyword through `kw_valid_as_identifier`
                    // so e.g. `a.null` / `a.fn` reject instead of becoming
                    // `ArrayAccess(a, "null")`.
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        let name = identifier_text(self.text(part), part.kind);
                        Ok(self.emit.array_access(
                            lhs,
                            self.emit.constant(self.emit.string(&name)),
                            false,
                        ))
                    }
                    _ => Err(self.err(format!(
                        "expected identifier or number after '.', got {:?}",
                        part.kind
                    ))),
                }
            }
            TokenKind::NullProperty => {
                self.bump()?;
                // `?.[expr]` is the bracketed nullish form.
                if self.peek() == TokenKind::LBracket {
                    self.bump()?;
                    let property = self.parse_expr_bp(0)?;
                    self.expect(TokenKind::RBracket, "]")?;
                    return Ok(self.emit.array_access(lhs, property, true));
                }
                let part = self.bump()?;
                match part.kind {
                    TokenKind::Number => {
                        // Same OCTAL_PREFIX_LITERAL vs DECIMAL_LITERAL
                        // split as the regular `.<N>` branch above.
                        let text = self.text(part);
                        if text.len() > 1 && text.starts_with('0') && !text.contains('.') {
                            return Err(self.err(format!(
                                "expected decimal integer after '?.', got {text:?}"
                            )));
                        }
                        let n: i64 = text.parse().map_err(|_| {
                            self.err(format!("expected integer after '?.', got {:?}", text))
                        })?;
                        Ok(self.emit.tuple_access(lhs, n, true))
                    }
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        let name = identifier_text(self.text(part), part.kind);
                        Ok(self.emit.array_access(
                            lhs,
                            self.emit.constant(self.emit.string(&name)),
                            true,
                        ))
                    }
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        let name = identifier_text(self.text(part), part.kind);
                        Ok(self.emit.array_access(
                            lhs,
                            self.emit.constant(self.emit.string(&name)),
                            true,
                        ))
                    }
                    _ => Err(self.err(format!(
                        "expected identifier or number after '?.', got {:?}",
                        part.kind
                    ))),
                }
            }
            _ => unreachable!("postfix_bp returned for unhandled token {:?}", kind),
        }
    }

    /// Consume the optional `COHORT` marker on `IN COHORT <expr>` /
    /// `NOT IN COHORT <expr>`. cpp's grammar (`(NOT)? IN COHORT?
    /// columnExpr`) routes through adaptive prediction: it only takes
    /// the `COHORT?` alternative when a `columnExpr` follows. If the
    /// next token can't start a columnExpr (EOF / `,` / `)` / `;` / a
    /// clause-keyword terminator like FROM / LIMIT / WHERE / GROUP /
    /// ORDER / HAVING / SETTINGS / UNION / ...), the bare `cohort`
    /// keyword is the IN rhs identifier instead — cpp emits
    /// `Compare(lhs, "in", Field([cohort]))`. Rust used to greedily
    /// eat COHORT and then choke parsing an empty rhs.
    fn try_consume_cohort_marker(&mut self) -> Result<bool, ParseError> {
        if self.peek() != TokenKind::Keyword(Kw::Cohort) {
            return Ok(false);
        }
        let next = self.peek_next();
        // Hard terminators that obviously can't begin an expression.
        let hard_terminator = matches!(
            next,
            TokenKind::Eof
                | TokenKind::Comma
                | TokenKind::RParen
                | TokenKind::RBracket
                | TokenKind::RBrace
                | TokenKind::Semicolon
        );
        // Clause-keyword introducers that terminate a columnExpr in the
        // outer SELECT context. Mirror the set in `peek_is_clause_terminator`.
        let clause_kw = matches!(
            next,
            TokenKind::Keyword(Kw::From)
                | TokenKind::Keyword(Kw::Where)
                | TokenKind::Keyword(Kw::Prewhere)
                | TokenKind::Keyword(Kw::Having)
                | TokenKind::Keyword(Kw::Qualify)
                | TokenKind::Keyword(Kw::Window)
                | TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                | TokenKind::Keyword(Kw::Settings)
                | TokenKind::Keyword(Kw::Order)
                | TokenKind::Keyword(Kw::Group)
        );
        if hard_terminator || clause_kw {
            return Ok(false);
        }
        self.bump()?;
        Ok(true)
    }

    // ---- Multi-token / context-sensitive infix --------------------------

    /// Returns `Some(true)` if it consumed and produced an infix.
    /// `Some(false)` is reserved for "we matched but didn't act — break"
    /// (currently unused). `None` means no special infix matched.
    fn try_special_infix(
        &mut self,
        kind: TokenKind,
        lhs: &mut E::Value,
        min_bp: u8,
        lhs_start: usize,
    ) -> Result<Option<bool>, ParseError> {
        match kind {
            // `IS [NOT] NULL` / `IS [NOT] DISTINCT FROM e`. The two
            // `IGNORE NULLS` — postfix modifier the cpp visitor
            // silently drops (`visitColumnExprIgnoreNulls` just returns
            // the inner expression). Gated at BP_IGNORE_NULLS so it
            // attaches at the same precedence as the grammar's
            // declaration order (tighter than IS NULL, looser than
            // arithmetic/compare). A trailing `(...)` postfix on a
            // larger expression like `a * b IGNORE NULLS ()` ends up
            // wrapping the whole `a * b`, not just `b`.
            TokenKind::Keyword(Kw::Ignore) if self.peek_next() == TokenKind::Keyword(Kw::Nulls) => {
                if BP_IGNORE_NULLS < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                self.bump()?;
                Ok(Some(true))
            }
            // shapes have different precedences in the grammar — IS NULL
            // is declared first and so binds tighter. Disambiguate via
            // bounded lookahead (peek past an optional NOT for DISTINCT)
            // so each shape uses its own BP for the `< min_bp` gate.
            TokenKind::Keyword(Kw::Is) => {
                // cpp's grammar admits IS only in two shapes: `x IS [NOT] NULL`
                // (ColumnExprIsNull) and `x IS [NOT] DISTINCT FROM y`. When
                // neither follows (e.g. Hog program source like `this is a
                // string`, where `is` is a bare identifier-statement),
                // ANTLR's ALL(*) lookahead backs off and lets each token
                // start its own ExprStatement. Mirror that: only commit
                // when the next-two tokens form a known IS-tail, otherwise
                // return None so the caller can stop the Pratt loop.
                let (is_distinct_form, is_null_form) = match self.peek_next() {
                    TokenKind::Keyword(Kw::Null) => (false, true),
                    TokenKind::Keyword(Kw::Distinct) => (true, false),
                    TokenKind::Keyword(Kw::Not) => {
                        // Look one further for `NOT NULL` / `NOT DISTINCT`.
                        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                        match probe.next_token().ok().map(|t| t.kind) {
                            Some(TokenKind::Keyword(Kw::Null)) => (false, true),
                            Some(TokenKind::Keyword(Kw::Distinct)) => (true, false),
                            _ => (false, false),
                        }
                    }
                    _ => (false, false),
                };
                if !is_distinct_form && !is_null_form {
                    return Ok(None);
                }
                let op_bp = if is_distinct_form {
                    BP_IS_DISTINCT_FROM
                } else {
                    BP_IS_NULL
                };
                if op_bp < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                let negated = self.eat_kw(Kw::Not)?;
                if self.eat_kw(Kw::Distinct)? {
                    self.expect_kw(Kw::From, "FROM")?;
                    // Left-associative + admit IS-NULL inside: RHS at
                    // BP_IS_DISTINCT_FROM + 1 lets `b IS NOT NULL`
                    // chain (since BP_IS_NULL > BP_IS_DISTINCT_FROM)
                    // but blocks a second IS NOT DISTINCT FROM.
                    let rhs = self.parse_expr_bp(BP_IS_DISTINCT_FROM + 1)?;
                    let prev = std::mem::replace(lhs, self.emit.null());
                    *lhs = self.emit.is_distinct_from(prev, rhs, negated);
                    return Ok(Some(true));
                }
                self.expect_kw(Kw::Null, "NULL")?;
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.compare_is_null(prev, negated);
                Ok(Some(true))
            }
            // `NOT BETWEEN ...` / `NOT IN ...` / `NOT LIKE ...` / `NOT ILIKE ...`
            TokenKind::Keyword(Kw::Not) => match self.peek_next() {
                TokenKind::Keyword(Kw::Between) => {
                    if BP_BETWEEN < min_bp {
                        return Ok(None);
                    }
                    self.bump()?;
                    self.bump()?;
                    let (low, high, hoisted) = self.parse_between_body(min_bp)?;
                    let prev = std::mem::replace(lhs, self.emit.null());
                    // Wrap the inner BetweenExpr with positions BEFORE the hoist loop. When a hoist
                    // wrapper (Or / Ternary / Alias / Arith) is applied, the outer pratt-loop wrap_pos
                    // at line ~126 stamps positions onto the OUTERMOST wrapper, but the BetweenExpr
                    // is now buried inside (e.g. as `Call(if, [BetweenExpr, …])` for the ternary hoist)
                    // and would not otherwise receive a span. cpp emits position info on BetweenExpr
                    // unconditionally — match that. Use `high.end` (not `last_consumed_end`) — see
                    // the BETWEEN arm below for the rationale.
                    let high_end = self.emit.get_field(&high, "end");
                    let between_inner = self.emit.between(prev, low, high, true);
                    let mut between = match high_end {
                        Some(end) => {
                            self.emit
                                .with_pos(between_inner, self.pos_obj(lhs_start), end)
                        }
                        None => self.wrap_pos(between_inner, lhs_start),
                    };
                    for hoist in hoisted {
                        between = apply_between_hoist(&self.emit, between, hoist);
                    }
                    *lhs = between;
                    Ok(Some(true))
                }
                TokenKind::Keyword(Kw::In) => {
                    if BP_COMPARE < min_bp {
                        return Ok(None);
                    }
                    self.bump()?;
                    self.bump()?;
                    let cohort = self.try_consume_cohort_marker()?;
                    let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
                    let op = if cohort { "not in cohort" } else { "not in" };
                    let prev = std::mem::replace(lhs, self.emit.null());
                    *lhs = self.emit.compare(prev, op, rhs);
                    Ok(Some(true))
                }
                TokenKind::Keyword(Kw::Like) => {
                    if BP_COMPARE < min_bp {
                        return Ok(None);
                    }
                    self.bump()?;
                    self.bump()?;
                    let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
                    let prev = std::mem::replace(lhs, self.emit.null());
                    *lhs = self.emit.compare(prev, "not like", rhs);
                    Ok(Some(true))
                }
                TokenKind::Keyword(Kw::Ilike) => {
                    if BP_COMPARE < min_bp {
                        return Ok(None);
                    }
                    self.bump()?;
                    self.bump()?;
                    let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
                    let prev = std::mem::replace(lhs, self.emit.null());
                    *lhs = self.emit.compare(prev, "not ilike", rhs);
                    Ok(Some(true))
                }
                _ => Ok(None),
            },
            // `[e] BETWEEN low AND high`
            TokenKind::Keyword(Kw::Between) => {
                if BP_BETWEEN < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                let (low, high, hoisted) = self.parse_between_body(min_bp)?;
                let prev = std::mem::replace(lhs, self.emit.null());
                // The inner BetweenExpr's structural end is `high.end`, not `self.last_consumed_end`.
                // When `parse_between_body`'s WIDE arm absorbs a nested BETWEEN and the split hoists
                // it back out (`BetweenHoist::Between`), `last_consumed_end` is past the high we'll
                // actually use; mirror cpp's per-ctx span by reading the end off `high` directly.
                let high_end = self.emit.get_field(&high, "end");
                let between_inner = self.emit.between(prev, low, high, false);
                let mut between = match high_end {
                    Some(end) => self
                        .emit
                        .with_pos(between_inner, self.pos_obj(lhs_start), end),
                    None => self.wrap_pos(between_inner, lhs_start),
                };
                for hoist in hoisted {
                    between = apply_between_hoist(&self.emit, between, hoist);
                }
                *lhs = between;
                Ok(Some(true))
            }
            // `[e] IN ...` (plain, no NOT)
            TokenKind::Keyword(Kw::In) => {
                if BP_COMPARE < min_bp {
                    return Ok(None);
                }
                // The structural `IN` separating a PIVOT/UNPIVOT
                // operand from its `( columnExprList )` values — yield
                // it back so the caller consumes it.
                if Some(self.peek0.start) == self.pivot_in_stop {
                    return Ok(None);
                }
                self.bump()?;
                let cohort = self.try_consume_cohort_marker()?;
                let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
                let op = if cohort { "in cohort" } else { "in" };
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.compare(prev, op, rhs);
                Ok(Some(true))
            }
            TokenKind::Keyword(Kw::Like) => {
                if BP_COMPARE < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.compare(prev, "like", rhs);
                Ok(Some(true))
            }
            TokenKind::Keyword(Kw::Ilike) => {
                if BP_COMPARE < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.compare(prev, "ilike", rhs);
                Ok(Some(true))
            }
            // `e IGNORE NULLS` is a postfix that the C++ visitor drops
            // entirely — the expression returns as-is. Detect via two-token
            // peek so we don't accidentally consume `IGNORE` mid-stream.
            TokenKind::Keyword(Kw::Ignore) if self.peek_next() == TokenKind::Keyword(Kw::Nulls) => {
                if BP_IS_NULL < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                self.bump()?;
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.ignore_nulls(prev);
                Ok(Some(true))
            }

            // Ternary `? a : b` (right-assoc; rhs recurses at the same bp).
            TokenKind::QMark => {
                if BP_TERNARY < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                let then_branch = self.parse_expr_bp(0)?;
                self.expect(TokenKind::Colon, ":")?;
                let else_branch = self.parse_expr_bp(BP_TERNARY)?;
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.call("if", vec![prev, then_branch, else_branch]);
                Ok(Some(true))
            }
            // `AS alias`
            TokenKind::Keyword(Kw::As) => {
                if BP_ALIAS < min_bp {
                    return Ok(None);
                }
                // Bail when this AS is the CAST argument separator —
                // the columnExpr ends here and the CAST grammar
                // consumes the AS itself.
                if Some(self.peek0.start) == self.cast_as_stop {
                    return Ok(None);
                }
                // The alias-target slot is restricted to identifier /
                // quoted-identifier / string literal (per grammar). The
                // grammar's `identifier` rule excludes a set of reserved
                // keywords (NULL/INF/NAN/EXCEPT/INTERSECT and the Hog-
                // statement keywords) which `kw_valid_as_identifier`
                // mirrors. TRUE/FALSE are also excluded but the existing
                // `is_reserved_alias_name` check inside the fold raises
                // a more specific "cannot be an alias" error for them,
                // so we admit them through the gate and let the inner
                // check produce that error. NULL is in both sets but the
                // gate yields a useful error too.
                let next_is_alias_target = match self.peek_next() {
                    TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::String => true,
                    TokenKind::Keyword(kw) => {
                        kw_valid_as_identifier(kw) || matches!(kw, Kw::True | Kw::False | Kw::Null)
                    }
                    _ => false,
                };
                if !next_is_alias_target {
                    return Ok(None);
                }
                // `LAMBDA` after `AS` always starts a `lambdaExpr`
                // (`LAMBDA identifier (COMMA identifier)* COMMA?
                // COLON columnExpr`), not an alias name. cpp's ALL(*)
                // sees the lambda body's `:` and backtracks the alias
                // alt; Pratt can't, so refuse the alias here so the
                // outer `INTERPOLATE (expr AS columnExpr)` form picks
                // the AS up itself.
                if matches!(self.peek_next(), TokenKind::Keyword(Kw::Lambda)) {
                    return Ok(None);
                }
                // `AS <ident> ->` is the arrow-form lambda. The single
                // ident would otherwise look like a valid alias name,
                // but it's actually the lambda's parameter list. Same
                // ALL(*) backtrack reasoning as above.
                if matches!(self.peek_next(), TokenKind::Ident | TokenKind::Keyword(_)) {
                    if let Ok(probe_tok) = {
                        let mut lex = Lexer::with_pos(self.src, self.peek1.end);
                        lex.next_token()
                    } {
                        if probe_tok.kind == TokenKind::Arrow {
                            return Ok(None);
                        }
                    }
                }
                self.bump()?;
                let tok = self.bump()?;
                let raw = self.text(tok);
                let name = match tok.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
                        identifier_text(raw, tok.kind)
                    }
                    TokenKind::String => unquote_single_string(raw),
                    _ => {
                        return Err(self.err(format!("expected alias after AS, got {:?}", tok.kind)))
                    }
                };
                // Reject unquoted reserved-keyword aliases. Quoted forms
                // (`"true"` / `` `true` ``) opt out of the keyword check.
                let is_quoted = matches!(tok.kind, TokenKind::QuotedIdent | TokenKind::String);
                if !is_quoted && is_reserved_alias_name(&name) {
                    // C++ ANTLR spans this error from the start of the
                    // aliased expression through the alias token, matching
                    // the visitor's reported error range.
                    return Err(ParseError::syntax(
                        format!(
                            "\"{raw}\" cannot be an alias or identifier, as it's a reserved keyword"
                        ),
                        lhs_start,
                        tok.end,
                    ));
                }
                let prev = std::mem::replace(lhs, self.emit.null());
                *lhs = self.emit.alias(prev, &name);
                Ok(Some(true))
            }
            _ => Ok(None),
        }
    }

    /// Parse the body of a BETWEEN (`<low> AND <high>`). cpp's grammar
    /// at line 285 is `columnExpr NOT? BETWEEN columnExpr AND columnExpr`,
    /// left-recursive; the line-284 TODO acknowledges cpp's resolution is
    /// "rightmost AND in body is the separator." Across body shapes:
    ///
    ///   `a BETWEEN b AND c AND d`               → low=And(b,c), high=d
    ///   `a NOT BETWEEN b AND c OR d`            → low=b, high=Or(c,d)
    ///   `a BETWEEN y AS alias AND high`         → low=Alias(y,alias), high=high
    ///   `a BETWEEN lambda y : a AND b AND high` → low=Lambda(y, And(a,b)), high=high
    ///   `a BETWEEN x ? y : c AND high`          → low=if(x,y,c), high=high
    ///   `a BETWEEN name := value AND high`      → low=NamedArg(name,value), high=high
    ///   `a BETWEEN b AND c ? then : else`       → if(BETWEEN(a,b,c), then, else)
    ///   `a NBT b AND c NBT 4 AND 5`             → BETWEEN(BETWEEN(a,b,c), 4, 5)
    ///
    /// Strategy: `try_alt` between two alternatives that cover this set.
    ///
    /// **Narrow alt** (`BP_BETWEEN + 1`): the body parse stops at any
    /// operator with BP ≤ BP_BETWEEN — that's `TERNARY` (20), `ALIAS`
    /// (10), and BETWEEN itself (30). Everything tighter (AND, OR,
    /// comparison, arithmetic) chains into the body. The split then
    /// peels the rightmost AND.
    ///
    /// The narrow alt handles the trailing-construct cases cleanly:
    /// `a BTWN b AND c ? then : else` — body stops at `?`, returns
    /// (b, c); the outer Pratt loop applies the ternary OUTSIDE the
    /// BetweenExpr.  `a NBT b AND c NBT 4 AND 5` — body stops at the
    /// second NBT, returns (b, c); the outer Pratt loop chains a
    /// second BETWEEN with the first as `.expr`. This is what made the
    /// `BetweenWrap` machinery unnecessary.
    ///
    /// **Wide alt** (`BP = 0`): handles the cases where the construct
    /// carrying the rightmost AND lives INSIDE the body — lambda's
    /// expression slot (`lambda y : a AND b AND high`), named-arg's
    /// value (`name := value AND high`), AS-alias's expression (`y AS
    /// alias AND high`), ternary's else-arm (`x ? y : c AND high`).
    /// `parse_expr_bp(0)` absorbs the lower-precedence wrappers; the
    /// split's descent rules in `split_at_rightmost_and` then walk
    /// into them to find the rightmost AND.
    ///
    /// Both alts share the same post-parse split + literal-AND
    /// fallback; the difference is just the starting BP.
    fn parse_between_body(
        &mut self,
        outer_min_bp: u8,
    ) -> Result<BetweenSplit<E::Value>, ParseError> {
        // Depth-aware arm ordering:
        //   - OUTERMOST call (depth=0): WIDE first. The body greedy
        //     parse maximizes what's inside the OUTER BETWEEN; split
        //     reassociates via low-peel / expr-hoist / alias-hoist /
        //     ternary-hoist to produce cpp's shape.
        //   - NESTED call (depth>=1): NARROW first. Inside an outer
        //     body parse, a nested BETWEEN must NOT consume the outer's
        //     trailing ternary / AND / etc. — cpp's left-recursive
        //     grammar gives each nested BETWEEN the SHORTEST body that
        //     lets the chain succeed.
        //
        // Arm ordering plus a hoist-compatibility filter on the WIDE
        // arm together model cpp's ANTLR ALL(*) "longest-parse-that-
        // lets-outer-succeed". WIDE explores the maximum body extent
        // (BP=0). If the resulting split's hoist contains a wrapper
        // whose precedence is below the outer context's `outer_min_bp`,
        // the WIDE arm REJECTS — the outer context owns that wrapper.
        // Example: in `x ? a : b BETWEEN c AND d AS al` with
        // outer_min_bp=BP_TERNARY=20, WIDE absorbs `c AND d AS al`,
        // splits to `(c, d, [Alias('al')])`. Alias' BP_ALIAS=10 <= 20,
        // so the WIDE alt rejects and the next narrower arm runs at
        // BP_ALIAS+1=11 (floored by outer_min_bp), which doesn't
        // absorb AS — letting the outer Pratt apply Alias(if(...),
        // al). For `... AS al AND y` (with a trailing AND), WIDE's
        // split gives `(Alias(And(c,d), al), y, [])` — empty hoist,
        // commit.
        self.between_body_depth += 1;
        let alt_bps: [u8; 3] = if self.between_body_depth == 1 {
            [0, BP_ALIAS + 1, BP_BETWEEN + 1]
        } else {
            [BP_BETWEEN + 1, BP_ALIAS + 1, 0]
        };
        // Narrower arms still respect outer_min_bp via flooring — they
        // serve as the fallback when WIDE rejects. WIDE itself is
        // intentionally UN-floored so its hoist-compatibility check
        // is the sole disambiguator at the top of the arm chain.
        let floored: [u8; 3] = [
            alt_bps[0],
            alt_bps[1].max(outer_min_bp),
            alt_bps[2].max(outer_min_bp),
        ];
        let result = self.try_alt(&[
            &|p| Self::parse_between_body_arm_wide(p, floored[0], outer_min_bp),
            &|p| Self::parse_between_body_arm(p, floored[1]),
            &|p| Self::parse_between_body_arm(p, floored[2]),
        ]);
        self.between_body_depth -= 1;
        result
    }

    /// Wide-arm wrapper: parses at the unfloored BP, then post-filters
    /// the split's hoist by `outer_min_bp`. A hoist of type X with BP <=
    /// outer_min_bp means the outer context wants to apply X itself,
    /// not have it inside BETWEEN's hoist chain — so we REJECT this
    /// arm and let `try_alt` fall to the next (narrower, floored) arm.
    fn parse_between_body_arm_wide(
        &mut self,
        start_bp: u8,
        outer_min_bp: u8,
    ) -> Result<BetweenSplit<E::Value>, ParseError> {
        let (low, high, hoisted) = Self::parse_between_body_arm(self, start_bp)?;
        if hoisted.iter().any(|h| hoist_min_bp(h) <= outer_min_bp) {
            return Err(
                self.err("WIDE body hoist conflicts with outer precedence; falling through")
            );
        }
        Ok((low, high, hoisted))
    }

    /// Shared body of `parse_between_body`'s two `try_alt` arms,
    /// parameterized by the starting binding power. See
    /// `parse_between_body` for the narrow/wide rationale.
    fn parse_between_body_arm(
        &mut self,
        start_bp: u8,
    ) -> Result<BetweenSplit<E::Value>, ParseError> {
        let chain = self.parse_expr_bp(start_bp)?;
        if let Some((low, high, hoisted)) = split_at_rightmost_and(&self.emit, &chain) {
            return Ok((low, high, hoisted));
        }
        // The body had no AND that the split could find — consume the
        // mandatory literal AND and parse `high` directly. Reached for
        // shapes like `a BETWEEN b AND c` parsed with the narrow alt
        // where the body parse stopped at the AND (BP_AND=50 vs
        // start_bp=31, both alts admit AND, so this branch is mostly a
        // safety net for inputs where the rightmost-AND descent fails).
        self.expect_kw(Kw::And, "AND")?;
        let high = self.parse_expr_bp(BP_BETWEEN + 1)?;
        Ok((chain, high, Vec::new()))
    }
}

/// Can `tok` plausibly begin a CASE body? CASE accepts an optional
/// scrutinee expression then `WHEN`. So a body-starter is either an
/// expression starter or the WHEN keyword itself.
fn can_start_case_body(tok: TokenKind) -> bool {
    if tok == TokenKind::Keyword(Kw::When) {
        return true;
    }
    peek_can_start_clause_body(tok) && !is_pure_infix_op(tok)
}

/// Can `tok` plausibly begin an INTERVAL value? Either an expression
/// starter (Number, Ident, etc.) or a string literal (the combined
/// `INTERVAL '5 day'` form).
fn can_start_interval_value(tok: TokenKind) -> bool {
    matches!(tok, TokenKind::String) || (peek_can_start_clause_body(tok) && !is_pure_infix_op(tok))
}

/// Is `tok` a pure infix operator that can never start an expression?
/// Used to disambiguate keyword-as-Field from special-form-keyword:
/// `interval := 5` should fall back to the named-argument identifier
/// path because `:=` can't open an INTERVAL value, and similar for
/// comparison / equality operators.
fn is_pure_infix_op(tok: TokenKind) -> bool {
    matches!(
        tok,
        TokenKind::ColonEquals
            | TokenKind::EqDouble
            | TokenKind::EqSingle
            | TokenKind::NotEq
            | TokenKind::Lt
            | TokenKind::LtEq
            | TokenKind::Gt
            | TokenKind::GtEq
            | TokenKind::Slash
            | TokenKind::Percent
            | TokenKind::RegexSingle
            | TokenKind::RegexDouble
            | TokenKind::IRegexSingle
            | TokenKind::IRegexDouble
            | TokenKind::NotRegex
            | TokenKind::NotIRegex
            | TokenKind::Concat
            | TokenKind::Nullish
            | TokenKind::Arrow
            | TokenKind::DoubleColon
            | TokenKind::Dot
            | TokenKind::NullProperty
    )
}

/// Can `tok` legitimately continue a FROM table reference — as an
/// alias (Ident / QuotedIdent / alias-permitted keyword), an explicit
/// `AS` keyword, table-function args (`(`), JOIN-chain prefix, or a
/// FINAL / SAMPLE decoration? Used to detect when a FROM table cannot
/// take its next token as a continuation, in which case cpp's ANTLR
/// backtracks and treats the FROM as a Field identifier (so the
/// following clause keyword introduces the actual clause).
fn can_be_table_continuation(tok: TokenKind) -> bool {
    match tok {
        TokenKind::Ident
        | TokenKind::QuotedIdent
        | TokenKind::LParen
        | TokenKind::Comma
        | TokenKind::Keyword(Kw::As)
        | TokenKind::Keyword(Kw::Final)
        | TokenKind::Keyword(Kw::Sample)
        | TokenKind::Keyword(Kw::Join)
        | TokenKind::Keyword(Kw::Inner)
        | TokenKind::Keyword(Kw::Outer)
        | TokenKind::Keyword(Kw::Left)
        | TokenKind::Keyword(Kw::Right)
        | TokenKind::Keyword(Kw::Full)
        | TokenKind::Keyword(Kw::Cross)
        | TokenKind::Keyword(Kw::Anti)
        | TokenKind::Keyword(Kw::Semi)
        | TokenKind::Keyword(Kw::Asof)
        | TokenKind::Keyword(Kw::Natural)
        | TokenKind::Keyword(Kw::On)
        | TokenKind::Keyword(Kw::Using)
        | TokenKind::Keyword(Kw::Pivot)
        | TokenKind::Keyword(Kw::Unpivot) => true,
        // Alias-permitted keywords per kw_allowed_as_implicit_alias.
        TokenKind::Keyword(
            Kw::Ascending
            | Kw::Cohort
            | Kw::Date
            | Kw::Descending
            | Kw::Id
            | Kw::Return
            | Kw::Top
            | Kw::Totals,
        ) => true,
        _ => false,
    }
}

/// Is `tok` a keyword that, in clause position, normally introduces
/// a SELECT clause? Used to gate the FROM+LIMIT/OFFSET disambiguation:
/// `FROM limit prewhere x` keeps FROM as the clause (PREWHERE is a
/// clause-introducer that wouldn't be a LIMIT-expression body), but
/// `FROM limit 5` flips FROM to a Field because `5` clearly fills the
/// LIMIT body.
fn is_clause_introducer_kw(tok: TokenKind) -> bool {
    matches!(
        tok,
        TokenKind::Keyword(Kw::From)
            | TokenKind::Keyword(Kw::Where)
            | TokenKind::Keyword(Kw::Prewhere)
            | TokenKind::Keyword(Kw::Having)
            | TokenKind::Keyword(Kw::Qualify)
            | TokenKind::Keyword(Kw::Group)
            | TokenKind::Keyword(Kw::Order)
            | TokenKind::Keyword(Kw::Window)
            | TokenKind::Keyword(Kw::Limit)
            | TokenKind::Keyword(Kw::Offset)
            | TokenKind::Keyword(Kw::Sample)
            | TokenKind::Keyword(Kw::Settings)
            | TokenKind::Keyword(Kw::Union)
            | TokenKind::Keyword(Kw::Intersect)
            | TokenKind::Keyword(Kw::Except)
            | TokenKind::Keyword(Kw::Using)
            | TokenKind::Keyword(Kw::On)
            | TokenKind::Keyword(Kw::Join)
            | TokenKind::Keyword(Kw::Inner)
            | TokenKind::Keyword(Kw::Outer)
            | TokenKind::Keyword(Kw::Left)
            | TokenKind::Keyword(Kw::Right)
            | TokenKind::Keyword(Kw::Full)
            | TokenKind::Keyword(Kw::Cross)
            | TokenKind::Keyword(Kw::Anti)
            | TokenKind::Keyword(Kw::Semi)
            | TokenKind::Keyword(Kw::Asof)
            | TokenKind::Keyword(Kw::Natural)
            | TokenKind::Keyword(Kw::Rollup)
            | TokenKind::Keyword(Kw::Cube)
            | TokenKind::Keyword(Kw::Grouping)
            | TokenKind::Keyword(Kw::Sets)
            | TokenKind::Keyword(Kw::Final)
    )
}

/// Could `tok` plausibly begin the body of a clause that the preceding
/// clause keyword introduces? Conservative — returns `true` for any
/// expression-starter / table-reference-starter, and `false` for hard
/// list-terminators and other clause keywords. Used to distinguish
/// "real clause start" from "this clause keyword is acting as a
/// Field identifier" in column-position lookahead.
fn peek_can_start_clause_body(tok: TokenKind) -> bool {
    match tok {
        // Hard list-terminators — never a clause body.
        TokenKind::Eof
        | TokenKind::RParen
        | TokenKind::RBracket
        | TokenKind::RBrace
        | TokenKind::Comma
        | TokenKind::Semicolon => false,
        // Another clause keyword can't start the previous clause's
        // body — the previous keyword must be a Field. (`BY` is
        // whitelisted because some clause keywords legitimately have
        // it as their second token, e.g. `LIMIT a BY b` body.)
        TokenKind::Keyword(kw) => {
            matches!(
                kw,
                // Expression-starter keywords — fine as clause body.
                Kw::Case
                    | Kw::Cast
                    | Kw::TryCast
                    | Kw::Lambda
                    | Kw::Interval
                    | Kw::Columns
                    | Kw::Not
                    | Kw::True
                    | Kw::False
                    | Kw::Null
                    | Kw::Inf
                    | Kw::Nan
                    | Kw::Distinct
                    | Kw::Array
                    | Kw::Trim
                    | Kw::Select
                    | Kw::With
                    | Kw::By
                    | Kw::Recursive
            ) || crate::parse::kw_acts_as_ident_in_primary(kw)
        }
        // A pure infix / postfix operator token (`?.`, `::`, `%`,
        // `=`, `->`, `.`, …) can never *start* a clause body — it
        // needs a left operand. (`+` / `-` / `*` are excluded from
        // `is_pure_infix_op` since they double as prefix / spread, so
        // they stay valid starters.)
        _ if is_pure_infix_op(tok) => false,
        // Everything else (Number, String, Ident, LParen, LBracket,
        // LBrace, +/-, * (asterisk-spread), `#` placeholder, …) is a
        // fine starter.
        _ => true,
    }
}

/// One outer wrapper that the caller of `parse_between_body` should
/// apply around the built BetweenExpr, in order (innermost first).
/// Used to reassemble cpp's shape when Pratt's greedy body parse
/// absorbed something that cpp's left-recursive grammar would have
/// folded OUTSIDE the BETWEEN.
///
/// - `Alias(name)` — `BETWEEN body AND high AS alias` puts the alias
///   on the BetweenExpr (BETWEEN binds tighter than alias-postfix).
/// - `Between { low, high, negated }` — chained `<X> BETWEEN body1
///   AND high1 BETWEEN body2 AND high2` builds left-recursively, so
///   the SECOND BETWEEN wraps the FIRST. When the FIRST's body parse
///   greedily consumed the second BETWEEN, we hoist the second out
///   to be applied to the outer BetweenExpr the caller will build.
/// - `Ternary { then_branch, else_branch }` — `(BETWEEN body AND
///   high) ? then : else` parses with BETWEEN binding tighter than
///   ternary, so the ternary wraps the BetweenExpr. When the body
///   parse absorbed the AND inside an if-call's cond (`if(And(low,
///   high), then, else)`), we hoist the ternary's then/else out to
///   wrap the BetweenExpr the caller builds.
#[derive(Debug, Clone)]
pub(crate) enum BetweenHoist<V> {
    Alias(String),
    Between {
        low: V,
        high: V,
        negated: bool,
    },
    Ternary {
        then_branch: V,
        else_branch: V,
    },
    /// `Or(left_siblings ... , <expr>, right_siblings ...)` —  the
    /// greedy body parse absorbed an OR whose AND-carrying child sits
    /// inside a looser wrapper (Alias / Lambda / NamedArg / Ternary).
    /// cpp's left-recursive grammar treats the wrapper as terminating
    /// BETWEEN's high body, so the OR (and its siblings) become an
    /// outer wrapper around the alias-wrapped BetweenExpr.
    Or {
        left_siblings: Vec<V>,
        right_siblings: Vec<V>,
    },
    /// `IsDistinctFrom(<expr>, right, negated?)` — `BETWEEN body AND
    /// high AS al IS [NOT] DISTINCT FROM rhs` parses with the IS
    /// DISTINCT FROM as the OUTERMOST node when an AS-alias sits
    /// between BETWEEN's high and the IS DISTINCT FROM (the alias
    /// terminates BETWEEN's high body, and IS DISTINCT FROM applies
    /// to the alias-wrapped BetweenExpr).
    IsDistinctFrom {
        right: V,
        negated: bool,
    },
    /// `IsNull(<expr>, negated?)` — `BETWEEN body AND high AS al IS
    /// [NOT] NULL` has the same shape: alias terminates body, IS NULL
    /// applies to the alias-wrapped BetweenExpr.
    IsNull {
        negated: bool,
    },
    /// `ArrayAccess(<expr>, property, nullish?)` — postfix `[…]`,
    /// `.<ident>` (when re-rooted), or `?.<ident>` on top of an
    /// alias-wrapped BetweenExpr. cpp's `ColumnExprArrayAccess` /
    /// nullish-property forms apply at higher precedence than the
    /// alias-wrap; when the body parse absorbed the access along
    /// with the alias, we hoist it OUTSIDE the alias around the
    /// BetweenExpr.
    ArrayAccess {
        property: V,
        nullish: bool,
    },
    /// `ExprCall(<expr>, args)` — postfix `(<args>)` on top of the
    /// alias-wrapped BetweenExpr. cpp's `ColumnExprCall` at
    /// BP_POSTFIX=130 wraps OUTSIDE BetweenExpr (BP_BETWEEN=30);
    /// when the WIDE body parse absorbed the call along with an
    /// inner Alias / Lambda layer carrying the BETWEEN-separator AND,
    /// the ExprCall hoists out alongside the alias to wrap the
    /// final BetweenExpr.
    ExprCall {
        args: Vec<V>,
    },
    /// `TypeCast(<expr>, "<type-ident>")` — postfix `:: <type>` at
    /// BP_POSTFIX=130. Same hoisting rationale as ExprCall: the
    /// type-cast attaches OUTSIDE the BetweenExpr after the inner
    /// AND-bearing wrapper chain is peeled.
    TypeCast {
        type_name: String,
    },
    /// `TupleAccess(<tuple>, index, nullish?)` — postfix `.<NUMBER>`
    /// / `?.<NUMBER>` at BP_POSTFIX=130. Same hoisting rationale as
    /// ArrayAccess (which carries the `.<ident>` / `?.<ident>` /
    /// `[<expr>]` cases). cpp lowers the two postfix families to
    /// different nodes (`TupleAccess` vs `ArrayAccess`) so we keep
    /// them as separate hoist variants rather than collapsing.
    TupleAccess {
        index: i64,
        nullish: bool,
    },
    /// `ArithmeticOperation(<expr>, op, right)` — a binary arith op
    /// whose AND was buried in its LEFT side (typically via an
    /// alias-around-And chain inside the .left). The arith op
    /// attaches OUTSIDE the BetweenExpr after the alias-wrapped
    /// And-chain is peeled. (The MIRRORED case of arith with AND in
    /// its RIGHT — `between c and ({}) * lambda q : ... and 999999`
    /// — is handled by the `.right`-descent branch in
    /// `split_at_rightmost_and` which keeps the arith node in place
    /// rather than hoisting.)
    ArithmeticOperation {
        op: String,
        right: V,
    },
}

/// Result of finding the BETWEEN separator AND inside a greedy body
/// parse. `hoisted` wrappers are applied around the BetweenExpr by
/// the caller of `parse_between_body`, innermost first.
type BetweenSplit<V> = (V, V, Vec<BetweenHoist<V>>);

/// The lowest binding power at which this hoist's outer wrapper can
/// fire. Used by `parse_between_body_arm_wide` to detect when an
/// outer Pratt context (the parent caller of `parse_between_body`)
/// would itself claim the wrapper — in which case the WIDE arm must
/// reject so the wrapper attaches at the outer level instead of
/// being applied INSIDE the BETWEEN.
fn hoist_min_bp<V>(hoist: &BetweenHoist<V>) -> u8 {
    match hoist {
        BetweenHoist::Alias(_) => BP_ALIAS,
        BetweenHoist::Ternary { .. } => BP_TERNARY,
        BetweenHoist::Between { .. } => BP_BETWEEN,
        BetweenHoist::Or { .. } => BP_OR,
        BetweenHoist::IsDistinctFrom { .. } => BP_IS_DISTINCT_FROM,
        BetweenHoist::IsNull { .. } => BP_IS_NULL,
        BetweenHoist::ArrayAccess { .. } => BP_POSTFIX,
        BetweenHoist::ExprCall { .. } => BP_POSTFIX,
        BetweenHoist::TypeCast { .. } => BP_POSTFIX,
        BetweenHoist::TupleAccess { .. } => BP_POSTFIX,
        // Arith hoists conservatively assume MULT (the tightest of
        // the binary arith family). If the WIDE arm absorbed a /+
        // -/concat/mod with the AND inside its left, we'd still want
        // to hoist — using the lowest member (additive at 100) would
        // still be above BP_BETWEEN so the gating check rarely
        // affects this hoist either way.
        BetweenHoist::ArithmeticOperation { .. } => BP_ADDITIVE,
    }
}

/// Apply one outer wrapper around an in-progress BetweenExpr.
fn apply_between_hoist<E: Emitter>(
    emit: &E,
    expr: E::Value,
    hoist: BetweenHoist<E::Value>,
) -> E::Value {
    match hoist {
        BetweenHoist::Alias(name) => emit.alias(expr, &name),
        BetweenHoist::Between { low, high, negated } => emit.between(expr, low, high, negated),
        BetweenHoist::Ternary {
            then_branch,
            else_branch,
        } => emit.call("if", vec![expr, then_branch, else_branch]),
        BetweenHoist::Or {
            left_siblings,
            right_siblings,
        } => {
            let mut all: Vec<E::Value> = left_siblings;
            all.push(expr);
            all.extend(right_siblings);
            emit.or_(all)
        }
        BetweenHoist::IsDistinctFrom { right, negated } => {
            emit.is_distinct_from(expr, right, negated)
        }
        BetweenHoist::IsNull { negated } => emit.compare_is_null(expr, negated),
        BetweenHoist::ArrayAccess { property, nullish } => {
            emit.array_access(expr, property, nullish)
        }
        BetweenHoist::ExprCall { args } => emit.expr_call(expr, args),
        BetweenHoist::TypeCast { type_name } => {
            // Reconstruct the TypeCast node the WIDE parse produced.
            // Inner field is `expr`; the type identifier is on
            // `type_name` (per cpp's `VISIT(ColumnTypeExprSimple)` —
            // it deserialises to the Python dataclass field of the
            // same name).
            emit.type_cast(expr, &type_name)
        }
        BetweenHoist::TupleAccess { index, nullish } => {
            // cpp's `VISIT(ColumnExprTupleAccess)` emits the inner
            // expression on the `tuple` field, and the dot-number
            // index on `index`. Mirror that.
            emit.tuple_access(expr, index, nullish)
        }
        BetweenHoist::ArithmeticOperation { op, right } => emit.arith(expr, &op, right),
    }
}

/// Stamp `start` / `end` on a synthetic And/Or built by
/// `split_at_rightmost_and` from a slice of pre-positioned children.
/// `emit::and_` / `emit::or_` produce position-less JSON; an outer
/// `wrap_pos` would catch the BETWEEN-level wrap but not the inner
/// synthetic And/Or that lives inside BetweenExpr's `low` or `high`,
/// because BetweenExpr's `low` / `high` are direct fields (not nested
/// expressions that the pratt loop wraps). Derive the span from the
/// first child's `start` and the last child's `end` so the inner
/// synthetic node carries a non-null span.
fn stamp_span_from_children<E: Emitter>(
    emit: &E,
    node: E::Value,
    children: &[E::Value],
) -> E::Value {
    if children.is_empty() {
        return node;
    }
    let start = emit.get_field(&children[0], "start");
    let end = emit.get_field(&children[children.len() - 1], "end");
    if let (Some(s), Some(e)) = (start, end) {
        emit.replace_pos(node, s, e)
    } else {
        node
    }
}

/// Walk an already-parsed boolean tree to find the rightmost AND in
/// source order and split there. Returns `(left_of_and, right_of_and)`.
/// Used by `parse_between_body` to apply ANTLR's "rightmost AND is the
/// separator" resolution to a tree we built greedily.
///
/// Walking semantics:
/// - An `And` node IS the AND. Peel the last operand: `low =
///   And(exprs[:-1])` (collapsed when length 2), `high = exprs[-1]`.
/// - An `Or` node defers — walk children right-to-left so we find the
///   *latest* AND-bearing child. Reconstruct the Or above the split.
/// - Anything else has no AND in it; return None.
fn split_at_rightmost_and<E: Emitter>(emit: &E, node: &E::Value) -> Option<BetweenSplit<E::Value>> {
    let node_name = emit.node_kind(node);
    let node_name = node_name.as_deref();
    if node_name == Some("And") {
        let exprs = emit
            .get_field(node, "exprs")
            .and_then(|v| emit.as_list(&v))?;
        if exprs.len() < 2 {
            return None;
        }
        // Try descending the LAST element first — it may itself contain
        // a deeper AND that's the rightmost in source order. e.g.
        // `(a) * b AND c := d AND e` parses as
        // `And(Arith, NamedArg(c, And(d, e)))`; the rightmost source
        // AND is between `d` and `e` (inside NamedArg.value). cpp
        // splits there, leaving NamedArg.value=d and using `e` as the
        // outer high. Without this descent we'd just pop the last
        // element (NamedArg) wholesale and lose that AND.
        if let Some((deep_left, deep_right, hoisted)) =
            split_at_rightmost_and(emit, &exprs[exprs.len() - 1])
        {
            let mut new_exprs = exprs.clone();
            let last_idx = new_exprs.len() - 1;
            new_exprs[last_idx] = deep_left;
            let new_left = if new_exprs.len() == 1 {
                new_exprs.into_iter().next().unwrap()
            } else {
                let synthetic = emit.and_(new_exprs.clone());
                stamp_span_from_children(emit, synthetic, &new_exprs)
            };
            return Some((new_left, deep_right, hoisted));
        }
        // No deeper AND in the last element — pop it as the split.
        let mut exprs = exprs;
        let right = exprs.pop().unwrap();
        let left = if exprs.len() == 1 {
            exprs.pop().unwrap()
        } else {
            let synthetic = emit.and_(exprs.clone());
            stamp_span_from_children(emit, synthetic, &exprs)
        };
        return Some((left, right, Vec::new()));
    }
    if node_name == Some("Or") {
        let exprs = emit
            .get_field(node, "exprs")
            .and_then(|v| emit.as_list(&v))?;
        for i in (0..exprs.len()).rev() {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &exprs[i])
            {
                if hoisted.is_empty() {
                    // AND was found directly inside the Or's child (no
                    // looser-wrapper between them). cpp's grammar lets
                    // BETWEEN's high absorb the OR, so left/right
                    // children flow into the high alongside the descent
                    // result. `x BETWEEN low AND high OR rest` →
                    // BETWEEN(x, low, Or(high, rest)).
                    let mut left_children: Vec<E::Value> = exprs[..i].to_vec();
                    left_children.push(left_in);
                    let left = if left_children.len() == 1 {
                        left_children.pop().unwrap()
                    } else {
                        let synthetic = emit.or_(left_children.clone());
                        stamp_span_from_children(emit, synthetic, &left_children)
                    };
                    let mut right_children: Vec<E::Value> = Vec::with_capacity(exprs.len() - i);
                    right_children.push(right_in);
                    right_children.extend_from_slice(&exprs[i + 1..]);
                    let right = if right_children.len() == 1 {
                        right_children.pop().unwrap()
                    } else {
                        let synthetic = emit.or_(right_children.clone());
                        stamp_span_from_children(emit, synthetic, &right_children)
                    };
                    return Some((left, right, hoisted));
                }
                // The descent passed THROUGH a looser wrapper (Alias /
                // Lambda / NamedArg / Ternary). cpp treats the wrapper
                // as terminating BETWEEN's high body, so the OR (and
                // its siblings) hoist OUTSIDE the wrapper rather than
                // being absorbed into the high. Pushing the Or hoist
                // AFTER `hoisted` puts it OUTSIDE the wrappers the
                // descent has accumulated.
                let left_siblings: Vec<E::Value> = exprs[..i].to_vec();
                let right_siblings: Vec<E::Value> = exprs[i + 1..].to_vec();
                if !left_siblings.is_empty() || !right_siblings.is_empty() {
                    hoisted.push(BetweenHoist::Or {
                        left_siblings,
                        right_siblings,
                    });
                }
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // Wrappers whose rightmost expression slot can contain the AND
    // that ALL(*) treats as BETWEEN's separator. Recurse, then
    // reconstruct the wrapper around the left side; the right side
    // surfaces as BETWEEN's high.
    //
    // - Lambda.expr — bare-list / parens / colon lambda bodies.
    // - NamedArgument.value — `name := body AND high`.
    // - Call(name='if').args[2] — `cond ? then : else AND high` (the
    //   ternary lowers to an `if` call with else in args[2]).
    // - Alias.expr — `body AND high AS outer` (greedy parse wraps the
    //   AND in an Alias). cpp's grammar has BETWEEN at higher
    //   precedence than alias-postfix, so the alias goes OUTSIDE the
    //   BetweenExpr. Descend through the Alias and HOIST its name to
    //   the caller's outer-wrap list.
    if node_name == Some("Lambda") {
        if let Some(inner) = emit.get_field(node, "expr") {
            if let Some((left_in, right_in, hoisted)) = split_at_rightmost_and(emit, &inner) {
                let mut new_node = node.clone();
                emit.set_field(&mut new_node, "expr", left_in);
                return Some((new_node, right_in, hoisted));
            }
        }
    }
    // `Not(expr)` — same shape as Lambda. The AND-reservation context
    // for BETWEEN's body must pass *through* a NOT prefix into the
    // wrapped expression. `a BETWEEN NOT lambda x : b AND c` parses
    // as `Not(Lambda(x, And(b, c)))` greedily; descending into
    // `Not.expr` peels the AND off so the outer BETWEEN sees its own
    // `low = Not(Lambda(x, b))`, `high = c` split.
    if node_name == Some("Not") {
        if let Some(inner) = emit.get_field(node, "expr") {
            if let Some((left_in, right_in, hoisted)) = split_at_rightmost_and(emit, &inner) {
                let mut new_node = node.clone();
                emit.set_field(&mut new_node, "expr", left_in);
                return Some((new_node, right_in, hoisted));
            }
        }
    }
    // ArithmeticOperation has two slots that can carry the BETWEEN-
    // separator AND, and the two shapes need DIFFERENT handling:
    //
    // 1. AND in `.right` (typically buried under a BP-resetting
    //    wrapper like Lambda.expr or NamedArgument.value): the arith
    //    op STAYS in place wrapping a piece of the BETWEEN LOW.
    //    Example: `BETWEEN columns(*) AND {} * lambda q : ... AND
    //    999999` — the deepest source AND is inside Lambda's body
    //    under Mul.right; the Mul itself belongs to the LOW.
    //
    // 2. AND in `.left` (typically via an Alias-around-And chain
    //    inside the arith's left operand): the arith op HOISTS
    //    outside the BetweenExpr. Example: `BETWEEN (1) AS p AND 2
    //    AS al * y` — the rightmost AND is between `(1) as p` and
    //    `2 as al`; the trailing `* y` wraps the BetweenExpr after
    //    the inner alias's hoist applies.
    //
    // Try `.right` first (keep in place); on failure try `.left`
    // (hoist via BetweenHoist::ArithmeticOperation). The order
    // matters: when both slots could contain the AND (rare but
    // possible), cpp prefers the rightmost-in-source which lives in
    // `.right`.
    if node_name == Some("ArithmeticOperation") {
        if let Some(inner) = emit.get_field(node, "right") {
            if let Some((left_in, right_in, hoisted)) = split_at_rightmost_and(emit, &inner) {
                let mut new_node = node.clone();
                emit.set_field(&mut new_node, "right", left_in);
                return Some((new_node, right_in, hoisted));
            }
        }
        if let Some(inner) = emit.get_field(node, "left") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                let op = emit
                    .get_field(node, "op")
                    .and_then(|v| emit.as_str(&v).map(|s| s.into_owned()))
                    .unwrap_or_default();
                let right = emit.get_field(node, "right").unwrap_or_else(|| emit.null());
                hoisted.push(BetweenHoist::ArithmeticOperation { op, right });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    if node_name == Some("NamedArgument") {
        if let Some(inner) = emit.get_field(node, "value") {
            if let Some((left_in, right_in, hoisted)) = split_at_rightmost_and(emit, &inner) {
                let mut new_node = node.clone();
                emit.set_field(&mut new_node, "value", left_in);
                return Some((new_node, right_in, hoisted));
            }
        }
    }
    if node_name == Some("Call")
        && emit
            .get_field(node, "name")
            .and_then(|v| emit.as_str(&v).map(|s| s.into_owned()))
            .as_deref()
            == Some("if")
    {
        if let Some(args) = emit.get_field(node, "args").and_then(|v| emit.as_list(&v)) {
            if args.len() == 3 {
                // Try the else-branch (args[2]) first: `cond ? then :
                // else AND high` parses with else absorbing the AND;
                // we peel and rewrap the if-call.
                if let Some((left_in, right_in, hoisted)) = split_at_rightmost_and(emit, &args[2]) {
                    let mut new_args = args.clone();
                    new_args[2] = left_in;
                    let mut new_node = node.clone();
                    emit.set_field(&mut new_node, "args", emit.array_(new_args));
                    return Some((new_node, right_in, hoisted));
                }
                // Try the cond (args[0]): `(BETWEEN body AND high) ?
                // then : else` parses with the AND inside the cond of
                // an outer ternary. Hoist the ternary's then/else
                // OUTSIDE the BETWEEN — cpp puts ternary at lower
                // precedence than BETWEEN, so the if-call wraps the
                // BetweenExpr the caller builds. The if-call node
                // itself dissolves: its then/else go to the hoist, its
                // cond's split becomes BETWEEN's low/high.
                if let Some((left_in, right_in, mut hoisted)) =
                    split_at_rightmost_and(emit, &args[0])
                {
                    hoisted.push(BetweenHoist::Ternary {
                        then_branch: args[1].clone(),
                        else_branch: args[2].clone(),
                    });
                    return Some((left_in, right_in, hoisted));
                }
            }
        }
    }
    if node_name == Some("Alias") {
        if let Some(inner) = emit.get_field(node, "expr") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                // Hoist *this* alias name. Caller wraps BetweenExpr
                // with each hoisted item in order (innermost first),
                // which matches cpp's `Alias(BetweenExpr(...),
                // outer_name)` shape.
                let name = emit
                    .get_field(node, "alias")
                    .and_then(|v| emit.as_str(&v).map(|s| s.into_owned()))
                    .unwrap_or_default();
                hoisted.push(BetweenHoist::Alias(name));
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // `IsDistinctFrom(left, right, negated)` and `CompareOperation`
    // with `is_null_comparison_style=true` (the IS NULL postfix
    // representation) are TIGHTER than BETWEEN in cpp's grammar, BUT
    // when their `left` contains an alias-wrapped And-chain, the
    // alias terminates BETWEEN's body and the IS DISTINCT FROM / IS
    // NULL applies OUTSIDE the alias-wrapped BetweenExpr. Recurse
    // into `left`; on a successful descent (which will hoist the
    // intermediate Alias), hoist the IS-postfix itself AFTER the
    // accumulated wrappers so it ends up OUTERMOST around the
    // alias-wrapped BetweenExpr the caller will build.
    if node_name == Some("IsDistinctFrom") {
        if let Some(inner) = emit.get_field(node, "left") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                let right = emit.get_field(node, "right").unwrap_or_else(|| emit.null());
                let negated = emit
                    .get_field(node, "negated")
                    .and_then(|v| emit.as_bool(&v))
                    .unwrap_or(false);
                hoisted.push(BetweenHoist::IsDistinctFrom { right, negated });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    if node_name == Some("CompareOperation")
        && emit
            .get_field(node, "is_null_comparison_style")
            .and_then(|v| emit.as_bool(&v))
            == Some(true)
    {
        if let Some(inner) = emit.get_field(node, "left") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                // `op` is "==" for IS NULL, "!=" for IS NOT NULL.
                let negated = emit
                    .get_field(node, "op")
                    .and_then(|v| emit.as_str(&v).map(|s| s.into_owned()))
                    .as_deref()
                    == Some("!=");
                hoisted.push(BetweenHoist::IsNull { negated });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // `ArrayAccess(<expr>, property, nullish?)` — postfix `[…]` /
    // `.<ident>` / `?.<ident>` over an alias-wrapped And-chain.
    // Descend through `array`; on success, hoist the access OUTSIDE
    // the alias so it wraps the BetweenExpr the caller builds.
    if node_name == Some("ArrayAccess") {
        if let Some(inner) = emit.get_field(node, "array") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                let property = emit
                    .get_field(node, "property")
                    .unwrap_or_else(|| emit.null());
                let nullish = emit
                    .get_field(node, "nullish")
                    .and_then(|v| emit.as_bool(&v))
                    .unwrap_or(false);
                hoisted.push(BetweenHoist::ArrayAccess { property, nullish });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // `ExprCall(<expr>, args)` — postfix `(<args>)` at BP_POSTFIX=130
    // on top of an alias-wrapped And-chain. Same hoisting pattern as
    // ArrayAccess: descend through `.expr`, hoist the call OUTSIDE.
    // Reaches cases like `x BETWEEN lambda k : 1 AND ((2)) AS 'a'
    // (1)` where the WIDE body parse absorbs `(1)` as a postfix call
    // on `Alias(And(1, (2)), 'a')`, burying the BETWEEN-separator
    // AND inside the call's `.expr`.
    if node_name == Some("ExprCall") {
        if let Some(inner) = emit.get_field(node, "expr") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                let args = emit
                    .get_field(node, "args")
                    .and_then(|v| emit.as_list(&v))
                    .unwrap_or_default();
                hoisted.push(BetweenHoist::ExprCall { args });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // `TypeCast(<expr>, type_name)` — postfix `:: <type>` at
    // BP_POSTFIX=130. Same hoisting pattern as ExprCall.
    if node_name == Some("TypeCast") {
        if let Some(inner) = emit.get_field(node, "expr") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                let type_name = emit
                    .get_field(node, "type_name")
                    .and_then(|v| emit.as_str(&v).map(|s| s.into_owned()))
                    .unwrap_or_default();
                hoisted.push(BetweenHoist::TypeCast { type_name });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // `TupleAccess(<tuple>, index, nullish?)` — postfix `.<NUMBER>` /
    // `?.<NUMBER>` at BP_POSTFIX=130. Same hoisting pattern as
    // ArrayAccess but on a different node type with a different
    // field name (`tuple` vs `array`, `index` vs `property`).
    if node_name == Some("TupleAccess") {
        if let Some(inner) = emit.get_field(node, "tuple") {
            if let Some((left_in, right_in, mut hoisted)) = split_at_rightmost_and(emit, &inner) {
                let index = emit
                    .get_field(node, "index")
                    .and_then(|v| emit.as_i64(&v))
                    .unwrap_or(0);
                let nullish = emit
                    .get_field(node, "nullish")
                    .and_then(|v| emit.as_bool(&v))
                    .unwrap_or(false);
                hoisted.push(BetweenHoist::TupleAccess { index, nullish });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    // BetweenExpr has TWO slots that can contain the AND we need.
    // ORDER MATTERS — cpp prefers nested-via-low when both options
    // are valid (e.g. `a BETWEEN b AND c BETWEEN d AND e AND f` →
    // outer(a, inner(And(b,c), d, e), f) NOT chained):
    //
    // 1. `low` first: classic nested-via-low case (`x BETWEEN y
    //    BETWEEN z AND w AND v` → outer.low = BETWEEN(y, z, w),
    //    outer.high = v; or 3-AND case where the inner BETWEEN's
    //    low absorbs the extra AND). Peel one AND from inner.low:
    //    the peeled-off right operand becomes the new inner.high;
    //    the OLD inner.high surfaces as the outer's high. Recursion
    //    peels N-1 ANDs across N levels.
    //
    // 2. `expr` fallback: when inner.low has no AND, the greedy body
    //    parse must have consumed a later sibling BETWEEN with the
    //    AND-chain ending up in the embedded BetweenExpr's `expr`
    //    field. cpp parses that pattern LEFT-RECURSIVELY: the second
    //    (rightmost-source) BETWEEN wraps the first. Hoist the whole
    //    BetweenExpr's low / high / negated out so the caller wraps
    //    with a second BETWEEN. Example:
    //
    //      `a NOT BETWEEN b ? c : d AND e NOT BETWEEN f AND g`
    //
    //    Pratt builds body = if(b, c, BetweenExpr(expr=And(d,e),
    //    low=f, high=g, neg=true)). inner.low=f is a single field
    //    (no AND), so the `low` peel above fails. Fall through to
    //    `expr`: split And(d,e), hoist (f, g, neg=true).
    if node_name == Some("BetweenExpr") {
        if let (Some(inner_low), Some(inner_high)) =
            (emit.get_field(node, "low"), emit.get_field(node, "high"))
        {
            if let Some((new_low, new_high, hoisted)) = split_at_rightmost_and(emit, &inner_low) {
                let mut new_inner = node.clone();
                emit.set_field(&mut new_inner, "low", new_low);
                emit.set_field(&mut new_inner, "high", new_high);
                return Some((new_inner, inner_high, hoisted));
            }
        }
        if let Some(inner_expr) = emit.get_field(node, "expr") {
            if let Some((left_in, right_in, mut hoisted)) =
                split_at_rightmost_and(emit, &inner_expr)
            {
                let low = emit.get_field(node, "low").unwrap_or_else(|| emit.null());
                let high = emit.get_field(node, "high").unwrap_or_else(|| emit.null());
                let negated = emit
                    .get_field(node, "negated")
                    .and_then(|v| emit.as_bool(&v))
                    .unwrap_or(false);
                hoisted.push(BetweenHoist::Between { low, high, negated });
                return Some((left_in, right_in, hoisted));
            }
        }
    }
    None
}

/// True when `v` is a `Field` node with a single-element identifier
/// chain. Used by `parse_expr_list_until_terminators` to detect
/// speculatively-parsed clause keywords (e.g. `qualify`, `having`,
/// `offset`) that resolved to a bare identifier and should NOT extend
/// the column list — cpp backs off the comma and dispatches them as
/// the next clause introducer.
pub(crate) fn is_bare_field<E: Emitter>(emit: &E, v: &E::Value) -> bool {
    if emit.node_kind(v).as_deref() != Some("Field") {
        return false;
    }
    let Some(chain) = emit.get_field(v, "chain").and_then(|c| emit.as_list(&c)) else {
        return false;
    };
    chain.len() == 1
}

/// Detect a ColumnsExpr produced by the bare-paren grammar alts
/// `LPAREN ASTERISK [EXCLUDE(...)]? REPLACE(...) RPAREN`, whose ctx
/// span includes the outer parens. Exclude-only `(* EXCLUDE(...))` is
/// a regular `ColumnExprAsterisk` inside `ColumnExprParens` (paren
/// pass-through), so we key off `replace` presence to identify the
/// bare-paren form. The COLUMNS-prefixed `COLUMNS(* REPLACE(...))`
/// variant takes a different parse path (it doesn't go through
/// `parse_paren_or_tuple`), so this check is safe.
fn is_paren_form_columns_replace<E: Emitter>(emit: &E, v: &E::Value) -> bool {
    if emit.node_kind(v).as_deref() != Some("ColumnsExpr") {
        return false;
    }
    if emit
        .get_field(v, "all_columns")
        .and_then(|v| emit.as_bool(&v))
        != Some(true)
    {
        return false;
    }
    emit.get_field(v, "replace")
        .map(|v| !emit.is_null(&v))
        .unwrap_or(false)
}
