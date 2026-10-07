from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.services.website_brand import read_brand_signals, read_manifest_signals


class TestReadBrandSignals(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "prefers_og_site_name",
                '<meta property="og:site_name" content="Juniper"><title>Pricing | Juniper Studio</title>',
                "Juniper",
            ),
            ("falls_back_to_the_title", "<title>Juniper Studio | Pricing</title>", "Juniper Studio"),
            ("splits_the_title_on_a_dash", "<title>Juniper Studio - Plans</title>", "Juniper Studio"),
            ("decodes_entities", "<title>Juniper &amp; Co</title>", "Juniper & Co"),
            ("skips_a_generic_first_segment", "<title>Home | Juniper Studio</title>", "Juniper Studio"),
            ("ignores_a_generic_title", "<title>Welcome</title>", "juniper.example.com"),
            (
                "keeps_only_the_page_title",
                "<title>Juniper</title><body><svg><title>Close menu</title></svg></body>",
                "Juniper",
            ),
            ("falls_back_to_the_host", "<html><head><title>  </title></head></html>", "juniper.example.com"),
        ]
    )
    def test_reads_the_brand_name(self, _name: str, html: str, expected: str) -> None:
        signals = read_brand_signals(html, "https://juniper.example.com/")

        assert signals.name == expected

    @parameterized.expand(
        [
            ("theme_color", '<meta name="theme-color" content="#1A2B3C">', "#1a2b3c", None),
            ("short_hex", '<meta name="theme-color" content="#abc">', "#aabbcc", None),
            ("rgb", '<meta name="theme-color" content="rgb(26, 43, 60)">', "#1a2b3c", None),
            (
                "light_scheme_over_dark",
                '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#123456">'
                '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#ff6600">',
                "#ff6600",
                None,
            ),
            ("tile_color", '<meta name="msapplication-TileColor" content="#2d89ef">', None, "#2d89ef"),
            ("near_white_is_not_a_brand_color", '<meta name="theme-color" content="#fafafa">', None, None),
            ("light_gray_is_not_a_brand_color", '<meta name="theme-color" content="#E5E7E0">', None, None),
            ("dark_gray_is_not_a_brand_color", '<meta name="theme-color" content="#1e2327">', None, None),
            ("mid_gray_stays_a_choice", '<meta name="theme-color" content="#6b7280">', "#6b7280", None),
            ("near_black_is_not_a_brand_color", '<meta name="theme-color" content="#000">', None, None),
            ("named_color_is_ignored", '<meta name="theme-color" content="rebeccapurple">', None, None),
        ]
    )
    def test_reads_declared_colors(
        self, _name: str, html: str, theme_color: str | None, tile_color: str | None
    ) -> None:
        signals = read_brand_signals(html, "https://juniper.example.com/")

        assert (signals.theme_color, signals.tile_color) == (theme_color, tile_color)

    def test_lists_raster_logos_largest_first_and_resolves_them(self) -> None:
        html = """
            <link rel="icon" href="/favicon.ico">
            <link rel="icon" type="image/svg+xml" href="/logo.svg">
            <link rel="icon" sizes="32x32" href="/favicon-32.png">
            <link rel="apple-touch-icon" href="/apple-touch-icon.png">
            <link rel="shortcut icon" type="image/png" sizes="192x192" href="https://cdn.example.com/icon-192">
        """

        signals = read_brand_signals(html, "https://juniper.example.com/en/")

        assert [logo.url for logo in signals.logos] == [
            "https://cdn.example.com/icon-192",
            "https://juniper.example.com/apple-touch-icon.png",
            "https://juniper.example.com/favicon-32.png",
        ]

    def test_skips_malformed_links_and_sizes(self) -> None:
        html = f"""
            <link rel="manifest" href="http://[broken/">
            <link rel="icon" href="http://[broken/icon.png">
            <link rel="apple-touch-icon" sizes="{"9" * 5000}x1" href="/apple-touch-icon.png">
        """

        signals = read_brand_signals(html, "https://juniper.example.com/")

        assert (signals.manifest_url, [logo.url for logo in signals.logos]) == (
            None,
            ["https://juniper.example.com/apple-touch-icon.png"],
        )

    def test_resolves_the_manifest_link(self) -> None:
        signals = read_brand_signals('<link rel="manifest" href="site.webmanifest">', "https://juniper.example.com/en/")

        assert signals.manifest_url == "https://juniper.example.com/en/site.webmanifest"


class TestReadManifestSignals(SimpleTestCase):
    def test_reads_theme_color_and_raster_icons(self) -> None:
        manifest = """{
            "theme_color": "#2E7D32",
            "icons": [
                {"src": "icons/192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "icons/logo.svg", "sizes": "any", "type": "image/svg+xml"},
                {"src": "icons/mono.png", "sizes": "512x512", "purpose": "monochrome"},
                {"src": "/icons/512.webp", "sizes": "256x256 512x512"},
                {"src": "http://[broken/icon.png", "sizes": "1024x1024", "type": "image/png"}
            ]
        }"""

        signals = read_manifest_signals(manifest, "https://juniper.example.com/static/site.webmanifest")

        assert signals.theme_color == "#2e7d32"
        assert [logo.url for logo in signals.logos] == [
            "https://juniper.example.com/icons/512.webp",
            "https://juniper.example.com/static/icons/192.png",
        ]

    @parameterized.expand([("not_json", "<html>"), ("not_an_object", "[1, 2]"), ("icons_not_a_list", '{"icons": 3}')])
    def test_reads_nothing_from_a_malformed_manifest(self, _name: str, manifest: str) -> None:
        signals = read_manifest_signals(manifest, "https://juniper.example.com/site.webmanifest")

        assert (signals.theme_color, signals.logos) == (None, ())
