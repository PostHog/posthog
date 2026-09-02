from parameterized import parameterized

from posthog.models.integration import OauthIntegration

from products.marketing_analytics.backend.services.native_integrations import (
    DISPLAY_NAMES,
    EXTERNAL_SOURCE_TYPE_TO_NATIVE,
    KEY_TO_NATIVE,
    NATIVE_TO_KEY,
    OAUTH_KIND_BY_NATIVE,
    aliases_for,
    canonical_source_aliases,
    display_name_for_key,
    lookup_alias,
    normalize,
)


class TestNormalize:
    @parameterized.expand(
        [
            ("Facebook", "facebook"),
            ("FACEBOOK-ADS", "facebookads"),
            ("Meta_Ads", "metaads"),
            ("  fb  ", "fb"),
            ("Google AdWords", "googleadwords"),
            ("", ""),
            ("---!!!", ""),
        ]
    )
    def test_normalize(self, raw, expected):
        assert normalize(raw) == expected


class TestLookupAlias:
    # Every value here MUST appear in one of the `*DefaultSources` enums in
    # `posthog/schema.py` (the platform-documented source list). Ad-hoc
    # variants like `fbads`, `googleads`, `tt` are NOT default-aliased — teams
    # configure those via `custom_source_mappings` per project.
    @parameterized.expand(
        [
            ("FB", "meta_ads"),
            ("facebook", "meta_ads"),
            ("Instagram", "meta_ads"),
            ("Meta", "meta_ads"),
            ("AdWords", "google_ads"),
            ("YouTube", "google_ads"),
            ("LinkedIn", "linkedin_ads"),
            ("Bing", "bing_ads"),
            ("Microsoft", "bing_ads"),
            ("Snapchat", "snapchat_ads"),
            ("TikTok", "tiktok_ads"),
        ]
    )
    def test_known_aliases_resolve(self, raw, expected):
        assert lookup_alias(raw) == expected

    @parameterized.expand(
        [
            ("unknown_source",),
            ("xyz",),
            ("",),
            ("organic",),
            ("direct",),
            ("newsletter",),
        ]
    )
    def test_unknown_aliases_return_none(self, raw):
        assert lookup_alias(raw) is None


class TestAliasesFor:
    def test_meta_ads_aliases_include_known_variants(self):
        meta = aliases_for("meta_ads")
        # All values come from MetaAdsDefaultSources in posthog/schema.py.
        assert "fb" in meta
        assert "facebook" in meta
        assert "instagram" in meta
        assert "meta" in meta

    def test_aliases_are_disjoint_per_integration(self):
        all_aliases: dict[str, str] = {}
        for alias, target in canonical_source_aliases().items():
            assert alias not in all_aliases, f"alias '{alias}' is mapped twice"
            all_aliases[alias] = target

    def test_youtube_resolves_to_google_ads(self):
        # `youtube` is in GoogleAdsDefaultSources — confirms canonical aliases are
        # derived from the official `*DefaultSources` enums (not a hardcoded list).
        assert lookup_alias("youtube") == "google_ads"

    def test_threads_resolves_to_meta_ads(self):
        # `threads` is in MetaAdsDefaultSources.
        assert lookup_alias("threads") == "meta_ads"

    def test_whatsapp_resolves_to_meta_ads(self):
        assert lookup_alias("whatsapp") == "meta_ads"

    def test_each_native_has_at_least_one_alias(self):
        for key in NATIVE_TO_KEY.values():
            assert len(aliases_for(key)) > 0, f"no aliases configured for {key}"


class TestDisplayNames:
    @parameterized.expand(
        [
            ("google_ads", "Google Ads"),
            ("meta_ads", "Meta Ads"),
            ("bing_ads", "Bing Ads"),
            ("linkedin_ads", "LinkedIn Ads"),
            ("reddit_ads", "Reddit Ads"),
            ("pinterest_ads", "Pinterest Ads"),
            ("snapchat_ads", "Snapchat Ads"),
            ("tiktok_ads", "TikTok Ads"),
        ]
    )
    def test_display_name_for_key(self, key, expected):
        assert display_name_for_key(key) == expected


class TestStructuralInvariants:
    def test_native_to_key_is_bijection_with_key_to_native(self):
        assert {v: k for k, v in NATIVE_TO_KEY.items()} == KEY_TO_NATIVE

    def test_display_names_cover_all_natives(self):
        for native in NATIVE_TO_KEY.keys():
            assert native in DISPLAY_NAMES

    def test_external_source_type_resolves_to_native(self):
        for source_type, native in EXTERNAL_SOURCE_TYPE_TO_NATIVE.items():
            assert native in NATIVE_TO_KEY
            assert isinstance(source_type, str)

    def test_every_oauth_kind_is_one_the_authorize_endpoint_accepts(self):
        # Spelled out means it can drift, and a kind `authorize` rejects is a Connect button
        # that 400s. `supported_kinds` is what that endpoint validates against.
        unknown = set(OAUTH_KIND_BY_NATIVE.values()) - set(OauthIntegration.supported_kinds)

        assert not unknown, f"{sorted(unknown)} are not kinds the authorize endpoint accepts"

    def test_every_native_integration_has_an_oauth_kind(self):
        for native in NATIVE_TO_KEY:
            assert native in OAUTH_KIND_BY_NATIVE, f"{native} has no OAuth kind, so it can't be connected"
