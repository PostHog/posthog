from dataclasses import dataclass


@dataclass
class BotDefinition:
    name: str  # Display name: "Googlebot", "ChatGPT"
    category: str  # Category: "search_crawler", "ai_crawler", "ai_search", "ai_assistant"
    traffic_type: str  # Type: "Bot", "AI Agent", "Automation"
    operator: str  # Operator/company: "Google", "OpenAI", "Anthropic"
    documentation_url: str | None = None  # Operator- or directory-published page describing the bot
    description: str | None = None  # Optional 1-line summary; None until populated case-by-case


# Pattern -> BotDefinition mapping (ordered by specificity)
BOT_DEFINITIONS: dict[str, BotDefinition] = {
    # AI Crawlers (training data collection)
    "GPTBot": BotDefinition(
        "GPTBot", "ai_crawler", "AI Agent", "OpenAI", documentation_url="https://bots.fyi/d/gptbot"
    ),
    "Google-CloudVertexBot": BotDefinition(
        "Google Cloud Vertex",
        "ai_crawler",
        "AI Agent",
        "Google",
        documentation_url="https://bots.fyi/d/google-cloudvertexbot",
    ),
    "Google-Extended": BotDefinition(
        "Google AI", "ai_crawler", "AI Agent", "Google", documentation_url="https://bots.fyi/d/google-extended"
    ),
    "GoogleOther": BotDefinition(
        "GoogleOther", "ai_crawler", "AI Agent", "Google", documentation_url="https://bots.fyi/d/googleother"
    ),
    "Claude-SearchBot": BotDefinition(
        "Claude Search",
        "ai_search",
        "AI Agent",
        "Anthropic",
        documentation_url="https://bots.fyi/d/claude-searchbot",
    ),
    "Claude-User": BotDefinition(
        "Claude User", "ai_assistant", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claude-user"
    ),
    "ClaudeBot": BotDefinition(
        "Claude", "ai_crawler", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claudebot"
    ),
    "Claude-Web": BotDefinition(
        "Claude Web", "ai_crawler", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claudebot"
    ),
    "anthropic-ai": BotDefinition(
        "Anthropic", "ai_crawler", "AI Agent", "Anthropic", documentation_url="https://bots.fyi/d/claudebot"
    ),
    "Perplexity-User": BotDefinition(
        "Perplexity User",
        "ai_assistant",
        "AI Agent",
        "Perplexity",
        documentation_url="https://bots.fyi/d/perplexity-user",
    ),
    "PerplexityBot": BotDefinition(
        "Perplexity", "ai_search", "AI Agent", "Perplexity", documentation_url="https://bots.fyi/d/perplexitybot"
    ),
    "CCBot": BotDefinition(
        "Common Crawl", "ai_crawler", "AI Agent", "Common Crawl", documentation_url="https://bots.fyi/d/ccbot"
    ),
    "meta-externalagent": BotDefinition(
        "Meta AI", "ai_crawler", "AI Agent", "Meta", documentation_url="https://bots.fyi/d/meta-externalagent"
    ),
    "Bytespider": BotDefinition(
        "ByteDance", "ai_crawler", "AI Agent", "ByteDance", documentation_url="https://bots.fyi/d/bytespider"
    ),
    "TikTokSpider": BotDefinition(
        "TikTok AI", "ai_crawler", "AI Agent", "ByteDance", documentation_url="https://bots.fyi/d/tiktokspider"
    ),
    "cohere-ai": BotDefinition(
        "Cohere", "ai_crawler", "AI Agent", "Cohere", documentation_url="https://docs.cohere.com/"
    ),
    "Diffbot": BotDefinition(
        "Diffbot",
        "ai_crawler",
        "AI Agent",
        "Diffbot",
        documentation_url="https://www.diffbot.com/products/automatic/",
    ),
    "omgili": BotDefinition(
        "Webz.io",
        "ai_crawler",
        "AI Agent",
        "Webz.io",
        documentation_url="https://webz.io/blog/web-data/what-is-our-crawler/",
    ),
    "Webzio-Extended": BotDefinition(
        "Webz.io Extended",
        "ai_crawler",
        "AI Agent",
        "Webz.io",
        documentation_url="https://webz.io/blog/web-data/what-is-our-crawler/",
    ),
    "Timpibot": BotDefinition("Timpi", "ai_crawler", "AI Agent", "Timpi", documentation_url="https://www.timpi.io/"),
    "Amazonbot": BotDefinition(
        "Amazon", "ai_crawler", "AI Agent", "Amazon", documentation_url="https://bots.fyi/d/amazonbot"
    ),
    "PetalBot": BotDefinition(
        "Petal", "ai_crawler", "AI Agent", "Huawei", documentation_url="https://bots.fyi/d/petalbot"
    ),
    "Brightbot": BotDefinition(
        "Brightbot", "ai_crawler", "AI Agent", "Bright Data", documentation_url="https://bots.fyi/d/brightbot"
    ),
    "amazon-kendra": BotDefinition(
        "Amazon Kendra",
        "ai_crawler",
        "AI Agent",
        "Amazon",
        documentation_url="https://docs.aws.amazon.com/kendra/",
    ),
    # AI Search (search result generation)
    "OAI-SearchBot": BotDefinition(
        "OpenAI Search", "ai_search", "AI Agent", "OpenAI", documentation_url="https://bots.fyi/d/oai-searchbot"
    ),
    "Applebot-Extended": BotDefinition(
        "Apple AI", "ai_search", "AI Agent", "Apple", documentation_url="https://bots.fyi/d/applebot"
    ),
    # AI Assistants (real-time user-facing fetching)
    "ChatGPT-User": BotDefinition(
        "ChatGPT", "ai_assistant", "AI Agent", "OpenAI", documentation_url="https://bots.fyi/d/chatgpt-user"
    ),
    # Lowercase variant first — Meta emits this casing in the wild (matches the bingbot/Bingbot
    # precedent). Both forms map to the same BotDefinition. The REGEXP_TREE dict is case-sensitive;
    # keeping both entries is the correct approach.
    "meta-externalfetcher": BotDefinition(
        "Meta Fetcher",
        "ai_assistant",
        "AI Agent",
        "Meta",
        documentation_url="https://bots.fyi/d/meta-externalfetcher",
    ),
    "Meta-ExternalFetcher": BotDefinition(
        "Meta Fetcher",
        "ai_assistant",
        "AI Agent",
        "Meta",
        documentation_url="https://bots.fyi/d/meta-externalfetcher",
    ),
    "DuckAssistBot": BotDefinition(
        "DuckDuckGo AI",
        "ai_assistant",
        "AI Agent",
        "DuckDuckGo",
        documentation_url="https://bots.fyi/d/duckassistbot",
    ),
    "MistralAI-User": BotDefinition(
        "Mistral AI", "ai_assistant", "AI Agent", "Mistral", documentation_url="https://docs.mistral.ai/"
    ),
    "Manus-User": BotDefinition("Manus", "ai_assistant", "AI Agent", "Manus", documentation_url="https://manus.im/"),
    "Google-NotebookLM": BotDefinition(
        "NotebookLM", "ai_assistant", "AI Agent", "Google", documentation_url="https://notebooklm.google.com/"
    ),
    "Shap-User": BotDefinition("Shap", "ai_assistant", "AI Agent", "Shap"),
    # PostHog Desktop clients (Electron desktop, React Native mobile, agent CLI, cloud agent server).
    # Dots are escaped because keys are evaluated as re2 regex by the REGEXP_TREE dictionary.
    r"desktop\.hog\.dev": BotDefinition(
        "PostHog Desktop",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/desktop",
    ),
    r"mobile\.hog\.dev": BotDefinition(
        "PostHog Mobile",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/desktop",
    ),
    r"agent\.hog\.dev": BotDefinition(
        "PostHog Desktop Agent",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/desktop",
    ),
    r"cloud\.hog\.dev": BotDefinition(
        "PostHog Desktop Cloud",
        "ai_assistant",
        "AI Agent",
        "PostHog",
        documentation_url="https://posthog.com/desktop",
    ),
    # Agent desktop app embedded browsers (Electron leaks the app name into the UA).
    # Anchored on the Electron token so the Claude/ChatGPT mobile in-app browsers stay Regular.
    "Claude/.*Electron": BotDefinition(
        "Claude Desktop",
        "ai_assistant",
        "AI Agent",
        "Anthropic",
        documentation_url="https://claude.ai/download",
    ),
    "ChatGPT/.*Electron": BotDefinition(
        "ChatGPT Desktop",
        "ai_assistant",
        "AI Agent",
        "OpenAI",
        documentation_url="https://openai.com/chatgpt/desktop/",
    ),
    # Search Crawlers (Applebot/ avoids matching Applebot-Extended)
    "Applebot/": BotDefinition(
        "Applebot", "ai_search", "AI Agent", "Apple", documentation_url="https://bots.fyi/d/applebot"
    ),
    "Googlebot": BotDefinition(
        "Googlebot", "search_crawler", "Bot", "Google", documentation_url="https://bots.fyi/d/googlebot"
    ),
    "bingbot": BotDefinition(
        "Bingbot", "search_crawler", "Bot", "Microsoft", documentation_url="https://bots.fyi/d/bingbot"
    ),
    "Bingbot": BotDefinition(
        "Bingbot", "search_crawler", "Bot", "Microsoft", documentation_url="https://bots.fyi/d/bingbot"
    ),
    "YandexBot": BotDefinition(
        "Yandex", "search_crawler", "Bot", "Yandex", documentation_url="https://bots.fyi/d/yandexbot"
    ),
    "Baiduspider": BotDefinition(
        "Baidu", "search_crawler", "Bot", "Baidu", documentation_url="https://bots.fyi/d/baiduspider"
    ),
    "DuckDuckBot": BotDefinition(
        "DuckDuckGo", "search_crawler", "Bot", "DuckDuckGo", documentation_url="https://bots.fyi/d/duckduckbot"
    ),
    "Slurp": BotDefinition(
        "Yahoo", "search_crawler", "Bot", "Yahoo", documentation_url="https://bots.fyi/d/yahoo-slurp"
    ),
    "Yeti/": BotDefinition("Naver", "search_crawler", "Bot", "Naver", documentation_url="https://bots.fyi/d/naverbot"),
    "YisouSpider": BotDefinition(
        "Yisou", "search_crawler", "Bot", "Yisou", documentation_url="https://bots.fyi/d/yisouspider"
    ),
    "Sogou web spider": BotDefinition("Sogou", "search_crawler", "Bot", "Sogou"),
    "pageburst": BotDefinition("Pageburst", "search_crawler", "Bot", "Pageburst"),
    "360Spider": BotDefinition("360 Spider", "search_crawler", "Bot", "Qihoo 360"),
    "Qwantbot": BotDefinition(
        "Qwant", "search_crawler", "Bot", "Qwant", documentation_url="https://bots.fyi/d/qwantbot"
    ),
    "YouBot": BotDefinition(
        "You.com", "search_crawler", "Bot", "You.com", documentation_url="https://bots.fyi/d/youbot"
    ),
    "DataForSeoBot": BotDefinition(
        "DataForSeo", "search_crawler", "Bot", "DataForSeo", documentation_url="https://dataforseo.com/dataforseo-bot"
    ),
    "AwarioBot": BotDefinition(
        "Awario", "search_crawler", "Bot", "Awario", documentation_url="https://awario.com/bots.html"
    ),
    "ArchiveTeam ArchiveBot": BotDefinition(
        "ArchiveTeam ArchiveBot",
        "search_crawler",
        "Bot",
        "ArchiveTeam",
        documentation_url="https://www.archiveteam.org/",
    ),
    # Search Crawlers (Google variants)
    "AdsBot-Google": BotDefinition(
        "Google Ads", "search_crawler", "Bot", "Google", documentation_url="https://bots.fyi/d/google-adsbot"
    ),
    "Google-InspectionTool": BotDefinition(
        "Google Inspection",
        "search_crawler",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/google-inspectiontool",
    ),
    "Google-Food": BotDefinition("Google Food", "search_crawler", "Bot", "Google"),
    "Google-Adwords": BotDefinition("Google Adwords", "search_crawler", "Bot", "Google"),
    # SEO Tools
    "AhrefsSiteAudit": BotDefinition(
        "Ahrefs Site Audit", "seo_crawler", "Bot", "Ahrefs", documentation_url="https://bots.fyi/d/ahrefssiteaudit"
    ),
    "AhrefsBot": BotDefinition(
        "Ahrefs", "seo_crawler", "Bot", "Ahrefs", documentation_url="https://bots.fyi/d/ahrefsbot"
    ),
    "Barkrowler": BotDefinition(
        "Barkrowler", "seo_crawler", "Bot", "Babbar", documentation_url="https://bots.fyi/d/barkrowler"
    ),
    "SemrushBot": BotDefinition(
        "Semrush", "seo_crawler", "Bot", "Semrush", documentation_url="https://bots.fyi/d/semrush"
    ),
    "SERankingBacklinksBot": BotDefinition(
        "SE Ranking",
        "seo_crawler",
        "Bot",
        "SE Ranking",
        documentation_url="https://bots.fyi/d/seranking-backlinks",
    ),
    "MJ12bot": BotDefinition(
        "Majestic", "seo_crawler", "Bot", "Majestic", documentation_url="https://bots.fyi/d/mj12bot"
    ),
    "DotBot": BotDefinition("Moz", "seo_crawler", "Bot", "Moz", documentation_url="https://bots.fyi/d/dotbot"),
    "Lighthouse": BotDefinition(
        "Lighthouse", "seo_crawler", "Bot", "Google", documentation_url="https://bots.fyi/d/chrome-lighthouse"
    ),
    "MeltwaterNews": BotDefinition("Meltwater", "seo_crawler", "Bot", "Meltwater"),
    "SiteAuditBot": BotDefinition(
        "Semrush Site Audit",
        "seo_crawler",
        "Bot",
        "Semrush",
        documentation_url="https://bots.fyi/d/semrush-siteaudit",
    ),
    "Screaming Frog SEO Spider": BotDefinition(
        "Screaming Frog", "seo_crawler", "Bot", "Screaming Frog", documentation_url="https://www.screamingfrog.co.uk/"
    ),
    "PTST": BotDefinition(
        "WebPageTest", "seo_crawler", "Bot", "Catchpoint", documentation_url="https://www.webpagetest.org/"
    ),
    # Social Crawlers
    "FacebookBot": BotDefinition(
        "Facebook Bot",
        "social_crawler",
        "Bot",
        "Meta",
        documentation_url="https://bots.fyi/d/facebookexternalhit",
    ),
    "facebookexternalhit": BotDefinition(
        "Facebook", "social_crawler", "Bot", "Meta", documentation_url="https://bots.fyi/d/facebookexternalhit"
    ),
    "Twitterbot": BotDefinition(
        "Twitter", "social_crawler", "Bot", "X", documentation_url="https://bots.fyi/d/twitterbot"
    ),
    "LinkedInBot": BotDefinition(
        "LinkedIn", "social_crawler", "Bot", "LinkedIn", documentation_url="https://bots.fyi/d/linkedinbot"
    ),
    "Pinterest": BotDefinition(
        "Pinterest", "social_crawler", "Bot", "Pinterest", documentation_url="https://bots.fyi/d/pinterest-bot"
    ),
    "Slackbot": BotDefinition(
        "Slack", "social_crawler", "Bot", "Salesforce", documentation_url="https://bots.fyi/d/slackbot"
    ),
    "Slack-ImgProxy": BotDefinition(
        "Slack Image Proxy",
        "social_crawler",
        "Bot",
        "Salesforce",
        documentation_url="https://bots.fyi/d/slack-imgproxy",
    ),
    "TelegramBot": BotDefinition(
        "Telegram",
        "social_crawler",
        "Bot",
        "Telegram",
        documentation_url="https://core.telegram.org/bots",
    ),
    "WhatsApp": BotDefinition(
        "WhatsApp",
        "social_crawler",
        "Bot",
        "Meta",
        documentation_url="https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
    ),
    "GoogleImageProxy": BotDefinition(
        "Google Image Proxy",
        "social_crawler",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/google-image-proxy",
    ),
    "Iframely": BotDefinition(
        "Iframely", "social_crawler", "Bot", "Iframely", documentation_url="https://bots.fyi/d/iframely"
    ),
    "SkypeUriPreview": BotDefinition(
        "Skype Preview", "social_crawler", "Bot", "Microsoft", documentation_url="https://bots.fyi/d/skypeuripreview"
    ),
    # Monitoring
    "Pingdom": BotDefinition(
        "Pingdom", "monitoring", "Bot", "SolarWinds", documentation_url="https://bots.fyi/d/pingdom-bot"
    ),
    "UptimeRobot": BotDefinition(
        "UptimeRobot", "monitoring", "Bot", "UptimeRobot", documentation_url="https://bots.fyi/d/uptime-robot"
    ),
    "Site24x7": BotDefinition("Site24x7", "monitoring", "Bot", "Zoho", documentation_url="https://bots.fyi/d/site24x7"),
    "StatusCake": BotDefinition(
        "StatusCake",
        "monitoring",
        "Bot",
        "StatusCake",
        documentation_url="https://bots.fyi/d/statuscake-uptime",
    ),
    "Google-Ads-Conversions": BotDefinition(
        "Google Ads Conversions",
        "monitoring",
        "Bot",
        "Google",
        documentation_url="https://support.google.com/google-ads/answer/6095821",
    ),
    "Datadog": BotDefinition(
        "Datadog",
        "monitoring",
        "Bot",
        "Datadog",
        documentation_url="https://bots.fyi/d/datadog-synthetic-monitoring-robot",
    ),
    "GrafanaSyntheticMonitoring": BotDefinition("Grafana Synthetic", "monitoring", "Bot", "Grafana Labs"),
    "DMBrowser": BotDefinition("Doctom Monitor", "monitoring", "Bot", "Doctom"),
    "DigitalOcean Uptime Probe": BotDefinition("DigitalOcean Uptime", "monitoring", "Bot", "DigitalOcean"),
    "HubSpot": BotDefinition(
        "HubSpot Crawler", "monitoring", "Bot", "HubSpot", documentation_url="https://www.hubspot.com/"
    ),
    # HTTP Clients
    "curl/": BotDefinition("curl", "http_client", "Automation", "curl", documentation_url="https://curl.se/"),
    "Wget": BotDefinition(
        "Wget", "http_client", "Automation", "GNU", documentation_url="https://www.gnu.org/software/wget/"
    ),
    "python-requests": BotDefinition(
        "Python Requests",
        "http_client",
        "Automation",
        "Python",
        documentation_url="https://requests.readthedocs.io/",
    ),
    "axios": BotDefinition("Axios", "http_client", "Automation", "axios", documentation_url="https://axios-http.com/"),
    "node-fetch": BotDefinition(
        "Node Fetch",
        "http_client",
        "Automation",
        "Node.js",
        documentation_url="https://github.com/node-fetch/node-fetch",
    ),
    "Go-http-client": BotDefinition(
        "Go HTTP", "http_client", "Automation", "Go", documentation_url="https://pkg.go.dev/net/http"
    ),
    "okhttp": BotDefinition(
        "OkHttp", "http_client", "Automation", "Square", documentation_url="https://square.github.io/okhttp/"
    ),
    "Apache-HttpClient": BotDefinition(
        "Apache HTTP",
        "http_client",
        "Automation",
        "Apache",
        documentation_url="https://hc.apache.org/httpcomponents-client-5.5.x/",
    ),
    "libwww-perl": BotDefinition(
        "LWP", "http_client", "Automation", "Perl", documentation_url="https://metacpan.org/pod/LWP"
    ),
    "Scrapy": BotDefinition("Scrapy", "http_client", "Automation", "Scrapy", documentation_url="https://scrapy.org/"),
    "httpx": BotDefinition(
        "httpx", "http_client", "Automation", "Python", documentation_url="https://www.python-httpx.org/"
    ),
    "Google-Apps-Script": BotDefinition(
        "Google Apps Script",
        "http_client",
        "Automation",
        "Google",
        documentation_url="https://developers.google.com/apps-script",
    ),
    # First-party vendor crawlers and verifiers
    "PlayStore-Google": BotDefinition("Google Play Store", "http_client", "Bot", "Google"),
    "Amazon CloudFront": BotDefinition("Amazon CloudFront", "http_client", "Bot", "Amazon"),
    "AmazonProductDiscovery": BotDefinition("Amazon Product Discovery", "http_client", "Bot", "Amazon"),
    "Google-BusinessLinkVerification": BotDefinition("Google Business Link", "http_client", "Bot", "Google"),
    "Storebot-Google": BotDefinition(
        "Google Storebot",
        "http_client",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/storebot-google",
    ),
    "Google-Read-Aloud": BotDefinition(
        "Google Read Aloud",
        "http_client",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/google-read-aloud",
    ),
    "Google-Appointments": BotDefinition("Google Appointments", "http_client", "Bot", "Google"),
    "Google-Actions": BotDefinition(
        "Google Actions",
        "http_client",
        "Bot",
        "Google",
        documentation_url="https://bots.fyi/d/google-actions",
    ),
    "OneTrust": BotDefinition("OneTrust", "http_client", "Bot", "OneTrust"),
    # Production-validated batch (prod-us 7d, $pageview, multi-source ranked by event count)
    "Checkly": BotDefinition("Checkly", "monitoring", "Bot", "Checkly"),
    "RuxitSynthetic": BotDefinition("dynatrace-monitor", "monitoring", "Bot", "Dynatrace"),
    "Google-AdWords-Express": BotDefinition("Google-AdWords-Express", "seo_crawler", "Bot", "Google"),
    "meta-externalads": BotDefinition("meta-externalads", "seo_crawler", "Bot", "Meta"),
    "Google-Safety": BotDefinition("Google-Safety", "monitoring", "Bot", "Google"),
    "GTmetrix": BotDefinition("GTmetrix", "monitoring", "Bot", "GTmetrix"),
    "TwilioKnowledge": BotDefinition("Twilio Knowledge", "ai_crawler", "AI Agent", "Twilio"),
    "Google-Agent": BotDefinition("Google-Agent", "ai_crawler", "AI Agent", "Google"),
    "Google-Structured-Data-Testing": BotDefinition("Google Schema Markup Testing Tool", "monitoring", "Bot", "Google"),
    "google-structured-data-testing-tool": BotDefinition(
        "google-structured-data-testing-tool", "search_crawler", "Bot", "Google"
    ),
    "adbeat": BotDefinition("Adbeat", "search_crawler", "Bot", "Adbeat"),
    "SEBot-WA": BotDefinition("SE Ranking Bot", "monitoring", "Bot", "SE Ranking"),
    "Ads-Naver": BotDefinition("adsnaver", "search_crawler", "Bot", "Naver"),
    "Better Uptime Bot": BotDefinition("Better Stack", "monitoring", "Bot", "BetterStack"),
    "woorankreview": BotDefinition("WooRank", "search_crawler", "Bot", "WooRank"),
    "Viber": BotDefinition("viber-crawler", "social_crawler", "Bot", "Rakuten"),
    "Taboolabot": BotDefinition("Taboola", "seo_crawler", "Bot", "Taboola"),
    "Archive-It": BotDefinition("Internet Archive - Archive-It", "search_crawler", "Bot", "Internet Archive"),
    "seo4ajax.com": BotDefinition("seo4ajax", "seo_crawler", "Bot", "Prerender.io"),
    "CookieHubScan": BotDefinition("cookiehub-scan", "http_client", "Automation", "CookieHub"),
    "BitSightBot": BotDefinition("BitSight", "monitoring", "Bot", "BitSight"),
    "ArchiveBox": BotDefinition("ArchiveBox", "search_crawler", "Bot", "ArchiveBox"),
    "Dataprovider": BotDefinition("Dataprovider.com", "search_crawler", "Bot", "Dataprovider"),
    "BingPreview": BotDefinition("Bing Preview", "social_crawler", "Bot", "Microsoft"),
    "Convertify": BotDefinition("Convertify", "http_client", "Automation", "Convertify"),
    "GoogleAgent-Mariner": BotDefinition("GoogleAgent-Mariner", "ai_crawler", "AI Agent", "Google"),
    "DareBoost": BotDefinition("dareboost-crawler", "seo_crawler", "Bot", "Dareboost"),
    "AccessibleWebBot": BotDefinition("Accessible Web Bot", "monitoring", "Bot", "AccessibleWebBot"),
    "Stripebot": BotDefinition("Stripebot", "monitoring", "Bot", "Stripe"),
    "Bluesky": BotDefinition("Bluesky", "social_crawler", "Bot", "Bluesky"),
    "TagInspector": BotDefinition("Tag Inspector", "search_crawler", "Bot", "Tag Inspector"),
    "oast": BotDefinition("Interactsh", "monitoring", "Bot", "ProjectDiscovery"),
    "CookieScript": BotDefinition("CookieScript", "monitoring", "Bot", "CookieScript"),
    "Mediapartners": BotDefinition("google-adsense-googlebot", "search_crawler", "Bot", "Google"),
    "OhDear": BotDefinition("OhDearBot", "monitoring", "Bot", "Oh Dear"),
    "Siteimprove": BotDefinition("Siteimprove", "search_crawler", "Bot", "Siteimprove"),
    "SnapchatAds": BotDefinition("SnapchatAdsBot", "seo_crawler", "Bot", "Snap"),
    "MarketGoo": BotDefinition("marketgoo", "seo_crawler", "Bot", "MarketGoo"),
    "oncrawl": BotDefinition("oncrawl", "seo_crawler", "Bot", "OnCrawl"),
    "kinsta-bot": BotDefinition("Kinsta", "monitoring", "Bot", "Kinsta"),
    "CensysInspect": BotDefinition("CensysInspectBot", "monitoring", "Bot", "Censys"),
    "SeznamBot": BotDefinition("SeznamBot", "search_crawler", "Bot", "Seznam"),
    "WPMU DEV": BotDefinition("WPMU DEV", "search_crawler", "Bot", "WPMU DEV"),
    "Google Web Preview": BotDefinition("google-preview", "search_crawler", "Bot", "Google"),
    "Catchpoint": BotDefinition("catchpoint", "monitoring", "Bot", "Catchpoint"),
    "Snap URL Preview Service": BotDefinition("SnapURLPreviewBot", "social_crawler", "Bot", "Snap"),
    "Blackboard": BotDefinition("blackboard-crawler", "search_crawler", "Bot", "Blackboard"),
    "Foregenix": BotDefinition("Foregenix ThreatView/WebScan", "monitoring", "Bot", "Foregenix"),
    "FirecrawlAgent": BotDefinition("FirecrawlAgent", "ai_crawler", "AI Agent", "Firecrawl"),
    "Seekport": BotDefinition("seekport-crawler", "search_crawler", "Bot", "Seekport"),
    "ev-crawler": BotDefinition("Headline", "search_crawler", "Bot", "Headline"),
    "bitdiscovery": BotDefinition("Tenable.asm", "monitoring", "Bot", "Tenable.asm"),
    "SecurityHeaders": BotDefinition("SecurityHeaders", "monitoring", "Bot", "Probely"),
    "vercel-screenshot": BotDefinition("Vercel Screenshot Bot", "social_crawler", "Bot", "Vercel"),
    "AppEngine-Google": BotDefinition("google-appengine", "search_crawler", "Bot", "Google"),
    "InternetMeasurement": BotDefinition("InternetMeasurementBot", "monitoring", "Bot", "DNS-OARC"),
    "GoogleDocs": BotDefinition("Google Docs", "http_client", "Automation", "Google"),
    "linkchecker.pro": BotDefinition("LinkChecker Bot", "seo_crawler", "Bot", "Webmasterworld"),
    "zgrab": BotDefinition("zgrab", "http_client", "Automation", "ZMap"),
    "amazon-QBusiness": BotDefinition("Amazon Q", "ai_crawler", "AI Agent", "Amazon"),
    "aiohttp": BotDefinition("python-aiohttp", "http_client", "Automation", "Python"),
    "WellKnownBot": BotDefinition("wellknown-crawler", "search_crawler", "Bot", "Wellknown-crawler"),
    "OKX-dolphin-crawler": BotDefinition("OKX-dolphin-crawler", "monitoring", "Bot", "OKX"),
    "BrightEdge Crawler": BotDefinition("BrightEdge Bot", "seo_crawler", "Bot", "BrightEdge"),
    "Asana": BotDefinition("Asana", "search_crawler", "Bot", "Asana"),
    "Google-PageRenderer": BotDefinition("Google PageRenderer", "social_crawler", "Bot", "Google"),
    "charlotte": BotDefinition("Charlotte", "search_crawler", "Bot", "Salesforce"),
    "AmazonSellerInitiatedListing": BotDefinition(
        "Amazon Seller Initiated Listing", "http_client", "Automation", "Amazon"
    ),
    # Production-validated batch (prod-eu 7d, $pageview, patterns unique to EU traffic)
    "Splunk Synthetics": BotDefinition("Splunk Synthetics", "monitoring", "Bot", "Splunk"),
    "Detectify": BotDefinition("Detectify", "monitoring", "Bot", "Detectify"),
    "Ghost Inspector": BotDefinition("Ghost Inspector", "monitoring", "Bot", "Ghost Inspector"),
    "Monsidobot": BotDefinition("Monsido", "monitoring", "Bot", "Monsido"),
    "SearchAtlas Bot": BotDefinition("SearchAtlas", "seo_crawler", "Bot", "SearchAtlas"),
    "VelenPublicWebCrawler": BotDefinition("Velen", "ai_crawler", "AI Agent", "Velen"),
    "Cookiebot": BotDefinition("Cookiebot", "monitoring", "Bot", "Cookiebot"),
    "nmap": BotDefinition("nmap", "http_client", "Automation", "Nmap"),
    "MicrosoftPreview": BotDefinition("Microsoft Preview", "social_crawler", "Bot", "Microsoft"),
    # Prefetch/Proxy
    "Chrome Privacy Preserving Prefetch Proxy": BotDefinition(
        "Chrome Prefetch Proxy",
        "http_client",
        "Automation",
        "Google",
        documentation_url="https://bots.fyi/d/chrome-privacy-preserving-prefetch-proxy",
    ),
    # Headless Browsers
    "Mozlila/": BotDefinition("Mozlila Typo Bot", "headless_browser", "Automation", "Unknown"),
    # Real Chrome always emits "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/..."; a platform
    # paren followed directly by Chrome (no KHTML clause) only occurs in hand-built UAs from
    # scraper/stealth-automation fleets (observed cross-team at ~30x the human events-per-IP).
    "\\) AppleWebKit/537\\.36 Chrome/": BotDefinition(
        "Malformed Chrome UA", "headless_browser", "Automation", "Unknown"
    ),
    "HeadlessChrome": BotDefinition(
        "Headless Chrome",
        "headless_browser",
        "Automation",
        "Google",
        documentation_url="https://developer.chrome.com/blog/headless-chrome",
    ),
    "PhantomJS": BotDefinition(
        "PhantomJS",
        "headless_browser",
        "Automation",
        "PhantomJS",
        documentation_url="https://phantomjs.org/",
    ),
    "Puppeteer": BotDefinition(
        "Puppeteer", "headless_browser", "Automation", "Google", documentation_url="https://pptr.dev/"
    ),
    "Playwright": BotDefinition(
        "Playwright",
        "headless_browser",
        "Automation",
        "Microsoft",
        documentation_url="https://playwright.dev/",
    ),
    "Selenium": BotDefinition(
        "Selenium",
        "headless_browser",
        "Automation",
        "Selenium",
        documentation_url="https://www.selenium.dev/",
    ),
    # Server-side batch (prod $http_log Vercel log drain, 7d, self-declared crawlers/monitors
    # absent from the JS-pageview stream). Each key is anchored on the operator's own declared
    # token, never a pattern that could match a real browser.
    # Search / index crawlers
    "ClueWeb-Crawler": BotDefinition("ClueWeb", "search_crawler", "Bot", "Carnegie Mellon University"),
    "mwmbl": BotDefinition("Mwmbl", "search_crawler", "Bot", "Mwmbl", documentation_url="https://mwmbl.org/"),
    "MojeekBot": BotDefinition(
        "Mojeek", "search_crawler", "Bot", "Mojeek", documentation_url="https://www.mojeek.com/bot.html"
    ),
    "meta-webindexer": BotDefinition("Meta Web Indexer", "search_crawler", "Bot", "Meta"),
    r"archive\.org_bot": BotDefinition(
        "Internet Archive", "search_crawler", "Bot", "Internet Archive", documentation_url="https://archive.org/"
    ),
    "jobcrawler": BotDefinition("jobcrawler", "search_crawler", "Bot", "Unknown"),
    "url-crawler": BotDefinition("url-crawler", "search_crawler", "Bot", "Unknown"),
    "FlamingoBot": BotDefinition("FlamingoBot", "search_crawler", "Bot", "hackernews.pink"),
    # Archival / research crawlers
    "heritrix": BotDefinition(
        "Heritrix",
        "search_crawler",
        "Bot",
        "image-meta.com",
        documentation_url="https://github.com/internetarchive/heritrix3",
    ),
    "crawlcrawl-actors": BotDefinition("crawlcrawl", "search_crawler", "Bot", "Unknown"),
    "crawler_eb_germany": BotDefinition("crawler_eb_germany", "search_crawler", "Bot", "Unknown"),
    # AI / agent crawlers
    "Inkeep-Crawler": BotDefinition(
        "Inkeep", "ai_crawler", "AI Agent", "Inkeep", documentation_url="https://inkeep.com/"
    ),
    "KhojifyBot": BotDefinition("Khojify", "ai_crawler", "AI Agent", "Khojify"),
    "AzureAI-SearchBot": BotDefinition("Azure AI Search", "ai_crawler", "AI Agent", "Microsoft"),
    "GrowthXBot": BotDefinition("GrowthX", "ai_crawler", "AI Agent", "GrowthX"),
    "RegieBrainBot": BotDefinition(
        "Regie.ai", "ai_crawler", "AI Agent", "Regie.ai", documentation_url="https://www.regie.ai/"
    ),
    "IntelvaneBot": BotDefinition("Intelvane", "ai_crawler", "AI Agent", "Intelvane"),
    "ModelContextProtocol": BotDefinition(
        "Model Context Protocol",
        "ai_crawler",
        "AI Agent",
        "Unknown",
        documentation_url="https://modelcontextprotocol.io/",
    ),
    "Amazon-Bedrock-AgentCore-Browser": BotDefinition(
        "Amazon Bedrock AgentCore",
        "ai_crawler",
        "AI Agent",
        "Amazon",
        documentation_url="https://aws.amazon.com/bedrock/agentcore/",
    ),
    "ResearchBot": BotDefinition("ResearchBot", "ai_crawler", "AI Agent", "Unknown"),
    "ShapBot": BotDefinition("Shap", "ai_crawler", "AI Agent", "Shap"),
    "ABEvalBot": BotDefinition("ABEvalBot", "ai_crawler", "AI Agent", "Unknown"),
    "OzDocsCrawler": BotDefinition("OzDocs", "ai_crawler", "AI Agent", "Unknown"),
    "polygazer": BotDefinition("polygazer", "ai_crawler", "AI Agent", "Unknown"),
    "BIC-Probe": BotDefinition("BIC Probe", "ai_crawler", "AI Agent", "pracharvedam.ai"),
    "AIWebIndex": BotDefinition(
        "AIWebIndex", "ai_crawler", "AI Agent", "Lyrenth", documentation_url="https://lyrenth.com/bot"
    ),
    # SEO / marketing crawlers
    "MBCrawler": BotDefinition(
        "Monitor Backlinks",
        "seo_crawler",
        "Bot",
        "Monitor Backlinks",
        documentation_url="https://monitorbacklinks.com/",
    ),
    "AffsignalCrawler": BotDefinition("Affsignal", "seo_crawler", "Bot", "Affsignal"),
    "RankyDockyBot": BotDefinition("RankyDocky", "seo_crawler", "Bot", "RankyDocky"),
    "pricingbrief-bot": BotDefinition("PricingBrief", "seo_crawler", "Bot", "PricingBrief"),
    "SolvedEarthPriceBot": BotDefinition(
        "SolvedEarth Price Bot", "seo_crawler", "Bot", "SolvedEarth", documentation_url="https://solved.earth"
    ),
    "SiteavailObservatory": BotDefinition("Siteavail", "seo_crawler", "Bot", "Siteavail"),
    "appzbot": BotDefinition("appzbot", "seo_crawler", "Bot", "Unknown"),
    "Optimize Pilot Research Bot": BotDefinition("Optimize Pilot", "seo_crawler", "Bot", "Optimize Pilot"),
    # Uptime / monitors
    "KalleWorks-Monitor": BotDefinition("KalleWorks", "monitoring", "Bot", "KalleWorks"),
    "LosClouds-Monitor": BotDefinition("LosClouds", "monitoring", "Bot", "LosClouds"),
    "Exit1-Website-Monitor": BotDefinition(
        "Exit1", "monitoring", "Bot", "Exit1", documentation_url="https://exit1.dev/"
    ),
    "UptimeWizardBot": BotDefinition("UptimeWizard", "monitoring", "Bot", "UptimeWizard"),
    "PreflightBot": BotDefinition("Preflight", "monitoring", "Bot", "Preflight"),
    # Security scanner
    "MerchantSecurityScanner": BotDefinition(
        "Stripe Merchant Security Scanner", "monitoring", "Bot", "Stripe", documentation_url="https://stripe.com/"
    ),
    # Social crawler (well-known bot not yet vendored here)
    "Discordbot": BotDefinition(
        "Discord", "social_crawler", "Bot", "Discord", documentation_url="https://discord.com/"
    ),
    # Self-declared crawlers observed in production `$http_log` traffic
    # AI crawlers
    "VioscaleAIBot": BotDefinition(
        "Vioscale AI", "ai_crawler", "AI Agent", "Vioscale", documentation_url="https://www.vioscale.ai/method"
    ),
    "Amzn-SearchBot": BotDefinition(
        "Amazon Search",
        "ai_crawler",
        "AI Agent",
        "Amazon",
        documentation_url="https://developer.amazon.com/support/amazonbot",
    ),
    "LeapwaveVIP": BotDefinition(
        "Leapwave", "ai_crawler", "AI Agent", "Leapwave", documentation_url="https://leapwave.ai"
    ),
    "docs-puller": BotDefinition(
        "docs-puller",
        "ai_crawler",
        "AI Agent",
        "docs-puller",
        documentation_url="https://github.com/nstranquist/docs-puller",
    ),
    "ToolchestBot": BotDefinition(
        "Toolchest", "ai_crawler", "AI Agent", "Toolchest AI", documentation_url="https://toolchest.ai"
    ),
    "scopy-docs-crawler": BotDefinition(
        "scopy docs crawler", "ai_crawler", "AI Agent", "scopy", documentation_url="https://scopy.dev"
    ),
    "llms-txt-sync": BotDefinition("llms-txt-sync", "ai_crawler", "AI Agent", "llms-txt-sync"),
    "PromptingBot": BotDefinition("PromptingBot", "ai_crawler", "AI Agent", "PromptingBot"),
    "llm-code-docs-scraper": BotDefinition("LLM code docs scraper", "ai_crawler", "AI Agent", "llm-code-docs-scraper"),
    "whichapi-bot": BotDefinition(
        "WhichAPI", "ai_crawler", "AI Agent", "WhichAPI", documentation_url="https://whichapi.ai/bot"
    ),
    "Codex-YCB2B": BotDefinition("Codex public research", "ai_crawler", "AI Agent", "OpenAI"),
    "PostHog-BusinessKnowledge": BotDefinition(
        "PostHog BusinessKnowledge", "ai_crawler", "AI Agent", "PostHog", documentation_url="https://posthog.com"
    ),
    "LlmsTxtBot": BotDefinition(
        "LlmsTxtBot",
        "ai_crawler",
        "AI Agent",
        "llms-txt",
        documentation_url="https://github.com/tristansinclair/llms-txt-tristan-sinclair",
    ),
    "every-api/": BotDefinition(
        "Every API", "ai_crawler", "AI Agent", "every-api", documentation_url="https://github.com/MEMEO-PRO/every-api"
    ),
    "RightAIChoiceBot": BotDefinition(
        "Right AI Choice", "ai_crawler", "AI Agent", "Right AI Choice", documentation_url="https://rightaichoice.com"
    ),
    # Search / index crawlers
    "redCactiBot": BotDefinition(
        "redCactiBot", "search_crawler", "Bot", "redCacti", documentation_url="https://redcacti.com/bot"
    ),
    "BelleaireCrawler": BotDefinition(
        "BelleaireCrawler", "search_crawler", "Bot", "Belleaire", documentation_url="https://belleaire.xyz/bot"
    ),
    "PersimmonDesignResearch": BotDefinition(
        "Persimmon Design Research",
        "search_crawler",
        "Bot",
        "Persimmon Software",
        documentation_url="https://persimmonsoftware.com",
    ),
    "barkReleasesBot": BotDefinition(
        "barkReleasesBot", "search_crawler", "Bot", "bark", documentation_url="https://github.com/JanV81/bark"
    ),
    "prospector/": BotDefinition(
        "Prospector", "search_crawler", "Bot", "Rebase", documentation_url="https://prospector.rebase.website"
    ),
    "YandexRenderResourcesBot": BotDefinition(
        "Yandex Render Resources", "search_crawler", "Bot", "Yandex", documentation_url="http://yandex.com/bots"
    ),
    "YandexAccessibilityBot": BotDefinition(
        "Yandex Accessibility", "search_crawler", "Bot", "Yandex", documentation_url="http://yandex.com/bots"
    ),
    "rewebbot": BotDefinition("rewebbot", "search_crawler", "Bot", "reweb", documentation_url="https://reweb.so/bot"),
    "Querit-SearchBot": BotDefinition(
        "Querit Search", "search_crawler", "Bot", "Querit", documentation_url="https://www.querit.ai"
    ),
    "ImpactVibeDesignResearch": BotDefinition(
        "ImpactVibe Design Research",
        "search_crawler",
        "Bot",
        "ImpactVibe",
        documentation_url="https://opencode.jwdev.us",
    ),
    "crawl-engine": BotDefinition(
        "crawl-engine", "search_crawler", "Bot", "Creasource", documentation_url="https://abuse.creasource.dev/"
    ),
    "CompanyFeedServer": BotDefinition(
        "CompanyFeedServer",
        "search_crawler",
        "Bot",
        "company-feed-server",
        documentation_url="https://github.com/Shuozeli/company-feed-server",
    ),
    "BranchenbuchBot": BotDefinition(
        "BranchenbuchBot", "search_crawler", "Bot", "Branchenbuch", documentation_url="https://branchenbuch.ag/bot"
    ),
    "ReachBot": BotDefinition("ReachBot", "search_crawler", "Bot", "ReachBot"),
    "IbouBot": BotDefinition("IbouBot", "search_crawler", "Bot", "IbouBot"),
    "Hypeline": BotDefinition("Hypeline", "search_crawler", "Bot", "Hypeline"),
    "OldSchoolBot": BotDefinition("OldSchoolBot", "search_crawler", "Bot", "OldSchoolBot"),
    "TutusooBot": BotDefinition("TutusooBot", "search_crawler", "Bot", "Tutusoo"),
    "HiringRadarBot": BotDefinition("HiringRadar", "search_crawler", "Bot", "HiringRadar"),
    "slopsearch-linux-crawler": BotDefinition("slopsearch", "search_crawler", "Bot", "slopsearch"),
    "ForgeYourPathAiJobCrawler": BotDefinition("ForgeYourPath Job Crawler", "search_crawler", "Bot", "ForgeYourPath"),
    "OkaraBot": BotDefinition("OkaraBot", "search_crawler", "Bot", "OkaraBot"),
    "DesignMD-Extract-Bot": BotDefinition("DesignMD Extract", "search_crawler", "Bot", "DesignMD"),
    "LyonlBot": BotDefinition("LyonlBot", "search_crawler", "Bot", "LyonlBot"),
    "Sokjan Crawler": BotDefinition("Sokjan Crawler", "search_crawler", "Bot", "Sokjan"),
    "ScryBot": BotDefinition("ScryBot", "search_crawler", "Bot", "ScryBot"),
    "Heexybot": BotDefinition("Heexybot", "search_crawler", "Bot", "Heexy", documentation_url="https://heexy.org/bot"),
    "bne\\.es_bot": BotDefinition(
        "Biblioteca Nacional de España",
        "search_crawler",
        "Bot",
        "Biblioteca Nacional de España",
        documentation_url="https://www.bne.es/es/colecciones/archivo-web-espanola/aviso-webmasters",
    ),
    "Zetlyn": BotDefinition("Zetlyn", "search_crawler", "Bot", "Zetlyn", documentation_url="https://zetlyn.com"),
    "algorand-platform-newspaper": BotDefinition(
        "Algorand platform newspaper",
        "search_crawler",
        "Bot",
        "algorand.pxke.me",
        documentation_url="https://algorand.pxke.me",
    ),
    "VendiditBot": BotDefinition(
        "Vendidit", "search_crawler", "Bot", "Vendidit", documentation_url="https://vendidit.com/bot"
    ),
    "Zee Company Intelligence": BotDefinition(
        "Zee Company Intelligence", "search_crawler", "Bot", "Lazyweb", documentation_url="https://www.lazyweb.com"
    ),
    "NicheStuffBot": BotDefinition(
        "NicheStuff", "search_crawler", "Bot", "NicheStuff", documentation_url="https://nichestuff.net"
    ),
    "Axiom-DocBot": BotDefinition(
        "Axiom DocBot", "search_crawler", "Bot", "Axiom", documentation_url="https://github.com/iadnanahsan/axiom"
    ),
    "RealPressBot": BotDefinition(
        "RealPressBot", "search_crawler", "Bot", "real.press", documentation_url="https://real.press/bot"
    ),
    "StraddleLibraryBot": BotDefinition("Straddle Library", "search_crawler", "Bot", "Straddle"),
    "LurantaBot": BotDefinition(
        "Luranta", "search_crawler", "Bot", "Luranta", documentation_url="https://luranta.com/crawler"
    ),
    "UnstenciledBot": BotDefinition(
        "Unstenciled", "search_crawler", "Bot", "Unstenciled", documentation_url="https://unstenciled.com/bot"
    ),
    "InloraBot": BotDefinition("Inlora", "search_crawler", "Bot", "Inlora", documentation_url="https://inlora.eu/bot"),
    "EfficientRustCrawler": BotDefinition(
        "Efficient Rust Crawler", "search_crawler", "Bot", "Xape", documentation_url="https://xape.eu/"
    ),
    "DatalenkCreatorResearch": BotDefinition(
        "Datalenk Creator Research", "search_crawler", "Bot", "Datalenk", documentation_url="https://datalenk.com"
    ),
    "Wrzutka-Bot": BotDefinition(
        "Wrzutka", "search_crawler", "Bot", "Wrzutka", documentation_url="https://wrzutka.com/bot"
    ),
    "Polon/": BotDefinition("Polon", "search_crawler", "Bot", "Polon"),
    "Babel42Bot": BotDefinition(
        "Babel42", "search_crawler", "Bot", "Babel42", documentation_url="https://babel42.io/bot"
    ),
    "jscrawler": BotDefinition("jscrawler", "search_crawler", "Bot", "jscrawler"),
    "PolycoreSupabaseDetector": BotDefinition(
        "Polycore Supabase Detector", "search_crawler", "Bot", "Polycore", documentation_url="https://www.polycore.ai/"
    ),
    "UnboundCompute-PublicSnapshot": BotDefinition(
        "UnboundCompute Public Snapshot",
        "search_crawler",
        "Bot",
        "UnboundCompute",
        documentation_url="https://unboundcompute.com/",
    ),
    "swissAItalentBot": BotDefinition(
        "swissAItalentBot",
        "search_crawler",
        "Bot",
        "swissaitalent.ch",
        documentation_url="https://swissaitalent.ch/bot",
    ),
    # SEO / marketing crawlers
    "LaunchReadyCodeBot": BotDefinition(
        "LaunchReadyCodeBot",
        "seo_crawler",
        "Bot",
        "LaunchReadyCode",
        documentation_url="https://launchreadycode.com/bot",
    ),
    "PricingArchiveBot": BotDefinition(
        "PricingArchiveBot",
        "seo_crawler",
        "Bot",
        "pricing-archive",
        documentation_url="https://github.com/colesharpton2024/pricing-archive",
    ),
    "SEOMasterBot": BotDefinition(
        "SEOMasterBot", "seo_crawler", "Bot", "SEOMaster", documentation_url="https://seomaster.live"
    ),
    "CanICancelIt-LinkCheck": BotDefinition(
        "CanICancelIt LinkCheck",
        "seo_crawler",
        "Bot",
        "CanICancelIt",
        documentation_url="https://canicancelit.com/methodology",
    ),
    "serpstatbot": BotDefinition(
        "Serpstat", "seo_crawler", "Bot", "Serpstat", documentation_url="https://serpstatbot.com/"
    ),
    "StackPick": BotDefinition("StackPick", "seo_crawler", "Bot", "StackPick"),
    "UXXRAYBot": BotDefinition("UXXRAY", "seo_crawler", "Bot", "UXXRAY", documentation_url="https://uxxray.com/bot"),
    "NoFluffGraderBot": BotDefinition(
        "NoFluff Grader",
        "seo_crawler",
        "Bot",
        "NoFluff Marketing",
        documentation_url="https://nofluffmktg.com/ai-grader",
    ),
    "PagePilot-SiteAudit": BotDefinition(
        "PagePilot Site Audit",
        "seo_crawler",
        "Bot",
        "PagePilot",
        documentation_url="https://pagepilot-ai-24.polsia.app",
    ),
    "double-ats-customer-discoverer": BotDefinition(
        "Double ATS Customer Discoverer", "seo_crawler", "Bot", "Double", documentation_url="https://double.fyi"
    ),
    "BenchRankBot": BotDefinition(
        "BenchRank", "seo_crawler", "Bot", "BenchRank", documentation_url="https://benchrank.app/bot"
    ),
    # Social / link-preview crawlers
    "PagePeeker": BotDefinition(
        "PagePeeker", "social_crawler", "Bot", "PagePeeker", documentation_url="https://pagepeeker.com/robots/"
    ),
    "Synapse \\(bot": BotDefinition(
        "Synapse", "social_crawler", "Bot", "Matrix.org", documentation_url="https://github.com/matrix-org/synapse"
    ),
    "Unfurlist": BotDefinition(
        "Unfurlist", "social_crawler", "Bot", "Doist", documentation_url="https://github.com/Doist/unfurlist"
    ),
    # Uptime / monitors / probes
    "heap\\.page source monitor": BotDefinition(
        "heap.page", "monitoring", "Bot", "heap.page", documentation_url="https://heap.page/methodology"
    ),
    "PulseWatch-Prober": BotDefinition("PulseWatch", "monitoring", "Bot", "PulseWatch"),
    "Scryer/": BotDefinition(
        "Scryer", "monitoring", "Bot", "Scryer", documentation_url="https://scryer.network/scanning"
    ),
    "UnusualAgentAudit": BotDefinition(
        "UnusualAgentAudit", "monitoring", "Bot", "unusual.ai", documentation_url="https://unusual.ai/agent-audit"
    ),
    "VersionWatchBot": BotDefinition("VersionWatch", "monitoring", "Bot", "VersionWatch"),
    "a14y/": BotDefinition(
        "a14y", "monitoring", "Bot", "a14y", documentation_url="https://github.com/timothyjordan/a14y"
    ),
    "UptimeLensBot": BotDefinition(
        "UptimeLens", "monitoring", "Bot", "UptimeLens", documentation_url="http://www.uptimelens.com/"
    ),
    "InterruptIndexBot": BotDefinition(
        "InterruptIndex", "monitoring", "Bot", "InterruptIndex", documentation_url="https://interruptindex.com/opt-out"
    ),
    "CurbCutScanner": BotDefinition(
        "CurbCut Scanner", "monitoring", "Bot", "CurbCut", documentation_url="https://github.com/devinxu0916/CurbCut"
    ),
    "VantageBot": BotDefinition(
        "VantageBot",
        "monitoring",
        "Bot",
        "webapp-monitor",
        documentation_url="https://github.com/morsela/webapp-monitor",
    ),
    "NimbusBlocklistSync": BotDefinition(
        "Nimbus Blocklist Sync", "monitoring", "Bot", "Nimbus", documentation_url="https://nimbus.com"
    ),
    # HTTP clients
    "MrAnandPortfolio": BotDefinition(
        "MrAnandPortfolio", "http_client", "Bot", "mranand.com", documentation_url="https://mranand.com"
    ),
}
