//! ECMAScript `Number::toString(10)`, which `String(n)` and `JSON.stringify` use.
//!
//! Rust's `{:e}` gives the shortest round-trip digit count. ECMAScript breaks a tie between two
//! equally close shortest candidates toward the even digit, so an odd last digit is checked
//! against the exactly rounded form, which rounds ties to even.

use std::fmt::Write;

pub fn number_to_string(value: f64) -> String {
    let mut out = String::new();
    write_number(value, &mut out);
    out
}

/// Below 2^53 every integer is exact, and ECMAScript prints an integer under 1e21 in full.
const EXACT_INTEGER_LIMIT: f64 = 9_007_199_254_740_992.0;

pub fn write_number(value: f64, out: &mut String) {
    if value.is_nan() {
        out.push_str("NaN");
        return;
    }
    if value == 0.0 {
        out.push('0');
        return;
    }
    if value.is_infinite() {
        out.push_str(if value > 0.0 { "Infinity" } else { "-Infinity" });
        return;
    }
    if value.fract() == 0.0 && value.abs() < EXACT_INTEGER_LIMIT {
        out.push_str(itoa::Buffer::new().format(value as i64));
        return;
    }
    if value < 0.0 {
        out.push('-');
    }
    let sci = shortest_scientific(value.abs());
    let sci = sci.as_str();
    let (mantissa, exp) = sci.split_once('e').expect("LowerExp has an exponent");
    let exp: i32 = exp.parse().expect("exponent is an integer");
    let mut digit_buf = [0u8; 32];
    let mut k = 0usize;
    for b in mantissa.bytes().filter(|b| *b != b'.') {
        digit_buf[k] = b;
        k += 1;
    }
    let digits = std::str::from_utf8(&digit_buf[..k]).expect("ASCII digits");
    let k = k as i32;
    // n is the position of the decimal point relative to the digit string.
    let n = exp + 1;
    if k <= n && n <= 21 {
        out.push_str(digits);
        out.extend(std::iter::repeat_n('0', (n - k) as usize));
    } else if 0 < n && n <= 21 {
        out.push_str(&digits[..n as usize]);
        out.push('.');
        out.push_str(&digits[n as usize..]);
    } else if -6 < n && n <= 0 {
        out.push_str("0.");
        out.extend(std::iter::repeat_n('0', (-n) as usize));
        out.push_str(digits);
    } else {
        out.push_str(&digits[..1]);
        if k > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if n - 1 < 0 { '-' } else { '+' });
        out.push_str(itoa::Buffer::new().format((n - 1).abs()));
    }
}

/// A fixed buffer for one formatted double, so the slow path does not allocate.
struct StackStr {
    buf: [u8; 64],
    len: usize,
}

impl StackStr {
    fn new() -> Self {
        Self {
            buf: [0; 64],
            len: 0,
        }
    }

    fn as_str(&self) -> &str {
        std::str::from_utf8(&self.buf[..self.len]).expect("formatter writes UTF-8")
    }
}

impl Write for StackStr {
    fn write_str(&mut self, s: &str) -> std::fmt::Result {
        let end = self.len + s.len();
        if end > self.buf.len() {
            return Err(std::fmt::Error);
        }
        self.buf[self.len..end].copy_from_slice(s.as_bytes());
        self.len = end;
        Ok(())
    }
}

fn shortest_scientific(value: f64) -> StackStr {
    let mut shortest = StackStr::new();
    write!(shortest, "{value:e}").expect("a double fits the buffer");
    let mantissa = shortest.as_str().split_once('e').map_or("", |(m, _)| m);
    let last_is_odd = mantissa.bytes().last().is_some_and(|d| (d - b'0') % 2 == 1);
    if !last_is_odd {
        return shortest;
    }
    let digits = mantissa.bytes().filter(u8::is_ascii_digit).count();
    let mut exact = StackStr::new();
    write!(exact, "{:.*e}", digits - 1, value).expect("a double fits the buffer");
    // At a power of two the lower gap is narrower, so the nearest candidate can miss.
    if exact.as_str() != shortest.as_str() && exact.as_str().parse::<f64>() == Ok(value) {
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
