//! Template-string body splitter for `f'…'` literals and the standalone
//! `parse_full_template_string` entry point.
//!
//! The body is a sequence of literal chunks separated by `{ expr }`
//! blocks. We sub-parse each block by spawning a fresh [`Parser`] seeked
//! to the byte after `{`, then advance past the closing `}` it stopped
//! on.

use serde_json::Value;

use super::Parser;
use crate::emit;
use crate::error::ParseError;
use crate::lex::{Lexer, TokenKind};

/// Split a template-string body into literal chunks and embedded
/// expression blocks, then wrap as either a bare `Constant` (no
/// `{ … }` blocks) or a `Call("concat", chunks)`.
///
/// The body is the inner contents of either an `f'…'` literal or a
/// `parse_full_template_string` input — neither form includes the
/// surrounding quotes. Escapes follow cpp's f-string `STRING_TEXT`
/// lexer rule and the `parse_string_text_ctx` visitor: `\{`, `\'`,
/// `\\`, `\n`, `\t`, `\r`, `\b`, `\f`, `\a`, `\v` decode in place,
/// `\0` contributes nothing, and `\xHH` is kept verbatim. Any other
/// `\X` is one the lexer rule cannot span — cpp ends the `STRING_TEXT`
/// token there, drops the `\X`, and starts a fresh token, so the body
/// splitter does the same: it closes the current literal chunk and
/// opens a new one (an extra `concat` argument).
pub(super) fn parse_template_body(src: &str) -> Result<Value, ParseError> {
    let bytes = src.as_bytes();
    let mut chunks: Vec<Value> = Vec::new();
    let mut literal = String::new();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if c == b'\\' && i + 1 < bytes.len() {
            let next = bytes[i + 1];
            // Escapes the f-string `STRING_TEXT` lexer rule admits
            // (`BACKSLASH LBRACE` / `BACKSLASH QUOTE_SINGLE` /
            // `ESCAPE_CHAR_COMMON`) stay inside the current literal
            // chunk; their decoded value follows the cpp
            // `parse_string_text_ctx` + `replace_common_escape_characters`
            // pair — note `\0` is dropped (NUL ignored) and `\xHH` is
            // left verbatim (the cpp escape map has no `\x` case).
            match next {
                b'{' => literal.push('{'),
                b'\'' => literal.push('\''),
                b'\\' => literal.push('\\'),
                b'n' => literal.push('\n'),
                b't' => literal.push('\t'),
                b'r' => literal.push('\r'),
                b'b' => literal.push('\u{08}'),
                b'f' => literal.push('\u{0C}'),
                b'a' => literal.push('\u{07}'),
                b'v' => literal.push('\u{0B}'),
                b'0' => { /* NUL is ignored, contributing nothing */ }
                b'x' if i + 4 <= bytes.len()
                    && bytes[i + 2].is_ascii_hexdigit()
                    && bytes[i + 3].is_ascii_hexdigit() =>
                {
                    literal.push_str(&src[i..i + 4]);
                    i += 4;
                    continue;
                }
                _ => {
                    // An escape the lexer rule cannot span: cpp's
                    // `STRING_TEXT` token ends here, the offending
                    // `\X` is dropped by lexer error recovery, and a
                    // fresh `STRING_TEXT` (a new concat chunk) begins.
                    if !literal.is_empty() {
                        chunks.push(emit::constant(Value::String(std::mem::take(&mut literal))));
                    }
                    i += 2;
                    continue;
                }
            }
            i += 2;
            continue;
        }
        if c == b'{' {
            if !literal.is_empty() {
                chunks.push(emit::constant(Value::String(std::mem::take(&mut literal))));
            }
            // Locate the matching `}` with a raw-lexer brace scan
            // before sub-parsing. The Lexer consumes string / quoted-
            // identifier / nested-template tokens whole, so a `}`
            // inside a literal is never miscounted. The expression is
            // then sub-parsed from a slice that *ends at* the `}` —
            // this is what keeps the sub-parser's two-token lookahead
            // from lexing on into the literal template text that
            // follows the block. That trailing text is not a valid
            // default-mode token stream (a bare `\` escape, for one),
            // so letting the lookahead reach it spuriously fails the
            // whole template.
            let mut scan = Lexer::with_pos(src, i + 1);
            let mut depth: i32 = 1;
            let close_brace_start = loop {
                let t = scan.next_token()?;
                match t.kind {
                    TokenKind::LBrace => depth += 1,
                    TokenKind::RBrace => {
                        depth -= 1;
                        if depth == 0 {
                            break t.start;
                        }
                    }
                    TokenKind::Eof => {
                        return Err(ParseError::syntax(
                            "expected `}` to close template expression",
                            i,
                            src.len(),
                        ));
                    }
                    _ => {}
                }
            };
            // Sub-parse the brace-internal expression. The slice stops
            // at the `}`, so the sub-parser sees EOF where the block
            // ends instead of the surrounding literal text.
            let mut sub = Parser::with_pos(&src[..close_brace_start], i + 1)?;
            let expr = sub.parse_expr_bp(0)?;
            if !matches!(sub.peek(), TokenKind::Eof) {
                return Err(ParseError::syntax(
                    format!(
                        "expected `}}` to close template expression, got {:?}",
                        sub.peek()
                    ),
                    sub.peek0.start,
                    sub.peek0.end,
                ));
            }
            i = close_brace_start + 1; // step past the closing `}`
            chunks.push(expr);
            continue;
        }
        // Generic char: decode the next UTF-8 scalar so we copy whole
        // codepoints, not stray bytes.
        let rest = &src[i..];
        let ch = rest.chars().next().expect("non-empty rest");
        literal.push(ch);
        i += ch.len_utf8();
    }
    if !literal.is_empty() {
        chunks.push(emit::constant(Value::String(literal)));
    }
    if chunks.is_empty() {
        return Ok(emit::constant(Value::String(String::new())));
    }
    // A single-chunk template IS that chunk — whether a literal
    // `Constant` or one `{ … }` substitution (`f'{x}'` is just `x`).
    // cpp only wraps in `concat` when there are two or more pieces.
    if chunks.len() == 1 {
        return Ok(chunks.remove(0));
    }
    Ok(emit::call("concat", chunks))
}
