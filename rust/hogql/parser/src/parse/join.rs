//! `FROM` clause + JOIN chain parsing.
//!
//! Covers everything from the `tableExpr` leaf up through the
//! left-recursive `joinExpr` chain, including the table-function
//! sentinel, PIVOT/UNPIVOT decoration, and the `SAMPLE … OFFSET …`
//! qualifier. ARRAY JOIN is *not* here — it belongs to the SELECT
//! statement (see `parse_select_stmt_body` in `select.rs`).

use super::{
    chain_join, check_alias_not_reserved, identifier_text, kw_valid_as_identifier, Parser,
};
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, TokenKind};

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    pub(crate) fn parse_join_expr(&mut self) -> Result<E::Value, ParseError> {
        // Left-recursive in the grammar; iterate, chaining each new
        // right-side table into the previous JoinExpr's `next_join` field.
        let chain_start = self.peek0.start;
        let mut left = self.parse_table_atom_with_pivot()?;
        // Record the lead's chain depth: a parens-wrapped joinExpr arrives
        // pre-built (e.g. `(a JOIN b)` is two JoinExprs deep). The peel-extras
        // loop below must NOT attach constraints into pre-existing joins —
        // those slots belong to the inner scope. Scope-local additions made
        // by THIS loop sit at depth > lead_depth.
        let lead_depth = chain_depth(&self.emit, &left);
        let mut joined_any = false;
        loop {
            // ARRAY JOIN belongs to the outer SELECT statement, not the
            // JoinExpr chain — exit the loop when we see one (in any of
            // its prefix forms: bare `ARRAY JOIN`, `LEFT ARRAY JOIN`,
            // `INNER ARRAY JOIN`) so parse_select_stmt can take over.
            if matches!(self.peek(), TokenKind::Keyword(Kw::Array))
                && self.peek_next() == TokenKind::Keyword(Kw::Join)
            {
                break;
            }
            if matches!(
                self.peek(),
                TokenKind::Keyword(Kw::Left) | TokenKind::Keyword(Kw::Inner)
            ) && self.peek_next() == TokenKind::Keyword(Kw::Array)
            {
                break;
            }
            // `,` cross join. A trailing comma (peek_next can't start a table
            // atom) is NOT a join-chain construct — cpp rejects it after a
            // cross / plain / positional join (`a, b,`, `a join b,`). The only
            // tolerated trailing comma is an ON / USING `columnExprList`'s
            // optional `COMMA?` (`a JOIN b ON 1,`), which is consumed inside
            // `parse_join_constraint_opt` so its span matches cpp's. So just
            // leave any trailing comma here for the SELECT parser, which
            // rejects it.
            if self.peek() == TokenKind::Comma {
                if !self.peek_next_starts_table_atom() {
                    break;
                }
                self.bump()?;
                let right = self.parse_table_atom_with_pivot()?;
                left = chain_join(&self.emit, left, right, "CROSS JOIN", None);
                joined_any = true;
                continue;
            }
            // CROSS JOIN explicit.
            if matches!(self.peek(), TokenKind::Keyword(Kw::Cross))
                && self.peek_next() == TokenKind::Keyword(Kw::Join)
            {
                self.bump()?;
                self.bump()?;
                let right = self.parse_table_atom_with_pivot()?;
                left = chain_join(&self.emit, left, right, "CROSS JOIN", None);
                joined_any = true;
                continue;
            }
            // POSITIONAL JOIN.
            if matches!(self.peek(), TokenKind::Keyword(Kw::Positional))
                && self.peek_next() == TokenKind::Keyword(Kw::Join)
            {
                self.bump()?;
                self.bump()?;
                let right = self.parse_table_atom_with_pivot()?;
                let constraint = self.parse_join_constraint_opt()?;
                left = chain_join(&self.emit, left, right, "POSITIONAL JOIN", constraint);
                joined_any = true;
                continue;
            }
            // [NATURAL]? [SEMI|ANTI|ALL|ANY|ASOF]? [INNER|LEFT|RIGHT|FULL [OUTER]?]? JOIN target.
            let _natural = self.eat_kw(Kw::Natural)?;
            let join_op = self.try_consume_join_op()?;
            if join_op.is_none() && !matches!(self.peek(), TokenKind::Keyword(Kw::Join)) {
                // No JOIN — but PIVOT / UNPIVOT also extend the
                // joinExpr chain, and the result can still take an
                // alias / FINAL / SAMPLE or a further JOIN / PIVOT.
                if matches!(
                    self.peek(),
                    TokenKind::Keyword(Kw::Pivot) | TokenKind::Keyword(Kw::Unpivot)
                ) {
                    left = self.wrap_pivot_chain(left, joined_any, chain_start)?;
                    continue;
                }
                break;
            }
            let op_text = join_op.unwrap_or_default();
            self.expect_kw(Kw::Join, "JOIN")?;
            let right = self.parse_table_atom_with_pivot()?;
            let constraint = self.parse_join_constraint_opt()?;
            let join_type = if op_text.is_empty() {
                "JOIN".to_string()
            } else {
                format!("{op_text} JOIN")
            };
            left = chain_join(&self.emit, left, right, &join_type, constraint);
            joined_any = true;
        }

        // cpp's left-recursive `joinExpr JOIN joinExpr joinConstraintClause?`
        // attaches a stacked `ON1 ON2 ON3` run right-associatively (ON1 → innermost
        // JOIN, ON3 → outermost). Our loop above is left-to-right and grabs only
        // one constraint per JOIN; peel the rest off here, inward-to-outward. If
        // no attachment site exists — bare FROM, all-CROSS chain, or every slot
        // already filled — raise a syntax error at the stray keyword.
        //
        // Guard against the SELECT-statement-level `USING sampleClause` form
        // (grammar `(USING? sampleClause)?`): `USING SAMPLE 0.5` belongs to the
        // outer selectStmt, not the JOIN — leave it for the SELECT parser.
        while matches!(
            self.peek(),
            TokenKind::Keyword(Kw::On) | TokenKind::Keyword(Kw::Using)
        ) {
            if self.peek() == TokenKind::Keyword(Kw::Using)
                && self.peek_next() == TokenKind::Keyword(Kw::Sample)
            {
                break;
            }
            let kw_kind = self.peek();
            let Some(constraint) = self.parse_join_constraint_opt()? else {
                break;
            };
            let (updated, attached) = attach_constraint_to_outermost_unconstrained_join(
                &self.emit,
                left,
                constraint,
                lead_depth + 1,
                1,
            );
            left = updated;
            if !attached {
                let kw = if matches!(kw_kind, TokenKind::Keyword(Kw::On)) {
                    "ON"
                } else {
                    "USING"
                };
                return Err(self.err(format!(
                    "stray {kw} — no preceding JOIN can take a constraint clause"
                )));
            }
        }

        // wrap_pos is idempotent. parse_table_atom and wrap_pivot_chain
        // both wrap their results with positions, so `left` always has
        // a span by this point — keeping wrap_pos here matches cpp's
        // JoinExprParens semantics (unwrap parens, keep the inner's
        // positions) and cpp's JoinExprOp / JoinExprCrossOp semantics
        // (chain joins, keep the head's positions; do not extend to the
        // joined-in tables).
        Ok(self.wrap_pos(left, chain_start))
    }

    /// `parse_table_atom` followed by an optional immediately-adjacent
    /// `PIVOT` / `UNPIVOT`. The grammar's `joinExpr PIVOT` is
    /// left-recursive on the *immediately preceding* joinExpr, so
    /// `a JOIN b PIVOT (…)` pivots `b` alone — the PIVOT binds to the
    /// freshly-parsed atom, not the whole JOIN chain. A PIVOT that
    /// instead follows a join *constraint* (`a JOIN b ON x PIVOT (…)`)
    /// applies to the whole chain; that case is left for the caller's
    /// loop, which calls `wrap_pivot_chain` with `joined_any`.
    fn parse_table_atom_with_pivot(&mut self) -> Result<E::Value, ParseError> {
        let atom_start = self.peek0.start;
        let atom = self.parse_table_atom()?;
        if matches!(
            self.peek(),
            TokenKind::Keyword(Kw::Pivot) | TokenKind::Keyword(Kw::Unpivot)
        ) {
            return self.wrap_pivot_chain(atom, false, atom_start);
        }
        Ok(atom)
    }

    /// Consume a `PIVOT (...)` / `UNPIVOT (...)` run that decorates the
    /// current join chain, then any `JoinExprTable`/`TableExprAlias`
    /// decoration the result can still take. `tableExpr PIVOT (...)` is
    /// itself a `tableExpr`, so an alias (`TableExprAlias`) and a
    /// trailing `FINAL? sampleClause?` (`JoinExprTable`) all still apply
    /// — `FROM (t PIVOT (...) AS x FINAL)`. The caller loops, so a
    /// following JOIN or further PIVOT is picked up too.
    fn wrap_pivot_chain(
        &mut self,
        left: E::Value,
        joined_any: bool,
        table_start: usize,
    ) -> Result<E::Value, ParseError> {
        // A trailing `sampleClause` binds here only for a tableExpr-pivot. Grammar has PIVOT at two levels: `tableExpr PIVOT (…)` (TableExprPivot, still a tableExpr, which feeds `JoinExprTable: tableExpr FINAL? sampleClause?`) and `joinExpr PIVOT (…)` (JoinExprPivot, a joinExpr). SAMPLE attaches only when the operand is a lone tableExpr: no JOIN happened and the atom isn't a parens-wrapped JOIN chain. Otherwise it's the statement-level `(USING? sampleClause)?`, left for `reject_select_level_sample`.
        let operand_is_table_expr = !joined_any && !self.emit.has_field(&left, "next_join");
        // For the single-atom case (no JOIN happened) the chain is a
        // JoinExpr that only wraps a bare Field — unwrap to match cpp's
        // shape (PivotExpr's `table` is the bare Field). When the
        // JoinExpr carries an alias / final / sample / column_aliases,
        // keep it as is since that decoration belongs *inside* the PIVOT.
        // `start` / `end` are position metadata, not grammar decoration —
        // exclude from the decoration probe.
        let pivot_input = if joined_any {
            left
        } else if self.emit.node_kind(&left).is_some() {
            // For abstract values we can't enumerate fields, so we use
            // a probe-based check: if the value has only the "expected"
            // shape (node + table + positions), peel out `table`. We
            // approximate by checking `alias` / `final` / `sample` /
            // `column_aliases` absence — the only other top-level
            // JoinExpr decorations.
            let decorated = self.emit.has_field(&left, "alias")
                || self.emit.has_field(&left, "table_final")
                || self.emit.has_field(&left, "sample")
                || self.emit.has_field(&left, "column_aliases")
                || self.emit.has_field(&left, "table_args")
                || self.emit.has_field(&left, "next_join");
            if decorated {
                left
            } else {
                self.emit.get_field(&left, "table").unwrap_or(left)
            }
        } else {
            left
        };
        let wrapped = self.try_consume_pivot_unpivot(pivot_input, table_start)?;
        // Wrap the PivotExpr/UnpivotExpr in an outer JoinExpr (the C++
        // visitor's JoinExprPivot does the same).
        // Grammar order: `TableExprAlias` (alias + columnAliases) binds
        // inside `tableExpr`, then `JoinExprTable` adds `FINAL?
        // sampleClause?`.
        let (alias, column_aliases, _) = self.consume_table_alias_chain()?;
        let table_final = self.eat_kw(Kw::Final)?;
        // Table-level SAMPLE (`tableExpr FINAL? sampleClause?`) binds only to a tableExpr-pivot; a joinExpr-pivot's trailing SAMPLE is statement-level, left for `reject_select_level_sample`.
        let sample = if operand_is_table_expr {
            self.try_consume_sample()?
        } else {
            None
        };
        let outer = self
            .emit
            .join_expr(wrapped, alias, None, column_aliases, table_final, sample);
        // Wrap before returning so the JoinExpr carries positions even
        // when a later wrap_pivot_chain stacks it as the inner table of
        // a fresh outer PivotExpr / UnpivotExpr. The outer parse_join_expr
        // wrap_pos at line ~160 is idempotent and only reaches the
        // *outermost* node — the inner one needs its own wrap here.
        Ok(self.wrap_pos(outer, table_start))
    }

    fn try_consume_join_op(&mut self) -> Result<Option<String>, ParseError> {
        // Mirror the C++ visitor's canonical ordering — the AST validates
        // join_type against a fixed allow-list and source-order
        // concatenation would produce variants outside it.
        let candidates: &[Kw] = &[
            Kw::All,
            Kw::Any,
            Kw::Asof,
            Kw::Inner,
            Kw::Left,
            Kw::Right,
            Kw::Full,
            Kw::Outer,
            Kw::Semi,
            Kw::Anti,
        ];
        let mut all = false;
        let mut any = false;
        let mut asof = false;
        let mut inner = false;
        let mut left = false;
        let mut right = false;
        let mut full = false;
        let mut outer = false;
        let mut semi = false;
        let mut anti = false;
        let mut seen_any_kw = false;
        // Track source order of relevant keywords for ordering-sensitive
        // grammar checks below (e.g. `ASOF (ANTI|SEMI)` must come in
        // that order, never `ANTI ASOF`).
        let mut order: Vec<Kw> = Vec::new();
        loop {
            let TokenKind::Keyword(kw) = self.peek() else {
                break;
            };
            if !candidates.contains(&kw) {
                break;
            }
            self.bump()?;
            seen_any_kw = true;
            // Each modifier keyword may appear at most once. cpp's
            // ANTLR `joinOp` alts each reference each
            // keyword at most once; rust was silently OR-ing duplicates
            // into the boolean state, so `INNER INNER JOIN` /
            // `LEFT OUTER LEFT JOIN` slipped through.
            let already_set = match kw {
                Kw::All => all,
                Kw::Any => any,
                Kw::Asof => asof,
                Kw::Inner => inner,
                Kw::Left => left,
                Kw::Right => right,
                Kw::Full => full,
                Kw::Outer => outer,
                Kw::Semi => semi,
                Kw::Anti => anti,
                _ => false,
            };
            if already_set {
                return Err(self.err(format!("duplicate {:?} in JOIN op", kw)));
            }
            match kw {
                Kw::All => all = true,
                Kw::Any => any = true,
                Kw::Asof => asof = true,
                Kw::Inner => inner = true,
                Kw::Left => left = true,
                Kw::Right => right = true,
                Kw::Full => full = true,
                Kw::Outer => outer = true,
                Kw::Semi => semi = true,
                Kw::Anti => anti = true,
                _ => {}
            }
            order.push(kw);
        }
        if !seen_any_kw {
            return Ok(None);
        }

        // Grammar validation. The three `joinOp` alts partition the
        // keyword set:
        //   JoinOpInner   ⇒ INNER + at most one of ALL/ANY/ASOF; or
        //                   ANTI; or SEMI; or ASOF (ANTI|SEMI). No
        //                   LEFT/RIGHT/FULL/OUTER.
        //   JoinOpLeftRight ⇒ exactly one of LEFT/RIGHT; optional
        //                   OUTER; optional one of SEMI/ALL/ANTI/ANY/ASOF
        //                   on either side. No INNER/FULL.
        //   JoinOpFull    ⇒ FULL; optional OUTER; optional one of
        //                   ALL/ANY/ASOF. No INNER/LEFT/RIGHT/ANTI/SEMI.
        // Rust's source-order loop happily accepted any subset, then
        // emitted a canonical-order token list — letting `INNER LEFT
        // JOIN` through as the synthetic `LEFT INNER`. Validate the
        // boolean state against the grammar before composing tokens.
        let lr_count = (left as u8) + (right as u8);
        if lr_count > 1 {
            return Err(self.err("LEFT and RIGHT cannot both appear in a JOIN op"));
        }
        if full && (inner || left || right || anti || semi) {
            return Err(self.err("FULL cannot combine with INNER/LEFT/RIGHT/ANTI/SEMI"));
        }
        if inner && (left || right || full || anti || semi) {
            return Err(self.err("INNER cannot combine with LEFT/RIGHT/FULL/ANTI/SEMI"));
        }
        if outer && !(left || right || full) {
            return Err(self.err("OUTER requires LEFT/RIGHT/FULL"));
        }
        // Within-category arity per the `joinOp` alts:
        //   - At most one of ALL/ANY/ASOF in any alt (the grammar
        //     references the group as `(ALL|ANY|ASOF)?`, never twice).
        //   - ANTI and SEMI never together — inner-style admits `ANTI`,
        //     `SEMI`, or `ASOF (ANTI|SEMI)` (one or the other, not both).
        //   - For the inner-style alt, ANTI / SEMI only combine with
        //     ASOF (never ALL or ANY).
        let modifier_count = (all as u8) + (any as u8) + (asof as u8);
        if modifier_count > 1 {
            return Err(self.err("JOIN op accepts at most one of ALL / ANY / ASOF"));
        }
        if anti && semi {
            return Err(self.err("ANTI and SEMI cannot both appear in a JOIN op"));
        }
        if !full && !left && !right {
            // Inner-style. ANTI / SEMI combine only with ASOF (never
            // ALL / ANY): `ASOF (ANTI | SEMI)`. And in that order —
            // `ANTI ASOF` / `SEMI ASOF` is the reverse and invalid.
            if (anti || semi) && (all || any) {
                return Err(
                    self.err("inner-style JOIN op: ANTI / SEMI cannot combine with ALL / ANY")
                );
            }
            if asof && (anti || semi) {
                let asof_pos = order.iter().position(|&k| k == Kw::Asof);
                let antisemi_pos = order.iter().position(|&k| matches!(k, Kw::Anti | Kw::Semi));
                if matches!((asof_pos, antisemi_pos), (Some(a), Some(b)) if a > b) {
                    return Err(self.err("JOIN op: ANTI / SEMI must follow ASOF, not precede it"));
                }
            }
        }

        let mut tokens: Vec<&str> = Vec::new();
        if left || right {
            if left {
                tokens.push("LEFT");
            }
            if right {
                tokens.push("RIGHT");
            }
            if outer {
                tokens.push("OUTER");
            }
            if semi {
                tokens.push("SEMI");
            }
            if all {
                tokens.push("ALL");
            }
            if anti {
                tokens.push("ANTI");
            }
            if any {
                tokens.push("ANY");
            }
            if asof {
                tokens.push("ASOF");
            }
        } else if full {
            tokens.push("FULL");
            if outer {
                tokens.push("OUTER");
            }
            if all {
                tokens.push("ALL");
            }
            if any {
                tokens.push("ANY");
            }
            if asof {
                tokens.push("ASOF");
            }
        } else {
            // Inner-style.
            if all {
                tokens.push("ALL");
            }
            if any {
                tokens.push("ANY");
            }
            if asof {
                tokens.push("ASOF");
            }
            if anti {
                tokens.push("ANTI");
            }
            if semi {
                tokens.push("SEMI");
            }
            if inner || (!anti && !semi) {
                tokens.push("INNER");
            }
        }
        Ok(Some(tokens.join(" ")))
    }

    fn parse_join_constraint_opt(&mut self) -> Result<Option<E::Value>, ParseError> {
        let cons_start = self.peek0.start;
        if self.eat_kw(Kw::On)? {
            let expr = self.parse_expr_bp(0)?;
            // cpp's `joinConstraintClause: ON columnExprList` greedily
            // consumes the comma-separated list, then the cpp visitor
            // raises `NotImplementedError` for any list with more than
            // one expression. Mirror that here: a comma followed by
            // anything that could continue the list belongs to the ON
            // list, not the outer JOIN's CROSS-JOIN comma. Rust used
            // to fall out and let the outer chain consume it as
            // cross-join, silently emitting a divergent JoinExpr.
            //
            // A *trailing* comma (`FROM a JOIN b ON 1,` with nothing parseable
            // after) is the `columnExprList`'s optional `COMMA?` — valid, and
            // cpp's JoinConstraint span covers it. Consume it here so the span
            // matches (and so the outer JOIN loop doesn't have to special-case
            // it). A comma with a real expression after is the unsupported
            // multi-expression list.
            if self.peek() == TokenKind::Comma {
                if matches!(
                    self.peek_next(),
                    TokenKind::Eof | TokenKind::Semicolon | TokenKind::RParen
                ) {
                    self.bump()?;
                } else {
                    let start = self.peek0.start;
                    let end = self.peek0.end;
                    return Err(ParseError::not_implemented(
                        "Unsupported: JOIN ... ON with multiple expressions",
                        start,
                        end,
                    ));
                }
            }
            return Ok(Some(
                self.wrap_pos(self.emit.join_constraint(expr, "ON"), cons_start),
            ));
        }
        if self.eat_kw(Kw::Using)? {
            // The grammar `joinConstraintClause` admits two USING shapes:
            //   `USING LPAREN columnExprList RPAREN`
            //   `USING columnExprList`
            // — both require a non-empty columnExprList. cpp rejects
            // `USING ()`; rust was silently producing an empty list.
            let exprs = if self.eat(TokenKind::LParen)? {
                if self.peek() == TokenKind::RParen {
                    return Err(self.err("USING (…) must have at least one expression"));
                }
                let list = self.parse_expr_list_until_paren()?;
                self.expect(TokenKind::RParen, ")")?;
                list
            } else {
                self.parse_expr_list_until_terminators()?
            };
            let expr = if exprs.len() == 1 {
                exprs.into_iter().next().unwrap()
            } else {
                self.emit.tuple_(exprs)
            };
            // Trailing `COMMA?` of the columnExprList — the paren form leaves it
            // after `)`; the no-paren list parse already absorbs it. Consume it
            // so the JoinConstraint span matches cpp's (`USING (c),`).
            if self.peek() == TokenKind::Comma
                && matches!(
                    self.peek_next(),
                    TokenKind::Eof | TokenKind::Semicolon | TokenKind::RParen
                )
            {
                self.bump()?;
            }
            return Ok(Some(
                self.wrap_pos(self.emit.join_constraint(expr, "USING"), cons_start),
            ));
        }
        Ok(None)
    }

    /// Probe: does `peek_next` look like the start of a `tableExpr`?
    /// Used by the JOIN loop to decide whether a top-level `,` is the
    /// start of a CROSS JOIN (table atom follows) or a stray trailing
    /// comma that the SELECT-level parser will handle.
    fn peek_next_starts_table_atom(&self) -> bool {
        matches!(
            self.peek_next(),
            TokenKind::Ident
                | TokenKind::QuotedIdent
                | TokenKind::LParen
                | TokenKind::LBrace
                | TokenKind::Lt
                | TokenKind::Keyword(Kw::Values)
        ) || matches!(
            self.peek_next(),
            TokenKind::Keyword(kw) if super::kw_valid_as_identifier(kw)
        )
    }

    fn parse_table_atom(&mut self) -> Result<E::Value, ParseError> {
        let atom_start = self.peek0.start;
        let table_expr = self.parse_table_expr()?;
        // Snapshot the end of `tableExpr` before alias / FINAL / SAMPLE
        // are consumed. For the table-function case (cpp's
        // `TableFunctionExpr`), cpp's emitted JoinExpr's ctx covers
        // ONLY `name(args)` — the alias is injected by the parent
        // `TableExprAlias` without changing the JoinExpr's span. Capture
        // here so the table-function branch below can clamp `end` to
        // the args-close position rather than letting it run through
        // the alias / FINAL / SAMPLE decorations.
        let table_expr_end = self.last_consumed_end;
        // `(joinExpr)` per the grammar's `JoinExprParens` returns an
        // already-wrapped JoinExpr (or chain). The grammar:
        //   joinExpr: ... | LPAREN joinExpr RPAREN  # JoinExprParens
        //   tableExpr: ... | tableExpr (alias | AS identifier) columnAliases?
        //                                           # TableExprAlias
        // `TableExprAlias` requires a `tableExpr` head — `LPAREN
        // joinExpr RPAREN` is a `joinExpr`, NOT a `tableExpr`, so an
        // alias / FINAL / SAMPLE / columnAliases CANNOT bind after the
        // closing paren. cpp rejects `(t) AS x`, `(t JOIN b ON x) AS y`,
        // `(t) FINAL`, etc. Return the JoinExpr unchanged and let the
        // caller surface any post-paren tokens as trailing-input errors.
        let already_join_expr = self.emit.node_kind(&table_expr).as_deref() == Some("JoinExpr");
        if already_join_expr {
            return Ok(table_expr);
        }
        // parse_table_expr signals table-function args via a sentinel key
        // on the returned Field — extract them into `table_args` so the
        // JoinExpr wrapper gets the C++-shape Field + table_args split.
        let mut table_expr = table_expr;
        let table_args = self.emit.remove_field(&mut table_expr, "__rust_table_args");
        let is_table_function = table_args.is_some();
        // Grammar order: `TableExprAlias` is `tableExpr (alias | AS
        // identifier) columnAliases?` — the alias and column-aliases
        // bind *inside* `tableExpr` — and `JoinExprTable` then
        // decorates it with `FINAL? sampleClause?`. So the alias comes
        // first, FINAL and SAMPLE after. Parsing SAMPLE before the
        // alias (as this did) silently dropped the sample on an
        // aliased table — `t AS e SAMPLE 1` lost its `SampleExpr`.
        let (alias, column_aliases, first_alias_end) = self.consume_table_alias_chain()?;
        let had_alias = alias.is_some() || column_aliases.is_some();
        // Snapshot end after the FIRST alias / column_aliases — cpp's
        // `TableExprAlias` ctx covers `tableExpr alias columnAliases?` and its
        // JoinExpr wrap stops at the innermost (first) alias. Stacked aliases
        // (`x a b c`, or the `t format JSON` FORMAT-as-alias chain) overwrite
        // the alias field but don't widen the span; the subsequent FINAL /
        // SAMPLE in the parent `JoinExprTable` rule don't widen it either.
        let after_alias_end = first_alias_end.unwrap_or(self.last_consumed_end);
        // `JoinExprTable: tableExpr FINAL? sampleClause?` — FINAL and
        // SAMPLE decorate the (possibly aliased) table.
        let final_ = self.eat_kw(Kw::Final)?;
        let sample = self.try_consume_sample()?;

        // PIVOT/UNPIVOT detection is done at the parse_join_expr level so
        // that the wrapping applies to a whole JOIN chain rather than to
        // each individual atom — `FROM a JOIN b PIVOT (...)` wraps the
        // entire `a JOIN b`, not just `b`. parse_table_atom only handles
        // the immediate table + its alias / sample / final decoration.
        let obj = self.emit.join_expr(
            table_expr,
            alias,
            table_args,
            column_aliases,
            final_,
            sample,
        );
        // Three position-end regimes match cpp's three wrapping points:
        //   - `TableFunctionExpr` (cpp lines 2797-2817): ctx covers
        //     `name(args)` only; alias / FINAL / SAMPLE never widen it.
        //   - `TableExprAlias`     (cpp lines 2754-2790): ctx covers
        //     `tableExpr alias columnAliases?`; FINAL / SAMPLE applied
        //     by the parent JoinExprTable don't widen.
        //   - `JoinExprTable`      (cpp lines 1056-1080): wraps a non-
        //     JoinExpr tableExpr with ctx = `tableExpr FINAL? SAMPLE?`;
        //     this is the only path where FINAL / SAMPLE contribute to
        //     the span.
        let wrap_end = if is_table_function {
            table_expr_end
        } else if had_alias {
            after_alias_end
        } else {
            self.last_consumed_end
        };
        Ok(self.wrap_pos_to(obj, atom_start, wrap_end))
    }

    /// Consume a chain of table aliases. The grammar's `TableExprAlias`
    /// — `tableExpr (alias | AS identifier) columnAliases?` — is
    /// left-recursive, so a table may carry several stacked aliases
    /// (`t a b c`). cpp's `visitTableExprAlias` overwrites `alias` and
    /// `column_aliases` on every wrap, so the LAST alias wins and its
    /// column-aliases win with it (a final alias with no `columnAliases`
    /// clears any that an inner alias set). Returns `(alias,
    /// column_aliases)` for the outermost — last — alias, or
    /// `(None, None)` when the table carries no alias at all.
    fn consume_table_alias_chain(
        &mut self,
    ) -> Result<(Option<String>, Option<Vec<String>>, Option<usize>), ParseError> {
        // NB: `from <implicitAlias>` as a *table* (`select a from b, from c` —
        // table `from` aliased `c`) is valid; the grammar's
        // `ColumnExprInvalidFromImplicitAlias` footgun is a SELECT-*column*
        // form only, enforced in `parse_select_columns`. Do not reject a bare
        // `from` table here.
        let mut alias: Option<String> = None;
        let mut column_aliases: Option<Vec<String>> = None;
        // `TableExprAlias` is left-recursive (`x a b c`): cpp's nested ctxs make
        // the JoinExpr span end at the INNERMOST alias (the first `tableExpr
        // alias columnAliases?`), while each outer alias only overwrites the
        // `alias` / `column_aliases` fields. Capture the end after the FIRST
        // alias so the caller clamps the span there (`from x a b` ends at `a`,
        // `from x a (c1) b (c2)` ends at `a (c1)`).
        let mut first_alias_end: Option<usize> = None;
        while let Some(a) = self.try_consume_table_alias()? {
            alias = Some(a);
            // `columnAliases` belongs to *this* alias's `TableExprAlias`;
            // re-read each iteration so the last alias's value (present
            // or absent) is the one that survives.
            column_aliases = self.try_consume_column_aliases()?;
            if first_alias_end.is_none() {
                first_alias_end = Some(self.last_consumed_end);
            }
        }
        Ok((alias, column_aliases, first_alias_end))
    }

    /// Optional `columnAliases` — `LPAREN identifier (COMMA identifier)*
    /// RPAREN` — renaming a table's output columns. The grammar only
    /// admits it directly after a table alias, so the caller consumes it
    /// inside the alias chain, never on its own.
    fn try_consume_column_aliases(&mut self) -> Result<Option<Vec<String>>, ParseError> {
        if self.peek() != TokenKind::LParen {
            return Ok(None);
        }
        self.bump()?;
        // `columnAliases: LPAREN identifier (COMMA identifier)* RPAREN` —
        // the grammar requires at least one identifier. Empty `()` is a
        // parse error in cpp.
        if self.peek() == TokenKind::RParen {
            return Err(self.err("column-alias list must have at least one identifier"));
        }
        let mut cols = Vec::new();
        loop {
            let t = self.bump()?;
            // `columnAliases` elements are `identifier` per the grammar
            // (`IDENTIFIER | QUOTED_IDENTIFIER | interval | keyword`);
            // exclude the same reserved keywords as elsewhere.
            let name = match t.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => identifier_text(self.text(t), t.kind),
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                    identifier_text(self.text(t), t.kind)
                }
                _ => {
                    return Err(self.err(format!(
                        "expected identifier in column-alias list, got {:?}",
                        t.kind
                    )));
                }
            };
            cols.push(name);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if self.peek() == TokenKind::RParen {
                break;
            }
        }
        self.expect(TokenKind::RParen, ")")?;
        Ok(Some(cols))
    }

    fn try_consume_table_alias(&mut self) -> Result<Option<String>, ParseError> {
        if self.eat_kw(Kw::As)? {
            // `tableExpr (alias | AS identifier)` — the explicit-`AS`
            // branch is `AS identifier`, and the grammar's `identifier`
            // rule admits any keyword bar the literals / hard set-ops
            // (`kw_valid_as_identifier`). This is much wider than the
            // bare-alias `keywordForAlias` set below: cpp accepts e.g.
            // `FROM t AS hour`, `AS select`, `AS interval`.
            let t = self.bump()?;
            let name = match t.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => identifier_text(self.text(t), t.kind),
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                    identifier_text(self.text(t), t.kind)
                }
                _ => return Err(self.err(format!("expected alias after AS, got {:?}", t.kind))),
            };
            if !matches!(t.kind, TokenKind::QuotedIdent) {
                check_alias_not_reserved(&name, t.start, t.end)?;
            }
            return Ok(Some(name));
        }
        // Bare (no `AS`) alias — the grammar's `alias` rule:
        // `IDENTIFIER | QUOTED_IDENTIFIER | keywordForAlias`, where
        // `keywordForAlias` is the small DATE / FIRST / ID / KEY set
        // (none of which is a JOIN op or clause keyword, so consuming
        // one here is unambiguous).
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
            TokenKind::Keyword(Kw::Date | Kw::First | Kw::Id | Kw::Key) => {
                let t = self.bump()?;
                Ok(Some(identifier_text(self.text(t), t.kind)))
            }
            _ => Ok(None),
        }
    }

    fn parse_table_expr(&mut self) -> Result<E::Value, ParseError> {
        // `(selectSet)`, table identifier (with optional function-arg
        // syntax), `{placeholder}`, `VALUES (...)`, `(joinExpr)`
        // (per the grammar's `JoinExprParens` rule — e.g. `FROM (t FINAL)`),
        // or HogQLX (`<Tag ...>`).
        let tab_start = self.peek0.start;
        if self.peek_starts_hogqlx_tag() {
            return self.parse_hogqlx_tag_element();
        }
        if self.peek() == TokenKind::LParen {
            // `(<Tag/>)` is `LPAREN joinExpr RPAREN` per the grammar,
            // where the inner `joinExpr → tableExpr → hogqlxTagElement`.
            // Don't shortcut — fall through to the JoinExprParens path
            // below so the tag gets wrapped in a JoinExpr (which the
            // outer table-atom code refuses to alias) and the inner
            // alias / FINAL / SAMPLE / JOIN decorations on the tag work.
            // Three competing grammar arms when the next token is `(`:
            //
            //   tableExpr: LPAREN selectSetStmt RPAREN  # TableExprSubquery
            //   tableExpr: LPAREN valuesClause RPAREN   # TableExprValues
            //   joinExpr:  LPAREN joinExpr RPAREN       # JoinExprParens
            //
            // ANTLR's ALL(*) tries them in grammar declaration order:
            // tableExpr alternatives first (Subquery before Values),
            // then joinExpr-parens as the fallback. We mirror that
            // with `try_alt` — first parse to a matching close paren
            // wins; failed alts roll back via the parser checkpoint.
            //
            // The previous Pratt-era code used a `peek_paren_wraps_select_stmt`
            // heuristic to commit early; that probe walked balanced parens
            // looking for SELECT/WITH/placeholder markers and could get the
            // call wrong on shapes like `from (a final) sample {x}` (cpp
            // drops the trailing sample as JoinExprParens; the probe would
            // have steered toward TableExprSubquery).
            return self.try_alt(&[
                &Self::parse_table_expr_subquery_arm,
                &Self::parse_table_expr_values_arm,
                &Self::parse_join_expr_parens_arm,
            ]);
        }
        // `{name}` — placeholder table reference (a Dict `{}` / `{k: v}` is not a tableExpr).
        if self.peek() == TokenKind::LBrace {
            return self.parse_brace_placeholder_only();
        }
        // Identifier-led: either a Field chain (plain table reference) or
        // a tableFunction (`name(args)`). Grammar's `tableIdentifier` →
        // `nestedIdentifier` admits `identifier` (`IDENTIFIER |
        // QUOTED_IDENTIFIER | interval | keyword`); the `keyword` rule
        // excludes the same set as `kw_valid_as_identifier`.
        let head = self.bump()?;
        let name = match head.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => {
                identifier_text(self.text(head), head.kind)
            }
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                identifier_text(self.text(head), head.kind)
            }
            TokenKind::Eof => {
                // FROM consumed but no table — surface as a reserved-
                // keyword issue so the Python side raises SyntaxError.
                return Err(ParseError::syntax(
                    "expected table reference after FROM (a reserved keyword cannot be a table name here)",
                    head.start, head.end,
                ));
            }
            _ => return Err(self.err(format!(
                "expected table reference, got {:?} (a reserved keyword cannot be used in this position)",
                head.kind,
            ))),
        };
        // Table function call form `name(args)`. The C++ visitor emits
        // this as a Field with `table_args` populated at the wrapping
        // JoinExpr level — NOT as a Call expression. parse_table_atom
        // picks up the args list off the returned Field.
        if self.peek() == TokenKind::LParen {
            self.bump()?;
            let args = self.parse_arg_list(TokenKind::RParen)?;
            self.expect(TokenKind::RParen, ")")?;
            // Encode as a Field with a sibling "table_args" object so the
            // wrapping JoinExpr in parse_table_atom can pull it out.
            // cpp's `VISIT(TableFunctionExpr)` (parser_json.cpp lines
            // 2797-2817) builds the inner Field WITHOUT calling
            // `addPositionInfo` — only the wrapping JoinExpr carries the
            // span. Emit position-less here too so the deserialised
            // Field's `start` / `end` stay `None`, matching cpp.
            let chain = vec![self.emit.string(&name)];
            let mut field = self.emit.field(chain);
            self.emit
                .set_field(&mut field, "__rust_table_args", self.emit.list_value(args));
            return Ok(self.emit.no_pos(field));
        }
        // Field chain.
        let mut chain: Vec<E::Value> = vec![self.emit.string(&name)];
        while self.peek() == TokenKind::Dot {
            self.bump()?;
            let part = self.bump()?;
            match part.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => {
                    chain.push(
                        self.emit
                            .string(&identifier_text(self.text(part), part.kind)),
                    );
                }
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                    chain.push(
                        self.emit
                            .string(&identifier_text(self.text(part), part.kind)),
                    );
                }
                _ => {
                    return Err(self.err(format!(
                        "expected identifier after '.', got {:?}",
                        part.kind
                    )))
                }
            }
        }
        Ok(self.wrap_pos(self.emit.field(chain), tab_start))
    }

    /// `parse_table_expr` arm: TableExprSubquery, `LPAREN selectSetStmt RPAREN`.
    /// The inner is anything `selectSetStmt` admits — SELECT statements,
    /// WITH-CTE selects, paren-wrapped set-stmts, or a bare placeholder
    /// `{x}` (placeholders are first-class `selectStmtWithParens` arms).
    fn parse_table_expr_subquery_arm(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::LParen, "(")?;
        let inner = self.parse_select_set_stmt()?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(inner)
    }

    /// `parse_table_expr` arm: TableExprValues, `LPAREN valuesClause RPAREN`.
    /// `VALUES` is the first inner token and uniquely identifies this arm,
    /// but we still parse it inside the try_alt so a malformed valuesClause
    /// (e.g. `(VALUES, x)`) rolls back cleanly to the joinExpr fallback.
    fn parse_table_expr_values_arm(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::LParen, "(")?;
        if self.peek() != TokenKind::Keyword(Kw::Values) {
            return Err(self.err("not a VALUES clause"));
        }
        let values = self.parse_values_query()?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(values)
    }

    /// `parse_table_expr` arm: JoinExprParens, `LPAREN joinExpr RPAREN`.
    /// Anything else admissible as a joinExpr — tableIdentifier, FINAL/
    /// sample-decorated tables, JOIN chains. cpp's `JoinExprParens` doesn't
    /// allow trailing FINAL / SAMPLE at the outer level; `parse_table_atom`
    /// distinguishes this case via the returned node's `"JoinExpr"` shape.
    fn parse_join_expr_parens_arm(&mut self) -> Result<E::Value, ParseError> {
        self.expect(TokenKind::LParen, "(")?;
        let inner = self.parse_join_expr()?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(inner)
    }

    /// `VALUES (...), (...)` — a literal-row query usable wherever a table
    /// reference is expected. The caller has already consumed the leading
    /// `(` if any; we consume the `VALUES` keyword and emit a ValuesQuery.
    fn parse_values_query(&mut self) -> Result<E::Value, ParseError> {
        self.expect_kw(Kw::Values, "VALUES")?;
        let mut rows: Vec<E::Value> = Vec::new();
        loop {
            self.expect(TokenKind::LParen, "(")?;
            let row = self.parse_expr_list_until_paren()?;
            self.expect(TokenKind::RParen, ")")?;
            rows.push(self.emit.list_value(row));
            if !self.eat(TokenKind::Comma)? {
                break;
            }
        }
        Ok(self.emit.values_query(rows))
    }

    /// `SAMPLE ratioExpr PERCENT? (OFFSET ratioExpr)? (LPAREN ident RPAREN)?`
    /// — attached to a table reference inside a JoinExpr. Returns None
    /// when no SAMPLE clause is present.
    pub(crate) fn try_consume_sample(&mut self) -> Result<Option<E::Value>, ParseError> {
        if !matches!(self.peek(), TokenKind::Keyword(Kw::Sample)) {
            return Ok(None);
        }
        let sample_start = self.peek0.start;
        self.bump()?;
        let sample_value = self.parse_ratio_expr()?;
        // `PERCENT` would be the `%` token; tolerate but ignore its
        // presence — there's no AST slot for the percent flag.
        let _ = self.eat(TokenKind::Percent)?;
        // OFFSET only belongs to the SAMPLE clause when the following
        // token can start a ratioExpr (`placeholder | numberLiteral`).
        // Otherwise the OFFSET stays for the outer parser — at SELECT
        // level it's the offsetOnlyClause that lands on SelectQuery.offset.
        // ANTLR ALL(*) makes the same split via grammar alternative
        // preference. Note: an `LBrace` only counts as a ratio starter
        // when it's actually a placeholder (`{name}`) — `{}` (empty
        // dict) and `{k: v}` (dict) aren't ratios, so the OFFSET goes
        // to the outer.
        let offset_is_ratio = matches!(self.peek(), TokenKind::Keyword(Kw::Offset))
            && match self.peek_next() {
                TokenKind::Number
                | TokenKind::Plus
                | TokenKind::Dash
                | TokenKind::Dot
                | TokenKind::Keyword(Kw::Inf)
                | TokenKind::Keyword(Kw::Nan) => true,
                TokenKind::LBrace => self.brace_after_offset_is_placeholder(),
                _ => false,
            };
        let offset_value = if offset_is_ratio {
            self.bump()?;
            Some(self.parse_ratio_expr()?)
        } else {
            None
        };
        // `( identifier )` qualifier — also no AST slot, swallow if present.
        if self.peek() == TokenKind::LParen {
            self.bump()?;
            let _ = self.bump()?;
            self.expect(TokenKind::RParen, ")")?;
        }
        let sample = self.emit.sample_expr(sample_value, offset_value);
        Ok(Some(self.wrap_pos(sample, sample_start)))
    }

    /// After a SAMPLE clause has consumed its value and (optional)
    /// PERCENT, decide whether `OFFSET {...}` is the SAMPLE's own
    /// offset (placeholder ratioExpr) or a separate outer
    /// offsetOnlyClause (Dict literal). cpp's ANTLR backtracks based
    /// on whether the `{...}` parses as a placeholder vs Dict; we
    /// peek inside the brace via a shadow lexer.
    fn brace_after_offset_is_placeholder(&self) -> bool {
        // Two tokens after OFFSET (the `{` is at peek1 here). Lex
        // forward from peek1.end to walk the contents of the brace.
        // cpp's `placeholder: LBRACE columnExpr RBRACE` admits any
        // columnExpr inside, but the *Dict* literal `{key: value, ...}`
        // is distinguished by the `:` separator at depth 0 inside the
        // outer brace, and an empty `{}` is the empty Dict. Walk
        // forward tracking paren depth (the outer `{` already counted
        // as depth 1) and decide based on what we see first.
        let mut lex = Lexer::with_pos(self.src, self.peek1.end);
        let mut depth: i32 = 1;
        let mut first = true;
        loop {
            let tok = match lex.next_token() {
                Ok(t) => t,
                Err(_) => return false,
            };
            // Immediate `{}` — empty Dict, not a placeholder.
            if first && tok.kind == TokenKind::RBrace {
                return false;
            }
            first = false;
            match tok.kind {
                TokenKind::LBrace | TokenKind::LParen | TokenKind::LBracket => depth += 1,
                TokenKind::RBrace | TokenKind::RParen | TokenKind::RBracket => {
                    depth -= 1;
                    if depth == 0 {
                        // Closed the outer brace without seeing a
                        // top-level `:` — placeholder.
                        return true;
                    }
                }
                // A `:` at the outer brace's depth marks a Dict
                // key/value separator.
                TokenKind::Colon if depth == 1 => return false,
                TokenKind::Eof => return false,
                _ => {}
            }
        }
    }

    /// Consume a single number-literal value for a `ratioExpr` slot,
    /// handling the trailing-dot float (`5.`) form. parse_prefix's
    /// number path leaves the dot for the Pratt postfix loop, but
    /// ratio context never runs the postfix loop — so a bare `5.`
    /// would leave the `.` stranded. Detect Number-then-bare-Dot and
    /// upgrade to a float Constant in-place.
    fn consume_ratio_value(&mut self) -> Result<E::Value, ParseError> {
        let val_start = self.peek0.start;
        // cpp grammar: `ratioExpr: placeholder | numberLiteral
        // (SLASH numberLiteral)?`. The numerator/denominator side is
        // strictly a `numberLiteral` — not a generic columnExpr. The
        // prior implementation called `parse_prefix()`, which let
        // Fields (`SAMPLE a`), TupleAccess (`SAMPLE x.y`), and
        // placeholder-as-RHS (`1 / {p}`) into the ratio slot.
        //
        // `numberLiteral` is `(PLUS | DASH)? (NULL | NAN | INF |
        // FLOATING_LITERAL | DECIMAL_LITERAL | HEXADECIMAL_LITERAL
        // | OCTAL_PREFIX_LITERAL)`. The parser already collapses signs
        // and special literals into single Number / Constant tokens via
        // `parse_number_literal` (called when the prefix is Number, or
        // an explicit sign + Number combo). Accept those shapes only.
        // numberLiteral: `(PLUS|DASH)? (floatingLiteral|BINARY|OCTAL|
        // OCTAL_PREFIX|DECIMAL|HEXADECIMAL|INF|NAN_SQL)`. INF / NAN are
        // keyword tokens; numeric literals surface as `Number`. The
        // leading-dot float (`.04`) lexes as `Dot` + `Number`, so admit
        // `Dot` when the following token is a Number. NULL is *not* in
        // numberLiteral. Anything else (Field, Call, placeholder-as-RHS,
        // etc.) is a grammar violation.
        match self.peek() {
            TokenKind::Number
            | TokenKind::Plus
            | TokenKind::Dash
            | TokenKind::Keyword(Kw::Nan)
            | TokenKind::Keyword(Kw::Inf) => {}
            TokenKind::Dot if self.peek_next() == TokenKind::Number => {}
            _ => return Err(self.err("SAMPLE ratio value must be a number literal")),
        }
        let mut val = self.parse_prefix()?;
        // Reject non-numeric prefixes (a placeholder masquerading as
        // a `{x}` ratio side, a sign followed by a non-number, etc.).
        let is_numeric_constant = self.emit.node_kind(&val).as_deref() == Some("Constant");
        if !is_numeric_constant {
            return Err(self.err("SAMPLE ratio value must be a number literal"));
        }
        // Trailing dot with no field-chain extender after — turn the
        // integer Constant into a float and consume the dot.
        if self.peek() == TokenKind::Dot
            && !matches!(
                self.peek_next(),
                TokenKind::Number | TokenKind::Ident | TokenKind::QuotedIdent,
            )
        {
            self.bump()?;
            if self.emit.node_kind(&val).as_deref() == Some("Constant") {
                if let Some(n) = self
                    .emit
                    .get_field(&val, "value")
                    .and_then(|v| self.emit.as_i64(&v))
                {
                    let fv = self.emit.float(n as f64);
                    self.emit.set_field(&mut val, "value", fv);
                }
            }
        }
        Ok(self.wrap_pos(val, val_start))
    }

    fn parse_ratio_expr(&mut self) -> Result<E::Value, ParseError> {
        // cpp grammar: `ratioExpr: placeholder | numberLiteral
        // (SLASH numberLiteral)?`. We mirror it narrowly so the
        // trailing `(identifier)` sample qualifier — and an unrelated
        // `OFFSET` ratio — don't get absorbed as a function call on
        // the placeholder. The placeholder branch returns the
        // Placeholder directly (cpp's `VISIT(RatioExpr)` short-circuits
        // and skips the RatioExpr wrapper); the numberLiteral branch
        // wraps in RatioExpr.
        let ratio_start = self.peek0.start;
        if self.peek() == TokenKind::LBrace {
            return self.parse_brace_placeholder_only();
        }
        let left = self.consume_ratio_value()?;
        let right = if self.eat(TokenKind::Slash)? {
            Some(self.consume_ratio_value()?)
        } else {
            None
        };
        let ratio = self.emit.ratio_expr(left, right);
        Ok(self.wrap_pos(ratio, ratio_start))
    }

    /// `<table> PIVOT (aggregates pivotColumnList (GROUP BY exprList)?)`
    /// or `<table> UNPIVOT (INCLUDE NULLS)? (unpivotColumnList)`. Both
    /// decorate the table reference. `tableExpr` is left-recursive
    /// (`tableExpr PIVOT …`), so decorators chain — `t PIVOT (…) UNPIVOT
    /// (…)` nests each decorator's result directly as the next one's
    /// `table` (no per-level `JoinExpr` wrapper; the caller wraps the
    /// whole chain once). Loops until neither keyword follows.
    /// `table_start` is the byte offset where the table expression
    /// preceding the PIVOT / UNPIVOT begins; cpp's `JoinExprPivot` /
    /// `JoinExprUnpivot` ctx covers `tableExpr PIVOT/UNPIVOT (...)`
    /// — span includes that leading table.
    fn try_consume_pivot_unpivot(
        &mut self,
        mut table: E::Value,
        table_start: usize,
    ) -> Result<E::Value, ParseError> {
        loop {
            if matches!(self.peek(), TokenKind::Keyword(Kw::Pivot)) {
                let pivot_start = table_start;
                self.bump()?;
                self.expect(TokenKind::LParen, "(")?;
                let aggregates = self.parse_expr_list_until_terminators_at_for_or_rparen()?;
                // Parse pivotColumnList: `FOR pivotColumn+` where each
                // pivotColumn is `<expr|tuple> IN (cols)`.
                self.expect_kw(Kw::For, "FOR")?;
                let mut columns: Vec<E::Value> = Vec::new();
                loop {
                    let col_expr = self.parse_expr_tuple_or_single(true)?;
                    self.expect_kw(Kw::In, "IN")?;
                    self.expect(TokenKind::LParen, "(")?;
                    // Grammar: `pivotColumn: columnExprTupleOrSingle IN
                    // LPAREN columnExprList RPAREN` — the IN list is
                    // non-empty (`columnExprList: columnExpr (COMMA
                    // columnExpr)* COMMA?`). cpp rejects empty `IN ()`.
                    if self.peek() == TokenKind::RParen {
                        return Err(self.err("PIVOT `IN (…)` list must be non-empty"));
                    }
                    let values = self.parse_expr_list_until_paren()?;
                    self.expect(TokenKind::RParen, ")")?;
                    columns.push(self.emit.pivot_column(col_expr, values));
                    // `pivotColumn+`: keep collecting columns until the
                    // list terminator — the closing `)` or an optional
                    // `GROUP BY`. Anything else begins the next
                    // `columnExprTupleOrSingle`, so it cannot be enumerated
                    // as a fixed token set (a pivotColumn may open with a
                    // number, string, `{placeholder}`, `*`, `(`, …). cpp's
                    // ALL(*) `+` prediction distinguishes a `GROUP BY`
                    // clause from a `group`-keyword Field by the `BY`.
                    if self.peek() == TokenKind::RParen {
                        break;
                    }
                    if matches!(self.peek(), TokenKind::Keyword(Kw::Group))
                        && self.peek_next() == TokenKind::Keyword(Kw::By)
                    {
                        break;
                    }
                }
                // Optional GROUP BY for additional grouping columns.
                // cpp's `(GROUP BY columnExprList)?` requires the list
                // to be non-empty when GROUP BY is present — a bare
                // `GROUP BY)` errors at the trailing paren. Rust's
                // `parse_expr_list_until_paren` returns an empty Vec on
                // `)` immediately, silently accepting; reject explicitly
                // to match cpp.
                let mut group_by: Option<Vec<E::Value>> = None;
                if matches!(self.peek(), TokenKind::Keyword(Kw::Group))
                    && self.peek_next() == TokenKind::Keyword(Kw::By)
                {
                    self.bump()?;
                    self.bump()?;
                    if self.peek() == TokenKind::RParen {
                        return Err(self.err("PIVOT GROUP BY must have at least one expression"));
                    }
                    group_by = Some(self.parse_expr_list_until_paren()?);
                }
                self.expect(TokenKind::RParen, ")")?;
                let pivot = self.emit.pivot_expr(table, aggregates, columns, group_by);
                table = self.wrap_pos(pivot, pivot_start);
                continue;
            }
            if matches!(self.peek(), TokenKind::Keyword(Kw::Unpivot)) {
                let unpivot_start = table_start;
                self.bump()?;
                let include_nulls = matches!(self.peek(), TokenKind::Keyword(Kw::Include))
                    && self.peek_next() == TokenKind::Keyword(Kw::Nulls);
                if include_nulls {
                    self.bump()?;
                    self.bump()?;
                }
                self.expect(TokenKind::LParen, "(")?;
                // `unpivotColumnList: unpivotColumn (COMMA unpivotColumn)* COMMA?`
                // where each `unpivotColumn` is
                //   `tos FOR tos IN ( list ) (tos IN ( list ))*`.
                // The trailing `(tos IN ( list ))*` groups are parsed but
                // dropped — cpp's visitor keeps only the first IN list.
                let mut columns: Vec<E::Value> = Vec::new();
                loop {
                    // value-columns slot is bounded by `FOR`, not a
                    // structural `IN` — no `pivot_in_stop` needed.
                    let value_columns = self.parse_expr_tuple_or_single(false)?;
                    self.expect_kw(Kw::For, "FOR")?;
                    let name_columns = self.parse_expr_tuple_or_single(true)?;
                    self.expect_kw(Kw::In, "IN")?;
                    self.expect(TokenKind::LParen, "(")?;
                    let unpivot_values = self.parse_expr_list_until_paren()?;
                    self.expect(TokenKind::RParen, ")")?;
                    columns.push(self.emit.unpivot_column(
                        value_columns,
                        name_columns,
                        unpivot_values,
                    ));
                    // Additional `tos IN ( list )` groups (no FOR, no
                    // comma) extend the SAME unpivotColumn; they are
                    // discarded to match cpp.
                    while !matches!(self.peek(), TokenKind::RParen | TokenKind::Comma) {
                        self.parse_expr_tuple_or_single(true)?;
                        self.expect_kw(Kw::In, "IN")?;
                        self.expect(TokenKind::LParen, "(")?;
                        self.parse_expr_list_until_paren()?;
                        self.expect(TokenKind::RParen, ")")?;
                    }
                    if !self.eat(TokenKind::Comma)? {
                        break;
                    }
                    if self.peek() == TokenKind::RParen {
                        break; // trailing `COMMA?`
                    }
                }
                self.expect(TokenKind::RParen, ")")?;
                let unpivot = self.emit.unpivot_expr(table, columns, include_nulls);
                table = self.wrap_pos(unpivot, unpivot_start);
                continue;
            }
            return Ok(table);
        }
    }

    /// `( exprList ) | columnExpr` — the `columnExprTupleOrSingle`
    /// operand used in PIVOT/UNPIVOT column slots.
    ///
    /// `columnExprTupleOrSingle: LPAREN columnExprList RPAREN |
    /// columnExpr`. The parenthesised alternative is always a `Tuple`
    /// (even a single element — `(x)` → Tuple([x])), but only when the
    /// matching `)` is the end of the operand, i.e. it is followed by
    /// the `FOR` / `IN` that bounds it. When a postfix instead follows
    /// (`(n)()`), cpp's ALL(*) takes the `columnExpr` alternative — a
    /// parenthesised expression extended by the postfix — so we defer
    /// to the expression parser there.
    ///
    /// The `columnExpr` alternative is parsed at full binding power so
    /// an operand that itself contains infix operators (`x in y`,
    /// `a = b`, `m as x`, …) is captured whole. For a slot bounded by a
    /// structural `IN ( values )` (`in_separated`),
    /// `find_pivot_in_separator` locates that `IN` and `pivot_in_stop`
    /// makes the Pratt `in` handler yield it back instead of consuming
    /// it as an operator. The value-columns slot of an `unpivotColumn`
    /// is bounded by `FOR` instead — never an infix operator — so it
    /// needs no stop.
    fn parse_expr_tuple_or_single(&mut self, in_separated: bool) -> Result<E::Value, ParseError> {
        let op_start = self.peek0.start;
        if self.peek() == TokenKind::LParen && self.paren_group_followed_by_for_or_in() {
            self.bump()?;
            let exprs = self.parse_expr_list_until_paren()?;
            self.expect(TokenKind::RParen, ")")?;
            // cpp's UnpivotColumn / PivotColumn visitors construct a
            // synthetic Tuple (`{node: Tuple, exprs: …}`) without calling
            // `addPositionInfo` (lines 1141-1148 and 1100-1116 of
            // `parser_json.cpp`). The grammar's
            // `columnExprTupleOrSingle: LPAREN columnExprList RPAREN`
            // exists only inside PIVOT/UNPIVOT, so every call to this
            // function lands in one of those slots and the Tuple
            // emission must be position-less to match.
            return Ok(self.emit.tuple_(exprs));
        }
        let stop = if in_separated {
            self.find_pivot_in_separator()
        } else {
            None
        };
        // Single-token operand fallback: when the structural IN is at
        // position peek1 (i.e. directly after the current token), the
        // entire operand is just this one token as a Field. cpp's
        // ANTLR resolves the ambiguous `NOT IN (…)` → `Field([NOT]) IN
        // (…)` here — NOT cannot start a unary expression because the
        // following IN isn't an expression atom, so ANTLR falls back
        // to the bare-identifier alt. Any keyword that's a valid
        // `identifier` (e.g. NOT / SELECT / IF / NULLS / …) lands
        // here; plain Ident / QuotedIdent already parse single-token
        // via parse_ident_lead and don't need the early return.
        if let Some(stop_pos) = stop {
            if stop_pos == self.peek1.start
                && matches!(self.peek(), TokenKind::Keyword(kw) if kw_valid_as_identifier(kw))
            {
                let t = self.bump()?;
                let name = identifier_text(self.text(t), t.kind);
                return Ok(self.wrap_pos(self.emit.field(vec![self.emit.string(&name)]), op_start));
            }
        }
        let prev = std::mem::replace(&mut self.pivot_in_stop, stop);
        let result = self.parse_expr_bp(0);
        self.pivot_in_stop = prev;
        result
    }

    /// Scan the upcoming `columnExprTupleOrSingle` operand and return
    /// the byte offset of the structural `IN` that separates it from
    /// its `( values )` list: the *first* depth-0 `IN` immediately
    /// followed by `(`, before the operand's `FOR` / `)` / `,`
    /// terminator. `None` when no such `IN` exists (a malformed slot;
    /// the caller's `expect_kw(In)` then reports it).
    ///
    /// "First `IN (`" is the structural one because the `pivotColumn`
    /// rule (`columnExprTupleOrSingle IN LPAREN … RPAREN`) ends right
    /// after that list — a following `colN IN ( … )` is the *next*
    /// `pivotColumn`. An operand-internal `x IN y` (with `y` not a
    /// `(`) is skipped, so `n IN p IN (r)` still splits as operand
    /// `n IN p` + separator `IN (r)`. The one shape this mis-splits is
    /// an operand whose own value is an `IN ( list )` *operator*
    /// expression (`x IN (1,2) IN (r)`) — vanishingly rare, and
    /// already rejected before this fix.
    fn find_pivot_in_separator(&self) -> Option<usize> {
        // Find the structural `IN` of this pivotColumn.
        //
        // cpp's ANTLR ALL(*) greedy-consumes the LHS
        // `columnExprTupleOrSingle` (a full `columnExpr`, which admits
        // nested `... IN (...)` operator expressions AND postfix
        // `(...)` calls on whatever it's already built). The structural
        // `IN` is the LAST depth-0 `IN (` whose closing `)` is NOT
        // followed by another token that could extend the LHS via an
        // infix operator OR a postfix decoration. Any such token means
        // the columnExpr keeps growing past this `IN ( … )` group.
        //
        // Extension tokens: postfix `(` / `[` / `.` / `?.`,
        // arithmetic / comparison / regex infix tokens, And / Or / In
        // / Is / Like / Ilike / Between / As keywords, `??`, `::`.
        // `Not` is intentionally NOT in the set: it's a prefix
        // operator, so a leading `NOT` starts a new operand. Bare
        // identifiers / literals / placeholders / `*`-as-spread also
        // start a new operand (commit the IN as structural).
        //
        // `y IN (1) (2) IN (3)` is one pivotColumn:
        //   IN1 = `IN (1)` followed by `(2)` (postfix call); LHS extends.
        //   IN2 = `IN (3)` followed by `)` (end); structural. ✓
        //
        // `a IN (1) IN (2)` is one pivotColumn:
        //   IN1 = `IN (1)` followed by `IN` (Compare infix); LHS extends.
        //   IN2 = `IN (2)` followed by `)`; structural. ✓
        //
        // `a IN (1) b IN (2)` is two pivotColumns:
        //   IN1 = `IN (1)` followed by `b` (new LHS); structural. ✓
        //
        // `a IN (1) NOT IN (2)` is two pivotColumns:
        //   IN1 = `IN (1)` followed by `NOT` (prefix); structural. ✓
        //   IN2 = `IN (2)` is the second column's separator. ✓
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let mut depth: i32 = 0;
        let mut pending_in: Option<usize> = None;
        // After an `IN ( ... )` group closes, this state holds the
        // start-pos of the candidate IN until we see the *next* token
        // and decide whether it's a postfix `(` (extends LHS) or
        // anything else (commits the IN as structural).
        let mut candidate_after_close: Option<usize> = None;
        while let Ok(tok) = probe.next_token() {
            if let Some(in_pos) = candidate_after_close.take() {
                if !token_extends_pivot_column_lhs(tok.kind) {
                    return Some(in_pos);
                }
                // The IN ( … ) group is followed by something that
                // extends the LHS (postfix call / array / dot, or
                // any infix operator / keyword that takes a LHS).
                // Keep scanning for a later structural IN. Fall
                // through to the normal token handling so we keep
                // tracking depth via `LParen` / `LBracket` / `LBrace`.
            }
            if let Some(in_pos) = pending_in.take() {
                if tok.kind == TokenKind::LParen {
                    // Found `IN (`; we'll commit it as structural when
                    // the matching `)` closes AND the following token
                    // isn't another `(`.
                    depth += 1;
                    // Scan to matching close.
                    while depth > 0 {
                        let inner = match probe.next_token() {
                            Ok(t) => t,
                            Err(_) => return None,
                        };
                        match inner.kind {
                            TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => {
                                depth += 1
                            }
                            TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                                depth -= 1
                            }
                            TokenKind::Eof => return None,
                            _ => {}
                        }
                    }
                    candidate_after_close = Some(in_pos);
                    continue;
                }
            }
            match tok.kind {
                TokenKind::LParen | TokenKind::LBracket | TokenKind::LBrace => depth += 1,
                TokenKind::RParen | TokenKind::RBracket | TokenKind::RBrace => {
                    if depth == 0 {
                        break;
                    }
                    depth -= 1;
                }
                TokenKind::Comma if depth == 0 => break,
                TokenKind::Keyword(Kw::For) if depth == 0 => break,
                TokenKind::Keyword(Kw::In) if depth == 0 => pending_in = Some(tok.start),
                TokenKind::Eof => break,
                _ => {}
            }
        }
        // Reached end of pivotColumn body. If the most-recent IN-(...)
        // group has no follow-on `(`, commit it.
        candidate_after_close
    }

    /// `self.peek()` is `(` — scan to its matching `)` and report
    /// whether a `FOR` / `IN` keyword immediately follows it.
    fn paren_group_followed_by_for_or_in(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.end);
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
                        let after = probe.next_token().map(|t| t.kind).unwrap_or(TokenKind::Eof);
                        return matches!(
                            after,
                            TokenKind::Keyword(Kw::For) | TokenKind::Keyword(Kw::In)
                        );
                    }
                }
                TokenKind::Eof => return false,
                _ => {}
            }
        }
    }

    /// Like parse_expr_list_until_terminators, but also stops at `FOR`
    /// (used inside PIVOT to separate aggregate list from the column
    /// spec). Comma-separated.
    fn parse_expr_list_until_terminators_at_for_or_rparen(
        &mut self,
    ) -> Result<Vec<E::Value>, ParseError> {
        let mut out = Vec::new();
        loop {
            out.push(self.parse_expr_bp(0)?);
            if !self.eat(TokenKind::Comma)? {
                break;
            }
            if matches!(self.peek(), TokenKind::Keyword(Kw::For))
                || self.peek() == TokenKind::RParen
            {
                break;
            }
        }
        Ok(out)
    }
}

/// `true` when `kind` can extend the LHS columnExpr of a pivotColumn
/// past a preceding `IN ( … )` group — either a postfix decoration
/// (`(...)`, `[...]`, `.x`, `?.x`) or an infix operator that takes a
/// LHS. cpp's ANTLR ALL(*) keeps eating tokens into the LHS as long
/// as one of these follows; the structural `IN` of the pivotColumn is
/// the LAST one whose closing `)` is NOT followed by an extender. A
/// `NOT` (prefix), bare identifier, literal, placeholder, top-level
/// `*` (spread asterisk), or `,` / `)` / `FOR` / `GROUP BY` instead
/// commits the IN as structural.
fn token_extends_pivot_column_lhs(kind: TokenKind) -> bool {
    matches!(
        kind,
        TokenKind::LParen
            | TokenKind::LBracket
            | TokenKind::Dot
            | TokenKind::NullProperty
            | TokenKind::DoubleColon
            | TokenKind::Asterisk
            | TokenKind::Slash
            | TokenKind::Percent
            | TokenKind::Plus
            | TokenKind::Dash
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
            | TokenKind::Keyword(
                Kw::And | Kw::Or | Kw::In | Kw::Is | Kw::Like | Kw::Ilike | Kw::Between | Kw::As,
            )
    )
}

/// Walk a JOIN chain (the outermost `JoinExpr`'s `next_join` linked
/// list) inward-to-outward, looking for the FIRST `JoinExpr` along
/// the way whose `constraint` is missing / null, and attach the given
/// constraint there. Returns `true` on success, `false` when every
/// level already has a constraint.
///
/// "Inward-to-outward" because cpp's right-associative join parse for
/// `a JOIN b JOIN c ON1 ON2` puts ON1 on the innermost (`c`) and ON2
/// on the next outer (`b`). The first stranded ON attaches inward
/// (after the loop's left-to-right pass already placed one on the
/// deepest JoinExpr); the second moves outward; etc.
/// `min_attachable_depth` is the chain depth at which scope-local joins begin
/// (one past the lead's pre-existing chain). Nodes shallower than that
/// belong to a parens-wrapped inner scope and are opaque — we recurse
/// through them but never attach.
/// Returns `(node, attached)` — `node` is the (possibly updated) input,
/// `attached` is true iff the constraint was placed.
fn attach_constraint_to_outermost_unconstrained_join<E: Emitter>(
    emit: &E,
    mut node: E::Value,
    constraint: E::Value,
    min_attachable_depth: usize,
    current_depth: usize,
) -> (E::Value, bool) {
    if emit.node_kind(&node).as_deref() != Some("JoinExpr") {
        return (node, false);
    }
    // Try recursing into next_join first.
    if let Some(nj) = emit.get_field(&node, "next_join") {
        if emit.node_kind(&nj).is_some() {
            let (updated, attached) = attach_constraint_to_outermost_unconstrained_join(
                emit,
                nj,
                constraint.clone(),
                min_attachable_depth,
                current_depth + 1,
            );
            emit.set_field(&mut node, "next_join", updated);
            if attached {
                return (node, true);
            }
        }
    }
    if current_depth < min_attachable_depth {
        return (node, false);
    }
    let join_type = emit
        .get_field(&node, "join_type")
        .and_then(|v| emit.as_str(&v).map(|s| s.into_owned()));
    let accepts_constraint = matches!(join_type.as_deref(), Some(jt) if jt != "CROSS JOIN");
    if !accepts_constraint {
        return (node, false);
    }
    let existing = emit.get_field(&node, "constraint");
    let is_unset = existing.as_ref().map(|v| emit.is_null(v)).unwrap_or(true);
    if is_unset {
        emit.set_field(&mut node, "constraint", constraint);
        return (node, true);
    }
    (node, false)
}

/// Count JoinExprs linked via `next_join`. Lead is depth 1.
fn chain_depth<E: Emitter>(emit: &E, node: &E::Value) -> usize {
    let mut depth = 1;
    let mut cursor: E::Value = node.clone();
    loop {
        let nj = emit.get_field(&cursor, "next_join");
        match nj {
            Some(v) if emit.node_kind(&v).is_some() => {
                depth += 1;
                cursor = v;
            }
            _ => break,
        }
    }
    depth
}
