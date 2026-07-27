//! `SELECT` statement parsing, including the set-operator chain wrapper
//! and all per-clause helpers: columns, WHERE, GROUP BY (and its CUBE /
//! ROLLUP / GROUPING SETS variants), HAVING, QUALIFY, WINDOW, ORDER BY +
//! INTERPOLATE, LIMIT (regular + BY) and OFFSET, plus the trailing
//! set-level decorators that decorate a `selectSetStmt` rather than the
//! inner `selectStmt`.
//!
//! ARRAY JOIN is handled here (not in `join.rs`) because the grammar
//! attaches it to the SELECT, not to the join chain.

use super::expr::is_bare_field;
use super::{
    check_alias_not_reserved, format_set_op, identifier_text, inject_ctes_into_select,
    kw_allowed_as_implicit_alias, kw_valid_as_identifier, merge_select_decorators, Parser, BP_MULT,
};
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, TokenKind};

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    pub(crate) fn parse_select_set_stmt(&mut self) -> Result<E::Value, ParseError> {
        // Guard the subquery / set recursion (`parse_select_set_stmt` ↔ `parse_select_stmt_with_parens` on each `(` / `WITH (`) so `(select (select …))` nested past the cap rejects cleanly instead of overflowing the host stack (uncatchable SIGSEGV). Shares the counter with expression + statement nesting.
        self.with_recursion_guard(Self::parse_select_set_stmt_inner)
    }

    fn parse_select_set_stmt_inner(&mut self) -> Result<E::Value, ParseError> {
        let stmt_start = self.peek0.start;
        let first = self.parse_select_stmt_with_parens()?;
        let mut subsequent: Vec<E::Value> = Vec::new();
        while let Some(op) = self.try_consume_set_op()? {
            let next = self.parse_select_stmt_with_parens()?;
            subsequent.push(self.emit.select_set_node(next, Some(op.as_str())));
        }

        // Optional trailing ORDER BY / LIMIT / OFFSET at the
        // selectSetStmt level — these decorate the whole set rather than a
        // single SELECT. The C++ visitor pushes them onto the SelectSetQuery
        // wrapper (or, if no UNION, onto the single inner SelectQuery).
        //
        // Snapshot whether ANY set-level trailing decorator is about
        // to be consumed; ORDER BY gets consumed-and-dropped (cpp's
        // VISIT(SelectSetStmt) ignores it) so it wouldn't show up in
        // the resulting `trailing` vec, but its presence still blocks
        // the OFFSET-lift below — cpp lifts only when the set-stmt
        // has NO trailing decorators of any kind.
        let has_set_level_trailing = matches!(
            self.peek(),
            TokenKind::Keyword(Kw::Order)
                | TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
        );
        // A lone `{placeholder}` body can't carry set-level LIMIT / OFFSET (only
        // SelectQuery / SelectSetQuery do), so cpp drops them and never visits
        // the subtree — see the `body_takes_decorators` drop below, which only
        // fires when `subsequent.is_empty()`. Tell the decorator parser so it
        // tolerates an unsupported date literal in that discarded LIMIT /
        // OFFSET, the same way the always-discarded ORDER BY does. A real
        // `(select …)` body keeps them, AND a set op (UNION / EXCEPT / …) wraps
        // the result in a decorator-carrying SelectSetQuery — so both stay
        // strict; only the lone-placeholder case is suppressed.
        let body_is_placeholder = subsequent.is_empty()
            && !matches!(
                self.emit.node_kind(&first).as_deref(),
                Some("SelectQuery") | Some("SelectSetQuery")
            );
        let trailing = self.parse_trailing_set_decorators(body_is_placeholder)?;

        if subsequent.is_empty() {
            // cpp's `VISIT(SelectSetStmt)` only writes `limit_percent`
            // and `limit_with_ties` in the multi-set branch (lines
            // 716-721 of parser_json.cpp). The single-select branch
            // (lines 633-651) writes only `limit` and `offset`. Mirror
            // that: drop those two fields when collapsing to a single
            // SelectQuery.
            let filtered: Vec<(String, E::Value)> = trailing
                .into_iter()
                .filter(|(k, _)| k != "limit_percent" && k != "limit_with_ties")
                .collect();
            // Clear the lift sentinel on the inner — it's only meaningful
            // when wrapping in a SelectSetQuery.
            let mut first = first;
            self.emit.remove_field(&mut first, "__rust_offset_liftable");
            // A set-level LIMIT / OFFSET clause has nowhere to attach on a
            // bare `{placeholder}` select body — only `SelectQuery` /
            // `SelectSetQuery` carry those fields — so it is dropped, the
            // same way cpp does (`#58885`). Without this the clause would
            // be written onto the `Placeholder` node and crash AST
            // deserialization.
            let body_takes_decorators = matches!(
                self.emit.node_kind(&first).as_deref(),
                Some("SelectQuery") | Some("SelectSetQuery")
            );
            if !body_takes_decorators {
                return Ok(first);
            }
            // Do NOT extend the inner SelectQuery / SelectSetQuery's
            // `end` to cover trailing set-level decorators. cpp's
            // `VISIT(SelectStmt)` positions the SelectQuery from its own
            // ctx (which spans whatever the selectStmt rule itself
            // matched), and the outer `VISIT(SelectSetStmt)` adds
            // limit / offset / limit_with_ties / limit_percent fields
            // without re-stamping positions — so the end stays at the
            // last body-level clause cpp consumed. Mirror that exactly.
            let merged = merge_select_decorators(&self.emit, first, filtered);
            // `has_set_level_trailing` is unused here (we keep it
            // declared above for parity with the set-stmt branch's
            // OFFSET-lift heuristic, which it still feeds).
            let _ = has_set_level_trailing;
            return Ok(merged);
        }
        // cpp's `VISIT(SelectSetStmt)` lifts the inner SelectQuery's
        // OFFSET to the outer SelectSetQuery — but ONLY for the
        // verbose `LIMIT n OFFSET m` form (after an explicit LIMIT).
        // The compact `LIMIT n, m`, bare `OFFSET m` (no LIMIT), and
        // limit-by's trailing bare OFFSET all stay on the inner.
        // LIMIT, PERCENT, WITH TIES always stay on the inner.
        //
        // Examples:
        //   `... except select 1 limit 5 OFFSET 10`     → lift (outer.offset=10)
        //   `... except select 1 limit 5, 10`           → keep  (inner.offset=10)
        //   `... except select 1 offset 10`             → keep  (inner.offset=10)
        //   `... except select 1 limit 5 by a offset 10` → keep  (inner.offset=10)
        //
        // The discriminator is the `__rust_offset_liftable` sentinel
        // that `parse_trailing_limit_and_offset` and the regular
        // limit-and-offset branch of `parse_limit_clauses` mark when
        // they consume the verbose form.
        let mut first = first;
        // Clean the lift sentinel off the initial SELECT — cpp's lift
        // only ever applies to the LAST inner SELECT, never the first.
        self.emit.remove_field(&mut first, "__rust_offset_liftable");
        // …and off every non-last subsequent SELECT (the lift only
        // applies to the trailing inner).
        let last_idx = subsequent.len().saturating_sub(1);
        for (i, node) in subsequent.iter_mut().enumerate() {
            if i == last_idx {
                continue;
            }
            if let Some(mut sq) = self.emit.get_field(node, "select_query") {
                self.emit.remove_field(&mut sq, "__rust_offset_liftable");
                self.emit.set_field(node, "select_query", sq);
            }
        }
        // Lift the inner's verbose OFFSET to the outer SelectSetQuery
        // only when the set-stmt has NO trailing decorators of any
        // kind. Any of:
        //
        //   - LIMIT / OFFSET at the set level — would overwrite the
        //     lifted slot or claim it directly.
        //   - ORDER BY at the set level — cpp's `VISIT(SelectSetStmt)`
        //     drops it but its presence still tells cpp's adaptive
        //     parser that the inner's OFFSET is "complete" at the
        //     inner level and shouldn't surface upward.
        //
        // Examples:
        //   ... UNION ... LIMIT 5 OFFSET 10                         → lift (no trailing)
        //   ... UNION ... LIMIT X OFFSET Y LIMIT Z, V               → no lift
        //   ... UNION ... LIMIT 5 % WITH TIES OFFSET m ORDER BY 1   → no lift
        //
        // `has_set_level_trailing` captures the ORDER-BY case (the
        // trailing decorator is consumed-and-dropped, so an
        // after-the-fact `trailing.iter()` check misses it).
        let inner_offset = if let Some(last) = subsequent.last_mut() {
            if let Some(mut sq) = self.emit.get_field(last, "select_query") {
                let liftable = self
                    .emit
                    .remove_field(&mut sq, "__rust_offset_liftable")
                    .and_then(|v| self.emit.as_bool(&v))
                    == Some(true);
                let off = if liftable && !has_set_level_trailing {
                    self.emit.remove_field(&mut sq, "offset")
                } else {
                    None
                };
                self.emit.set_field(last, "select_query", sq);
                off
            } else {
                None
            }
        } else {
            None
        };
        let mut wrap = self.emit.select_set_query(first, subsequent);
        if let Some(off) = inner_offset {
            self.emit.set_field(&mut wrap, "offset", off);
        }
        // Trailing decorators are applied last so they can override
        // the lifted inner offset when present.
        for (k, v) in trailing {
            self.emit.set_field(&mut wrap, &k, v);
        }
        Ok(self.wrap_pos(wrap, stmt_start))
    }

    fn try_consume_set_op(&mut self) -> Result<Option<String>, ParseError> {
        let base = match self.peek() {
            TokenKind::Keyword(Kw::Union) => "UNION",
            TokenKind::Keyword(Kw::Intersect) => "INTERSECT",
            TokenKind::Keyword(Kw::Except) => "EXCEPT",
            _ => return Ok(None),
        };
        self.bump()?;
        let modifier = if self.eat_kw(Kw::All)? {
            Some("ALL")
        } else if self.eat_kw(Kw::Distinct)? {
            Some("DISTINCT")
        } else {
            None
        };
        let by_name = matches!(self.peek(), TokenKind::Keyword(Kw::By))
            && self.peek_next() == TokenKind::Keyword(Kw::Name);
        if by_name {
            self.bump()?;
            self.bump()?;
        }
        let op = format_set_op(base, modifier, by_name).ok_or_else(|| {
            self.err(format!(
                "invalid set operator {base} with modifier {modifier:?}"
            ))
        })?;
        Ok(Some(op))
    }

    fn parse_trailing_set_decorators(
        &mut self,
        body_is_placeholder: bool,
    ) -> Result<Vec<(String, E::Value)>, ParseError> {
        let mut out: Vec<(String, E::Value)> = Vec::new();
        // `selectSetStmt`'s `orderByClause?` slot at this level is
        // parsed by ANTLR but cpp's `VISIT(SelectSetStmt)` never emits
        // it — `(SELECT 1) ORDER BY 2` drops the ORDER BY entirely.
        // Consume-and-discard so the grammar still accepts the input
        // without leaking an `order_by` onto a SelectSetQuery /
        // Placeholder / standalone SelectQuery target.
        //
        // EXCEPTION: when `suppress_setstmt_trailing_order_by` is set,
        // we leave the ORDER BY untouched so the outer caller can
        // absorb it. This is set by `parse_call_argument_select` for
        // inputs like `f((select 1) order by 1)` — cpp prefers
        // ColumnExprFunction here, which means the ORDER BY belongs
        // to the function-call's `orderByClause`, not the inner set
        // statement.
        if !self.suppress_setstmt_trailing_order_by
            && matches!(self.peek(), TokenKind::Keyword(Kw::Order))
            && self.peek_next() == TokenKind::Keyword(Kw::By)
        {
            self.bump()?;
            self.bump()?;
            // cpp never visits this discarded orderByClause, so an
            // unsupported `date`/`timestamp` literal anywhere in its
            // (also unvisited) subtree is tolerated. Suppress the fatal
            // date-literal check for the duration of this parse; it
            // intentionally leaks into nested selects/calls here, since
            // cpp visits none of that subtree either.
            let prev_date = self.suppress_unvisited_clause_checks;
            self.suppress_unvisited_clause_checks = true;
            let order_by_result = self.parse_order_expr_list();
            self.suppress_unvisited_clause_checks = prev_date;
            order_by_result?;
            // Optional trailing `INTERPOLATE [(...)]` is part of the
            // orderByClause grammar; consume-and-drop alongside the
            // order_by we're discarding here.
            if self.eat_kw(Kw::Interpolate)? && self.eat(TokenKind::LParen)? {
                let mut depth: i32 = 1;
                while depth > 0 {
                    match self.peek() {
                        TokenKind::LParen => depth += 1,
                        TokenKind::RParen => depth -= 1,
                        // EOF with the `(` still open is an unterminated clause —
                        // cpp rejects ("mismatched input '<EOF>'"). This fires when
                        // a `#`-comment inside the parens (`interpolate ( # 6 )`)
                        // swallows the closing `)` to end-of-line; break-ing here
                        // would silently accept it.
                        TokenKind::Eof => return Err(self.err("unterminated INTERPOLATE clause")),
                        _ => {}
                    }
                    self.bump()?;
                }
            }
        }
        // Trailing LIMIT / OFFSET. For a `{placeholder}` body these are
        // dropped (the body can't carry them) and cpp never visits them, so —
        // exactly like the ORDER BY above — tolerate an unsupported date
        // literal inside. Gate on `body_is_placeholder` so a real `(select …)`
        // body, whose LIMIT / OFFSET ARE kept and visited, stays strict.
        // Restore the flag on every exit (incl. errors an outer `try_alt` may
        // roll back) before propagating.
        let prev_date = self.suppress_unvisited_clause_checks;
        if body_is_placeholder {
            self.suppress_unvisited_clause_checks = true;
        }
        let limit_offset_result = self.parse_set_trailing_limit_offset(&mut out);
        self.suppress_unvisited_clause_checks = prev_date;
        limit_offset_result?;
        Ok(out)
    }

    /// Parse the trailing `limitAndOffsetClauseOptional` of a `selectSetStmt`,
    /// pushing any `limit` / `offset` / `limit_percent` / `limit_with_ties`
    /// decorators onto `out`. Split out of `parse_trailing_set_decorators` so
    /// the caller can scope the date-literal-check suppression around it.
    /// Mirrors the grammar:
    ///   `LIMIT columnExpr PERCENT? (COMMA columnExpr)? (WITH TIES)?`
    ///   `LIMIT columnExpr PERCENT? (WITH TIES)? OFFSET columnExpr`
    ///   `OFFSET columnExpr`
    fn parse_set_trailing_limit_offset(
        &mut self,
        out: &mut Vec<(String, E::Value)>,
    ) -> Result<(), ParseError> {
        if self.eat_kw(Kw::Limit)? {
            // The initial parse stops at BP_MULT+1 so `limit_resolve_percent`
            // sees `%` undigested and can decide PERCENT-marker vs modulo.
            // When `%` resolves to the PERCENT marker the body is done; in
            // any other case (no `%`, or `%` resolved as modulo) the body
            // may still extend with lower-precedence operators (additive,
            // comparison, AND, OR), so continue the Pratt loop at BP=0.
            // See `parse_limit_clauses` for why `limit_body_depth`
            // wraps the whole body parse.
            self.limit_body_depth += 1;
            let body = self.parse_limit_body();
            self.limit_body_depth -= 1;
            let (first, percent) = body?;
            let mut with_ties = self.peek_kw2(Kw::With, Kw::Ties);
            if with_ties {
                self.bump()?;
                self.bump()?;
            }
            let (limit, offset) = if self.eat(TokenKind::Comma)? {
                // `LIMIT a, b` — cpp emits limit=a, offset=b (no
                // swap). The visitor reads the slots in source order
                // for the SelectSetStmt's trailing clause.
                let second = self.parse_expr_bp(0)?;
                (first, Some(second))
            } else if self.eat_kw(Kw::Offset)? {
                let off = self.parse_expr_bp(0)?;
                (first, Some(off))
            } else {
                (first, None)
            };
            // Trailing `WITH TIES` after the compact comma form.
            if !with_ties && self.peek_kw2(Kw::With, Kw::Ties) {
                self.bump()?;
                self.bump()?;
                with_ties = true;
            }
            // cpp's visitor overwrites `limit` (always — the outer
            // clause has one) but only writes the optional
            // accompanying fields when they're present in the outer
            // clause itself: a bare `LIMIT n` outer preserves the
            // inner's `offset`, `limit_percent`, and `limit_with_ties`.
            out.push(("limit".into(), limit));
            if let Some(off) = offset {
                out.push(("offset".into(), off));
            }
            if percent {
                out.push(("limit_percent".into(), self.emit.bool(true)));
            }
            if with_ties {
                out.push(("limit_with_ties".into(), self.emit.bool(true)));
            }
        } else if self.eat_kw(Kw::Offset)? {
            // `offsetOnlyClause: OFFSET columnExpr` — a full
            // `columnExpr`, so parse at BP=0; a `BP_MULT+1` bound
            // stranded any lower-precedence tail (`offset (x) or y`,
            // `offset (x) ignore nulls`).
            let off = self.parse_expr_bp(0)?;
            out.push(("offset".into(), off));
        }
        Ok(())
    }

    fn parse_select_stmt_with_parens(&mut self) -> Result<E::Value, ParseError> {
        // `WITH … (selectSet)` — paren'd set wrapper form with CTEs.
        // Consume the WITH clause and its CTEs, then peek the next token
        // to decide between the two valid continuations:
        //   - `(` → paren-wrapped selectSet that inherits the CTEs
        //   - `SELECT` → bare WITH-SELECT; thread CTEs into parse_select_stmt
        if matches!(self.peek(), TokenKind::Keyword(Kw::With)) {
            // Capture WITH's start so the resulting SelectQuery /
            // SelectSetQuery has a span starting at WITH rather than at
            // the inner SELECT — cpp's selectStmt ctx covers the whole
            // WITH-led statement.
            let with_start = self.peek0.start;
            self.bump()?; // WITH
            let recursive = self.eat_kw(Kw::Recursive)?;
            let mut ctes = self.parse_with_expr_list()?;
            if recursive {
                for cte in ctes.iter_mut() {
                    self.emit.set_field(cte, "recursive", self.emit.bool(true));
                }
            }
            if matches!(self.peek(), TokenKind::LParen) {
                self.bump()?;
                let mut inner = self.parse_select_set_stmt()?;
                self.expect(TokenKind::RParen, ")")?;
                inject_ctes_into_select(&self.emit, &mut inner, ctes);
                // cpp's `WITH ctes (selectSet)` ctx for the outer
                // SelectSetQuery starts at the `(`, NOT at WITH. The
                // CTEs are injected into the inner set's SelectQuery,
                // but the outer span doesn't widen to cover WITH.
                // Keep `inner`'s existing positions untouched.
                return Ok(inner);
            }
            return self.parse_select_stmt_body(Some(ctes), Some(with_start));
        }
        if self.eat(TokenKind::LParen)? {
            let inner = self.parse_select_set_stmt()?;
            self.expect(TokenKind::RParen, ")")?;
            return Ok(inner);
        }
        // `selectStmtWithParens` grammar admits a bare `placeholder` as
        // its fourth alternative — `{name}` standing in for a whole
        // select. Defer to the expression parser, which already knows
        // how to emit a Placeholder node for `{…}`. cpp's
        // `VISIT(Placeholder)` covers the whole `{ … }` span — wrap so
        // the bare-placeholder select body carries that position.
        if self.peek() == TokenKind::LBrace {
            let placeholder_start = self.peek0.start;
            let placeholder = self.parse_brace_placeholder_only()?;
            return Ok(self.wrap_pos(placeholder, placeholder_start));
        }
        self.parse_select_stmt()
    }

    /// Single `SELECT` statement with all its clauses.
    fn parse_select_stmt(&mut self) -> Result<E::Value, ParseError> {
        // WITH at the start; consume CTEs here then delegate to the body
        // helper. This lets parse_select_stmt_with_parens hand us
        // already-parsed CTEs when it disambiguated WITH+`(`.
        // Capture the WITH start before consuming so the body wraps the
        // resulting SelectQuery with a span beginning at WITH (cpp's
        // selectStmt ctx covers the whole WITH-led statement).
        let with_start = if matches!(self.peek(), TokenKind::Keyword(Kw::With)) {
            Some(self.peek0.start)
        } else {
            None
        };
        let mut ctes: Option<Vec<E::Value>> = None;
        if self.eat_kw(Kw::With)? {
            let recursive = self.eat_kw(Kw::Recursive)?;
            let mut parsed = self.parse_with_expr_list()?;
            if recursive {
                for cte in parsed.iter_mut() {
                    self.emit.set_field(cte, "recursive", self.emit.bool(true));
                }
            }
            ctes = Some(parsed);
        }
        self.parse_select_stmt_body(ctes, with_start)
    }

    /// SELECT statement body, starting at the `SELECT` keyword (after
    /// any WITH clause has been consumed). `pre_parsed_ctes` carries
    /// CTEs that the caller already consumed; `override_start` carries
    /// the caller-snapshotted position of the WITH keyword so the
    /// resulting SelectQuery's span starts at WITH rather than at the
    /// inner SELECT — cpp's selectStmt ctx covers the whole
    /// WITH-led statement.
    fn parse_select_stmt_body(
        &mut self,
        pre_parsed_ctes: Option<Vec<E::Value>>,
        override_start: Option<usize>,
    ) -> Result<E::Value, ParseError> {
        let stmt_start = override_start.unwrap_or(self.peek0.start);
        let mut obj = self.emit.select_query_empty();
        if let Some(ctes) = pre_parsed_ctes {
            self.emit
                .set_field(&mut obj, "ctes", self.emit.list_value(ctes));
        }

        // Catch typo'd SELECT keyword (e.g. `SELEC`) with the exact ANTLR-style
        // "mismatched input" message cpp emits, so cross-backend assertions match
        // on equality, not just substring. End position spans through the rest of
        // the source (matching C++ which highlights the whole malformed region,
        // not just the first token).
        if !matches!(self.peek(), TokenKind::Keyword(Kw::Select)) {
            let raw = if self.peek0.kind == TokenKind::Eof {
                "<eof>"
            } else {
                self.text(self.peek0)
            };
            return Err(ParseError::syntax(
                format!("mismatched input '{raw}' expecting {{SELECT, WITH, '{{', '(', '<'}}"),
                self.peek0.start,
                self.src.len(),
            ));
        }
        self.bump()?;
        let cp_after_select = self.checkpoint();
        let distinct = self.eat_kw(Kw::Distinct)?;
        if distinct {
            // `SELECT DISTINCT` is the modifier only when a column follows it.
            // When the next token ends the column list (comma / EOF / `)` / `;`)
            // or opens a clause (`ORDER BY` / `WHERE` / `GROUP BY` / `LIMIT` /
            // …), cpp's ALL(*) re-reads DISTINCT as the sole column Field instead
            // (`SELECT DISTINCT` -> `[Field(distinct)]`, `SELECT DISTINCT ORDER BY
            // 1` -> `[Field(distinct)]` + ORDER BY). FROM is the exception:
            // `SELECT DISTINCT FROM x` keeps DISTINCT a modifier and rejects via
            // the FROM-implicit-alias footgun, matching cpp.
            // `distinct()` (empty parens) is the zero-arg call `Call(distinct,
            // [])`, not the modifier — cpp can't read DISTINCT as the modifier
            // with only `()` (no column) after, so it backs off to a function
            // call. `distinct(x)` stays the modifier on `(x)`; only empty `()`.
            let distinct_is_column = matches!(
                self.peek(),
                TokenKind::Comma | TokenKind::Eof | TokenKind::RParen | TokenKind::Semicolon
            ) || (self.peek_is_clause_terminator()
                && self.peek() != TokenKind::Keyword(Kw::From))
                || (self.peek() == TokenKind::LParen && self.peek_next() == TokenKind::RParen);
            if distinct_is_column {
                self.restore(cp_after_select)?;
            } else {
                self.emit
                    .set_field(&mut obj, "distinct", self.emit.bool(true));
            }
        }
        // `topClause: TOP DECIMAL_LITERAL (WITH TIES)?` — accepted by
        // the grammar, rejected by the cpp visitor as unsupported. A
        // bare `top` (not followed by a number) is still a valid Field
        // / column name, so only treat `TOP <number>` as the clause.
        if matches!(self.peek(), TokenKind::Keyword(Kw::Top))
            && matches!(self.peek_next(), TokenKind::Number)
        {
            return Err(ParseError::not_implemented(
                "Unsupported: SelectStmt.topClause()",
                self.peek0.start,
                self.src.len(),
            ));
        }
        let columns = self.parse_select_columns()?;
        if columns.is_empty() {
            // `SELECT FROM …` / `SELECT WHERE …` — no expression in the
            // column slot. The C++ parser rejects this; surface as a
            // syntax error including "reserved keyword" so the Python
            // side raises HogQLSyntaxError.
            return Err(ParseError::syntax(
                "SELECT must list at least one expression (a reserved keyword cannot stand in for a column)",
                self.peek0.start, self.peek0.end,
            ));
        }
        self.emit
            .set_field(&mut obj, "select", self.emit.list_value(columns));

        if self.eat_kw(Kw::From)? {
            let join = self.parse_join_expr()?;
            self.emit.set_field(&mut obj, "select_from", join);
        }
        // ARRAY JOIN: `(LEFT|INNER)? ARRAY JOIN <expr_list>`.
        let array_join_op_kw = if matches!(self.peek(), TokenKind::Keyword(Kw::Left))
            && self.peek_next() == TokenKind::Keyword(Kw::Array)
        {
            self.bump()?;
            Some("LEFT")
        } else if matches!(self.peek(), TokenKind::Keyword(Kw::Inner))
            && self.peek_next() == TokenKind::Keyword(Kw::Array)
        {
            self.bump()?;
            Some("INNER")
        } else {
            None
        };
        if matches!(self.peek(), TokenKind::Keyword(Kw::Array))
            && self.peek_next() == TokenKind::Keyword(Kw::Join)
        {
            // Two semantic errors the C++ visitor raises on ARRAY JOIN:
            //   - No FROM: "Using ARRAY JOIN without a FROM clause is not permitted"
            //   - Unaliased array expr: "ARRAY JOIN arrays must have an alias"
            // Both are SelectStmt-VISITOR checks, not grammar checks —
            // `suppress_array_join_checks` skips them when this SELECT
            // is a subquery inside a discarded `FILTER (WHERE …)` body
            // (see `parse_optional_filter`).
            if !self.suppress_array_join_checks && !self.emit.has_field(&obj, "select_from") {
                return Err(ParseError::syntax(
                    "Using ARRAY JOIN without a FROM clause is not permitted",
                    0,
                    self.src.len(),
                ));
            }
            self.bump()?;
            self.bump()?;
            let op = match array_join_op_kw {
                Some("LEFT") => "LEFT ARRAY JOIN",
                Some("INNER") => "INNER ARRAY JOIN",
                _ => "ARRAY JOIN",
            };
            self.emit
                .set_field(&mut obj, "array_join_op", self.emit.string(op));
            // Inline expr-list parsing so we can capture each item's span
            // for the alias-required error.
            let mut exprs: Vec<E::Value> = Vec::new();
            loop {
                let item_start = self.peek0.start;
                let expr = self.parse_expr_bp(0)?;
                // Use the token *just consumed* as the item's end. After
                // parse_expr_bp the cursor sits on the next token; the
                // previous token's end is the most accurate item-end.
                let item_end = self.last_consumed_end;
                // Implicit alias: `[…] alias` without AS.
                let aliased = if let Some(name) = self.try_consume_implicit_alias()? {
                    self.emit.alias(expr, &name)
                } else {
                    expr
                };
                if !self.suppress_array_join_checks
                    && self.emit.node_kind(&aliased).as_deref() != Some("Alias")
                {
                    return Err(ParseError::syntax(
                        "ARRAY JOIN arrays must have an alias",
                        item_start,
                        item_end,
                    ));
                }
                exprs.push(aliased);
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek_is_clause_terminator()
                    || matches!(
                        self.peek(),
                        TokenKind::Eof | TokenKind::RParen | TokenKind::Semicolon
                    )
                {
                    break;
                }
            }
            self.emit
                .set_field(&mut obj, "array_join_list", self.emit.list_value(exprs));
        }
        if self.eat_kw(Kw::Prewhere)? {
            let _v = self.parse_expr_bp(0)?;
            self.emit.set_field(&mut obj, "prewhere", _v);
        }
        if self.eat_kw(Kw::Where)? {
            let _v = self.parse_expr_bp(0)?;
            self.emit.set_field(&mut obj, "where", _v);
        }
        // `selectStmt`-level `(USING? sampleClause)?` (before GROUP BY): DuckDB's `USING SAMPLE`, rejected not dropped.
        self.reject_select_level_sample()?;
        if matches!(self.peek(), TokenKind::Keyword(Kw::Group))
            && self.peek_next() == TokenKind::Keyword(Kw::By)
        {
            self.bump()?;
            self.bump()?;
            if matches!(self.peek(), TokenKind::Keyword(Kw::All))
                && self.peek_next_can_terminate_group_by_all()
            {
                // `GROUP BY ALL` — all-mode. Bare ALL or followed by a
                // clause-end token only. Anything postfix-shaped (`.x`,
                // `[1]`, `()`, `+1`, `::Int`, `,`, …) means cpp's
                // ALL(*) falls back to `columnExprList` with ALL as a
                // plain Field.
                self.bump()?;
                self.emit
                    .set_field(&mut obj, "group_by_mode", self.emit.string("all"));
            } else if matches!(self.peek(), TokenKind::Keyword(Kw::Cube | Kw::Rollup))
                && self.peek_next() == TokenKind::LParen
                && !self.peek_lparen_is_empty()
                && !self.cube_rollup_followed_by_more_keys()
            {
                let kw = if matches!(self.peek(), TokenKind::Keyword(Kw::Cube)) {
                    "cube"
                } else {
                    "rollup"
                };
                self.bump()?;
                self.expect(TokenKind::LParen, "(")?;
                let exprs = self.parse_expr_list_until_paren()?;
                self.expect(TokenKind::RParen, ")")?;
                self.emit
                    .set_field(&mut obj, "group_by", self.emit.list_value(exprs));
                self.emit
                    .set_field(&mut obj, "group_by_mode", self.emit.string(kw));
            } else if matches!(self.peek(), TokenKind::Keyword(Kw::Grouping))
                && self.peek_next() == TokenKind::Keyword(Kw::Sets)
            {
                self.bump()?;
                self.bump()?;
                self.expect(TokenKind::LParen, "(")?;
                // grouping sets: list of `GroupingSet` nodes — cpp's
                // visitor wraps each paren'd column list in a node so
                // the Python AST can hold them in `group_by: list[Expr]`.
                // The cpp ctx for `groupingSet` is `LPAREN columnExprList? RPAREN`
                // so the position spans the parens themselves.
                let mut sets: Vec<E::Value> = Vec::new();
                loop {
                    let set_start = self.peek0.start;
                    self.expect(TokenKind::LParen, "(")?;
                    let exprs = if self.peek() == TokenKind::RParen {
                        self.bump()?;
                        Vec::new()
                    } else {
                        let exprs = self.parse_expr_list_until_paren()?;
                        self.expect(TokenKind::RParen, ")")?;
                        exprs
                    };
                    sets.push(self.wrap_pos(self.emit.grouping_set(exprs), set_start));
                    if !self.eat(TokenKind::Comma)? {
                        break;
                    }
                }
                self.expect(TokenKind::RParen, ")")?;
                self.emit
                    .set_field(&mut obj, "group_by", self.emit.list_value(sets));
                self.emit
                    .set_field(&mut obj, "group_by_mode", self.emit.string("grouping_sets"));
            } else {
                let exprs = self.parse_expr_list_until_terminators()?;
                self.emit
                    .set_field(&mut obj, "group_by", self.emit.list_value(exprs));
            }
        }
        // `WITH (CUBE | ROLLUP | TOTALS)` after the GROUP BY position —
        // the grammar admits them as independent optionals. The cpp
        // visitor parses but doesn't persist any AST bit here (mode is
        // only set on the GROUP-BY-led form like `GROUP BY CUBE(...)`).
        // We silently consume to match. cpp grammar:
        //   `… (WITH (CUBE | ROLLUP))? (WITH TOTALS)?`
        // — at most one of CUBE / ROLLUP, then optionally TOTALS, in
        // that order. Track which slots we've filled so a second
        // `WITH CUBE` / `WITH ROLLUP` / `WITH TOTALS` errors out.
        let mut saw_cube_or_rollup = false;
        let mut saw_totals = false;
        loop {
            if !matches!(self.peek(), TokenKind::Keyword(Kw::With)) {
                break;
            }
            match self.peek_next() {
                TokenKind::Keyword(Kw::Cube) | TokenKind::Keyword(Kw::Rollup) => {
                    if saw_cube_or_rollup || saw_totals {
                        return Err(self.err(
                            "GROUP BY admits at most one of WITH CUBE / WITH ROLLUP, before WITH TOTALS",
                        ));
                    }
                    saw_cube_or_rollup = true;
                    self.bump()?;
                    self.bump()?;
                }
                TokenKind::Keyword(Kw::Totals) => {
                    if saw_totals {
                        return Err(self.err("duplicate WITH TOTALS"));
                    }
                    saw_totals = true;
                    self.bump()?;
                    self.bump()?;
                }
                _ => break,
            }
        }
        if self.eat_kw(Kw::Having)? {
            let _v = self.parse_expr_bp(0)?;
            self.emit.set_field(&mut obj, "having", _v);
        }
        if self.eat_kw(Kw::Qualify)? {
            let _v = self.parse_expr_bp(0)?;
            self.emit.set_field(&mut obj, "qualify", _v);
        }
        // Second `selectStmt`-level `(USING sampleClause)?` slot (after QUALIFY): same DuckDB `USING SAMPLE`, rejected not dropped.
        self.reject_select_level_sample()?;
        // WINDOW clause — minimal: WINDOW name AS (...) [, ...].
        if self.eat_kw(Kw::Window)? {
            let mut windows: std::collections::BTreeMap<String, E::Value> =
                std::collections::BTreeMap::new();
            loop {
                let name_tok = self.bump()?;
                let name = match name_tok.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(name_tok), name_tok.kind)
                    }
                    // A WINDOW-clause name is an `identifier`, so only `kw_valid_as_identifier` keywords qualify — the Hog-statement keywords (try / catch / finally / …) do not.
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        identifier_text(self.text(name_tok), name_tok.kind)
                    }
                    _ => {
                        return Err(
                            self.err(format!("expected window name, got {:?}", name_tok.kind))
                        )
                    }
                };
                self.expect_kw(Kw::As, "AS")?;
                self.expect(TokenKind::LParen, "(")?;
                let we = self.parse_window_expr()?;
                self.expect(TokenKind::RParen, ")")?;
                windows.insert(name, we);
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
            }
            let windows_pairs: Vec<(String, E::Value)> = windows.into_iter().collect();
            self.emit.set_field(
                &mut obj,
                "window_exprs",
                self.emit.string_keyed_map(windows_pairs),
            );
        }
        if matches!(self.peek(), TokenKind::Keyword(Kw::Order))
            && self.peek_next() == TokenKind::Keyword(Kw::By)
        {
            self.bump()?;
            self.bump()?;
            let ob = self.parse_order_expr_list()?;
            self.emit
                .set_field(&mut obj, "order_by", self.emit.list_value(ob));
            // Optional `INTERPOLATE [(expr [AS expr], …)]` after ORDER BY.
            if self.eat_kw(Kw::Interpolate)? {
                let items = if self.eat(TokenKind::LParen)? {
                    let mut items: Vec<E::Value> = Vec::new();
                    // `interpolateClause: INTERPOLATE (LPAREN interpolateExpr
                    // (COMMA interpolateExpr)* RPAREN)?` — when parens are
                    // present, at least one interpolateExpr is required.
                    if self.peek() == TokenKind::RParen {
                        return Err(self.err("INTERPOLATE (...) must have at least one item"));
                    }
                    loop {
                        // Parse expr greedily so AS-alias gets
                        // absorbed when its right operand is a
                        // valid alias target — matches cpp's
                        // ALL(*) which prefers the inner
                        // columnExpr's AS-alias over the outer
                        // `(AS columnExpr)?` separator.
                        // `interpolate(a AS 5)` keeps AS for the
                        // outer because `5` isn't an alias target.
                        let interp_start = self.peek0.start;
                        let expr = self.parse_expr_bp(0)?;
                        let value = if self.eat_kw(Kw::As)? {
                            Some(self.parse_expr_bp(0)?)
                        } else {
                            None
                        };
                        // cpp spans the InterpolateExpr from the expr start to the
                        // value end (or the expr end when there is no `AS value`).
                        let interp_end = self.last_consumed_end;
                        let interp = self.emit.interpolate_expr(expr, value);
                        items.push(self.wrap_pos_to(interp, interp_start, interp_end));
                        if !self.eat(TokenKind::Comma)? {
                            break;
                        }
                        // `interpolateClause: INTERPOLATE LPAREN
                        // interpolateExpr (COMMA interpolateExpr)*
                        // RPAREN` — no trailing comma. cpp rejects
                        // `INTERPOLATE (y,)`.
                        if self.peek() == TokenKind::RParen {
                            return Err(self.err("trailing comma in INTERPOLATE clause"));
                        }
                    }
                    self.expect(TokenKind::RParen, ")")?;
                    items
                } else {
                    Vec::new()
                };
                self.emit
                    .set_field(&mut obj, "interpolate", self.emit.list_value(items));
            }
        }
        // LIMIT / LIMIT BY / OFFSET handling. The grammar allows both
        // limitByClause and limitAndOffsetClause; when both are present,
        // limitBy comes first. We deferred the choice of "which form" until
        // the prefix is fully parsed — see parse_limit_clauses for the
        // disambiguation strategy (no bounded probe).
        self.parse_limit_clauses(&mut obj)?;
        // SETTINGS — accepted by the grammar, rejected by the cpp
        // visitor as unsupported. Raise the same `NotImplementedError`
        // class rather than letting the stray `SETTINGS` token fall
        // through to a generic trailing-token `SyntaxError`.
        if matches!(self.peek(), TokenKind::Keyword(Kw::Settings)) {
            return Err(ParseError::not_implemented(
                "Unsupported: SelectStmt.settingsClause()",
                self.peek0.start,
                self.src.len(),
            ));
        }

        Ok(self.wrap_pos(obj, stmt_start))
    }

    /// Probe: at the GROUP BY position, peek is `ALL`. The peek_next
    /// token decides whether `ALL` is the all-mode marker (cpp's
    /// `groupByClause: GROUP BY ALL` alt) or the head of a
    /// `columnExprList` whose first element is the keyword-as-Field
    /// `ALL` (`GROUP BY ALL, b`, `GROUP BY ALL.x`, `GROUP BY ALL()`,
    /// `GROUP BY ALL::Int`, etc.). Return true if peek_next is a
    /// terminator that closes the GROUP BY (i.e. all-mode wins).
    fn peek_next_can_terminate_group_by_all(&self) -> bool {
        matches!(
            self.peek_next(),
            TokenKind::Eof
                | TokenKind::Semicolon
                | TokenKind::RParen
                | TokenKind::Keyword(Kw::With)
                | TokenKind::Keyword(Kw::Having)
                | TokenKind::Keyword(Kw::Qualify)
                | TokenKind::Keyword(Kw::Window)
                | TokenKind::Keyword(Kw::Order)
                | TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Settings)
                | TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
        )
    }

    /// Probe: at the GROUP BY position, peek is `CUBE` or `ROLLUP` and
    /// peek_next is `(`. Look past the matching close `)` to see if a
    /// `,` follows — that signals the caller's specialised
    /// `CUBE(...)` / `ROLLUP(...)` mode is wrong and cpp's ANTLR ALL(*)
    /// would fall back to the `columnExprList` alternative with the
    /// CUBE/ROLLUP as an ordinary function call.
    fn cube_rollup_followed_by_more_keys(&self) -> bool {
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
        // After the matching close, is the next token a list separator?
        matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::Comma))
    }

    /// Parse a `LIMIT` clause's first operand — a `columnExpr`
    /// optionally followed by the `%` PERCENT marker — and return
    /// `(body, percent)`. Callers raise `limit_body_depth` around this
    /// so the Pratt `%` handler can resolve modulo vs the PERCENT
    /// marker at any depth.
    fn parse_limit_body(&mut self) -> Result<(E::Value, bool), ParseError> {
        // BP_MULT+1 stops the initial parse before a top-level `%` so
        // `limit_resolve_percent` sees it undigested; a compound body
        // (additive / comparison / AND / OR) is then extended at BP=0.
        let body_start = self.peek0.start;
        let first_raw = self.parse_expr_bp(BP_MULT + 1)?;
        let (mut first, mut percent) = self.limit_resolve_percent(first_raw, body_start)?;
        if !percent {
            // Use the body's start (snapshotted before parse_expr_bp) for
            // the continuation's wrap so the resulting infix span starts
            // at the first operand, not at the operator that pratt_continue
            // reads from peek0. cpp's limitExpr ctx covers the whole body
            // from the first token.
            first = self.pratt_continue_with_lhs(first, 0, body_start)?;
            // The continuation's `%` handler leaves a `LIMIT … PERCENT`
            // marker unconsumed (it isn't modulo); pick it up here.
            if self.peek() == TokenKind::Percent {
                self.bump()?;
                percent = true;
            }
        }
        Ok((first, percent))
    }

    /// Parse the optional `limitByClause? (limitAndOffsetClause | offsetOnlyClause)?`
    /// trailer of a SELECT, without using bounded token lookahead.
    ///
    /// The two forms share a prefix (`LIMIT <expr> [, <expr> | OFFSET <expr>]`),
    /// and only the trailing token disambiguates: `BY` means limit-by,
    /// anything else means regular limit-and-offset. `%` (PERCENT) and
    /// `WITH TIES` rule out limit-by mid-parse — they are only valid in the
    /// limit-and-offset form.
    fn parse_limit_clauses(&mut self, obj: &mut E::Value) -> Result<(), ParseError> {
        // Capture the LIMIT keyword's start so the eventual LimitByExpr
        // (cpp's `limitByClause` ctx, `LIMIT limitExpr BY columnExprList`)
        // gets a span starting at LIMIT, not at the first BY-expr.
        let limit_start = self.peek0.start;
        if !self.eat_kw(Kw::Limit)? {
            // No LIMIT — accept a standalone OFFSET clause (offsetOnlyClause).
            if self.eat_kw(Kw::Offset)? {
                let _v = self.parse_expr_bp(0)?;
                self.emit.set_field(obj, "offset", _v);
            }
            return Ok(());
        }

        // Common prefix: LIMIT <expr>. BP_MULT+1 prevents the trailing `%`
        // from being consumed as a modulo on the limit expression itself;
        // limit_resolve_percent then disambiguates `%` between PERCENT and
        // modulo (the latter when the modulo path is the only one that
        // succeeds end-to-end). When `%` resolves to PERCENT marker the
        // body is done; otherwise continue Pratt at BP=0 to consume any
        // lower-precedence operators (additive, comparison, AND, OR).
        // `limit_body_depth` stays raised across the whole body parse
        // so the Pratt `%` handler (and `limit_resolve_percent`'s own
        // speculation) resolve modulo vs the PERCENT marker uniformly,
        // at any depth — `LIMIT a%b % WITH TIES` keeps `a%b` as modulo
        // and the second `%` as the marker.
        self.limit_body_depth += 1;
        let body = self.parse_limit_body();
        self.limit_body_depth -= 1;
        let (first, percent) = body?;
        let mut with_ties = false;
        if self.peek_kw2(Kw::With, Kw::Ties) {
            self.bump()?;
            self.bump()?;
            with_ties = true;
        }

        // Parse the optional second operand: `, b` (compact) or `OFFSET b`
        // (verbose). The compact form's role flips between limit-by and
        // limit-and-offset; we capture which separator was used and decide
        // later. Both operands parse at full bp (no `%` ambiguity here —
        // PERCENT only attaches to the first LIMIT operand).
        enum Tail<V> {
            None,
            Comma(V),
            Offset(V),
        }
        let tail = if self.eat(TokenKind::Comma)? {
            Tail::Comma(self.parse_expr_bp(0)?)
        } else if matches!(self.peek(), TokenKind::Keyword(Kw::Offset)) {
            // cpp's grammar allows OFFSET at the body level in two places:
            //   - `limitByClause: LIMIT limitExpr BY ...` where
            //     `limitExpr: columnExpr ((COMMA | OFFSET) columnExpr)?`
            //     — i.e. `LIMIT a OFFSET b BY c` is limit-by with offset_value=b.
            //   - `limitAndOffsetClause` verbose alt: `LIMIT n PERCENT?
            //     (WITH TIES)? OFFSET m`.
            // For the verbose limit-and-offset alt, cpp's ANTLR ALL(*)
            // prefers the COMPACT alt (`LIMIT n` only) when both can
            // match, leaving `OFFSET m` to be absorbed by selectSetStmt's
            // trailing `limitAndOffsetClauseOptional`. So consume OFFSET
            // here ONLY when BY follows — otherwise leave it for the
            // outer set-stmt trailing-decorators pass.
            let cp = self.checkpoint();
            self.bump()?; // OFFSET
            let off = self.parse_expr_bp(0)?;
            if matches!(self.peek(), TokenKind::Keyword(Kw::By)) {
                Tail::Offset(off)
            } else {
                self.restore(cp)?;
                Tail::None
            }
        } else {
            Tail::None
        };

        // Trailing `WITH TIES` after the compact comma form. The
        // verbose form (`LIMIT n WITH TIES OFFSET m`) puts WITH TIES
        // BEFORE OFFSET, so a trailing WITH TIES is only valid after
        // the compact form (Tail::Comma). `LIMIT n OFFSET m WITH TIES`
        // doesn't match either grammar alt — cpp rejects.
        if !with_ties
            && matches!(tail, Tail::None | Tail::Comma(_))
            && self.peek_kw2(Kw::With, Kw::Ties)
        {
            self.bump()?;
            self.bump()?;
            with_ties = true;
        }

        // Disambiguator: `BY` makes this a limit-by clause.
        if self.eat_kw(Kw::By)? {
            if percent || with_ties {
                return Err(self.err("PERCENT and WITH TIES are not valid in a LIMIT BY clause"));
            }
            let cols = self.parse_limit_by_exprs()?;
            let (n, offset_value) = match tail {
                Tail::None => (first, None),
                // `LIMIT a, b BY ...` → n=b, offset_value=a (compact swaps)
                Tail::Comma(s) => (s, Some(first)),
                // `LIMIT a OFFSET b BY ...` → n=a, offset_value=b
                Tail::Offset(s) => (first, Some(s)),
            };
            let lb = self.emit.limit_by_expr(n, cols, offset_value);
            self.emit
                .set_field(obj, "limit_by", self.wrap_pos(lb, limit_start));

            // After the limit-by clause, an optional outer
            // limit-and-offset (or bare OFFSET) may follow.
            self.parse_trailing_limit_and_offset(obj)?;
            return Ok(());
        }

        // Otherwise: regular limit-and-offset. The verbose `OFFSET m`
        // form (Tail::Offset) is liftable to the outer SelectSetQuery
        // when wrapped in a set-stmt; the compact `, m` form is not.
        // See `parse_select_set_stmt` for the lift logic.
        self.emit.set_field(obj, "limit", first);
        if percent {
            self.emit
                .set_field(obj, "limit_percent", self.emit.bool(true));
        }
        match tail {
            Tail::Comma(s) => {
                self.emit.set_field(obj, "offset", s);
            }
            Tail::Offset(s) => {
                self.emit.set_field(obj, "offset", s);
                self.emit
                    .set_field(obj, "__rust_offset_liftable", self.emit.bool(true));
            }
            Tail::None => {}
        }
        if with_ties {
            self.emit
                .set_field(obj, "limit_with_ties", self.emit.bool(true));
        }
        Ok(())
    }

    /// Outer limit/offset that may follow a `LIMIT BY` clause. Same
    /// grammar as `limitAndOffsetClause | offsetOnlyClause`, but `BY` is
    /// not legal here.
    fn parse_trailing_limit_and_offset(&mut self, obj: &mut E::Value) -> Result<(), ParseError> {
        if self.eat_kw(Kw::Limit)? {
            // Full `columnExpr` body — `parse_limit_body` covers the
            // compound case (`limit (x) ?? y`) and the `%`/PERCENT
            // resolution; a bare `BP_MULT+1` parse stranded any
            // lower-precedence tail.
            self.limit_body_depth += 1;
            let body = self.parse_limit_body();
            self.limit_body_depth -= 1;
            let (limit, percent) = body?;
            self.emit.set_field(obj, "limit", limit);
            if percent {
                self.emit
                    .set_field(obj, "limit_percent", self.emit.bool(true));
            }
            // Grammar (line 107–110): limitAndOffsetClause has two
            // alternatives that differ in where WITH TIES sits relative
            // to the second value:
            //
            //   compact: LIMIT n PERCENT? (COMMA n)? (WITH TIES)?
            //   verbose: LIMIT n PERCENT? (WITH TIES)? OFFSET n
            //
            // After consuming `LIMIT n PERCENT?`, the next token
            // disambiguates: COMMA → compact, WITH/OFFSET → verbose.
            // The compact form puts WITH TIES *after* the comma's
            // second operand; verbose puts WITH TIES *before* OFFSET.
            // The previous flat eat-comma-or-offset-then-check-WITH-TIES
            // missed `LIMIT n % WITH TIES OFFSET m` because the WITH
            // TIES check happened only after the (skipped) comma /
            // OFFSET branch.
            if self.eat(TokenKind::Comma)? {
                // Compact form.
                let _v = self.parse_expr_bp(0)?;
                self.emit.set_field(obj, "offset", _v);
                if self.peek_kw2(Kw::With, Kw::Ties) {
                    self.bump()?;
                    self.bump()?;
                    self.emit
                        .set_field(obj, "limit_with_ties", self.emit.bool(true));
                }
            } else {
                // After LIMIT BY's trailing LIMIT n, ANTLR ALL(*) picks
                // `limitAndOffsetClause`'s compact alt — `LIMIT n PERCENT?
                // (COMMA m)? (WITH TIES)?` — over verbose (which would
                // consume OFFSET) because compact is listed first in the
                // grammar. So we stop here even if `OFFSET m` follows; the
                // outer `selectSetStmt`'s `limitAndOffsetClauseOptional`
                // picks it up, and `merge_select_decorators` attaches it
                // to the inner SelectQuery — keeping the inner's position
                // span stopping before OFFSET, matching cpp's selectStmt
                // ctx. Verbose-form `__rust_offset_liftable` is never set
                // here: limit-by's trailing OFFSET stays on the inner.
                if self.peek_kw2(Kw::With, Kw::Ties) {
                    self.bump()?;
                    self.bump()?;
                    self.emit
                        .set_field(obj, "limit_with_ties", self.emit.bool(true));
                }
            }
        } else if self.eat_kw(Kw::Offset)? {
            // Bare `OFFSET m` (no preceding LIMIT). cpp keeps this on
            // the inner SELECT — don't mark liftable.
            let _v = self.parse_expr_bp(0)?;
            self.emit.set_field(obj, "offset", _v);
        }
        Ok(())
    }

    /// Peek two consecutive keyword tokens without consuming.
    fn peek_kw2(&self, a: Kw, b: Kw) -> bool {
        matches!(self.peek(), TokenKind::Keyword(kw) if kw == a)
            && self.peek_next() == TokenKind::Keyword(b)
    }

    /// After parsing a LIMIT expression, decide whether a following `%` is
    /// the PERCENT marker or modulo, and return the (possibly extended)
    /// expression along with whether PERCENT was consumed.
    ///
    /// Mirrors ANTLR ALL(*) on `LIMIT columnExpr PERCENT?`: cpp picks
    /// modulo whenever the modulo path can succeed end-to-end (the
    /// whole `columnExpr` parses and the rest forms a valid limit
    /// continuation), otherwise `%` is the PERCENT marker.
    fn limit_resolve_percent(
        &mut self,
        expr: E::Value,
        expr_start: usize,
    ) -> Result<(E::Value, bool), ParseError> {
        if self.peek0.kind != TokenKind::Percent {
            return Ok((expr, false));
        }
        match self.try_limit_modulo_extension(expr.clone(), expr_start)? {
            Some(extended) => Ok((extended, false)),
            None => {
                self.bump()?; // % (PERCENT marker)
                Ok((expr, true))
            }
        }
    }

    /// Caller has confirmed peek is `%`. Speculatively parse it as the
    /// modulo operator: `% rhs` (RHS bounded at BP_MULT+1 so the inner
    /// Pratt doesn't re-engage `%`) followed by the rest of the
    /// `columnExpr` at BP=0. Returns `Some(extended)` — cursor advanced
    /// past the whole modulo expression — when it lands at a clean
    /// LIMIT-body boundary;
    /// cpp's ANTLR ALL(*) takes the modulo alt only then. Returns
    /// `None` with the cursor restored to the `%` otherwise: there the
    /// `%` is the `LIMIT … PERCENT` marker, not modulo.
    ///
    /// `%` is genuinely ambiguous — `ColumnExprPrecedence1` modulo and
    /// the `LIMIT columnExpr PERCENT?` marker — and which one applies
    /// depends on whether the modulo RHS exists and the whole thing
    /// lands cleanly, so a token-level heuristic is not enough. The
    /// Pratt `%` handler calls this for every `%` it meets inside a
    /// LIMIT body (`limit_body_depth > 0`).
    pub(crate) fn try_limit_modulo_extension(
        &mut self,
        lhs: E::Value,
        lhs_start: usize,
    ) -> Result<Option<E::Value>, ParseError> {
        let cp = self.checkpoint();
        let trial = (|p: &mut Self| -> Result<Option<E::Value>, ParseError> {
            p.bump()?; // %
            let rhs = p.parse_expr_bp(BP_MULT + 1)?;
            // Stamp the modulo node's span before folding any lower-precedence tail, mirroring the Pratt loop's wrap-the-lhs step. Without this the inner `a % b` stays position-less when an outer op (`% 2 + 3` → the `+` node) wraps it (cpp positions the modulo sub-node).
            let combined = p.wrap_pos(p.emit.arith(lhs.clone(), "%", rhs), lhs_start);
            // Extend the whole columnExpr (BP=0) — cpp parses the
            // LIMIT body greedily, so a lower-precedence tail
            // (`% 2 + 3`, `% 2 AND 3`) stays part of the modulo body.
            // `lhs_start` is the original LHS's start, not the `%` —
            // cpp's `columnExprPrecedence2` ctx covers the whole modulo
            // expression from the LHS's first token.
            let extended = p.pratt_continue_with_lhs(combined, 0, lhs_start)?;
            if p.peek_is_limit_body_done() {
                return Ok(Some(extended));
            }
            // Second-level speculation: when the modulo extension
            // lands on `BY`, try parsing the BY-exprs clause. cpp's
            // `LIMIT {} % order by 2` parses as LIMIT BY where
            // n=Mod(Dict, Field(order)) and exprs=[2]. Without this
            // check the modulo extension rolls back to PERCENT and
            // the trailing `order by 2` ends up consumed-and-dropped
            // by the outer set-stmt's trailing decorators — losing
            // the cpp interpretation. The BY-exprs check rolls back
            // to just AFTER the modulo so the outer
            // `parse_limit_clauses` BY handler picks up cleanly.
            if p.peek() == TokenKind::Keyword(Kw::By) {
                let after_modulo = p.checkpoint();
                let by_trial = (|p: &mut Self| -> Result<bool, ParseError> {
                    p.bump()?; // BY
                    p.parse_limit_by_exprs()?;
                    // Post-BY-exprs state must be a valid LIMIT-BY
                    // tail per the grammar: optional outer
                    // limit/offset trailer, SETTINGS, or end-of-stmt
                    // (incl. set operators). Notably excludes WITH
                    // (cpp's `WITH FILL TO …` order-by suffix is
                    // invalid here) and ORDER (we're past ORDER BY
                    // position in selectStmt).
                    Ok(matches!(
                        p.peek(),
                        TokenKind::Eof
                            | TokenKind::RParen
                            | TokenKind::RBracket
                            | TokenKind::RBrace
                            | TokenKind::Comma
                            | TokenKind::Semicolon
                            | TokenKind::Keyword(Kw::Limit)
                            | TokenKind::Keyword(Kw::Offset)
                            | TokenKind::Keyword(Kw::Settings)
                            | TokenKind::Keyword(Kw::Union)
                            | TokenKind::Keyword(Kw::Intersect)
                            | TokenKind::Keyword(Kw::Except)
                    ))
                })(p);
                p.restore(after_modulo)?;
                if let Ok(true) = by_trial {
                    return Ok(Some(extended));
                }
            }
            Ok(None)
        })(self);
        match trial {
            Ok(Some(v)) => Ok(Some(v)),
            _ => {
                self.restore(cp)?;
                Ok(None)
            }
        }
    }

    /// True when peek is a valid LIMIT-clause boundary token: a
    /// structural terminator (paren/bracket/brace/comma/semicolon/eof),
    /// the LIMIT clause's own trailing modifiers (`WITH TIES`,
    /// `OFFSET`), or the start of a sibling clause / set operator.
    /// Used by `limit_resolve_percent` to decide whether a speculative
    /// modulo extension lands cleanly.
    fn peek_is_limit_body_done(&self) -> bool {
        matches!(
            self.peek(),
            TokenKind::Eof
                | TokenKind::RParen
                | TokenKind::RBracket
                | TokenKind::RBrace
                | TokenKind::Comma
                | TokenKind::Semicolon
                // A `%` directly after a modulo extension is the
                // `LIMIT … PERCENT` marker — the extension ends here.
                | TokenKind::Percent
                | TokenKind::Keyword(Kw::With)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Settings)
                | TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                // `ORDER BY` can appear AFTER the LIMIT body at the
                // selectSetStmt level (cpp's grammar admits the slot
                // there; cpp drops the parsed AST but still consumes
                // the tokens cleanly). Treat ORDER as a clean
                // LIMIT-body boundary so the modulo speculation
                // commits when the extended chain is followed by a
                // top-level ORDER BY clause. Bare `BY` (without
                // ORDER preceding) is NOT in the list — that would
                // imply a malformed `... LIMIT % BY ...` shape that
                // cpp's recovery handles but ours can't.
                | TokenKind::Keyword(Kw::Order)
        )
    }

    /// True when peek is a valid boundary AFTER a LIMIT-BY-exprs
    /// item: another item (Comma), end-of-statement structural,
    /// the outer LIMIT-and-offset trailer (Limit/Offset), ORDER BY
    /// at selectSetStmt level, set operators, or SETTINGS. cpp's
    /// adaptive prediction bails out of the iteration when the
    /// post-parse state doesn't fit one of these — most notably for
    /// `WITH TIES` which is part of the outer LIMIT-body, NOT a
    /// LIMIT-BY-exprs continuation.
    fn peek_is_limit_by_exprs_boundary(&self) -> bool {
        matches!(
            self.peek(),
            TokenKind::Eof
                | TokenKind::RParen
                | TokenKind::RBracket
                | TokenKind::RBrace
                | TokenKind::Comma
                | TokenKind::Semicolon
                | TokenKind::Keyword(Kw::Limit)
                | TokenKind::Keyword(Kw::Offset)
                | TokenKind::Keyword(Kw::Settings)
                | TokenKind::Keyword(Kw::Union)
                | TokenKind::Keyword(Kw::Intersect)
                | TokenKind::Keyword(Kw::Except)
                | TokenKind::Keyword(Kw::Order)
        )
    }

    /// Reject `selectStmt`-level `[USING] SAMPLE`: DuckDB's `USING SAMPLE`, which HogQL has no AST home for (only table-level `JoinExprTable` lands on `JoinExpr.sample`), so reject rather than silently drop. Matches the python + cpp visitors' `NotImplementedError`.
    fn reject_select_level_sample(&mut self) -> Result<(), ParseError> {
        let saw_sample = self.peek_kw2(Kw::Using, Kw::Sample)
            || matches!(self.peek(), TokenKind::Keyword(Kw::Sample));
        if !saw_sample {
            return Ok(());
        }
        Err(ParseError::not_implemented(
            "Unsupported: SelectStmt.sampleClause()",
            self.peek0.start,
            self.peek0.end,
        ))
    }

    /// LIMIT BY columnExprList: comma-separated columnExprs. Two
    /// disambiguations cpp's ALL(*) handles by looking past the
    /// comma:
    ///
    ///   `LIMIT a BY b, offset * c`
    ///     → second item is `offset_field * c` — OFFSET is a Field,
    ///       the list continues, no offsetOnlyClause.
    ///   `LIMIT X, Y BY Z, offset W`
    ///     → list ends after `Z`; `OFFSET W` is the separate
    ///       offsetOnlyClause that lands on `SelectQuery.offset`.
    ///
    /// cpp's choice across `<comma> offset <X>`: parse `offset <X>` as
    /// a continuing columnExpr when feasible, otherwise end the list
    /// and start the OFFSET clause. The disambiguator is whether `<X>`
    /// can extend `offset` as a Field — postfix chaining (`.`, `[`,
    /// `(`), infix operators (`*`, `/`, `=`, …), or infix keywords
    /// (`AND`, `IS`, `BETWEEN`, `LIKE`, `AS`, …) all keep `offset` as
    /// a Field. Standalone primary-starters (Ident, Number, String,
    /// `{…}`, primary keywords) terminate.
    ///
    /// `peek_is_clause_terminator` is tuned for column-list context
    /// and treats `OFFSET <primary>` as a clause introducer — that
    /// matches when `<primary>` doesn't extend `offset`. Its
    /// `asterisk_after_offset_continues_arith` probe is too narrow
    /// here though: for `LIMIT … BY b, offset * columns(…)` cpp
    /// continues the list, but the probe returns false (treating
    /// COLUMNS-with-paren as the body of `OFFSET *`). Override OFFSET
    /// specifically with a more permissive infix-or-postfix check.
    fn parse_limit_by_exprs(&mut self) -> Result<Vec<E::Value>, ParseError> {
        let mut out = Vec::new();
        out.push(self.parse_expr_bp(0)?);
        while self.eat(TokenKind::Comma)? {
            if matches!(
                self.peek(),
                TokenKind::Eof | TokenKind::RParen | TokenKind::Semicolon
            ) {
                break;
            }
            if self.peek() == TokenKind::Keyword(Kw::Offset) {
                if !offset_next_terminates_limit_by(self.peek_next()) {
                    // OFFSET extends as a Field — continue the list.
                    out.push(self.parse_expr_bp(0)?);
                    continue;
                }
                // OFFSET starts a new clause — end the list so the
                // outer parser picks up `OFFSET <body>`.
                break;
            }
            if self.peek_is_clause_terminator() {
                // Same speculative-parse trick as
                // `parse_expr_list_until_terminators`: cpp's columnExpr
                // greedily extends through keyword-as-Field forms (`,
                // limit * columns('ok')` → `Mul(Field('limit'),
                // ColumnsExpr)` as another LIMIT-BY item). Commit only
                // when the result engaged structure beyond a bare
                // single-chain Field AND the post-parse cursor lands
                // at a clean LIMIT-BY-exprs boundary. Otherwise back
                // off the comma and let the outer dispatcher pick up
                // the keyword as a clause introducer. The post-parse
                // boundary check rejects shapes like `, limit (1)
                // WITH TIES` — cpp's adaptive prediction sees the
                // trailing `WITH TIES` doesn't fit the BY-exprs
                // grammar and bails out of the iteration, letting
                // `LIMIT (1) WITH TIES` parse as the outer LIMIT
                // clause instead.
                let cp = self.checkpoint();
                let speculated = match self.parse_expr_bp(0) {
                    Ok(expr) if is_bare_field(&self.emit, &expr) => {
                        self.restore(cp)?;
                        None
                    }
                    Ok(_expr) if !self.peek_is_limit_by_exprs_boundary() => {
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

    /// PARTITION BY exprs inside a windowExpr: a comma-separated
    /// columnExprList that terminates when the next sibling clause
    /// (ORDER BY, ROWS-frame, RANGE-frame) or the closing paren
    /// appears. Without this RANGE/ROWS would be consumed as Field
    /// identifiers (per the keyword rule) and BETWEEN that follows
    /// them would over-greedily eat the window frame body.
    fn parse_window_partition_by_exprs(&mut self) -> Result<Vec<E::Value>, ParseError> {
        let mut out = Vec::new();
        loop {
            out.push(self.parse_expr_bp(0)?);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            // Window-specific terminators in addition to the standard set.
            if matches!(
                self.peek(),
                TokenKind::Eof
                    | TokenKind::RParen
                    | TokenKind::Semicolon
                    | TokenKind::Keyword(Kw::Range)
                    | TokenKind::Keyword(Kw::Rows)
                    | TokenKind::Keyword(Kw::Order)
            ) || self.peek_is_clause_terminator()
            {
                break;
            }
        }
        Ok(out)
    }

    pub(crate) fn parse_window_expr(&mut self) -> Result<E::Value, ParseError> {
        let we_start = self.peek0.start;
        let mut obj = self.emit.window_expr_empty();
        if matches!(self.peek(), TokenKind::Keyword(Kw::Partition))
            && self.peek_next() == TokenKind::Keyword(Kw::By)
        {
            self.bump()?;
            self.bump()?;
            // Window-context partition_by exprs terminate on the
            // following frame/order keywords (RANGE / ROWS / ORDER) or
            // the closing paren of the windowExpr.
            let exprs = self.parse_window_partition_by_exprs()?;
            self.emit
                .set_field(&mut obj, "partition_by", self.emit.list_value(exprs));
        }
        if matches!(self.peek(), TokenKind::Keyword(Kw::Order))
            && self.peek_next() == TokenKind::Keyword(Kw::By)
        {
            self.bump()?;
            self.bump()?;
            let ob = self.parse_order_expr_list()?;
            self.emit
                .set_field(&mut obj, "order_by", self.emit.list_value(ob));
        }
        // Frame clause: ROWS|RANGE bound [BETWEEN bound AND bound].
        let frame_method = if self.eat_kw(Kw::Rows)? {
            Some("ROWS")
        } else if self.eat_kw(Kw::Range)? {
            Some("RANGE")
        } else {
            None
        };
        if let Some(m) = frame_method {
            self.emit
                .set_field(&mut obj, "frame_method", self.emit.string(m));
            // `BETWEEN` after ROWS / RANGE is ambiguous: the
            // `frameBetween` alt (`BETWEEN bound AND bound`) or a
            // `frameStart` bound whose `columnExpr` is the `between`
            // keyword used as a Field (`RANGE BETWEEN PRECEDING` is
            // the frame expr `Field(between)` PRECEDING). cpp's ALL(*)
            // takes `frameBetween` only when it parses end-to-end;
            // speculate, and on failure rewind so the `between` is
            // re-read as the Field of a `frameStart` bound.
            let cp = self.checkpoint();
            let between_frame = if self.eat_kw(Kw::Between)? {
                (|p: &mut Self| -> Result<(E::Value, E::Value), ParseError> {
                    let start = p.parse_window_frame_bound()?;
                    p.expect_kw(Kw::And, "AND")?;
                    let end = p.parse_window_frame_bound()?;
                    Ok((start, end))
                })(self)
                .ok()
            } else {
                None
            };
            if let Some((start, end)) = between_frame {
                self.emit.set_field(&mut obj, "frame_start", start);
                self.emit.set_field(&mut obj, "frame_end", end);
            } else {
                self.restore(cp)?;
                let start = self.parse_window_frame_bound()?;
                self.emit.set_field(&mut obj, "frame_start", start);
            }
        }
        // cpp's `VISIT(WindowExpr)` calls `addPositionInfo(json, ctx)`,
        // so the JSON has `start` / `end` spanning the window-expr body
        // (between the parens — `OVER ( PARTITION BY ... ROWS ... )`).
        Ok(self.wrap_pos(obj, we_start))
    }

    fn parse_window_frame_bound(&mut self) -> Result<E::Value, ParseError> {
        let bound_start = self.peek0.start;
        if self.eat_kw(Kw::Current)? {
            self.expect_kw(Kw::Row, "ROW")?;
            let null_val = self.emit.null();
            return Ok(self.wrap_pos(
                self.emit.window_frame_bound("CURRENT ROW", null_val),
                bound_start,
            ));
        }
        if self.eat_kw(Kw::Unbounded)? {
            let ty = if self.eat_kw(Kw::Preceding)? {
                "PRECEDING"
            } else if self.eat_kw(Kw::Following)? {
                "FOLLOWING"
            } else {
                return Err(self.err("expected PRECEDING or FOLLOWING after UNBOUNDED"));
            };
            let null_val = self.emit.null();
            return Ok(self.wrap_pos(self.emit.window_frame_bound(ty, null_val), bound_start));
        }
        // `winFrameBound: columnExpr PRECEDING | columnExpr FOLLOWING`
        // — the value is a full `columnExpr`, so parse it at binding
        // power 0. `PRECEDING` / `FOLLOWING` are keywords (never infix
        // operators), so they always terminate the value parse; the
        // `AND` separating two bounds of a `BETWEEN` frame sits after
        // that keyword and is never swallowed.
        let val = self.parse_expr_bp(0)?;
        let ty = if self.eat_kw(Kw::Preceding)? {
            "PRECEDING"
        } else if self.eat_kw(Kw::Following)? {
            "FOLLOWING"
        } else {
            return Err(self.err("expected PRECEDING or FOLLOWING after frame bound expression"));
        };
        // cpp's `VISIT(WinFrameBound)` unwraps a frame-bound `Constant`
        // to a bare number only when the value `isInt()`; a float or
        // string Constant keeps its full object form. Mirror that —
        // unwrap only an integer-valued Constant.
        let frame_value = if self.emit.node_kind(&val).as_deref() == Some("Constant") {
            match self.emit.get_field(&val, "value") {
                Some(v) if self.emit.as_i64(&v).is_some() => v,
                _ => val,
            }
        } else {
            val
        };
        Ok(self.wrap_pos(self.emit.window_frame_bound(ty, frame_value), bound_start))
    }

    fn parse_select_columns(&mut self) -> Result<Vec<E::Value>, ParseError> {
        // `selectColumnExprList` with optional trailing comma. Each item is
        // either `IDENT COLON expr` (alias-before), `expr [implicitAlias]`,
        // or `expr AS alias` (`AS` already handled by Pratt as an infix).
        let mut cols: Vec<E::Value> = Vec::new();
        loop {
            if matches!(
                self.peek(),
                TokenKind::Eof | TokenKind::RParen | TokenKind::Semicolon
            ) {
                break;
            }
            // `selectColumnExprList: selectColumnExpr (COMMA selectColumnExpr)*
            // COMMA?` — after a comma the list continues with another
            // column for any clause keyword that can also be a Field
            // (`select 1, window from t` keeps `window` as the second
            // column). Whether the comma was trailing is decided
            // entirely by `peek_is_clause_terminator` below (it folds
            // in `peek_is_two_token_clause_terminator` and the `FROM`
            // table-reference carve-out).
            //
            // A clause keyword after the trailing comma starts its
            // clause — not another column — whenever a valid clause
            // body follows: cpp's ALL(*) prefers the clause when both
            // the column and the clause interpretations parse (`select
            // a, where * columns('x')` is one column plus a WHERE
            // clause, even though `where * columns('x')` is also a
            // valid multiplication column). With no body the keyword
            // stays a column (`select a, where` → two columns);
            // `peek_is_clause_terminator` encodes that split, incl. the
            // `WINDOW <name> AS (` and arith-`*` carve-outs. The `:`
            // guard keeps the alias-before form (`select a, where : 1`)
            // out of this path.
            // A `from` here normally opens the FROM clause and ends the column
            // list. But cpp's `selectColumnExprListBeforeFrom` makes every
            // `from X` BEFORE the last one a SELECT column (the
            // `ColumnExprInvalidFromImplicitAlias` footgun for bare `from
            // <ident>`, or a `from(...)` call); only the FINAL `from` opens the
            // clause. So when a later `from` exists, don't break — fall through
            // and parse this `from X` as a column (`from b` then rejects via
            // `is_bare_from_field`; `from(b)` stays a valid call column).
            // A `from <implicitAlias>` whose FROM region dangles a `, USING SAMPLE`
            // / `, ARRAY JOIN` is, per cpp's greedy `selectColumnExprListBeforeFrom`,
            // a `ColumnExprInvalidFromImplicitAlias` column (not the FROM clause) —
            // so don't break; fall through to parse `from X` as a column, which
            // rejects via `is_bare_from_field`. Mirrors the second-`from` carve-out.
            if !cols.is_empty()
                && self.peek_next() != TokenKind::Colon
                && self.peek_is_clause_terminator()
                && !(self.peek() == TokenKind::Keyword(Kw::From)
                    && self.from_clause_followed_by_another_from())
                && !(self.peek() == TokenKind::Keyword(Kw::From)
                    && self.peek_next_is_implicit_alias()
                    && self.from_region_has_dangling_clause_comma())
            {
                break;
            }
            let col_start = self.peek0.start;
            // Alias-before: `IDENT : expr` or `"IDENT" : expr` or
            // `<keyword> : expr`. The grammar's `identifier` rule admits
            // any keyword (per the `keyword` production), so e.g.
            // `select asc : 1` is valid and aliases `1` as `asc`.
            if matches!(
                self.peek(),
                TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
            ) && self.peek_next() == TokenKind::Colon
            {
                let name_tok = self.bump()?;
                let name = identifier_text(self.text(name_tok), name_tok.kind);
                if !matches!(name_tok.kind, TokenKind::QuotedIdent) {
                    check_alias_not_reserved(&name, name_tok.start, name_tok.end)?;
                }
                self.bump()?; // consume `:`
                let expr = self.parse_expr_bp(0)?;
                // cpp's `ColumnExprAlias` ctx for the alias-before form
                // (`IDENT COLON columnExpr`) spans from the alias ident
                // through the value expression. Wrap so the column's
                // `start` / `end` match cpp's `addPositionInfo`.
                cols.push(self.wrap_pos(self.emit.alias(expr, &name), col_start));
            } else {
                let expr = self.parse_expr_bp(0)?;
                // Implicit alias: a trailing identifier (or one of the
                // `keywordForImplicitAlias` set) directly after the
                // expression. Plain `AS alias` is already folded into the
                // expression by the Pratt loop.
                let aliased = if let Some(name) = self.try_consume_implicit_alias()? {
                    // Grammar alt `FROM implicitAlias #
                    // ColumnExprInvalidFromImplicitAlias`: a bare `from`
                    // Field carrying an *implicit* (no-`AS`) alias is a
                    // deliberate footgun-catcher — cpp's visitor rejects
                    // it. (`from AS x` is fine; the `AS` form folds into
                    // the expr above and never reaches here.)
                    if is_bare_from_field(&self.emit, &expr)
                        && !self.suppress_unvisited_clause_checks
                    {
                        return Err(self.err("Cannot use \"from\" before an implicit alias"));
                    }
                    // cpp's `ColumnExprAlias` ctx for the implicit-alias
                    // form (`columnExpr IDENT`) spans from the value
                    // expression through the alias identifier — wrap
                    // with the column's running start so the Alias
                    // carries the cpp span.
                    self.wrap_pos(self.emit.alias(expr, &name), col_start)
                } else {
                    expr
                };
                cols.push(aliased);
            }
            if !self.eat(TokenKind::Comma)? {
                break;
            }
        }
        Ok(cols)
    }

    /// Probe forward from the current `from` (`peek0 == Keyword(From)`) for a
    /// SECOND depth-0 `from` within the same FROM-clause region. A valid single
    /// `joinExpr` never has two depth-0 `from` keywords, so a second one means
    /// the current `from` is a SELECT column (not the clause) per cpp's
    /// `selectColumnExprListBeforeFrom`. Stops at the from-region's end (a
    /// depth-0 clause keyword / set-op, a closing bracket below the start depth,
    /// `;`, or EOF) so a `from` in a later clause or UNIONed select doesn't
    /// count.
    fn from_clause_followed_by_another_from(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.end);
        let mut depth: i32 = 0;
        loop {
            let kind = match probe.next_token() {
                Ok(t) => t.kind,
                Err(_) => return false,
            };
            match kind {
                TokenKind::Eof | TokenKind::Semicolon => return false,
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    depth -= 1;
                    if depth < 0 {
                        return false;
                    }
                }
                TokenKind::Keyword(Kw::From) if depth == 0 => return true,
                TokenKind::Keyword(kw) if depth == 0 && from_region_terminator(kw) => return false,
                _ => {}
            }
        }
    }

    /// Probe forward from the current `from` (`peek0 == Keyword(From)`) for a
    /// depth-0 `COMMA` immediately followed by a two-token clause introducer —
    /// `USING SAMPLE` or `ARRAY JOIN`. Consulted only in the leading/trailing-
    /// comma column context (the column-loop break is unreachable otherwise), so
    /// a hit means cpp's greedy `selectColumnExprListBeforeFrom` consumes this
    /// `from <implicitAlias>` (and any following cross-join tables) as columns up
    /// to that trailing comma, leaving the introducer as a select-level clause —
    /// then its visitor rejects the `ColumnExprInvalidFromImplicitAlias`. cpp:
    /// `select 1, from f, using sample 1` and `… , array join x` reject, while
    /// `select 1, from f, using` / `… , array` (a bare keyword cross-join table,
    /// no SAMPLE/JOIN) and the no-leading-comma `select 1 from f, using sample 1`
    /// stay valid — hence the two-token check and the comma-context gate. Stops
    /// at the from-region's end (depth-0 terminator, closing bracket below the
    /// start depth, `;`, or EOF).
    fn from_region_has_dangling_clause_comma(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.end);
        let mut depth: i32 = 0;
        let mut prev_was_comma = false;
        loop {
            let kind = match probe.next_token() {
                Ok(t) => t.kind,
                Err(_) => return false,
            };
            match kind {
                TokenKind::Eof | TokenKind::Semicolon => return false,
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => {
                    depth += 1;
                    prev_was_comma = false;
                }
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    depth -= 1;
                    if depth < 0 {
                        return false;
                    }
                    prev_was_comma = false;
                }
                TokenKind::Comma if depth == 0 => prev_was_comma = true,
                TokenKind::Keyword(Kw::Using) if depth == 0 && prev_was_comma => {
                    return matches!(
                        probe.next_token().map(|t| t.kind),
                        Ok(TokenKind::Keyword(Kw::Sample))
                    );
                }
                TokenKind::Keyword(Kw::Array) if depth == 0 && prev_was_comma => {
                    return matches!(
                        probe.next_token().map(|t| t.kind),
                        Ok(TokenKind::Keyword(Kw::Join))
                    );
                }
                TokenKind::Keyword(kw) if depth == 0 && from_region_terminator(kw) => return false,
                _ => {
                    if depth == 0 {
                        prev_was_comma = false;
                    }
                }
            }
        }
    }

    /// True when the token after `peek0` can be an `implicitAlias`
    /// (`IDENTIFIER | QUOTED_IDENTIFIER | keywordForImplicitAlias`) — i.e. a bare
    /// `from <here>` could be the grammar's `FROM implicitAlias` column form.
    fn peek_next_is_implicit_alias(&self) -> bool {
        matches!(self.peek_next(), TokenKind::Ident | TokenKind::QuotedIdent)
            || matches!(self.peek_next(), TokenKind::Keyword(kw) if kw_allowed_as_implicit_alias(kw))
    }

    fn try_consume_implicit_alias(&mut self) -> Result<Option<String>, ParseError> {
        match self.peek() {
            TokenKind::Ident => {
                let t = self.bump()?;
                let name = identifier_text(self.text(t), t.kind);
                check_alias_not_reserved(&name, t.start, t.end)?;
                Ok(Some(name))
            }
            TokenKind::QuotedIdent => {
                let t = self.bump()?;
                Ok(Some(identifier_text(self.text(t), t.kind)))
            }
            TokenKind::Keyword(kw) if kw_allowed_as_implicit_alias(kw) => {
                let t = self.bump()?;
                let name = self.text(t).to_string();
                check_alias_not_reserved(&name, t.start, t.end)?;
                Ok(Some(name))
            }
            _ => Ok(None),
        }
    }
}

/// Keywords whose appearance at depth 0 ends the FROM-clause region: the
/// post-FROM clauses and the set-operation joiners. Used by
/// `from_clause_followed_by_another_from` to bound its look-ahead so a `from`
/// in a later clause or UNIONed select isn't mistaken for a second FROM.
fn from_region_terminator(kw: Kw) -> bool {
    matches!(
        kw,
        Kw::Where
            | Kw::Prewhere
            | Kw::Group
            | Kw::Having
            | Kw::Qualify
            | Kw::Window
            | Kw::Order
            | Kw::Limit
            | Kw::Offset
            | Kw::Settings
            | Kw::Union
            | Kw::Intersect
            | Kw::Except
            | Kw::Array
    )
}

/// True when `expr` is a bare `from` Field — a `Field` whose chain is
/// the single element `from` (any case). Flags the grammar's
/// `ColumnExprInvalidFromImplicitAlias` footgun (`select from x`) in the SELECT
/// column list. (A bare `from` in *table* position is valid — `from b, from c`
/// is table `from` aliased `c` — so the FROM/join path does not use this.)
pub(crate) fn is_bare_from_field<E: Emitter>(emit: &E, expr: &E::Value) -> bool {
    if emit.node_kind(expr).as_deref() != Some("Field") {
        return false;
    }
    match emit.get_field(expr, "chain").and_then(|c| emit.as_list(&c)) {
        Some(chain) => {
            chain.len() == 1
                && emit
                    .as_str(&chain[0])
                    .is_some_and(|s| s.eq_ignore_ascii_case("from"))
        }
        None => false,
    }
}

/// Inside a `LIMIT … BY <list>`, given that the previous token was a
/// comma and `peek` is OFFSET, does `peek_next` terminate the list? cpp
/// continues whenever `offset <peek_next>` could be parsed as a columnExpr
/// (postfix chain `. [ (`, infix operator, infix keyword, `AS` alias),
/// and only terminates when `peek_next` is a standalone primary-expression
/// starter that doesn't combine with the preceding `offset` Field.
fn offset_next_terminates_limit_by(tok: TokenKind) -> bool {
    match tok {
        // Primary-only starters: a fresh expression begins, so `offset`
        // ends the previous list item AND the OFFSET clause body starts.
        TokenKind::Ident
        | TokenKind::QuotedIdent
        | TokenKind::Number
        | TokenKind::String
        | TokenKind::LBrace
        // `#N` (HASH DECIMAL_LITERAL) is the ColumnExprPositional form
        // — a primary-only expression that doesn't combine with a
        // preceding `offset` Field.
        | TokenKind::Hash
        // Primary-only keywords (kw_acts_as_ident_in_primary style):
        // these start fresh expressions and never act as infix
        // continuation of a Field.
        | TokenKind::Keyword(
            Kw::Case
            | Kw::Cast
            | Kw::TryCast
            | Kw::Lambda
            | Kw::Interval
            | Kw::Columns
            | Kw::True
            | Kw::False
            | Kw::Null
            | Kw::Inf
            | Kw::Nan
            | Kw::Distinct
            | Kw::Array
            | Kw::Trim
            | Kw::Select
            | Kw::With,
        ) => true,
        // Everything else (operators, postfix chaining, infix keywords,
        // commas, parens) keeps `offset` as a Field — the list continues.
        _ => false,
    }
}
