"""Static catalog of the demo marketing world.

Every campaign and channel here exists to exercise a specific dashboard or
Integration health state; the `scenario` field documents which one.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DemoAd:
    ad_id: str
    name: str


@dataclass(frozen=True)
class DemoAdGroup:
    ad_group_id: str
    name: str
    ads: tuple[DemoAd, ...]


@dataclass(frozen=True)
class DemoCampaign:
    platform: str  # ExternalDataSource.source_type, e.g. "GoogleAds"
    campaign_id: str
    name: str
    daily_cost: float
    daily_impressions: int
    daily_clicks: int
    daily_sessions: int  # $pageviews generated per day; 0 => no traffic (not_linked)
    utm_source: str | None
    utm_campaign: str | None  # value events carry; None => use name.lower()
    utm_medium: str = "cpc"
    referring_domain: str = ""
    click_id_property: str | None = None  # $gclid / $fbclid
    signup_rate: float = 0.0
    purchase_rate: float = 0.0
    reported_conversion_rate: float = 0.02  # of clicks
    reported_value_per_conversion: float = 90.0
    utm_source_variants: dict[str, float] = field(default_factory=dict)  # variant -> share
    utm_campaign_variants: dict[str, float] = field(default_factory=dict)
    ad_groups: tuple[DemoAdGroup, ...] = ()
    scenario: str = ""


@dataclass(frozen=True)
class DemoFreeChannel:
    key: str
    daily_sessions: int
    referring_domain: str
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    signup_rate: float = 0.03
    purchase_rate: float = 0.008
    utm_source_variants: dict[str, float] = field(default_factory=dict)
    scenario: str = ""


def _google_hierarchy() -> tuple[DemoAdGroup, ...]:
    return (
        DemoAdGroup(
            "20001",
            "brand-exact",
            (DemoAd("30001", "hero_v1"), DemoAd("30002", "hero_v2")),
        ),
        DemoAdGroup(
            "20002",
            "brand-broad",
            (DemoAd("30003", "lifestyle"), DemoAd("30004", "testimonial")),
        ),
    )


CAMPAIGNS: tuple[DemoCampaign, ...] = (
    # --- Google Ads (source healthy, full campaign > ad group > ad hierarchy) ---
    DemoCampaign(
        platform="GoogleAds",
        campaign_id="10001",
        name="brand_search",
        daily_cost=120.0,
        daily_impressions=2600,
        daily_clicks=140,
        daily_sessions=60,
        utm_source="google",
        utm_campaign="brand_search",
        referring_domain="google.com",
        click_id_property="$gclid",
        signup_rate=0.12,
        purchase_rate=0.035,
        reported_conversion_rate=0.05,
        reported_value_per_conversion=140.0,
        # ~10% of clicks arrive with a capitalized source: demonstrates the
        # case-sensitive source split on the conversions side.
        utm_source_variants={"Google": 0.1},
        ad_groups=_google_hierarchy(),
        scenario="healthy hero campaign, good ROAS, drill-down to ad level",
    ),
    DemoCampaign(
        platform="GoogleAds",
        campaign_id="10002",
        name="generic_search",
        daily_cost=260.0,
        daily_impressions=6100,
        daily_clicks=210,
        daily_sessions=45,
        utm_source="google",
        utm_campaign="generic_search",
        referring_domain="google.com",
        click_id_property="$gclid",
        signup_rate=0.015,
        purchase_rate=0.002,
        reported_conversion_rate=0.01,
        reported_value_per_conversion=45.0,
        ad_groups=(
            DemoAdGroup("20003", "generic-broad", (DemoAd("30005", "explainer_30s"), DemoAd("30006", "pricing_card"))),
        ),
        scenario="high spend, ROAS < 1 (wasted-spend story)",
    ),
    DemoCampaign(
        platform="GoogleAds",
        campaign_id="10003",
        name="summer_promo_2026",
        daily_cost=45.0,
        daily_impressions=1900,
        daily_clicks=70,
        daily_sessions=0,
        utm_source=None,
        utm_campaign=None,
        scenario="spend but zero tagged pageviews -> UTM audit NOT_LINKED",
    ),
    DemoCampaign(
        platform="GoogleAds",
        campaign_id="10004",
        name="Spring Sale 2026",
        daily_cost=85.0,
        daily_impressions=2100,
        daily_clicks=95,
        daily_sessions=35,
        utm_source="google",
        utm_campaign="spring_sale_2026",
        referring_domain="google.com",
        click_id_property="$gclid",
        signup_rate=0.08,
        purchase_rate=0.02,
        utm_campaign_variants={"spring-sale-2026": 0.4},
        scenario="dirty utm_campaign variants resolved via campaign_name_mappings",
    ),
    DemoCampaign(
        platform="GoogleAds",
        campaign_id="10005",
        name="mixed_promo",
        daily_cost=55.0,
        daily_impressions=1500,
        daily_clicks=60,
        daily_sessions=25,
        utm_source="google",
        utm_campaign="mixed_promo",
        referring_domain="google.com",
        signup_rate=0.06,
        purchase_rate=0.015,
        scenario="same campaign name as a Meta campaign; only google-tagged events",
    ),
    # --- Meta Ads (source stale: last sync > 24h ago) ---
    DemoCampaign(
        platform="MetaAds",
        campaign_id="120330000000000001",
        name="prospecting_feed",
        daily_cost=90.0,
        daily_impressions=11000,
        daily_clicks=180,
        daily_sessions=55,
        utm_source="meta",
        utm_campaign="prospecting_feed",
        utm_medium="paid-social",
        referring_domain="facebook.com",
        click_id_property="$fbclid",
        signup_rate=0.05,
        purchase_rate=0.012,
        # The UTM audit only exact-matches the primary source (default aliases
        # are not applied there), so the base stays "meta"; the variants still
        # exercise facebook/fb -> meta normalization on the conversions side.
        utm_source_variants={"facebook": 0.25, "fb": 0.15},
        scenario="alias sources (meta/facebook/fb) all resolve to meta",
    ),
    DemoCampaign(
        platform="MetaAds",
        campaign_id="120330000000000002",
        name="stories_reels",
        daily_cost=70.0,
        daily_impressions=9000,
        daily_clicks=150,
        daily_sessions=40,
        utm_source="ig",
        utm_campaign="stories_reels",
        utm_medium="paid-social",
        referring_domain="instagram.com",
        signup_rate=0.04,
        purchase_rate=0.008,
        scenario="'ig' is not a Meta alias -> UTM audit UNKNOWN_SOURCE + mapping suggestion flow",
    ),
    DemoCampaign(
        platform="MetaAds",
        campaign_id="120330000000000003",
        name="mixed_promo",
        daily_cost=40.0,
        daily_impressions=5200,
        daily_clicks=80,
        daily_sessions=0,
        utm_source=None,
        utm_campaign=None,
        utm_medium="paid-social",
        scenario="same name as the Google campaign that owns the events -> NAME_COLLISION",
    ),
    # --- Bing Ads (source in error state; matched by campaign_id via field preferences) ---
    DemoCampaign(
        platform="BingAds",
        campaign_id="90001",
        name="bing_brand",
        daily_cost=35.0,
        daily_impressions=900,
        daily_clicks=45,
        daily_sessions=18,
        utm_source="bing",
        utm_campaign="90001",
        referring_domain="bing.com",
        signup_rate=0.09,
        purchase_rate=0.02,
        scenario="matches by campaign_id (campaign_field_preferences)",
    ),
    DemoCampaign(
        platform="BingAds",
        campaign_id="90002",
        name="shared_campaign",
        daily_cost=25.0,
        daily_impressions=700,
        daily_clicks=30,
        daily_sessions=12,
        utm_source="google",
        utm_campaign="90002",
        referring_domain="google.com",
        signup_rate=0.03,
        purchase_rate=0.005,
        scenario="events tagged with a source claimed by Google -> NO_TAGGED_EVENTS",
    ),
    # --- LinkedIn Ads (campaign_groups hierarchy naming, cost_in_usd column) ---
    DemoCampaign(
        platform="LinkedinAds",
        campaign_id="501",
        name="li_abm_exec",
        daily_cost=110.0,
        daily_impressions=1400,
        daily_clicks=40,
        daily_sessions=16,
        utm_source="linkedin",
        utm_campaign="li_abm_exec",
        utm_medium="paid-social",
        referring_domain="linkedin.com",
        signup_rate=0.1,
        purchase_rate=0.03,
        reported_value_per_conversion=350.0,
        utm_source_variants={"li": 0.2},
        scenario="high-value B2B campaign; 'li' alias variant",
    ),
    DemoCampaign(
        platform="LinkedinAds",
        campaign_id="502",
        name="li_retargeting",
        daily_cost=45.0,
        daily_impressions=800,
        daily_clicks=18,
        daily_sessions=8,
        utm_source="linkedin",
        utm_campaign="li_retargeting",
        utm_medium="paid-social",
        referring_domain="linkedin.com",
        signup_rate=0.12,
        purchase_rate=0.04,
        scenario="LinkedIn retargeting",
    ),
    # --- Reddit Ads (spend in micros, conversion values in cents) ---
    DemoCampaign(
        platform="RedditAds",
        campaign_id="60001",
        name="reddit_devs",
        daily_cost=28.0,
        daily_impressions=5200,
        daily_clicks=120,
        daily_sessions=20,
        utm_source="reddit",
        utm_campaign="reddit_devs",
        utm_medium="paid-social",
        referring_domain="reddit.com",
        signup_rate=0.06,
        purchase_rate=0.01,
        scenario="Reddit: micros + cents formats",
    ),
    # --- Pinterest Ads (total_impression / spend_in_dollar columns) ---
    DemoCampaign(
        platform="PinterestAds",
        campaign_id="2001",
        name="pin_inspiration",
        daily_cost=22.0,
        daily_impressions=8800,
        daily_clicks=95,
        daily_sessions=14,
        utm_source="pinterest",
        utm_campaign="pin_inspiration",
        utm_medium="paid-social",
        referring_domain="pinterest.com",
        signup_rate=0.04,
        purchase_rate=0.012,
        scenario="Pinterest: dollar spend + micro-dollar checkout value",
    ),
    # --- Snapchat Ads (swipes as clicks, spend in micros; source in error state) ---
    DemoCampaign(
        platform="SnapchatAds",
        campaign_id="80001",
        name="snap_gen_z",
        daily_cost=38.0,
        daily_impressions=15500,
        daily_clicks=210,
        daily_sessions=17,
        utm_source="snapchat",
        utm_campaign="snap_gen_z",
        utm_medium="paid-social",
        referring_domain="snapchat.com",
        signup_rate=0.03,
        purchase_rate=0.006,
        scenario="Snapchat: swipes column + micros",
    ),
    # --- TikTok Ads (report in CLP: exercises currency conversion; stats schema disabled) ---
    DemoCampaign(
        platform="TikTokAds",
        campaign_id="70001",
        name="tt_launch",
        daily_cost=42.0,  # USD equivalent; written to the report in CLP
        daily_impressions=12800,
        daily_clicks=260,
        daily_sessions=30,
        utm_source="tiktok",
        utm_campaign="tt_launch",
        utm_medium="paid-social",
        referring_domain="tiktok.com",
        signup_rate=0.03,
        purchase_rate=0.006,
        # 'tik-tok' normalizes to the tiktok alias in attribution health, but not
        # in the UTM audit (different normalization rules) - both on purpose.
        utm_source_variants={"tik-tok": 0.3},
        scenario="TikTok: CLP currency conversion + near-miss 'tik-tok' variant",
    ),
    # --- External BigQuery cost table (sources_map + const: source + EUR currency) ---
    DemoCampaign(
        platform="BigQuery",
        campaign_id="partner-1",
        name="partner_newsletter_boost",
        daily_cost=30.0,  # EUR: exercises convertCurrency against team base currency
        daily_impressions=2500,
        daily_clicks=65,
        daily_sessions=22,
        utm_source="demo_partner",
        utm_campaign="partner_newsletter_boost",
        utm_medium="paid",
        referring_domain="partner.example.com",
        signup_rate=0.07,
        purchase_rate=0.018,
        scenario="self-managed style table via sources_map, const: source, EUR costs",
    ),
)


FREE_CHANNELS: tuple[DemoFreeChannel, ...] = (
    DemoFreeChannel(
        key="organic_search",
        daily_sessions=80,
        referring_domain="google.com",
        signup_rate=0.05,
        purchase_rate=0.012,
        scenario="Organic Search: no UTMs, no cost -> null ROAS/CPC",
    ),
    DemoFreeChannel(
        key="direct",
        daily_sessions=50,
        referring_domain="$direct",
        signup_rate=0.06,
        purchase_rate=0.02,
        scenario="Direct",
    ),
    DemoFreeChannel(
        key="email",
        daily_sessions=30,
        referring_domain="$direct",
        utm_source="newsletter",
        utm_medium="email",
        utm_campaign="weekly_digest",
        signup_rate=0.09,
        purchase_rate=0.025,
        utm_source_variants={"newsltr": 0.2},
        scenario="Email + a near-miss source with no known alias token (audit 'unmapped')",
    ),
    DemoFreeChannel(
        key="organic_social",
        daily_sessions=26,
        referring_domain="facebook.com",
        signup_rate=0.03,
        purchase_rate=0.006,
        scenario="Organic Social: social referrer, no UTMs, no paid signals",
    ),
    DemoFreeChannel(
        key="organic_social_x",
        daily_sessions=12,
        referring_domain="twitter.com",
        signup_rate=0.025,
        purchase_rate=0.004,
        scenario="Organic Social (X)",
    ),
    DemoFreeChannel(
        key="organic_video",
        daily_sessions=20,
        referring_domain="youtube.com",
        signup_rate=0.04,
        purchase_rate=0.008,
        scenario="Organic Video",
    ),
    DemoFreeChannel(
        key="affiliate",
        daily_sessions=9,
        referring_domain="partners.example.com",
        utm_source="partner_tier1",
        utm_medium="affiliate",
        utm_campaign="affiliate_program",
        signup_rate=0.08,
        purchase_rate=0.025,
        scenario="Affiliate channel via utm_medium=affiliate",
    ),
    DemoFreeChannel(
        key="push",
        daily_sessions=11,
        referring_domain="$direct",
        utm_source="onesignal",
        utm_medium="push",
        utm_campaign="winback_push",
        signup_rate=0.02,
        purchase_rate=0.015,
        scenario="Push channel via utm_medium=push",
    ),
    DemoFreeChannel(
        key="sms",
        daily_sessions=6,
        referring_domain="$direct",
        utm_source="twilio",
        utm_medium="sms",
        utm_campaign="flash_sale_sms",
        signup_rate=0.05,
        purchase_rate=0.03,
        scenario="SMS channel via utm_medium=sms",
    ),
    DemoFreeChannel(
        key="referral_ph",
        daily_sessions=15,
        referring_domain="producthunt.com",
        signup_rate=0.1,
        purchase_rate=0.02,
        scenario="Referral",
    ),
    DemoFreeChannel(
        key="referral_hn",
        daily_sessions=10,
        referring_domain="news.ycombinator.com",
        signup_rate=0.07,
        purchase_rate=0.01,
        scenario="Referral",
    ),
    DemoFreeChannel(
        key="ai_chatgpt",
        daily_sessions=18,
        referring_domain="chatgpt.com",
        signup_rate=0.11,
        purchase_rate=0.03,
        scenario="AI channel via referrer, no paid signals",
    ),
    DemoFreeChannel(
        key="ai_claude",
        daily_sessions=8,
        referring_domain="claude.ai",
        signup_rate=0.14,
        purchase_rate=0.04,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_perplexity",
        daily_sessions=6,
        referring_domain="perplexity.ai",
        signup_rate=0.08,
        purchase_rate=0.02,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_gemini",
        daily_sessions=4,
        referring_domain="gemini.google.com",
        signup_rate=0.06,
        purchase_rate=0.012,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_copilot",
        daily_sessions=3,
        referring_domain="copilot.microsoft.com",
        signup_rate=0.05,
        purchase_rate=0.01,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_grok",
        daily_sessions=3,
        referring_domain="grok.com",
        signup_rate=0.06,
        purchase_rate=0.012,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_deepseek",
        daily_sessions=2,
        referring_domain="deepseek.com",
        signup_rate=0.05,
        purchase_rate=0.008,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_meta",
        daily_sessions=2,
        referring_domain="meta.ai",
        signup_rate=0.04,
        purchase_rate=0.006,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_mistral",
        daily_sessions=2,
        referring_domain="chat.mistral.ai",
        signup_rate=0.05,
        purchase_rate=0.008,
        scenario="AI channel",
    ),
    DemoFreeChannel(
        key="ai_chatgpt_utm",
        daily_sessions=4,
        referring_domain="chatgpt.com",
        utm_source="chatgpt",
        utm_medium="referral",
        utm_campaign="ai_recommendation",
        signup_rate=0.1,
        purchase_rate=0.025,
        scenario="AI channel reached via utm_source=chatgpt (not just referrer)",
    ),
)

# Sources with cost rows written to the warehouse (must stay in sync with health.py).
NATIVE_PLATFORMS_WITH_DATA: tuple[str, ...] = (
    "GoogleAds",
    "MetaAds",
    "BingAds",
    "LinkedinAds",
    "RedditAds",
    "PinterestAds",
    "SnapchatAds",
    "TikTokAds",
)

BIGQUERY_SOURCE_LABEL = "demo_partner"

EVENT_SIGNUP = "user signed up"
EVENT_PURCHASE = "purchase completed"
EVENT_DEMO_BOOKED = "demo booked"
EVENT_PAGEVIEW = "$pageview"

SITE_URL = "https://demo.posthog.dev"
