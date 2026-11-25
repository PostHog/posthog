use std::borrow::Cow;

use gpui::SharedString;

#[derive(Clone, PartialEq, Debug)]
pub enum MaskToken {
    /// 0 Digit, equivalent to `[0]`
    // Digit0,
    /// Digit, equivalent to `[0-9]`
    Digit,
    /// Letter, equivalent to `[a-zA-Z]`
    Letter,
    /// Letter or digit, equivalent to `[a-zA-Z0-9]`
    LetterOrDigit,
    /// Separator
    Sep(char),
    /// Any character
    Any,
}

#[allow(unused)]
impl MaskToken {
    /// Check if the token is any character.
    pub fn is_any(&self) -> bool {
        matches!(self, MaskToken::Any)
    }

    /// Check if the token is a match for the given character.
    ///
    /// The separator is always a match any input character.
    fn is_match(&self, ch: char) -> bool {
        match self {
            MaskToken::Digit => ch.is_ascii_digit(),
            MaskToken::Letter => ch.is_ascii_alphabetic(),
            MaskToken::LetterOrDigit => ch.is_ascii_alphanumeric(),
            MaskToken::Any => true,
            MaskToken::Sep(c) => *c == ch,
        }
    }

    /// Is the token a separator (Can be ignored)
    fn is_sep(&self) -> bool {
        matches!(self, MaskToken::Sep(_))
    }

    /// Check if the token is a number.
    pub fn is_number(&self) -> bool {
        matches!(self, MaskToken::Digit)
    }

    pub fn placeholder(&self) -> char {
        match self {
            MaskToken::Sep(c) => *c,
            _ => '_',
        }
    }

    fn mask_char(&self, ch: char) -> char {
        match self {
            MaskToken::Digit | MaskToken::LetterOrDigit | MaskToken::Letter => ch,
            MaskToken::Sep(c) => *c,
            MaskToken::Any => ch,
        }
    }

    fn unmask_char(&self, ch: char) -> Option<char> {
        match self {
            MaskToken::Digit => Some(ch),
            MaskToken::Letter => Some(ch),
            MaskToken::LetterOrDigit => Some(ch),
            MaskToken::Any => Some(ch),
            _ => None,
        }
    }
}

#[derive(Clone, Default)]
pub enum MaskPattern {
    #[default]
    None,
    Pattern {
        pattern: SharedString,
        tokens: Vec<MaskToken>,
    },
    Number {
        /// Group separator, e.g. "," or " "
        separator: Option<char>,
        /// Number of fraction digits, e.g. 2 for 123.45
        fraction: Option<usize>,
    },
}

impl From<&str> for MaskPattern {
    fn from(pattern: &str) -> Self {
        Self::new(pattern)
    }
}

impl MaskPattern {
    /// Create a new mask pattern
    ///
    /// - `9` - Digit
    /// - `A` - Letter
    /// - `#` - Letter or Digit
    /// - `*` - Any character
    /// - other characters - Separator
    ///
    /// For example:
    ///
    /// - `(999)999-9999` - US phone number: (123)456-7890
    /// - `99999-9999` - ZIP code: 12345-6789
    /// - `AAAA-99-####` - Custom pattern: ABCD-12-3AB4
    /// - `*999*` - Custom pattern: (123) or [123]
    pub fn new(pattern: &str) -> Self {
        let tokens = pattern
            .chars()
            .map(|ch| match ch {
                // '0' => MaskToken::Digit0,
                '9' => MaskToken::Digit,
                'A' => MaskToken::Letter,
                '#' => MaskToken::LetterOrDigit,
                '*' => MaskToken::Any,
                _ => MaskToken::Sep(ch),
            })
            .collect();

        Self::Pattern {
            pattern: pattern.to_owned().into(),
            tokens,
        }
    }

    #[allow(unused)]
    fn tokens(&self) -> Option<&Vec<MaskToken>> {
        match self {
            Self::Pattern { tokens, .. } => Some(tokens),
            Self::Number { .. } => None,
            Self::None => None,
        }
    }

    /// Create a new mask pattern with group separator, e.g. "," or " "
    pub fn number(sep: Option<char>) -> Self {
        Self::Number {
            separator: sep,
            fraction: None,
        }
    }

    pub fn placeholder(&self) -> Option<String> {
        match self {
            Self::Pattern { tokens, .. } => {
                Some(tokens.iter().map(|token| token.placeholder()).collect())
            }
            Self::Number { .. } => None,
            Self::None => None,
        }
    }

    /// Return true if the mask pattern is None or no any pattern.
    pub fn is_none(&self) -> bool {
        match self {
            Self::Pattern { tokens, .. } => tokens.is_empty(),
            Self::Number { .. } => false,
            Self::None => true,
        }
    }

    /// Check is the mask text is valid.
    ///
    /// If the mask pattern is None, always return true.
    pub fn is_valid(&self, mask_text: &str) -> bool {
        if self.is_none() {
            return true;
        }

        let mut text_index = 0;
        let mask_text_chars: Vec<char> = mask_text.chars().collect();
        match self {
            Self::Pattern { tokens, .. } => {
                for token in tokens {
                    if text_index >= mask_text_chars.len() {
                        break;
                    }

                    let ch = mask_text_chars[text_index];
                    if token.is_match(ch) {
                        text_index += 1;
                    }
                }
                text_index == mask_text_chars.len()
            }
            Self::Number { separator, .. } => {
                if mask_text.is_empty() {
                    return true;
                }

                // check if the text is valid number
                let mut parts = mask_text.split('.');
                let int_part = parts.next().unwrap_or("");
                let frac_part = parts.next();

                // only one dot is valid
                if parts.next().is_some() {
                    return false;
                }

                let sign_positions: Vec<usize> = int_part
                    .chars()
                    .enumerate()
                    .filter_map(|(i, ch)| match is_sign(&ch) {
                        true => Some(i),
                        false => None,
                    })
                    .collect();

                // only one sign is valid
                // sign is only valid at the beginning of the string
                if sign_positions.len() > 1 || sign_positions.first() > Some(&0) {
                    return false;
                }

                // check if the integer part is valid
                if !int_part.chars().enumerate().all(|(i, ch)| {
                    ch.is_ascii_digit() || is_sign(&ch) && i == 0 || Some(ch) == *separator
                }) {
                    return false;
                }

                // check if the fraction part is valid
                if let Some(frac) = frac_part {
                    if !frac
                        .chars()
                        .all(|ch| ch.is_ascii_digit() || Some(ch) == *separator)
                    {
                        return false;
                    }
                }

                true
            }
            Self::None => true,
        }
    }

    /// Check if valid input char at the given position.
    pub fn is_valid_at(&self, ch: char, pos: usize) -> bool {
        if self.is_none() {
            return true;
        }

        match self {
            Self::Pattern { tokens, .. } => {
                if let Some(token) = tokens.get(pos) {
                    if token.is_match(ch) {
                        return true;
                    }

                    if token.is_sep() {
                        // If next token is match, it's valid
                        if let Some(next_token) = tokens.get(pos + 1) {
                            if next_token.is_match(ch) {
                                return true;
                            }
                        }
                    }
                }

                false
            }
            Self::Number { .. } => true,
            Self::None => true,
        }
    }

    /// Format the text according to the mask pattern
    ///
    /// For example:
    ///
    /// - pattern: (999)999-999
    /// - text: 123456789
    /// - mask_text: (123)456-789
    pub fn mask(&self, text: &str) -> SharedString {
        if self.is_none() {
            return text.to_owned().into();
        }

        match self {
            Self::Number {
                separator,
                fraction,
            } => {
                if let Some(sep) = *separator {
                    // Remove the existing group separator
                    let text = text.replace(sep, "");

                    let mut parts = text.split('.');
                    let int_part = parts.next().unwrap_or("");

                    // Limit the fraction part to the given range, if not enough, pad with 0
                    let frac_part = parts.next().map(|part| {
                        part.chars()
                            .take(fraction.unwrap_or(usize::MAX))
                            .collect::<String>()
                    });

                    // Reverse the integer part for easier grouping
                    let mut chars: Vec<char> = int_part.chars().rev().collect();

                    // Removing the sign from formatting to avoid cases such as: -,123
                    let maybe_signed = if let Some(pos) = chars.iter().position(is_sign) {
                        Some(chars.remove(pos))
                    } else {
                        None
                    };

                    let mut result = String::new();
                    for (i, ch) in chars.iter().enumerate() {
                        if i > 0 && i % 3 == 0 {
                            result.push(sep);
                        }
                        result.push(*ch);
                    }
                    let int_with_sep: String = result.chars().rev().collect();

                    let final_str = if let Some(frac) = frac_part {
                        if fraction == &Some(0) {
                            int_with_sep
                        } else {
                            format!("{}.{}", int_with_sep, frac)
                        }
                    } else {
                        int_with_sep
                    };

                    let final_str = if let Some(sign) = maybe_signed {
                        format!("{}{}", sign, final_str)
                    } else {
                        final_str
                    };

                    return final_str.into();
                }

                text.to_owned().into()
            }
            Self::Pattern { tokens, .. } => {
                let mut result = String::new();
                let mut text_index = 0;
                let text_chars: Vec<char> = text.chars().collect();
                for (pos, token) in tokens.iter().enumerate() {
                    if text_index >= text_chars.len() {
                        break;
                    }
                    let ch = text_chars[text_index];
                    // Break if expected char is not match
                    if !token.is_sep() && !self.is_valid_at(ch, pos) {
                        break;
                    }
                    let mask_ch = token.mask_char(ch);
                    result.push(mask_ch);
                    if ch == mask_ch {
                        text_index += 1;
                        continue;
                    }
                }
                result.into()
            }
            Self::None => text.to_owned().into(),
        }
    }

    /// Extract original text from masked text
    pub fn unmask(&self, mask_text: &str) -> String {
        match self {
            Self::Number { separator, .. } => {
                if let Some(sep) = *separator {
                    let mut result = String::new();
                    for ch in mask_text.chars() {
                        if ch == sep {
                            continue;
                        }
                        result.push(ch);
                    }

                    if result.contains('.') {
                        result = result.trim_end_matches('0').to_string();
                    }
                    return result;
                }

                return mask_text.to_owned();
            }
            Self::Pattern { tokens, .. } => {
                let mut result = String::new();
                let mask_text_chars: Vec<char> = mask_text.chars().collect();
                for (text_index, token) in tokens.iter().enumerate() {
                    if text_index >= mask_text_chars.len() {
                        break;
                    }
                    let ch = mask_text_chars[text_index];
                    let unmask_ch = token.unmask_char(ch);
                    if let Some(ch) = unmask_ch {
                        result.push(ch);
                    }
                }
                result
            }
            Self::None => mask_text.to_owned(),
        }
    }
}

#[inline]
fn is_sign(ch: &char) -> bool {
    matches!(ch, '+' | '-')
}

/// Normalize full-width and CJK number characters into their ASCII equivalents.
///
/// E.g. `123。5` -> `123.5`
///
/// Every mapping is 1 char to 1 char with the same UTF-16 length, so the IME
/// marked-range offsets (in UTF-16) stay valid. The UTF-8 byte length may
/// shrink (3 bytes to 1), the caller must use the normalized string for all
/// byte-offset calculations.
#[doc(hidden)]
pub(super) fn normalize_number_input(text: &str) -> Cow<'_, str> {
    #[inline]
    fn normalize_char(ch: char) -> Option<char> {
        match ch {
            // Full-width digits 0-9
            '\u{FF10}'..='\u{FF19}' => char::from_u32(ch as u32 - 0xFF10 + '0' as u32),
            // Full-width plus ＋
            '\u{FF0B}' => Some('+'),
            // Full-width hyphen － and minus sign −
            '\u{FF0D}' | '\u{2212}' => Some('-'),
            // Full-width dot ． and ideographic full stop 。
            '\u{FF0E}' | '\u{3002}' => Some('.'),
            // Full-width comma ，
            '\u{FF0C}' => Some(','),
            _ => None,
        }
    }

    if !text.chars().any(|ch| normalize_char(ch).is_some()) {
        return Cow::Borrowed(text);
    }

    Cow::Owned(
        text.chars()
            .map(|ch| normalize_char(ch).unwrap_or(ch))
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::{MaskPattern, MaskToken};

    #[test]
    fn test_is_match() {
        assert_eq!(MaskToken::Sep('(').is_match('('), true);
        assert_eq!(MaskToken::Sep('-').is_match('('), false);
        assert_eq!(MaskToken::Sep('-').is_match('3'), false);

        assert_eq!(MaskToken::Digit.is_match('0'), true);
        assert_eq!(MaskToken::Digit.is_match('9'), true);
        assert_eq!(MaskToken::Digit.is_match('a'), false);
        assert_eq!(MaskToken::Digit.is_match('C'), false);

        assert_eq!(MaskToken::Letter.is_match('a'), true);
        assert_eq!(MaskToken::Letter.is_match('Z'), true);
        assert_eq!(MaskToken::Letter.is_match('3'), false);
        assert_eq!(MaskToken::Letter.is_match('-'), false);

        assert_eq!(MaskToken::LetterOrDigit.is_match('0'), true);
        assert_eq!(MaskToken::LetterOrDigit.is_match('9'), true);
        assert_eq!(MaskToken::LetterOrDigit.is_match('a'), true);
        assert_eq!(MaskToken::LetterOrDigit.is_match('Z'), true);
        assert_eq!(MaskToken::LetterOrDigit.is_match('3'), true);

        assert_eq!(MaskToken::Any.is_match('a'), true);
        assert_eq!(MaskToken::Any.is_match('3'), true);
        assert_eq!(MaskToken::Any.is_match('-'), true);
        assert_eq!(MaskToken::Any.is_match(' '), true);
    }

    #[test]
    fn test_mask_none() {
        let mask = MaskPattern::None;
        assert_eq!(mask.is_none(), true);
        assert_eq!(mask.is_valid("1124124ASLDJKljk"), true);
        assert_eq!(mask.mask("hello-world"), "hello-world");
        assert_eq!(mask.unmask("hello-world"), "hello-world");
    }

    #[test]
    fn test_mask_pattern1() {
        let mask = MaskPattern::new("(AA)999-999");
        assert_eq!(
            mask.tokens(),
            Some(&vec![
                MaskToken::Sep('('),
                MaskToken::Letter,
                MaskToken::Letter,
                MaskToken::Sep(')'),
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Sep('-'),
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Digit,
            ])
        );

        assert_eq!(mask.is_valid_at('(', 0), true);
        assert_eq!(mask.is_valid_at('H', 0), true);
        assert_eq!(mask.is_valid_at('3', 0), false);
        assert_eq!(mask.is_valid_at('-', 0), false);
        assert_eq!(mask.is_valid_at(')', 1), false);
        assert_eq!(mask.is_valid_at('H', 1), true);
        assert_eq!(mask.is_valid_at('1', 1), false);
        assert_eq!(mask.is_valid_at('e', 2), true);
        assert_eq!(mask.is_valid_at(')', 3), true);
        assert_eq!(mask.is_valid_at('1', 3), true);
        assert_eq!(mask.is_valid_at('2', 4), true);

        assert_eq!(mask.is_valid("(AB)123-456"), true);

        assert_eq!(mask.mask("AB123456"), "(AB)123-456");
        assert_eq!(mask.mask("(AB)123-456"), "(AB)123-456");
        assert_eq!(mask.mask("(AB123456"), "(AB)123-456");
        assert_eq!(mask.mask("AB123-456"), "(AB)123-456");
        assert_eq!(mask.mask("AB123-"), "(AB)123-");
        assert_eq!(mask.mask("AB123--"), "(AB)123-");
        assert_eq!(mask.mask("AB123-4"), "(AB)123-4");

        let unmasked_text = mask.unmask("(AB)123-456");
        assert_eq!(unmasked_text, "AB123456");

        assert_eq!(mask.is_valid("12AB345"), false);
        assert_eq!(mask.is_valid("(11)123-456"), false);
        assert_eq!(mask.is_valid("##"), false);
        assert_eq!(mask.is_valid("(AB)123456"), true);
    }

    #[test]
    fn test_mask_pattern2() {
        let mask = MaskPattern::new("999-999-******");
        assert_eq!(
            mask.tokens(),
            Some(&vec![
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Sep('-'),
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Digit,
                MaskToken::Sep('-'),
                MaskToken::Any,
                MaskToken::Any,
                MaskToken::Any,
                MaskToken::Any,
                MaskToken::Any,
                MaskToken::Any,
            ])
        );

        let text = "123456A(111)";
        let masked_text = mask.mask(text);
        assert_eq!(masked_text, "123-456-A(111)");
        let unmasked_text = mask.unmask(&masked_text);
        assert_eq!(unmasked_text, "123456A(111)");
        assert_eq!(mask.is_valid(&masked_text), true);
    }

    #[test]
    fn test_is_valid_with_non_ascii_text() {
        let mask = MaskPattern::new("9999年99月");
        assert_eq!(mask.is_valid("2024年"), true);
        assert_eq!(mask.is_valid("2024年12月"), true);
        assert_eq!(mask.is_valid("2024年1x"), false);

        let mask = MaskPattern::new("*999");
        assert_eq!(mask.is_valid("€"), true);
        assert_eq!(mask.is_valid("€123"), true);
    }

    #[test]
    fn test_number_with_group_separator() {
        // Use comma as group separator
        let mask = MaskPattern::number(Some(','));
        assert_eq!(mask.mask("1234567"), "1,234,567");
        assert_eq!(mask.mask("1,234,567"), "1,234,567");
        assert_eq!(mask.unmask("1,234,567"), "1234567");
        let mask = MaskPattern::number(Some(','));
        assert_eq!(mask.mask("1234567.89"), "1,234,567.89");
        assert_eq!(mask.unmask("1,234,567.89"), "1234567.89");

        // Use space as group separator
        let mask = MaskPattern::number(Some(' '));
        assert_eq!(mask.mask("1234567"), "1 234 567");
        assert_eq!(mask.unmask("1 234 567"), "1234567");
        let mask = MaskPattern::number(Some(' '));
        assert_eq!(mask.mask("1234567.89"), "1 234 567.89");
        assert_eq!(mask.unmask("1 234 567.89"), "1234567.89");

        // No group separator
        let mask = MaskPattern::number(None);
        assert_eq!(mask.mask("1234567"), "1234567");
        assert_eq!(mask.unmask("1234567"), "1234567");
        let mask = MaskPattern::number(None);
        assert_eq!(mask.mask("1234567.89"), "1234567.89");
        assert_eq!(mask.unmask("1234567.89"), "1234567.89");
    }

    #[test]
    fn test_number_with_fraction_digits() {
        let mask = MaskPattern::Number {
            separator: Some(','),
            fraction: Some(4),
        };

        assert_eq!(mask.mask("1234567"), "1,234,567");
        assert_eq!(mask.unmask("1,234,567"), "1234567");
        assert_eq!(mask.mask("1234567."), "1,234,567.");
        assert_eq!(mask.mask("1234567.89"), "1,234,567.89");
        assert_eq!(mask.unmask("1,234,567.890"), "1234567.89");
        assert_eq!(mask.mask("1234567.891"), "1,234,567.891");
        assert_eq!(mask.mask("1234567.891234"), "1,234,567.8912");

        let mask = MaskPattern::Number {
            separator: Some(','),
            fraction: None,
        };

        assert_eq!(mask.mask("1234567.1234567"), "1,234,567.1234567");

        let mask = MaskPattern::Number {
            separator: Some(','),
            fraction: Some(0),
        };

        assert_eq!(mask.mask("1234567.1234567"), "1,234,567");
    }

    #[test]
    fn test_signed_number_numbers() {
        let mask = MaskPattern::Number {
            separator: Some(','),
            fraction: Some(2),
        };

        assert_eq!(mask.is_valid("-"), true);
        assert_eq!(mask.is_valid("-1234567"), true);
        assert_eq!(mask.is_valid("-1,234,567"), true);
        assert_eq!(mask.is_valid("-1234567."), true);
        assert_eq!(mask.is_valid("-1234567.89"), true);

        assert_eq!(mask.is_valid("+"), true);
        assert_eq!(mask.is_valid("+1234567"), true);
        assert_eq!(mask.is_valid("+1,234,567"), true);
        assert_eq!(mask.is_valid("+1234567."), true);
        assert_eq!(mask.is_valid("+1234567.89"), true);

        // Only one sign is valid
        assert_eq!(mask.is_valid("+-"), false);
        assert_eq!(mask.is_valid("-+"), false);
        assert_eq!(mask.is_valid("+-1234567"), false);

        // No sign is valid in the middle of the number
        assert_eq!(mask.is_valid("1,-234,567"), false);
        assert_eq!(mask.is_valid("12-34567.89"), false);

        // Signs in fractions are invalid
        assert_eq!(mask.is_valid("+1234567.-"), false);

        // The separator does not show up before the sign i.e. -,123
        assert_eq!(mask.mask("-123"), "-123");

        assert_eq!(mask.mask("-1234567"), "-1,234,567");
        assert_eq!(mask.mask("+1234567"), "+1,234,567");
        assert_eq!(mask.unmask("-1,234,567"), "-1234567");
        assert_eq!(mask.mask("-1234567."), "-1,234,567.");
        assert_eq!(mask.mask("-1234567.89"), "-1,234,567.89");
    }

    #[test]
    fn test_number_leading_dot() {
        let mask = MaskPattern::number(None);
        assert_eq!(mask.is_valid("."), true);
        assert_eq!(mask.is_valid(".5"), true);
        assert_eq!(mask.is_valid("-."), true);
        assert_eq!(mask.is_valid("-.5"), true);
        assert_eq!(mask.is_valid("1.2.3"), false);
        assert_eq!(mask.is_valid("1.."), false);

        // A bare leading dot is kept as-is (not completed to "0."), so that
        // deleting the integer part of "1.2" keeps ".2" and stays editable.
        assert_eq!(mask.mask("."), ".");
        assert_eq!(mask.mask(".5"), ".5");
        assert_eq!(mask.mask("-.5"), "-.5");
        assert_eq!(mask.mask("+.5"), "+.5");

        let mask = MaskPattern::number(Some(','));
        assert_eq!(mask.mask(".5"), ".5");
        assert_eq!(mask.mask("-.5"), "-.5");
    }

    #[test]
    fn test_normalize_number_input() {
        use std::borrow::Cow;

        use super::normalize_number_input;

        // Fast path: no allocation when nothing to normalize
        assert!(matches!(
            normalize_number_input("-1,234.5"),
            Cow::Borrowed(_)
        ));

        // Full-width digits
        assert_eq!(normalize_number_input("0123456789"), "0123456789");
        // Full-width signs, dot and comma
        assert_eq!(normalize_number_input("＋1．5"), "+1.5");
        assert_eq!(normalize_number_input("－1，234"), "-1,234");
        // Minus sign (U+2212)
        assert_eq!(normalize_number_input("−1.5"), "-1.5");
        // Ideographic full stop
        assert_eq!(normalize_number_input("12。5"), "12.5");
        // Other characters are kept as-is
        assert_eq!(normalize_number_input("ab 中 1"), "ab 中 1");
    }
}
