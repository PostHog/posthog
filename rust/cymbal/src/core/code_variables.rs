//! Server-side masking of Python frame `code_variables`.
//!
//! The rules port the default masking of the posthog-python SDK
//! (`posthog/exception_utils.py`). Older SDK versions send values that the current rules
//! redact, so cymbal applies the current rules to every event it processes. Keep the
//! pattern lists in step with the SDK.

use std::{borrow::Cow, collections::HashMap, sync::LazyLock};

use base64::Engine;
use regex::{Captures, Regex};
use serde_json::{Map, Value};

pub const REDACTED: &str = "$$_posthog_redacted_based_on_masking_rules_$$";
pub const TOO_LONG: &str = "$$_posthog_value_too_long_$$";

const MAX_LENGTH_FOR_PATTERN_MATCH: usize = 2_048;
const MAX_DEPTH: usize = 12;
const SECRET_MIN_LENGTH: usize = 16;
const SECRET_MIN_ENTROPY_BITS: f64 = 3.8;
const SECRET_MIN_CHAR_CLASSES: u8 = 3;
// Shorter values are prose, such as "the bearer of". A `Basic` credential of any length is
// still redacted when it decodes to `user:password`, e.g. `YTpi` for `a:b`.
const AUTH_CREDENTIAL_MIN_LENGTH: usize = 8;
const AUTH_PROSE_WORD_MAX_LENGTH: usize = 15;
const PEM_PRIVATE_KEY_MARKER: &str = "PRIVATE KEY-----";
// Punctuation of reprs and structured strings. A bare token never holds it.
const SECRET_REJECT_CHARS: &str = "()[]{}<>'\"`,;";

// The SDK's `DEFAULT_CODE_VARIABLES_MASK_PATTERNS`. The SDK matches them against names and
// string values alike, so a value that contains `token` is redacted whole. One difference:
// `sk_` must start a word here, so `task_id` and `disk_usage` keep their values. A team can
// change the SDK patterns in its own code, but not these.
static MASK_PATTERNS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"(?i)password|secret|passwd|pwd|api_key|apikey|auth|credentials|privatekey|",
        r"private_key|token|aws_access_key_id|_pass|(?:^|[^a-z0-9])sk_|jwt|connection_string|",
        r"connectionstring|conn_str|connstr|dsn|[?&]sig="
    ))
    .unwrap()
});

// The SDK's `_KNOWN_SECRET_PATTERNS`.
static KNOWN_SECRET: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        &[
            r"sk-ant-[A-Za-z0-9_-]{16,}",
            r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
            r"hf_[A-Za-z0-9]{34}",
            r"AKIA[0-9A-Z]{16}",
            r"(?:ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA|ACCA)[0-9A-Z]{16}",
            r"AIza[A-Za-z0-9_-]{35}",
            r"ya29\.[A-Za-z0-9_-]{20,}",
            r"do[opr]_v1_[a-f0-9]{64}",
            r"(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}",
            r"sq0[a-z]{3}-[A-Za-z0-9_-]{22,43}",
            r"gh[pousr]_[A-Za-z0-9]{36}",
            r"github_pat_[A-Za-z0-9_]{20,}",
            r"gl(?:pat|ptt|rt|soat)-[A-Za-z0-9_-]{20}",
            r"glsa_[A-Za-z0-9]{32}_[A-Fa-f0-9]{8}",
            r"xox[abeoprs]-[A-Za-z0-9-]{10,}",
            r"xapp-[0-9]-[A-Za-z0-9-]{10,}",
            r"SK[0-9a-fA-F]{32}",
            r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}",
            r"key-[0-9a-f]{32}",
            r"[0-9a-f]{32}-us[0-9]{1,2}",
            r"npm_[A-Za-z0-9]{36}",
            r"pypi-AgEI[A-Za-z0-9_-]{50,}",
            r"dapi[0-9a-f]{32}",
            r"dp\.pt\.[A-Za-z0-9]{40,}",
            r"PMAK-[a-f0-9]{24}-[a-f0-9]{34}",
            r"lin_api_[A-Za-z0-9]{40}",
            r"ntn_[A-Za-z0-9]{40,}",
            r"shp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}",
            r"NR(?:AK|JS|II|MA|RA)-[A-Za-z0-9]{27}",
            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}",
        ]
        .join("|"),
    )
    .unwrap()
});

// The SDK uses a lookahead that the regex crate lacks, so `redact_url_credential` checks
// for the `:` instead. The userinfo ends where the authority ends, at `/`, `?` or `#`.
static URL_CREDENTIALS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)([a-z][a-z0-9+.\-]{0,30}://)([^/?#\s]*)@").unwrap());

// A header pair list or an ASGI scope holds an `Authorization` value apart from its header
// name, so the name patterns never see it. The separator also accepts a colon or an opening
// quote, as in `Bearer: <token>`, but it must not be empty, so that names such as
// `basicConfig` stay untouched.
static AUTH_HEADER_CREDENTIALS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)\b(bearer|basic)((?:\s*:\s*|\s+)['"]?)([A-Za-z0-9._~+/-]+=*)"#).unwrap()
});

static UUID: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        .unwrap()
});

static PATH_WORD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z][a-z.]*$").unwrap());

// A key that matches a mask pattern is kept only in this shape. Other text, such as
// `password=hunter2`, can hold the value itself.
static FIELD_NAME: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[\w.\-]+$").unwrap());

pub fn mask_code_variables(code_variables: &mut Value) {
    mask_value(code_variables, 0);
}

fn mask_value(value: &mut Value, depth: usize) {
    if depth >= MAX_DEPTH && (value.is_object() || value.is_array()) {
        *value = Value::String(TOO_LONG.to_string());
        return;
    }
    match value {
        Value::String(text) => {
            if let Some(masked) = mask_string(text, depth) {
                *text = masked;
            }
        }
        Value::Array(items) => {
            for item in items {
                mask_value(item, depth + 1);
            }
        }
        Value::Object(map) => {
            let entries = std::mem::take(map);
            *map = mask_mapping(entries, depth);
        }
        _ => {}
    }
}

fn mask_string(value: &str, depth: usize) -> Option<String> {
    if value.chars().count() > MAX_LENGTH_FOR_PATTERN_MATCH {
        return Some(TOO_LONG.to_string());
    }
    // The SDK serializes a dict or an object to a JSON string after it masks it. The string
    // rules would redact all of it for any sensitive key name, so mask the structure instead.
    if let Some(parsed) = parse_json_container(value) {
        let mut masked = parsed.clone();
        mask_value(&mut masked, depth + 1);
        return (masked != parsed).then(|| masked.to_string());
    }
    if MASK_PATTERNS.is_match(value) || looks_like_secret(value) {
        return Some(REDACTED.to_string());
    }
    match redact_embedded_credentials(value) {
        Cow::Owned(redacted) => Some(redacted),
        Cow::Borrowed(_) => None,
    }
}

fn parse_json_container(value: &str) -> Option<Value> {
    if !matches!(value.trim_start().as_bytes().first(), Some(b'{' | b'[')) {
        return None;
    }
    serde_json::from_str(value).ok()
}

fn mask_mapping(entries: Map<String, Value>, depth: usize) -> Map<String, Value> {
    let mut result = Map::new();
    let mut next_placeholder = 0;
    for (key, mut value) in entries {
        if key.chars().count() > MAX_LENGTH_FOR_PATTERN_MATCH {
            let placeholder = redacted_key(&result, &mut next_placeholder);
            result.insert(placeholder, Value::String(TOO_LONG.to_string()));
            continue;
        }
        let key_matches_mask = MASK_PATTERNS.is_match(&key);
        let mut out_key =
            if (key_matches_mask && !FIELD_NAME.is_match(&key)) || looks_like_secret(&key) {
                redacted_key(&result, &mut next_placeholder)
            } else {
                redact_embedded_credentials(&key).into_owned()
            };
        // Two keys can mask to the same text, e.g. URLs that differ only in their credentials.
        if result.contains_key(&out_key) {
            out_key = redacted_key(&result, &mut next_placeholder);
        }
        if key_matches_mask {
            value = Value::String(REDACTED.to_string());
        } else {
            mask_value(&mut value, depth + 1);
        }
        result.insert(out_key, value);
    }
    result
}

// Placeholders are only added, so the search resumes from the last one instead of zero.
fn redacted_key(result: &Map<String, Value>, next: &mut usize) -> String {
    loop {
        let candidate = format!("$$_posthog_redacted_key_{next}_$$");
        *next += 1;
        if !result.contains_key(&candidate) {
            return candidate;
        }
    }
}

// URLs go first, because the `Authorization` pass can consume a URL scheme, as in
// `Bearer postgresql://user:pass@host`.
fn redact_embedded_credentials(value: &str) -> Cow<'_, str> {
    let value = if value.contains("://") {
        URL_CREDENTIALS.replace_all(value, redact_url_credential)
    } else {
        Cow::Borrowed(value)
    };
    match redact_auth_credentials(&value) {
        Some(redacted) => Cow::Owned(redacted),
        None => value,
    }
}

// `replace_all` cannot see the text after a match, and `is_auth_credential` needs it.
fn redact_auth_credentials(value: &str) -> Option<String> {
    let mut redacted = String::new();
    let mut copied_up_to = 0;
    for caps in AUTH_HEADER_CREDENTIALS.captures_iter(value) {
        let whole = caps.get(0).expect("group 0 is the whole match");
        if !is_auth_credential(&caps, &value[whole.end()..]) {
            continue;
        }
        redacted.push_str(&value[copied_up_to..whole.start()]);
        redacted.push_str(&caps[1]);
        redacted.push_str(&caps[2]);
        redacted.push_str(REDACTED);
        copied_up_to = whole.end();
    }
    if copied_up_to == 0 {
        return None;
    }
    redacted.push_str(&value[copied_up_to..]);
    Some(redacted)
}

// A plain word of up to 15 letters is prose only when more text follows it, as in "Basic
// Configuration loaded". At the end of a value, the same word looks exactly like a header
// value such as "Bearer Sunflower", so it counts as a credential.
fn is_auth_credential(caps: &Captures, rest: &str) -> bool {
    let credential = &caps[3];
    if caps[1].eq_ignore_ascii_case("basic") && is_basic_credential(credential) {
        return true;
    }
    if credential.len() < AUTH_CREDENTIAL_MIN_LENGTH {
        return false;
    }
    let is_plain_word = credential.len() <= AUTH_PROSE_WORD_MAX_LENGTH
        && credential
            .bytes()
            .next()
            .is_some_and(|b| b.is_ascii_alphabetic())
        && credential.bytes().skip(1).all(|b| b.is_ascii_lowercase());
    let more_text_follows = rest.starts_with(char::is_whitespace)
        && rest
            .trim_start()
            .starts_with(|c: char| c.is_ascii_alphabetic());
    !(is_plain_word && more_text_follows)
}

fn is_basic_credential(credential: &str) -> bool {
    base64::engine::general_purpose::STANDARD
        .decode(credential)
        .ok()
        .and_then(|decoded| String::from_utf8(decoded).ok())
        .is_some_and(|decoded| decoded.contains(':'))
}

fn redact_url_credential(caps: &Captures) -> String {
    // Only userinfo with a password is a credential: `ssh://git@host` keeps its username.
    let userinfo = &caps[2];
    if userinfo
        .split('@')
        .next()
        .is_some_and(|user| user.contains(':'))
    {
        format!("{}{REDACTED}@", &caps[1])
    } else {
        caps[0].to_string()
    }
}

fn looks_like_secret(value: &str) -> bool {
    if value.contains(PEM_PRIVATE_KEY_MARKER) {
        return true;
    }
    let length = value.chars().count();
    if length < SECRET_MIN_LENGTH {
        return false;
    }
    if is_high_entropy_secret(value, length) {
        return true;
    }
    // Known formats that the entropy check misses, e.g. AWS key ids with two char classes.
    length <= MAX_LENGTH_FOR_PATTERN_MATCH && KNOWN_SECRET.is_match(value)
}

fn is_high_entropy_secret(value: &str, length: usize) -> bool {
    if value.contains(' ') || looks_like_path_or_url(value) || UUID.is_match(value) {
        return false;
    }
    let mut counts: HashMap<char, usize> = HashMap::new();
    for ch in value.chars() {
        *counts.entry(ch).or_default() += 1;
    }

    let (mut lower, mut upper, mut digit, mut symbol) = (false, false, false, false);
    let mut hex_only = true;
    for &ch in counts.keys() {
        if ch.is_whitespace() || SECRET_REJECT_CHARS.contains(ch) {
            return false;
        }
        if ch.is_lowercase() {
            lower = true;
            hex_only &= ch.is_ascii_hexdigit();
        } else if ch.is_uppercase() {
            upper = true;
            hex_only &= ch.is_ascii_hexdigit();
        } else if ch.is_numeric() {
            digit = true;
        } else {
            symbol = true;
            hex_only = false;
        }
    }
    // A hex string is an id or a digest, such as a SHA or an ObjectId.
    let classes = [lower, upper, digit, symbol].iter().filter(|&&c| c).count() as u8;
    if hex_only || classes < SECRET_MIN_CHAR_CLASSES {
        return false;
    }

    let total = length as f64;
    let entropy: f64 = counts
        .values()
        .map(|&n| {
            let p = n as f64 / total;
            -p * p.log2()
        })
        .sum();
    entropy >= SECRET_MIN_ENTROPY_BITS
}

fn looks_like_path_or_url(value: &str) -> bool {
    if value.contains("://") || value.contains('\\') {
        return true;
    }
    value.contains('/')
        && value
            .split('/')
            .filter(|segment| !segment.is_empty() && PATH_WORD.is_match(segment))
            .nth(1)
            .is_some()
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;

    // Synthetic fakes, assembled at runtime so no complete credential literal sits in source.
    fn fake(prefix: &str, body: &str) -> String {
        format!("{prefix}{body}")
    }

    fn masked(value: &Value) -> Value {
        let mut value = value.clone();
        mask_code_variables(&mut value);
        value
    }

    #[test]
    fn masks_what_the_python_sdk_masks() {
        let stripe_key = fake("sk_live_", "Zx81Qm7Lp2Vb9Nc4Rt6Yh3Kd");
        let bearer_token = fake("tok_", "Zx81Qm7Lp2Vb9Nc4");
        let basic_credential = fake("c3ZjOmZha2Ut", "cGFzcy0xMjM=");
        let cases = [
            (
                "variable with a secret name",
                json!({"api_key": "abc"}),
                json!({"api_key": REDACTED}),
            ),
            (
                "known format under a neutral name",
                json!({"value": stripe_key}),
                json!({"value": REDACTED}),
            ),
            (
                "high-entropy value",
                json!({"value": "Zx81Qm7Lp2Vb9Nc4Rt6Yh3Kd"}),
                json!({"value": REDACTED}),
            ),
            (
                "PEM private key",
                json!({"value": "-----BEGIN PRIVATE KEY-----\nMIIEvQ"}),
                json!({"value": REDACTED}),
            ),
            (
                "URL credentials",
                json!({"url": "postgresql://app:hunter22@db.example.com/app"}),
                json!({"url": format!("postgresql://{REDACTED}@db.example.com/app")}),
            ),
            (
                "Bearer value in a header pair list",
                json!({"headers": [["authorization", format!("Bearer {bearer_token}")]]}),
                json!({"headers": [[REDACTED, format!("Bearer {REDACTED}")]]}),
            ),
            (
                "Basic value under a neutral name",
                json!({"value": format!("Basic {basic_credential}")}),
                json!({"value": format!("Basic {REDACTED}")}),
            ),
            (
                "credential of lowercase letters only",
                json!({"value": format!("Bearer {}", fake("zqwklmno", "pxyzrstu"))}),
                json!({"value": format!("Bearer {REDACTED}")}),
            ),
            (
                "short Basic credential that decodes to user:password",
                json!({"value": "Basic YTpi"}),
                json!({"value": format!("Basic {REDACTED}")}),
            ),
            (
                "DSN after the scheme keeps its own credential redacted",
                json!({"value": "Bearer mongodb+srv://alice:sunflower99@db.example.com/app"}),
                json!({"value": format!("Bearer {REDACTED}://{REDACTED}@db.example.com/app")}),
            ),
            (
                "one word that ends the value, like a header",
                json!({"value": "Bearer Sunflower"}),
                json!({"value": format!("Bearer {REDACTED}")}),
            ),
            (
                "short fragment of a scheme and one word",
                json!({"value": "basic: configuration"}),
                json!({"value": format!("basic: {REDACTED}")}),
            ),
            (
                "colon between the scheme and the credential",
                json!({"value": format!("Bearer: {bearer_token}")}),
                json!({"value": format!("Bearer: {REDACTED}")}),
            ),
            (
                "quote between the scheme and the credential",
                json!({"value": format!("Bearer '{bearer_token}'")}),
                json!({"value": format!("Bearer '{REDACTED}'")}),
            ),
            (
                "signed URL",
                json!({"url": "https://acct.blob.core.windows.net/c/f?sv=2022-11-02&sig=q2VxT8fKz1aB3dE%3D"}),
                json!({"url": REDACTED}),
            ),
            (
                "object repr from an old SDK",
                json!({"settings": "Settings(AWS_SECRET_ACCESS_KEY='abc')"}),
                json!({"settings": REDACTED}),
            ),
            (
                "JSON string from the current SDK keeps its safe fields",
                json!({"user": "{\"name\": \"bob\", \"password\": \"hunter22\"}"}),
                json!({"user": format!("{{\"name\":\"bob\",\"password\":\"{REDACTED}\"}}")}),
            ),
            (
                "URL credentials end at the authority",
                json!({"url": "https://app:hunter22@db.example.com?next=a@b"}),
                json!({"url": format!("https://{REDACTED}@db.example.com?next=a@b")}),
            ),
            (
                "sk_ at the start of a word",
                json!({"stripe_sk_key": "abc"}),
                json!({"stripe_sk_key": REDACTED}),
            ),
            (
                "several keys that hold text get distinct placeholders",
                json!({"pools": {"password=a": 1, "password=b": 2}}),
                json!({"pools": {
                    "$$_posthog_redacted_key_0_$$": REDACTED,
                    "$$_posthog_redacted_key_1_$$": REDACTED,
                }}),
            ),
            (
                "URL credentials in a key",
                json!({"pools": {"postgresql://app:hunter22@db.example.com/app": 1}}),
                json!({"pools": Map::from_iter([(
                    format!("postgresql://{REDACTED}@db.example.com/app"),
                    json!(1),
                )])}),
            ),
        ];

        for (name, input, expected) in cases {
            let once = masked(&input);
            assert_eq!(once, expected, "{name}");
            // Processing masks a frame on arrival and again after resolution.
            assert_eq!(masked(&once), once, "{name} is not idempotent");
        }
    }

    #[test]
    fn leaves_benign_values_alone() {
        for value in [
            "hello world",
            "design",
            "/signup?step=2",
            "the bearer of bad news",
            "bearer transportation services",
            "Basic Configuration loaded",
            "basicConfig(level=10)",
            "550e8400-e29b-41d4-a716-446655440000",
            "da39a3ee5e6b4b0d3255bfef95601890afd80709",
            "/usr/local/lib/python3.12/site-packages/app/views.py",
            "{\"name\": \"bob\"}",
            "disk_usage at 91%",
            "https://db.example.com?next=a:b@c",
        ] {
            let input = json!({"value": value});
            assert_eq!(masked(&input), input, "{value}");
        }
        for key in ["task_id", "disk_usage"] {
            let input = json!({key: "42"});
            assert_eq!(masked(&input), input, "{key}");
        }
    }
}
