//! ECMAScript `Number::toString(10)`, which `String(n)` and `JSON.stringify` use.
//!
//! Rust's `{:e}` gives the same shortest round-trip digits as ECMAScript; only the layout
//! differs (where JavaScript switches to exponent form, and `e+21` instead of `e21`).

pub fn number_to_string(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_string();
    }
    if value == 0.0 {
        return "0".to_string();
    }
    if value.is_infinite() {
        return if value > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    let mut out = String::new();
    if value < 0.0 {
        out.push('-');
    }
    let sci = format!("{:e}", value.abs());
    let (mantissa, exp) = sci.split_once('e').expect("LowerExp has an exponent");
    let exp: i32 = exp.parse().expect("exponent is an integer");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let k = digits.len() as i32;
    // n is the position of the decimal point relative to the digit string.
    let n = exp + 1;
    if k <= n && n <= 21 {
        out.push_str(&digits);
        out.extend(std::iter::repeat_n('0', (n - k) as usize));
    } else if 0 < n && n <= 21 {
        out.push_str(&digits[..n as usize]);
        out.push('.');
        out.push_str(&digits[n as usize..]);
    } else if -6 < n && n <= 0 {
        out.push_str("0.");
        out.extend(std::iter::repeat_n('0', (-n) as usize));
        out.push_str(&digits);
    } else {
        out.push_str(&digits[..1]);
        if k > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if n - 1 < 0 { '-' } else { '+' });
        out.push_str(&(n - 1).abs().to_string());
    }
    out
}

#[cfg(test)]
mod tests {
    use super::number_to_string;

    #[test]
    fn matches_ecmascript_number_to_string() {
        let cases: &[(f64, &str)] = &[
            (1e21, "1e+21"),
            (1e20, "100000000000000000000"),
            (123e20, "1.23e+22"),
            (1e-7, "1e-7"),
            (1.5e-7, "1.5e-7"),
            (0.000001, "0.000001"),
            (0.1 + 0.2, "0.30000000000000004"),
            (-0.0, "0"),
            (5e-324, "5e-324"),
            (9007199254740993.0, "9007199254740992"),
            (12345678901234567890.0, "12345678901234567000"),
            (1.0, "1"),
            (-3.5, "-3.5"),
            (42.0, "42"),
            (f64::MAX, "1.7976931348623157e+308"),
        ];
        for (value, expected) in cases {
            assert_eq!(number_to_string(*value), *expected, "{value}");
        }
    }
}
