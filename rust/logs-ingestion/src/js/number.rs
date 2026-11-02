//! ECMAScript `Number::toString(10)`, which `String(n)` and `JSON.stringify` use.
//!
//! Rust's `{:e}` gives the shortest round-trip digit count. ECMAScript breaks a tie between two
//! equally close shortest candidates toward the even digit, so an odd last digit is checked
//! against the exactly rounded form, which rounds ties to even.

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
    let sci = shortest_scientific(value.abs());
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

fn shortest_scientific(value: f64) -> String {
    let shortest = format!("{value:e}");
    let mantissa = shortest.split_once('e').map_or("", |(m, _)| m);
    let last_is_odd = mantissa.bytes().last().is_some_and(|d| (d - b'0') % 2 == 1);
    if !last_is_odd {
        return shortest;
    }
    let digits = mantissa.bytes().filter(u8::is_ascii_digit).count();
    let exact = format!("{:.*e}", digits - 1, value);
    // At a power of two the lower gap is narrower, so the nearest candidate can miss.
    if exact != shortest && exact.parse::<f64>() == Ok(value) {
        exact
    } else {
        shortest
    }
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
            (f64::from_bits(0x409a_ab1c_d000_0000), "1706.7781372070312"),
            (f64::from_bits(0x40fd_58f9_f100_0000), "120207.62133789062"),
            (-1417389728594571.2, "-1417389728594571.2"),
        ];
        for (value, expected) in cases {
            assert_eq!(number_to_string(*value), *expected, "{value}");
        }
    }
}
