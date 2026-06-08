//! Bot detection for `/flags`. UA-substring matcher mirrors posthog-js
//! (`sdk/js-sdk/packages/core/src/utils/bot-detection.ts`); IP-range matcher
//! covers the case where an upstream proxy (e.g. CloudFront) rewrites the
//! User-Agent and only the source IP is usable.

use aho_corasick::{AhoCorasick, MatchKind};
use std::net::IpAddr;
use std::sync::LazyLock;

/// Used as a Prometheus label, so the variant set must stay closed and
/// low-cardinality.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BotCategory {
    Google,
    Ai,
    Seo,
    Uptime,
    Social,
    Headless,
    Crawler,
    Other,
}

impl BotCategory {
    pub fn as_str(self) -> &'static str {
        match self {
            BotCategory::Google => "google",
            BotCategory::Ai => "ai",
            BotCategory::Seo => "seo",
            BotCategory::Uptime => "uptime",
            BotCategory::Social => "social",
            BotCategory::Headless => "headless",
            BotCategory::Crawler => "crawler",
            BotCategory::Other => "other",
        }
    }
}

/// Which signal triggered the bot classification. Reported as a metric label
/// and on the canonical log so operators can see whether UA or IP did the work.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BotSource {
    UserAgent,
    Ip,
}

impl BotSource {
    pub fn as_str(self) -> &'static str {
        match self {
            BotSource::UserAgent => "user_agent",
            BotSource::Ip => "ip",
        }
    }
}

/// (lowercased pattern, category). First-hit; specific names come before
/// generic substrings like `bot/` so e.g. AhrefsBot UAs that also contain
/// `bot/` via a reference URL classify as Seo, not Crawler.
const BOT_PATTERNS: &[(&str, BotCategory)] = &[
    // Google crawlers
    ("google-hoteladsverifier", BotCategory::Google),
    ("adsbot-google", BotCategory::Google),
    ("apis-google", BotCategory::Google),
    ("duplexweb-google", BotCategory::Google),
    ("feedfetcher-google", BotCategory::Google),
    ("google favicon", BotCategory::Google),
    ("google web preview", BotCategory::Google),
    ("google-read-aloud", BotCategory::Google),
    ("googlebot", BotCategory::Google),
    ("googleother", BotCategory::Google),
    ("google-cloudvertexbot", BotCategory::Google),
    ("googleweblight", BotCategory::Google),
    ("mediapartners-google", BotCategory::Google),
    ("storebot-google", BotCategory::Google),
    ("google-inspectiontool", BotCategory::Google),
    // AI crawlers
    ("gptbot", BotCategory::Ai),
    ("oai-searchbot", BotCategory::Ai),
    ("chatgpt-user", BotCategory::Ai),
    ("perplexitybot", BotCategory::Ai),
    ("bytespider", BotCategory::Ai),
    // SEO tools
    ("ahrefsbot", BotCategory::Seo),
    ("ahrefssiteaudit", BotCategory::Seo),
    ("semrushbot", BotCategory::Seo),
    ("siteauditbot", BotCategory::Seo),
    ("splitsignalbot", BotCategory::Seo),
    ("backlinksextendedbot", BotCategory::Seo),
    ("dataforseobot", BotCategory::Seo),
    ("mj12bot", BotCategory::Seo),
    ("rogerbot", BotCategory::Seo),
    ("screaming frog", BotCategory::Seo),
    ("sitebulb", BotCategory::Seo),
    // Uptime monitors
    ("better uptime bot", BotCategory::Uptime),
    ("sentryuptimebot", BotCategory::Uptime),
    ("uptimerobot", BotCategory::Uptime),
    // Headless browsers / automation
    ("headlesschrome", BotCategory::Headless),
    ("cypress", BotCategory::Headless),
    ("chrome-lighthouse", BotCategory::Headless),
    ("prerender", BotCategory::Headless),
    ("vercel-screenshot", BotCategory::Headless),
    // Social link unfurlers
    ("facebookexternal", BotCategory::Social),
    ("facebookcatalog", BotCategory::Social),
    ("linkedinbot", BotCategory::Social),
    ("meta-externalagent", BotCategory::Social),
    ("pinterest", BotCategory::Social),
    ("slackbot", BotCategory::Social),
    ("twitterbot", BotCategory::Social),
    // Named search crawlers
    ("baiduspider", BotCategory::Crawler),
    ("bingbot", BotCategory::Crawler),
    ("bingpreview", BotCategory::Crawler),
    ("duckduckbot", BotCategory::Crawler),
    ("http://yandex.com/bots", BotCategory::Crawler),
    ("msnbot", BotCategory::Crawler),
    ("petalbot", BotCategory::Crawler),
    ("slurp", BotCategory::Crawler),
    ("yahoo! slurp", BotCategory::Crawler),
    ("yandexbot", BotCategory::Crawler),
    // Other named bots
    ("amazonbot", BotCategory::Other),
    ("amazonproductbot", BotCategory::Other),
    ("app.hypefactors.com", BotCategory::Other),
    ("applebot", BotCategory::Other),
    ("archive.org_bot", BotCategory::Other),
    ("awariobot", BotCategory::Other),
    ("deepscan", BotCategory::Other),
    ("hubspot", BotCategory::Other),
    ("ia_archiver", BotCategory::Other),
    ("leikibot", BotCategory::Other),
    ("nessus", BotCategory::Other),
    ("sebot-wa", BotCategory::Other),
    ("trendictionbot", BotCategory::Other),
    ("turnitin", BotCategory::Other),
    ("vercelbot", BotCategory::Other),
    ("zoombot", BotCategory::Other),
    // Generic substrings — keep below the named-bot entries. `classify`
    // returns the lowest pattern index, so specific names win over `bot/`
    // / `crawler`. Guarded by `specific_pattern_beats_generic_bot_substring`.
    ("bot.htm", BotCategory::Crawler),
    ("bot.php", BotCategory::Crawler),
    ("(bot;", BotCategory::Crawler),
    ("bot/", BotCategory::Crawler),
    ("crawler", BotCategory::Crawler),
];

/// `MatchKind::Standard` is required for `find_overlapping_iter`, which
/// is what `classify` uses to enumerate every match so the lowest pattern
/// index wins (specific bot names ahead of generic `bot/` / `crawler`).
static BOT_MATCHER: LazyLock<AhoCorasick> = LazyLock::new(|| {
    AhoCorasick::builder()
        .ascii_case_insensitive(true)
        .match_kind(MatchKind::Standard)
        .build(BOT_PATTERNS.iter().map(|(p, _)| *p))
        .expect("BOT_PATTERNS is a valid Aho-Corasick input")
});

/// Call once at server start to keep the first `/flags` request after a
/// pod restart off the matcher/IP-range build path.
pub fn warm_caches() {
    LazyLock::force(&BOT_MATCHER);
    LazyLock::force(&BOT_IP_RANGES);
}

/// When multiple patterns match, the lowest index in `BOT_PATTERNS` wins.
pub fn classify(user_agent: &str) -> Option<BotCategory> {
    if user_agent.is_empty() {
        return None;
    }
    BOT_MATCHER
        .find_overlapping_iter(user_agent)
        .map(|m| m.pattern().as_usize())
        .min()
        .map(|idx| BOT_PATTERNS[idx].1)
}

/// Yandex IP ranges. `yandex.com/ips/` is behind SmartCaptcha and not
/// machine-fetchable, so this list is maintained by hand. Refresh by opening
/// the page in a browser and comparing against the entries below.
///
/// Last reviewed: 2026-05-26.
const YANDEX_FALLBACK_CIDRS: &[(&str, BotCategory)] = &[
    ("5.45.207.0/24", BotCategory::Crawler),
    ("5.255.250.0/24", BotCategory::Crawler),
    ("87.250.224.0/19", BotCategory::Crawler),
    ("95.108.128.0/17", BotCategory::Crawler),
    ("213.180.192.0/19", BotCategory::Crawler),
];

/// Machine-fetchable provider lists, embedded at compile time. Refresh via
/// `rust/feature-flags/scripts/refresh_bot_ips.sh`. The whole provider list
/// maps to a single [`BotCategory`] — the category is a metric label, not
/// per-IP metadata.
///
/// `min_v4_prefix` / `min_v6_prefix` tighten the global [`MIN_V4_PREFIX`] /
/// [`MIN_V6_PREFIX`] floors to each provider's realistic ceiling — the widest
/// prefix it currently publishes per family. An upstream refresh that widens
/// past this floor fails the test suite (and server start) before it can ship;
/// bump the floor deliberately once the wider range is confirmed genuine.
struct Provider {
    name: &'static str,
    blob: &'static str,
    category: BotCategory,
    min_v4_prefix: u32,
    min_v6_prefix: u32,
}

const PROVIDERS: &[Provider] = &[
    // Googlebot: widest currently published `/27` v4, `/64` v6.
    Provider {
        name: "googlebot",
        blob: include_str!("bot_ips/googlebot.json"),
        category: BotCategory::Google,
        min_v4_prefix: 27,
        min_v6_prefix: 64,
    },
    // Bingbot: widest currently published `/22`.
    Provider {
        name: "bingbot",
        blob: include_str!("bot_ips/bingbot.json"),
        category: BotCategory::Crawler,
        min_v4_prefix: 22,
        min_v6_prefix: 64,
    },
    // Applebot: widest currently published `/24`.
    Provider {
        name: "applebot",
        blob: include_str!("bot_ips/applebot.json"),
        category: BotCategory::Other,
        min_v4_prefix: 24,
        min_v6_prefix: 64,
    },
];

/// Schema of every provider JSON: `{"prefixes": [{"ipv4Prefix"|"ipv6Prefix": "..."}, ...]}`.
/// Both `ipv4_prefix` and `ipv6_prefix` are `Option` because each entry has
/// exactly one — Google mixes both kinds in a single array, the others are
/// v4-only.
#[derive(serde::Deserialize)]
struct BotIpManifest {
    prefixes: Vec<BotIpEntry>,
}

#[derive(serde::Deserialize)]
struct BotIpEntry {
    #[serde(rename = "ipv4Prefix")]
    ipv4_prefix: Option<String>,
    #[serde(rename = "ipv6Prefix")]
    ipv6_prefix: Option<String>,
}

/// Flatten the three provider JSONs plus the inline Yandex list into a single
/// `(cidr, category)` vector consumed by [`build_ranges`]. Runs once at
/// `LazyLock` initialization (warmed at server start via [`warm_caches`]).
///
/// Panics on malformed embedded JSON, an entry that has both or neither of
/// `ipv4Prefix` / `ipv6Prefix`, or an entry that exceeds the provider's own
/// width floor (see [`Provider::min_v4_prefix`] / `min_v6_prefix`). The
/// per-provider floor catches upstream drift earlier than the global floor
/// in [`build_ranges`] would; both checks run as defense-in-depth.
fn load_published_cidrs() -> Vec<(String, BotCategory)> {
    let mut out = Vec::new();
    for provider in PROVIDERS {
        let manifest: BotIpManifest = serde_json::from_str(provider.blob)
            .unwrap_or_else(|e| panic!("malformed bot IP JSON for {}: {e}", provider.name));
        for (idx, entry) in manifest.prefixes.into_iter().enumerate() {
            let cidr = match (entry.ipv4_prefix, entry.ipv6_prefix) {
                (Some(v4), None) => v4,
                (None, Some(v6)) => v6,
                _ => panic!(
                    "bot IP JSON {} entry {idx} must have exactly one of \
                     ipv4Prefix / ipv6Prefix",
                    provider.name,
                ),
            };
            enforce_provider_floor(provider, &cidr);
            out.push((cidr, provider.category));
        }
    }
    for (cidr, category) in YANDEX_FALLBACK_CIDRS {
        out.push(((*cidr).to_string(), *category));
    }
    out
}

/// Per-provider width-floor check. Fails fast if an upstream refresh
/// publishes a CIDR wider than the provider's documented ceiling — caught
/// at `LazyLock` init / server start, not silently shipped.
fn enforce_provider_floor(provider: &Provider, cidr: &str) {
    let parsed = parse_cidr(cidr)
        .unwrap_or_else(|| panic!("invalid CIDR from provider {}: {cidr}", provider.name));
    let host_bits = (parsed.end - parsed.start + 1).trailing_zeros();
    let (max_host_bits, floor_prefix) = if parsed.is_v4 {
        (32 - provider.min_v4_prefix, provider.min_v4_prefix)
    } else {
        (128 - provider.min_v6_prefix, provider.min_v6_prefix)
    };
    assert!(
        host_bits <= max_host_bits,
        "provider {} CIDR {cidr} is broader than its per-provider floor (/{}); \
         widen the floor deliberately if upstream genuinely publishes this",
        provider.name,
        floor_prefix,
    );
}

/// Half-open is tempting but inclusive `[start, end]` is what fits CIDR
/// semantics and lets v4 share the lookup with v6 by widening to `u128`.
#[derive(Debug, Clone, Copy)]
struct IpRange {
    start: u128,
    end: u128,
    category: BotCategory,
}

/// Split-by-family so v4 lookups never scan v6 entries and vice versa. Each
/// slice is sorted by `start`, enabling `partition_point` binary search.
struct BotIpRanges {
    v4: Box<[IpRange]>,
    v6: Box<[IpRange]>,
}

static BOT_IP_RANGES: LazyLock<BotIpRanges> =
    LazyLock::new(|| build_ranges(&load_published_cidrs()));

/// Minimum CIDR prefix accepted from any provider list — bounds how many
/// addresses a single entry classifies as bots. Enforced by `build_ranges`,
/// surfaced at server start via `warm_caches()`.
///
/// Current widest entries: `/17` (Yandex v4), `/64` (Googlebot v6 — JSON
/// publishes per-/64 ranges, not a supernet).
const MIN_V4_PREFIX: u32 = 16;
const MIN_V6_PREFIX: u32 = 32;

fn build_ranges(cidrs: &[(String, BotCategory)]) -> BotIpRanges {
    let mut v4 = Vec::new();
    let mut v6 = Vec::new();
    for (cidr, category) in cidrs {
        let parsed =
            parse_cidr(cidr).unwrap_or_else(|| panic!("invalid CIDR from provider list: {cidr}"));
        // `2^host_bits = end - start + 1` for an inclusive [start, end].
        let host_bits = (parsed.end - parsed.start + 1).trailing_zeros();
        let max_host_bits = if parsed.is_v4 {
            32 - MIN_V4_PREFIX
        } else {
            128 - MIN_V6_PREFIX
        };
        assert!(
            host_bits <= max_host_bits,
            "provider CIDR {cidr} is broader than the minimum prefix \
             (/{} v4, /{} v6); refusing to classify that many addresses as bots",
            MIN_V4_PREFIX,
            MIN_V6_PREFIX,
        );
        let range = IpRange {
            start: parsed.start,
            end: parsed.end,
            category: *category,
        };
        if parsed.is_v4 {
            v4.push(range);
        } else {
            v6.push(range);
        }
    }
    v4.sort_by_key(|r| r.start);
    v6.sort_by_key(|r| r.start);
    BotIpRanges {
        v4: v4.into_boxed_slice(),
        v6: v6.into_boxed_slice(),
    }
}

struct ParsedCidr {
    start: u128,
    end: u128,
    is_v4: bool,
}

fn parse_cidr(cidr: &str) -> Option<ParsedCidr> {
    let (addr_str, prefix_str) = cidr.split_once('/')?;
    let prefix: u8 = prefix_str.parse().ok()?;
    let addr: IpAddr = addr_str.parse().ok()?;
    match addr {
        IpAddr::V4(v4) => {
            if prefix > 32 {
                return None;
            }
            let base = u32::from(v4);
            let mask = if prefix == 0 {
                0
            } else {
                !0u32 << (32 - prefix)
            };
            let start = base & mask;
            let end = start | !mask;
            Some(ParsedCidr {
                start: u128::from(start),
                end: u128::from(end),
                is_v4: true,
            })
        }
        IpAddr::V6(v6) => {
            if prefix > 128 {
                return None;
            }
            let base = u128::from(v6);
            let mask = if prefix == 0 {
                0
            } else {
                !0u128 << (128 - prefix)
            };
            let start = base & mask;
            let end = start | !mask;
            Some(ParsedCidr {
                start,
                end,
                is_v4: false,
            })
        }
    }
}

/// Collapse IPv4-mapped IPv6 (`::ffff:1.2.3.4`) to IPv4 so reverse proxies
/// that hand us mapped form still hit the v4 ranges.
fn normalize(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(v6) => v6
            .to_ipv4_mapped()
            .map(IpAddr::V4)
            .unwrap_or(IpAddr::V6(v6)),
        v4 => v4,
    }
}

/// Returns the matched bot category if `ip` falls inside any published bot
/// range. Hot path is one `partition_point` over a few dozen sorted entries.
pub fn classify_ip(ip: IpAddr) -> Option<BotCategory> {
    let ranges = &*BOT_IP_RANGES;
    match normalize(ip) {
        IpAddr::V4(v4) => lookup(&ranges.v4, u128::from(u32::from(v4))),
        IpAddr::V6(v6) => lookup(&ranges.v6, u128::from(v6)),
    }
}

fn lookup(ranges: &[IpRange], key: u128) -> Option<BotCategory> {
    // `partition_point` returns the count of entries whose `start <= key`.
    // The candidate range, if any, is the immediately preceding entry.
    let idx = ranges.partition_point(|r| r.start <= key);
    if idx == 0 {
        return None;
    }
    let r = ranges[idx - 1];
    (key <= r.end).then_some(r.category)
}

/// Unified classifier: UA first (cheaper, more specific), then IP. Returns
/// the matched category plus which signal fired, so the caller can label
/// metrics and logs without re-running either check.
pub fn classify_request(user_agent: Option<&str>, ip: IpAddr) -> Option<(BotCategory, BotSource)> {
    if let Some(ua) = user_agent {
        if let Some(c) = classify(ua) {
            return Some((c, BotSource::UserAgent));
        }
    }
    classify_ip(ip).map(|c| (c, BotSource::Ip))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        BotCategory::Google
    )]
    #[case("Googlebot-Image/1.0", BotCategory::Google)]
    #[case(
        "AdsBot-Google (+http://www.google.com/adsbot.html)",
        BotCategory::Google
    )]
    #[case(
        "APIs-Google (+https://developers.google.com/webmasters/APIs-Google.html)",
        BotCategory::Google
    )]
    #[case("Mozilla/5.0 (compatible; GoogleOther)", BotCategory::Google)]
    #[case(
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        BotCategory::Crawler
    )]
    #[case(
        "DuckDuckBot/1.1; (+http://duckduckgo.com/duckduckbot.html)",
        BotCategory::Crawler
    )]
    #[case(
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
        BotCategory::Crawler
    )]
    #[case(
        "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
        BotCategory::Crawler
    )]
    #[case(
        "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
        BotCategory::Seo
    )]
    #[case(
        "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
        BotCategory::Seo
    )]
    #[case("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.0; +https://openai.com/gptbot)", BotCategory::Ai)]
    #[case("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ChatGPT-User/1.0; +https://openai.com/bot)", BotCategory::Ai)]
    #[case("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/bot)", BotCategory::Ai)]
    #[case(
        "Mozilla/5.0 (compatible; Bytespider; spider-feedback@bytedance.com)",
        BotCategory::Ai
    )]
    #[case(
        "Mozilla/5.0 (compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)",
        BotCategory::Uptime
    )]
    #[case("Better Uptime Bot Manifest/1.0", BotCategory::Uptime)]
    #[case(
        "Mozilla/5.0 (compatible; LinkedInBot/1.0; +http://www.linkedin.com/)",
        BotCategory::Social
    )]
    #[case(
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        BotCategory::Social
    )]
    #[case("Twitterbot/1.0", BotCategory::Social)]
    #[case(
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        BotCategory::Social
    )]
    #[case("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.0.0 Safari/537.36", BotCategory::Headless)]
    #[case(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Cypress/13.0.0",
        BotCategory::Headless
    )]
    fn classify_returns_expected_category(#[case] ua: &str, #[case] expected: BotCategory) {
        assert_eq!(classify(ua), Some(expected), "UA: {}", ua);
    }

    #[rstest]
    #[case("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")]
    #[case("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0")]
    #[case("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1")]
    #[case("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15")]
    #[case("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")]
    #[case("posthog-js/1.374.3")]
    #[case("posthog-python/3.0.0")]
    #[case("posthog-node/5.34.7")]
    #[case("posthog-go/1.0.0")]
    fn classify_returns_none_for_real_clients(#[case] ua: &str) {
        assert_eq!(
            classify(ua),
            None,
            "Should not match real client UA: {}",
            ua
        );
    }

    #[test]
    fn empty_user_agent_is_not_a_bot() {
        assert_eq!(classify(""), None);
    }

    #[rstest]
    #[case("Mozilla/5.0 (compatible; GoogleBot/2.1)", BotCategory::Google)]
    #[case("Mozilla/5.0 (compatible; GOOGLEBOT/2.1)", BotCategory::Google)]
    #[case("Mozilla/5.0 (compatible; googlebot/2.1)", BotCategory::Google)]
    #[case("MOZILLA/5.0 GPTBOT/1.0", BotCategory::Ai)]
    #[case("AHREFSBOT/7.0", BotCategory::Seo)]
    fn matching_is_case_insensitive(#[case] ua: &str, #[case] expected: BotCategory) {
        assert_eq!(classify(ua), Some(expected));
    }

    #[test]
    fn category_as_str_is_low_cardinality() {
        // Guards the Prometheus label invariant: short, stable, ASCII.
        for &(_, cat) in BOT_PATTERNS {
            let s = cat.as_str();
            assert!(!s.is_empty());
            assert!(s.len() < 32);
            assert!(s.chars().all(|c| c.is_ascii_lowercase() || c == '_'));
        }
    }

    #[test]
    fn bot_patterns_are_lowercase() {
        // Keeps the source-of-truth comparison with the SDK list trivial.
        for &(pattern, _) in BOT_PATTERNS {
            assert_eq!(
                pattern,
                pattern.to_ascii_lowercase(),
                "Pattern must be lowercase: {}",
                pattern
            );
        }
    }

    #[test]
    fn every_pattern_classifies_as_its_own_category() {
        // A UA equal to a pattern must classify as that pattern's
        // category — guards the lowest-index-wins rule against any
        // future matcher drift.
        for &(pattern, expected) in BOT_PATTERNS {
            assert_eq!(
                classify(pattern),
                Some(expected),
                "Pattern {pattern:?} should classify as {expected:?}",
            );
        }
    }

    /// UAs that contain both a specific bot name and the generic `bot/`
    /// substring — exercises the lowest-index tiebreaker.
    #[rstest]
    #[case(
        "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
        BotCategory::Seo
    )]
    #[case(
        "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
        BotCategory::Seo
    )]
    #[case(
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        BotCategory::Crawler
    )]
    fn specific_pattern_beats_generic_bot_substring(
        #[case] ua: &str,
        #[case] expected: BotCategory,
    ) {
        assert_eq!(classify(ua), Some(expected));
    }

    mod ip {
        use super::*;
        use std::net::Ipv4Addr;

        #[rstest]
        // Googlebot: published /27s inside the historical 66.249.x.x block.
        // Pick from 66.249.66.x because that /24 is densely covered (every
        // /27 in .0–.224); any single-/27 drift in a refresh still leaves
        // these representative samples passing.
        #[case("66.249.66.0", BotCategory::Google)]
        #[case("66.249.66.31", BotCategory::Google)]
        // Googlebot: GCP-hosted /28 (192.178.x and 34.x publish-time ranges).
        #[case("192.178.4.0", BotCategory::Google)]
        #[case("34.100.182.96", BotCategory::Google)]
        // Bingbot.
        #[case("207.46.13.42", BotCategory::Crawler)]
        #[case("40.77.139.5", BotCategory::Crawler)]
        // YandexBot.
        #[case("95.108.200.10", BotCategory::Crawler)]
        // Applebot — regression for the IP customer saw (17.246.19.0/24 was
        // published but not blocked because the const carried only
        // 17.241.75.0/26). Cover every Apple second-octet block.
        #[case("17.22.237.0", BotCategory::Other)]
        #[case("17.241.75.0", BotCategory::Other)]
        #[case("17.241.75.255", BotCategory::Other)]
        #[case("17.246.19.0", BotCategory::Other)]
        #[case("17.246.19.255", BotCategory::Other)]
        #[case("17.246.23.128", BotCategory::Other)]
        fn classify_ip_matches_known_bot_ranges(#[case] ip: &str, #[case] expected: BotCategory) {
            let parsed: IpAddr = ip.parse().unwrap();
            assert_eq!(classify_ip(parsed), Some(expected));
        }

        #[rstest]
        // Googlebot — just outside the historical 66.249.64.0/27 → 79.224/27
        // span on either side.
        #[case("66.249.63.255")]
        #[case("66.249.80.0")]
        // Googlebot — first IP below the lowest 192.178.x /27 and the first
        // unpublished /27 inside 192.178.5.0/24 (only .5.0/27 is in the JSON).
        #[case("192.178.3.255")]
        #[case("192.178.5.32")]
        // Googlebot GCP-hosted /28 boundaries (34.100.182.96/28 → .96–.111).
        #[case("34.100.182.95")]
        #[case("34.100.182.112")]
        // Bingbot — one above 40.77.139.0/25 (which ends at .127), one below
        // 207.46.13.0/24, and one above its end.
        #[case("40.77.139.128")]
        #[case("207.46.12.255")]
        #[case("207.46.14.0")]
        // YandexBot — adjacent to the /24 and the /19 boundaries.
        #[case("5.45.206.255")]
        #[case("5.45.208.0")]
        #[case("87.250.223.255")]
        #[case("87.251.0.0")]
        // Applebot — adjacent to the IP that triggered this fix
        // (17.246.19.0/24) plus surrounding-block boundaries.
        #[case("17.246.18.255")]
        #[case("17.246.20.0")]
        #[case("17.246.16.0")] // gap between 17.246.15.0/24 and .19.0/24
        #[case("17.241.74.255")]
        #[case("17.241.76.0")]
        #[case("17.22.236.255")]
        #[case("17.22.238.0")]
        // Apple-owned /8 but far from any published Applebot block —
        // these were never bot ranges and never should be.
        #[case("17.0.0.1")]
        #[case("17.142.0.1")]
        #[case("17.248.1.1")]
        // Common public DNS / CDN ranges that aren't on any bot list.
        #[case("8.8.8.8")]
        #[case("1.1.1.1")]
        #[case("104.16.0.1")]
        // Documented test-net ranges (RFC 5737) — guaranteed non-bot.
        #[case("192.0.2.1")]
        #[case("198.51.100.1")]
        #[case("203.0.113.1")]
        // Private RFC1918.
        #[case("10.0.0.1")]
        #[case("192.168.1.1")]
        // Loopback.
        #[case("127.0.0.1")]
        fn classify_ip_returns_none_for_non_bot_ips(#[case] ip: &str) {
            let parsed: IpAddr = ip.parse().unwrap();
            assert_eq!(classify_ip(parsed), None);
        }

        #[rstest]
        // Each of these is a published Googlebot /64 in googlebot.json —
        // lowest, mid, and the highest currently published (`:b6::/64`).
        #[case("2001:4860:4801:2::1")]
        #[case("2001:4860:4801:42::1")]
        #[case("2001:4860:4801:b6::ffff")]
        fn googlebot_ipv6_published_64s_match(#[case] ip: &str) {
            let parsed: IpAddr = ip.parse().unwrap();
            assert_eq!(classify_ip(parsed), Some(BotCategory::Google));
        }

        #[rstest]
        // Gaps inside Google's 2001:4860:4801::/48 that are NOT published as
        // /64s. The classifier is JSON-precise (no /48 supernet), so these
        // must NOT match — they may be used by non-bot Google services and
        // would be a false positive.
        #[case("2001:4860:4801::1")] // :0::/64 (unpublished)
        #[case("2001:4860:4801:43::1")] // gap between :42::/64 and :44::/64
        #[case("2001:4860:4801:b7::1")] // one above the highest :b6::/64
        #[case("2001:4860:4801:ff::1")] // far above any published /64
        #[case("2001:4860:4802::1")] // outside the historical /48 entirely
        fn googlebot_ipv6_unpublished_blocks_are_not_bots(#[case] ip: &str) {
            let parsed: IpAddr = ip.parse().unwrap();
            assert_eq!(classify_ip(parsed), None);
        }

        #[test]
        fn ipv4_mapped_ipv6_normalizes_to_ipv4_match() {
            // `::ffff:66.249.66.0` represents Googlebot via IPv4-mapped form;
            // upstream proxies sometimes hand us this shape.
            let mapped = Ipv4Addr::new(66, 249, 66, 0).to_ipv6_mapped();
            assert_eq!(classify_ip(IpAddr::V6(mapped)), Some(BotCategory::Google));
        }

        #[test]
        fn arbitrary_ipv6_outside_bot_ranges_is_none() {
            let ip: IpAddr = "2606:4700:4700::1111".parse().unwrap(); // Cloudflare DNS.
            assert_eq!(classify_ip(ip), None);
        }

        #[rstest]
        #[case("0.0.0.0/0", 0u32, u32::MAX)]
        #[case("10.0.0.0/8", 10u32 << 24, (10u32 << 24) | 0x00_FF_FF_FF)]
        #[case("192.168.1.0/24", (192u32 << 24) | (168 << 16) | (1 << 8), (192u32 << 24) | (168 << 16) | (1 << 8) | 0xFF)]
        #[case("203.0.113.42/32", (203u32 << 24) | (113 << 8) | 42, (203u32 << 24) | (113 << 8) | 42)]
        fn parse_cidr_v4_boundaries(
            #[case] cidr: &str,
            #[case] expected_start: u32,
            #[case] expected_end: u32,
        ) {
            let p = parse_cidr(cidr).unwrap();
            assert!(p.is_v4);
            assert_eq!(p.start, u128::from(expected_start));
            assert_eq!(p.end, u128::from(expected_end));
        }

        #[rstest]
        #[case("not-an-ip/24")]
        #[case("10.0.0.0/33")]
        #[case("::/129")]
        #[case("missing-prefix")]
        fn parse_cidr_rejects_malformed(#[case] cidr: &str) {
            assert!(parse_cidr(cidr).is_none());
        }

        #[test]
        fn built_ranges_are_sorted_by_start() {
            // The lookup uses `partition_point` which requires the slice to
            // be sorted by `start`. Guard the invariant the builder enforces.
            let ranges = &*BOT_IP_RANGES;
            assert!(ranges.v4.windows(2).all(|w| w[0].start <= w[1].start));
            assert!(ranges.v6.windows(2).all(|w| w[0].start <= w[1].start));
        }

        #[test]
        fn built_ranges_are_non_overlapping() {
            // `lookup` only inspects the largest `start <= key` entry,
            // so an overlapping later range would mask an earlier one.
            let ranges = &*BOT_IP_RANGES;
            for w in ranges.v4.windows(2) {
                assert!(
                    w[0].end < w[1].start,
                    "overlapping v4 ranges: [{}, {}] and [{}, {}]",
                    w[0].start,
                    w[0].end,
                    w[1].start,
                    w[1].end,
                );
            }
            for w in ranges.v6.windows(2) {
                assert!(
                    w[0].end < w[1].start,
                    "overlapping v6 ranges: [{}, {}] and [{}, {}]",
                    w[0].start,
                    w[0].end,
                    w[1].start,
                    w[1].end,
                );
            }
        }

        #[test]
        fn every_published_cidr_parses() {
            // build_ranges panics on a bad CIDR; touching LazyLock would
            // have already done this, but be explicit for future drift.
            for (cidr, _) in load_published_cidrs() {
                assert!(parse_cidr(&cidr).is_some(), "failed to parse {cidr}");
            }
        }

        /// Coverage test — every CIDR in every provider JSON (plus the inline
        /// Yandex fallback) MUST classify as the expected category for both the
        /// network address and the last address in the range. This is the test
        /// that would have caught the original Applebot regression: as long as
        /// `17.246.19.0/24` is in `applebot.json`, classifying `17.246.19.0`
        /// (and `17.246.19.255`) returns `Some(BotCategory::Other)`.
        ///
        /// Failure mode tells the operator either upstream changed shape or the
        /// `PROVIDERS` category mapping is out of sync.
        #[test]
        fn every_published_cidr_is_classified() {
            for (cidr, expected) in load_published_cidrs() {
                let parsed = parse_cidr(&cidr).expect("provider CIDR parses");
                let net = if parsed.is_v4 {
                    IpAddr::V4(Ipv4Addr::from(parsed.start as u32))
                } else {
                    IpAddr::V6(std::net::Ipv6Addr::from(parsed.start))
                };
                let last = if parsed.is_v4 {
                    IpAddr::V4(Ipv4Addr::from(parsed.end as u32))
                } else {
                    IpAddr::V6(std::net::Ipv6Addr::from(parsed.end))
                };
                assert_eq!(
                    classify_ip(net),
                    Some(expected),
                    "{cidr}: network address {net} did not classify as {expected:?}",
                );
                assert_eq!(
                    classify_ip(last),
                    Some(expected),
                    "{cidr}: last address {last} did not classify as {expected:?}",
                );
            }
        }

        /// Schema test — every embedded provider JSON deserializes and every
        /// entry has exactly one of `ipv4Prefix` / `ipv6Prefix`. Guards against
        /// an upstream format change silently producing a smaller, partially
        /// loaded list (the load path would skip entries with both keys absent
        /// without this guard).
        #[test]
        fn each_provider_json_is_well_formed() {
            for provider in PROVIDERS {
                let manifest: BotIpManifest = serde_json::from_str(provider.blob)
                    .unwrap_or_else(|e| panic!("{} JSON failed to parse: {e}", provider.name));
                assert!(
                    !manifest.prefixes.is_empty(),
                    "{} JSON has no prefixes — likely an upstream outage \
                     or shape change",
                    provider.name,
                );
                for (idx, entry) in manifest.prefixes.iter().enumerate() {
                    assert!(
                        entry.ipv4_prefix.is_some() ^ entry.ipv6_prefix.is_some(),
                        "{} entry {idx} must have exactly one of \
                         ipv4Prefix / ipv6Prefix",
                        provider.name,
                    );
                }
            }
        }

        /// Per-provider floor: each provider's published CIDRs must fit
        /// within its own declared min-prefix. Exercises the real
        /// [`enforce_provider_floor`] (rather than re-deriving its arithmetic)
        /// so a bug in that check is caught here, not just at `LazyLock` init.
        #[test]
        fn each_provider_respects_its_own_width_floor() {
            for provider in PROVIDERS {
                let manifest: BotIpManifest =
                    serde_json::from_str(provider.blob).expect("provider JSON parses");
                for entry in manifest.prefixes {
                    let cidr = entry
                        .ipv4_prefix
                        .or(entry.ipv6_prefix)
                        .expect("entry has exactly one prefix");
                    // Panics (failing the test) if the entry is wider than the
                    // provider's declared floor.
                    enforce_provider_floor(provider, &cidr);
                }
            }
        }

        /// Yandex stays on the global floor (its widest entry is `/17`,
        /// inside the `/16` ceiling).
        #[test]
        fn yandex_respects_global_width_floor() {
            for (cidr, _) in YANDEX_FALLBACK_CIDRS {
                let parsed = parse_cidr(cidr).expect("yandex CIDR parses");
                let host_bits = (parsed.end - parsed.start + 1).trailing_zeros();
                let max_host_bits = if parsed.is_v4 {
                    32 - MIN_V4_PREFIX
                } else {
                    128 - MIN_V6_PREFIX
                };
                assert!(
                    host_bits <= max_host_bits,
                    "{cidr} exceeds the global width floor",
                );
            }
        }

        #[test]
        #[should_panic(expected = "broader than the minimum prefix")]
        fn build_ranges_rejects_overly_broad_v4_cidr() {
            drop(build_ranges(&[(
                "66.0.0.0/8".to_string(),
                BotCategory::Google,
            )]));
        }

        #[test]
        #[should_panic(expected = "broader than the minimum prefix")]
        fn build_ranges_rejects_overly_broad_v6_cidr() {
            drop(build_ranges(&[(
                "2001::/16".to_string(),
                BotCategory::Google,
            )]));
        }

        /// Per-provider floor panics with a provider-specific message before
        /// the global floor would have. Construct a synthetic Applebot entry
        /// at `/16` (within the global `/16` floor but well past Applebot's
        /// own `/24` floor) and assert the per-provider check fires.
        #[test]
        #[should_panic(expected = "broader than its per-provider floor")]
        fn enforce_provider_floor_rejects_over_widening() {
            let applebot = PROVIDERS
                .iter()
                .find(|p| p.name == "applebot")
                .expect("applebot provider present");
            enforce_provider_floor(applebot, "17.0.0.0/16");
        }
    }

    mod request {
        use super::*;
        use std::net::Ipv4Addr;

        const GOOGLEBOT_IP: IpAddr = IpAddr::V4(Ipv4Addr::new(66, 249, 66, 0));
        const NON_BOT_IP: IpAddr = IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8));

        #[test]
        fn ua_match_takes_priority_over_ip() {
            // Even if both signals match, UA wins because it's the more
            // specific signal (the IP could be a misconfigured network).
            let (cat, source) = classify_request(
                Some("Mozilla/5.0 (compatible; AhrefsBot/7.0)"),
                GOOGLEBOT_IP,
            )
            .unwrap();
            assert_eq!(cat, BotCategory::Seo);
            assert_eq!(source, BotSource::UserAgent);
        }

        #[test]
        fn falls_back_to_ip_when_ua_does_not_match() {
            let (cat, source) = classify_request(
                Some("Mozilla/5.0 (Windows NT 10.0) Chrome/120"),
                GOOGLEBOT_IP,
            )
            .unwrap();
            assert_eq!(cat, BotCategory::Google);
            assert_eq!(source, BotSource::Ip);
        }

        #[test]
        fn missing_ua_still_runs_ip_check() {
            let (cat, source) = classify_request(None, GOOGLEBOT_IP).unwrap();
            assert_eq!(cat, BotCategory::Google);
            assert_eq!(source, BotSource::Ip);
        }

        #[test]
        fn returns_none_when_neither_signal_matches() {
            assert!(classify_request(Some("Mozilla/5.0 Chrome/120"), NON_BOT_IP).is_none());
            assert!(classify_request(None, NON_BOT_IP).is_none());
        }

        #[test]
        fn bot_source_labels_are_low_cardinality() {
            for s in [BotSource::UserAgent, BotSource::Ip] {
                let label = s.as_str();
                assert!(!label.is_empty());
                assert!(label.len() < 32);
                assert!(label.chars().all(|c| c.is_ascii_lowercase() || c == '_'));
            }
        }
    }
}
