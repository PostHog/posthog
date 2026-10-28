use json5::char::is_json5_line_terminator;
use serde::Deserialize;

/// serde_json's default recursion limit is also 128, and the form-urlencoded path applies it.
pub const MAX_NESTING_DEPTH: usize = 128;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("arrays and objects nest deeper than {MAX_NESTING_DEPTH} levels")]
    TooDeep,
    #[error(transparent)]
    Syntax(#[from] json5::Error),
}

/// Parses JSON5 like [`json5::from_str`], but rejects input that nests deeper than
/// [`MAX_NESTING_DEPTH`] before the parse starts.
///
/// json5 recurses once per nested array or object and has no depth limit. Deep enough input
/// overflows the thread stack, and Rust aborts the whole process on a stack overflow.
pub fn from_str<'a, T: Deserialize<'a>>(input: &'a str) -> Result<T, Error> {
    if exceeds_max_depth(input) {
        return Err(Error::TooDeep);
    }
    Ok(json5::from_str(input)?)
}

#[derive(Clone, Copy)]
enum Lexeme {
    Code,
    String { quote: char },
    LineComment,
    BlockComment,
}

/// Brackets inside strings and comments are not structure, so the scan ends strings and comments
/// where json5 ends them. A scan that counts fewer levels than json5 recurses into would let a
/// crafted body through. Where the two disagree, the input is invalid JSON5 at that point, and
/// json5 returns a syntax error there instead of recursing further.
fn exceeds_max_depth(input: &str) -> bool {
    let mut chars = input.chars().peekable();
    let mut lexeme = Lexeme::Code;
    let mut depth = 0;

    while let Some(c) = chars.next() {
        lexeme = match lexeme {
            Lexeme::Code => match c {
                '[' | '{' => {
                    depth += 1;
                    if depth > MAX_NESTING_DEPTH {
                        return true;
                    }
                    Lexeme::Code
                }
                ']' | '}' => {
                    depth = depth.saturating_sub(1);
                    Lexeme::Code
                }
                '"' | '\'' => Lexeme::String { quote: c },
                '/' if chars.next_if_eq(&'/').is_some() => Lexeme::LineComment,
                '/' if chars.next_if_eq(&'*').is_some() => Lexeme::BlockComment,
                _ => Lexeme::Code,
            },
            Lexeme::String { quote } => match c {
                '\\' => {
                    chars.next();
                    lexeme
                }
                c if c == quote => Lexeme::Code,
                _ => lexeme,
            },
            Lexeme::LineComment if is_json5_line_terminator(c) => Lexeme::Code,
            Lexeme::BlockComment if c == '*' && chars.next_if_eq(&'/').is_some() => Lexeme::Code,
            Lexeme::LineComment | Lexeme::BlockComment => lexeme,
        };
    }

    false
}

#[cfg(test)]
mod tests {
    use rstest::rstest;
    use serde_json::Value;

    use super::*;

    fn nested_arrays(levels: usize) -> String {
        "[".repeat(levels) + &"]".repeat(levels)
    }

    #[rstest]
    #[case::at_the_limit(nested_arrays(MAX_NESTING_DEPTH))]
    #[case::brackets_in_double_quoted_string(format!(r#"["{}"]"#, "[{".repeat(MAX_NESTING_DEPTH)))]
    #[case::brackets_in_single_quoted_string(format!("['{}']", "[{".repeat(MAX_NESTING_DEPTH)))]
    #[case::brackets_in_comments(format!("/* {0} */ [] // {0}", "[{".repeat(MAX_NESTING_DEPTH)))]
    fn parses_input_within_the_limit(#[case] input: String) {
        let parsed = from_str::<Value>(&input);
        assert!(parsed.is_ok(), "{parsed:?}");
    }

    #[rstest]
    #[case::arrays(nested_arrays(MAX_NESTING_DEPTH + 1))]
    #[case::objects(
        r#"{"a":"#.repeat(MAX_NESTING_DEPTH + 1) + "1" + &"}".repeat(MAX_NESTING_DEPTH + 1)
    )]
    #[case::after_line_comment_ended_by_line_separator(
        format!("// note\u{2028}{}", nested_arrays(MAX_NESTING_DEPTH + 1))
    )]
    #[case::after_block_comment(format!("/* note */{}", nested_arrays(MAX_NESTING_DEPTH + 1)))]
    #[case::after_escaped_quote(format!(r#"["a\"b", {}]"#, nested_arrays(MAX_NESTING_DEPTH)))]
    #[case::after_double_quote_in_single_quoted_string(
        format!(r#"['"', {}]"#, nested_arrays(MAX_NESTING_DEPTH))
    )]
    fn rejects_nesting_past_the_limit(#[case] input: String) {
        let parsed = from_str::<Value>(&input);
        assert!(matches!(parsed, Err(Error::TooDeep)), "{parsed:?}");
    }
}
