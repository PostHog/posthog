// Copied from MLHog prep/labeling/src/scrub/text.rs — bench-only. Adapted: `crate::` import paths
// point at `crate::mlhog::`, and the let-chain in `strip_possessive` is rewritten as a nested
// `if let` (this crate is edition 2021).

use crate::mlhog::config::Config;
use crate::mlhog::context::Ctx;
use crate::mlhog::dict::AllowLists;

#[allow(dead_code)]
pub fn scrub(ctx: &Ctx<'_>, input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    scrub_into(ctx, input, &mut out);
    out
}

pub fn scrub_into(ctx: &Ctx<'_>, input: &str, out: &mut String) -> bool {
    let mut redacted = String::new();
    let (text, mut changed) = if input.as_bytes().contains(&b'@')
        && redact_emails_into(input, &mut redacted)
    {
        (redacted.as_str(), true)
    } else {
        (input, false)
    };

    let allow = ctx.allow;
    let mut chars = text.char_indices().peekable();
    while let Some(&(start, c)) = chars.peek() {
        if is_word_char(c) {
            let mut end = start;
            while let Some(&(i, ch)) = chars.peek() {
                if is_word_char(ch) {
                    end = i + ch.len_utf8();
                    chars.next();
                } else {
                    break;
                }
            }
            emit_word(&text[start..end], allow, out, &mut changed);
        } else {
            out.push(c);
            chars.next();
        }
    }
    changed
}

// Redact emails, one `*` per char: `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`.
pub fn redact_emails_into(input: &str, out: &mut String) -> bool {
    let b = input.as_bytes();
    let mut changed = false;
    let mut i = 0;
    while i < b.len() {
        if is_local_char(b[i]) {
            let mut le = i;
            while le < b.len() && is_local_char(b[le]) {
                le += 1;
            }
            if let Some(end) = match_email(b, le) {
                for _ in i..end {
                    out.push(Config::REDACT_CHAR);
                }
                changed = true;
                i = end;
            } else {
                out.push_str(&input[i..le]);
                i = le;
            }
            continue;
        }
        let len = utf8_len(b[i]);
        out.push_str(&input[i..i + len]);
        i += len;
    }
    changed
}

fn match_email(b: &[u8], le: usize) -> Option<usize> {
    if le >= b.len() || b[le] != b'@' {
        return None;
    }
    let ds = le + 1;
    let mut re = ds;
    while re < b.len() && is_domain_char(b[re]) {
        re += 1;
    }
    let mut k = re;
    while k > ds {
        k -= 1;
        if b[k] == b'.' && k > ds {
            let mut l = k + 1;
            while l < b.len() && b[l].is_ascii_alphabetic() {
                l += 1;
            }
            if l - (k + 1) >= 2 {
                return Some(l);
            }
        }
    }
    None
}

fn is_local_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'%' | b'+' | b'-')
}

fn is_domain_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-')
}

fn utf8_len(lead: u8) -> usize {
    match lead {
        0x00..=0x7F => 1,
        0xC0..=0xDF => 2,
        0xE0..=0xEF => 3,
        _ => 4,
    }
}

fn is_word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '\'' || c == '\u{2019}'
}

fn emit_word(word: &str, allow: &AllowLists, out: &mut String, changed: &mut bool) {
    if is_numeric_token(word) {
        push_redacted(word, Config::NUMBER_CHAR, out);
        *changed = true;
        return;
    }
    if word_is_allowed(allow, word) {
        out.push_str(word);
    } else {
        push_redacted(word, Config::REDACT_CHAR, out);
        *changed = true;
    }
}

fn push_redacted(word: &str, mark: char, out: &mut String) {
    for _ in word.chars() {
        out.push(mark);
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
        if let Some(b) = strip_possessive(&normalized) {
            if allow.text_contains(b) {
                return true;
            }
        }
    }
    if let Some(b) = strip_possessive(word) {
        if allow.text_contains(b) {
            return true;
        }
    }
    false
}

fn strip_possessive(word: &str) -> Option<&str> {
    for suffix in ["'s", "\u{2019}s", "'", "\u{2019}"] {
        if let Some(b) = word.strip_suffix(suffix) {
            if !b.is_empty() {
                return Some(b);
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
