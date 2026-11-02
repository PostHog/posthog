//! `Date.parse` as V8 implements it (`src/date/dateparser-inl.h`).
//!
//! The consumer reads the `created_at` header with `Date.parse` for the rate limiter clock and
//! the internal-logs signature window. V8 first tries the ES5 ISO format and falls back to a
//! lenient legacy parser, so this is a port of both, not of the ISO grammar alone.
//!
//! A string without a time zone is local time in V8. The consumer runs with `TZ=UTC`, so this
//! port reads local time as UTC.

const NONE: i64 = i64::MIN;
/// V8 checks a few composed values against the small-integer range of a 64-bit build with
/// pointer compression (31 bits).
const SMI_MAX: i64 = (1 << 30) - 1;
const SMI_MIN: i64 = -(1 << 30);

#[derive(Clone, Copy, Debug, PartialEq)]
enum KeywordType {
    Invalid,
    MonthName,
    TimeZoneName,
    TimeSeparator,
    AmPm,
}

#[derive(Clone, Copy, Debug)]
enum Token {
    Invalid,
    Unknown,
    Number {
        value: i64,
        length: usize,
    },
    Symbol(char),
    WhiteSpace,
    Keyword {
        kind: KeywordType,
        value: i64,
        length: usize,
    },
    End,
}

impl Token {
    fn is_number(&self) -> bool {
        matches!(self, Token::Number { .. })
    }
    fn is_fixed_length_number(&self, n: usize) -> bool {
        matches!(self, Token::Number { length, .. } if *length == n)
    }
    fn number(&self) -> i64 {
        match self {
            Token::Number { value, .. } => *value,
            _ => 0,
        }
    }
    fn is_symbol(&self, c: char) -> bool {
        matches!(self, Token::Symbol(s) if *s == c)
    }
    fn is_ascii_sign(&self) -> bool {
        self.is_symbol('+') || self.is_symbol('-')
    }
    fn ascii_sign(&self) -> i64 {
        if self.is_symbol('-') {
            -1
        } else {
            1
        }
    }
    fn is_end(&self) -> bool {
        matches!(self, Token::End)
    }
    fn is_white_space(&self) -> bool {
        matches!(self, Token::WhiteSpace)
    }
    fn is_keyword_type(&self, kind: KeywordType) -> bool {
        matches!(self, Token::Keyword { kind: k, .. } if *k == kind)
    }
    fn is_keyword_z(&self) -> bool {
        matches!(
            self,
            Token::Keyword {
                kind: KeywordType::TimeZoneName,
                value: 0,
                length: 1
            }
        )
    }
}

/// V8's keyword table. Words match on their first three lower-cased letters; a longer word
/// matches only a month name.
const KEYWORDS: &[(&str, KeywordType, i64)] = &[
    ("jan", KeywordType::MonthName, 1),
    ("feb", KeywordType::MonthName, 2),
    ("mar", KeywordType::MonthName, 3),
    ("apr", KeywordType::MonthName, 4),
    ("may", KeywordType::MonthName, 5),
    ("jun", KeywordType::MonthName, 6),
    ("jul", KeywordType::MonthName, 7),
    ("aug", KeywordType::MonthName, 8),
    ("sep", KeywordType::MonthName, 9),
    ("oct", KeywordType::MonthName, 10),
    ("nov", KeywordType::MonthName, 11),
    ("dec", KeywordType::MonthName, 12),
    ("am", KeywordType::AmPm, 0),
    ("pm", KeywordType::AmPm, 12),
    ("ut", KeywordType::TimeZoneName, 0),
    ("utc", KeywordType::TimeZoneName, 0),
    ("z", KeywordType::TimeZoneName, 0),
    ("gmt", KeywordType::TimeZoneName, 0),
    ("cdt", KeywordType::TimeZoneName, -5),
    ("cst", KeywordType::TimeZoneName, -6),
    ("edt", KeywordType::TimeZoneName, -4),
    ("est", KeywordType::TimeZoneName, -5),
    ("mdt", KeywordType::TimeZoneName, -6),
    ("mst", KeywordType::TimeZoneName, -7),
    ("pdt", KeywordType::TimeZoneName, -7),
    ("pst", KeywordType::TimeZoneName, -8),
    ("t", KeywordType::TimeSeparator, 0),
];

fn lookup_keyword(prefix: &[u32; 3], len: usize) -> (KeywordType, i64) {
    for (word, kind, value) in KEYWORDS {
        let mut key = [0u32; 3];
        for (i, c) in word.chars().enumerate() {
            key[i] = c as u32;
        }
        if key == *prefix && (len <= 3 || *kind == KeywordType::MonthName) {
            return (*kind, *value);
        }
    }
    (KeywordType::Invalid, 0)
}

/// `IsWhiteSpaceOrLineTerminator` from V8.
fn is_js_white_space(c: char) -> bool {
    matches!(
        c,
        '\t' | '\u{b}'
            | '\u{c}'
            | ' '
            | '\u{a0}'
            | '\u{feff}'
            | '\n'
            | '\r'
            | '\u{2028}'
            | '\u{2029}'
    ) || (c != '\u{a0}' && c.is_whitespace() && general_category_zs(c))
}

/// Space separators (Unicode category Zs) beyond the ones listed above.
fn general_category_zs(c: char) -> bool {
    matches!(
        c,
        '\u{1680}' | '\u{2000}'..='\u{200a}' | '\u{202f}' | '\u{205f}' | '\u{3000}'
    )
}

struct Tokenizer {
    chars: Vec<char>,
    pos: usize,
    peeked: Option<Token>,
}

impl Tokenizer {
    fn new(input: &str) -> Self {
        Self {
            chars: input.chars().collect(),
            pos: 0,
            peeked: None,
        }
    }

    fn ch(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    /// V8's `IsAsciiAlphaOrAbove`: any character from 'A' up, which takes in non-ASCII text.
    fn is_alpha_or_above(c: char) -> bool {
        c >= 'A'
    }

    fn scan(&mut self) -> Token {
        let Some(c) = self.ch() else {
            return Token::End;
        };
        if c.is_ascii_digit() {
            // V8's `ReadUnsignedNumeral`: skip leading zeros, keep 9 significant digits, and
            // count every digit in the length.
            let start = self.pos;
            while self.ch() == Some('0') {
                self.pos += 1;
            }
            let mut n: i64 = 0;
            let mut significant = 0;
            while let Some(d) = self.ch().filter(char::is_ascii_digit) {
                if significant < 9 {
                    n = n * 10 + (d as i64 - '0' as i64);
                }
                significant += 1;
                self.pos += 1;
            }
            return Token::Number {
                value: n,
                length: self.pos - start,
            };
        }
        if matches!(c, ':' | '-' | '+' | '.' | ')') {
            self.pos += 1;
            return Token::Symbol(c);
        }
        if Self::is_alpha_or_above(c) && !is_js_white_space(c) {
            let mut prefix = [0u32; 3];
            let mut len = 0;
            while let Some(w) = self
                .ch()
                .filter(|w| Self::is_alpha_or_above(*w) && !is_js_white_space(*w))
            {
                if len < 3 {
                    prefix[len] = (w as u32) | 0x20;
                }
                len += 1;
                self.pos += 1;
            }
            let (kind, value) = lookup_keyword(&prefix, len);
            return Token::Keyword {
                kind,
                value,
                length: len,
            };
        }
        if is_js_white_space(c) {
            while self.ch().is_some_and(is_js_white_space) {
                self.pos += 1;
            }
            return Token::WhiteSpace;
        }
        if c == '(' {
            let mut balance = 0i32;
            loop {
                match self.ch() {
                    Some(')') => balance -= 1,
                    Some('(') => balance += 1,
                    _ => {}
                }
                self.pos += 1;
                if balance <= 0 || self.ch().is_none() {
                    break;
                }
            }
            return Token::Unknown;
        }
        self.pos += 1;
        Token::Unknown
    }

    fn next(&mut self) -> Token {
        match self.peeked.take() {
            Some(t) => t,
            None => self.scan(),
        }
    }

    fn peek(&mut self) -> Token {
        if self.peeked.is_none() {
            self.peeked = Some(self.scan());
        }
        self.peeked.unwrap()
    }

    fn skip_symbol(&mut self, c: char) -> bool {
        if self.peek().is_symbol(c) {
            self.next();
            true
        } else {
            false
        }
    }
}

#[derive(Default)]
struct DayComposer {
    comp: [i64; 3],
    index: usize,
    named_month: Option<i64>,
    is_iso_date: bool,
}

impl DayComposer {
    fn is_empty(&self) -> bool {
        self.index == 0
    }
    fn add(&mut self, n: i64) -> bool {
        if self.index < 3 {
            self.comp[self.index] = n;
            self.index += 1;
            true
        } else {
            false
        }
    }
    fn is_month(n: i64) -> bool {
        (1..=12).contains(&n)
    }
    fn is_day(n: i64) -> bool {
        (1..=31).contains(&n)
    }
    fn write(&mut self) -> Option<(i64, i64, i64)> {
        if self.index < 1 {
            return None;
        }
        while self.index < 3 {
            self.comp[self.index] = 1;
            self.index += 1;
        }
        let (mut year, month, day);
        match self.named_month {
            None => {
                if self.is_iso_date || !Self::is_day(self.comp[0]) {
                    year = self.comp[0];
                    month = self.comp[1];
                    day = self.comp[2];
                } else {
                    month = self.comp[0];
                    day = self.comp[1];
                    year = self.comp[2];
                }
            }
            Some(named) => {
                month = named;
                if !Self::is_day(self.comp[0]) {
                    year = self.comp[0];
                    day = self.comp[1];
                } else {
                    day = self.comp[0];
                    year = self.comp[1];
                }
            }
        }
        if !self.is_iso_date {
            if (0..=49).contains(&year) {
                year += 2000;
            } else if (50..=99).contains(&year) {
                year += 1900;
            }
        }
        if !(SMI_MIN..=SMI_MAX).contains(&year) || !Self::is_month(month) || !Self::is_day(day) {
            return None;
        }
        Some((year, month - 1, day))
    }
}

#[derive(Default)]
struct TimeComposer {
    comp: [i64; 4],
    index: usize,
    hour_offset: Option<i64>,
}

impl TimeComposer {
    fn is_empty(&self) -> bool {
        self.index == 0
    }
    fn is_expecting(&self, n: i64) -> bool {
        (self.index == 1 && Self::is_minute(n))
            || (self.index == 2 && Self::is_second(n))
            || (self.index == 3 && Self::is_millisecond(n))
    }
    fn add(&mut self, n: i64) -> bool {
        if self.index < 4 {
            self.comp[self.index] = n;
            self.index += 1;
            true
        } else {
            false
        }
    }
    fn add_final(&mut self, n: i64) -> bool {
        if !self.add(n) {
            return false;
        }
        while self.index < 4 {
            self.comp[self.index] = 0;
            self.index += 1;
        }
        true
    }
    fn is_hour(n: i64) -> bool {
        (0..=23).contains(&n)
    }
    fn is_minute(n: i64) -> bool {
        (0..=59).contains(&n)
    }
    fn is_second(n: i64) -> bool {
        (0..=59).contains(&n)
    }
    fn is_hour12(n: i64) -> bool {
        (0..=12).contains(&n)
    }
    fn is_millisecond(n: i64) -> bool {
        (0..=999).contains(&n)
    }
    fn write(&mut self) -> Option<(i64, i64, i64, i64)> {
        while self.index < 4 {
            self.comp[self.index] = 0;
            self.index += 1;
        }
        let [mut hour, minute, second, ms] = self.comp;
        if let Some(offset) = self.hour_offset {
            if !Self::is_hour12(hour) {
                return None;
            }
            hour %= 12;
            hour += offset;
        }
        if !Self::is_hour(hour)
            || !Self::is_minute(minute)
            || !Self::is_second(second)
            || !Self::is_millisecond(ms)
        {
            // A 24th hour is allowed if minutes, seconds, and milliseconds are 0.
            if hour != 24 || minute != 0 || second != 0 || ms != 0 {
                return None;
            }
        }
        Some((hour, minute, second, ms))
    }
}

struct TimeZoneComposer {
    sign: i64,
    hour: i64,
    minute: i64,
}

impl Default for TimeZoneComposer {
    fn default() -> Self {
        Self {
            sign: NONE,
            hour: NONE,
            minute: NONE,
        }
    }
}

impl TimeZoneComposer {
    fn set(&mut self, offset_hours: i64) {
        self.sign = if offset_hours < 0 { -1 } else { 1 };
        self.hour = offset_hours.abs();
        self.minute = 0;
    }
    fn is_expecting(&self, n: i64) -> bool {
        self.hour != NONE && self.minute == NONE && TimeComposer::is_minute(n)
    }
    fn is_utc(&self) -> bool {
        self.hour == 0 && self.minute == 0
    }
    fn is_empty(&self) -> bool {
        self.hour == NONE
    }
    /// Seconds east of UTC, `None` for local time, or `Err` when the offset is out of range.
    fn write(&mut self) -> Result<Option<i64>, ()> {
        if self.sign == NONE {
            return Ok(None);
        }
        if self.hour == NONE {
            self.hour = 0;
        }
        if self.minute == NONE {
            self.minute = 0;
        }
        let total = self.sign * (self.hour * 3600 + self.minute * 60);
        if !(SMI_MIN..=SMI_MAX).contains(&total) {
            return Err(());
        }
        Ok(Some(total))
    }
}

fn read_milliseconds(token: Token) -> i64 {
    let Token::Number { value, length } = token else {
        return 0;
    };
    let mut number = value;
    let mut length = length;
    if length < 3 {
        if length == 1 {
            number *= 100;
        } else if length == 2 {
            number *= 10;
        }
    } else if length > 3 {
        length = length.min(9);
        let mut factor = 1;
        while length > 3 {
            factor *= 10;
            length -= 1;
        }
        number /= factor;
    }
    number
}

/// V8's `ParseES5DateTime`. Returns the first token it did not handle, `End` when the whole
/// string was an ES5 date, or `Invalid` for a strict rejection.
fn parse_es5(
    s: &mut Tokenizer,
    day: &mut DayComposer,
    time: &mut TimeComposer,
    tz: &mut TimeZoneComposer,
) -> Token {
    if s.peek().is_ascii_sign() {
        let sign_token = s.next();
        if !s.peek().is_fixed_length_number(6) {
            return sign_token;
        }
        let sign = sign_token.ascii_sign();
        let year = s.next().number();
        if sign < 0 && year == 0 {
            return sign_token;
        }
        day.add(sign * year);
    } else if s.peek().is_fixed_length_number(4) {
        day.add(s.next().number());
    } else {
        return s.next();
    }
    if s.skip_symbol('-') {
        if !s.peek().is_fixed_length_number(2) || !DayComposer::is_month(s.peek().number()) {
            return s.next();
        }
        day.add(s.next().number());
        if s.skip_symbol('-') {
            if !s.peek().is_fixed_length_number(2) || !DayComposer::is_day(s.peek().number()) {
                return s.next();
            }
            day.add(s.next().number());
        }
    }
    if !s.peek().is_keyword_type(KeywordType::TimeSeparator) {
        if !s.peek().is_end() {
            return s.next();
        }
    } else {
        s.next();
        if !s.peek().is_fixed_length_number(2) || !(0..=24).contains(&s.peek().number()) {
            return Token::Invalid;
        }
        let hour_is_24 = s.peek().number() == 24;
        time.add(s.next().number());
        if !s.skip_symbol(':') {
            return Token::Invalid;
        }
        if !s.peek().is_fixed_length_number(2)
            || !TimeComposer::is_minute(s.peek().number())
            || (hour_is_24 && s.peek().number() > 0)
        {
            return Token::Invalid;
        }
        time.add(s.next().number());
        if s.skip_symbol(':') {
            if !s.peek().is_fixed_length_number(2)
                || !TimeComposer::is_second(s.peek().number())
                || (hour_is_24 && s.peek().number() > 0)
            {
                return Token::Invalid;
            }
            time.add(s.next().number());
            if s.skip_symbol('.') {
                if !s.peek().is_number() || (hour_is_24 && s.peek().number() > 0) {
                    return Token::Invalid;
                }
                time.add(read_milliseconds(s.next()));
            }
        }
        if s.peek().is_keyword_z() {
            s.next();
            tz.set(0);
        } else if s.peek().is_ascii_sign() {
            tz.sign = s.next().ascii_sign();
            if s.peek().is_fixed_length_number(4) {
                let hourmin = s.next().number();
                let hour = hourmin / 100;
                let minute = hourmin % 100;
                if !TimeComposer::is_hour(hour) || !TimeComposer::is_minute(minute) {
                    return Token::Invalid;
                }
                tz.hour = hour;
                tz.minute = minute;
            } else {
                if !s.peek().is_fixed_length_number(2) || !TimeComposer::is_hour(s.peek().number())
                {
                    return Token::Invalid;
                }
                tz.hour = s.next().number();
                if !s.skip_symbol(':') {
                    return Token::Invalid;
                }
                if !s.peek().is_fixed_length_number(2)
                    || !TimeComposer::is_minute(s.peek().number())
                {
                    return Token::Invalid;
                }
                tz.minute = s.next().number();
            }
        }
        if !s.peek().is_end() {
            return Token::Invalid;
        }
    }
    // A date-only form without a zone is UTC; a date-time form is local time.
    if tz.is_empty() && time.is_empty() {
        tz.set(0);
    }
    day.is_iso_date = true;
    Token::End
}

fn parse_components(input: &str) -> Option<f64> {
    let mut s = Tokenizer::new(input);
    let mut day = DayComposer::default();
    let mut time = TimeComposer::default();
    let mut tz = TimeZoneComposer::default();

    let mut token = parse_es5(&mut s, &mut day, &mut time, &mut tz);
    if matches!(token, Token::Invalid) {
        return None;
    }
    let mut has_read_number = !day.is_empty();
    while !token.is_end() {
        match token {
            Token::Number { value: n, .. } => {
                has_read_number = true;
                if s.skip_symbol(':') {
                    if s.skip_symbol(':') {
                        if !time.is_empty() {
                            return None;
                        }
                        time.add(n);
                        time.add(0);
                    } else {
                        if !time.add(n) {
                            return None;
                        }
                        if s.peek().is_symbol('.') {
                            s.next();
                        }
                    }
                } else if s.skip_symbol('.') && time.is_expecting(n) {
                    // V8 consumes the '.' even when the time does not expect this number.
                    time.add(n);
                    if !s.peek().is_number() {
                        return None;
                    }
                    let ms = read_milliseconds(s.next());
                    if ms < 0 {
                        return None;
                    }
                    time.add_final(ms);
                } else if tz.is_expecting(n) {
                    tz.minute = n;
                } else if time.is_expecting(n) {
                    time.add_final(n);
                    let peek = s.peek();
                    if !peek.is_end()
                        && !peek.is_white_space()
                        && !peek.is_keyword_z()
                        && !peek.is_ascii_sign()
                    {
                        return None;
                    }
                } else {
                    if !day.add(n) {
                        return None;
                    }
                    s.skip_symbol('-');
                }
            }
            Token::Keyword { kind, value, .. } => {
                if kind == KeywordType::AmPm && !time.is_empty() {
                    time.hour_offset = Some(value);
                } else if kind == KeywordType::MonthName {
                    day.named_month = Some(value);
                    s.skip_symbol('-');
                } else if kind == KeywordType::TimeZoneName && has_read_number {
                    tz.set(value);
                } else {
                    // Garbage words are illegal once a number has been read, and the first
                    // number must be separated from garbage words.
                    if has_read_number || s.peek().is_number() {
                        return None;
                    }
                }
            }
            t if t.is_ascii_sign() && (tz.is_utc() || !time.is_empty()) => {
                tz.sign = t.ascii_sign();
                let mut n = 0;
                let mut length = 0;
                if s.peek().is_number() {
                    if let Token::Number { value, length: l } = s.next() {
                        n = value;
                        length = l;
                    }
                }
                has_read_number = true;
                if s.peek().is_symbol(':') {
                    tz.hour = n;
                    tz.minute = NONE;
                } else if length == 1 || length == 2 {
                    tz.hour = n;
                    tz.minute = 0;
                } else if length == 3 || length == 4 {
                    tz.hour = n / 100;
                    tz.minute = n % 100;
                } else {
                    return None;
                }
            }
            t if (t.is_ascii_sign() || t.is_symbol(')')) && has_read_number => return None,
            _ => {}
        }
        token = s.next();
    }

    let (year, month, day_of_month) = day.write()?;
    let (hour, minute, second, ms) = time.write()?;
    let offset_seconds = tz.write().ok()?;
    let days = make_day(year as f64, month as f64, day_of_month as f64);
    let time_ms = ((hour * 60 + minute) * 60 + second) as f64 * 1000.0 + ms as f64;
    let mut date = days * 86_400_000.0 + time_ms;
    if let Some(offset) = offset_seconds {
        date -= offset as f64 * 1000.0;
    }
    // TimeClip.
    if !date.is_finite() || date.abs() > 8.64e15 {
        return None;
    }
    Some(date)
}

/// ECMAScript `MakeDay`: the day number of a year, a 0-based month that may overflow, and a day.
fn make_day(year: f64, month: f64, date: f64) -> f64 {
    let ym = year + (month / 12.0).floor();
    let mn = month.rem_euclid(12.0) as i64;
    days_from_civil(ym as i64, mn + 1, 1) as f64 + date - 1.0
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// `Date.parse(input)` in epoch milliseconds, or `None` where JavaScript returns NaN.
pub fn date_parse(input: &str) -> Option<f64> {
    parse_utc_iso_millis(input).or_else(|| parse_components(input))
}

/// The `toISOString` form `YYYY-MM-DDTHH:mm:ss.sssZ`, which producers send, without the
/// tokenizer. `None` hands any other text, and any field out of range, to the full parser.
fn parse_utc_iso_millis(input: &str) -> Option<f64> {
    let b = input.as_bytes();
    if b.len() != 24 {
        return None;
    }
    for (i, &c) in b.iter().enumerate() {
        let ok = match i {
            4 | 7 => c == b'-',
            10 => c == b'T',
            13 | 16 => c == b':',
            19 => c == b'.',
            23 => c == b'Z',
            _ => c.is_ascii_digit(),
        };
        if !ok {
            return None;
        }
    }
    let num = |from: usize, to: usize| {
        b[from..to]
            .iter()
            .fold(0i64, |n, &d| n * 10 + i64::from(d - b'0'))
    };
    let (year, month, day) = (num(0, 4), num(5, 7), num(8, 10));
    let (hour, minute, second, ms) = (num(11, 13), num(14, 16), num(17, 19), num(20, 23));
    if !DayComposer::is_month(month)
        || !DayComposer::is_day(day)
        || !TimeComposer::is_minute(minute)
        || !TimeComposer::is_second(second)
        || !(TimeComposer::is_hour(hour) || (hour == 24 && minute == 0 && second == 0 && ms == 0))
    {
        return None;
    }
    let days = make_day(year as f64, (month - 1) as f64, day as f64);
    let time_ms = ((hour * 60 + minute) * 60 + second) as f64 * 1000.0 + ms as f64;
    let date = days * 86_400_000.0 + time_ms;
    if !date.is_finite() || date.abs() > 8.64e15 {
        return None;
    }
    Some(date)
}

#[cfg(test)]
mod tests {
    use super::{date_parse, parse_components};

    #[test]
    fn the_iso_fast_path_agrees_with_the_full_parser() {
        let mut state = 0x2545_f491_4f6c_dd1du64;
        let template = b"0000-00-00T00:00:00.000Z";
        for _ in 0..200_000 {
            let mut text = *template;
            for (i, c) in text.iter_mut().enumerate() {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                if c.is_ascii_digit() {
                    // Mostly the low digits that make valid fields, sometimes any digit.
                    let range = if i < 4 || state.is_multiple_of(4) {
                        10
                    } else {
                        3
                    };
                    *c = b'0' + (state >> 8) as u8 % range;
                }
            }
            let text = std::str::from_utf8(&text).unwrap();
            assert_eq!(date_parse(text), parse_components(text), "{text}");
        }
    }

    #[test]
    fn parses_common_forms() {
        assert_eq!(
            date_parse("2025-01-15T12:00:00.000Z"),
            Some(1736942400000.0)
        );
        assert_eq!(
            date_parse("Wed, 15 Jan 2025 12:00:00 GMT"),
            Some(1736942400000.0)
        );
        assert_eq!(
            date_parse("Jan 15 2025 12:00:00 PM GMT+0100"),
            Some(1736938800000.0)
        );
        assert_eq!(date_parse("2025-02-30T00:00:00Z"), Some(1740873600000.0));
        assert_eq!(date_parse("1970-01-01T00:00:00Z"), Some(0.0));
        assert_eq!(date_parse("1969-12-31T23:59:59.999Z"), Some(-1.0));
        assert_eq!(date_parse("2025-01-15T24:00:00Z"), Some(1736985600000.0));
        assert_eq!(date_parse("2025-01-15T24:01:00Z"), None);
        assert_eq!(date_parse("2025-13-01"), None);
        // V8 skips a word before the first number, so this is 2025-01-01.
        assert_eq!(date_parse("garbage 2025"), Some(1735689600000.0));
        assert_eq!(date_parse("garbage2025"), None);
        // Leading zeros are skipped, and only 9 significant digits are kept.
        assert_eq!(
            date_parse("-0800 12:00:00.1234561970"),
            Some(-36921614399877.0)
        );
        assert_eq!(date_parse("Jan 15 0000000000002025"), Some(1736899200000.0));
    }
}
