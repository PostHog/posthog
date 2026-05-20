//! Bot User-Agent detection for short-circuiting `/flags` requests.
//!
//! Mirror of the substring blocklist used by posthog-js at
//! `sdk/js-sdk/packages/core/src/utils/bot-detection.ts` (function
//! `isBlockedUA`). Keep the patterns in sync with that file — the SDK list
//! is the source of truth and is reused so that a request the browser would
//! have suppressed reaches the same outcome if it slips through.
//!
//! Matching mirrors the SDK exactly: the haystack is lowercased and each
//! pattern is checked with a plain substring contains. No regex, no anchors.
//!
//! `BOT_PATTERNS` pairs each pattern with a low-cardinality category label
//! suitable for Prometheus (`google`, `ai`, `seo`, `uptime`, `social`,
//! `headless`, `crawler`, `other`).

/// Low-cardinality category label for the matched bot pattern. The set is
/// closed — keep it small so Prometheus stays happy.
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

/// (lowercased pattern, category). Matching is first-hit; specific bot
/// names appear before the generic "Bot-like words" group below them so
/// that e.g. an AhrefsBot UA — which also contains the generic `bot/`
/// substring via its reference URL — is correctly categorized as Seo
/// rather than the catch-all Crawler. Order within each named group
/// matches the SDK list (`sdk/js-sdk/packages/core/src/utils/bot-detection.ts`).
const BOT_PATTERNS: &[(&str, BotCategory)] = &[
    // Google crawlers (placed first so any Googlebot UA pins as Google,
    // even when the same string also matches generic `bot/`).
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
    // Generic "bot-like" substrings — checked LAST so they don't shadow
    // any of the specific entries above.
    ("bot.htm", BotCategory::Crawler),
    ("bot.php", BotCategory::Crawler),
    ("(bot;", BotCategory::Crawler),
    ("bot/", BotCategory::Crawler),
    ("crawler", BotCategory::Crawler),
];

/// Returns the bot category that matched `user_agent`, or `None` if the
/// User-Agent does not look like a known bot. Matches the SDK's
/// case-insensitive substring semantics: an empty/missing UA is never a bot.
pub fn classify(user_agent: &str) -> Option<BotCategory> {
    if user_agent.is_empty() {
        return None;
    }
    // The SDK lowercases the UA once and then runs `indexOf` for each
    // pattern. We do the same: one allocation, then borrow into it for the
    // substring search.
    let lowered = user_agent.to_ascii_lowercase();
    for (pattern, category) in BOT_PATTERNS {
        if lowered.contains(*pattern) {
            return Some(*category);
        }
    }
    None
}

/// Convenience: `true` if `classify` returns `Some`.
pub fn is_blocked_ua(user_agent: &str) -> bool {
    classify(user_agent).is_some()
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
        assert!(is_blocked_ua(ua), "is_blocked_ua should be true for {}", ua);
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
        assert!(!is_blocked_ua(ua));
    }

    #[test]
    fn empty_user_agent_is_not_a_bot() {
        assert_eq!(classify(""), None);
        assert!(!is_blocked_ua(""));
    }

    #[rstest]
    // SDK lowercases before scanning, so any casing of the pattern
    // should match. Verifies the customer's actual UA flavor:
    // Googlebot uses mixed casing in the wild.
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
        // Every label must be a short, stable string suitable for a
        // Prometheus label value. Guard against accidental drift.
        for &(_, cat) in BOT_PATTERNS {
            let s = cat.as_str();
            assert!(!s.is_empty());
            assert!(s.len() < 32);
            assert!(s.chars().all(|c| c.is_ascii_lowercase() || c == '_'));
        }
    }

    #[test]
    fn bot_patterns_are_lowercase() {
        // The matcher lowercases the haystack but trusts patterns are
        // already lowercase. Guard against future drift that would
        // silently bypass the matcher.
        for &(pattern, _) in BOT_PATTERNS {
            assert_eq!(
                pattern,
                pattern.to_ascii_lowercase(),
                "Pattern must be lowercase: {}",
                pattern
            );
        }
    }
}
