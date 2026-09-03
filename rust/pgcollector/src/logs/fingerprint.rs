//! Query fingerprint: a stable 64-bit hash of a query with literals, parameter
//! markers and IN-list lengths normalised away. Applied to both pg_stat_statements
//! text (already `$1`-normalised) and raw statement text from logs so the two can
//! be joined when `%Q` (query id) isn't in `log_line_prefix`.

use once_cell::sync::Lazy;
use regex::Regex;

static COMMENT: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?s)/\*.*?\*/|--[^\n]*").unwrap());
static STRING: Lazy<Regex> = Lazy::new(|| Regex::new(r"'(?:[^']|'')*'").unwrap());
static PARAM: Lazy<Regex> = Lazy::new(|| Regex::new(r"\$\d+").unwrap());
static NUMBER: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b\d+(?:\.\d+)?\b").unwrap());
static LIST: Lazy<Regex> = Lazy::new(|| Regex::new(r"\(\s*\?(?:\s*,\s*\?)*\s*\)").unwrap());
static WS: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());
static PUNCT: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s*([=<>!,()+\-*/])\s*").unwrap());

pub fn normalize(sql: &str) -> String {
    let s = COMMENT.replace_all(sql, " ");
    let s = STRING.replace_all(&s, "?");
    let s = PARAM.replace_all(&s, "?");
    let s = NUMBER.replace_all(&s, "?");
    let s = LIST.replace_all(&s, "(?)");
    let s = WS.replace_all(&s, " ");
    let s = PUNCT.replace_all(&s, "$1");
    s.trim().trim_end_matches(';').trim().to_lowercase()
}

/// Replace string literals with `'?'` and leave everything else intact, so stored
/// statement text keeps its shape but not the values (credentials, tokens, PII)
/// that logs and pg_stat_activity carry verbatim.
pub fn redact_literals(sql: &str) -> String {
    STRING.replace_all(sql, "'?'").into_owned()
}

/// FNV-1a 64 of the normalised text, as i64 so it fits a bigint column.
pub fn fingerprint(sql: &str) -> i64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in normalize(sql).bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h as i64
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn literals_params_and_lists_normalise_together() {
        let a = fingerprint("SELECT * FROM t WHERE id = 42 AND name = 'bob' AND x IN (1, 2, 3)");
        let b = fingerprint("select * from t where id = $1 and name = $2 and x in ($3)");
        let c = fingerprint("select *\n  from t where id=7 and name='al''ice' and x in (9,8,7,6);");
        assert_eq!(a, b);
        assert_eq!(a, c);
        assert_ne!(a, fingerprint("select * from t where id = 1"));
    }

    #[test]
    fn redaction_keeps_shape_and_drops_values() {
        assert_eq!(
            redact_literals("select * from t where token = 'sk-secret' and n = 42"),
            "select * from t where token = '?' and n = 42"
        );
        assert_eq!(redact_literals("select 'it''s'"), "select '?'");
    }
}
