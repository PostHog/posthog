//! Rule JSON can hold any value, so each coercion follows the ECMAScript algorithm for every JSON shape, including the ones that throw.

use std::cmp::Ordering;

use crate::js::{number_to_string, CharOrSurrogate, JsString, JsValue};

/// The callers catch this and fail open, as the TypeScript does.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JsTypeError(pub &'static str);

impl std::fmt::Display for JsTypeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "TypeError: {}", self.0)
    }
}

impl std::error::Error for JsTypeError {}

/// JSON cannot make an own `toString` callable, so `OrdinaryToPrimitive` reaches `valueOf` and throws.
pub fn js_to_string(value: &JsValue) -> Result<JsString, JsTypeError> {
    match value {
        JsValue::Null => Ok(JsString::from("null")),
        JsValue::Bool(b) => Ok(JsString::from(if *b { "true" } else { "false" })),
        JsValue::Number(n) => Ok(JsString::from(number_to_string(*n))),
        JsValue::String(s) => Ok(s.clone()),
        JsValue::Array(items) => {
            // `Array.prototype.join(',')`: null and undefined elements become ''.
            let mut out = JsString::new();
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(",");
                }
                if !matches!(item, JsValue::Null) {
                    out.push_js(&js_to_string(item)?);
                }
            }
            Ok(out)
        }
        JsValue::Object(o) => {
            if o.contains_key("toString") {
                Err(JsTypeError("Cannot convert object to primitive value"))
            } else {
                Ok(JsString::from("[object Object]"))
            }
        }
    }
}

pub fn js_to_string_opt(value: Option<&JsValue>) -> Result<JsString, JsTypeError> {
    match value {
        None => Ok(JsString::from("undefined")),
        Some(v) => js_to_string(v),
    }
}

pub fn is_js_whitespace(c: char) -> bool {
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

pub fn js_trim(s: &str) -> &str {
    s.trim_matches(is_js_whitespace)
}

fn trim_start_js(s: &JsString) -> String {
    // The numeric parsers only read ASCII after the whitespace, so a lone surrogate ends the number.
    let text = s.to_utf8_lossy();
    text.trim_start_matches(is_js_whitespace).to_string()
}

pub fn js_parse_float(s: &JsString) -> f64 {
    parse_float_str(&trim_start_js(s))
}

fn parse_float_str(t: &str) -> f64 {
    let b = t.as_bytes();
    let mut i = 0;
    let mut negative = false;
    if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
        negative = b[i] == b'-';
        i += 1;
    }
    if t[i..].starts_with("Infinity") {
        return if negative {
            f64::NEG_INFINITY
        } else {
            f64::INFINITY
        };
    }
    let digits_start = i;
    let int_start = i;
    while i < b.len() && b[i].is_ascii_digit() {
        i += 1;
    }
    let int_digits = i - int_start;
    let mut frac_digits = 0;
    if i < b.len() && b[i] == b'.' {
        let mut j = i + 1;
        while j < b.len() && b[j].is_ascii_digit() {
            j += 1;
        }
        frac_digits = j - i - 1;
        if int_digits > 0 || frac_digits > 0 {
            i = j;
        }
    }
    if int_digits == 0 && frac_digits == 0 {
        return f64::NAN;
    }
    if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
        let mut j = i + 1;
        if j < b.len() && (b[j] == b'+' || b[j] == b'-') {
            j += 1;
        }
        let exp_start = j;
        while j < b.len() && b[j].is_ascii_digit() {
            j += 1;
        }
        if j > exp_start {
            i = j;
        }
    }
    let mut literal = String::with_capacity(i - digits_start + 2);
    if negative {
        literal.push('-');
    }
    let body = &t[digits_start..i];
    // A leading zero keeps ".5" valid for every Rust version of the float parser.
    if body.starts_with('.') {
        literal.push('0');
    }
    literal.push_str(body);
    literal.parse::<f64>().unwrap_or(f64::NAN)
}

pub fn js_parse_int(s: &str, radix: Option<u32>) -> f64 {
    let t = if s.as_bytes().first().is_some_and(u8::is_ascii_alphanumeric) {
        s
    } else {
        s.trim_start_matches(is_js_whitespace)
    };
    let b = t.as_bytes();
    let mut i = 0;
    let mut negative = false;
    if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
        negative = b[i] == b'-';
        i += 1;
    }
    let mut radix = radix.unwrap_or(0);
    let has_hex_prefix = b.len() >= i + 2 && b[i] == b'0' && (b[i + 1] == b'x' || b[i + 1] == b'X');
    if (radix == 0 || radix == 16) && has_hex_prefix {
        i += 2;
        radix = 16;
    }
    if radix == 0 {
        radix = 10;
    }
    let start = i;
    while i < b.len() && (b[i] as char).is_digit(radix) {
        i += 1;
    }
    if i == start {
        return f64::NAN;
    }
    let digits = &t[start..i];
    let magnitude = if radix == 10 && digits.len() <= 15 {
        // Under 10^15, so the integer is exact as a double.
        digits
            .bytes()
            .fold(0u64, |acc, d| acc * 10 + u64::from(d - b'0')) as f64
    } else if radix == 10 {
        // V8 converts decimal digits with correct rounding, as Rust's parser does.
        digits.parse::<f64>().unwrap_or(f64::NAN)
    } else {
        digits.chars().fold(0f64, |acc, c| {
            acc * radix as f64 + c.to_digit(radix).unwrap_or(0) as f64
        })
    };
    if negative {
        -magnitude
    } else {
        magnitude
    }
}

/// A lone surrogate breaks the final-sigma context, so each valid run lowercases on its own.
pub fn js_to_lower(s: &JsString) -> JsString {
    if let Some(text) = s.as_str() {
        return JsString::from(text.to_lowercase());
    }
    let mut out = JsString::new();
    let mut run = String::new();
    for unit in s.chars_or_surrogates() {
        match unit {
            CharOrSurrogate::Char(c) => run.push(c),
            CharOrSurrogate::Surrogate(u) => {
                out.push_str(&run.to_lowercase());
                run.clear();
                out.push_code_unit(u);
            }
        }
    }
    out.push_str(&run.to_lowercase());
    out
}

pub fn utf16_units(s: &JsString) -> Vec<u16> {
    let mut out = Vec::new();
    for unit in s.chars_or_surrogates() {
        match unit {
            CharOrSurrogate::Char(c) => {
                let mut buf = [0u16; 2];
                out.extend_from_slice(c.encode_utf16(&mut buf));
            }
            CharOrSurrogate::Surrogate(u) => out.push(u),
        }
    }
    out
}

/// UTF-16 code unit order, which differs from UTF-8 byte order above U+FFFF.
pub fn js_compare(a: &JsString, b: &JsString) -> Ordering {
    match (a.as_str(), b.as_str()) {
        (Some(x), Some(y)) => x.encode_utf16().cmp(y.encode_utf16()),
        _ => utf16_units(a).cmp(&utf16_units(b)),
    }
}

/// A needle with a lone surrogate can match half of a pair, so it needs the UTF-16 search.
pub fn js_includes(haystack: &JsString, needle: &JsString) -> bool {
    match (haystack.as_str(), needle.as_str()) {
        (Some(h), Some(n)) => h.contains(n),
        _ => {
            let h = utf16_units(haystack);
            let n = utf16_units(needle);
            n.is_empty() || h.windows(n.len()).any(|w| w == n.as_slice())
        }
    }
}

pub fn js_starts_with(haystack: &JsString, needle: &JsString) -> bool {
    match (haystack.as_str(), needle.as_str()) {
        (Some(h), Some(n)) => h.starts_with(n),
        _ => utf16_units(haystack).starts_with(&utf16_units(needle)),
    }
}

pub fn js_ends_with(haystack: &JsString, needle: &JsString) -> bool {
    match (haystack.as_str(), needle.as_str()) {
        (Some(h), Some(n)) => h.ends_with(n),
        _ => utf16_units(haystack).ends_with(&utf16_units(needle)),
    }
}

/// `Math.round`: halves round toward +Infinity.
pub fn js_math_round(x: f64) -> f64 {
    if !x.is_finite() {
        return x;
    }
    let floor = x.floor();
    let rounded = if x - floor >= 0.5 { floor + 1.0 } else { floor };
    // Math.round(-0.4) is -0; String(-0) is "0", so the sign only matters to division.
    if rounded == 0.0 && x < 0.0 {
        -0.0
    } else {
        rounded
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::js::json_parse;

    fn s(v: &str) -> JsString {
        JsString::from(v)
    }

    #[test]
    fn string_coercion_matches_javascript() {
        let cases = [
            ("null", Some("null")),
            ("true", Some("true")),
            ("1e21", Some("1e+21")),
            ("-0", Some("0")),
            (r#"[1,null,[2,[3]],"a",true]"#, Some("1,,2,3,a,true")),
            (r#"{"a":1}"#, Some("[object Object]")),
            (r#"{"valueOf":1}"#, Some("[object Object]")),
            (r#"{"toString":1}"#, None),
            (r#"[{"toString":"x"}]"#, None),
        ];
        for (json, expected) in cases {
            let value = json_parse(json).unwrap();
            assert_eq!(
                js_to_string(&value).ok().map(|s| s.to_string()),
                expected.map(str::to_string),
                "{json}"
            );
        }
    }

    #[test]
    fn parse_float_matches_javascript() {
        let cases: [(&str, f64); 16] = [
            ("  12.5abc", 12.5),
            ("\u{3000}\u{FEFF}-.5", -0.5),
            ("1.e3", 1000.0),
            ("1e", 1.0),
            ("1e+", 1.0),
            ("1e-2x", 0.01),
            (".e5", f64::NAN),
            ("-Infinityx", f64::NEG_INFINITY),
            ("+Infinity", f64::INFINITY),
            ("infinity", f64::NAN),
            ("0x10", 0.0),
            ("\"42\"", f64::NAN),
            ("", f64::NAN),
            ("1_000", 1.0),
            ("9007199254740993", 9007199254740992.0),
            ("1e400", f64::INFINITY),
        ];
        for (input, expected) in cases {
            let got = js_parse_float(&s(input));
            assert!(
                got == expected || (got.is_nan() && expected.is_nan()),
                "parseFloat({input:?}) = {got}"
            );
        }
        assert!(js_parse_float(&s("-0")).is_sign_negative());
    }

    #[test]
    fn parse_int_matches_javascript() {
        let cases: [(&str, Option<u32>, f64); 9] = [
            (" 42px", Some(10), 42.0),
            ("-17", Some(10), -17.0),
            ("0x1A", None, 26.0),
            ("0x1A", Some(10), 0.0),
            ("1.9", Some(10), 1.0),
            ("abc", Some(10), f64::NAN),
            ("\u{00A0}7", None, 7.0),
            ("+0x", None, f64::NAN),
            ("08", None, 8.0),
        ];
        for (input, radix, expected) in cases {
            let got = js_parse_int(input, radix);
            assert!(
                got == expected || (got.is_nan() && expected.is_nan()),
                "parseInt({input:?}, {radix:?}) = {got}"
            );
        }
    }

    #[test]
    fn string_order_is_utf16() {
        // U+FF61 is above the surrogate range in UTF-16 but below U+1F600 in UTF-8.
        assert_eq!(js_compare(&s("\u{1F600}"), &s("\u{FF61}")), Ordering::Less);
        assert_eq!(
            s("\u{1F600}").as_str().unwrap().cmp("\u{FF61}"),
            Ordering::Greater
        );
    }

    #[test]
    fn a_lone_surrogate_needle_can_match_half_a_pair() {
        let rocket = s("a\u{1F680}");
        let lone = match json_parse(r#""\ude80""#).unwrap() {
            JsValue::String(s) => s,
            _ => unreachable!(),
        };
        assert!(js_includes(&rocket, &lone));
        assert!(js_ends_with(&rocket, &lone));
        assert!(!js_starts_with(&rocket, &lone));
    }

    #[test]
    fn math_round_rounds_halves_up() {
        assert_eq!(js_math_round(2.5), 3.0);
        assert_eq!(js_math_round(-2.5), -2.0);
        assert_eq!(js_math_round(0.49999999999999994), 0.0);
        assert!(js_math_round(-0.4).is_sign_negative());
    }
}
