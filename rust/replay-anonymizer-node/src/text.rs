//! Length-preserving text scrub: numeric tokens -> `#`, allow-listed words kept, everything else -> `*`.
//! Mirrors `anonymize/text.ts`. `None` means "unchanged" (caller keeps the original).

use crate::allow_lists::AllowLists;

/// Replacement char for redacted (non-allow-listed) word characters.
pub const REDACT_CHAR: char = '*';
/// Replacement char for numeric tokens.
pub const NUMBER_CHAR: char = '#';

/// Guaranteed email-PII pass. Hand-rolled scan (expand around each `@`, equivalent to
/// `/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g`) because that regex backtracks
/// quadratically on long unbroken charset runs (base64 bodies: minutes per event).
pub fn redact_emails(input: &str) -> Option<String> {
    let bytes = input.as_bytes();
    let mut at = find_at(bytes, 0)?;
    let mut out = String::new();
    let mut last = 0usize;
    let mut changed = false;
    loop {
        let mut start = at;
        while start > last && is_local_char(bytes[start - 1]) {
            start -= 1;
        }
        let mut scan_end = at + 1;
        while scan_end < bytes.len() && is_domain_char(bytes[scan_end]) {
            scan_end += 1;
        }
        let end = trim_domain_to_tld(bytes, at + 1, scan_end);
        if start < at {
            if let Some(end) = end {
                out.push_str(&input[last..start]);
                for _ in input[start..end].chars() {
                    out.push(REDACT_CHAR);
                }
                last = end;
                changed = true;
                match find_at(bytes, end) {
                    Some(n) => at = n,
                    None => break,
                }
                continue;
            }
        }
        match find_at(bytes, at + 1) {
            Some(n) => at = n,
            None => break,
        }
    }
    if !changed {
        return None;
    }
    out.push_str(&input[last..]);
    Some(out)
}

fn find_at(bytes: &[u8], from: usize) -> Option<usize> {
    bytes[from..]
        .iter()
        .position(|&b| b == b'@')
        .map(|i| from + i)
}

/// Longest `end` in `(domain_start, scan_end]` where the domain ends with `.` + >=2 letters, else None.
fn trim_domain_to_tld(bytes: &[u8], domain_start: usize, scan_end: usize) -> Option<usize> {
    let mut i = scan_end;
    while i > domain_start {
        let mut letters = 0usize;
        while i > domain_start && is_ascii_letter(bytes[i - 1]) {
            i -= 1;
            letters += 1;
        }
        if letters >= 2 && i > domain_start + 1 && bytes[i - 1] == b'.' {
            return Some(i + letters);
        }
        i -= 1; // skip the non-letter (or short-TLD dot) and keep looking left
    }
    None
}

fn is_ascii_letter(c: u8) -> bool {
    c.is_ascii_alphabetic()
}

// [A-Za-z0-9._%+-]
fn is_local_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'%' | b'+' | b'-')
}

// [A-Za-z0-9.-]
fn is_domain_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, b'.' | b'-')
}

pub fn scrub_text(allow: &AllowLists, input: &str) -> Option<String> {
    // Nuke whole email addresses first; the tokenizer then runs over what's left.
    let emails = redact_emails(input);
    let text: &str = emails.as_deref().unwrap_or(input);
    match tokenize_scrub(allow, text) {
        Some(t) => Some(t),
        None => emails,
    }
}

fn tokenize_scrub(allow: &AllowLists, text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut changed = false;
    let mut i = 0usize;
    while i < bytes.len() {
        // Non-word run: find its end bytewise (ASCII fast path) and copy it in one slice push.
        let run_start = i;
        while i < bytes.len() {
            let b = bytes[i];
            if b < 0x80 {
                if is_ascii_word_byte(b) {
                    break;
                }
                i += 1;
            } else {
                let c = next_char(text, i);
                if is_word_char(c) {
                    break;
                }
                i += c.len_utf8();
            }
        }
        out.push_str(&text[run_start..i]);
        if i >= bytes.len() {
            break;
        }
        // Word run.
        let word_start = i;
        while i < bytes.len() {
            let b = bytes[i];
            if b < 0x80 {
                if !is_ascii_word_byte(b) {
                    break;
                }
                i += 1;
            } else {
                let c = next_char(text, i);
                if !is_word_char(c) {
                    break;
                }
                i += c.len_utf8();
            }
        }
        emit_word(allow, &text[word_start..i], &mut out, &mut changed);
    }
    if changed {
        Some(out)
    } else {
        None
    }
}

fn next_char(text: &str, at: usize) -> char {
    text[at..].chars().next().expect("at is a char boundary")
}

// A "word" is a maximal run of word chars: Unicode letters/numbers, `_`, `'`, `’`.
// The byte test is the ASCII projection of `is_word_char` (`’` is non-ASCII, handled per-char).
fn is_ascii_word_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_' || b == b'\''
}

fn is_word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '\'' || c == '\u{2019}'
}

fn emit_word(allow: &AllowLists, word: &str, out: &mut String, changed: &mut bool) {
    if is_numeric_token(word) {
        push_redacted(word, NUMBER_CHAR, out);
        *changed = true;
    } else if word_is_allowed(allow, word) {
        out.push_str(word);
    } else {
        push_redacted(word, REDACT_CHAR, out);
        *changed = true;
    }
}

/// Length-preserving redaction: one mark per source code point, pushed in chunks.
fn push_redacted(word: &str, mark: char, out: &mut String) {
    const STARS: &str = "********************************";
    const HASHES: &str = "################################";
    let chunk = if mark == NUMBER_CHAR { HASHES } else { STARS };
    let mut n = if word.is_ascii() {
        word.len()
    } else {
        word.chars().count()
    };
    while n > 0 {
        let take = n.min(chunk.len());
        out.push_str(&chunk[..take]);
        n -= take;
    }
}

fn word_is_allowed(allow: &AllowLists, word: &str) -> bool {
    if allow.text_contains(word) {
        return true;
    }
    if word.contains('\u{2019}') {
        let normalized = word.replace('\u{2019}', "'");
        if allow.text_contains(&normalized) {
            return true;
        }
        if let Some(base) = strip_possessive(&normalized) {
            if allow.text_contains(base) {
                return true;
            }
        }
    }
    if let Some(base) = strip_possessive(word) {
        if allow.text_contains(base) {
            return true;
        }
    }
    false
}

fn strip_possessive(word: &str) -> Option<&str> {
    for suffix in ["'s", "\u{2019}s", "'", "\u{2019}"] {
        if let Some(base) = word.strip_suffix(suffix) {
            if !base.is_empty() {
                return Some(base);
            }
        }
    }
    None
}

fn is_numeric_token(word: &str) -> bool {
    let mut saw_digit = false;
    for c in word.chars() {
        if c.is_ascii_digit() {
            saw_digit = true;
        } else if !matches!(c, '.' | ',' | '-' | '+') {
            return false;
        }
    }
    saw_digit
}
