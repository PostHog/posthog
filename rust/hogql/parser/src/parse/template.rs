//! Template-string body splitter for `f'…'` literals and the standalone
//! `parse_full_template_string` entry point.
//!
//! The body is a sequence of literal chunks separated by `{ expr }`
//! blocks. We sub-parse each block by spawning a fresh [`Parser`] seeked
//! to the byte after `{`, then advance past the closing `}` it stopped
//! on.

use super::Parser;
use crate::emit::Emitter;
use crate::error::ParseError;
use crate::lex::{Lexer, TokenKind};

/// Split a template-string body into literal chunks and embedded
/// expression blocks, then wrap as either a bare `Constant` (no
/// `{ … }` blocks) or a `Call("concat", chunks)`.
///
/// `full_src` is the source the outer parser sees; `body_offset` is the
/// byte offset where the template body begins (just past `f'`) and
/// `body_end` is the byte offset of the closing `'`. Positions emitted
/// on literal Constants are absolute in `full_src`, matching cpp's
/// `STRING_TEXT` ctx spans. Sub-parsed `{ … }` expression chunks already
/// get absolute positions because their sub-parser sees the full source
/// up to the closing brace.
///
/// Escapes follow cpp's f-string `STRING_TEXT` lexer rule and the
/// `parse_string_text_ctx` visitor: `\{`, `\'`, `\\`, `\n`, `\t`, `\r`,
/// `\b`, `\f`, `\a`, `\v` decode in place, `\0` contributes nothing,
/// and `\xHH` is kept verbatim. Any other `\X` is one the lexer rule
/// cannot span — cpp ends the `STRING_TEXT` token there, drops the
/// `\X`, and starts a fresh token, so the body splitter does the same:
/// it closes the current literal chunk and opens a new one (an extra
/// `concat` argument).
pub(super) fn parse_template_body<E: Emitter + Clone>(
    emit: &E,
    full_src: &str,
    body_offset: usize,
    body_end: usize,
) -> Result<E::Value, ParseError> {
    let body = &full_src[body_offset..body_end];
    let bytes = body.as_bytes();
    // (start_in_body, end_in_body, value) — absolute positions wrap on
    // each push so callers receive cpp-shaped `start` / `end` spans.
    let mut chunks: Vec<E::Value> = Vec::new();
    let mut literal = String::new();
    let mut literal_start = 0; // byte offset within `body` where the current literal began
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        // `\` always introduces an escape: cpp's `STRING_TEXT` lexer
        // sweeps over `ESCAPE_CHAR_COMMON`, then `parse_string_text_ctx`
        // decodes recognised ones and drops the byte for unrecognised
        // ones. We do both in one pass.
        if c == b'\\' && i + 1 < bytes.len() {
            let next = bytes[i + 1];
            match next {
                b'{' => {
                    literal.push('{');
                    i += 2;
                    continue;
                }
                b'}' => {
                    literal.push('}');
                    i += 2;
                    continue;
                }
                b'\'' => {
                    literal.push('\'');
                    i += 2;
                    continue;
                }
                b'\\' => {
                    literal.push('\\');
                    i += 2;
                    continue;
                }
                b'n' => {
                    literal.push('\n');
                    i += 2;
                    continue;
                }
                b't' => {
                    literal.push('\t');
                    i += 2;
                    continue;
                }
                b'r' => {
                    literal.push('\r');
                    i += 2;
                    continue;
                }
                b'b' => {
                    literal.push('\u{08}');
                    i += 2;
                    continue;
                }
                b'f' => {
                    literal.push('\u{0C}');
                    i += 2;
                    continue;
                }
                b'a' => {
                    literal.push('\u{07}');
                    i += 2;
                    continue;
                }
                b'v' => {
                    literal.push('\u{0B}');
                    i += 2;
                    continue;
                }
                b'0' => {
                    // cpp's `parse_string_text_ctx` drops `\0` (NUL is
                    // not emitted, contributing nothing to the output).
                    i += 2;
                    continue;
                }
                b'x' => {
                    // cpp keeps `\xHH` verbatim as `\xHH` — the lexer
                    // doesn't decode it, and `parse_string_text_ctx`
                    // copies the backslash + the 'x' + the two hex
                    // digits literally.
                    literal.push('\\');
                    i += 1;
                    continue;
                }
                _ => {
                    // Unknown `\X` — cpp ends the current `STRING_TEXT`
                    // token at the `\`, then starts a fresh token on
                    // the next valid character. The body splitter
                    // models that by closing the current literal chunk
                    // and dropping the two-byte `\X` sequence.
                    if !literal.is_empty() {
                        chunks.push(wrap_literal_chunk(
                            emit,
                            full_src,
                            std::mem::take(&mut literal),
                            body_offset + literal_start,
                            body_offset + i,
                        ));
                    }
                    i += 2;
                    literal_start = i;
                    continue;
                }
            }
        }
        if c == b'{' {
            if !literal.is_empty() {
                chunks.push(wrap_literal_chunk(
                    emit,
                    full_src,
                    std::mem::take(&mut literal),
                    body_offset + literal_start,
                    body_offset + i,
                ));
            }
            // The body inside `{ … }` is parsed as a `columnExpr`. cpp's
            // `parse_string_template` lifts the `{ … }` lexer mode into
            // a sub-`columnExpr` parse — paren-balance via the
            // sub-lexer so nested `{}` (Hog blocks, dicts) within the
            // expression don't terminate the substitution. We mirror
            // that here by lexing through `{`/`}` until the matching
            // close-brace lands at depth zero.
            //
            // Positions stay absolute in `full_src`. cpp's grammar
            // emits ctx spans relative to the *outer* source — the
            // visitor doesn't reset them per template chunk — so the
            // sub-parser's nodes share an `offset` space with the
            // whole template.
            //
            // Scan via the FULL source so the lexer's positions are
            // absolute (`scan.next_token()?.start` is a `full_src`
            // offset), then sub-parse from the same full source so the
            // emitted positions stay absolute too.
            let abs_brace_start = body_offset + i;
            let mut scan = Lexer::with_pos(full_src, abs_brace_start + 1);
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
                            abs_brace_start,
                            body_end,
                        ));
                    }
                    _ => {}
                }
            };
            // Sub-parse the brace-internal expression. The slice stops
            // at the `}`, so the sub-parser sees EOF where the block
            // ends instead of the surrounding literal text. Slicing
            // `full_src` keeps the absolute offsets up to that point —
            // a Parser::with_pos started at `abs_brace_start + 1`
            // emits absolute positions in `full_src`.
            let mut sub = Parser::<'_, E>::with_pos_emit(
                &full_src[..close_brace_start],
                abs_brace_start + 1,
                emit.clone(),
            )?;
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
            // Convert absolute close-brace offset back to body-relative
            // for the byte-level scan loop.
            i = close_brace_start - body_offset + 1;
            literal_start = i;
            chunks.push(expr);
            continue;
        }
        // Generic char: decode the next UTF-8 scalar so we copy whole
        // codepoints, not stray bytes.
        let rest = &body[i..];
        let ch = rest.chars().next().expect("non-empty rest");
        literal.push(ch);
        i += ch.len_utf8();
    }
    if !literal.is_empty() {
        chunks.push(wrap_literal_chunk(
            emit,
            full_src,
            literal,
            body_offset + literal_start,
            body_offset + i,
        ));
    }
    if chunks.is_empty() {
        // Empty body — cpp emits an empty-string Constant spanning the
        // body (between the quotes). Position it accordingly.
        return Ok(wrap_literal_chunk(
            emit,
            full_src,
            String::new(),
            body_offset,
            body_end,
        ));
    }
    // A single-chunk template IS that chunk — whether a literal
    // `Constant` or one `{ … }` substitution (`f'{x}'` is just `x`).
    // cpp only wraps in `concat` when there are two or more pieces.
    if chunks.len() == 1 {
        return Ok(chunks.remove(0));
    }
    // The outer concat Call wraps the chunks. Its position spans the
    // whole template body — the caller adds the outer wrap based on
    // the `f'…'` token bounds via the standard pratt-loop wrap.
    Ok(emit.call("concat", chunks))
}

/// Wrap a literal-chunk Constant with the cpp `STRING_TEXT` ctx span.
/// Positions are absolute byte offsets in the full source. The
/// helper directly assembles the cpp-shape `{line, column, offset}`
/// envelope without spinning up a fresh `Parser` (which would try to
/// lex the rest of the source starting from `start`, and inside an
/// `f'…'` body that lex would fail on the trailing unclosed `'`).
fn wrap_literal_chunk<E: Emitter>(
    emit: &E,
    full_src: &str,
    value: String,
    start: usize,
    end: usize,
) -> E::Value {
    let constant = emit.constant(emit.string(&value));
    let start_pos = pos_in_source(emit, full_src, start);
    let end_pos = pos_in_source(emit, full_src, end);
    emit.with_pos(constant, start_pos, end_pos)
}

/// Compute the cpp-shape `{line, column, offset}` envelope for an
/// absolute byte offset in `src`. `offset` is the character index
/// (Unicode code points), matching cpp's ANTLR `getStartIndex()`
/// semantics; `column` is character-position-in-line.
fn pos_in_source<E: Emitter>(emit: &E, src: &str, byte_offset: usize) -> E::Value {
    // Line: count `\n` bytes before `byte_offset`.
    let preceding = &src[..byte_offset.min(src.len())];
    let line_breaks = preceding.bytes().filter(|&b| b == b'\n').count();
    let line = (line_breaks + 1) as u32;
    // Column + char offset: count chars in the preceding-source slice.
    let line_start = preceding.rfind('\n').map(|i| i + 1).unwrap_or(0);
    let column = src[line_start..byte_offset.min(src.len())].chars().count() as u32;
    let char_offset = if src.is_ascii() {
        byte_offset
    } else {
        preceding.chars().count()
    };
    emit.position(line, column, char_offset)
}
