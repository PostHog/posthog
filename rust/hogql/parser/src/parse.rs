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

use crate::emit::{Emitter, JsonEmitter};
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
    build_infix, fold_call_or_exprcall, infix_bp, postfix_bp, BP_ALIAS, BP_BETWEEN, BP_COMPARE,
    BP_IGNORE_NULLS, BP_IS_DISTINCT_FROM, BP_IS_NULL, BP_MULT, BP_NOT, BP_TERNARY, BP_UNARY_MINUS,
};
use template::parse_template_body;

// ============================================================================
// Public entry points
// ============================================================================

pub fn parse_expr(src: &str, is_internal: bool) -> Result<Value, ParseError> {
    parse_expr_with_emit(JsonEmitter, src, is_internal)
}

pub fn parse_expr_with_emit<E: Emitter + Clone>(
    emit: E,
    src: &str,
    is_internal: bool,
) -> Result<E::Value, ParseError> {
    let mut p = Parser::new_with_emit(src, emit)?;
    p.suppress_pos = is_internal;
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
    parse_order_expr_with_emit(JsonEmitter, src)
}

pub fn parse_order_expr_with_emit<E: Emitter + Clone>(
    emit: E,
    src: &str,
) -> Result<E::Value, ParseError> {
    let mut p = Parser::new_with_emit(src, emit)?;
    let exprs = p.parse_order_expr_list()?;
    // cpp's `parse_order_expr_json` entry point silently drops any
    // trailing tokens after the first OrderExpr — `a ASC extra` parses
    // as just `OrderExpr(a, ASC)`, and `a WITH FILL INTERPOLATE (b)`
    // drops the INTERPOLATE since INTERPOLATE lives at the
    // orderByClause level, not on the orderExpr itself. Mirror that
    // permissive behaviour; the `parse_expr_json` and
    // `parse_select_json` entry points still enforce expect_eof so
    // callers there see real syntax errors.
    exprs
        .into_iter()
        .next()
        .ok_or_else(|| ParseError::syntax("empty order expression", 0, 0))
}

pub fn parse_select(src: &str) -> Result<Value, ParseError> {
    parse_select_with_emit(JsonEmitter, src)
}

pub fn parse_select_with_emit<E: Emitter + Clone>(
    emit: E,
    src: &str,
) -> Result<E::Value, ParseError> {
    let mut p = Parser::new_with_emit(src, emit)?;
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
    parse_program_with_emit(JsonEmitter, src)
}

pub fn parse_program_with_emit<E: Emitter + Clone>(
    emit: E,
    src: &str,
) -> Result<E::Value, ParseError> {
    let mut p = Parser::new_with_emit(src, emit)?;
    let prog = p.parse_program()?;
    p.expect_eof()?;
    Ok(prog)
}

pub fn parse_full_template_string(src: &str) -> Result<Value, ParseError> {
    parse_full_template_string_with_emit(JsonEmitter, src)
}

pub fn parse_full_template_string_with_emit<E: Emitter + Clone>(
    emit: E,
    src: &str,
) -> Result<E::Value, ParseError> {
    // The Python wrapper `parse_string_template` prepends `F'` to the
    // template body before handing the source off to either backend
    // (see `posthog/hogql/parser.py::parse_string_template`). Strip
    // that prefix here so the body splitter operates on the real
    // template contents; if it's absent we fall back to treating the
    // whole input as the body.
    let body_offset = if src.starts_with("F'") || src.starts_with("f'") {
        2
    } else {
        0
    };
    // `parse_template_body` walks the body inside `full_src` between
    // `body_offset` and `body_end`. For the standalone entry point the
    // body extends to the end of `src` — there is no trailing `'`.
    let body_end = src.len();
    let result = parse_template_body(&emit, src, body_offset, body_end, true)?;
    // cpp positions the result by chunk count: a multi-chunk `concat(...)`
    // gets the outer rule-ctx span `(0, src.len())`, while a single-chunk
    // shortcut keeps the inner element's own span (the literal text or the
    // substitution expr). `with_pos` is idempotent — it sets `(0, src.len())`
    // on the position-less `concat` and is a no-op on the already-positioned
    // single-chunk cases.
    let start_pos = template::pos_in_source(&emit, src, 0);
    let end_pos = template::pos_in_source(&emit, src, src.len());
    Ok(emit.with_pos(result, start_pos, end_pos))
}

// ============================================================================
// Parser core
// ============================================================================

/// Shared recursion-depth cap across the parser's three recursive-descent dimensions — expression nesting (`parse_expr_bp`), subquery / set nesting (`parse_select_set_stmt`), and Hog statement / block nesting (`parse_statement`). Mirrors ClickHouse's `max_parser_depth` default (1000) so deeply-nested input (`((((…))))`, `(select (select …))`, `{ { … } }`) surfaces a clean `ParseError` instead of stack-OOMing the worker before any parse error can fire. One shared counter (not one per dimension) bounds total live descent depth regardless of how the nesting is composed, and stays below the empirical host-stack overflow points (~2000 nested subqueries, ~8000 nested blocks).
pub(crate) const MAX_RECURSION_DEPTH: u32 = 1000;

pub(crate) struct Parser<'a, E: Emitter = JsonEmitter> {
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
    /// Set by the AS-alias infix arm and read (and reset) at the top of the next
    /// Pratt-loop iteration. A bare alias sits in the loosest grammar tier, so only
    /// an outer-tier operator (`AND`/`OR`/ternary/chained `AS`) may bind to it; a
    /// value-tier operator terminates the expression. Guards `1 AS x + 2` etc.
    pub(crate) after_bare_alias: bool,
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
    /// When set, the parser is inside a clause cpp grammar-parses but its
    /// visitor never visits, so VISITOR-level rejections are downgraded to
    /// "tolerate-and-throw-away": a `DATE`/`TIMESTAMP` string literal
    /// (`visitColumnExprDate`) and a unit-less `INTERVAL <string>`
    /// (`visitColumnExprIntervalString`) parse into a throwaway node instead
    /// of fatally rejecting. Set around the always-discarded `selectSetStmt`
    /// `orderByClause?`, a `{placeholder}` body's dropped LIMIT / OFFSET, and
    /// the discarded select-level `sampleClause`. cpp visits none of those
    /// subtrees, so the flag intentionally leaks into nested parses there
    /// (`({x} order by date 'd')`, `{x} limit interval 'p'` accept). A KEPT
    /// clause (a real SelectQuery's order by / limit, a table-level sample)
    /// leaves the flag unset, so `select 1 order by date 'd'` still rejects on
    /// both. Saved/restored at each set site.
    pub(crate) suppress_unvisited_clause_checks: bool,
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
    /// When set, the Pratt loop's infix-RHS parse is wrapped with
    /// checkpoint-restore: a failing RHS parse rolls back to before
    /// the infix operator and the loop breaks (returning the LHS
    /// built so far). cpp's ALL(*) handles `let x := {} * ()` by
    /// splitting into two statements (`let x := {}` plus
    /// `ExprStatement(Call(Field("*"), []))`) — the `* ()` infix
    /// can't extend the rhs because `()` isn't a valid expression,
    /// so the operator + failing operand become the next statement.
    /// `parse_stmt_rhs_expr` sets this flag.
    pub(crate) stmt_rhs_recover_on_pratt_rhs_failure: bool,
    /// Non-zero while the Pratt loop is parsing the compound body of a
    /// `LIMIT` clause. `%` is overloaded as both the modulo operator
    /// and the `LIMIT … PERCENT` marker; inside the limit body the
    /// `%` handler resolves the two via `try_limit_modulo_extension`
    /// (cpp's ALL(*) takes the modulo alt only when it lands at a
    /// clean limit boundary). Incremented around the body's Pratt
    /// continuation in `parse_limit_clauses` / `parse_trailing_set_decorators`.
    pub(crate) limit_body_depth: u32,
    /// When set, the Pratt `IN` infix handler stops (yields the
    /// operator back) at this byte offset. A PIVOT/UNPIVOT
    /// `columnExprTupleOrSingle` operand is a full `columnExpr` that
    /// may itself contain `in`, but the *last* depth-0 `in (` is the
    /// structural separator before the `( columnExprList )` values.
    /// `parse_expr_tuple_or_single` sets this to that `in` so the
    /// operand parse stops there.
    pub(crate) pivot_in_stop: Option<usize>,
    /// When non-zero, `bump()` converts a lex error on the new peek1
    /// to a synthetic `Eof` token. Used inside HogQLX tag-body parsing:
    /// cpp's `HOGQLX_TEXT` lexer mode admits any byte except `<` / `{`,
    /// but rust's mode-less lexer would reject punctuation like `&` /
    /// `!` / `@` when pre-loading peek1 across a `>` / `/>` / closing
    /// `>` boundary. `parse_hogqlx_children` byte-walks the body
    /// directly and re-seeks the lexer, so peek1's transient invalid
    /// state is recoverable.
    pub(crate) hogqlx_text_lookahead_depth: u32,
    /// One-shot flag set just before `parse_interval_expr` parses its value
    /// expression and consumed at the top of `parse_primary`. When the value's
    /// leading primary is itself an `INTERVAL`, cpp's ALL(*) reserves the
    /// trailing unit keyword for the OUTER interval, so the nested interval is
    /// parsed string-only (`INTERVAL '5 day'`) or as a Field / call — never the
    /// unit-consuming `INTERVAL columnExpr interval` form. The take-on-read
    /// semantics auto-reset across parens / call-args, so a parenthesised nested
    /// interval (`interval (interval '5 day' month) second`) keeps its own unit.
    pub(crate) interval_value_pending: bool,
    /// Sorted byte offsets of each line start in `src` (line 1 starts at 0,
    /// line N starts at `line_starts[N-1]`). Built once at construction;
    /// `pos(offset)` binary-searches for line / column. Used to emit cpp's
    /// per-node `{line, column, offset}` position objects.
    pub(crate) line_starts: Vec<usize>,
    /// Sorted byte offsets of each character start in `src`. Lazily built
    /// on first conversion when the source contains any non-ASCII bytes;
    /// stays `None` for pure-ASCII sources where byte offset == char index.
    /// `byte_to_char(byte_offset)` returns the character index by binary
    /// searching this vector — matches cpp's ANTLR `getStartIndex()`
    /// semantics (character-based, not byte-based).
    pub(crate) char_offsets: std::cell::OnceCell<Option<Vec<usize>>>,
    /// Cached `src.is_ascii()` result — `pos_obj` reads it on every emitted
    /// node, and the underlying `str::is_ascii` is O(n) per call. Computed
    /// once at construction so the hot wrap_pos path stays O(log n) via the
    /// line-starts binary search.
    pub(crate) is_ascii_src: bool,
    /// Live recursive-descent depth shared across expression / subquery / statement nesting; bumped on entry to each recursive entry point, decremented on exit. Enforces `MAX_RECURSION_DEPTH`.
    pub(crate) recursion_depth: u32,
    /// When set, every node is emitted position-less (`pos_obj` returns
    /// `null`). Mirrors cpp's `is_internal` flag, which gates every
    /// `addPositionInfo(json, ctx)` call: a synthetic fragment parsed with
    /// `start=None` (e.g. an injected database `ExpressionField`) carries no
    /// meaningful source spans, so cpp emits none and we must match.
    pub(crate) suppress_pos: bool,
    /// UTF-8 byte length of a leading BOM (3) or 0 if none. cpp's ANTLR
    /// lexer treats a leading `U+FEFF` as zero-width: every emitted char
    /// offset is reckoned from the char AFTER the BOM, so `let` at byte 3
    /// gets char offset 0 (not 1). `pos_obj` subtracts this width past the
    /// BOM so rust matches.
    pub(crate) leading_bom_bytes: usize,
    /// AST node builder. Routes every node/position construction through the `Emitter` trait so we can swap `JsonEmitter` (current default, kept for WASM) for `PyEmitter` (constructs Python ast.* objects directly, avoiding the `serde_json::Value` intermediate). See `crate::emit`.
    pub(crate) emit: E,
}

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    pub(crate) fn new_with_emit(src: &'a str, emit: E) -> Result<Self, ParseError> {
        Self::with_pos_emit(src, 0, emit)
    }

    /// Construct a Parser whose lexer starts at the given byte offset.
    /// Used by the template-body splitter to parse a `{ … }` expression
    /// block without lexing the literal text on either side.
    pub(crate) fn with_pos_emit(src: &'a str, pos: usize, emit: E) -> Result<Self, ParseError> {
        let mut lexer = Lexer::with_pos(src, pos);
        let peek0 = lexer.next_token()?;
        let peek1 = lexer.next_token()?;
        let line_starts = build_line_starts(src);
        let is_ascii_src = src.is_ascii();
        Ok(Self {
            src,
            lexer,
            peek0,
            peek1,
            last_consumed_end: pos,
            cast_as_stop: None,
            after_bare_alias: false,
            suppress_setstmt_trailing_order_by: false,
            suppress_array_join_checks: false,
            suppress_unvisited_clause_checks: false,
            stop_postfix_call_before_colon_equals: false,
            stmt_rhs_recover_on_pratt_rhs_failure: false,
            limit_body_depth: 0,
            pivot_in_stop: None,
            hogqlx_text_lookahead_depth: 0,
            interval_value_pending: false,
            line_starts,
            char_offsets: std::cell::OnceCell::new(),
            is_ascii_src,
            recursion_depth: 0,
            suppress_pos: false,
            leading_bom_bytes: if src.starts_with('\u{FEFF}') { 3 } else { 0 },
            emit,
        })
    }
}

/// Test-only convenience: the JsonEmitter-bound `Parser::new(src)` form. Production code routes through `parse_<rule>_with_emit` (which uses `new_with_emit`) so this only has callers inside the `#[cfg(test)] mod tests` below.
#[cfg(test)]
impl<'a> Parser<'a, JsonEmitter> {
    pub(crate) fn new(src: &'a str) -> Result<Self, ParseError> {
        Self::new_with_emit(src, JsonEmitter)
    }
}

impl<'a, E: Emitter + Clone> Parser<'a, E> {
    pub(crate) fn peek(&self) -> TokenKind {
        self.peek0.kind
    }
    pub(crate) fn peek_next(&self) -> TokenKind {
        self.peek1.kind
    }

    pub(crate) fn bump(&mut self) -> Result<Token, ParseError> {
        let next = match self.lexer.next_token() {
            Ok(t) => t,
            Err(_e) if self.hogqlx_text_lookahead_depth > 0 => {
                // We're inside a HogQLX tag body (`HOGQLX_TEXT` lexer
                // mode in cpp). Defer the error — the immediate caller
                // is about to byte-walk the text body and re-seek the
                // lexer via `set_lexer_pos`, so peek1's invalid state
                // is transient. Stash a synthetic Eof at the current
                // lexer position; if `peek_next()` is consulted before
                // the re-seek, the parser will see Eof and bail out
                // cleanly (matching what it would have done in a
                // boundary token's presence).
                let pos = self.lexer.pos();
                Token {
                    kind: TokenKind::Eof,
                    start: pos,
                    end: pos,
                }
            }
            Err(e) => return Err(e),
        };
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
            "trailing tokens after expression: '{}' ({:?}){extra}",
            self.text(self.peek0),
            self.peek()
        )))
    }

    pub(crate) fn err(&self, message: impl Into<String>) -> ParseError {
        ParseError::syntax(message, self.peek0.start, self.peek0.end)
    }

    pub(crate) fn text(&self, t: Token) -> &'a str {
        &self.src[t.start..t.end]
    }

    /// Resolve a byte offset to a cpp-shape `{line, column, offset}` object.
    /// Lines are 1-based, columns are 0-based — matches the C++ visitor's
    /// `start` / `end` emission. The `offset` and `column` fields are
    /// CHARACTER indices (Unicode code points), not byte indices — cpp's
    /// ANTLR `getStartIndex()` / `getCharPositionInLine()` are
    /// character-based, so byte offsets need converting through `src`
    /// slicing for any source containing non-ASCII bytes.
    pub(crate) fn pos_obj(&self, byte_offset: usize) -> E::Value {
        // `is_internal` parses (cpp's term) emit no positions at all — every
        // node stays at its dataclass `start`/`end` default. Returning `null`
        // here is the single chokepoint: `with_pos` / `replace_pos` then leave
        // the node bare (json `start:null` → None; py setattr of None is a
        // no-op on the already-None default), matching cpp's `!is_internal`
        // gate on `addPositionInfo`.
        if self.suppress_pos {
            return self.emit.null();
        }
        let (line, byte_col, line_start_byte) = offset_to_line_col(&self.line_starts, byte_offset);
        // ASCII fast path: byte == char in every dimension. Avoid the
        // `byte_to_char_index` binary search and the line-slice chars
        // count entirely.
        if self.is_ascii_src {
            return self.emit.position(line, byte_col, byte_offset);
        }
        let mut char_offset = self.byte_to_char_index(byte_offset);
        // Column needs to be characters-in-line, not bytes-in-line. For
        // lines with multi-byte chars we count chars between the line
        // start and the offset.
        let mut column = if byte_col == 0 {
            0
        } else {
            self.src[line_start_byte..byte_offset].chars().count() as u32
        };
        // cpp's ANTLR lexer treats a leading UTF-8 BOM (`U+FEFF`, 3 bytes / 1 char) as zero-width: every char offset
        // it reports is reckoned from the char AFTER the BOM, and the BOM contributes no column on line 1. Mirror
        // that here past the BOM byte boundary — without this, every offset is `+1` and a BOM-prefixed source
        // diverges from cpp at every node.
        if self.leading_bom_bytes > 0 && byte_offset >= self.leading_bom_bytes {
            char_offset = char_offset.saturating_sub(1);
            if line == 1 {
                column = column.saturating_sub(1);
            }
        }
        self.emit.position(line, column, char_offset)
    }

    /// Convert a byte offset into the source into a character (Unicode
    /// code point) index. Pure-ASCII sources short-circuit (byte index
    /// == char index). Mixed sources lazily build a sorted `char_offsets`
    /// vector on first call and binary-search subsequent lookups.
    fn byte_to_char_index(&self, byte_offset: usize) -> usize {
        let char_offsets = self.char_offsets.get_or_init(|| {
            // Pure-ASCII fast path: skip the vector allocation entirely.
            if self.src.is_ascii() {
                None
            } else {
                Some(build_char_offsets(self.src))
            }
        });
        match char_offsets {
            None => byte_offset,
            Some(offsets) => match offsets.binary_search(&byte_offset) {
                Ok(idx) => idx,
                // `byte_offset` lands inside a multi-byte char — return the
                // index of the character starting at or before it.
                Err(idx) => idx.saturating_sub(1),
            },
        }
    }

    /// Inject `start` / `end` position objects on `value` using `start`
    /// (the byte offset of the first token consumed) and the parser's
    /// `last_consumed_end` (the end of the last token consumed). The
    /// canonical wrap-on-return helper for every `parse_*` fn that emits
    /// an AST node.
    pub(crate) fn wrap_pos(&self, value: E::Value, start: usize) -> E::Value {
        let s = self.pos_obj(start);
        let e = self.pos_obj(self.last_consumed_end);
        self.emit.with_pos(value, s, e)
    }

    /// Variant of [`Self::wrap_pos`] that takes an explicit end offset —
    /// used when the natural end of the node isn't `last_consumed_end`
    /// (e.g. composite chain re-tagged with the rightmost child's end).
    pub(crate) fn wrap_pos_to(&self, value: E::Value, start: usize, end: usize) -> E::Value {
        let s = self.pos_obj(start);
        let e = self.pos_obj(end);
        self.emit.with_pos(value, s, e)
    }

    /// Run `f` one level deeper in the shared recursion-depth counter, rejecting cleanly if it would exceed [`MAX_RECURSION_DEPTH`]. The counter is decremented on every exit path (the over-depth bail and any `?` inside `f`), so it tracks live descent depth. Wraps the recursive entry points whose mutual recursion is otherwise unbounded — `parse_select_set_stmt` (subquery / set nesting) and `parse_statement` (Hog block / statement nesting); `parse_expr_bp` does the equivalent inline.
    pub(crate) fn with_recursion_guard<T>(
        &mut self,
        f: impl FnOnce(&mut Self) -> Result<T, ParseError>,
    ) -> Result<T, ParseError> {
        self.recursion_depth += 1;
        if self.recursion_depth > MAX_RECURSION_DEPTH {
            self.recursion_depth -= 1;
            return Err(ParseError::syntax(
                "input too deeply nested",
                self.peek0.start,
                self.peek0.end,
            ));
        }
        let result = f(self);
        self.recursion_depth -= 1;
        result
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
            after_bare_alias: self.after_bare_alias,
        }
    }

    /// Restore the parser to a prior checkpoint. Re-lexes `peek0` and
    /// `peek1` from the saved byte offset.
    pub(crate) fn restore(&mut self, c: Checkpoint) -> Result<(), ParseError> {
        self.set_lexer_pos(c.pos)?;
        self.last_consumed_end = c.last_consumed_end;
        self.cast_as_stop = c.cast_as_stop;
        self.after_bare_alias = c.after_bare_alias;
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
                Err(e) if e.fatal => {
                    // Alt committed to its parse and failed validation
                    // past the point of no return; cpp's ANTLR would
                    // raise visitor-level NotImplementedError here.
                    // Short-circuit so the outer error is the actual
                    // diagnostic, not "no matching alternative".
                    return Err(e);
                }
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
    #[cfg(test)]
    #[allow(clippy::type_complexity)]
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
    after_bare_alias: bool,
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

/// Parse the post-`0x` text of a strict-C99 hex-float literal to f64:
/// `<hex>+(.<hex>*)?p[+-]?<dec>+`. Rust's f64 `FromStr` doesn't accept
/// a `0x` prefix, so accumulate the mantissa from the hex digits and
/// scale by `2^exp`. Bounded-precision when the mantissa overflows
/// f64 (matches what `strtod` would do anyway).
fn parse_hex_float_value(rest: &str) -> f64 {
    let p_idx = rest
        .bytes()
        .position(|b| b == b'p' || b == b'P')
        .expect("caller guarantees a p/P marker is present");
    let mantissa = &rest[..p_idx];
    let exp_str = &rest[p_idx + 1..];
    let (int_part, frac_part) = match mantissa.find('.') {
        Some(i) => (&mantissa[..i], &mantissa[i + 1..]),
        None => (mantissa, ""),
    };
    let mut m = 0.0_f64;
    for c in int_part.chars() {
        m = m * 16.0 + f64::from(c.to_digit(16).unwrap_or(0));
    }
    let mut scale = 1.0_f64 / 16.0;
    for c in frac_part.chars() {
        m += f64::from(c.to_digit(16).unwrap_or(0)) * scale;
        scale /= 16.0;
    }
    let exp: i32 = exp_str.parse().unwrap_or(0);
    m * 2.0_f64.powi(exp)
}

/// Emit a finite float as a numeric Constant, or `±Infinity` / `NaN`
/// when the value isn't finite — mirrors cpp's `stod` result (and its
/// `out_of_range` → `±Infinity` fallthrough).
fn emit_float_constant<E: Emitter>(emit: &E, f: f64) -> E::Value {
    if !f.is_finite() {
        return emit.constant_special_number(if f.is_nan() {
            "NaN"
        } else if f > 0.0 {
            "Infinity"
        } else {
            "-Infinity"
        });
    }
    emit.constant(emit.float(f))
}

pub(crate) fn parse_number_literal<E: Emitter>(
    emit: &E,
    src: &str,
    negative: bool,
) -> Result<E::Value, ParseError> {
    // Hex literal — `0x…`. Three cases:
    //   - Contains `p`/`P`: hex-float (`FLOATING_LITERAL` strict C99
    //     `HEX (DOT HEX*)? P [+-]? DEC+`). Parse to f64 — Rust's f64
    //     `FromStr` doesn't accept a `0x` prefix, so hand-roll it.
    //   - Fits i64: native int.
    //   - Beyond i64: lossless via the `value_type: "number"` digit
    //     string envelope (serde_json::Value can't hold an arbitrary
    //     bigint as a native JSON number).
    if let Some(rest) = src.strip_prefix("0x").or_else(|| src.strip_prefix("0X")) {
        if rest.bytes().any(|b| b == b'p' || b == b'P') {
            let f = parse_hex_float_value(rest);
            return Ok(emit_float_constant(emit, if negative { -f } else { f }));
        }
        let signed = if negative {
            format!("-{rest}")
        } else {
            rest.to_string()
        };
        match i64::from_str_radix(&signed, 16) {
            Ok(n) => return Ok(emit.constant(emit.int(n))),
            Err(_) => {
                let lit = if negative {
                    format!("-{src}")
                } else {
                    src.to_string()
                };
                return Ok(emit.constant_number_string(lit));
            }
        }
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
            return Ok(emit.constant(emit.int(v)));
        }
        // Positive: `Value::from(u64)` emits the exact magnitude as a
        // JSON number — for magnitude > i64::MAX this preserves the
        // full unsigned value (cpp emits the same via Json::raw).
        return Ok(emit.constant(emit.uint(magnitude)));
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
        return Ok(emit_float_constant(emit, if negative { -f } else { f }));
    }
    // Integer. The signed text carries the sign so
    // `-9223372036854775808` (i64::MIN) parses exactly. A literal
    // wider than i64 is kept lossless as a digit string — see the hex
    // branch above for why it can't round-trip as a JSON number.
    let signed = if negative {
        format!("-{src}")
    } else {
        src.to_string()
    };
    match signed.parse::<i64>() {
        Ok(i) => Ok(emit.constant(emit.int(i))),
        Err(_) => Ok(emit.constant_number_string(signed)),
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
                // cpp's `string.cpp` ignores `\0` (NUL is dropped, not
                // emitted) and decodes `\a` → BEL, `\v` → VT.
                Some('0') => {}
                Some('a') => out.push('\u{07}'),
                Some('v') => out.push('\u{0B}'),
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

/// Lenient cpp `parse_string_literal_text` twin (`string.cpp`), exposed via PyO3 for cpp-wheel API parity.
/// Accepts doubled + backslash-escaped quotes (4 quote types, incl. `{...}`) unlike the strict [`decode_quoted_body`].
pub(crate) fn parse_string_literal_text(text: &str) -> Result<String, ParseError> {
    if text.is_empty() {
        return Err(ParseError::parsing(
            "Encountered an unexpected empty string input",
            0,
            0,
        ));
    }
    let bytes = text.as_bytes();
    let first = bytes[0];
    let last = bytes[bytes.len() - 1];
    // Quote bytes are ASCII, so the byte 1/len-1 slice is char-boundary-safe; the `_` arm never slices.
    let stripped = match (first, last) {
        (b'\'', b'\'') => inner_between_quotes(text)
            .replace("''", "'")
            .replace("\\'", "'"),
        (b'"', b'"') => inner_between_quotes(text)
            .replace("\"\"", "\"")
            .replace("\\\"", "\""),
        (b'`', b'`') => inner_between_quotes(text)
            .replace("``", "`")
            .replace("\\`", "`"),
        (b'{', b'}') => inner_between_quotes(text)
            .replace("{{", "{")
            .replace("\\{", "{"),
        _ => {
            return Err(ParseError::syntax(
                format!(
                    "Invalid string literal, must start and end with the same quote type: {text}"
                ),
                0,
                0,
            ));
        }
    };
    Ok(replace_common_escape_characters(&stripped))
}

/// Drop the surrounding quote bytes, cpp `substr(1, size-2)`-style: a length-1 input yields `""`, not a panic.
fn inner_between_quotes(text: &str) -> &str {
    if text.len() < 2 {
        ""
    } else {
        &text[1..text.len() - 1]
    }
}

/// Twin of cpp's `replace_common_escape_characters`: single pass, `\0` dropped, unknown `\X` keeps the backslash.
fn replace_common_escape_characters(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\\' {
            if let Some(&next) = chars.peek() {
                match next {
                    'b' => {
                        out.push('\u{08}');
                        chars.next();
                        continue;
                    }
                    'f' => {
                        out.push('\u{0C}');
                        chars.next();
                        continue;
                    }
                    'r' => {
                        out.push('\r');
                        chars.next();
                        continue;
                    }
                    'n' => {
                        out.push('\n');
                        chars.next();
                        continue;
                    }
                    't' => {
                        out.push('\t');
                        chars.next();
                        continue;
                    }
                    // cpp drops the NUL: `\0` consumes both and emits nothing.
                    '0' => {
                        chars.next();
                        continue;
                    }
                    'a' => {
                        out.push('\u{07}');
                        chars.next();
                        continue;
                    }
                    'v' => {
                        out.push('\u{0B}');
                        chars.next();
                        continue;
                    }
                    '\\' => {
                        out.push('\\');
                        chars.next();
                        continue;
                    }
                    _ => {}
                }
            }
        }
        out.push(c);
    }
    out
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

/// cpp's `assertValidAlias`: an unquoted alias / identifier equal to a
/// reserved keyword is rejected. Callers invoke this only for the
/// *unquoted* alias forms — a quoted alias (`"true"`, `` `team_id` ``)
/// opts out, exactly as cpp's `isQuotedIdentifier` guard does.
pub(crate) fn check_alias_not_reserved(
    name: &str,
    start: usize,
    end: usize,
) -> Result<(), ParseError> {
    if is_reserved_alias_name(name) {
        return Err(ParseError::syntax(
            format!("\"{name}\" cannot be an alias or identifier, as it's a reserved keyword"),
            start,
            end,
        ));
    }
    Ok(())
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
/// keyword`. The `keyword` rule omits:
///   - the literal keywords TRUE / FALSE / NULL / INF / NAN,
///   - the hard set-op introducers INTERSECT / EXCEPT,
///   - the Hog-statement keywords FN / FUN / LET / WHILE / THROW / TRY
///     / CATCH / FINALLY — these head a `statement` and are NOT in the
///     `keyword` rule, so they are not valid identifiers / Field names
///     (cpp rejects `fn`, `let`, … in expression position).
///
/// `interval` adds the unit keywords, which are never in the omitted
/// set anyway.
///
/// Unlike `kw_acts_as_ident_in_primary` this does NOT also exclude the
/// special-form heads (CASE / CAST / SELECT / LAMBDA / INTERVAL / NOT):
/// in a plain `identifier` position — e.g. a table alias after `AS`,
/// per `tableExpr: … | tableExpr (alias | AS identifier) …` — there is
/// no special-form ambiguity to guard against, and cpp accepts them.
pub(crate) fn kw_valid_as_identifier(kw: Kw) -> bool {
    // `true` / `false` are NOT lexer-level keywords in the cpp
    // grammar (they're plain IDENTIFIERs), so they pass through as
    // valid identifiers in chain / table-ident / CTE column / etc.
    // positions. The bare-Field branch in parse_primary still
    // promotes them to Bool Constants; only positions that route
    // through this predicate (postfix `.`, table identifiers, CTE
    // columns, columnAliases) admit them as identifier text.
    !matches!(
        kw,
        Kw::Null
            | Kw::Inf
            | Kw::Nan
            | Kw::Intersect
            | Kw::Except
            | Kw::Fn
            | Kw::Fun
            | Kw::Let
            | Kw::While
            | Kw::Throw
            | Kw::Try
            | Kw::Catch
            | Kw::Finally
            // MATERIALIZED is a lexer keyword used only in `WITH x AS MATERIALIZED (…)`; the grammar's `keyword` rule omits it, so it is never a valid identifier.
            | Kw::Materialized
            // WITHIN is a lexer keyword used only in the `within group (...)` clause; the grammar's `keyword` rule omits it, so it is never a valid identifier.
            | Kw::Within
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
        // Hog-statement keywords — also OMITTED from the `keyword`
        // rule, so they are not Field names / call heads in an
        // expression (`fn`, `let`, `while`, … are rejected by cpp in
        // expression position).
        | Kw::Fn | Kw::Fun | Kw::Let | Kw::While
        | Kw::Throw | Kw::Try | Kw::Catch | Kw::Finally
        // MATERIALIZED — keyword only in `WITH … AS MATERIALIZED (…)`, never a `keyword`-rule identifier.
        | Kw::Materialized
        // WITHIN — keyword only in the `within group (...)` clause, never a `keyword`-rule identifier.
        | Kw::Within
    )
}

/// Walk into a SelectQuery / SelectSetQuery and attach the given CTE
/// list to the innermost SelectQuery's `ctes` field. Used by the
/// `WITH ctes (selectSet)` form where the CTEs declared before the
/// wrapper paren belong to the inner SELECT. cpp's `VISIT(SelectStmtWithParens)`
/// **appends** the outer CTEs after any existing inner CTEs — so if the
/// inner already has `WITH a AS ...`, the outer's CTEs come *after* `a`
/// in declaration order. Match that.
pub(crate) fn inject_ctes_into_select<E: Emitter>(
    emit: &E,
    node: &mut E::Value,
    ctes: Vec<E::Value>,
) {
    // Walk to the inner SelectQuery; the outer wrapper may be a
    // SelectSetQuery that holds the SelectQuery in its
    // `initial_select_query` slot. The walk uses owned recursion via
    // get_field + set_field, mirroring chain_join's pattern (no
    // mutable cursors into nested values for abstract E::Value).
    fn walk<E: Emitter>(emit: &E, mut node: E::Value, ctes: Vec<E::Value>) -> E::Value {
        match emit.node_kind(&node).as_deref() {
            Some("SelectQuery") => {
                let existing = emit
                    .get_field(&node, "ctes")
                    .and_then(|v| emit.as_list(&v))
                    .unwrap_or_default();
                let mut combined = existing;
                combined.extend(ctes);
                emit.set_field(&mut node, "ctes", emit.list_value(combined));
                node
            }
            Some("SelectSetQuery") => {
                if let Some(inner) = emit.get_field(&node, "initial_select_query") {
                    let updated = walk(emit, inner, ctes);
                    emit.set_field(&mut node, "initial_select_query", updated);
                }
                node
            }
            _ => node,
        }
    }
    let owned = std::mem::replace(node, emit.null());
    *node = walk(emit, owned, ctes);
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
pub(crate) fn merge_select_decorators<E: Emitter>(
    emit: &E,
    mut node: E::Value,
    decorators: Vec<(String, E::Value)>,
) -> E::Value {
    if decorators.is_empty() {
        return node;
    }
    for (k, v) in decorators {
        // Clobber pre-existing values on the inner SelectQuery —
        // cpp's `VISIT(SelectSetStmt)` walks the inner select first,
        // then the trailing `orderByClause` / `limitAndOffsetClauseOptional`,
        // so later writes (the SET level) overwrite earlier ones (the
        // inner STMT level). A null value is a sentinel for "remove
        // this key" — the SET-level visitor writes all four limit-related
        // fields, clearing the inner's `offset` even when the outer
        // clause has no OFFSET of its own.
        if emit.is_null(&v) {
            emit.remove_field(&mut node, &k);
        } else {
            emit.set_field(&mut node, &k, v);
        }
    }
    node
}

/// Build / extend a JoinExpr chain. `left` is the existing chain root; we
/// walk down its `next_join` pointers and attach `right` (carrying its
/// `join_type` + `constraint`) at the tail.
pub(crate) fn chain_join<E: Emitter>(
    emit: &E,
    left: E::Value,
    mut right: E::Value,
    join_type: &str,
    constraint: Option<E::Value>,
) -> E::Value {
    let jt = emit.string(join_type);
    emit.set_field(&mut right, "join_type", jt);
    if let Some(c) = constraint {
        emit.set_field(&mut right, "constraint", c);
    }
    // Walk to the tail of `left`'s next_join chain. With abstract
    // E::Value we can't recurse with `&mut` cursors (no `as_object_mut`),
    // so unwind via owned recursion: pop the existing next_join, recurse
    // to append, then put it back.
    fn append_at_tail<E: Emitter>(emit: &E, mut node: E::Value, new_tail: E::Value) -> E::Value {
        let has_next = emit
            .get_field(&node, "next_join")
            .map(|v| !emit.is_null(&v))
            .unwrap_or(false);
        if !has_next {
            emit.set_field(&mut node, "next_join", new_tail);
            return node;
        }
        // Move the existing next_join out, recurse with it, set it back.
        let existing = emit.get_field(&node, "next_join").expect("just checked");
        let updated = append_at_tail(emit, existing, new_tail);
        emit.set_field(&mut node, "next_join", updated);
        node
    }
    append_at_tail(emit, left, right)
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

/// Case-sensitive variant of `interval_call_name` used by the
/// `INTERVAL '<n> <unit>'` combined-string form. cpp's
/// `visitColumnExprIntervalString` matches the unit against a
/// literal-lowercase set, so `'1 SECOND'` is rejected. The keyword-form
/// (`INTERVAL 5 SECOND`) uses the case-insensitive helper because
/// keywords come from the lexer (which is case-insensitive).
pub(crate) fn interval_call_name_case_sensitive(unit: &str) -> Option<&'static str> {
    // cpp matches each unit against exactly its singular OR single-`s` plural.
    // `trim_end_matches('s')` would strip *every* trailing `s`, over-accepting
    // doubled plurals (`dayss`, `secondss`) that cpp rejects.
    match unit {
        "second" | "seconds" => Some("toIntervalSecond"),
        "minute" | "minutes" => Some("toIntervalMinute"),
        "hour" | "hours" => Some("toIntervalHour"),
        "day" | "days" => Some("toIntervalDay"),
        "week" | "weeks" => Some("toIntervalWeek"),
        "month" | "months" => Some("toIntervalMonth"),
        "quarter" | "quarters" => Some("toIntervalQuarter"),
        "year" | "years" => Some("toIntervalYear"),
        _ => None,
    }
}

/// Collect the byte offset of each line start in `src`. Line 1 begins at
/// offset 0; each `\n` byte begins the next line. Single pass over the
/// source, used by `offset_to_line_col` for O(log N) lookups.
fn build_line_starts(src: &str) -> Vec<usize> {
    let mut starts = Vec::with_capacity(src.len() / 40 + 1);
    starts.push(0);
    for (i, b) in src.as_bytes().iter().enumerate() {
        if *b == b'\n' {
            starts.push(i + 1);
        }
    }
    starts
}

/// Resolve a byte offset to `(line, byte_column, line_start_byte)` using
/// a sorted line-starts table. cpp's visitor uses 1-based lines and
/// 0-based columns. The caller converts `byte_column` to character
/// column via `src[line_start_byte..byte_offset].chars().count()` when
/// the source contains non-ASCII bytes.
fn offset_to_line_col(line_starts: &[usize], offset: usize) -> (u32, u32, usize) {
    let line_idx = match line_starts.binary_search(&offset) {
        Ok(i) => i,
        Err(i) => i.saturating_sub(1),
    };
    let line = (line_idx + 1) as u32;
    let line_start_byte = line_starts[line_idx];
    let byte_column = (offset - line_start_byte) as u32;
    (line, byte_column, line_start_byte)
}

/// Collect the byte offset of each character start in `src`. The i-th
/// entry is the byte index where character i begins. `byte_to_char_index`
/// binary-searches this to convert from byte offsets (our lexer's
/// position units) to character indices (cpp's ANTLR `getStartIndex()`
/// semantics). Only called for non-ASCII sources — pure-ASCII parses
/// short-circuit to `byte_offset == char_index`.
fn build_char_offsets(src: &str) -> Vec<usize> {
    let mut offsets: Vec<usize> = Vec::with_capacity(src.len());
    for (i, _) in src.char_indices() {
        offsets.push(i);
    }
    offsets.push(src.len()); // sentinel for end-of-source
    offsets
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::ErrorKind;

    /// Parity cases mirroring the DB-bound `_test_parse_string.py` factory, pinned DB-free here.
    #[test]
    fn parse_string_literal_text_matches_cpp() {
        let f = |s: &str| parse_string_literal_text(s).expect("should decode");

        // Quote types.
        assert_eq!(f("`asd`"), "asd");
        assert_eq!(f("'asd'"), "asd");
        assert_eq!(f("\"asd\""), "asd");
        assert_eq!(f("{asd}"), "asd");

        // Doubled-quote escapes.
        assert_eq!(f("`a``sd`"), "a`sd");
        assert_eq!(f("'a''sd'"), "a'sd");
        assert_eq!(f("\"a\"\"sd\""), "a\"sd");
        assert_eq!(f("{a{{sd}"), "a{sd");
        assert_eq!(f("{a}sd}"), "a}sd");

        // Odd / long quote runs — pins str::replace against cpp's sequential replace_all.
        assert_eq!(f("''''''"), "''");
        assert_eq!(f("'a'''b'"), "a''b");
        assert_eq!(f("`a```b`"), "a``b");

        // Backslash-escaped quotes (the lenient form the strict in-parser decoder rejects).
        assert_eq!(f("`a\\`sd`"), "a`sd");
        assert_eq!(f("'a\\'sd'"), "a'sd");
        assert_eq!(f("\"a\\\"sd\""), "a\"sd");
        assert_eq!(f("{a\\{sd}"), "a{sd");

        // Common escapes; `\0` is dropped.
        assert_eq!(f("`a\nsd`"), "a\nsd");
        assert_eq!(f("`a\\bsd`"), "a\u{08}sd");
        assert_eq!(f("`a\\fsd`"), "a\u{0C}sd");
        assert_eq!(f("`a\\rsd`"), "a\rsd");
        assert_eq!(f("`a\\nsd`"), "a\nsd");
        assert_eq!(f("`a\\tsd`"), "a\tsd");
        assert_eq!(f("`a\\asd`"), "a\u{07}sd");
        assert_eq!(f("`a\\vsd`"), "a\u{0B}sd");
        assert_eq!(f("`a\\\\sd`"), "a\\sd");
        assert_eq!(f("`a\\0sd`"), "asd");

        // Unknown escapes keep the backslash.
        assert_eq!(f("`a\\xsd`"), "a\\xsd");
        assert_eq!(f("`a\\ysd`"), "a\\ysd");
        assert_eq!(f("`a\\osd`"), "a\\osd");

        // Backslash sequencing.
        assert_eq!(f("`a\\\\nsd`"), "a\\nsd");
        assert_eq!(f("`a\\\\n\\sd`"), "a\\n\\sd");
        assert_eq!(f("`a\\\\n\\\\tsd`"), "a\\n\\tsd");

        // Multibyte content survives the byte-level quote strip.
        assert_eq!(f("`café`"), "café");
        assert_eq!(f("{ünïcödé}"), "ünïcödé");
    }

    /// Mismatched quotes raise `SyntaxError`; empty input raises `ParsingError` (cpp's declared class).
    #[test]
    fn parse_string_literal_text_error_paths() {
        let mismatched = parse_string_literal_text("`asd'").expect_err("mismatched quotes");
        assert!(matches!(mismatched.kind, ErrorKind::Syntax));
        assert_eq!(
            mismatched.message,
            "Invalid string literal, must start and end with the same quote type: `asd'"
        );

        let empty = parse_string_literal_text("").expect_err("empty input");
        assert!(matches!(empty.kind, ErrorKind::Parsing));
        assert_eq!(
            empty.message,
            "Encountered an unexpected empty string input"
        );
    }

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
