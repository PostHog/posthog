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
    unquote_single_string, Parser, BP_ALIAS, BP_BETWEEN, BP_COMPARE, BP_IGNORE_NULLS,
    BP_IS_DISTINCT_FROM, BP_IS_NULL, BP_NOT, BP_TERNARY, BP_UNARY_MINUS,
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
        // Cap the central recursive entry so deeply-nested input (`((…))` with thousands of nests) surfaces as a syntax error rather than stack OOM. Shares the counter with subquery / statement nesting; bound rationale on `MAX_RECURSION_DEPTH`.
        self.recursion_depth += 1;
        let result = if self.recursion_depth > crate::parse::MAX_RECURSION_DEPTH {
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
        self.recursion_depth -= 1;
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
            // A bare alias was just built: an outer-tier operator (AND, OR,
            // ternary `?`, a chained AS) may wrap it, and a comparison may take
            // it as its left operand — `1 AS x > 0` is `(1 AS x) > 0`, cpp's
            // `ColumnExprAliasCompare` (ClickHouse accepts the shape in nested
            // contexts, e.g. `if(1 AS x > 0, …)`). Any other value-tier operator
            // terminates the expression here, matching cpp's two-tier grammar
            // (`1 AS x AND y` is `(1 AS x) AND y`; `1 AS x + 2` rejects).
            if std::mem::take(&mut self.after_bare_alias) {
                let continues = matches!(
                    kind,
                    TokenKind::Keyword(Kw::And)
                        | TokenKind::Keyword(Kw::Or)
                        | TokenKind::Keyword(Kw::As)
                        | TokenKind::QMark
                        | TokenKind::Keyword(Kw::In)
                        | TokenKind::Keyword(Kw::Like)
                        | TokenKind::Keyword(Kw::Ilike)
                ) || (kind == TokenKind::Keyword(Kw::Not)
                    && matches!(
                        self.peek_next(),
                        TokenKind::Keyword(Kw::In)
                            | TokenKind::Keyword(Kw::Like)
                            | TokenKind::Keyword(Kw::Ilike)
                    ))
                    || infix_bp(kind).is_some_and(|(lbp, _, _)| lbp == BP_COMPARE);
                if !continues {
                    break;
                }
            }
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
                    // `<` is a pure-infix token (less-than), but it also starts
                    // a HogQLX tag: `1 % <a/>` is `1 modulo <tag>`. Don't treat
                    // the `%` as the PERCENT marker when a tag follows. Plain
                    // `1 % < 2` (peek-next `<` not a tag) still breaks.
                    if (!peek_can_start_clause_body(next) || is_pure_infix_op(next))
                        && !self.peek_next_starts_hogqlx_tag()
                    {
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
            // Special-infix (LIKE / BETWEEN / IS [NOT] (NULL|DISTINCT FROM) /
            // IN / …). At a statement boundary (recover flag set) an INCOMPLETE
            // form is cpp's "end this statement, start the next" shape, not an
            // error: `week like` is two Field statements, `"_" between "_"` is
            // three. The body/RHS parse happens before `lhs.take()`, so a
            // failure leaves `lhs` intact — roll back the lexer and break so the
            // operator begins the next statement (mirrors cpp ALL(*) backtrack
            // and the regular-infix recovery above). At expression level (flag
            // off) the failure stays a hard error, matching cpp.
            if self.stmt_rhs_recover_on_pratt_rhs_failure {
                let cp = self.checkpoint();
                match self.try_special_infix(kind, &mut lhs, min_bp, lhs_start) {
                    Ok(Some(true)) => {
                        lhs = self.wrap_pos(lhs, lhs_start);
                        continue;
                    }
                    Ok(_) => {}
                    Err(_) => {
                        self.restore(cp)?;
                        break;
                    }
                }
            } else if let Some(handled) =
                self.try_special_infix(kind, &mut lhs, min_bp, lhs_start)?
            {
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
                // Same statement-boundary recovery as special-infix: a failing
                // postfix (`[ ] [ ]` — the second `[` can't index the first
                // empty array) ends the statement so the postfix token begins
                // the next one. `parse_postfix` moves `lhs` by value, so clone
                // it to restore on failure. Expression level keeps the error.
                if self.stmt_rhs_recover_on_pratt_rhs_failure {
                    let cp = self.checkpoint();
                    let lhs_backup = lhs.clone();
                    match self.parse_postfix(kind, lhs) {
                        Ok(v) => {
                            lhs = self.wrap_pos(v, lhs_start);
                            continue;
                        }
                        Err(_) => {
                            self.restore(cp)?;
                            lhs = lhs_backup;
                            break;
                        }
                    }
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
                // `not <tag>` — a `<` that begins a HogQLX tag is NOT the
                // less-than operator, so NOT is the unary prefix and the tag is
                // its operand (`not <a/>` → `Not(<a/>)`). Without this, the
                // `Lt` arm in the pure-binary-operator set below would read NOT
                // as a Field and `<` as less-than, stranding the tag. Plain
                // `not < 2` (peek-next `<` not a tag) still falls through there.
                if self.peek_next_starts_hogqlx_tag() {
                    // `<…` is the tag operand only when it forms a *complete* tag
                    // (`not <a/>` -> `Not(<a/>)`); an incomplete `< ident`
                    // (`not < a`) is the less-than operator with NOT as a Field.
                    // Try the tag and fall through to the Field path on failure.
                    let cp = self.checkpoint();
                    self.bump()?; // NOT
                    match self.parse_expr_bp(BP_NOT) {
                        Ok(rhs) => return Ok(self.emit.not_(rhs)),
                        Err(_) => self.restore(cp)?,
                    }
                }
                // Bare `NOT` followed by a token that can't start an
                // expression (list-terminator / EOF) is the identifier
                // "not" — cpp's `keyword` rule admits NOT as an identifier
                // and falls back to a Field. Without this check, parse_prefix
                // would eagerly consume NOT and then error on the unexpected
                // following token. (`not as` is NOT here: `AS` parses as a
                // Field operand, so cpp keeps `Not(Field('AS'))` via the
                // general fallback below.)
                if matches!(
                    self.peek_next(),
                    TokenKind::Comma
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
                        | TokenKind::NullSafeEq
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
                // At a STATEMENT boundary cpp takes the shortest leading
                // statement, so a `not <op-keyword> <rhs>` is `Not(Field(<kw>))`
                // (statement 1) with `<rhs>` opening the next statement, rather
                // than the greedy single expression `Field(not) <op> <rhs>`.
                // Skip all the expression-context NOT-flip probes below and go
                // straight to the general fallback, which produces exactly that
                // split (`not like 'a'` → `Not(Field(like))`; then `'a'`).
                if self.stmt_rhs_recover_on_pratt_rhs_failure {
                    let cp = self.checkpoint();
                    self.bump()?; // NOT
                    return match self.parse_expr_bp(BP_NOT) {
                        Ok(rhs) => Ok(self.emit.not_(rhs)),
                        Err(_) => {
                            self.restore(cp)?;
                            self.parse_ident_lead()
                        }
                    };
                }
                // EXPRESSION context below: cpp's single-expression parse greedily
                // reads NOT as a Field so a following infix / alias binds to it.
                // `not as <alias>` → `Field(not) AS <alias>`; a bare `not as` (no
                // alias after `AS`) stays `Not(Field('as'))`. Aliases are
                // IDENTIFIER / QUOTED_IDENTIFIER / keywordForAlias (date/first/id/key).
                if self.peek_next() == TokenKind::Keyword(Kw::As) {
                    let mut probe = Lexer::with_pos(self.src, self.peek1.end);
                    if matches!(
                        probe.next_token().map(|t| t.kind),
                        Ok(TokenKind::Ident
                            | TokenKind::QuotedIdent
                            | TokenKind::Keyword(Kw::Date | Kw::First | Kw::Id | Kw::Key))
                    ) {
                        return self.parse_ident_lead();
                    }
                }
                // `not in a` → binary `in` (`Compare(Field(not), "in", a)`), but
                // `not in (1,2)` keeps the unary `Not(Call(in, [1,2]))` via the
                // LParen exclusion.
                if self.peek_next() == TokenKind::Keyword(Kw::In) {
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
                                | TokenKind::LParen
                        ) {
                            return self.parse_ident_lead();
                        }
                    }
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
                // General NOT fallback (cpp ALL(*) parity): try NOT as the unary
                // prefix; if its operand can't parse, cpp re-reads NOT as a bare
                // Field and the following infix/postfix binds to it — `not < a` ->
                // `(Field not) < a`, `not + a` -> `(Field not) + a`, `not in a` ->
                // `(Field not) in a`. `not AS` keeps `Not(Field('AS'))` because the
                // operand parses. The earlier probes already diverted the cases
                // where the operand parses but cpp still prefers Field(not), so the
                // fallback only fires on a genuine operand failure. At a statement
                // boundary this is also the `not let x` shape (`not` Field stmt then
                // the `let x` statement). rust rejects only when both the unary and
                // the Field interpretation fail — exactly as cpp does.
                let cp = self.checkpoint();
                self.bump()?; // NOT
                match self.parse_expr_bp(BP_NOT) {
                    Ok(rhs) => Ok(self.emit.not_(rhs)),
                    Err(_) => {
                        self.restore(cp)?;
                        self.parse_ident_lead()
                    }
                }
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

    /// After `<cursor> .` (the cursor token followed by a `.`), is the token
    /// past the `.` a Field-chain link (identifier-ish) rather than a
    /// tuple-access index (number)? `true.x` is a Field chain; `true.1` is
    /// tuple access on the boolean Constant. Used to keep `true`/`false` a
    /// Constant base for numeric tuple access while still folding `.identifier`
    /// into a Field chain.
    pub(crate) fn dot_next_is_chain_link(&self) -> bool {
        if self.peek_next() != TokenKind::Dot {
            return false;
        }
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        matches!(
            probe.next_token().map(|t| t.kind),
            Ok(TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_))
        )
    }

    fn parse_primary(&mut self) -> Result<E::Value, ParseError> {
        let tok = self.peek0;
        // One-shot: true only for the leading primary of an enclosing INTERVAL's
        // value (set in `parse_interval_expr`). Taken here so it never leaks past
        // the first primary — parens / call-args reset it for free.
        let interval_value = std::mem::take(&mut self.interval_value_pending);
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
                if self.peek_next() == TokenKind::LParen || self.dot_next_is_chain_link() =>
            {
                // `true`/`false` are not lexer tokens in the grammar — they are
                // ordinary identifiers, and become Bool Constants only as a bare
                // `columnIdentifier`. cpp treats them as identifiers in two
                // columnExpr-leading postfix positions:
                //   `true(…)`  → Call(name='true')       (function call)
                //   `true.x`   → Field(['true', 'x'])    (chain)
                // Route those through ident-lead so the chain accumulates. But
                // `true.<number>` is tuple access on the boolean Constant
                // (`true.1` → TupleAccess(Constant(true), 1)) — cpp keeps the
                // Constant base, so that case is NOT routed here: it falls
                // through to the Constant arms and the Pratt `.` postfix builds
                // the TupleAccess. `null` differs — NULL is a real keyword, so
                // `null(…)` / `null.1` already keep the Null constant.
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
            // form).
            //
            // cpp commits to the INTERVAL form only when a STRING_LITERAL
            // follows (the `INTERVAL STRING_LITERAL` ColumnExprIntervalString
            // alt): then a missing / bad unit is a hard error, never a fall-back
            // to `interval`-as-Field. This matters at statement level —
            // `{ interval 'ln' }` must reject, not split into `interval` (Field)
            // + `'ln'` (Constant). So mark the string-committed parse fatal so no
            // outer `try_alt` rolls it back. For a number / identifier / quoted-
            // identifier value (`interval 1`, `interval x`, `interval "a"`) cpp
            // does NOT commit: with no trailing unit it backtracks to `interval`-
            // as-Field, so at program level `interval 1` is two statements
            // (`interval` + `1`). Use try_alt there so `interval 1 day` still
            // parses as an interval while a unit-less `interval 1` falls back to
            // a Field. The `interval(...)` shape keeps the function-call fall-
            // back; operator continuations like `interval + 1` reach try_alt too.
            //
            // A nested INTERVAL in the value position of an enclosing INTERVAL
            // is two-faced. The STRING form (`interval interval '5 day' month`)
            // is self-contained — count and unit live inside the string — so
            // cpp's ALL(*) parses the inner string-only and reserves the
            // trailing `month` for the OUTER interval (a bad string is a hard
            // error like cpp's `ColumnExprIntervalString`). The EXPR form is
            // resolved by which reading lets the WHOLE thing parse: the inner is
            // a nested `INTERVAL <value> <unit>` only when it leaves a unit for
            // the outer (`interval interval 0 week week` → inner `INTERVAL 0
            // WEEK`, outer `WEEK`). Otherwise the inner `interval` is an
            // identifier and its trailing unit binds to the outer
            // (`interval interval - x week` → `INTERVAL (interval - x) WEEK`;
            // `interval interval(1) week` → the call as the value). So probe the
            // nested form and keep it only when a unit keyword still follows.
            TokenKind::Keyword(Kw::Interval) if interval_value => {
                if self.peek_next() == TokenKind::String {
                    // Nested string-valued INTERVAL. cpp keeps the inner string a
                    // self-contained `ColumnExprIntervalString` (count+unit inside
                    // the quotes, `'5 day'`) when a SINGLE unit trails — that unit
                    // is the OUTER interval's. When TWO units trail, the inner is
                    // instead an expr+unit INTERVAL whose VALUE is the (plain
                    // constant) string and whose unit is the first keyword, leaving
                    // the second for the outer (`interval interval '' day month` →
                    // `INTERVAL (INTERVAL '' DAY) MONTH`). The value-expr reading
                    // sidesteps the string's count/unit validation, which is why
                    // `''` parses there but not as a bare string interval.
                    if self.interval_string_trailing_unit_count() >= 2 {
                        self.parse_interval_expr().map_err(ParseError::into_fatal)
                    } else {
                        self.parse_interval_string_only()
                            .map_err(ParseError::into_fatal)
                    }
                } else {
                    let cp = self.checkpoint();
                    match self.parse_interval_expr() {
                        // Keep the nested reading only when a unit is still left
                        // for the OUTER interval — directly, or after a run of
                        // postfix operators on the inner (`interval interval 0
                        // hour () hour` → `INTERVAL ((INTERVAL 0 HOUR)()) HOUR`).
                        Ok(inner) if self.interval_unit_follows_postfix_run() => Ok(inner),
                        Err(e) if e.fatal => Err(e),
                        _ => {
                            self.restore(cp)?;
                            self.parse_ident_lead()
                        }
                    }
                }
            }
            // A HogQLX tag is a valid interval value (`interval <t/> second` →
            // `INTERVAL (<t/>) SECOND`), but `<` is a pure-infix operator so
            // `can_start_interval_value` rejects it — admit it explicitly when
            // the `<` actually begins a tag (not a `<` comparison). The try_alt
            // below still falls back to the `interval < x` comparison reading
            // when the tag parse doesn't pan out.
            TokenKind::Keyword(Kw::Interval)
                if can_start_interval_value(self.peek_next())
                    || self.peek_next_starts_hogqlx_tag() =>
            {
                if self.peek_next() == TokenKind::String {
                    self.parse_interval_expr().map_err(ParseError::into_fatal)
                } else {
                    self.try_alt(&[&Self::parse_interval_expr, &Self::parse_ident_lead])
                }
            }
            // ColumnExprDate (`DATE STRING_LITERAL`) / ColumnExprTimestamp
            // (`TIMESTAMP STRING_LITERAL`). cpp's grammar matches these but its
            // visitor raises NotImplementedError — the AST builder has no date /
            // timestamp literal node — so they reject. Without this arm rust
            // treats `date` / `timestamp` as a plain identifier and strands the
            // string: at expression level `expect_eof` rejects, but inside a Hog
            // `{ … }` block body the string becomes a second statement, so
            // `{ date 'x' }` parses as `date; 'x'` and accepts input cpp rejects.
            // Reject fatally so no outer `try_alt` rolls it back to the
            // identifier form. `date(…)` (function call) and bare `date` keep
            // the identifier path — only `date <string>` is the literal form.
            TokenKind::Keyword(Kw::Date | Kw::Timestamp)
                if self.peek_next() == TokenKind::String =>
            {
                if self.suppress_unvisited_clause_checks {
                    // Inside a clause cpp grammar-parses but never visits (a
                    // selectStmtWithParens trailing ORDER BY): consume `DATE
                    // STRING` into a throwaway Constant so the discarded parse
                    // completes, matching cpp's accept. The node value is moot.
                    self.bump()?;
                    let str_tok = self.peek0;
                    self.bump()?;
                    return Ok(self
                        .emit
                        .constant(self.emit.string(&unquote_single_string(self.text(str_tok)))));
                }
                let tok = self.peek0;
                Err(ParseError::not_implemented_fatal(
                    "Date and timestamp literals are not supported",
                    tok.start,
                    tok.end,
                ))
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
            // Unvisited clause (window FILTER body / discarded ORDER BY): cpp
            // grammar-parses the string-form INTERVAL but never visits it, so
            // none of its count / unit "not supported" rejections (`interval
            // 'bm '`) fire here. Consume the string into a throwaway and return;
            // the value is moot. (The no-space `interval 'p'` case is covered
            // too, so its own suppress branch below is unreachable now.)
            if self.suppress_unvisited_clause_checks {
                self.bump()?;
                return Ok(self.emit.call(
                    "toIntervalSecond",
                    vec![self.emit.constant(self.emit.string(&raw))],
                ));
            }
            if let Some((count_str, unit)) = raw.split_once(' ') {
                // `INTERVAL '<count> <unit>'` carries both inside one string;
                // cpp's `visitColumnExprIntervalString` validates and emits it.
                return self.emit_interval_combined_string(count_str, unit, str_tok);
            }
            // The string has no internal space (the split failed) and — per the
            // branch guard — no trailing unit keyword. cpp's ALL(*) still prefers
            // `ColumnExprInterval` (expr+unit) when the no-space string is only the
            // HEAD of a longer unit-terminated value (`interval 'a' || 'b' hour`),
            // so try that form first. If it fails (no unit keyword closes the
            // value, e.g. bare `interval ''` / `interval 'x' + 1`), cpp falls back
            // to `ColumnExprIntervalString`, whose visitor rejects a string that
            // isn't `<count> <unit>`. Reproduce that rejection rather than leaking
            // the expr+unit form's "expected interval unit keyword" syntax error.
            // A fatal error from the value parse (a committed nested rejection)
            // surfaces as-is, matching cpp.
            let cp = self.checkpoint();
            return match self.parse_interval_value_unit_form() {
                Ok(v) => Ok(v),
                Err(e) if e.fatal => Err(e),
                Err(_) => {
                    self.restore(cp)?;
                    self.bump()?;
                    Err(ParseError::not_implemented_fatal(
                        "Unsupported interval type: must be in the format '<count> <unit>'",
                        str_tok.start,
                        str_tok.end,
                    ))
                }
            };
        }
        self.parse_interval_value_unit_form()
    }

    /// `INTERVAL <expr> <unit>` (cpp's `ColumnExprInterval`): parse a full
    /// columnExpr value at BP=0 (greedy), then require one of the eight singular
    /// unit keywords. The unit-keyword tokens (`SECOND`/`MINUTE`/…/`YEAR`) aren't
    /// binary or postfix operators, so the Pratt loop halts before them; AND / OR
    /// / BETWEEN that surround the INTERVAL in an outer expression bind correctly
    /// because the unit keyword terminates the value before they're seen.
    fn parse_interval_value_unit_form(&mut self) -> Result<E::Value, ParseError> {
        // Flag the value's leading primary so a nested INTERVAL there yields
        // the unit to us rather than eating it (see `parse_primary`). One-shot:
        // `parse_primary` takes it, so only that first primary is affected.
        // Reset unconditionally after the parse before propagating: on success
        // `parse_primary` already took it, but if `parse_expr_bp` errors BEFORE
        // reaching `parse_primary` (e.g. `interval + <non-number>`), the flag
        // would otherwise leak past the enclosing `try_alt` rollback (whose
        // checkpoint doesn't track it) and corrupt a following INTERVAL.
        self.interval_value_pending = true;
        let value_result = self.parse_expr_bp(0);
        self.interval_value_pending = false;
        let expr = value_result?;
        // The grammar's `interval` rule is the eight singular unit
        // *keyword* tokens (`SECOND | MINUTE | HOUR | DAY | WEEK |
        // MONTH | QUARTER | YEAR`, with `YYYY` lexed as `YEAR`). A
        // plural (`hours`) lexes as an identifier and an arbitrary
        // identifier / quoted identifier is never a unit — cpp rejects
        // all of those (`INTERVAL 1 hours`, `INTERVAL 1 "hour"`). The
        // plural-tolerant `INTERVAL '5 days'` form is the *string*
        // branch in `parse_interval_expr`, handled before this point.
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

    /// Parse `INTERVAL '<count> <unit>'` as the string-only
    /// `ColumnExprIntervalString` form WITHOUT consuming a following unit
    /// keyword. Used when an INTERVAL sits in the value position of an
    /// enclosing INTERVAL (`interval interval '5 day' month`): cpp reserves the
    /// trailing unit for the outer interval, so the inner string must carry its
    /// own count+unit. Mirrors the combined-string branch of
    /// `parse_interval_expr`, except a string that is not `<count> <unit>` is a
    /// hard error (cpp's `visitColumnExprIntervalString`) rather than a
    /// fall-through to the expr+unit form, which would steal the outer's unit.
    fn parse_interval_string_only(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Interval, "INTERVAL")?;
        let str_tok = self.peek0;
        let raw = unquote_single_string(self.text(str_tok));
        // Unvisited clause (window FILTER body / discarded ORDER BY): cpp
        // grammar-parses the inner `ColumnExprIntervalString` but never visits it,
        // so its count/unit "not supported" rejections never fire — tolerate any
        // string with a throwaway, matching the suppress short-circuit in
        // `parse_interval_expr` (`a() filter(where interval interval 'bm ' day) over a`).
        if self.suppress_unvisited_clause_checks {
            self.bump()?;
            return Ok(self.emit.call(
                "toIntervalSecond",
                vec![self.emit.constant(self.emit.string(&raw))],
            ));
        }
        let Some((count_str, unit)) = raw.split_once(' ') else {
            self.bump()?;
            return Err(ParseError::not_implemented_fatal(
                "Unsupported interval type: must be in the format '<count> <unit>'",
                str_tok.start,
                str_tok.end,
            ));
        };
        self.emit_interval_combined_string(count_str, unit, str_tok)
    }

    /// Validate and emit a `<count> <unit>` combined-string INTERVAL (cpp's
    /// `visitColumnExprIntervalString`). `str_tok` is the string literal at the
    /// cursor; it is consumed here, and anchors every error. Shared by the
    /// top-level combined-string branch of `parse_interval_expr` and the nested
    /// `parse_interval_string_only`.
    ///
    /// The count must be a non-empty run of ASCII digits (cpp digit-checks each
    /// char). ClickHouse stores intervals as Int64, so the count is accepted
    /// across the full Int64 range; a digit string past Int64 max is rejected as
    /// too large. The unit is matched case-sensitively against cpp's
    /// literal-lowercase singular / plural set (so `SECOND` rejects).
    fn emit_interval_combined_string(
        &mut self,
        count_str: &str,
        unit: &str,
        str_tok: Token,
    ) -> Result<E::Value, ParseError> {
        self.bump()?;
        if count_str.is_empty() || !count_str.bytes().all(|b| b.is_ascii_digit()) {
            return Err(ParseError::not_implemented_fatal(
                format!("Unsupported interval count: '{count_str}' is not a valid integer"),
                str_tok.start,
                str_tok.end,
            ));
        }
        let count: i64 = match count_str.parse::<i64>() {
            Ok(n) => n,
            Err(_) => {
                return Err(ParseError::not_implemented_fatal(
                    format!("Unsupported interval count: '{count_str}' is too large"),
                    str_tok.start,
                    str_tok.end,
                ));
            }
        };
        let Some(unit_name) = interval_call_name_case_sensitive(unit) else {
            return Err(ParseError::not_implemented_fatal(
                format!("Unsupported interval unit: {unit}"),
                str_tok.start,
                str_tok.end,
            ));
        };
        Ok(self
            .emit
            .call(unit_name, vec![self.emit.constant(self.emit.int(count))]))
    }

    /// For a nested string-valued INTERVAL (`peek0 == interval`, `peek1 ==
    /// String`), count the INTERVAL unit keywords (`SECOND … YEAR`) that
    /// immediately trail the string, capped at 2. Drives the string-only vs
    /// expr+unit choice for the inner interval: one trailing unit is the OUTER
    /// interval's (inner stays self-contained), two means the inner takes the
    /// first as its own unit and reserves the second for the outer.
    fn interval_string_trailing_unit_count(&self) -> usize {
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        let mut count = 0usize;
        while count < 2 {
            match probe.next_token() {
                Ok(t)
                    if matches!(
                        t.kind,
                        TokenKind::Keyword(
                            Kw::Second
                                | Kw::Minute
                                | Kw::Hour
                                | Kw::Day
                                | Kw::Week
                                | Kw::Month
                                | Kw::Quarter
                                | Kw::Year
                        )
                    ) =>
                {
                    count += 1
                }
                _ => break,
            }
        }
        count
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

    /// After a nested-interval value at `peek0`, would one of the eight singular
    /// INTERVAL unit keywords (`SECOND … YEAR`, what `parse_interval_expr`'s unit
    /// slot accepts) follow once a run of postfix operators on that value — a
    /// `(…)` call, `[…]` subscript, or `.id` / `?.id` member — is skipped? The
    /// enclosing INTERVAL takes that unit, so the inner `interval` is a nested
    /// value-plus-postfixes (`interval interval 0 hour () hour`) rather than a
    /// bare identifier. Postfix runs only — an arithmetic / infix continuation
    /// is left to the bare-identifier reading.
    fn interval_unit_follows_postfix_run(&self) -> bool {
        let is_unit = |k: TokenKind| {
            matches!(
                k,
                TokenKind::Keyword(
                    Kw::Second
                        | Kw::Minute
                        | Kw::Hour
                        | Kw::Day
                        | Kw::Week
                        | Kw::Month
                        | Kw::Quarter
                        | Kw::Year
                )
            )
        };
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        loop {
            let Ok(t) = probe.next_token() else {
                return false;
            };
            match t.kind {
                k if is_unit(k) => return true,
                TokenKind::LParen | TokenKind::LBracket => {
                    let mut depth: i32 = 1;
                    while depth > 0 {
                        let Ok(inner) = probe.next_token() else {
                            return false;
                        };
                        match inner.kind {
                            TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => {
                                depth += 1
                            }
                            TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                                depth -= 1
                            }
                            TokenKind::Eof => return false,
                            _ => {}
                        }
                    }
                }
                // `.id` / `?.id` member — skip the member token too.
                TokenKind::Dot | TokenKind::NullProperty => {
                    if probe.next_token().is_err() {
                        return false;
                    }
                }
                _ => return false,
            }
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
        // Empty `columns()` matches no `ColumnExprColumns*` production (regex needs a string, the list needs >=1 columnExpr, the all-form needs `*`), so reject it: a bare `columns()` then falls back to a function call and `* columns()` (spread) is rejected, both matching cpp.
        if self.peek() == TokenKind::RParen {
            return Err(self.err("empty COLUMNS() is not a columns expression"));
        }
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
                self.columns_list_from_first(inner, asterisk_pos)?
            }
        } else {
            // Could be `ident . *` or an expression list.
            // Peek for the qualified-asterisk pattern: IDENT DOT ASTERISK.
            // The qualifier is the grammar's `identifier`, so only keywords admitted by `kw_valid_as_identifier` qualify — Hog-statement keywords (try/catch/finally) and the rest of the omitted set are not Field qualifiers, so cpp rejects `columns(try.*)`; without this gate rust took it as a qualified-asterisk ColumnsExpr.
            let first_is_qualifier_ident =
                matches!(self.peek(), TokenKind::Ident | TokenKind::QuotedIdent)
                    || matches!(self.peek(), TokenKind::Keyword(kw) if kw_valid_as_identifier(kw));
            if first_is_qualifier_ident && self.peek_next() == TokenKind::Dot {
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
                    // Chain links are `identifier` too — gate keyword links on `kw_valid_as_identifier` so `columns(a.try.*)` rejects like cpp.
                    if matches!(nxt.kind, TokenKind::Ident | TokenKind::QuotedIdent)
                        || matches!(nxt.kind, TokenKind::Keyword(kw) if kw_valid_as_identifier(kw))
                    {
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
                        (None, None) => self.columns_list_from_first(qualified_field, saved_pos)?,
                        (Some(ex), None) => {
                            // cpp's `ColumnExprColumnsQualifiedExclude`
                            // ctx covers `IDENT.* EXCLUDE(...)`; the
                            // inner ColumnsExpr inherits that span.
                            // Wrap before passing to the outer list.
                            let inner = self.wrap_pos(
                                self.emit.columns_expr(None, None, true, Some(ex), None),
                                saved_pos,
                            );
                            self.columns_list_from_first(inner, saved_pos)?
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
    fn columns_list_from_first(
        &mut self,
        first: E::Value,
        first_start: usize,
    ) -> Result<E::Value, ParseError> {
        if self.peek() == TokenKind::RParen {
            return Ok(self
                .emit
                .columns_expr(None, Some(vec![first]), false, None, None));
        }
        // The continuation (postfix call, infix op) extends the asterisk LHS, so its span must start at the LHS's start (`first_start`), not `self.peek0.start` (the token after it) — cpp spans `columns(a.*(b))`'s call from `a`, not from the `(`.
        let first = self.pratt_continue_with_lhs(first, 0, first_start)?;
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
        let exclude = self.parse_exclude_clause()?;
        let replace = self.parse_replace_clause()?;
        Ok((exclude, replace))
    }

    /// `EXCLUDE LPAREN identifierList RPAREN` — the optional exclude list shared by the `COLUMNS(...)` family and the bare `ColumnExprAsterisk` (grammar line 289). Returns `None` when no EXCLUDE keyword follows.
    fn parse_exclude_clause(&mut self) -> Result<Option<Vec<String>>, ParseError> {
        if !self.eat_kw(Kw::Exclude)? {
            return Ok(None);
        }
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
        Ok(Some(names))
    }

    /// `REPLACE LPAREN columnsReplaceList RPAREN` — the optional replace list, valid only inside the `COLUMNS(...)` / `(*...)` wrapper forms (a bare `ColumnExprAsterisk` admits EXCLUDE but never REPLACE). Returns `None` when no REPLACE keyword follows.
    fn parse_replace_clause(&mut self) -> Result<Option<Vec<(String, E::Value)>>, ParseError> {
        if !self.eat_kw(Kw::Replace)? {
            return Ok(None);
        }
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
                TokenKind::Ident | TokenKind::QuotedIdent => identifier_text(self.text(t), t.kind),
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
        Ok(Some(items))
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
            // cpp's ANTLR tries the `* COLUMNS(…)` spread (regex / list) and, when neither matches (e.g. an empty `columns()`), backs off to bare `*` (`ColumnExprAsterisk`), leaving COLUMNS(…) to the enclosing context (a later statement, or an error at the closing `)`). Mirror that fall-back on a non-fatal spread failure.
            let cp = self.checkpoint();
            match self.parse_columns_expr() {
                Ok(inner) => return Ok(self.emit.spread_expr(inner)),
                Err(e) if e.fatal => return Err(e),
                Err(_) => self.restore(cp)?,
            }
        }
        // `ColumnExprAsterisk` (grammar line 289) admits ONLY an optional trailing
        // EXCLUDE on a bare `*`. `REPLACE` after `*` is valid only inside the
        // paren-wrapped forms — `(* REPLACE (…))`, `(* EXCLUDE (…) REPLACE (…))`
        // (parse_paren_or_tuple) and `COLUMNS(* … REPLACE …)` (parse_columns_expr),
        // each of which consumes the `*` itself. So a `* … REPLACE` that reaches here is
        // a bare top-level attempt (a function argument, a tuple element, …) — which cpp
        // rejects, since bare `* … REPLACE` is not a columnExpr.
        let cp_before_decorators = self.checkpoint();
        let exclude = match self.parse_exclude_clause() {
            Ok(e) => e,
            Err(e) if e.fatal => return Err(e),
            Err(e) => {
                // The EXCLUDE list needs >=1 identifier, so a string / empty list
                // fails the columns-exclude. At a statement boundary cpp re-reads
                // `*` as a bare Field statement and `exclude(<…>)` as the next
                // statement (a call): `* exclude ('j')` -> `*` ; `exclude('j')`.
                // Outside a statement boundary (a SELECT column, an arg, …) there
                // is no split, so propagate the rejection — matching cpp.
                self.restore(cp_before_decorators)?;
                if self.stmt_rhs_recover_on_pratt_rhs_failure {
                    return Ok(self.emit.field(vec![self.emit.string("*")]));
                }
                return Err(e);
            }
        };
        // A bare `*` / `* EXCLUDE(...)` admits no trailing REPLACE (that needs the
        // paren-wrapped `(* REPLACE …)` / `COLUMNS(* … REPLACE …)`). At a statement
        // boundary cpp keeps the `*` / `* EXCLUDE(...)` as this statement and
        // re-reads `replace(...)` as the next statement's call (`* replace (1 as b)`
        // -> `*` ; `replace(1 as b)`); elsewhere it's a hard reject.
        let cp_before_replace = self.checkpoint();
        if self.parse_replace_clause()?.is_some() {
            if self.stmt_rhs_recover_on_pratt_rhs_failure {
                self.restore(cp_before_replace)?;
            } else {
                self.restore(cp_before_decorators)?;
                return Err(self.err(
                    "REPLACE after a bare `*` is only valid inside `(* REPLACE …)` / `COLUMNS(* REPLACE …)`",
                ));
            }
        }
        if exclude.is_none() {
            Ok(self.emit.field(vec![self.emit.string("*")]))
        } else {
            Ok(self.emit.columns_expr(None, None, true, exclude, None))
        }
    }

    /// `#<integer>` — positional column reference from a SELECT.
    fn parse_positional(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::Hash, "#")?;
        let tok = self.bump()?;
        // Grammar: `HASH DECIMAL_LITERAL # ColumnExprPositional` — only a base-10 integer. Rust's lexer folds hex / octal / float into one `Number` kind, so re-check the text: `#0x6` (hex), `#017` (octal), `#1e3` (float) all reject in cpp, where rust used to read them as PositionalRef(0) via `parse().unwrap_or(0)`.
        let is_dec = tok.kind == TokenKind::Number && is_decimal_literal(self.text(tok));
        if !is_dec {
            let got = self.text(tok).to_string();
            return Err(self.err(format!("expected decimal integer after '#', got {got:?}")));
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

    /// Parse a placeholder-only `{ … }` slot (`tableExpr` / `ratioExpr` / `selectStmtWithParens`): only `{ columnExpr }` is valid, so reject the Dict that `{}` or `{k: v}` would otherwise produce.
    pub(crate) fn parse_brace_placeholder_only(&mut self) -> Result<E::Value, ParseError> {
        let node = self.parse_brace_dict_or_placeholder()?;
        if self.emit.node_kind(&node).as_deref() != Some("Placeholder") {
            return Err(self.err("expected a placeholder `{name}` here, not a dict"));
        }
        Ok(node)
    }

    fn parse_single_arg_arrow_lambda(&mut self) -> Result<E::Value, ParseError> {
        let lambda_start = self.peek0.start;
        let ident = self.bump()?;
        let name = identifier_text(self.text(ident), ident.kind);
        self.expect(TokenKind::Arrow, "->")?;
        let body = self.parse_lambda_body()?;
        // Stamp the span here (not just via the caller's `wrap_pos`): a block
        // body followed by a postfix leaves the lambda as an intermediate
        // pratt-loop lhs the outer wrap never reaches.
        Ok(self.wrap_pos(self.emit.lambda(vec![name], body), lambda_start))
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
        // The Lambda spans from its first parameter through the body's last
        // token. Stamp it here rather than relying on the caller's `wrap_pos`:
        // a block body that can't absorb a trailing postfix (`x -> { … } . 1`)
        // leaves the lambda as an intermediate pratt-loop lhs that the outer
        // wrap never reaches, so it would otherwise be position-less.
        let lambda_start = self.peek0.start;
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
                    return Ok(Some(
                        self.wrap_pos(self.emit.lambda(names, body), lambda_start),
                    ));
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
                            return Ok(Some(
                                self.wrap_pos(self.emit.lambda(names, body), lambda_start),
                            ));
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
        // Carry the HogQLX tag-mode flag across the re-seek — restores /
        // text-boundary re-seeks happen mid-tag and must keep lexing
        // `#` the tag-mode way.
        let in_tag = self.lexer.in_hogqlx_tag();
        self.lexer = Lexer::with_pos(self.src, pos);
        self.lexer.set_in_hogqlx_tag(in_tag);
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
        // `(* [EXCLUDE(...)] REPLACE(...))` — ColumnExprColumns[Exclude]Replace. A bare
        // `* … REPLACE(…)` is a columnExpr only inside this paren form (or
        // `COLUMNS(* … REPLACE(…))`); the general asterisk path rejects REPLACE everywhere
        // else (function arg, tuple element, …) as cpp does. Recognise it here, consuming
        // the wrapping `)`, rather than via a peek-at-`)` heuristic that can't tell this
        // wrapper paren from a borrowed function-call paren.
        if self.peek() == TokenKind::Asterisk {
            let cp = self.checkpoint();
            self.bump()?;
            if let Ok((exclude, replace)) = self.parse_columns_decorators() {
                if replace.is_some() && self.peek() == TokenKind::RParen {
                    self.bump()?;
                    let node = self.emit.columns_expr(None, None, true, exclude, replace);
                    return Ok(self.wrap_pos_to(node, outer_start, self.last_consumed_end));
                }
            }
            self.restore(cp)?;
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
        // The bare `LPAREN ASTERISK [EXCLUDE(...)]? REPLACE(...) RPAREN` form —
        // the only ColumnsExpr-with-REPLACE shape whose ctx includes the outer
        // parens — is already handled above (the `peek == Asterisk` branch wraps
        // it at `outer_start`). Any ColumnsExpr reaching here came through a
        // `columns(...)` call or an extra wrapping paren, where cpp treats the
        // wrapping parens as a separate `ColumnExprParens` (stripped) — so leave
        // the inner span untouched rather than over-extending to the parens.
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
            | TokenKind::NullSafeEq
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
            // Optional `FILTER (WHERE …)` between the args and OVER. An invalid
            // FILTER (e.g. `filter ()`, no `(WHERE …)`) is, at a statement
            // boundary, cpp's completed `name(args)` statement followed by a
            // `filter(...)` call as the NEXT statement (`l() filter ()` -> `l()`
            // ; `filter()`); outside a statement boundary there is no split.
            let cp_before_filter = self.checkpoint();
            let filter_expr_for_window = match self.parse_optional_filter() {
                Ok(f) => f,
                Err(e) if e.fatal => return Err(e),
                Err(e) => {
                    if self.stmt_rhs_recover_on_pratt_rhs_failure {
                        self.restore(cp_before_filter)?;
                        None
                    } else {
                        return Err(e);
                    }
                }
            };
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
                        TokenKind::Ident | TokenKind::QuotedIdent => {
                            identifier_text(self.text(tok), tok.kind)
                        }
                        // A window name is an `identifier`, which admits only `kw_valid_as_identifier` keywords — the Hog-statement keywords (try / catch / finally / …) are not valid window names.
                        TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
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
            // Bare `ColumnExprAsterisk` admits only EXCLUDE — a trailing REPLACE has no bare production (REPLACE lives only inside `columns(...)` / `(*...)`), so consume exclude-only and leave any REPLACE for the enclosing context to reject, matching cpp's `a.* exclude(z) replace(...)` rejection.
            let exclude = self.parse_exclude_clause()?;
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
        // `<call>() FILTER (...)` is the aggregate FILTER clause, which requires
        // `(WHERE <expr>)`. An invalid FILTER (e.g. `filter ()`, no WHERE) is, at
        // a statement boundary, cpp's completed `<call>()` statement followed by a
        // `filter(...)` call as the NEXT statement (`l() filter ()` -> `l()` ;
        // `filter()`). Outside a statement boundary there is no split, so reject.
        let cp_before_filter = self.checkpoint();
        let filter_expr = match self.parse_optional_filter() {
            Ok(f) => f,
            Err(e) if e.fatal => return Err(e),
            Err(e) => {
                if self.stmt_rhs_recover_on_pratt_rhs_failure {
                    self.restore(cp_before_filter)?;
                    None
                } else {
                    return Err(e);
                }
            }
        };
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
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(tok), tok.kind)
                    }
                    // A window name is an `identifier`, which admits only `kw_valid_as_identifier` keywords — the Hog-statement keywords (try / catch / finally / …) are not valid window names.
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
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
        // `distinct()` with EMPTY parens is the zero-arg call `Call(distinct,
        // [])`, not the args DISTINCT-marker: cpp reads `count(distinct())` as
        // `count` over a nested `distinct()` call (cf. `SELECT distinct()`).
        // `distinct(x)` keeps the marker, so only empty `()` triggers this.
        let distinct_heads_empty_call =
            self.peek_next() == TokenKind::LParen && self.peek_lparen_is_empty();
        let distinct = if self.peek() == TokenKind::Keyword(Kw::Distinct)
            && !matches!(self.peek_next(), TokenKind::Comma)
            && !is_pure_infix_op(self.peek_next())
            && !distinct_heads_empty_call
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
        // cpp's window FILTER (`VISIT(ColumnExprWinFunction)`) grammar-parses
        // the WHERE body but never visits it; aggregate FILTER does visit.
        // We can't peek `OVER` until the body is consumed, so optimistically
        // parse with both suppressions (window form) and re-parse strictly
        // below if no OVER follows.
        let cp_before_filter = self.checkpoint();
        self.bump()?;
        self.expect(TokenKind::LParen, "(")?;
        self.expect_kw(Kw::Where, "WHERE")?;
        let prev_array_join = self.suppress_array_join_checks;
        let prev_unvisited = self.suppress_unvisited_clause_checks;
        self.suppress_array_join_checks = true;
        self.suppress_unvisited_clause_checks = true;
        let result = self.parse_expr_bp(0);
        self.suppress_array_join_checks = prev_array_join;
        self.suppress_unvisited_clause_checks = prev_unvisited;
        let expr = result?;
        self.expect(TokenKind::RParen, ")")?;
        // No OVER → aggregate FILTER. Re-parse strictly so cpp's visit-time
        // rejections (ARRAY JOIN, DATE/TIMESTAMP/INTERVAL, ColumnTypeExprEnum)
        // fire.
        if !matches!(self.peek(), TokenKind::Keyword(Kw::Over)) {
            self.restore(cp_before_filter)?;
            self.bump()?;
            self.expect(TokenKind::LParen, "(")?;
            self.expect_kw(Kw::Where, "WHERE")?;
            let strict_expr = self.parse_expr_bp(0)?;
            self.expect(TokenKind::RParen, ")")?;
            return Ok(Some(strict_expr));
        }
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

    /// True when the parenthesised type body starting at `peek0` is a complete
    /// `ColumnTypeExprEnum` list: `enumValue (COMMA enumValue)* COMMA?` where
    /// `enumValue: string EQ_SINGLE numberLiteral`. Mirrors ANTLR committing to
    /// the Enum alt only when EVERY entry matches; any non-numberLiteral value
    /// (`'a' = ''`, `'a' = x`, `'a' = 1 + 2`) or a `==` separator instead of `=`
    /// makes it fall through to `ColumnTypeExprParam` (a `columnExprList`).
    /// NOTE: the lexer's `EqDouble` is the *single* `=` (grammar EQ_SINGLE);
    /// `EqSingle` is `==`. numberLiteral folds to `Number` (plus optional sign)
    /// or the `inf` / `nan` keywords.
    fn paren_body_is_enum_value_list(&self) -> bool {
        let mut pos = self.peek0.start;
        loop {
            let mut probe = Lexer::with_pos(self.src, pos);
            // enumValue: string `=` numberLiteral, where `string` is
            // STRING_LITERAL | templateString — so an `f'…'` key (`a(f''=0)`) is
            // an enum value too, which cpp rejects as `ColumnTypeExprEnum`.
            if !matches!(
                probe.next_token().map(|t| t.kind),
                Ok(TokenKind::String | TokenKind::TemplateString)
            ) {
                return false;
            }
            if !matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::EqDouble)) {
                return false;
            }
            // numberLiteral: optional sign, then a number / leading-dot float /
            // inf / nan. The lexer assembles a `.`-float across tokens (`1.5` is
            // `1` `.` `5`), so after the leading number token consume the
            // `(Dot|Number)*` continuation run before reading the separator —
            // that keeps `'k' = 1.5e3` an enumValue while `'k' = 1 + 2` (an
            // operator after the number) and `'k' = x` / `'k' = ''` fall through.
            let mut t = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
            if matches!(t.kind, TokenKind::Plus | TokenKind::Dash) {
                t = match probe.next_token() {
                    Ok(t) => t,
                    Err(_) => return false,
                };
            }
            if !matches!(
                t.kind,
                TokenKind::Number
                    | TokenKind::Dot
                    | TokenKind::Keyword(Kw::Inf)
                    | TokenKind::Keyword(Kw::Nan)
            ) {
                return false;
            }
            let mut sep = match probe.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
            while matches!(sep.kind, TokenKind::Dot | TokenKind::Number) {
                sep = match probe.next_token() {
                    Ok(t) => t,
                    Err(_) => return false,
                };
            }
            match sep.kind {
                TokenKind::RParen => return true,
                TokenKind::Comma => {
                    pos = sep.end;
                    // Trailing comma (`… ,)`) closes a valid enum list.
                    let mut after = Lexer::with_pos(self.src, pos);
                    if matches!(after.next_token().map(|t| t.kind), Ok(TokenKind::RParen)) {
                        return true;
                    }
                }
                _ => return false,
            }
        }
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
            //
            // But ANTLR commits to Enum only when the WHOLE body is a valid
            // enumValue list — `string '=' numberLiteral`, comma-separated. If
            // any entry's value is not a numberLiteral (`q('a' = '')`, `q('a' =
            // x)`, `q('a' = 1 + 2)`) or the separator is `==` rather than `=`
            // (`q('a' == 1)`), ANTLR falls through to `ColumnTypeExprParam` (the
            // body is a `columnExprList`, e.g. the comparison `'a' = ''`), which
            // cpp ACCEPTS. So gate the reject on the full enum-list shape and let
            // the Param path below handle the rest.
            if self.paren_body_is_enum_value_list() {
                if self.suppress_unvisited_clause_checks {
                    // Unvisited clause: consume the enum body, return a placeholder.
                    while self.peek() != TokenKind::RParen {
                        self.bump()?;
                    }
                    self.expect(TokenKind::RParen, ")")?;
                    return Ok(format!("{head_name}(<discarded-enum>)"));
                }
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
            // A FATAL error means the nested type committed and failed a
            // visitor-level check — e.g. `q(w('k'=1))`, where the inner
            // `w('k'=1)` is a `ColumnTypeExprEnum` that cpp rejects. Propagate
            // it rather than masking it with the raw-text Param fallback (which
            // would over-accept). Mirrors `try_alt`'s fatal short-circuit.
            Err(e) if e.fatal => Err(e),
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
                | TokenKind::NullSafeEq
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
        //
        // ANTLR runs `getText()` only after matching the item as a `columnExpr`,
        // so the verbatim text is a *valid* expression. Validate that first:
        // parse the item as a columnExpr and require it to land on the param
        // terminator. Otherwise non-columnExpr junk — `()` (empty group),
        // `a() b` (juxtaposition), `Int NULL` — is swallowed as raw text and
        // accepted, where cpp rejects. Both callers (param-mode loop and the
        // `parse_type_param_item` fall-back) route through here.
        //
        // `getText()` matches the item but never VISITS it, so the visitor-level
        // "not supported" rejections (a `date '' ` / `timestamp ''` literal —
        // `a(date '')` — and friends) must not fire during this grammar-only
        // validation: cpp accepts them as raw param text. Suppress those checks
        // for the validation parse only. (A genuine `ColumnTypeExprEnum` is
        // already caught by `paren_body_is_enum_value_list` before we get here.)
        let validate_cp = self.checkpoint();
        let prev_suppress = self.suppress_unvisited_clause_checks;
        self.suppress_unvisited_clause_checks = true;
        let validated = self.parse_expr_bp(0);
        self.suppress_unvisited_clause_checks = prev_suppress;
        validated?;
        if !matches!(self.peek(), TokenKind::Comma | TokenKind::RParen) {
            return Err(self.err("type parameter is not a valid expression"));
        }
        self.restore(validate_cp)?;

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

    /// Table-function argument list (cpp's `tableArgList`): each arg is a plain
    /// `columnExpr` or a named `ident := expr`. Unlike a general function call
    /// (cpp's `ColumnExprCallSelect`), a *bare* `SELECT …` is not a valid table
    /// arg — cpp rejects `FROM a(SELECT 1)` but accepts `FROM a((SELECT 1))` —
    /// so this skips the bare-`selectSetStmt` alt that `parse_arg_list` allows.
    pub(crate) fn parse_table_arg_list(
        &mut self,
        terminator: TokenKind,
    ) -> Result<Vec<E::Value>, ParseError> {
        let mut args = Vec::new();
        if self.peek() == terminator {
            return Ok(args);
        }
        loop {
            args.push(self.parse_table_argument()?);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if self.peek() == terminator {
                break;
            }
        }
        Ok(args)
    }

    /// One table-function argument: a named `ident := expr`, else a plain
    /// `columnExpr` (no bare-`SELECT` alt — see `parse_table_arg_list`). The
    /// named-arg gate mirrors `parse_call_argument_with` (cpp's
    /// `ColumnExprNamedArg` admits the full `identifier` rule).
    fn parse_table_argument(&mut self) -> Result<E::Value, ParseError> {
        let name_kw_ok =
            matches!(self.peek(), TokenKind::Keyword(kw) if kw_valid_as_identifier(kw));
        if (matches!(self.peek(), TokenKind::Ident | TokenKind::QuotedIdent) || name_kw_ok)
            && self.peek_next() == TokenKind::ColonEquals
        {
            let named_start = self.peek0.start;
            let name_tok = self.bump()?;
            let name = identifier_text(self.text(name_tok), name_tok.kind);
            self.bump()?; // consume `:=`
            let value = self.parse_expr_bp(0)?;
            // cpp's `ColumnExprNamedArg` is a value-tier primary, so a
            // trailing value-tier operator re-roots onto the NamedArgument
            // itself when the value parse stopped at a bare-alias boundary:
            // `f(y := 1 as x [1])` is `ArrayAccess(NamedArgument(…), 1)`.
            let named = self.emit.named_argument(&name, value);
            return self.pratt_continue_with_lhs(named, 0, named_start);
        }
        self.parse_expr_bp(0)
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
            let named_start = self.peek0.start;
            let name_tok = self.bump()?;
            let name = identifier_text(self.text(name_tok), name_tok.kind);
            self.bump()?; // consume `:=`
            let value = self.parse_expr_bp(0)?;
            // See `parse_table_argument`: a trailing value-tier operator
            // re-roots onto the NamedArgument primary, matching cpp.
            let named = self.emit.named_argument(&name, value);
            return self.pratt_continue_with_lhs(named, 0, named_start);
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
                        // Grammar: tuple access takes a DECIMAL_LITERAL index. Rust's lexer folds hex / octal / float into one `Number` kind, so re-check the text. cpp's lexer matches `0123` / `017` as OCTAL_LITERAL (leading zero, all-octal digits) and rejects them here, but `08` / `019` are DECIMAL (8 and 9 are not octal digits) and accept.
                        let text = self.text(part);
                        if !is_decimal_literal(text) {
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
                        // Same DECIMAL_LITERAL check as the regular `.<N>` branch above.
                        let text = self.text(part);
                        if !is_decimal_literal(text) {
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

    /// Parse the RHS of `IN` / `NOT IN`, consuming an optional `COHORT` marker.
    /// cpp only takes the grammar's `COHORT?` alternative when a `columnExpr`
    /// actually follows. `try_consume_cohort_marker` rejects the obvious
    /// terminators up front, but a value that *starts* to parse and then fails
    /// (e.g. `a IN COHORT < b`, where `< b` is a comparison on the whole
    /// `(a in COHORT)` and is not a cohort value) must also fall back to
    /// `COHORT`-as-Field. Try the cohort value and, on failure, restore and
    /// re-read `COHORT` as the IN rhs Field. Returns `(is_cohort, rhs)`.
    fn parse_in_cohort_rhs(&mut self) -> Result<(bool, E::Value), ParseError> {
        let cp = self.checkpoint();
        if self.try_consume_cohort_marker()? {
            if let Ok(rhs) = self.parse_expr_bp(BP_COMPARE + 1) {
                // The marker holds only when the value is a *complete* columnExpr
                // with nothing left dangling. If a fresh primary sits right after
                // it, the "value" was really an infix operator that parsed as a
                // bare Field / `*` (`cohort * b`, `cohort like b`, `cohort is
                // null`): two primaries can't be adjacent, so `cohort` is part of
                // the rhs expression instead. `cohort < b` / `cohort + b` already
                // fail the value parse above (incomplete tag / unary `+`), so they
                // restore here too. Then the non-marker parse below yields
                // `a in (cohort * b)` or `(a in cohort) like b` per precedence.
                if !matches!(
                    self.peek(),
                    TokenKind::Number
                        | TokenKind::String
                        | TokenKind::Ident
                        | TokenKind::QuotedIdent
                        | TokenKind::Keyword(Kw::Null | Kw::Inf | Kw::Nan | Kw::True | Kw::False)
                ) {
                    return Ok((true, rhs));
                }
            }
            self.restore(cp)?;
        }
        let rhs = self.parse_expr_bp(BP_COMPARE + 1)?;
        Ok((false, rhs))
    }

    /// True when the `lambda` keyword sitting at `peek_next` (peek1) is the head
    /// of a `lambdaExpr` body — `LAMBDA (identifier (COMMA identifier)* COMMA?)?
    /// COLON …`. Probes past the keyword with a shadow lexer. Used by the
    /// AS-alias infix to distinguish a lambda value (`… AS lambda y: y`, only
    /// reachable in INTERPOLATE) from a plain `lambda` alias (`1 AS lambda`).
    fn lambda_body_follows_after_peek_next(&self) -> bool {
        let mut lex = Lexer::with_pos(self.src, self.peek1.end);
        loop {
            match lex.next_token().map(|t| t.kind) {
                // bare `lambda :` or the `:` after the last param
                Ok(TokenKind::Colon) => return true,
                // a parameter identifier — must be followed by `,` (more params)
                // or `:` (body); anything else means this isn't a lambda head.
                Ok(TokenKind::Ident | TokenKind::QuotedIdent) => {
                    match lex.next_token().map(|t| t.kind) {
                        Ok(TokenKind::Colon) => return true,
                        Ok(TokenKind::Comma) => continue,
                        _ => return false,
                    }
                }
                _ => return false,
            }
        }
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
                    self.bump()?; // NOT
                    self.bump()?; // BETWEEN
                    let (low, high) = self.parse_between_body()?;
                    let prev = std::mem::replace(lhs, self.emit.null());
                    let between_inner = self.emit.between(prev, low, high, true);
                    *lhs = self.wrap_pos(between_inner, lhs_start);
                    Ok(Some(true))
                }
                TokenKind::Keyword(Kw::In) => {
                    if BP_COMPARE < min_bp {
                        return Ok(None);
                    }
                    self.bump()?;
                    self.bump()?;
                    let (cohort, rhs) = self.parse_in_cohort_rhs()?;
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
            // `[e] BETWEEN low AND high`. BETWEEN binds at the comparison tier
            // (BP_BETWEEN), so the bounds are parsed above BP_AND and cannot swallow
            // a trailing `AND` chain — `a BETWEEN b AND c AND d` becomes
            // `(a BETWEEN b AND c) AND d`. The low bound parses at BP_BETWEEN (a
            // nested BETWEEN chains into it); the high at BP_BETWEEN + 1 (a trailing
            // BETWEEN chains left-associatively via the outer Pratt loop instead).
            TokenKind::Keyword(Kw::Between) => {
                if BP_BETWEEN < min_bp {
                    return Ok(None);
                }
                self.bump()?;
                let (low, high) = self.parse_between_body()?;
                let prev = std::mem::replace(lhs, self.emit.null());
                let between_inner = self.emit.between(prev, low, high, false);
                *lhs = self.wrap_pos(between_inner, lhs_start);
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
                let (cohort, rhs) = self.parse_in_cohort_rhs()?;
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
                // `AS lambda <params> :` is a `lambdaExpr` value, not an alias —
                // only valid in `INTERPOLATE (expr AS columnExpr)`, where refusing
                // the alias here lets the INTERPOLATE clause pick up the AS and
                // parse the lambda. But a bare `AS lambda` with NO lambda body is
                // a plain alias (`1 as lambda` -> `Alias(1, 'lambda')`, cpp
                // accepts; `1 as lambda: 2` rejects on both since the lambda-expr
                // form isn't allowed in plain expression context — the alias
                // absorbs `lambda` and the trailing `: 2` then fails). So refuse
                // only when a lambda body actually follows.
                if matches!(self.peek_next(), TokenKind::Keyword(Kw::Lambda))
                    && self.lambda_body_follows_after_peek_next()
                {
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
                // `AS`/aliases sit in the loosest (boolean) grammar tier, so only an
                // outer-tier operator may bind to a bare alias — `AND`, `OR`, ternary
                // (`?`), or a chained `AS` wrap it, while a value-tier operator (`+`,
                // `[`, `::`, `BETWEEN`, `IS`, a call `()`, …) cannot and terminates the
                // expression (cpp rejects `1 AS x + 2`; parenthesise as `(1 AS x) + 2`).
                // The Pratt loop's next iteration reads this flag and stops before
                // folding a value-tier op onto the alias.
                self.after_bare_alias = true;
                Ok(Some(true))
            }
            _ => Ok(None),
        }
    }

    /// Parse the `<low> AND <high>` body of a BETWEEN. BETWEEN binds at the
    /// comparison tier (`BP_BETWEEN`, tighter than `AND`/`OR`/`NOT`), matching
    /// cpp's grammar where the tested expression and both bounds are
    /// `columnExprValue`. The `AND` separator sits at `BP_AND < BP_BETWEEN`, so
    /// the low bound stops before it rather than swallowing the surrounding
    /// `AND` chain. The low bound parses at `BP_BETWEEN` (a nested BETWEEN
    /// chains into it — cpp's greedy interior operand); the high bound at
    /// `BP_BETWEEN + 1` (a trailing BETWEEN instead chains left-associatively
    /// onto the whole expression via the outer Pratt loop).
    fn parse_between_body(&mut self) -> Result<(E::Value, E::Value), ParseError> {
        let low = self.parse_expr_bp(BP_BETWEEN)?;
        self.expect_kw(Kw::And, "AND")?;
        let high = self.parse_expr_bp(BP_BETWEEN + 1)?;
        Ok((low, high))
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

/// Is `text` a HogQL `DECIMAL_LITERAL` (base-10 integer) as the lexer would
/// classify it? Used after `#`, `.`, and `?.`, all of which the grammar
/// restricts to DECIMAL_LITERAL. Rust's lexer folds every numeric literal
/// into one `Number` kind, so we re-check the text and reject what cpp's
/// lexer would tokenize as something else: hex (`0x6`), floats (`1e3`,
/// `1.5`), and OCTAL_LITERAL — a leading-zero run of octal digits (`017`,
/// `00`), which the lexer matches as OCTAL before DECIMAL. A leading-zero
/// number containing an 8 or 9 (`08`, `019`) is NOT octal, so the lexer
/// reads it as DECIMAL and it is allowed.
fn is_decimal_literal(text: &str) -> bool {
    !text.is_empty()
        && text.bytes().all(|b| b.is_ascii_digit())
        && !(text.len() >= 2
            && text.starts_with('0')
            && text.bytes().all(|b| b.is_ascii_digit() && b <= b'7'))
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
pub(crate) fn is_pure_infix_op(tok: TokenKind) -> bool {
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
            | TokenKind::NullSafeEq
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
