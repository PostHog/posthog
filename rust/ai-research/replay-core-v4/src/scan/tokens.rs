//! A streaming JSON tokenizer that reads every byte once.
//!
//! The span scanner's skip is linear for one value, but a walk that skips a node to read its fields and then descends
//! into its children reads each subtree once per ancestor. A DOM is deep, so the inspector walks tokens instead.

use crate::bytescan::{self as scan, Span};

/// Deeper nesting is hostile input, not a page.
pub(crate) const MAX_DEPTH: usize = 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Token {
    ObjectStart,
    ObjectEnd,
    ArrayStart,
    ArrayEnd,
    /// An object key, without its quotes. An escaped key never matches a key the caller compares bytes against.
    Key {
        span: Span,
        escaped: bool,
    },
    /// A string with its quotes, or a number, `true`, `false` or `null`.
    Value(Span),
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Container {
    Object { expect_key: bool },
    Array,
}

pub struct Tokens<'b> {
    bytes: &'b [u8],
    pos: usize,
    end: usize,
    stack: Vec<Container>,
    /// Set when the input is malformed or too deep. The iterator then ends.
    pub failed: bool,
}

impl<'b> Tokens<'b> {
    /// Tokenizes the value at `span`.
    pub fn new(bytes: &'b [u8], span: Span) -> Self {
        Self {
            bytes,
            pos: span.0,
            end: span.1,
            stack: Vec::new(),
            failed: false,
        }
    }

    fn fail(&mut self) -> Option<Token> {
        self.failed = true;
        None
    }
}

impl Iterator for Tokens<'_> {
    type Item = Token;

    fn next(&mut self) -> Option<Token> {
        loop {
            self.pos = scan::skip_ws(self.bytes, self.pos);
            if self.pos >= self.end || self.failed {
                return None;
            }
            let byte = self.bytes[self.pos];
            match byte {
                b'{' | b'[' => {
                    if self.stack.len() >= MAX_DEPTH {
                        return self.fail();
                    }
                    self.pos += 1;
                    if byte == b'{' {
                        self.stack.push(Container::Object { expect_key: true });
                        return Some(Token::ObjectStart);
                    }
                    self.stack.push(Container::Array);
                    return Some(Token::ArrayStart);
                }
                b'}' | b']' => {
                    self.pos += 1;
                    return match (self.stack.pop(), byte) {
                        (Some(Container::Object { .. }), b'}') => Some(Token::ObjectEnd),
                        (Some(Container::Array), b']') => Some(Token::ArrayEnd),
                        _ => self.fail(),
                    };
                }
                b',' => {
                    self.pos += 1;
                    if let Some(Container::Object { expect_key }) = self.stack.last_mut() {
                        *expect_key = true;
                    }
                }
                b':' => self.pos += 1,
                b'"' => {
                    let Ok(end) = scan::skip_string(self.bytes, self.pos) else {
                        return self.fail();
                    };
                    let span = (self.pos, end);
                    self.pos = end;
                    if let Some(Container::Object {
                        expect_key: expect_key @ true,
                    }) = self.stack.last_mut()
                    {
                        *expect_key = false;
                        let key = (span.0 + 1, span.1 - 1);
                        return Some(Token::Key {
                            span: key,
                            escaped: self.bytes[key.0..key.1].contains(&b'\\'),
                        });
                    }
                    return Some(Token::Value(span));
                }
                _ => {
                    let start = self.pos;
                    while self.pos < self.end
                        && !matches!(
                            self.bytes[self.pos],
                            b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r'
                        )
                    {
                        self.pos += 1;
                    }
                    return Some(Token::Value((start, self.pos)));
                }
            }
        }
    }
}
