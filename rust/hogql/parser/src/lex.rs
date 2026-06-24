//! HogQL lexer (default mode).
//!
//! Produces tokens matching the ANTLR grammar at
//! [`posthog/hogql/grammar/HogQLLexer.common.g4`] for everything outside the
//! template-string and HogQLX modes. Those modes maintain a stack and switch
//! lexer state mid-stream; they're deferred until the relevant tests are
//! reached.
//!
//! Keywords are case-insensitive (the ANTLR fragments expand to `[aA]`-style
//! character classes). The keyword table is a static slice; lookup is a
//! linear scan after lowering bytes — fine at this size and well below the
//! cost of the parser's per-decision work.

use crate::error::ParseError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Token {
    pub kind: TokenKind,
    pub start: usize,
    pub end: usize,
}

impl Token {
    pub fn eof(at: usize) -> Self {
        Self {
            kind: TokenKind::Eof,
            start: at,
            end: at,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenKind {
    // ---- Literals / names ----------------------------------------------
    Ident,
    QuotedIdent,
    /// Decimal/octal/hex/float literal. The exact subform is decoded at
    /// parse time from the source slice.
    Number,
    /// Single-quoted string literal. Source slice still contains the
    /// surrounding quotes and any embedded escapes — `parse_string_literal`
    /// in the parser strips and unescapes.
    String,
    /// `f'...'` / `F'...'` template-string literal. Source slice spans
    /// the entire `f'…'`, including the leading `f`/`F`, both quotes,
    /// and any embedded `{expr}` blocks. Body interpretation and
    /// chunk-splitting happen in `parse_full_template_string` so the
    /// lexer only has to find the matching closing quote (skipping
    /// nested `{ ... }` expression blocks that may themselves contain
    /// strings or further template strings).
    TemplateString,

    // ---- Punctuation / brackets ---------------------------------------
    LParen,
    RParen,
    LBracket,
    RBracket,
    LBrace,
    RBrace,
    Comma,
    Dot,
    Colon,
    Semicolon,
    QMark,   // `?`
    Hash,    // `#`
    LtSlash, // `</` for HogQLX closing tags (recognised even outside
    // tag mode so the parser can route on it)
    SlashGt, // `/>` for HogQLX self-closing tags

    // ---- Arithmetic / bitwise / concat --------------------------------
    Plus,
    Dash,
    Asterisk,
    Slash,
    Percent,
    Concat, // `||`

    // ---- Comparison / equality ----------------------------------------
    EqDouble, // `=`  (the SQL "single equals" assignment-style equality)
    EqSingle, // `==` (the SQL "double equals")
    NotEq,    // `!=` or `<>`
    Lt,
    LtEq,
    Gt,
    GtEq,
    NullSafeEq, // `<=>` (MySQL null-safe equality, sugar for IS NOT DISTINCT FROM)

    // ---- Regex --------------------------------------------------------
    RegexSingle,  // `~`
    RegexDouble,  // `=~`
    NotRegex,     // `!~`
    IRegexSingle, // `~*`
    IRegexDouble, // `=~*`
    NotIRegex,    // `!~*`

    // ---- Composite operators -----------------------------------------
    Arrow,        // `->`
    DoubleColon,  // `::`
    ColonEquals,  // `:=`
    Nullish,      // `??`
    NullProperty, // `?.`

    // ---- Keywords -----------------------------------------------------
    Keyword(Kw),

    Eof,
}

/// One variant per keyword recognised by the HogQL lexer. Kept in
/// sync with [`KEYWORDS`] below; if you add a variant, add the entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kw {
    All,
    And,
    Anti,
    Any,
    Array,
    As,
    Ascending,
    Asof,
    Between,
    Both,
    By,
    Case,
    Cast,
    Catch,
    Cohort,
    Collate,
    Columns,
    Cross,
    Cube,
    Current,
    Date,
    Day,
    Desc,
    Descending,
    Distinct,
    Else,
    End,
    Except,
    Exclude,
    Extract,
    False,
    Fill,
    Filter,
    Final,
    Finally,
    First,
    Fn,
    Following,
    For,
    From,
    Full,
    Fun,
    Group,
    Grouping,
    Having,
    Hour,
    Id,
    If,
    Ignore,
    Ilike,
    In,
    Include,
    Inf,
    Inner,
    Interpolate,
    Intersect,
    Interval,
    Is,
    Join,
    Key,
    Lambda,
    Last,
    Leading,
    Left,
    Let,
    Like,
    Limit,
    Local,
    Materialized,
    Minute,
    Month,
    Name,
    Nan,
    Natural,
    Not,
    Null,
    Nulls,
    Offset,
    On,
    Or,
    Order,
    Outer,
    Over,
    Partition,
    Pivot,
    Positional,
    Preceding,
    Prewhere,
    Qualify,
    Quarter,
    Range,
    Recursive,
    Replace,
    Return,
    Right,
    Rollup,
    Row,
    Rows,
    Sample,
    Second,
    Select,
    Semi,
    Sets,
    Settings,
    Step,
    Substring,
    Then,
    Throw,
    Ties,
    Time,
    Timestamp,
    To,
    Top,
    Totals,
    Trailing,
    Trim,
    True,
    Truncate,
    Try,
    TryCast,
    Unbounded,
    Union,
    Unpivot,
    Using,
    Values,
    Week,
    When,
    Where,
    While,
    Window,
    With,
    Within,
    Year,
    Zone,
}

/// Static keyword table. Entries are matched against the lowercased
/// identifier text. Order doesn't matter functionally; grouped roughly by
/// the grammar's `keyword` rule for readability.
const KEYWORDS: &[(&str, Kw)] = &[
    ("all", Kw::All),
    ("and", Kw::And),
    ("anti", Kw::Anti),
    ("any", Kw::Any),
    ("array", Kw::Array),
    ("as", Kw::As),
    ("ascending", Kw::Ascending),
    ("asc", Kw::Ascending),
    ("asof", Kw::Asof),
    ("between", Kw::Between),
    ("both", Kw::Both),
    ("by", Kw::By),
    ("case", Kw::Case),
    ("cast", Kw::Cast),
    ("catch", Kw::Catch),
    ("cohort", Kw::Cohort),
    ("collate", Kw::Collate),
    ("columns", Kw::Columns),
    ("cross", Kw::Cross),
    ("cube", Kw::Cube),
    ("current", Kw::Current),
    ("date", Kw::Date),
    ("day", Kw::Day),
    ("desc", Kw::Desc),
    ("descending", Kw::Descending),
    ("distinct", Kw::Distinct),
    ("else", Kw::Else),
    ("end", Kw::End),
    ("except", Kw::Except),
    ("exclude", Kw::Exclude),
    ("extract", Kw::Extract),
    ("false", Kw::False),
    ("fill", Kw::Fill),
    ("filter", Kw::Filter),
    ("final", Kw::Final),
    ("finally", Kw::Finally),
    ("first", Kw::First),
    ("fn", Kw::Fn),
    ("following", Kw::Following),
    ("for", Kw::For),
    ("from", Kw::From),
    ("full", Kw::Full),
    ("fun", Kw::Fun),
    ("group", Kw::Group),
    ("grouping", Kw::Grouping),
    ("having", Kw::Having),
    ("hour", Kw::Hour),
    ("id", Kw::Id),
    ("if", Kw::If),
    ("ignore", Kw::Ignore),
    ("ilike", Kw::Ilike),
    ("in", Kw::In),
    ("include", Kw::Include),
    ("inf", Kw::Inf),
    ("infinity", Kw::Inf), // cpp grammar: `INF: I N F | I N F I N I T Y` — same keyword
    ("inner", Kw::Inner),
    ("interpolate", Kw::Interpolate),
    ("intersect", Kw::Intersect),
    ("interval", Kw::Interval),
    ("is", Kw::Is),
    ("join", Kw::Join),
    ("key", Kw::Key),
    ("lambda", Kw::Lambda),
    ("last", Kw::Last),
    ("leading", Kw::Leading),
    ("left", Kw::Left),
    ("let", Kw::Let),
    ("like", Kw::Like),
    ("limit", Kw::Limit),
    ("local", Kw::Local),
    ("materialized", Kw::Materialized),
    ("minute", Kw::Minute),
    ("month", Kw::Month),
    ("name", Kw::Name),
    ("nan", Kw::Nan),
    ("natural", Kw::Natural),
    ("not", Kw::Not),
    ("null", Kw::Null),
    ("nulls", Kw::Nulls),
    ("offset", Kw::Offset),
    ("on", Kw::On),
    ("or", Kw::Or),
    ("order", Kw::Order),
    ("outer", Kw::Outer),
    ("over", Kw::Over),
    ("partition", Kw::Partition),
    ("pivot", Kw::Pivot),
    ("positional", Kw::Positional),
    ("preceding", Kw::Preceding),
    ("prewhere", Kw::Prewhere),
    ("qualify", Kw::Qualify),
    ("quarter", Kw::Quarter),
    ("range", Kw::Range),
    ("recursive", Kw::Recursive),
    ("replace", Kw::Replace),
    ("return", Kw::Return),
    ("right", Kw::Right),
    ("rollup", Kw::Rollup),
    ("row", Kw::Row),
    ("rows", Kw::Rows),
    ("sample", Kw::Sample),
    ("second", Kw::Second),
    ("select", Kw::Select),
    ("semi", Kw::Semi),
    ("sets", Kw::Sets),
    ("settings", Kw::Settings),
    ("step", Kw::Step),
    ("substring", Kw::Substring),
    ("then", Kw::Then),
    ("throw", Kw::Throw),
    ("ties", Kw::Ties),
    ("time", Kw::Time),
    ("timestamp", Kw::Timestamp),
    ("to", Kw::To),
    ("top", Kw::Top),
    ("totals", Kw::Totals),
    ("trailing", Kw::Trailing),
    ("trim", Kw::Trim),
    ("true", Kw::True),
    ("truncate", Kw::Truncate),
    ("try", Kw::Try),
    ("try_cast", Kw::TryCast),
    ("unbounded", Kw::Unbounded),
    ("union", Kw::Union),
    ("unpivot", Kw::Unpivot),
    ("using", Kw::Using),
    ("values", Kw::Values),
    ("week", Kw::Week),
    ("when", Kw::When),
    ("where", Kw::Where),
    ("while", Kw::While),
    ("window", Kw::Window),
    ("with", Kw::With),
    ("within", Kw::Within),
    // YEAR has a `YYYY` alias per HogQLLexer.common.g4 line 140
    // (`YEAR: Y E A R | Y Y Y Y`). The interval-unit keywords are
    // singular only — cpp's lexer has no plural forms, so `hours`,
    // `days`, … lex as plain identifiers and only the in-string
    // `INTERVAL '5 days'` form accepts a plural (handled by the
    // visitor, not the lexer).
    ("year", Kw::Year),
    ("yyyy", Kw::Year),
    ("zone", Kw::Zone),
];

pub struct Lexer<'a> {
    src: &'a [u8],
    pos: usize,
    /// Mirrors cpp's `HOGQLX_TAG_OPEN` / `HOGQLX_TAG_CLOSE` lexer modes
    /// for the one trivia rule that differs there: `HASH_COMMENT` is
    /// default-mode-only, so a `#` between tag attributes must stay a
    /// `Hash` token (which the tag parser rejects, matching the
    /// grammar's `TAG_UNEXPECTED` catch-all) instead of starting a
    /// comment. Toggled by the HogQLX tag parser; see
    /// `parse_hogqlx_tag_element`.
    in_hogqlx_tag: bool,
}

impl<'a> Lexer<'a> {
    /// Construct a lexer at the given byte offset of `src`. The parser
    /// passes 0 for normal top-level lexing and a forward position when
    /// it needs to spawn a shadow lexer for bounded lookahead (lambda
    /// heads, CTE shape probes) or to resume after a template-string
    /// expression block.
    pub fn with_pos(src: &'a str, pos: usize) -> Self {
        Self {
            src: src.as_bytes(),
            pos,
            in_hogqlx_tag: false,
        }
    }

    pub fn pos(&self) -> usize {
        self.pos
    }

    pub fn in_hogqlx_tag(&self) -> bool {
        self.in_hogqlx_tag
    }

    pub fn set_in_hogqlx_tag(&mut self, on: bool) {
        self.in_hogqlx_tag = on;
    }

    pub fn next_token(&mut self) -> Result<Token, ParseError> {
        self.skip_trivia()?;
        let start = self.pos;
        let Some(b) = self.peek_byte(0) else {
            return Ok(Token::eof(start));
        };

        let kind = match b {
            b'(' => {
                self.pos += 1;
                TokenKind::LParen
            }
            b')' => {
                self.pos += 1;
                TokenKind::RParen
            }
            b'[' => {
                self.pos += 1;
                TokenKind::LBracket
            }
            b']' => {
                self.pos += 1;
                TokenKind::RBracket
            }
            b'{' => {
                self.pos += 1;
                TokenKind::LBrace
            }
            b'}' => {
                self.pos += 1;
                TokenKind::RBrace
            }
            b',' => {
                self.pos += 1;
                TokenKind::Comma
            }
            b';' => {
                self.pos += 1;
                TokenKind::Semicolon
            }
            b'#' => match self.peek_byte(1) {
                // `#` immediately followed by a digit is the positional-ref
                // HASH token (`#1`); the grammar's HASH_COMMENT rule
                // explicitly excludes a leading digit so those keep lexing.
                Some(b'0'..=b'9') => {
                    self.pos += 1;
                    TokenKind::Hash
                }
                // Anything else (including EOL / EOF right after the `#`)
                // is a MySQL-style `#` line comment, skipped like `--`.
                // skip_trivia caught most of these already; this catches a
                // `#` that follows a non-trivia token mid-expression.
                _ if !self.in_hogqlx_tag => {
                    self.skip_line_comment();
                    return self.next_token();
                }
                // Inside a HogQLX tag there is no HASH_COMMENT rule; emit
                // Hash and let the tag parser reject it (TAG_UNEXPECTED).
                _ => {
                    self.pos += 1;
                    TokenKind::Hash
                }
            },

            // Always emit a single dot. `.5` style literals are assembled
            // at parse time via the grammar's `floatingLiteral` (DOT then
            // DECIMAL_LITERAL) — folding here would misread `t.1` (tuple
            // access) as `t` followed by the float `.1`.
            b'.' => {
                self.pos += 1;
                TokenKind::Dot
            }

            b':' => match self.peek_byte(1) {
                Some(b':') => {
                    self.pos += 2;
                    TokenKind::DoubleColon
                }
                Some(b'=') => {
                    self.pos += 2;
                    TokenKind::ColonEquals
                }
                _ => {
                    self.pos += 1;
                    TokenKind::Colon
                }
            },

            b'?' => match self.peek_byte(1) {
                Some(b'.') => {
                    self.pos += 2;
                    TokenKind::NullProperty
                }
                Some(b'?') => {
                    self.pos += 2;
                    TokenKind::Nullish
                }
                _ => {
                    self.pos += 1;
                    TokenKind::QMark
                }
            },

            b'+' => {
                self.pos += 1;
                TokenKind::Plus
            }

            b'-' => match self.peek_byte(1) {
                Some(b'>') => {
                    self.pos += 2;
                    TokenKind::Arrow
                }
                Some(b'-') => {
                    // `--` line comment. skip_trivia caught most of these
                    // already; this catches a `--` that follows a non-trivia
                    // token mid-expression. Re-route through trivia and
                    // restart.
                    self.skip_line_comment();
                    return self.next_token();
                }
                _ => {
                    self.pos += 1;
                    TokenKind::Dash
                }
            },

            b'*' => {
                self.pos += 1;
                TokenKind::Asterisk
            }

            b'/' => match self.peek_byte(1) {
                Some(b'>') => {
                    self.pos += 2;
                    TokenKind::SlashGt
                }
                Some(b'*') if self.block_comment_has_closer() => {
                    self.skip_block_comment(start)?;
                    return self.next_token();
                }
                Some(b'/') => {
                    // `//` line comment (C-style alias for `--`).
                    // `skip_trivia` catches most occurrences; this
                    // mid-stream branch covers `//` that follows a
                    // non-trivia token, same way the mid-stream `--`
                    // line below the dash arm does.
                    self.skip_line_comment();
                    return self.next_token();
                }
                _ => {
                    self.pos += 1;
                    TokenKind::Slash
                }
            },

            b'%' => {
                self.pos += 1;
                TokenKind::Percent
            }

            b'|' => match self.peek_byte(1) {
                Some(b'|') => {
                    self.pos += 2;
                    TokenKind::Concat
                }
                _ => return Err(self.err(start, "unexpected '|' (expected '||')")),
            },

            b'=' => match self.peek_byte(1) {
                Some(b'=') => {
                    self.pos += 2;
                    TokenKind::EqSingle
                }
                Some(b'~') => match self.peek_byte(2) {
                    Some(b'*') => {
                        self.pos += 3;
                        TokenKind::IRegexDouble
                    }
                    _ => {
                        self.pos += 2;
                        TokenKind::RegexDouble
                    }
                },
                _ => {
                    self.pos += 1;
                    TokenKind::EqDouble
                }
            },

            b'!' => match self.peek_byte(1) {
                Some(b'=') => {
                    self.pos += 2;
                    TokenKind::NotEq
                }
                Some(b'~') => match self.peek_byte(2) {
                    Some(b'*') => {
                        self.pos += 3;
                        TokenKind::NotIRegex
                    }
                    _ => {
                        self.pos += 2;
                        TokenKind::NotRegex
                    }
                },
                // A bare `!` (not `!=` / `!~` / `!~*`) matches no token
                // — the grammar's catch-all `UNEXPECTED_CHARACTER`.
                // Report it by code point, same as the generic arm.
                _ => return Err(self.err(start, "unexpected character '!' (U+0021)")),
            },

            b'<' => match self.peek_byte(1) {
                // `<=>` must win over `<=` (longest match, mirroring the
                // grammar's NULL_SAFE_EQ-before-LT_EQ declaration order).
                Some(b'=') if self.peek_byte(2) == Some(b'>') => {
                    self.pos += 3;
                    TokenKind::NullSafeEq
                }
                Some(b'=') => {
                    self.pos += 2;
                    TokenKind::LtEq
                }
                Some(b'>') => {
                    self.pos += 2;
                    TokenKind::NotEq
                }
                Some(b'/') => {
                    self.pos += 2;
                    TokenKind::LtSlash
                }
                _ => {
                    self.pos += 1;
                    TokenKind::Lt
                }
            },

            b'>' => match self.peek_byte(1) {
                Some(b'=') => {
                    self.pos += 2;
                    TokenKind::GtEq
                }
                _ => {
                    self.pos += 1;
                    TokenKind::Gt
                }
            },

            b'~' => match self.peek_byte(1) {
                Some(b'*') => {
                    self.pos += 2;
                    TokenKind::IRegexSingle
                }
                _ => {
                    self.pos += 1;
                    TokenKind::RegexSingle
                }
            },

            b'\'' => self.lex_string(start)?,
            b'`' | b'"' => self.lex_quoted_ident(start)?,

            b'0'..=b'9' => self.lex_number(start),

            // `f'...'` / `F'...'` template string. Must intercept BEFORE
            // the generic ident path, since `f` is a valid ident-start.
            // Requires zero gap between the `f` and the `'` — `f 'x'` is
            // still `Ident("f")` followed by `String`.
            b'f' | b'F' if self.peek_byte(1) == Some(b'\'') => self.lex_template_string(start)?,

            b'a'..=b'z' | b'A'..=b'Z' | b'_' | b'$' => self.lex_ident_or_keyword(start),

            other => {
                // No lexer rule matched — the grammar's catch-all
                // `UNEXPECTED_CHARACTER` token. Decode the whole UTF-8
                // scalar (not just the lead byte) and name it by code
                // point: the only actionable signal when the character
                // is invisible (a zero-width space / joiner).
                let ch = self.peek_char().map(|(c, _)| c).unwrap_or(other as char);
                return Err(self.err(
                    start,
                    format!("unexpected character {:?} (U+{:04X})", ch, ch as u32),
                ));
            }
        };
        Ok(Token {
            kind,
            start,
            end: self.pos,
        })
    }

    // ---- internals ---------------------------------------------------------

    fn peek_byte(&self, ahead: usize) -> Option<u8> {
        self.src.get(self.pos + ahead).copied()
    }

    /// Decode the UTF-8 scalar starting at `self.pos`, returning it
    /// alongside its byte length. `None` at EOF or when `self.pos`
    /// sits on a continuation / invalid lead byte — the lexer input is
    /// always a valid `&str`, so the latter only happens mid-scalar.
    fn peek_char(&self) -> Option<(char, usize)> {
        let lead = self.peek_byte(0)?;
        let len = match lead {
            0x00..=0x7F => 1,
            0xC0..=0xDF => 2,
            0xE0..=0xEF => 3,
            0xF0..=0xF7 => 4,
            _ => return None,
        };
        let slice = self.src.get(self.pos..self.pos + len)?;
        let c = std::str::from_utf8(slice).ok()?.chars().next()?;
        Some((c, len))
    }

    fn err(&self, start: usize, msg: impl Into<String>) -> ParseError {
        ParseError::syntax(msg, start, self.pos.max(start + 1))
    }

    fn skip_trivia(&mut self) -> Result<(), ParseError> {
        loop {
            // Whitespace. The ANTLR `WHITESPACE` rule is
            // `[ \t\r\n]`; `u8::is_ascii_whitespace`
            // covers all of those bar the vertical tab (``),
            // which is added explicitly. Non-ASCII whitespace
            // (NO-BREAK SPACE, the Unicode line/paragraph separators,
            // etc.) is also skipped: cpp's ANTLR lexer error-recovers
            // past such characters, leaving the parser a clean token
            // stream, and treating them as trivia reaches the same
            // result without a hard reject.
            while let Some(b) = self.peek_byte(0) {
                if b < 0x80 {
                    if !(b.is_ascii_whitespace() || b == 0x0B) {
                        break;
                    }
                    self.pos += 1;
                } else {
                    // `char::is_whitespace` is the Unicode `White_Space`
                    // set; the grammar's `WHITESPACE` rule also admits
                    // U+FEFF (BOM), so a file saved with a byte-order
                    // mark still parses.
                    match self.peek_char() {
                        Some((c, len)) if c.is_whitespace() || c == '\u{FEFF}' => self.pos += len,
                        _ => break,
                    }
                }
            }
            // `--` or `//` line comment (HogQL accepts both forms).
            if (self.peek_byte(0) == Some(b'-') && self.peek_byte(1) == Some(b'-'))
                || (self.peek_byte(0) == Some(b'/') && self.peek_byte(1) == Some(b'/'))
            {
                self.skip_line_comment();
                continue;
            }
            // MySQL-style `#` line comment (the grammar's HASH_COMMENT;
            // default mode only — HogQLX tag modes reject `#` instead).
            // `#` immediately followed by a digit is NOT a comment — it
            // stays a HASH token so positional references (`#1`) keep
            // lexing. Everything else after `#` (including EOL / EOF) is
            // comment: the ANTLR rule's tail matches '\n' | '\r' | EOF, so
            // a bare `#` at end of line is skipped too.
            if !self.in_hogqlx_tag
                && self.peek_byte(0) == Some(b'#')
                && !matches!(self.peek_byte(1), Some(b'0'..=b'9'))
            {
                self.skip_line_comment();
                continue;
            }
            // `/* ... */` block comment. cpp's ANTLR lexer only matches
            // the comment rule when a closing `*/` is found; an
            // unterminated `/*` falls back to `/` and `*` tokens (which
            // the parser then evaluates per the normal expression
            // grammar). Probe for `*/` first; if missing, leave the
            // characters in place for the regular lex path.
            if self.peek_byte(0) == Some(b'/')
                && self.peek_byte(1) == Some(b'*')
                && self.block_comment_has_closer()
            {
                self.skip_block_comment(self.pos)?;
                continue;
            }
            break;
        }
        Ok(())
    }

    /// Lookahead from a `/*` at `self.pos`: is there a matching `*/`
    /// before EOF? Used by `skip_trivia` to commit to the comment-skip
    /// path only when the comment is well-formed (matching cpp's ANTLR
    /// `/* ... */` rule, which fails to match on unterminated comments).
    fn block_comment_has_closer(&self) -> bool {
        // We're positioned at `/`; the `*` is at +1, content at +2.
        let mut i = self.pos + 2;
        let bytes = self.src;
        while i + 1 < bytes.len() {
            if bytes[i] == b'*' && bytes[i + 1] == b'/' {
                return true;
            }
            i += 1;
        }
        false
    }

    fn skip_line_comment(&mut self) {
        // Caller already established the leading `--`.
        while let Some(b) = self.peek_byte(0) {
            if b == b'\n' {
                break;
            }
            self.pos += 1;
        }
    }

    fn skip_block_comment(&mut self, start: usize) -> Result<(), ParseError> {
        // Caller has confirmed a closing `*/` exists ahead via
        // `block_comment_has_closer` (matching cpp's ANTLR `/*...*/`
        // rule, which fails on unterminated). Just walk to the close.
        self.pos += 2;
        loop {
            match (self.peek_byte(0), self.peek_byte(1)) {
                (Some(b'*'), Some(b'/')) => {
                    self.pos += 2;
                    return Ok(());
                }
                (Some(_), _) => self.pos += 1,
                (None, _) => {
                    // Shouldn't be reachable when callers gate on
                    // `block_comment_has_closer`, but surface as an
                    // error rather than silently advancing.
                    return Err(ParseError::syntax(
                        "unterminated block comment",
                        start,
                        self.pos,
                    ));
                }
            }
        }
    }

    fn lex_number(&mut self, start: usize) -> TokenKind {
        let _ = start;
        // Hex / octal prefix.
        if self.peek_byte(0) == Some(b'0') {
            match self.peek_byte(1) {
                Some(b'x') | Some(b'X')
                    if self.peek_byte(2).is_some_and(|b| b.is_ascii_hexdigit()) =>
                {
                    // Require at least one hex digit after `0x` — the
                    // grammar token is `'0' X HEX_DIGIT+`. A bare `0x`
                    // lexes as `0` + ident `x` (matches the `0b` / `0o`
                    // arms below); cpp's `HEXADECIMAL_LITERAL` rejects
                    // an empty body, so `SELECT 0x AS y` is a parse
                    // error, not a `0x` literal aliased to `y`.
                    self.pos += 2;
                    let prefix_end = self.pos;
                    while self.peek_byte(0).is_some_and(|b| b.is_ascii_hexdigit()) {
                        self.pos += 1;
                    }
                    let int_end = self.pos;
                    // Try to extend to a FLOATING_LITERAL hex-float —
                    //   `HEX (DOT HEX*)? P [+-]? DEC+`. `p`/`P` is the
                    // only marker per grammar; `e`/`E` stays a hex
                    // digit. Requires at least one hex digit in the
                    // mantissa (per `HEXADECIMAL_LITERAL: '0' X HEX+`),
                    // so `0x.8p3` is *not* a hex-float — it stays a
                    // bare `0x` token the parser then rejects. If the
                    // suffix doesn't match cleanly we leave self.pos
                    // at int_end (never commit the `.` / `p` probes).
                    if int_end > prefix_end {
                        let mut probe = 0usize;
                        if self.peek_byte(probe) == Some(b'.') {
                            probe += 1;
                            while self.peek_byte(probe).is_some_and(|b| b.is_ascii_hexdigit()) {
                                probe += 1;
                            }
                        }
                        if matches!(self.peek_byte(probe), Some(b'p') | Some(b'P')) {
                            let mut exp_probe = probe + 1;
                            if matches!(self.peek_byte(exp_probe), Some(b'+') | Some(b'-')) {
                                exp_probe += 1;
                            }
                            if self
                                .peek_byte(exp_probe)
                                .is_some_and(|b| b.is_ascii_digit())
                            {
                                self.pos += exp_probe;
                                while self.peek_byte(0).is_some_and(|b| b.is_ascii_digit()) {
                                    self.pos += 1;
                                }
                            }
                        }
                    }
                    return TokenKind::Number;
                }
                // `0b…` — BINARY_LITERAL (`0b<bin>+`) and the grammar's
                // MALFORMED_BINARY_LITERAL (`0b<dec>+`, e.g. `0b22`).
                // Scan the full decimal-digit run as one Number token;
                // `parse_number_literal` decodes the value and rejects
                // a non-binary digit. The `peek_byte(2)` digit guard
                // keeps a bare `0b` lexing as `0` + ident `b`.
                Some(b'b') | Some(b'B')
                    if self.peek_byte(2).is_some_and(|b| b.is_ascii_digit()) =>
                {
                    self.pos += 2;
                    while self.peek_byte(0).is_some_and(|b| b.is_ascii_digit()) {
                        self.pos += 1;
                    }
                    return TokenKind::Number;
                }
                // `0o…` — OCTAL_PREFIX_LITERAL (`0o<dec>+`). cpp's
                // `VISIT(NumberLiteral)` rejects it; scan the decimal
                // run as one Number token so `parse_number_literal`
                // surfaces that rejection. (`OCT_DIGIT` would stop at
                // `0o9` and strand the `9`; the grammar token spans
                // DEC_DIGIT.) The digit guard keeps `0o` lexing as
                // `0` + ident `o`.
                Some(b'o') | Some(b'O')
                    if self.peek_byte(2).is_some_and(|b| b.is_ascii_digit()) =>
                {
                    self.pos += 2;
                    while self.peek_byte(0).is_some_and(|b| b.is_ascii_digit()) {
                        self.pos += 1;
                    }
                    return TokenKind::Number;
                }
                _ => {}
            }
        }
        // Integer part only — the grammar's `floatingLiteral` rule is
        // `DECIMAL_LITERAL DOT (DECIMAL_LITERAL | OCTAL_LITERAL)?`, i.e.
        // the fractional `.<digits>` tail is assembled at parse time, NOT
        // at lex time. This is deliberate: lexing it eagerly would
        // misread `t.1.2` (tuple access) as `t.<float 1.2>`.
        while self.peek_byte(0).is_some_and(|b| b.is_ascii_digit()) {
            self.pos += 1;
        }
        // FLOATING_LITERAL with an exponent but no fractional digits:
        // `1.e5` / `1.E+5`. The grammar's FLOATING_LITERAL token is
        // `DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS|DASH)? DEC_DIGIT+`, so
        // cpp's lexer munches the whole thing as one token. Consume the
        // `.` here only when an exponent unambiguously follows; `1.2` /
        // `t.1.2` (dot then digit, no `e`) is left for parse-time
        // fractional assembly. The exponent block below then consumes
        // the `e<digits>` tail.
        if self.peek_byte(0) == Some(b'.') && matches!(self.peek_byte(1), Some(b'e') | Some(b'E')) {
            let digit_at = if matches!(self.peek_byte(2), Some(b'+') | Some(b'-')) {
                3
            } else {
                2
            };
            if self.peek_byte(digit_at).is_some_and(|b| b.is_ascii_digit()) {
                self.pos += 1;
            }
        }
        // Exponent
        // Exponent: only consume `e`/`E` when followed by an optional
        // sign and at least one digit (else it's a following identifier
        // like `1eq`).
        if matches!(self.peek_byte(0), Some(b'e') | Some(b'E')) {
            let mut probe = 1;
            if matches!(self.peek_byte(probe), Some(b'+') | Some(b'-')) {
                probe += 1;
            }
            if self.peek_byte(probe).is_some_and(|b| b.is_ascii_digit()) {
                self.pos += probe;
                while self.peek_byte(0).is_some_and(|b| b.is_ascii_digit()) {
                    self.pos += 1;
                }
            }
        }
        TokenKind::Number
    }

    fn lex_ident_or_keyword(&mut self, start: usize) -> TokenKind {
        while let Some(b) = self.peek_byte(0) {
            if b.is_ascii_alphanumeric() || b == b'_' || b == b'$' {
                self.pos += 1;
            } else {
                break;
            }
        }
        let text = &self.src[start..self.pos];
        if let Some(kw) = lookup_keyword(text) {
            TokenKind::Keyword(kw)
        } else {
            TokenKind::Ident
        }
    }

    fn lex_string(&mut self, start: usize) -> Result<TokenKind, ParseError> {
        self.pos += 1; // opening quote
        loop {
            match self.peek_byte(0) {
                None => {
                    return Err(ParseError::syntax(
                        "unterminated string literal",
                        start,
                        self.pos,
                    ))
                }
                Some(b'\'') => {
                    // `''` inside a single-quoted string is an escaped quote.
                    if self.peek_byte(1) == Some(b'\'') {
                        self.pos += 2;
                        continue;
                    }
                    self.pos += 1;
                    return Ok(TokenKind::String);
                }
                Some(b'\\') => {
                    // `ESCAPE_CHAR_COMMON` (`HogQLLexer.common.g4:145`)
                    // is a closed set: `\b \f \r \n \t \0 \a \v \\ \xNN`,
                    // plus the string-literal-only `\'`. cpp rejects
                    // anything else; rust was silently keeping the
                    // backslash + char as literal text.
                    let escape_pos = self.pos;
                    self.pos += 1;
                    match self.peek_byte(0) {
                        None => {} // unterminated — caught by the outer loop's None arm
                        Some(c) => match c {
                            b'b' | b'B' | b'f' | b'F' | b'r' | b'R' | b'n' | b'N' | b't' | b'T'
                            | b'0' | b'a' | b'A' | b'v' | b'V' | b'\\' | b'\'' => {
                                self.pos += 1;
                            }
                            b'x' | b'X' => {
                                // `\xNN` — exactly two hex digits required.
                                self.pos += 1;
                                if self.peek_byte(0).is_some_and(|b| b.is_ascii_hexdigit())
                                    && self.peek_byte(1).is_some_and(|b| b.is_ascii_hexdigit())
                                {
                                    self.pos += 2;
                                } else {
                                    return Err(ParseError::syntax(
                                        r"\x escape requires two hex digits",
                                        escape_pos,
                                        self.pos,
                                    ));
                                }
                            }
                            _ => {
                                return Err(ParseError::syntax(
                                    format!("unrecognised escape '\\{}'", c as char),
                                    escape_pos,
                                    self.pos + 1,
                                ));
                            }
                        },
                    }
                }
                Some(_) => self.pos += 1,
            }
        }
    }

    /// `f'…'` template string. Caller positioned at the leading `f`/`F`,
    /// with byte 1 confirmed to be `'`. Scans the body until the
    /// matching unescaped `'` at the outermost level, descending into
    /// `{ … }` expression blocks via recursive token-level lexing so
    /// nested strings and nested template strings inside `{…}` don't
    /// confuse the boundary search.
    fn lex_template_string(&mut self, start: usize) -> Result<TokenKind, ParseError> {
        self.pos += 2; // consume `f'`
        loop {
            let Some(b) = self.peek_byte(0) else {
                return Err(ParseError::syntax(
                    "unterminated template string",
                    start,
                    self.pos,
                ));
            };
            match b {
                b'\\' => {
                    // Generic escape: consume backslash + the escaped byte.
                    // The body parser re-interprets these.
                    self.pos += 1;
                    if self.peek_byte(0).is_some() {
                        self.pos += 1;
                    }
                }
                b'\'' => {
                    self.pos += 1;
                    return Ok(TokenKind::TemplateString);
                }
                b'{' => {
                    // Switch into expression-token mode for the body of
                    // the `{ … }` block. Recursively call next_token so
                    // nested strings, parens, and nested template
                    // strings are all parsed correctly. Stop when the
                    // matching `}` arrives at depth 0.
                    self.pos += 1; // consume `{`
                    let mut depth: i32 = 1;
                    while depth > 0 {
                        let t = self.next_token()?;
                        match t.kind {
                            TokenKind::LBrace => depth += 1,
                            TokenKind::RBrace => depth -= 1,
                            TokenKind::Eof => {
                                return Err(ParseError::syntax(
                                    "unterminated template-string expression block",
                                    start,
                                    self.pos,
                                ));
                            }
                            _ => {}
                        }
                    }
                }
                _ => self.pos += 1,
            }
        }
    }

    fn lex_quoted_ident(&mut self, start: usize) -> Result<TokenKind, ParseError> {
        let quote = self.src[self.pos];
        self.pos += 1;
        loop {
            match self.peek_byte(0) {
                None => {
                    return Err(ParseError::syntax(
                        "unterminated quoted identifier",
                        start,
                        self.pos,
                    ))
                }
                Some(b) if b == quote => {
                    // Doubled-quote inside the ident is an escaped quote
                    // (grammar: `BACKQUOTE BACKQUOTE` / `QUOTE_DOUBLE
                    // QUOTE_DOUBLE`).
                    if self.peek_byte(1) == Some(quote) {
                        self.pos += 2;
                        continue;
                    }
                    self.pos += 1;
                    return Ok(TokenKind::QuotedIdent);
                }
                Some(b'\\') => {
                    // The grammar's quoted-identifier rule admits:
                    //   `ESCAPE_CHAR_COMMON`     — `\b \f \r \n \t \0 \a \v \\ \xHH`
                    //   `BACKSLASH QUOTE_DOUBLE` — only inside `"..."`
                    //   `BACKSLASH QUOTE_SINGLE` — only inside `` `...` ``
                    // Otherwise `\` is a stray char and the grammar
                    // rejects (`~([\\<quote>])` excludes a bare
                    // backslash). Mirror the closed set so `"\"abc"`
                    // is a single quoted ident containing `"abc`.
                    let escape_pos = self.pos;
                    self.pos += 1;
                    match self.peek_byte(0) {
                        None => {}
                        Some(c) => match c {
                            b'b' | b'B' | b'f' | b'F' | b'r' | b'R' | b'n' | b'N' | b't' | b'T'
                            | b'0' | b'a' | b'A' | b'v' | b'V' | b'\\' => {
                                self.pos += 1;
                            }
                            b'"' if quote == b'"' => self.pos += 1,
                            b'\'' if quote == b'`' => self.pos += 1,
                            b'x' | b'X' => {
                                self.pos += 1;
                                if self.peek_byte(0).is_some_and(|b| b.is_ascii_hexdigit())
                                    && self.peek_byte(1).is_some_and(|b| b.is_ascii_hexdigit())
                                {
                                    self.pos += 2;
                                } else {
                                    return Err(ParseError::syntax(
                                        r"\x escape in quoted identifier requires two hex digits",
                                        escape_pos,
                                        self.pos,
                                    ));
                                }
                            }
                            _ => {
                                return Err(ParseError::syntax(
                                    format!(
                                        "unrecognised escape '\\{}' in quoted identifier",
                                        c as char
                                    ),
                                    escape_pos,
                                    self.pos + 1,
                                ));
                            }
                        },
                    }
                }
                Some(_) => self.pos += 1,
            }
        }
    }
}

/// Case-insensitive keyword lookup against [`KEYWORDS`]. Linear scan over
/// ~120 entries, ASCII-lowered byte compare; well under the cost of any
/// per-token decision. Returns `None` for plain identifiers.
fn lookup_keyword(bytes: &[u8]) -> Option<Kw> {
    for (text, kw) in KEYWORDS {
        if eq_ignore_ascii_case(bytes, text.as_bytes()) {
            return Some(*kw);
        }
    }
    None
}

fn eq_ignore_ascii_case(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter()
        .zip(b.iter())
        .all(|(x, y)| x.eq_ignore_ascii_case(y))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lex_all(src: &str) -> Vec<TokenKind> {
        let mut lx = Lexer::with_pos(src, 0);
        let mut kinds = Vec::new();
        loop {
            let t = lx.next_token().expect("lex error in test corpus");
            if t.kind == TokenKind::Eof {
                break;
            }
            kinds.push(t.kind);
        }
        kinds
    }

    #[test]
    fn arithmetic() {
        assert_eq!(
            lex_all("1 + 2 * 3"),
            vec![
                TokenKind::Number,
                TokenKind::Plus,
                TokenKind::Number,
                TokenKind::Asterisk,
                TokenKind::Number
            ],
        );
    }

    #[test]
    fn keywords_case_insensitive() {
        assert_eq!(lex_all("SELECT")[0], TokenKind::Keyword(Kw::Select));
        assert_eq!(lex_all("select")[0], TokenKind::Keyword(Kw::Select));
        assert_eq!(lex_all("SeLeCt")[0], TokenKind::Keyword(Kw::Select));
    }

    #[test]
    fn tuple_access_is_dot_then_number() {
        assert_eq!(
            lex_all("t.1"),
            vec![TokenKind::Ident, TokenKind::Dot, TokenKind::Number],
        );
    }

    #[test]
    fn strings_with_doubled_quote() {
        let kinds = lex_all("'it''s'");
        assert_eq!(kinds, vec![TokenKind::String]);
    }

    #[test]
    fn line_comment_skipped() {
        assert_eq!(
            lex_all("1 -- the answer\n+ 2"),
            vec![TokenKind::Number, TokenKind::Plus, TokenKind::Number]
        );
    }

    #[test]
    fn block_comment_skipped() {
        assert_eq!(
            lex_all("1 /* nope */ + 2"),
            vec![TokenKind::Number, TokenKind::Plus, TokenKind::Number]
        );
    }

    #[test]
    fn hash_comment_skipped() {
        assert_eq!(
            lex_all("1 # the answer\n+ 2"),
            vec![TokenKind::Number, TokenKind::Plus, TokenKind::Number]
        );
        // A bare `#` at EOF / EOL is a comment too (the ANTLR rule's
        // tail admits '\n' | '\r' | EOF directly after the `#`).
        assert_eq!(lex_all("1 #"), vec![TokenKind::Number]);
        assert_eq!(lex_all("#\n1"), vec![TokenKind::Number]);
        assert_eq!(lex_all("# only a comment"), vec![]);
    }

    #[test]
    fn hash_before_digit_stays_positional_ref() {
        assert_eq!(lex_all("#1"), vec![TokenKind::Hash, TokenKind::Number]);
        assert_eq!(
            lex_all("select #2"),
            vec![
                TokenKind::Keyword(Kw::Select),
                TokenKind::Hash,
                TokenKind::Number
            ],
        );
    }

    #[test]
    fn null_safe_eq_wins_over_lt_eq() {
        assert_eq!(
            lex_all("1 <=> 2"),
            vec![TokenKind::Number, TokenKind::NullSafeEq, TokenKind::Number]
        );
        assert_eq!(
            lex_all("1 <= 2"),
            vec![TokenKind::Number, TokenKind::LtEq, TokenKind::Number]
        );
        assert_eq!(
            lex_all("1 <= > 2"),
            vec![
                TokenKind::Number,
                TokenKind::LtEq,
                TokenKind::Gt,
                TokenKind::Number
            ],
        );
    }

    #[test]
    fn regex_family() {
        assert_eq!(
            lex_all("a ~ b =~ c !~ d ~* e =~* f !~* g"),
            vec![
                TokenKind::Ident,
                TokenKind::RegexSingle,
                TokenKind::Ident,
                TokenKind::RegexDouble,
                TokenKind::Ident,
                TokenKind::NotRegex,
                TokenKind::Ident,
                TokenKind::IRegexSingle,
                TokenKind::Ident,
                TokenKind::IRegexDouble,
                TokenKind::Ident,
                TokenKind::NotIRegex,
                TokenKind::Ident,
            ],
        );
    }
}
