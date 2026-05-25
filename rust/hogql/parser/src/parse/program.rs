//! Hog program-statement parsing — the imperative-language layer
//! built on top of the HogQL expression grammar.
//!
//! Grammar (HogQLParser.g4):
//!
//!   program     : declaration* EOF
//!   declaration : varDecl | statement
//!   varDecl     : LET ident (':=' expression)?
//!   statement   : returnStmt | throwStmt | tryCatchStmt | ifStmt
//!               | whileStmt | forInStmt | forStmt | funcStmt
//!               | varAssignment | block | exprStmt | emptyStmt
//!   block       : '{' declaration* '}'
//!
//! AST shapes (cpp parity, dropping start/end / null defaults):
//!   - VariableDeclaration { name, expr }
//!   - VariableAssignment { left, right }
//!   - ExprStatement { expr }
//!   - IfStatement { expr, then, else_ }
//!   - WhileStatement { expr, body }
//!   - ForStatement { initializer, condition, increment, body }
//!   - ForInStatement { keyVar, valueVar, expr, body }
//!   - Function { name, params: [str], body: Block }
//!   - ReturnStatement { expr }
//!   - ThrowStatement { expr }
//!   - TryCatchStatement { try_stmt, catches: [[var, type|null, block], ...], finally_stmt }
//!   - Block { declarations: [decl, ...] }
//!   - Program { declarations: [decl, ...] }

use serde_json::{json, Value};

use super::expr::is_pure_infix_op;
use super::{identifier_text, kw_valid_as_identifier, Parser};
use crate::emit;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, TokenKind};

impl<'a> Parser<'a> {
    pub(crate) fn parse_program(&mut self) -> Result<Value, ParseError> {
        let prog_start = self.peek0.start;
        let mut declarations: Vec<Value> = Vec::new();
        while !matches!(self.peek(), TokenKind::Eof) {
            // Empty statement (a stray `;`) is a no-op — skip it
            // without producing a declaration so the AST stays clean.
            if self.peek() == TokenKind::Semicolon {
                self.bump()?;
                continue;
            }
            declarations.push(self.parse_declaration()?);
        }
        // cpp's `VISIT(Program)` calls `addPositionInfo(json, ctx)`, and
        // ANTLR's Program ctx ends at the EOF token — i.e. the source
        // length, NOT the end of the last meaningful token. Any trailing
        // whitespace / `;` / newline is included in the span. Use the
        // source length explicitly rather than `last_consumed_end` so
        // `let x := 1\n` ends at 11 (matching cpp) not 10 (the `1`).
        let prog_end = self.src.len();
        Ok(self.wrap_pos_to(
            json!({
                "node": "Program",
                "declarations": declarations,
            }),
            prog_start,
            prog_end,
        ))
    }

    fn parse_declaration(&mut self) -> Result<Value, ParseError> {
        let decl_start = self.peek0.start;
        let result = if self.peek() == TokenKind::Keyword(Kw::Let) {
            self.parse_var_decl()?
        } else {
            self.parse_statement()?
        };
        Ok(self.wrap_pos(result, decl_start))
    }

    /// Parse a statement-level expression — a `varAssignment` target
    /// or RHS, a `varDecl` / `return` / `throw` value, or a bare
    /// `exprStmt` — with the `stop_postfix_call_before_colon_equals`
    /// guard active, so a trailing `(…) :=` opens the NEXT statement
    /// instead of folding into this expression as a postfix call.
    fn parse_stmt_rhs_expr(&mut self) -> Result<Value, ParseError> {
        let prev_postfix = self.stop_postfix_call_before_colon_equals;
        self.stop_postfix_call_before_colon_equals = true;
        let prev_recover = self.stmt_rhs_recover_on_pratt_rhs_failure;
        self.stmt_rhs_recover_on_pratt_rhs_failure = true;
        let result = self.parse_expr_bp(0);
        self.stop_postfix_call_before_colon_equals = prev_postfix;
        self.stmt_rhs_recover_on_pratt_rhs_failure = prev_recover;
        result
    }

    /// `LET ident (':=' expression)?` (no required trailing `;` —
    /// cpp's `varDecl` doesn't include it). The optional trailing `;`
    /// is consumed at the statement level via the `emptyStmt` skip in
    /// `parse_program` / `parse_block`. We do NOT consume it here:
    /// cpp's `VarDecl` ctx span ends at the expression token, not at
    /// the trailing `;`, so wrapping with `last_consumed_end` after a
    /// local `eat(Semicolon)` would over-extend the span by 1 byte
    /// vs cpp's `addPositionInfo(json, ctx)`.
    fn parse_var_decl(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::Let, "let")?;
        let name_tok = self.bump()?;
        let name = match name_tok.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => {
                identifier_text(self.text(name_tok), name_tok.kind)
            }
            // cpp's `varDecl: LET identifier …` routes through the
            // grammar's `identifier` rule, which omits NULL / INF / NAN
            // and the Hog-statement keywords. `kw_valid_as_identifier`
            // is exactly that filter.
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                identifier_text(self.text(name_tok), name_tok.kind)
            }
            _ => {
                return Err(self.err(format!(
                    "expected variable name after `let`, got {:?}",
                    name_tok.kind
                )));
            }
        };
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("VariableDeclaration".into()));
        obj.insert("name".into(), Value::String(name));
        if self.eat(TokenKind::ColonEquals)? {
            let cp = self.checkpoint();
            let expr = self.parse_stmt_rhs_expr()?;
            // cpp's varDecl grammar (`LET ident (':=' expression)?`)
            // has no place for a trailing `:=` after the expression.
            // When one follows, cpp's ANTLR ALL(*) shortens the
            // expression to the shortest prefix (the leading single
            // token) that leaves the trailing `:=` as the START of a
            // *new* statement's varAssignment lvalue. `let x := y *
            // (z) := 3` → `let x := y` + `*(z) := 3`. Rust used to
            // greedy-parse the full `y * (z)` and then choke on the
            // dangling `:=`.
            if self.peek() == TokenKind::ColonEquals {
                // Shorten to the leading primary form. cpp's ALL(*)
                // does the equivalent: take the shortest columnExpr
                // prefix (typically just one primary — a single token
                // for ident/number/string/`*`, or a paren-wrapped
                // group unwrapped to its inner) that leaves the
                // trailing `:=` and its rhs as a separate statement.
                // `parse_prefix` handles all primary shapes cleanly.
                self.restore(cp)?;
                match self.parse_prefix() {
                    Ok(primary) => {
                        obj.insert("expr".into(), primary);
                    }
                    Err(_) => {
                        // Re-parse and accept the full greedy result —
                        // we'll error at the next statement boundary
                        // the same way the original code did.
                        self.restore(cp)?;
                        obj.insert("expr".into(), self.parse_stmt_rhs_expr()?);
                    }
                }
            } else {
                obj.insert("expr".into(), expr);
            }
        }
        Ok(Value::Object(obj))
    }

    fn parse_statement(&mut self) -> Result<Value, ParseError> {
        let stmt_start = self.peek0.start;
        let result = self.parse_statement_inner()?;
        Ok(self.wrap_pos(result, stmt_start))
    }

    fn parse_statement_inner(&mut self) -> Result<Value, ParseError> {
        match self.peek() {
            // `return` is also a `keyword`-rule identifier. When it is followed
            // by a pure infix / postfix operator (`return :: t`, `return.x`,
            // `return -> y`, `return = 1`, `return / 2`, …) that operator binds
            // `return` as its LHS, so cpp parses the whole line as one exprStmt
            // (`return` is a Field / lambda param), not a bare return that
            // strands the operator. A value-starter or keyword-infix after
            // `return` keeps the returnStmt (`return 1`, `return + 1`) or the
            // bare-return split (`return like x`). Gate on `is_pure_infix_op`
            // and fall through to the exprStmt arm for the identifier case.
            //
            // Exception: a `.` that begins a leading-dot float (`return .5` →
            // value 0.5, `return .5.5` → tuple-access on 0.5) is a return VALUE,
            // not tuple-access on `return`. Only a `.`-chain-link (`return.x`)
            // makes `return` an identifier, so keep `return .<number>` in the
            // returnStmt path.
            //
            // Exception: `return ()` — empty parens are not a valid return value,
            // so cpp re-reads `return` as a Field and `()` as an empty call:
            // `Call(return, [])`. `return (expr)` keeps the returnStmt. Route the
            // empty-call case to the exprStmt arm below.
            TokenKind::Keyword(Kw::Return)
                if (!is_pure_infix_op(self.peek_next())
                    || (self.peek_next() == TokenKind::Dot && !self.dot_next_is_chain_link()))
                    && !self.return_followed_by_empty_call() =>
            {
                self.parse_return_stmt()
            }
            TokenKind::Keyword(Kw::Throw) => self.parse_throw_stmt(),
            TokenKind::Keyword(Kw::Try) => self.parse_try_catch_stmt(),
            // `ifStmt` / `forStmt` / `forInStmt` open with `IF` / `FOR`
            // then a mandatory `(` — but `IF` and `FOR` are also
            // `keyword`-rule identifiers, so an `if` / `for` that is
            // NOT opening its statement form (`if cond {…}` with no
            // parens, a bare `for` lvalue) is just a Field. cpp's
            // ALL(*) takes `statement`'s `ifStmt` / `forStmt` alt only
            // when the whole statement parses; otherwise it falls to
            // `exprStmt`. `try_alt` mirrors that: the statement form is
            // tried first, and a failure rolls back to the expression
            // statement (`while` / `fn` / `fun` are NOT in the
            // `keyword` rule, so they have no such fallback).
            TokenKind::Keyword(Kw::If) => {
                self.try_alt(&[&Self::parse_if_stmt, &Self::parse_expr_or_assignment_stmt])
            }
            TokenKind::Keyword(Kw::While) => self.parse_while_stmt(),
            TokenKind::Keyword(Kw::For) => self.try_alt(&[
                &Self::parse_for_or_for_in_stmt,
                &Self::parse_expr_or_assignment_stmt,
            ]),
            TokenKind::Keyword(Kw::Fn) | TokenKind::Keyword(Kw::Fun) => self.parse_func_stmt(),
            // A leading `{` is a three-way ambiguity — cpp's
            // `statement` rule lists `varAssignment | block | exprStmt`
            // and ANTLR's ALL(*) picks the first that consumes the
            // whole statement:
            //   - `{…} := …`  → varAssignment (`{…}` is a Dict/
            //     Placeholder *expression* used as the lvalue)
            //   - `{}` / `{ <decls> }` → Block
            //   - `{1: 2}` / `{x}`-as-Dict → exprStmt
            // Mirror the precedence with `try_alt`: the var-assignment
            // arm rejects unless it actually found `:=`, so `{}` falls
            // through to the Block arm, and `{1: 2}` (whose body isn't
            // a valid `declaration*`) falls through to the exprStmt arm.
            TokenKind::LBrace => {
                // cpp's ALL(*) prefers the exprStmt alt only for a postfix the
                // Block parse can't strand onto a following statement: a `.`
                // (`{1}.x`) or an EMPTY `()` (`{1}()`). A non-empty `(expr)` is
                // itself a valid next statement, so cpp keeps the Block and
                // parses it separately (`{1} (a)` → Block + exprStmt). Other
                // postfixes (`[…]`, `+`, …) already keep the Block. The
                // block-vs-Dict split for the rest is left to `try_alt`: the
                // block arm fails on a non-`declaration*` body like `{1: 2}`,
                // falling through to the exprStmt arm.
                if self.brace_followed_by_dot_or_empty_call() {
                    self.parse_expr_or_assignment_stmt()
                } else {
                    self.try_alt(&[
                        &Self::parse_brace_lvalue_assignment,
                        &Self::parse_block,
                        &Self::parse_expr_or_assignment_stmt,
                    ])
                }
            }
            // `emptyStmt: SEMICOLON` — a bare `;` as a statement.
            // cpp's `VISIT(EmptyStmt)` emits `ExprStatement(expr=null)`.
            // Reached when a statement *slot* holds `;` — e.g. a
            // `while (…) ;` / `for (…;…;…) ;` body or an `if` branch.
            // (At the program / block level a stray `;` is skipped
            // outright in `parse_program` / `parse_block`.)
            TokenKind::Semicolon => {
                self.bump()?;
                Ok(json!({"node": "ExprStatement", "expr": Value::Null}))
            }
            _ => self.parse_expr_or_assignment_stmt(),
        }
    }

    fn parse_return_stmt(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::Return, "return")?;
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("ReturnStatement".into()));
        // `returnStmt: RETURN expression? SEMICOLON?` — the expression
        // is optional. cpp's ANTLR takes the `?` only when an
        // `expression` actually parses. Two filters mirror that:
        //
        //  1. A token that begins the NEXT declaration instead — `let`
        //     (varDecl), a Hog-statement keyword, or a statement/block
        //     terminator — is never an expression start (`return let x`
        //     is a bare return + varDecl; `{ return }` is a Block with
        //     a bare return).
        //  2. For the remaining tokens the expression CAN start but may
        //     not parse to completion — `return { return {} }` (the
        //     `{…}` is a Block statement, not a Dict) or `return for (…)`
        //     (`for` is a keyword-ident but `(… ; …)` can't be its
        //     call-args). cpp's ALL(*) backtracks here; we mirror with
        //     a checkpoint — if `parse_expr_bp` fails, roll back and
        //     emit a bare return so the stranded tokens become the
        //     next declaration.
        if peek_starts_return_expr(self.peek()) {
            let cp = self.checkpoint();
            match self.parse_stmt_rhs_expr() {
                Ok(_) if self.peek() == TokenKind::ColonEquals => {
                    // `return <expr> := …` — taking the full expression
                    // would strand the `:=`. cpp's ALL(*) backtracks to
                    // the shortest expr PREFIX that leaves the rest
                    // parseable as a statement. The common shortenings:
                    //
                    //  - `return * columns(…) := …` → expr is just `*`
                    //    (Field(['*'])); the `columns(…) := …` becomes
                    //    a varAssignment whose lvalue is the `columns`
                    //    call.
                    //  - `return columns(…) := …` → expr is `columns`
                    //    (Field(['columns'])); the `(…) := …` becomes
                    //    a varAssignment whose lvalue is the
                    //    parenthesised inner.
                    //  - `return return * ('e') := {}` → expr is the
                    //    head Keyword as a Field; the rest forms a
                    //    `* ('e') := {}` varAssignment. cpp consistently
                    //    shortens to the FIRST single-token Field,
                    //    regardless of what immediately follows.
                    //  - Otherwise (e.g. `return a.b := c` where the
                    //    first token would chain) no valid shortening
                    //    exists; fall back to bare return so `a.b := c`
                    //    opens the next stmt.
                    self.restore(cp)?;
                    if self.peek() == TokenKind::Asterisk {
                        self.bump()?;
                        obj.insert("expr".into(), emit::field(vec![Value::String("*".into())]));
                    } else if matches!(
                        self.peek(),
                        TokenKind::Ident | TokenKind::QuotedIdent | TokenKind::Keyword(_)
                    ) && !matches!(
                        self.peek_next(),
                        TokenKind::Dot | TokenKind::NullProperty
                    ) {
                        // First single token as Field — cpp shortens to
                        // a one-element chain regardless of what comes
                        // after (call, infix, or another statement
                        // keyword). The Dot / `?.` exclusion stops a
                        // multi-token chain `a.b := c` from being
                        // split (cpp's ANTLR backtracks past chained
                        // shortening to the bare-return path in that
                        // shape).
                        let t = self.bump()?;
                        let name = identifier_text(self.text(t), t.kind);
                        obj.insert("expr".into(), emit::field(vec![Value::String(name)]));
                    } else {
                        obj.insert("expr".into(), Value::Null);
                    }
                }
                Ok(expr) => {
                    obj.insert("expr".into(), expr);
                }
                Err(_) => {
                    self.restore(cp)?;
                    obj.insert("expr".into(), Value::Null);
                }
            }
        } else {
            obj.insert("expr".into(), Value::Null);
        }
        let _ = self.eat(TokenKind::Semicolon)?;
        Ok(Value::Object(obj))
    }

    fn parse_throw_stmt(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::Throw, "throw")?;
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("ThrowStatement".into()));
        // `throwStmt: THROW expression SEMICOLON?` — the expression is
        // MANDATORY (unlike `returnStmt`'s `expression?`). A bare
        // `throw` / `throw;` is rejected. `parse_expr_bp` raises on a
        // missing expression, so no explicit empty-check is needed.
        obj.insert("expr".into(), self.parse_stmt_rhs_expr()?);
        let _ = self.eat(TokenKind::Semicolon)?;
        Ok(Value::Object(obj))
    }

    fn parse_if_stmt(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::If, "if")?;
        self.expect(TokenKind::LParen, "(")?;
        let cond = self.parse_expr_bp(0)?;
        self.expect(TokenKind::RParen, ")")?;
        let then = self.parse_statement()?;
        let else_ = if self.eat_kw(Kw::Else)? {
            Some(self.parse_statement()?)
        } else {
            None
        };
        Ok(json!({
            "node": "IfStatement",
            "expr": cond,
            "then": then,
            "else_": else_.unwrap_or(Value::Null),
        }))
    }

    fn parse_while_stmt(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::While, "while")?;
        self.expect(TokenKind::LParen, "(")?;
        let cond = self.parse_expr_bp(0)?;
        self.expect(TokenKind::RParen, ")")?;
        let body = self.parse_statement()?;
        let _ = self.eat(TokenKind::Semicolon)?;
        Ok(json!({
            "node": "WhileStatement",
            "expr": cond,
            "body": body,
        }))
    }

    /// `for (...)` dispatches between the C-style triple-clause form
    /// and the `for (let ident (, ident)? in expr) body` for-in form
    /// by probing past the `LET`.
    fn parse_for_or_for_in_stmt(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::For, "for")?;
        self.expect(TokenKind::LParen, "(")?;
        // Detect for-in by probing: `LET ident (, ident)? IN`.
        if self.peek() == TokenKind::Keyword(Kw::Let) && self.is_for_in_shape() {
            self.bump()?; // LET
            let first_tok = self.bump()?;
            let first = match first_tok.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => {
                    identifier_text(self.text(first_tok), first_tok.kind)
                }
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                    identifier_text(self.text(first_tok), first_tok.kind)
                }
                _ => {
                    return Err(self.err(format!(
                        "expected loop variable after `let`, got {:?}",
                        first_tok.kind
                    )));
                }
            };
            // Single-var `for (let v in ...)`  →  keyVar=None,
            // valueVar=v. Two-var `for (let k, v in ...)`  →
            // keyVar=k, valueVar=v. cpp's emitter follows the same
            // convention: in the single-binding form the binding
            // names the *value*, not the key.
            let (key_var, value_var) = if self.eat(TokenKind::Comma)? {
                let v_tok = self.bump()?;
                let v = match v_tok.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(v_tok), v_tok.kind)
                    }
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        identifier_text(self.text(v_tok), v_tok.kind)
                    }
                    _ => {
                        return Err(
                            self.err(format!("expected value variable, got {:?}", v_tok.kind))
                        );
                    }
                };
                (Some(first), v)
            } else {
                (None, first)
            };
            self.expect_kw(Kw::In, "in")?;
            let iter_expr = self.parse_expr_bp(0)?;
            self.expect(TokenKind::RParen, ")")?;
            let body = self.parse_statement()?;
            let _ = self.eat(TokenKind::Semicolon)?;
            return Ok(json!({
                "node": "ForInStatement",
                "keyVar": key_var.map(Value::String).unwrap_or(Value::Null),
                "valueVar": value_var,
                "expr": iter_expr,
                "body": body,
            }));
        }
        // C-style: (init?; cond?; incr?) body
        let initializer = if self.peek() != TokenKind::Semicolon {
            Some(self.parse_for_clause()?)
        } else {
            None
        };
        self.expect(TokenKind::Semicolon, ";")?;
        let condition = if self.peek() != TokenKind::Semicolon {
            Some(self.parse_expr_bp(0)?)
        } else {
            None
        };
        self.expect(TokenKind::Semicolon, ";")?;
        let increment = if self.peek() != TokenKind::RParen {
            Some(self.parse_for_clause()?)
        } else {
            None
        };
        self.expect(TokenKind::RParen, ")")?;
        let body = self.parse_statement()?;
        let _ = self.eat(TokenKind::Semicolon)?;
        Ok(json!({
            "node": "ForStatement",
            "initializer": initializer.unwrap_or(Value::Null),
            "condition": condition.unwrap_or(Value::Null),
            "increment": increment.unwrap_or(Value::Null),
            "body": body,
        }))
    }

    /// `for`'s initializer / increment slot accepts `varDecl`,
    /// `varAssignment` (expr := expr), or a bare expression. The
    /// varDecl shape is unambiguous (`LET` prefix); the other two
    /// share the expression prefix and disambiguate by the trailing
    /// `:=` token after the expression.
    fn parse_for_clause(&mut self) -> Result<Value, ParseError> {
        // cpp positions the for-clause initializer / increment in the
        // outer `ForStmt` ctx, so each shape needs a `start` / `end`
        // matching cpp's per-node visit. Capture the slot's start and
        // wrap the emitted VariableDeclaration / VariableAssignment /
        // expression node before returning.
        let clause_start = self.peek0.start;
        if self.peek() == TokenKind::Keyword(Kw::Let) {
            let decl = self.parse_var_decl_no_semicolon()?;
            return Ok(self.wrap_pos(decl, clause_start));
        }
        // Bare `IDENT := …` — same special-case as
        // `parse_expr_or_assignment_stmt`: a leading identifier
        // (including a keyword-named place) followed by `:=` would
        // otherwise be absorbed by `parse_ident_lead` into a
        // `NamedArgument` rather than a `VariableAssignment`.
        if self.peek_is_bare_assignment_lead() {
            let id_start = self.peek0.start;
            let id_end = self.peek0.end;
            let id = self.bump()?;
            let name = identifier_text(self.text(id), id.kind);
            self.bump()?; // `:=`
            let right = self.parse_stmt_rhs_expr()?;
            let left =
                self.wrap_pos_to(json!({"node": "Field", "chain": [name]}), id_start, id_end);
            return Ok(self.wrap_pos(
                json!({
                    "node": "VariableAssignment",
                    "left": left,
                    "right": right,
                }),
                clause_start,
            ));
        }
        // Leading expression — parsed without the
        // `stop_postfix_call_before_colon_equals` guard (see
        // `parse_expr_or_assignment_stmt`): a `(…)` here folds as this
        // clause's own call.
        let expr = self.parse_expr_bp(0)?;
        if self.eat(TokenKind::ColonEquals)? {
            let right = self.parse_stmt_rhs_expr()?;
            return Ok(self.wrap_pos(
                json!({
                    "node": "VariableAssignment",
                    "left": expr,
                    "right": right,
                }),
                clause_start,
            ));
        }
        Ok(expr)
    }

    /// `LET ident (:= expression)?` without the trailing-`;` consume —
    /// used inside `for (...)` where the `;` is the for-loop
    /// separator, not a statement terminator.
    fn parse_var_decl_no_semicolon(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::Let, "let")?;
        let name_tok = self.bump()?;
        let name = match name_tok.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => {
                identifier_text(self.text(name_tok), name_tok.kind)
            }
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                identifier_text(self.text(name_tok), name_tok.kind)
            }
            _ => {
                return Err(self.err(format!(
                    "expected variable name after `let`, got {:?}",
                    name_tok.kind
                )));
            }
        };
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("VariableDeclaration".into()));
        obj.insert("name".into(), Value::String(name));
        if self.eat(TokenKind::ColonEquals)? {
            obj.insert("expr".into(), self.parse_stmt_rhs_expr()?);
        }
        Ok(Value::Object(obj))
    }

    /// Probe: starting at the `LET` token after `for (`, look ahead for
    /// `LET ident (, ident)? IN` — that's the for-in shape. Anything
    /// else (`LET ident := …`) is a C-style initializer.
    fn is_for_in_shape(&self) -> bool {
        let mut probe = Lexer::with_pos(self.src, self.peek0.start);
        let lt = probe.next_token().ok();
        if !matches!(
            lt.as_ref().map(|t| t.kind),
            Some(TokenKind::Keyword(Kw::Let))
        ) {
            return false;
        }
        // Loop-var positions route through `identifier`, so a Keyword
        // is only valid here when `kw_valid_as_identifier` admits it
        // (excludes Null/Inf/Nan and the Hog-statement keywords).
        let id = probe.next_token().ok();
        if !is_hog_identifier_kind(id.as_ref().map(|t| t.kind)) {
            return false;
        }
        let next = probe.next_token().ok();
        match next.as_ref().map(|t| t.kind) {
            Some(TokenKind::Keyword(Kw::In)) => true,
            Some(TokenKind::Comma) => {
                let id2 = probe.next_token().ok();
                if !is_hog_identifier_kind(id2.as_ref().map(|t| t.kind)) {
                    return false;
                }
                matches!(
                    probe.next_token().ok().map(|t| t.kind),
                    Some(TokenKind::Keyword(Kw::In))
                )
            }
            _ => false,
        }
    }

    fn parse_func_stmt(&mut self) -> Result<Value, ParseError> {
        // FN or FUN — both accepted, both emit the same Function node.
        self.bump()?;
        let name_tok = self.bump()?;
        let name = match name_tok.kind {
            TokenKind::Ident | TokenKind::QuotedIdent => {
                identifier_text(self.text(name_tok), name_tok.kind)
            }
            TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                identifier_text(self.text(name_tok), name_tok.kind)
            }
            _ => {
                return Err(self.err(format!("expected function name, got {:?}", name_tok.kind)));
            }
        };
        self.expect(TokenKind::LParen, "(")?;
        // `funcStmt … LPAREN identifierList? RPAREN` and
        // `identifierList: nestedIdentifier (COMMA nestedIdentifier)*
        // COMMA?` — each parameter is a *nestedIdentifier* (a dotted
        // chain `a.b.c`, not a single name), and a trailing comma is
        // allowed. cpp's visitor joins the chain with `.` into one
        // param string (`a.b.c`).
        let mut params: Vec<Value> = Vec::new();
        if self.peek() != TokenKind::RParen {
            loop {
                params.push(Value::String(
                    self.parse_nested_identifier_text("parameter name")?,
                ));
                if !self.eat(TokenKind::Comma)? {
                    break;
                }
                if self.peek() == TokenKind::RParen {
                    break;
                }
            }
        }
        self.expect(TokenKind::RParen, ")")?;
        let body = self.parse_block()?;
        Ok(json!({
            "node": "Function",
            "name": name,
            "params": params,
            "body": body,
        }))
    }

    /// `try block (catch (var (: type)?)? block)* (finally block)?`
    fn parse_try_catch_stmt(&mut self) -> Result<Value, ParseError> {
        self.expect_kw(Kw::Try, "try")?;
        let try_stmt = self.parse_block()?;
        let mut catches: Vec<Value> = Vec::new();
        while self.peek() == TokenKind::Keyword(Kw::Catch) {
            self.bump()?; // catch
            let (var, ty) = if self.eat(TokenKind::LParen)? {
                let v_tok = self.bump()?;
                let v = match v_tok.kind {
                    TokenKind::Ident | TokenKind::QuotedIdent => {
                        identifier_text(self.text(v_tok), v_tok.kind)
                    }
                    TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                        identifier_text(self.text(v_tok), v_tok.kind)
                    }
                    _ => {
                        return Err(self.err(format!(
                            "expected catch variable name, got {:?}",
                            v_tok.kind
                        )));
                    }
                };
                let ty = if self.eat(TokenKind::Colon)? {
                    let t_tok = self.bump()?;
                    let t = match t_tok.kind {
                        TokenKind::Ident | TokenKind::QuotedIdent => {
                            identifier_text(self.text(t_tok), t_tok.kind)
                        }
                        TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                            identifier_text(self.text(t_tok), t_tok.kind)
                        }
                        _ => {
                            return Err(
                                self.err(format!("expected catch type name, got {:?}", t_tok.kind))
                            );
                        }
                    };
                    Some(t)
                } else {
                    None
                };
                self.expect(TokenKind::RParen, ")")?;
                (Some(v), ty)
            } else {
                (None, None)
            };
            let catch_block = self.parse_block()?;
            catches.push(json!([
                var.map(Value::String).unwrap_or(Value::Null),
                ty.map(Value::String).unwrap_or(Value::Null),
                catch_block,
            ]));
        }
        let finally_stmt = if self.eat_kw(Kw::Finally)? {
            Some(self.parse_block()?)
        } else {
            None
        };
        Ok(json!({
            "node": "TryCatchStatement",
            "try_stmt": try_stmt,
            "catches": catches,
            "finally_stmt": finally_stmt.unwrap_or(Value::Null),
        }))
    }

    /// `self.peek()` is `{` — scan to its matching `}` and report whether the
    /// following postfix forces the exprStmt parse over the Block parse. Only a
    /// postfix that can't itself begin a statement does, so the Block parse
    /// would strand it: a `.x` property access (`{1}.x`) or an EMPTY `()`
    /// (`{1}()`). Postfixes that CAN begin a statement return false so the
    /// Block stands: a non-empty `(expr)` (`{1} (a)` → Block + exprStmt) and a
    /// leading-dot number `.5` (`{ } .5` → Block + `.5`, not `{}.5`).
    fn brace_followed_by_dot_or_empty_call(&self) -> bool {
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
        match probe.next_token().map(|t| t.kind) {
            // `.x` (property access) can't begin a statement, so force the
            // exprStmt parse; a leading-dot number (`.5`) IS a valid statement,
            // so keep the Block (`{ } .5` → Block + `.5`, not `{}.5`).
            Ok(TokenKind::Dot) => !matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::Number)),
            // `{…} ()` is the dict / placeholder called with empty args →
            // exprStmt. But `{…} () -> …` is a Block followed by an empty-param
            // lambda statement (`() -> body`), so an Arrow after the empty `()`
            // means keep the Block (`{ } () -> 1` → Block + lambda), not force
            // the call. A non-empty `(a) -> 1` already keeps the Block (the
            // RParen check below fails), matching cpp.
            Ok(TokenKind::LParen) => {
                matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::RParen))
                    && !matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::Arrow))
            }
            _ => false,
        }
    }

    /// True when `return` is immediately followed by an empty `()` (the call
    /// `return()`), distinguishing it from `return (expr)` (a return value).
    /// `peek_next` is the `(`; probe one token past it for the closing `)`.
    fn return_followed_by_empty_call(&self) -> bool {
        if self.peek_next() != TokenKind::LParen {
            return false;
        }
        let mut probe = Lexer::with_pos(self.src, self.peek1.end);
        matches!(probe.next_token().map(|t| t.kind), Ok(TokenKind::RParen))
    }

    pub(crate) fn parse_block(&mut self) -> Result<Value, ParseError> {
        let block_start = self.peek0.start;
        self.expect(TokenKind::LBrace, "{")?;
        let mut declarations: Vec<Value> = Vec::new();
        while !matches!(self.peek(), TokenKind::RBrace | TokenKind::Eof) {
            if self.peek() == TokenKind::Semicolon {
                self.bump()?;
                continue;
            }
            declarations.push(self.parse_declaration()?);
        }
        self.expect(TokenKind::RBrace, "}")?;
        Ok(self.wrap_pos(
            json!({
                "node": "Block",
                "declarations": declarations,
            }),
            block_start,
        ))
    }

    /// Does the cursor sit on a bare `<ident> :=` — a single
    /// identifier-shaped token immediately followed by `:=`? The token
    /// is identifier-shaped if it is a plain identifier, a quoted
    /// identifier, or a keyword admissible wherever the grammar's
    /// `identifier` rule applies (the `keyword` rule — every keyword
    /// bar the literal keywords and the hard set-op introducers, see
    /// `kw_valid_as_identifier`). This is the `varAssignment` whose
    /// `assignmentTarget` is a lone `columnIdentifier`; it must be
    /// caught before `parse_ident_lead` folds the `:=` into a
    /// `NamedArgument`. Keyword-named places — `current := …`,
    /// `timestamp := …` — are the reason the keyword arm is here:
    /// without it they slip past the fast path and mis-parse as a
    /// `NamedArgument` ExprStatement instead of a `VariableAssignment`.
    fn peek_is_bare_assignment_lead(&self) -> bool {
        let head_ok = match self.peek() {
            TokenKind::Ident | TokenKind::QuotedIdent => true,
            TokenKind::Keyword(kw) => kw_valid_as_identifier(kw),
            _ => false,
        };
        head_ok && self.peek_next() == TokenKind::ColonEquals
    }

    /// `expr := expr` (VariableAssignment) or `expr` (ExprStatement).
    /// Disambiguate after parsing the leading expression.
    ///
    /// Special-case `IDENT := expr` up front: `parse_expr_bps`
    /// `parse_ident_lead` would otherwise route the leading ident
    /// through the NamedArgument branch and absorb the `:=` itself,
    /// giving us `NamedArgument(ident, expr)` instead of the
    /// statement-level `VariableAssignment`. Compound lvalues like
    /// `obj.prop := value` go through the fallback — the Field chain
    /// completes before `:=` is reached, so parse_ident_lead doesn't
    /// see the ColonEquals.
    fn parse_expr_or_assignment_stmt(&mut self) -> Result<Value, ParseError> {
        if self.peek_is_bare_assignment_lead() {
            let id_start = self.peek0.start;
            let id_end = self.peek0.end;
            let id = self.bump()?;
            let name = identifier_text(self.text(id), id.kind);
            self.bump()?; // `:=`
            let right = self.parse_stmt_rhs_expr()?;
            // A *second* `:=` after the rhs means cpp's varAssignment
            // separator is the second one, not the first — the leading
            // `IDENT := <rhs>` becomes a NamedArgument as the lvalue of
            // the outer varAssignment. `a := 1 := 2` →
            // `VariableAssignment(NamedArgument(a, 1), 2)`. cpp arrives
            // here via the columnExpr alt of varAssignment when the
            // rhs of the first `:=` is a non-ident-led expression that
            // stops at the next `:=`.
            if self.eat(TokenKind::ColonEquals)? {
                let outer_right = self.parse_stmt_rhs_expr()?;
                let _ = self.eat(TokenKind::Semicolon)?;
                return Ok(json!({
                    "node": "VariableAssignment",
                    "left": emit::named_argument(&name, right),
                    "right": outer_right,
                }));
            }
            // The `:=` form is an `exprStmt` (`expression (COLONEQUALS
            // expression)? SEMICOLON?`) — consume the optional trailing
            // `;` so `if (c) a := b ; else d` sees the `else`.
            let _ = self.eat(TokenKind::Semicolon)?;
            let left =
                self.wrap_pos_to(json!({"node": "Field", "chain": [name]}), id_start, id_end);
            return Ok(json!({
                "node": "VariableAssignment",
                "left": left,
                "right": right,
            }));
        }
        // The leading expression is parsed WITHOUT the
        // `stop_postfix_call_before_colon_equals` guard: a `(…)` here
        // is this statement's own call (`if(x) := y` is
        // `Call(if,[x]) := y`, `f() := 1` is `Call(f) := 1`). The
        // guard is only for a *RHS* parse, where a trailing `(…) :=`
        // would be the next statement's target.
        //
        // We *do* enable the Pratt-RHS-failure recovery flag: cpp's
        // ALL(*) splits `x *= 2` into `x` + `* = 2` (the `*= 2` lexes
        // as `*` `=` `2`, and `* = 2` is a valid Compare(Field(*), =,
        // 2) statement on its own). Rust used to hard-error on the
        // failed RHS of `*`. Wrap the leading parse in checkpoint +
        // recovery so a failed infix RHS at the top level yields the
        // LHS so far and the operator becomes the next statement's
        // leading token.
        let prev_recover = self.stmt_rhs_recover_on_pratt_rhs_failure;
        self.stmt_rhs_recover_on_pratt_rhs_failure = true;
        let expr_result = self.parse_expr_bp(0);
        self.stmt_rhs_recover_on_pratt_rhs_failure = prev_recover;
        let expr = expr_result?;
        if self.eat(TokenKind::ColonEquals)? {
            let right = self.parse_stmt_rhs_expr()?;
            // `exprStmt: expression (COLONEQUALS expression)? SEMICOLON?`
            // — the `:=` form is an `exprStmt`, so it consumes an
            // optional trailing `;`. Without it `if (c) a := b ; else
            // d` would not see the `else` (the `;` would strand).
            let _ = self.eat(TokenKind::Semicolon)?;
            return Ok(json!({
                "node": "VariableAssignment",
                "left": expr,
                "right": right,
            }));
        }
        let _ = self.eat(TokenKind::Semicolon)?;
        Ok(json!({
            "node": "ExprStatement",
            "expr": expr,
        }))
    }

    /// Read a `nestedIdentifier` — `identifier (DOT identifier)*` —
    /// and return its parts joined with `.` (cpp's visitor emits the
    /// dotted chain as one string, with quoted-identifier quotes
    /// stripped). Used for `funcStmt` parameter names.
    fn parse_nested_identifier_text(&mut self, what: &str) -> Result<String, ParseError> {
        let mut parts: Vec<String> = Vec::new();
        loop {
            let t = self.bump()?;
            let part = match t.kind {
                TokenKind::Ident | TokenKind::QuotedIdent => identifier_text(self.text(t), t.kind),
                TokenKind::Keyword(kw) if kw_valid_as_identifier(kw) => {
                    identifier_text(self.text(t), t.kind)
                }
                _ => {
                    return Err(self.err(format!("expected {what}, got {:?}", t.kind)));
                }
            };
            parts.push(part);
            if self.peek() != TokenKind::Dot {
                break;
            }
            self.bump()?; // consume `.`
        }
        Ok(parts.join("."))
    }

    /// `try_alt` arm for a `{`-led statement: parse it as a statement
    /// and accept ONLY if it turned out to be a `VariableAssignment`
    /// (i.e. a `{…} := …` whose `{…}` lvalue is a `Placeholder`, the
    /// only `{…}`-shaped `assignmentTarget`). Anything else — a bare
    /// `{}` Block, a `{1: 2}` Dict exprStmt — is rejected so `try_alt`
    /// falls through to the Block / exprStmt arms. Mirrors ANTLR
    /// trying `varAssignment` before `block` / `exprStmt`.
    fn parse_brace_lvalue_assignment(&mut self) -> Result<Value, ParseError> {
        let stmt = self.parse_expr_or_assignment_stmt()?;
        if stmt.get("node").and_then(Value::as_str) == Some("VariableAssignment") {
            Ok(stmt)
        } else {
            Err(self.err("`{…}`-led statement is not a varAssignment"))
        }
    }
}

/// Can `tok` begin the optional `expression` of a `returnStmt`?
/// `false` for statement/block terminators (`;` `}` `)` `]` `,` EOF)
/// and for the eight Hog-statement keywords that are NOT in the
/// grammar's `keyword` rule — `LET` / `WHILE` / `FN` / `FUN` /
/// `THROW` / `TRY` / `CATCH` / `FINALLY`. Every other keyword
/// (including `IF` / `FOR` / `RETURN` / `ELSE`) IS in `keyword`, so
/// it can be a Field identifier and therefore start an expression:
/// `return return` is `ReturnStatement(expr=Field('return'))`, while
/// `return while` is a bare return followed by a `whileStmt`.
fn peek_starts_return_expr(tok: TokenKind) -> bool {
    !matches!(
        tok,
        TokenKind::Semicolon
            | TokenKind::RBrace
            | TokenKind::RParen
            | TokenKind::RBracket
            | TokenKind::Comma
            | TokenKind::Eof
            | TokenKind::Keyword(
                Kw::Let
                    | Kw::While
                    | Kw::Fn
                    | Kw::Fun
                    | Kw::Throw
                    | Kw::Try
                    | Kw::Catch
                    | Kw::Finally
            )
    )
}

/// `true` when `kind` can stand in for the grammar's `identifier`
/// rule — Ident / QuotedIdent / any keyword admitted by
/// `kw_valid_as_identifier` (the `keyword` rule omits NULL / INF / NAN
/// and the Hog-statement keywords). Used by probe sites that look
/// ahead for an identifier shape (for-in, lambda heads).
pub(crate) fn is_hog_identifier_kind(kind: Option<TokenKind>) -> bool {
    match kind {
        Some(TokenKind::Ident) | Some(TokenKind::QuotedIdent) => true,
        Some(TokenKind::Keyword(kw)) => kw_valid_as_identifier(kw),
        _ => false,
    }
}
