//! `FROM` clause + JOIN chain parsing.
//!
//! Covers everything from the `tableExpr` leaf up through the
//! left-recursive `joinExpr` chain, including the table-function
//! sentinel, PIVOT/UNPIVOT decoration, and the `SAMPLE … OFFSET …`
//! qualifier. ARRAY JOIN is *not* here — it belongs to the SELECT
//! statement (see `parse_select_stmt_body` in `select.rs`).

use serde_json::{json, Value};

use super::{chain_join, identifier_text, kw_valid_as_identifier, Parser, BP_COMPARE};
use crate::emit;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, TokenKind};

impl<'a> Parser<'a> {
    pub(crate) fn parse_join_expr(&mut self) -> Result<Value, ParseError> {
        // Left-recursive in the grammar; iterate, chaining each new
        // right-side table into the previous JoinExpr's `next_join` field.
        let mut left = self.parse_table_atom()?;
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
            // `,` cross join.
            if self.eat(TokenKind::Comma)? {
                let right = self.parse_table_atom()?;
                left = chain_join(left, right, "CROSS JOIN", None);
                joined_any = true;
                continue;
            }
            // CROSS JOIN explicit.
            if matches!(self.peek(), TokenKind::Keyword(Kw::Cross))
                && self.peek_next() == TokenKind::Keyword(Kw::Join)
            {
                self.bump()?;
                self.bump()?;
                let right = self.parse_table_atom()?;
                left = chain_join(left, right, "CROSS JOIN", None);
                joined_any = true;
                continue;
            }
            // POSITIONAL JOIN.
            if matches!(self.peek(), TokenKind::Keyword(Kw::Positional))
                && self.peek_next() == TokenKind::Keyword(Kw::Join)
            {
                self.bump()?;
                self.bump()?;
                let right = self.parse_table_atom()?;
                let constraint = self.parse_join_constraint_opt()?;
                left = chain_join(left, right, "POSITIONAL JOIN", constraint);
                joined_any = true;
                continue;
            }
            // [NATURAL]? [SEMI|ANTI|ALL|ANY|ASOF]? [INNER|LEFT|RIGHT|FULL [OUTER]?]? JOIN target.
            let _natural = self.eat_kw(Kw::Natural)?;
            let join_op = self.try_consume_join_op()?;
            if join_op.is_none() && !matches!(self.peek(), TokenKind::Keyword(Kw::Join)) {
                break;
            }
            let op_text = join_op.unwrap_or_default();
            self.expect_kw(Kw::Join, "JOIN")?;
            let right = self.parse_table_atom()?;
            let constraint = self.parse_join_constraint_opt()?;
            let join_type = if op_text.is_empty() {
                "JOIN".to_string()
            } else {
                format!("{op_text} JOIN")
            };
            left = chain_join(left, right, &join_type, constraint);
            joined_any = true;
        }

        // PIVOT/UNPIVOT decorates the entire chain. For the single-atom
        // case (no JOIN happened), the chain is a JoinExpr that only
        // wraps a bare Field — unwrap to match the C++ shape where the
        // PivotExpr's `table` is the bare Field. When the JoinExpr carries
        // an alias / final / sample / column_aliases, we keep it as is
        // since that decoration belongs *inside* the PIVOT.
        if matches!(
            self.peek(),
            TokenKind::Keyword(Kw::Pivot) | TokenKind::Keyword(Kw::Unpivot)
        ) {
            let pivot_input = if joined_any {
                left
            } else if let Some(obj) = left.as_object() {
                let has_decorations = obj.keys().any(|k| k != "node" && k != "table");
                if has_decorations {
                    left
                } else {
                    obj.get("table").cloned().unwrap_or(left)
                }
            } else {
                left
            };
            let wrapped = self.try_consume_pivot_unpivot(pivot_input)?;
            // Wrap the PivotExpr/UnpivotExpr in an outer JoinExpr (the C++
            // visitor's JoinExprPivot does the same).
            let mut outer = serde_json::Map::new();
            outer.insert("node".into(), Value::String("JoinExpr".into()));
            outer.insert("table".into(), wrapped);
            // `tableExpr PIVOT (...)` is itself a `tableExpr`, so the
            // `JoinExprTable: tableExpr FINAL? sampleClause?` wrapper can
            // still decorate it — `FROM (t PIVOT (...) FINAL)`. cpp puts
            // `table_final` / `sample` on this outer JoinExpr.
            if self.eat_kw(Kw::Final)? {
                outer.insert("table_final".into(), Value::Bool(true));
            }
            if let Some(s) = self.try_consume_sample()? {
                outer.insert("sample".into(), s);
            }
            return Ok(Value::Object(outer));
        }
        Ok(left)
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
        loop {
            let TokenKind::Keyword(kw) = self.peek() else {
                break;
            };
            if !candidates.contains(&kw) {
                break;
            }
            self.bump()?;
            seen_any_kw = true;
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
        }
        if !seen_any_kw {
            return Ok(None);
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

    fn parse_join_constraint_opt(&mut self) -> Result<Option<Value>, ParseError> {
        if self.eat_kw(Kw::On)? {
            let expr = self.parse_expr_bp(0)?;
            return Ok(Some(
                json!({"node": "JoinConstraint", "expr": expr, "constraint_type": "ON"}),
            ));
        }
        if self.eat_kw(Kw::Using)? {
            // The grammar allows both parenthesised and bare lists.
            let exprs = if self.eat(TokenKind::LParen)? {
                let list = self.parse_expr_list_until_paren()?;
                self.expect(TokenKind::RParen, ")")?;
                list
            } else {
                self.parse_expr_list_until_terminators()?
            };
            let expr = if exprs.len() == 1 {
                exprs.into_iter().next().unwrap()
            } else {
                emit::tuple_(exprs)
            };
            return Ok(Some(
                json!({"node": "JoinConstraint", "expr": expr, "constraint_type": "USING"}),
            ));
        }
        Ok(None)
    }

    fn parse_table_atom(&mut self) -> Result<Value, ParseError> {
        let mut table_expr = self.parse_table_expr()?;
        // `(joinExpr)` per the grammar's `JoinExprParens` returns an
        // already-wrapped JoinExpr (or chain). FINAL / sample don't
        // apply at this level (they're inside the parens), but cpp's
        // `VISIT(TableExprAlias)` injects the outer alias straight onto
        // the existing JoinExpr — `(a JOIN b) AS x` lands `alias: "x"`
        // on the root JoinExpr of the chain. Mirror that.
        let already_join_expr = table_expr.get("node").and_then(Value::as_str) == Some("JoinExpr");
        if already_join_expr {
            // Reached here only via the JoinExprParens arm of
            // `parse_table_expr` (`LPAREN joinExpr RPAREN`). cpp's grammar
            // doesn't admit trailing FINAL / SAMPLE on JoinExprParens —
            // those fall through to the SELECT-level silent-drop. The
            // TableExprSubquery arm (which DOES allow trailing FINAL /
            // SAMPLE, e.g. `({x}) sample 0.5`) returns a non-JoinExpr
            // (Placeholder / SelectQuery / SelectSetQuery) and lands in
            // the bottom branch below.
            //
            // Alias still attaches here — `(a JOIN b) AS x` is cpp's
            // accepted shape even though the strict grammar reads it
            // through a separate TableExprAlias rule.
            let (alias, column_aliases) = self.consume_table_alias_chain()?;
            if let Some(obj) = table_expr.as_object_mut() {
                if let Some(a) = alias {
                    obj.insert("alias".into(), Value::String(a));
                }
                if let Some(ca) = column_aliases {
                    obj.insert(
                        "column_aliases".into(),
                        Value::Array(ca.into_iter().map(Value::String).collect()),
                    );
                }
            }
            return Ok(table_expr);
        }
        // parse_table_expr signals table-function args via a sentinel key
        // on the returned Field — extract them into `table_args` so the
        // JoinExpr wrapper gets the C++-shape Field + table_args split.
        let table_args = table_expr
            .as_object_mut()
            .and_then(|m| m.remove("__rust_table_args"));
        // Grammar order: `TableExprAlias` is `tableExpr (alias | AS
        // identifier) columnAliases?` — the alias and column-aliases
        // bind *inside* `tableExpr` — and `JoinExprTable` then
        // decorates it with `FINAL? sampleClause?`. So the alias comes
        // first, FINAL and SAMPLE after. Parsing SAMPLE before the
        // alias (as this did) silently dropped the sample on an
        // aliased table — `t AS e SAMPLE 1` lost its `SampleExpr`.
        let (alias, column_aliases) = self.consume_table_alias_chain()?;
        // `JoinExprTable: tableExpr FINAL? sampleClause?` — FINAL and
        // SAMPLE decorate the (possibly aliased) table.
        let final_ = self.eat_kw(Kw::Final)?;
        let sample = self.try_consume_sample()?;

        // PIVOT/UNPIVOT detection is done at the parse_join_expr level so
        // that the wrapping applies to a whole JOIN chain rather than to
        // each individual atom — `FROM a JOIN b PIVOT (...)` wraps the
        // entire `a JOIN b`, not just `b`. parse_table_atom only handles
        // the immediate table + its alias / sample / final decoration.
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("JoinExpr".into()));
        obj.insert("table".into(), table_expr);
        if let Some(ta) = table_args {
            obj.insert("table_args".into(), ta);
        }
        if let Some(a) = alias {
            obj.insert("alias".into(), Value::String(a));
        }
        if final_ {
            obj.insert("table_final".into(), Value::Bool(true));
        }
        if let Some(s) = sample {
            obj.insert("sample".into(), s);
        }
        if let Some(ca) = column_aliases {
            obj.insert(
                "column_aliases".into(),
                Value::Array(ca.into_iter().map(Value::String).collect()),
            );
        }
        Ok(Value::Object(obj))
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
    ) -> Result<(Option<String>, Option<Vec<String>>), ParseError> {
        let mut alias: Option<String> = None;
        let mut column_aliases: Option<Vec<String>> = None;
        while let Some(a) = self.try_consume_table_alias()? {
            alias = Some(a);
            // `columnAliases` belongs to *this* alias's `TableExprAlias`;
            // re-read each iteration so the last alias's value (present
            // or absent) is the one that survives.
            column_aliases = self.try_consume_column_aliases()?;
        }
        Ok((alias, column_aliases))
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
        let mut cols = Vec::new();
        if self.peek() != TokenKind::RParen {
            loop {
                let t = self.bump()?;
                cols.push(identifier_text(self.text(t), t.kind));
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RParen {
                    break;
                }
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
            return Ok(Some(name));
        }
        // Bare (no `AS`) alias — the grammar's `alias` rule:
        // `IDENTIFIER | QUOTED_IDENTIFIER | keywordForAlias`, where
        // `keywordForAlias` is the small DATE / FIRST / ID / KEY set
        // (none of which is a JOIN op or clause keyword, so consuming
        // one here is unambiguous).
        match self.peek() {
            TokenKind::Ident | TokenKind::QuotedIdent => {
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

    fn parse_table_expr(&mut self) -> Result<Value, ParseError> {
        // `(selectSet)`, table identifier (with optional function-arg
        // syntax), `{placeholder}`, `VALUES (...)`, `(joinExpr)`
        // (per the grammar's `JoinExprParens` rule — e.g. `FROM (t FINAL)`),
        // or HogQLX (`<Tag ...>`).
        if self.peek_starts_hogqlx_tag() {
            return self.parse_hogqlx_tag_element();
        }
        if self.peek() == TokenKind::LParen {
            // Before the standard tableExpr-paren alts: `(<Tag />)` is
            // the paren-wrapped HogQLX form. Probe via checkpoint —
            // if the inner is a tag, consume it + the closing paren
            // and return; otherwise restore and fall through to the
            // try_alt below.
            if self.peek_next() == TokenKind::Lt {
                let cp = self.checkpoint();
                self.bump()?; // `(`
                if self.peek_starts_hogqlx_tag() {
                    let tag = self.parse_hogqlx_tag_element()?;
                    self.expect(TokenKind::RParen, ")")?;
                    return Ok(tag);
                }
                self.restore(cp)?;
            }
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
        // `{name}` — placeholder table reference.
        if self.peek() == TokenKind::LBrace {
            return self.parse_brace_dict_or_placeholder();
        }
        // Identifier-led: either a Field chain (plain table reference) or
        // a tableFunction (`name(args)`).
        let head = self.bump()?;
        let name = match head.kind {
            TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
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
            return Ok(json!({
                "node": "Field",
                "chain": [name],
                "__rust_table_args": args,
            }));
        }
        // Field chain.
        let mut chain: Vec<Value> = vec![Value::String(name)];
        while self.peek() == TokenKind::Dot {
            self.bump()?;
            let part = self.bump()?;
            match part.kind {
                TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_) => {
                    chain.push(Value::String(identifier_text(self.text(part), part.kind)));
                }
                _ => {
                    return Err(self.err(format!(
                        "expected identifier after '.', got {:?}",
                        part.kind
                    )))
                }
            }
        }
        Ok(emit::field(chain))
    }

    /// `parse_table_expr` arm: TableExprSubquery, `LPAREN selectSetStmt RPAREN`.
    /// The inner is anything `selectSetStmt` admits — SELECT statements,
    /// WITH-CTE selects, paren-wrapped set-stmts, or a bare placeholder
    /// `{x}` (placeholders are first-class `selectStmtWithParens` arms).
    fn parse_table_expr_subquery_arm(&mut self) -> Result<Value, ParseError> {
        self.expect(TokenKind::LParen, "(")?;
        let inner = self.parse_select_set_stmt()?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(inner)
    }

    /// `parse_table_expr` arm: TableExprValues, `LPAREN valuesClause RPAREN`.
    /// `VALUES` is the first inner token and uniquely identifies this arm,
    /// but we still parse it inside the try_alt so a malformed valuesClause
    /// (e.g. `(VALUES, x)`) rolls back cleanly to the joinExpr fallback.
    fn parse_table_expr_values_arm(&mut self) -> Result<Value, ParseError> {
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
    fn parse_join_expr_parens_arm(&mut self) -> Result<Value, ParseError> {
        self.expect(TokenKind::LParen, "(")?;
        let inner = self.parse_join_expr()?;
        self.expect(TokenKind::RParen, ")")?;
        Ok(inner)
    }

    /// `VALUES (...), (...)` — a literal-row query usable wherever a table
    /// reference is expected. The caller has already consumed the leading
    /// `(` if any; we consume the `VALUES` keyword and emit a ValuesQuery.
    fn parse_values_query(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::Values, "VALUES")?;
        let mut rows: Vec<Value> = Vec::new();
        loop {
            self.expect(TokenKind::LParen, "(")?;
            let row = self.parse_expr_list_until_paren()?;
            self.expect(TokenKind::RParen, ")")?;
            rows.push(Value::Array(row));
            if !self.eat(TokenKind::Comma)? {
                break;
            }
        }
        Ok(json!({"node": "ValuesQuery", "rows": rows}))
    }

    /// `SAMPLE ratioExpr PERCENT? (OFFSET ratioExpr)? (LPAREN ident RPAREN)?`
    /// — attached to a table reference inside a JoinExpr. Returns None
    /// when no SAMPLE clause is present.
    pub(crate) fn try_consume_sample(&mut self) -> Result<Option<Value>, ParseError> {
        if !matches!(self.peek(), TokenKind::Keyword(Kw::Sample)) {
            return Ok(None);
        }
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
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("SampleExpr".into()));
        obj.insert("sample_value".into(), sample_value);
        if let Some(o) = offset_value {
            obj.insert("offset_value".into(), o);
        }
        Ok(Some(Value::Object(obj)))
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
    fn consume_ratio_value(&mut self) -> Result<Value, ParseError> {
        let mut val = self.parse_prefix()?;
        // Trailing dot with no field-chain extender after — turn the
        // integer Constant into a float and consume the dot.
        if self.peek() == TokenKind::Dot
            && !matches!(
                self.peek_next(),
                TokenKind::Number | TokenKind::Ident | TokenKind::QuotedIdent,
            )
        {
            self.bump()?;
            if let Some(obj) = val.as_object_mut() {
                if obj.get("node").and_then(Value::as_str) == Some("Constant") {
                    if let Some(n) = obj.get("value").and_then(Value::as_i64) {
                        obj.insert("value".into(), serde_json::json!(n as f64));
                    }
                }
            }
        }
        Ok(val)
    }

    fn parse_ratio_expr(&mut self) -> Result<Value, ParseError> {
        // cpp grammar: `ratioExpr: placeholder | numberLiteral
        // (SLASH numberLiteral)?`. We mirror it narrowly so the
        // trailing `(identifier)` sample qualifier — and an unrelated
        // `OFFSET` ratio — don't get absorbed as a function call on
        // the placeholder. The placeholder branch returns the
        // Placeholder directly (cpp's `VISIT(RatioExpr)` short-circuits
        // and skips the RatioExpr wrapper); the numberLiteral branch
        // wraps in RatioExpr.
        if self.peek() == TokenKind::LBrace {
            return self.parse_brace_dict_or_placeholder();
        }
        let left = self.consume_ratio_value()?;
        let right = if self.eat(TokenKind::Slash)? {
            Some(self.consume_ratio_value()?)
        } else {
            None
        };
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("RatioExpr".into()));
        obj.insert("left".into(), left);
        if let Some(r) = right {
            obj.insert("right".into(), r);
        }
        Ok(Value::Object(obj))
    }

    /// `<table> PIVOT (aggregates pivotColumnList (GROUP BY exprList)?)`
    /// or `<table> UNPIVOT (INCLUDE NULLS)? (unpivotColumnList)`. Both
    /// decorate the table reference. `tableExpr` is left-recursive
    /// (`tableExpr PIVOT …`), so decorators chain — `t PIVOT (…) UNPIVOT
    /// (…)` nests each decorator's result directly as the next one's
    /// `table` (no per-level `JoinExpr` wrapper; the caller wraps the
    /// whole chain once). Loops until neither keyword follows.
    fn try_consume_pivot_unpivot(&mut self, mut table: Value) -> Result<Value, ParseError> {
        loop {
            if matches!(self.peek(), TokenKind::Keyword(Kw::Pivot)) {
                self.bump()?;
                self.expect(TokenKind::LParen, "(")?;
                let aggregates = self.parse_expr_list_until_terminators_at_for_or_rparen()?;
                // Parse pivotColumnList: `FOR pivotColumn+` where each
                // pivotColumn is `<expr|tuple> IN (cols)`.
                self.expect_kw(Kw::For, "FOR")?;
                let mut columns: Vec<Value> = Vec::new();
                loop {
                    let col_expr = self.parse_expr_tuple_or_single()?;
                    self.expect_kw(Kw::In, "IN")?;
                    self.expect(TokenKind::LParen, "(")?;
                    let values = self.parse_expr_list_until_paren()?;
                    self.expect(TokenKind::RParen, ")")?;
                    columns.push(json!({
                        "node": "PivotColumn",
                        "column": col_expr,
                        "values": values,
                    }));
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
                let mut group_by: Option<Vec<Value>> = None;
                if matches!(self.peek(), TokenKind::Keyword(Kw::Group))
                    && self.peek_next() == TokenKind::Keyword(Kw::By)
                {
                    self.bump()?;
                    self.bump()?;
                    group_by = Some(self.parse_expr_list_until_paren()?);
                }
                self.expect(TokenKind::RParen, ")")?;
                let mut obj = serde_json::Map::new();
                obj.insert("node".into(), Value::String("PivotExpr".into()));
                obj.insert("table".into(), table);
                obj.insert("aggregates".into(), Value::Array(aggregates));
                obj.insert("columns".into(), Value::Array(columns));
                if let Some(g) = group_by {
                    obj.insert("group_by".into(), Value::Array(g));
                }
                table = Value::Object(obj);
                continue;
            }
            if matches!(self.peek(), TokenKind::Keyword(Kw::Unpivot)) {
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
                let mut columns: Vec<Value> = Vec::new();
                loop {
                    let value_columns = self.parse_expr_tuple_or_single()?;
                    self.expect_kw(Kw::For, "FOR")?;
                    let name_columns = self.parse_expr_tuple_or_single()?;
                    self.expect_kw(Kw::In, "IN")?;
                    self.expect(TokenKind::LParen, "(")?;
                    let unpivot_values = self.parse_expr_list_until_paren()?;
                    self.expect(TokenKind::RParen, ")")?;
                    columns.push(json!({
                        "node": "UnpivotColumn",
                        "value_columns": value_columns,
                        "name_columns": name_columns,
                        "unpivot_values": unpivot_values,
                    }));
                    // Additional `tos IN ( list )` groups (no FOR, no
                    // comma) extend the SAME unpivotColumn; they are
                    // discarded to match cpp.
                    while !matches!(self.peek(), TokenKind::RParen | TokenKind::Comma) {
                        self.parse_expr_tuple_or_single()?;
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
                let mut obj = serde_json::Map::new();
                obj.insert("node".into(), Value::String("UnpivotExpr".into()));
                obj.insert("table".into(), table);
                obj.insert("columns".into(), Value::Array(columns));
                if include_nulls {
                    obj.insert("include_nulls".into(), Value::Bool(true));
                }
                table = Value::Object(obj);
                continue;
            }
            return Ok(table);
        }
    }

    /// `( exprList ) | columnExpr` — used in PIVOT/UNPIVOT column slots.
    /// Parsed at a binding power above `IN` so the mandatory PIVOT `IN
    /// (values)` keyword isn't consumed as a comparison operator on the
    /// expression that precedes it.
    fn parse_expr_tuple_or_single(&mut self) -> Result<Value, ParseError> {
        if self.peek() == TokenKind::LParen {
            self.bump()?;
            let exprs = self.parse_expr_list_until_paren()?;
            self.expect(TokenKind::RParen, ")")?;
            return Ok(if exprs.len() == 1 {
                exprs.into_iter().next().unwrap()
            } else {
                emit::tuple_(exprs)
            });
        }
        self.parse_expr_bp(BP_COMPARE + 1)
    }

    /// Like parse_expr_list_until_terminators, but also stops at `FOR`
    /// (used inside PIVOT to separate aggregate list from the column
    /// spec). Comma-separated.
    fn parse_expr_list_until_terminators_at_for_or_rparen(
        &mut self,
    ) -> Result<Vec<Value>, ParseError> {
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
