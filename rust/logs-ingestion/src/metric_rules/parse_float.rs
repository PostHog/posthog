//! JavaScript `parseFloat`.

use crate::js::{CharOrSurrogate, JsString};

/// ECMAScript WhiteSpace and LineTerminator, which `parseFloat` skips at the start.
/// Rust's `char::is_whitespace` differs: it includes U+0085 and excludes U+FEFF.
fn is_js_whitespace(c: char) -> bool {
    matches!(
        c,
        '\u{0009}'
            | '\u{000A}'
            | '\u{000B}'
            | '\u{000C}'
            | '\u{000D}'
            | '\u{0020}'
            | '\u{00A0}'
            | '\u{1680}'
            | '\u{2000}'
            ..='\u{200A}'
                | '\u{2028}'
                | '\u{2029}'
                | '\u{202F}'
                | '\u{205F}'
                | '\u{3000}'
                | '\u{FEFF}'
    )
}

/// `parseFloat(s)`: the longest prefix that is a StrDecimalLiteral, after leading whitespace.
/// NaN when there is no such prefix.
pub fn js_parse_float(s: &JsString) -> f64 {
    // Only ASCII can be part of the literal, so a lone surrogate ends it like any other char.
    let mut chars = s.chars_or_surrogates().peekable();
    while let Some(CharOrSurrogate::Char(c)) = chars.peek() {
        if !is_js_whitespace(*c) {
            break;
        }
        chars.next();
    }
    let rest: Vec<u8> = chars
        .map_while(|u| match u {
            CharOrSurrogate::Char(c) if c.is_ascii() => Some(c as u8),
            _ => None,
        })
        .collect();
    parse_prefix(&rest)
}

fn parse_prefix(b: &[u8]) -> f64 {
    let mut i = 0;
    let negative = match b.first() {
        Some(b'-') => {
            i += 1;
            true
        }
        Some(b'+') => {
            i += 1;
            false
        }
        _ => false,
    };
    if b[i..].starts_with(b"Infinity") {
        return if negative {
            f64::NEG_INFINITY
        } else {
            f64::INFINITY
        };
    }
    let digits = |from: usize| b[from..].iter().take_while(|c| c.is_ascii_digit()).count();
    let start = i;
    let int_digits = digits(i);
    i += int_digits;
    let mut frac_digits = 0;
    if b.get(i) == Some(&b'.') {
        frac_digits = digits(i + 1);
        if int_digits > 0 || frac_digits > 0 {
            i += 1 + frac_digits;
        }
    }
    if int_digits == 0 && frac_digits == 0 {
        return f64::NAN;
    }
    if matches!(b.get(i), Some(b'e' | b'E')) {
        let mut j = i + 1;
        if matches!(b.get(j), Some(b'+' | b'-')) {
            j += 1;
        }
        let exp_digits = digits(j);
        if exp_digits > 0 {
            i = j + exp_digits;
        }
    }
    let text = std::str::from_utf8(&b[start..i]).expect("ASCII prefix");
    // Rust's parse is correctly rounded, as ECMAScript requires.
    let magnitude: f64 = text.parse().expect("prefix is a decimal literal");
    if negative {
        -magnitude
    } else {
        magnitude
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_javascript_parse_float() {
        let nan = f64::NAN;
        let cases: &[(&str, f64)] = &[
            ("42", 42.0),
            ("-3.5", -3.5),
            ("12.5abc", 12.5),
            ("  \u{FEFF}\u{3000}7", 7.0),
            ("\u{0085}7", nan),
            (".5", 0.5),
            ("5.", 5.0),
            ("-.5e1", -5.0),
            ("1e", 1.0),
            ("1e+", 1.0),
            ("1e-2x", 0.01),
            (".", nan),
            ("-", nan),
            ("", nan),
            ("Infinity", f64::INFINITY),
            ("-Infinityx", f64::NEG_INFINITY),
            ("infinity", nan),
            ("0x10", 0.0),
            ("1e999", f64::INFINITY),
            ("true", nan),
            ("1_000", 1.0),
        ];
        for (input, expected) in cases {
            let actual = js_parse_float(&JsString::from(*input));
            if expected.is_nan() {
                assert!(actual.is_nan(), "parseFloat({input:?}) = {actual}");
            } else {
                assert_eq!(actual, *expected, "parseFloat({input:?})");
            }
        }
        assert!(js_parse_float(&JsString::from("-0")).is_sign_negative());
    }
}
