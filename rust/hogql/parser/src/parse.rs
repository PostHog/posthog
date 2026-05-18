//! HogQL parser entry points + Pratt expression parser.
//!
//! Public API is a set of `parse_*` functions that return `Result<Value,
//! ParseError>`. The PyO3 wrappers in [`crate::lib`] catch errors and emit
//! the JSON error envelope expected by [`posthog/hogql/json_ast.py`].
//!
//! Implementation strategy: Pratt parser with explicit binding powers, full
//! precedence ladder from [`posthog/hogql/grammar/HogQLParser.g4`]'s
//! `columnExpr` rule. The spike validated that the grammar's tricky spots
//! (function-call dispatch, tuple-vs-parens-vs-subquery, `NOT (e)` being a
//! function call by grammar accident, BETWEEN low-binding) need only
//! bounded lookahead.

use serde_json::Value;

use crate::emit;
use crate::error::ParseError;
use crate::lex::{Kw, Lexer, Token, TokenKind};

mod bp;
mod cte;
mod expr;
mod hogqlx;
mod join;
mod program;
mod select;
mod template;

use bp::{
    build_infix, fold_call_or_exprcall, infix_bp, postfix_bp, BP_ADDITIVE, BP_ALIAS, BP_BETWEEN,
    BP_COMPARE, BP_IGNORE_NULLS, BP_IS_DISTINCT_FROM, BP_IS_NULL, BP_MULT, BP_NOT, BP_OR,
    BP_POSTFIX, BP_TERNARY, BP_UNARY_MINUS,
};
use template::parse_template_body;

// ============================================================================
// Public entry points
// ============================================================================

pub fn parse_expr(src: &str, _is_internal: bool) -> Result<Value, ParseError> {
    let mut p = Parser::new(src)?;
    // Bare-list lambda `IDENT (, IDENT)* -> body` is only valid at the
    // outermost expression level; inside an argument list each item parses
    // independently and the commas are separators. So we try it here
    // before falling into the Pratt loop.
    //
    // A bare-list lambda is still a regular expression value — it can
    // be the LHS of a trailing operator (`a, b -> body BETWEEN c`,
    // `x -> {block} [i]`, `x -> {block} * y`). With an expression
    // body the body parse is greedy and absorbs those operators, but
    // a `{ … }` Hog-block body stops at `}`, leaving the operator for
    // the Pratt loop. So feed the lambda through `pratt_continue_with_lhs`
    // rather than demanding EOF immediately after it.
    if let Some(lambda) = p.try_bare_list_lambda()? {
        let expr = p.pratt_continue_with_lhs(lambda, 0, 0)?;
        p.expect_eof()?;
        return Ok(expr);
    }
    let expr = p.parse_expr_bp(0)?;
    p.expect_eof()?;
    Ok(expr)
}

pub fn parse_order_expr(src: &str) -> Result<Value, ParseError> {
    let mut p = Parser::new(src)?;
    let exprs = p.parse_order_expr_list()?;
    p.expect_eof()?;
    exprs
        .into_iter()
        .next()
        .ok_or_else(|| ParseError::syntax("empty order expression", 0, 0))
}

pub fn parse_select(src: &str) -> Result<Value, ParseError> {
    let mut p = Parser::new(src)?;
    // `select` rule top-level admits a bare HogQLX tag element as the
    // third alternative (alongside selectSetStmt / selectStmt). The tag
    // covers both standalone-`<Tag />` use and the `from <Tag />` shape
    // (via `parse_table_expr`).
    let result = if p.peek_starts_hogqlx_tag() {
        p.parse_hogqlx_tag_element()?
    } else {
        p.parse_select_set_stmt()?
    };
    let _ = p.eat(TokenKind::Semicolon)?;
    p.expect_eof()?;
    Ok(result)
}

pub fn parse_program(src: &str) -> Result<Value, ParseError> {
    let mut p = Parser::new(src)?;
    let prog = p.parse_program()?;
    p.expect_eof()?;
    Ok(prog)
}

pub fn parse_full_template_string(src: &str) -> Result<Value, ParseError> {
    // The Python wrapper `parse_string_template` prepends `F'` to the
    // template body before handing the source off to either backend
    // (see `posthog/hogql/parser.py::parse_string_template`). Strip
    // that prefix here so the body splitter operates on the real
    // template contents; if it's absent we fall back to treating the
    // whole input as the body.
    let body = src
        .strip_prefix("F'")
        .or_else(|| src.strip_prefix("f'"))
        .unwrap_or(src);
    parse_template_body(body)
}

// ============================================================================
// Parser core
// ============================================================================

pub(crate) struct Parser<'a> {
    pub(crate) src: &'a str,
    pub(crate) lexer: Lexer<'a>,
    /// One-token-ahead cursor. We carry a second peek for the few
    /// bounded-lookahead spots (`NOT IN`, `IS NULL`, `<.>` for tuple access
    /// vs. Field chain).
    pub(crate) peek0: Token,
    pub(crate) peek1: Token,
    /// End byte offset of the most recently consumed token. Used by
    /// callers that need the end-of-the-expression span without
    /// re-deriving it from the AST.
    pub(crate) last_consumed_end: usize,
    /// Byte offset of the `AS` reserved as a structural separator by
    /// the enclosing construct. cpp's `columnExpr` greedily absorbs
    /// alias forms (`expr AS ident`), so when the value carries one or
    /// more `AS` aliases the *last* AS at paren-depth zero is the
    /// separator: the `AS` before the type in a CAST argument, or the
    /// `AS` before the replacement name in a `columnsReplaceItem`. The
    /// alias-infix bails out when it would consume the AS at this
    /// position. None outside such a construct. Saved/restored across
    /// nesting.
    pub(crate) cast_as_stop: Option<usize>,
    /// Depth tracker for nested `parse_between_body` calls. Used to
    /// switch arm ordering: the outermost call uses WIDE-first
    /// (consuming all in-between tokens greedy so split can find the
    /// rightmost AND), but nested calls switch to NARROW-first so an
    /// inner BETWEEN's body parse doesn't over-consume the outer's
    /// trailing ternary / AND / etc. Mirrors cpp's ANTLR left-recursive
    /// expansion where each nested BETWEEN matches the SHORTEST body
    /// that lets the outer rule succeed.
    pub(crate) between_body_depth: u32,
    /// When set, `parse_trailing_set_decorators` skips a trailing
    /// `ORDER BY` at the selectSetStmt-wrapper level. Used by
    /// `parse_call_argument_select` so that for inputs like
    /// `f((select 1) order by 1)` the ORDER BY is left for the outer
    /// function-call's `orderByClause` slot rather than being
    /// consumed-and-dropped by the SetStmt wrapper. cpp's ANTLR
    /// ALL(*) prefers ColumnExprFunction over ColumnExprCallSelect
    /// (line 236 < 237 in HogQLParser.g4), so the ORDER BY there
    /// belongs to the Function's outer `orderByClause`. Saved/
    /// restored around each call-argument parse.
    pub(crate) suppress_setstmt_trailing_order_by: bool,
    /// When set, the SELECT parser skips the two ARRAY JOIN *visitor*
    /// checks ("Using ARRAY JOIN without a FROM clause is not
    /// permitted" / "ARRAY JOIN arrays must have an alias"). Set by
    /// `parse_optional_filter` while parsing a `FILTER (WHERE …)`
    /// body: cpp's `VISIT(ColumnExprWinFunction)` parses the FILTER
    /// where-expression at the *grammar* level but never visits it
    /// into the AST, so the SelectStmt-visitor semantic checks never
    /// run for a subquery nested inside it. `f() FILTER (WHERE
    /// (SELECT 1 ARRAY JOIN 2)) OVER w` is accepted by cpp for
    /// exactly this reason. Saved/restored around the FILTER parse.
    pub(crate) suppress_array_join_checks: bool,
    /// When set, the Pratt postfix loop stops before folding a
    /// `(…)`-call onto its LHS if a `:=` follows the matching `)`.
    /// Set by the Hog-program statement parser while parsing a
    /// statement RHS expression (a `varAssignment` / `varDecl` /
    /// `return` / `throw` value). cpp's ALL(*) does whole-program
    /// lookahead: in `(a) := (b) (c) := (d)` the first RHS is `(b)`,
    /// not `(b)(c)` — the trailing `(c)` is the next statement's
    /// lvalue. A single-pass parser would greedily fold `(b)(c)` and
    /// strand the second `:=`; the probe mirrors the backtrack.
    /// Saved/restored around each statement-RHS parse.
    pub(crate) stop_postfix_call_before_colon_equals: bool,
}

impl<'a> Parser<'a> {
    pub(crate) fn new(src: &'a str) -> Result<Self, ParseError> {
        Self::with_pos(src, 0)
    }

    /// Construct a Parser whose lexer starts at the given byte offset.
    /// Used by the template-body splitter to parse a `{ … }` expression
    /// block without lexing the literal text on either side.
    pub(crate) fn with_pos(src: &'a str, pos: usize) -> Result<Self, ParseError> {
        let mut lexer = Lexer::with_pos(src, pos);
        let peek0 = lexer.next_token()?;
        let peek1 = lexer.next_token()?;
        Ok(Self {
            src,
            lexer,
            peek0,
            peek1,
            last_consumed_end: pos,
            cast_as_stop: None,
            between_body_depth: 0,
            suppress_setstmt_trailing_order_by: false,
            suppress_array_join_checks: false,
            stop_postfix_call_before_colon_equals: false,
        })
    }

    pub(crate) fn peek(&self) -> TokenKind {
        self.peek0.kind
    }
    pub(crate) fn peek_next(&self) -> TokenKind {
        self.peek1.kind
    }

    pub(crate) fn bump(&mut self) -> Result<Token, ParseError> {
        let next = self.lexer.next_token()?;
        let old = std::mem::replace(&mut self.peek0, self.peek1);
        self.peek1 = next;
        self.last_consumed_end = old.end;
        Ok(old)
    }

    pub(crate) fn eat(&mut self, k: TokenKind) -> Result<bool, ParseError> {
        if self.peek() == k {
            self.bump()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub(crate) fn eat_kw(&mut self, kw: Kw) -> Result<bool, ParseError> {
        if self.peek() == TokenKind::Keyword(kw) {
            self.bump()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub(crate) fn expect(&mut self, k: TokenKind, what: &str) -> Result<Token, ParseError> {
        if self.peek() == k {
            self.bump()
        } else {
            Err(self.err(format!("expected {what}, got {:?}", self.peek())))
        }
    }

    pub(crate) fn expect_kw(&mut self, kw: Kw, what: &str) -> Result<(), ParseError> {
        if self.peek() == TokenKind::Keyword(kw) {
            self.bump()?;
            Ok(())
        } else {
            Err(self.err(format!("expected {what}, got {:?}", self.peek())))
        }
    }

    pub(crate) fn expect_eof(&mut self) -> Result<(), ParseError> {
        if self.peek() == TokenKind::Eof {
            return Ok(());
        }
        // If the trailing token is a keyword, surface it as a reserved-
        // keyword problem so the Python side maps the envelope to
        // `HogQLSyntaxError` (the deserialiser triggers on the substring
        // "reserved keyword"). Plain identifier or punctuation trailing
        // gets the generic message.
        let extra = match self.peek() {
            TokenKind::Keyword(_) => " (reserved keyword cannot appear in this position)",
            _ => "",
        };
        Err(self.err(format!(
            "trailing tokens after expression: {:?}{extra}",
            self.peek()
        )))
    }

    pub(crate) fn err(&self, message: impl Into<String>) -> ParseError {
        ParseError::syntax(message, self.peek0.start, self.peek0.end)
    }

    pub(crate) fn text(&self, t: Token) -> &'a str {
        &self.src[t.start..t.end]
    }

    /// Snapshot the parser cursor + per-call context so a failed
    /// alternative can be rolled back. Carries the byte position of
    /// `peek0`, the end of the last-consumed token, and the CAST/AS
    /// stop. The lexer itself is `(src, pos)` — restoring re-derives
    /// the peek window via `set_lexer_pos`.
    ///
    /// AST construction is purely returned-by-value, never stored on
    /// `Parser`, so the checkpoint doesn't need to capture any AST
    /// state. If a future change adds parser-stored AST state, it must
    /// be added here (and a `restore` regression test added).
    pub(crate) fn checkpoint(&self) -> Checkpoint {
        Checkpoint {
            pos: self.peek0.start,
            last_consumed_end: self.last_consumed_end,
            cast_as_stop: self.cast_as_stop,
        }
    }

    /// Restore the parser to a prior checkpoint. Re-lexes `peek0` and
    /// `peek1` from the saved byte offset.
    pub(crate) fn restore(&mut self, c: Checkpoint) -> Result<(), ParseError> {
        self.set_lexer_pos(c.pos)?;
        self.last_consumed_end = c.last_consumed_end;
        self.cast_as_stop = c.cast_as_stop;
        Ok(())
    }

    /// ALL(*)-style adaptive lookahead via bounded backtrack: try each
    /// alternative in order; commit to the first that parses to
    /// completion. Failed alternatives roll the parser cursor back to
    /// the checkpoint before the call, so the next alt sees the same
    /// input.
    ///
    /// **Invariant**: each alternative must consume at least one token
    /// before recursing into a Pratt loop on the same rule — otherwise
    /// a re-entrant `try_alt` on the same decision can loop forever.
    /// Callers are expected to enforce this via their grammar shape
    /// (the alts correspond to grammar rule arms, each of which has at
    /// least one mandatory terminal).
    ///
    /// **Error reporting**: the error from the last-tried alt
    /// surfaces. For better diagnostics we should later prefer the
    /// alt that progressed furthest into the input (deepest
    /// `peek0.start`); deferring that until we see whether error
    /// messages regress in practice.
    #[allow(clippy::type_complexity)]
    pub(crate) fn try_alt<T>(
        &mut self,
        alts: &[&dyn Fn(&mut Self) -> Result<T, ParseError>],
    ) -> Result<T, ParseError> {
        let cp = self.checkpoint();
        let mut last_err: Option<ParseError> = None;
        for alt in alts {
            match alt(self) {
                Ok(v) => return Ok(v),
                Err(e) => {
                    self.restore(cp)?;
                    last_err = Some(e);
                }
            }
        }
        Err(last_err.unwrap_or_else(|| self.err("no matching alternative")))
    }

    /// Cross-arm backtrack with a follow-set check. Each alternative
    /// parses its branch; AFTER a successful parse, the `followup_ok`
    /// predicate is consulted against the post-parse `peek` token. If
    /// the alt's parse succeeds AND the follow-up token is in the
    /// caller's accepted set, the alt commits. Otherwise the alt is
    /// rolled back like a parse failure and the next alt is tried.
    ///
    /// This extends `try_alt` to handle decisions whose discriminator
    /// is what comes AFTER the arm's parse, not just whether the arm
    /// parsed. The motivating case is `NOT (a,) -> 1` vs
    /// `NOT ((a,) -> 1)`: with bare `try_alt`, the function-call arm
    /// successfully parses `not((a,))` for the first input, leaving
    /// `-> 1` as trailing tokens for the OUTER caller to choke on —
    /// by which point we've already committed. With a follow-up check
    /// that rejects `Arrow` at expression-follow position, the
    /// function-call arm fails on the first input (allowing the
    /// NOT-prefix arm to take over) but succeeds on the second (where
    /// `(a,) -> 1` is a single inner columnExpr and the post-parse
    /// peek is EOF / clean).
    ///
    /// **Cost**: each alt that parses successfully but fails the
    /// follow-up check is wasted work (parses then rolls back). This
    /// is the bounded-backtrack analogue of ANTLR's adaptive LL
    /// prediction without the DFA cache. For our grammar's decision
    /// points the wasted work is bounded by the arm depth.
    #[allow(dead_code, clippy::type_complexity)]
    pub(crate) fn try_alt_with_followup<T, F>(
        &mut self,
        alts: &[&dyn Fn(&mut Self) -> Result<T, ParseError>],
        followup_ok: F,
    ) -> Result<T, ParseError>
    where
        F: Fn(TokenKind) -> bool,
    {
        let cp = self.checkpoint();
        let mut last_err: Option<ParseError> = None;
        for alt in alts {
            match alt(self) {
                Ok(v) => {
                    if followup_ok(self.peek()) {
                        return Ok(v);
                    }
                    // Alt parsed but the follow-up isn't acceptable.
                    // Roll back; the next alt should fit better. Build
                    // an error in case all alts fail follow-up.
                    let what = self.peek();
                    self.restore(cp)?;
                    last_err = Some(self.err(format!(
                        "alt parsed but follow-up token {:?} isn't accepted",
                        what
                    )));
                }
                Err(e) => {
                    self.restore(cp)?;
                    last_err = Some(e);
                }
            }
        }
        Err(last_err.unwrap_or_else(|| self.err("no matching alternative")))
    }
}

/// Snapshot of `Parser` cursor + per-call context for backtracking via
/// [`Parser::try_alt`]. Returned by [`Parser::checkpoint`]; consumed by
/// [`Parser::restore`].
#[derive(Clone, Copy)]
pub(crate) struct Checkpoint {
    pos: usize,
    last_consumed_end: usize,
    cast_as_stop: Option<usize>,
}

// Per-section method bodies live in the submodules:
//   - `bp.rs`       : binding powers, infix/postfix dispatch tables
//   - `expr.rs`     : Pratt loop, primary forms, postfix, special infix
//   - `select.rs`   : SELECT statement + clauses + WINDOW + LIMIT
//   - `join.rs`     : FROM/JOIN chain, table expressions, PIVOT/UNPIVOT
//   - `cte.rs`      : WITH/CTE
//   - `template.rs` : `f'…'` template-string body splitter

// ============================================================================
// Lexeme helpers (number / string / identifier text decoding)
// ============================================================================

pub(crate) fn parse_number_literal(src: &str, negative: bool) -> Result<Value, ParseError> {
    // Hex — always an integer.
    if let Some(rest) = src.strip_prefix("0x").or_else(|| src.strip_prefix("0X")) {
        let n = i64::from_str_radix(rest, 16).unwrap_or(0);
        return Ok(emit::constant(Value::from(if negative { -n } else { n })));
    }
    // `0o`-prefixed octal — cpp 1.3.45's `VISIT(NumberLiteral)`
    // unconditionally rejects it (matches ClickHouse and pre-pg16
    // Postgres). The lexer captures `0o<dec digits>` as one Number
    // token purely so we can raise the error here.
    if src.starts_with("0o") || src.starts_with("0O") {
        return Err(ParseError::syntax(
            format!(
                "HogQL does not support `0o`-prefixed octal integer literals; got `{src}`. Use a plain decimal literal instead."
            ),
            0,
            src.len(),
        ));
    }
    // `0b`-prefixed binary. cpp: a non-binary digit makes it a
    // MALFORMED_BINARY_LITERAL token (no grammar rule references it →
    // reject); the magnitude must fit UInt64 (positive) or 2^63
    // (negative).
    if let Some(rest) = src.strip_prefix("0b").or_else(|| src.strip_prefix("0B")) {
        if rest.is_empty() || !rest.bytes().all(|b| b == b'0' || b == b'1') {
            return Err(ParseError::syntax(
                format!("invalid binary integer literal `{src}` (digits must be 0 or 1)"),
                0,
                src.len(),
            ));
        }
        let magnitude = u64::from_str_radix(rest, 2).map_err(|_| {
            ParseError::syntax(
                format!("HogQL binary integer literals are limited to 64 bits; got `{src}`."),
                0,
                src.len(),
            )
        })?;
        if negative {
            // cpp: magnitude > 2^63 rejects; == 2^63 is i64::MIN;
            // otherwise the negated i64.
            if magnitude > (1u64 << 63) {
                return Err(ParseError::syntax(
                    format!("HogQL binary integer literals are limited to 64 bits; got `{src}`."),
                    0,
                    src.len(),
                ));
            }
            let v = if magnitude == (1u64 << 63) {
                i64::MIN
            } else {
                -(magnitude as i64)
            };
            return Ok(emit::constant(Value::from(v)));
        }
        // Positive: `Value::from(u64)` emits the exact magnitude as a
        // JSON number — for magnitude > i64::MAX this preserves the
        // full unsigned value (cpp emits the same via Json::raw).
        return Ok(emit::constant(Value::from(magnitude)));
    }
    // cpp 1.3.45's `VISIT(NumberLiteral)` parses integer text with
    // `stoll(text, nullptr, 10)` — base 10, NOT base-0 auto-detect.
    // Leading zeros are no-ops, never octal: `017` → 17, `09` → 9.
    // (Pre-1.3.45 cpp used base-0, which made `017` C-style octal 15;
    // that's been removed upstream.) The plain `src.parse()` path
    // below already does base-10 parsing, so leading-zero integers
    // need no special handling.
    let is_float = src.contains('.') || src.contains('e') || src.contains('E');
    if is_float {
        let f: f64 = src.parse().unwrap_or(0.0);
        let f = if negative { -f } else { f };
        if !f.is_finite() {
            return Ok(emit::constant_special_number(if f.is_nan() {
                "NaN"
            } else if f > 0.0 {
                "Infinity"
            } else {
                "-Infinity"
            }));
        }
        Ok(emit::constant(
            serde_json::Number::from_f64(f)
                .map(Value::Number)
                .unwrap_or(Value::Null),
        ))
    } else {
        let i: i64 = src.parse().unwrap_or(0);
        Ok(emit::constant(Value::from(if negative { -i } else { i })))
    }
}

/// Decode a quoted body — the text between matching quotes, with the
/// quotes already stripped. Processes backslash escapes (`\n`, `\t`,
/// `\r`, `\0`, `\\`, `\'`, `\"`, `\b`, `\f`) and the SQL doubled-quote
/// escape (`quote` `quote` → `quote`). Shared by single-quoted string
/// literals and `"`/`` ` ``-quoted identifiers — the grammar's
/// `STRING_LITERAL` and quoted-`IDENTIFIER` rules admit the same
/// `ESCAPE_CHAR_COMMON` set. Mirrors `parse_string_literal_ctx` on the
/// C++ side.
fn decode_quoted_body(inner: &str, quote: char) -> String {
    let mut out = String::with_capacity(inner.len());
    let mut chars = inner.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\\' {
            match chars.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some('r') => out.push('\r'),
                Some('0') => out.push('\0'),
                Some('\'') => out.push('\''),
                Some('"') => out.push('"'),
                Some('\\') => out.push('\\'),
                Some('b') => out.push('\u{08}'),
                Some('f') => out.push('\u{0C}'),
                Some(other) => {
                    out.push('\\');
                    out.push(other);
                }
                None => out.push('\\'),
            }
        } else if c == quote {
            // Doubled `quote quote` inside the body -> one `quote`.
            if chars.peek() == Some(&quote) {
                chars.next();
                out.push(quote);
            } else {
                out.push(c);
            }
        } else {
            out.push(c);
        }
    }
    out
}

/// Decode a single-quoted string literal: strip the surrounding quotes
/// and process the escapes handled by [`decode_quoted_body`].
pub(crate) fn unquote_single_string(src: &str) -> String {
    decode_quoted_body(&src[1..src.len() - 1], '\'')
}

pub(crate) fn identifier_text(src: &str, kind: TokenKind) -> String {
    match kind {
        TokenKind::QuotedIdent => {
            let bytes = src.as_bytes();
            let quote = bytes[0] as char;
            // The quoted-`IDENTIFIER` rule admits the same
            // `ESCAPE_CHAR_COMMON` escapes as a string literal (plus the
            // doubled-quote escape), so the identifier name carries
            // `\n` / `\t` / … decoded, not literal.
            decode_quoted_body(&src[1..src.len() - 1], quote)
        }
        _ => src.to_string(),
    }
}

/// Keywords accepted as the type-cast target on the `::` postfix. Maps to
/// the grammar's `columnTypeCastIdentifier` rule: IDENTIFIER /
/// QUOTED_IDENTIFIER / interval-units / `DATE` / `TIME` / `TIMESTAMP` /
/// `INTERVAL`. Any other keyword (e.g. `WITH`, `ZONE`, `LOCAL`) is
/// rejected so `1::with` doesn't silently parse as a TypeCast.
pub(crate) fn kw_valid_type_cast_ident(kw: Kw) -> bool {
    matches!(
        kw,
        Kw::Date
            | Kw::Time
            | Kw::Timestamp
            | Kw::Interval
            | Kw::Second
            | Kw::Minute
            | Kw::Hour
            | Kw::Day
            | Kw::Week
            | Kw::Month
            | Kw::Quarter
            | Kw::Year
    )
}

/// Reserved keywords that can't be used as bare (unquoted) aliases. Mirrors
/// `posthog.hogql.constants.RESERVED_KEYWORDS = [*KEYWORDS, "team_id"]`
/// where `KEYWORDS = ["true", "false", "null"]`.
pub(crate) fn is_reserved_alias_name(name: &str) -> bool {
    let n = name.to_ascii_lowercase();
    matches!(n.as_str(), "true" | "false" | "null" | "team_id")
}

/// Keywords accepted as implicit column aliases (no `AS`). Matches the
/// grammar's `keywordForImplicitAlias` rule.
pub(crate) fn kw_allowed_as_implicit_alias(kw: Kw) -> bool {
    matches!(
        kw,
        Kw::Ascending
            | Kw::Cohort
            | Kw::Date
            | Kw::Descending
            | Kw::Final
            | Kw::Id
            | Kw::Return
            | Kw::Top
            | Kw::Totals
    )
}

/// Keywords admissible wherever the grammar's `identifier` rule
/// applies — `identifier: IDENTIFIER | QUOTED_IDENTIFIER | interval |
/// keyword`. The `keyword` rule covers every keyword except the
/// literal keywords (TRUE / FALSE / NULL / INF / NAN) and the hard
/// set-op introducers (INTERSECT / EXCEPT). `interval` adds the unit
/// keywords, which are never in the excluded set anyway.
///
/// Unlike `kw_acts_as_ident_in_primary` this does NOT also exclude the
/// special-form heads (CASE / CAST / SELECT / LAMBDA / INTERVAL / NOT):
/// in a plain `identifier` position — e.g. a table alias after `AS`,
/// per `tableExpr: … | tableExpr (alias | AS identifier) …` — there is
/// no special-form ambiguity to guard against, and cpp accepts them.
pub(crate) fn kw_valid_as_identifier(kw: Kw) -> bool {
    !matches!(
        kw,
        Kw::True | Kw::False | Kw::Null | Kw::Inf | Kw::Nan | Kw::Intersect | Kw::Except
    )
}

pub(crate) fn kw_acts_as_ident_in_primary(kw: Kw) -> bool {
    !matches!(
        kw,
        // Reserved primary forms — handled by their own parse_primary
        // branches. `COLUMNS` and `WITH` aren't in this list: the
        // dedicated `COLUMNS(...)` branch gates on a `(` follow-up,
        // and `WITH` only consumes CTEs at the start of a SELECT
        // stmt context (parse_select_*). In any other position both
        // fall through here and parse as identifiers per the
        // grammar's keyword rule.
        Kw::Case | Kw::Select
        | Kw::Cast | Kw::TryCast | Kw::Lambda | Kw::Interval
        // Already handled by parse_primary as their own variants.
        | Kw::True | Kw::False | Kw::Null | Kw::Inf | Kw::Nan
        // Prefix operators handled by parse_prefix.
        | Kw::Not
        // Hard set-op keywords — cpp's grammar `keyword` rule
        // explicitly OMITS Intersect and Except (UNION is included).
        // Treating them as identifiers would let `intersect (select)`
        // parse as Call(intersect, [select]) in a column-list context,
        // diverging from cpp which uses them only as set-op
        // introducers.
        | Kw::Intersect | Kw::Except
    )
}

/// Walk into a SelectQuery / SelectSetQuery and attach the given CTE
/// list to the innermost SelectQuery's `ctes` field. Used by the
/// `WITH ctes (selectSet)` form where the CTEs declared before the
/// wrapper paren belong to the inner SELECT. cpp's `VISIT(SelectStmtWithParens)`
/// **appends** the outer CTEs after any existing inner CTEs — so if the
/// inner already has `WITH a AS ...`, the outer's CTEs come *after* `a`
/// in declaration order. Match that.
pub(crate) fn inject_ctes_into_select(node: &mut Value, ctes: Vec<Value>) {
    let mut cursor: &mut Value = node;
    loop {
        let Some(obj) = cursor.as_object_mut() else {
            return;
        };
        match obj.get("node").and_then(Value::as_str) {
            Some("SelectQuery") => {
                match obj.get_mut("ctes") {
                    Some(existing) if existing.is_array() => {
                        if let Some(arr) = existing.as_array_mut() {
                            arr.extend(ctes);
                        }
                    }
                    _ => {
                        obj.insert("ctes".into(), Value::Array(ctes));
                    }
                }
                return;
            }
            Some("SelectSetQuery") => {
                let Some(inner) = obj.get_mut("initial_select_query") else {
                    return;
                };
                cursor = inner;
            }
            _ => return,
        }
    }
}

/// Format a set operator from its base + modifier + by_name. Mirrors the
/// C++ visitor's switch-tree; returns None for impossible combinations
/// (e.g. `EXCEPT DISTINCT`).
pub(crate) fn format_set_op(base: &str, modifier: Option<&str>, by_name: bool) -> Option<String> {
    let stem = match (base, modifier) {
        ("UNION", Some("ALL")) => "UNION ALL",
        ("UNION", Some("DISTINCT")) => "UNION DISTINCT",
        ("UNION", None) => "UNION DISTINCT", // C++ default for bare UNION
        ("INTERSECT", Some("ALL")) => "INTERSECT ALL",
        ("INTERSECT", Some("DISTINCT")) => "INTERSECT DISTINCT",
        ("INTERSECT", None) => "INTERSECT",
        ("EXCEPT", Some("ALL")) => "EXCEPT ALL",
        ("EXCEPT", None) => "EXCEPT",
        _ => return None,
    };
    Some(if by_name {
        format!("{stem} BY NAME")
    } else {
        stem.to_string()
    })
}

/// Merge top-level decorators (`order_by` / `limit` / `offset`) into a
/// SELECT/SelectSetQuery node. When the target is a SelectSetQuery they
/// land on the wrapper; for a single SelectQuery they merge into its
/// existing fields. We pass through whatever shape we have.
pub(crate) fn merge_select_decorators(mut node: Value, decorators: Vec<(String, Value)>) -> Value {
    if decorators.is_empty() {
        return node;
    }
    if let Some(obj) = node.as_object_mut() {
        for (k, v) in decorators {
            // Clobber pre-existing values on the inner SelectQuery —
            // cpp's `VISIT(SelectSetStmt)` walks the inner select
            // first, then the trailing `orderByClause` /
            // `limitAndOffsetClauseOptional`, so later writes (the SET
            // level) overwrite earlier ones (the inner STMT level).
            // A `Value::Null` is a sentinel for "remove this key" —
            // the SET-level visitor writes all four limit-related
            // fields, clearing the inner's `offset` even when the
            // outer clause has no OFFSET of its own.
            if v.is_null() {
                obj.remove(&k);
            } else {
                obj.insert(k, v);
            }
        }
    }
    node
}

/// Build / extend a JoinExpr chain. `left` is the existing chain root; we
/// walk down its `next_join` pointers and attach `right` (carrying its
/// `join_type` + `constraint`) at the tail.
pub(crate) fn chain_join(
    mut left: Value,
    mut right: Value,
    join_type: &str,
    constraint: Option<Value>,
) -> Value {
    if let Some(obj) = right.as_object_mut() {
        obj.insert("join_type".into(), Value::String(join_type.into()));
        if let Some(c) = constraint {
            obj.insert("constraint".into(), c);
        }
    }
    // Walk to the tail of `left`'s next_join chain.
    {
        let mut cursor: &mut Value = &mut left;
        loop {
            let next_exists = cursor
                .as_object()
                .and_then(|o| o.get("next_join"))
                .map(|v| !v.is_null())
                .unwrap_or(false);
            if !next_exists {
                break;
            }
            let obj = cursor.as_object_mut().unwrap();
            cursor = obj.get_mut("next_join").unwrap();
        }
        if let Some(obj) = cursor.as_object_mut() {
            obj.insert("next_join".into(), right);
        }
    }
    left
}

/// Map an INTERVAL unit name (e.g. "month") to the call name the C++
/// visitor emits (`toIntervalMonth`). Case-insensitive, accepts singular
/// and pluralised forms.
pub(crate) fn interval_call_name(unit: &str) -> Option<&'static str> {
    let u = unit.to_ascii_lowercase();
    // `yyyy` is a lexer-level alias for YEAR (HogQLLexer.common.g4
    // line 140: `YEAR: Y E A R | Y Y Y Y`).
    if u == "yyyy" {
        return Some("toIntervalYear");
    }
    match u.trim_end_matches('s') {
        "second" => Some("toIntervalSecond"),
        "minute" => Some("toIntervalMinute"),
        "hour" => Some("toIntervalHour"),
        "day" => Some("toIntervalDay"),
        "week" => Some("toIntervalWeek"),
        "month" => Some("toIntervalMonth"),
        "quarter" => Some("toIntervalQuarter"),
        "year" => Some("toIntervalYear"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `checkpoint` + `restore` on a freshly-constructed parser must
    /// leave it indistinguishable from one constructed at the same
    /// byte offset: same peek window, same `last_consumed_end`, same
    /// CAST stop. Validates that the snapshot captures everything that
    /// matters to subsequent parsing.
    #[test]
    fn checkpoint_restore_roundtrip() {
        let src = "select 1 from a";
        let mut p = Parser::new(src).expect("init parser");
        // Move the cursor past `select`.
        p.bump().expect("bump select");
        let cp = p.checkpoint();
        let saved_peek0 = p.peek0;
        let saved_peek1 = p.peek1;
        let saved_last_end = p.last_consumed_end;

        // Consume a couple more tokens, then restore.
        p.bump().expect("bump 1");
        p.bump().expect("bump from");
        assert_ne!(p.peek0.kind, saved_peek0.kind, "advanced past cp");

        p.restore(cp).expect("restore");
        assert_eq!(p.peek0.kind, saved_peek0.kind);
        assert_eq!(p.peek0.start, saved_peek0.start);
        assert_eq!(p.peek1.kind, saved_peek1.kind);
        assert_eq!(p.peek1.start, saved_peek1.start);
        assert_eq!(p.last_consumed_end, saved_last_end);
    }

    /// `try_alt` commits to the first alt that succeeds. Failing alts
    /// must roll the cursor back so the next alt sees pristine input.
    /// Uses two trivial alts: alt A expects `FROM` (fails on `select`);
    /// alt B consumes `SELECT` and succeeds.
    #[test]
    fn try_alt_picks_first_success() {
        // Alt A: insists on seeing FROM as first token. Fails on
        // `select` and rolls back.
        // Alt B: consumes SELECT. Succeeds.
        let src = "select 1";
        let mut p = Parser::new(src).expect("init parser");
        let result = p
            .try_alt(&[
                &|p: &mut Parser<'_>| {
                    p.expect_kw(Kw::From, "FROM")?;
                    Ok("from")
                },
                &|p: &mut Parser<'_>| {
                    p.expect_kw(Kw::Select, "SELECT")?;
                    Ok("select")
                },
            ])
            .expect("alt B should win");
        assert_eq!(result, "select");
        // Cursor should be just past SELECT now (since alt B committed).
        assert_eq!(p.peek0.kind, TokenKind::Number);
    }

    /// When every alt fails, `try_alt` surfaces an error and leaves
    /// the cursor at the original checkpoint (so the caller can try
    /// something else or report a meaningful error).
    #[test]
    fn try_alt_all_fail_restores_cursor() {
        let src = "select 1";
        let mut p = Parser::new(src).expect("init parser");
        let start_peek = p.peek0;
        let result: Result<(), ParseError> = p.try_alt(&[
            &|p: &mut Parser<'_>| {
                p.expect_kw(Kw::From, "FROM")?;
                Ok(())
            },
            &|p: &mut Parser<'_>| {
                p.expect_kw(Kw::Where, "WHERE")?;
                Ok(())
            },
        ]);
        assert!(result.is_err(), "both alts should fail");
        assert_eq!(p.peek0.kind, start_peek.kind, "cursor unchanged");
        assert_eq!(p.peek0.start, start_peek.start);
    }

    /// `try_alt` correctly rolls back arbitrary forward progress.
    /// Alt A consumes 3 tokens then fails; the cursor must return all
    /// the way to the original position before alt B runs.
    #[test]
    fn try_alt_rolls_back_deep_progress() {
        let src = "select a from b";
        let mut p = Parser::new(src).expect("init parser");
        let result = p
            .try_alt(&[
                // Alt A: consumes 3 tokens then demands a NUMBER (after
                // 3 bumps we're on `b`, an Ident). Fails.
                &|p: &mut Parser<'_>| {
                    p.bump()?;
                    p.bump()?;
                    p.bump()?;
                    p.expect(TokenKind::Number, "number")?;
                    Ok("a")
                },
                // Alt B: consumes SELECT. Should see the original
                // `select`, not whatever alt A advanced to.
                &|p: &mut Parser<'_>| {
                    p.expect_kw(Kw::Select, "SELECT")?;
                    Ok("b")
                },
            ])
            .expect("alt B should win");
        assert_eq!(result, "b");
        // Cursor is past SELECT. Next token should be `a` (Ident).
        assert_eq!(p.peek0.kind, TokenKind::Ident);
    }

    /// `try_alt_with_followup` rejects an alt whose parse succeeded
    /// but left the cursor on a follow-up token the caller forbids.
    /// Models the `NOT (a,) -> 1` case: the function-call arm parses
    /// `not((a,))` happily but leaves `->` at peek; the follow-up
    /// check (rejecting Arrow) rolls it back so the NOT-prefix arm
    /// can take over.
    #[test]
    fn try_alt_with_followup_rejects_unwanted_followup() {
        let src = "select a";
        let mut p = Parser::new(src).expect("init parser");
        let start_peek = p.peek0;
        // Alt A: parses SELECT but leaves `a` at peek. Follow-up check
        // rejects Ident, so this rolls back.
        // Alt B: parses SELECT, then consumes `a` so peek is EOF.
        // Follow-up accepts Eof, so this commits.
        let result = p
            .try_alt_with_followup(
                &[
                    &|p: &mut Parser<'_>| {
                        p.expect_kw(Kw::Select, "SELECT")?;
                        Ok("partial")
                    },
                    &|p: &mut Parser<'_>| {
                        p.expect_kw(Kw::Select, "SELECT")?;
                        p.bump()?; // a
                        Ok("complete")
                    },
                ],
                |t| matches!(t, TokenKind::Eof),
            )
            .expect("alt B should win");
        assert_eq!(result, "complete");
        assert_eq!(p.peek0.kind, TokenKind::Eof);
        // Sanity: the starting peek shouldn't have changed before
        // we started parsing.
        assert_eq!(start_peek.kind, TokenKind::Keyword(Kw::Select));
    }

    /// `try_alt_with_followup` falls back when ALL alts succeed but
    /// none have an acceptable follow-up. Returns the last alt's
    /// follow-up rejection as the error and restores the cursor.
    #[test]
    fn try_alt_with_followup_all_followup_fail_restores_cursor() {
        let src = "select a";
        let mut p = Parser::new(src).expect("init parser");
        let start_peek = p.peek0;
        let result: Result<&'static str, ParseError> = p.try_alt_with_followup(
            &[
                &|p: &mut Parser<'_>| {
                    p.expect_kw(Kw::Select, "SELECT")?;
                    Ok("a")
                },
                &|p: &mut Parser<'_>| {
                    p.expect_kw(Kw::Select, "SELECT")?;
                    p.bump()?; // a
                    Ok("b")
                },
            ],
            // Accept only Semicolon, neither alt leaves us there.
            |t| matches!(t, TokenKind::Semicolon),
        );
        assert!(result.is_err());
        assert_eq!(p.peek0.kind, start_peek.kind);
        assert_eq!(p.peek0.start, start_peek.start);
    }
}
