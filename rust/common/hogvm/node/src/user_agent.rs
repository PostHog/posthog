//! `parseUserAgent`, mirrored from `nodejs/src/cdp/hog-transformations/transformation-functions.ts`,
//! which wraps the `detect-browser` npm package (5.3.0). The rule tables below are that package's,
//! in its order: the first rule that matches wins.
//!
//! The patterns are JavaScript regexes without the `u` flag. There `.` also excludes `\r`, U+2028
//! and U+2029, `\s` has U+FEFF but not U+0085, and `\d`, `\b` and `i` are ASCII-only.

use std::sync::LazyLock;

use regex::Regex;
use serde_json::{json, Value};

// Mirrors MAX_USER_AGENT_LENGTH, which JavaScript measures in UTF-16 code units.
const MAX_USER_AGENT_LENGTH: usize = 1024;

const DOT: &str = r"[^\n\r\u{2028}\u{2029}]";
const SPACE: &str = r"[\t\n\x0B\x0C\r \u{A0}\u{1680}\u{2000}-\u{200A}\u{2028}\u{2029}\u{202F}\u{205F}\u{3000}\u{FEFF}]";

enum Rule {
    Plain(Regex),
    // detect-browser's chrome rule is `(?!Chrom.*OPR)Chrom(?:e|ium)/…`. The `regex` crate has no
    // lookahead, so the guard is a second pattern, tested at each candidate match's start.
    NotFollowedBy { pattern: Regex, guard: Regex },
}

struct BrowserRule {
    name: &'static str,
    rule: Rule,
}

fn js(pattern: &str) -> Regex {
    let pattern = pattern.replace("{D}", DOT).replace("{S}", SPACE);
    Regex::new(&pattern).unwrap_or_else(|e| panic!("invalid user agent pattern {pattern}: {e}"))
}

fn plain(name: &'static str, pattern: &str) -> BrowserRule {
    BrowserRule {
        name,
        rule: Rule::Plain(js(pattern)),
    }
}

static BROWSER_RULES: LazyLock<Vec<BrowserRule>> = LazyLock::new(|| {
    vec![
        plain("aol", r"AOLShield/([0-9._]+)"),
        plain("edge", r"Edge/([0-9._]+)"),
        plain("edge-ios", r"EdgiOS/([0-9._]+)"),
        plain("yandexbrowser", r"YaBrowser/([0-9._]+)"),
        plain("kakaotalk", r"KAKAOTALK{S}([0-9.]+)"),
        plain("samsung", r"SamsungBrowser/([0-9.]+)"),
        plain("silk", r"(?-u:\b)Silk/([0-9._-]+)(?-u:\b)"),
        plain("miui", r"MiuiBrowser/([0-9.]+)$"),
        plain("beaker", r"BeakerBrowser/([0-9.]+)"),
        plain("edge-chromium", r"EdgA?/([0-9.]+)"),
        // The source has the chrome lookahead here too, but at a `wv)` match start it can never
        // see `Chrom`, so it never rejects anything.
        plain(
            "chromium-webview",
            r"wv\){D}*Chrom(?:e|ium)/([0-9.]+)(:?{S}|$)",
        ),
        BrowserRule {
            name: "chrome",
            rule: Rule::NotFollowedBy {
                pattern: js(r"Chrom(?:e|ium)/([0-9.]+)(:?{S}|$)"),
                guard: js(r"^Chrom{D}*OPR"),
            },
        },
        plain("phantomjs", r"PhantomJS/([0-9.]+)(:?{S}|$)"),
        plain("crios", r"CriOS/([0-9.]+)(:?{S}|$)"),
        plain("firefox", r"Firefox/([0-9.]+)(?:{S}|$)"),
        plain("fxios", r"FxiOS/([0-9.]+)"),
        plain("opera-mini", r"Opera Mini{D}*Version/([0-9.]+)"),
        plain("opera", r"Opera/([0-9.]+)(?:{S}|$)"),
        plain("opera", r"OPR/([0-9.]+)(:?{S}|$)"),
        plain(
            "pie",
            r"^Microsoft Pocket Internet Explorer/([0-9]+\.[0-9]+)$",
        ),
        plain(
            "pie",
            r"^Mozilla/[0-9]\.[0-9]+{S}\(compatible;{S}(?:MSP?IE|MSInternet Explorer) ([0-9]+\.[0-9]+);{D}*Windows CE{D}*\)$",
        ),
        plain(
            "netfront",
            r"^Mozilla/[0-9]\.[0-9]+{D}*NetFront/([0-9]{D}[0-9])",
        ),
        plain("ie", r"Trident/7\.0{D}*rv:([0-9.]+){D}*\){D}*Gecko$"),
        plain("ie", r"MSIE{S}([0-9.]+);{D}*Trident/[4-7]{D}0"),
        plain("ie", r"MSIE{S}(7\.0)"),
        plain("bb10", r"BB10;{S}Touch{D}*Version/([0-9.]+)"),
        plain("android", r"Android{S}([0-9.]+)"),
        plain("ios", r"Version/([0-9._]+){D}*Mobile{D}*Safari{D}*"),
        plain("safari", r"Version/([0-9._]+){D}*Safari"),
        plain("facebook", r"FB[AS]V/([0-9.]+)"),
        plain("instagram", r"Instagram{S}([0-9.]+)"),
        plain("ios-webview", r"AppleWebKit/([0-9.]+){D}*Mobile"),
        plain("ios-webview", r"AppleWebKit/([0-9.]+){D}*Gecko\)$"),
        plain("curl", r"^curl/([0-9.]+)$"),
        plain(
            "searchbot",
            r"alexa|bot|crawl(er|ing)|facebookexternalhit|feedburner|google web preview|nagios|postrank|pingdom|slurp|spider|yahoo!|yandex",
        ),
    ]
});

static OS_RULES: LazyLock<Vec<(&'static str, Regex)>> = LazyLock::new(|| {
    [
        ("iOS", r"iP(hone|od|ad)"),
        ("Android OS", r"Android"),
        ("BlackBerry OS", r"BlackBerry|BB10"),
        ("Windows Mobile", r"IEMobile"),
        ("Amazon OS", r"Kindle"),
        ("Windows 3.11", r"Win16"),
        ("Windows 95", r"(Windows 95)|(Win95)|(Windows_95)"),
        ("Windows 98", r"(Windows 98)|(Win98)"),
        ("Windows 2000", r"(Windows NT 5{D}0)|(Windows 2000)"),
        ("Windows XP", r"(Windows NT 5{D}1)|(Windows XP)"),
        ("Windows Server 2003", r"(Windows NT 5{D}2)"),
        ("Windows Vista", r"(Windows NT 6{D}0)"),
        ("Windows 7", r"(Windows NT 6{D}1)"),
        ("Windows 8", r"(Windows NT 6{D}2)"),
        ("Windows 8.1", r"(Windows NT 6{D}3)"),
        ("Windows 10", r"(Windows NT 10{D}0)"),
        ("Windows ME", r"Windows ME"),
        (
            "Windows CE",
            r"Windows CE|WinCE|Microsoft Pocket Internet Explorer",
        ),
        ("Open BSD", r"OpenBSD"),
        ("Sun OS", r"SunOS"),
        ("Chrome OS", r"CrOS"),
        ("Linux", r"(Linux)|(X11)"),
        ("Mac OS", r"(Mac_PowerPC)|(Macintosh)"),
        ("QNX", r"QNX"),
        ("BeOS", r"BeOS"),
        ("OS/2", r"OS/2"),
    ]
    .into_iter()
    .map(|(os, pattern)| (os, js(pattern)))
    .collect()
});

static SEARCHBOT_OS: LazyLock<Regex> = LazyLock::new(|| {
    js(r"(nuhk|curl|Googlebot|Yammybot|Openbot|Slurp|MSNBot|Ask Jeeves/Teoma|ia_archiver)")
});

static WINDOWS_PHONE: LazyLock<Regex> = LazyLock::new(|| js(r"(?i-u:Windows Phone)|WPDesktop"));
static BLACKBERRY: LazyLock<Regex> = LazyLock::new(|| js(r"(?i-u:BlackBerry|PlayBook|BB10)"));

struct Detected {
    name: &'static str,
    version: Option<String>,
    os: Option<&'static str>,
    browser_type: &'static str,
}

fn rule_match<'a>(rule: &Rule, ua: &'a str) -> Option<regex::Captures<'a>> {
    match rule {
        Rule::Plain(regex) => regex.captures(ua),
        Rule::NotFollowedBy { pattern, guard } => {
            let mut start = 0;
            while let Some(captures) = pattern.captures_at(ua, start) {
                let match_start = captures.get(0)?.start();
                if !guard.is_match(&ua[match_start..]) {
                    return Some(captures);
                }
                // Every match starts with `Chrom`, so the next char boundary is one byte on.
                start = match_start + 1;
            }
            None
        }
    }
}

fn detect(ua: &str) -> Option<Detected> {
    let (name, captures) = BROWSER_RULES
        .iter()
        .find_map(|rule| rule_match(&rule.rule, ua).map(|captures| (rule.name, captures)))?;
    if name == "searchbot" {
        return Some(Detected {
            name: "bot",
            version: None,
            os: None,
            browser_type: "bot",
        });
    }
    let mut parts: Vec<&str> = captures
        .get(1)
        .map(|version| version.as_str().split(['.', '_']).take(3).collect())
        .unwrap_or_default();
    if !parts.is_empty() {
        parts.resize(3, "0");
    }
    let version = parts.join(".");
    let os = OS_RULES
        .iter()
        .find(|(_, regex)| regex.is_match(ua))
        .map(|(os, _)| *os);
    let browser_type = if SEARCHBOT_OS.is_match(ua) {
        "bot-device"
    } else {
        "browser"
    };
    Some(Detected {
        name,
        version: Some(version),
        os,
        browser_type,
    })
}

fn detect_device(ua: &str) -> &'static str {
    if WINDOWS_PHONE.is_match(ua) {
        "Windows Phone"
    } else if ua.contains("iPad") {
        "iPad"
    } else if ua.contains("iPod") {
        "iPod Touch"
    } else if ua.contains("iPhone") {
        "iPhone"
    } else if BLACKBERRY.is_match(ua) {
        "BlackBerry"
    } else if ua.contains("Android") && !ua.contains("Mobile") {
        "Android Tablet"
    } else if ua.contains("Android") {
        "Android"
    } else {
        ""
    }
}

fn detect_device_type(device: &str) -> &'static str {
    match device {
        "iPad" | "Android Tablet" => "Tablet",
        "" => "Desktop",
        _ => "Mobile",
    }
}

pub fn parse_user_agent(ua: &str) -> Value {
    if ua.is_empty() || ua.encode_utf16().count() > MAX_USER_AGENT_LENGTH {
        return Value::Null;
    }
    let detected = detect(ua);
    let device = detect_device(ua);
    json!({
        "browser": detected.as_ref().map(|d| d.name),
        "browserVersion": detected.as_ref().and_then(|d| d.version.clone()),
        "os": detected.as_ref().and_then(|d| d.os),
        "browserType": detected.as_ref().map(|d| d.browser_type),
        "device": device,
        "deviceType": detect_device_type(device),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_user_agent_matches_the_node_implementation() {
        let cases: Vec<Value> =
            serde_json::from_str(include_str!("../tests/static/user_agent_cases.json"))
                .expect("user agent fixture parses");
        let mismatches: Vec<String> = cases
            .iter()
            .filter_map(|case| {
                let user_agent = case["userAgent"].as_str().expect("userAgent is a string");
                let actual = parse_user_agent(user_agent);
                (actual != case["expected"]).then(|| {
                    format!(
                        "{}: expected {} got {actual}",
                        case["label"], case["expected"]
                    )
                })
            })
            .collect();
        assert!(cases.len() > 1, "no user agent cases in fixture");
        assert!(mismatches.is_empty(), "{}", mismatches.join("\n"));
    }
}
