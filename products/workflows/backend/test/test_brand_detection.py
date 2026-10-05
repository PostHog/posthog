import json
import time
import random

import pytest

from parameterized import parameterized

from posthog.models.uploaded_media import MAX_IMAGE_BYTES

from products.workflows.backend.services.brand_detection.detector import (
    BrandDetection,
    TreeEntry,
    UnknownAppRoot,
    detect_brand,
)
from products.workflows.backend.services.brand_detection.files import MAX_FILE_BYTES


def detect(files: dict[str, str], *, app_root: str | None = None, repository: str = "acme/acme-web") -> BrandDetection:
    reads: list[str] = []

    def read_text(path: str) -> str:
        reads.append(path)
        return files[path]

    tree = [TreeEntry(path=path, size=len(text.encode())) for path, text in files.items()]
    detection = detect_brand(repository_name=repository, tree=tree, read_text=read_text, app_root=app_root)
    assert len(reads) == len(set(reads)), "a file was read twice"
    return detection


def css_root(*declarations: str) -> str:
    return ":root {\n" + "".join(f"  {declaration};\n" for declaration in declarations) + "}\n"


TAILWIND_COLORS_IMPORT = 'const colors = require("tailwindcss/colors")\n'


class TestBrandColors:
    @parameterized.expand(
        [
            ("hex", css_root("--brand: #1D4AFF"), "#1d4aff"),
            ("short hex", css_root("--brand: #e44"), "#ee4444"),
            ("hex with alpha", css_root("--brand: #1d4aff80"), "#1d4aff"),
            ("rgb with commas", css_root("--brand: rgb(29, 74, 255)"), "#1d4aff"),
            ("rgb with slash alpha", css_root("--brand: rgb(29 74 255 / 50%)"), "#1d4aff"),
            ("hsl", css_root("--brand: hsl(0, 100%, 50%)"), "#ff0000"),
            ("shadcn triplet", css_root("--brand: 120 100% 25%"), "#008000"),
            ("hsl around a triplet variable", css_root("--brand: hsl(var(--blue))", "--blue: 240 100% 50%"), "#0000ff"),
            ("oklch", css_root("--brand: oklch(62.8% 0.2577 29.23)"), "#ff0000"),
            ("oklch clamped into sRGB", css_root("--brand: oklch(0.628 0.3 29.23)"), "#ff0000"),
            (
                "var chain",
                css_root("--brand: var(--brand-base)", "--brand-base: var(--blue-6)", "--blue-6: #1d4aff"),
                "#1d4aff",
            ),
            ("var fallback", css_root("--brand: var(--missing, #1d4aff)"), "#1d4aff"),
            ("tailwind v4 palette variable", css_root("--color-brand: var(--color-indigo-600)"), "#4f46e5"),
            ("tailwind theme() palette reference", css_root("--brand: theme('colors.indigo.600')"), "#4f46e5"),
        ]
    )
    def test_converts_every_color_format_to_hex(self, _name, css, expected):
        detection = detect({"app/globals.css": css})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == expected

    @parameterized.expand(
        [
            ("palette shade", "colors: { brand: colors.indigo[600] }", "#4f46e5"),
            ("palette without a shade", "colors: { brand: colors.indigo }", "#6366f1"),
            ("object with DEFAULT", "colors: { primary: { DEFAULT: '#1d4aff', 50: '#eef2ff' } }", "#1d4aff"),
        ]
    )
    def test_reads_tailwind_config_colors(self, _name, colors, expected):
        config = TAILWIND_COLORS_IMPORT + "module.exports = { theme: { extend: { " + colors + " } } }\n"

        detection = detect({"tailwind.config.js": config})

        assert detection.proposal.primary_color is not None
        assert (detection.proposal.primary_color.value, detection.proposal.primary_color.line) == (expected, 2)

    def test_reads_scss_defaults_through_their_variable_chain(self):
        scss = "$blue: #1d4aff !default;\n$primary: $blue !default;\n"

        detection = detect({"src/styles/_variables.scss": scss})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == "#1d4aff"
        assert detection.proposal.primary_color.line == 2

    def test_reads_an_mui_palette_main_color(self):
        theme = "export const theme = createTheme({\n  palette: {\n    primary: { main: '#e5484d' },\n  },\n})\n"

        detection = detect({"src/theme.ts": theme})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == "#e5484d"

    @parameterized.expand(
        [
            (
                "brand token over primary token",
                {"app/globals.css": css_root("--primary: #2563eb", "--brand: #e5484d")},
                "#e5484d",
            ),
            (
                "primary token over theme color",
                {
                    "app/globals.css": css_root("--primary: #2563eb"),
                    "public/manifest.json": json.dumps({"theme_color": "#e5484d"}),
                },
                "#2563eb",
            ),
            (
                "theme color over logo fill",
                {
                    "index.html": '<meta name="theme-color" content="#2563eb">',
                    "public/logo.svg": '<svg><path fill="#e5484d"/></svg>',
                },
                "#2563eb",
            ),
            (
                "next viewport theme color",
                {"app/layout.tsx": "export const viewport = { themeColor: '#2563eb' }"},
                "#2563eb",
            ),
            ("logo fill", {"public/logo.svg": '<svg><path fill="#e5484d"/><path fill="#fff"/></svg>'}, "#e5484d"),
            (
                "saturated theme color over a gray primary token",
                {
                    "app/globals.css": css_root("--primary: #6b7280"),
                    "public/manifest.json": json.dumps({"theme_color": "#e5484d"}),
                },
                "#e5484d",
            ),
            (
                "near-black brand token over a saturated theme color",
                {
                    "app/globals.css": css_root("--brand: #111111"),
                    "public/manifest.json": json.dumps({"theme_color": "#e5484d"}),
                },
                "#111111",
            ),
            (
                "gray primary token when nothing saturated exists",
                {"app/globals.css": css_root("--primary: #6b7280")},
                "#6b7280",
            ),
        ]
    )
    def test_ranks_primary_signals(self, _name, files, expected):
        detection = detect(files)

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == expected

    @parameterized.expand(
        [
            ("rgb channel beyond float range", "rgb(1e309 0 0)"),
            ("oklch lightness beyond float range", "oklch(1e200 0 0)"),
            ("hsl with a missing channel", "hsl(120, 50%)"),
            ("hex of odd length", "#12345"),
        ]
    )
    def test_skips_a_malformed_color_instead_of_failing(self, _name, expression):
        detection = detect({"app/globals.css": css_root(f"--brand: {expression}", "--primary: #2563eb")})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == "#2563eb"

    def test_never_proposes_a_near_white_theme_color_as_primary(self):
        detection = detect(
            {
                "public/manifest.json": json.dumps({"theme_color": "#ffffff"}),
                "index.html": '<meta name="theme-color" content="#fafafa">',
            }
        )

        assert detection.proposal.primary_color is None

    @parameterized.expand(
        [
            ("shadcn v3 slate", css_root("--primary: 222.2 47.4% 11.2%")),
            ("shadcn v3 zinc", css_root("--primary: 240 5.9% 10%")),
            ("shadcn v4 neutral", css_root("--primary: oklch(0.205 0 0)")),
        ]
    )
    def test_flags_an_untouched_shadcn_primary_as_default_theme(self, _name, css):
        detection = detect({"app/globals.css": css})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.default_theme is True

    def test_does_not_flag_a_customized_primary(self):
        detection = detect({"app/globals.css": css_root("--primary: 252 87% 58%")})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.default_theme is False

    def test_picks_an_accent_with_a_different_hue_and_ignores_shadcn_surfaces(self):
        detection = detect(
            {
                "app/globals.css": css_root(
                    "--primary: #e5484d",
                    "--accent: 210 40% 96.1%",
                    "--secondary: 262 83% 58%",
                ),
                "public/manifest.json": json.dumps({"theme_color": "#e0484f"}),
                "public/logo.svg": '<svg><path fill="#0ea5e9"/></svg>',
            }
        )

        assert detection.proposal.accent_color is not None
        assert detection.proposal.accent_color.value == "#0ea5e9"

    def test_prefers_an_accent_token_from_the_tailwind_config(self):
        detection = detect(
            {
                "app/globals.css": css_root("--brand: #e5484d"),
                "tailwind.config.ts": "export default { theme: { colors: { accent: '#f59e0b' } } }",
            }
        )

        assert detection.proposal.accent_color is not None
        assert detection.proposal.accent_color.value == "#f59e0b"


class TestTextAndBackground:
    def test_reads_the_light_theme_foreground_and_background(self):
        css = css_root("--background: 0 0% 100%", "--foreground: #1c1c1c") + ".dark {\n  --background: #000000;\n}\n"

        detection = detect({"app/globals.css": css})

        assert detection.proposal.background_color is not None and detection.proposal.text_color is not None
        assert (detection.proposal.background_color.value, detection.proposal.background_color.line) == ("#ffffff", 2)
        assert detection.proposal.text_color.value == "#1c1c1c"

    @parameterized.expand(
        [
            ("dark first theme", css_root("--background: #0b0b0f", "--foreground: #f5f5f5")),
            ("no theme colors", css_root("--brand: #e5484d")),
        ]
    )
    def test_falls_back_to_dark_text_on_white(self, _name, css):
        detection = detect({"app/globals.css": css})

        assert detection.proposal.text_color is not None and detection.proposal.background_color is not None
        assert (detection.proposal.text_color.value, detection.proposal.text_color.path) == ("#111111", None)
        assert (detection.proposal.background_color.value, detection.proposal.background_color.path) == (
            "#ffffff",
            None,
        )


class TestBrandName:
    @parameterized.expand(
        [
            (
                "manifest name",
                {
                    "public/manifest.json": json.dumps({"name": "Acme Cloud", "short_name": "Acme"}),
                    "package.json": json.dumps({"name": "acme-web"}),
                },
                "Acme Cloud",
                "public/manifest.json",
            ),
            (
                "next metadata siteName",
                {
                    "app/layout.tsx": "export const metadata = {\n  openGraph: { siteName: 'Acme Cloud' },\n  title: 'Home'\n}"
                },
                "Acme Cloud",
                "app/layout.tsx",
            ),
            (
                "manifest short name",
                {"public/site.webmanifest": json.dumps({"short_name": "Acme"})},
                "Acme",
                "public/site.webmanifest",
            ),
            (
                "next metadata title default",
                {"app/layout.tsx": "export const metadata = { title: { default: 'Acme Cloud', template: '%s' } }"},
                "Acme Cloud",
                "app/layout.tsx",
            ),
            ("html title", {"index.html": "<title>Acme Cloud | Ship faster</title>"}, "Acme Cloud", "index.html"),
            (
                "scoped package name with suffix",
                {"package.json": json.dumps({"name": "@acme/acme-cloud-app"})},
                "Acme Cloud",
                "package.json",
            ),
            ("repository name", {"README.md": "# readme"}, "Acme Web", None),
            (
                "template title is ignored",
                {"index.html": "<title>Create Next App</title>", "package.json": json.dumps({"name": "acme-cloud"})},
                "Acme Cloud",
                "package.json",
            ),
            (
                "sign-in title is ignored",
                {"index.html": "<title>Sign in to Acme</title>", "package.json": json.dumps({"name": "globex"})},
                "Globex",
                "package.json",
            ),
            (
                "scaffold manifest names are ignored",
                {
                    "public/manifest.json": json.dumps({"name": "Create React App Sample", "short_name": "React App"}),
                    "package.json": json.dumps({"name": "globex-dashboard"}),
                },
                "Globex Dashboard",
                "package.json",
            ),
            (
                "names that are not valid unicode are ignored",
                {
                    "public/manifest.json": '{"name": "\\ud800"}',
                    "package.json": '{"name": "\\udfff-web"}',
                    "app/layout.tsx": "export const metadata = { title: 'Globex' }",
                },
                "Globex",
                "app/layout.tsx",
            ),
            (
                "generic package name is ignored",
                {"package.json": json.dumps({"name": "@acme/web"})},
                "Acme Web",
                None,
            ),
        ]
    )
    def test_ranks_name_sources(self, _name, files, expected_name, expected_path):
        detection = detect(files)

        assert detection.proposal.name is not None
        assert (detection.proposal.name.value, detection.proposal.name.path) == (expected_name, expected_path)


class TestFont:
    @parameterized.expand(
        [
            (
                "next/font/google import",
                {
                    "app/layout.tsx": 'import { Geist_Mono, Plus_Jakarta_Sans } from "next/font/google"',
                    "app/globals.css": css_root("--font-sans: 'Inter', sans-serif"),
                },
                "Plus Jakarta Sans",
            ),
            ("css --font-sans", {"app/globals.css": css_root('--font-sans: "Manrope", ui-sans-serif')}, "Manrope"),
            (
                "tailwind fontFamily sans",
                {
                    "tailwind.config.js": "module.exports = { theme: { fontFamily: { sans: ['Nunito', 'sans-serif'] } } }"
                },
                "Nunito",
            ),
            ("body font-family", {"src/styles/main.css": "body {\n  font-family: 'Lato', sans-serif;\n}"}, "Lato"),
            (
                "google fonts link",
                {
                    "index.html": '<link href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@400" rel="stylesheet">'
                },
                "Work Sans",
            ),
            (
                "generic families are skipped",
                {"app/globals.css": css_root("--font-sans: var(--font-geist), system-ui, sans-serif")},
                None,
            ),
        ]
    )
    def test_ranks_font_sources(self, _name, files, expected_family):
        font = detect(files).proposal.font_family

        assert (font.value if font else None) == expected_family

    def test_ends_the_font_stack_in_email_safe_fonts(self):
        font = detect({"app/globals.css": css_root("--font-sans: 'Plus Jakarta Sans'")}).proposal.font_family

        assert font is not None
        assert font.font_stack == "'Plus Jakarta Sans', Arial, Helvetica, sans-serif"


class TestAppRoot:
    MONOREPO = {
        "package.json": json.dumps({"name": "acme"}),
        "apps/docs/package.json": json.dumps({"name": "@acme/docs"}),
        "apps/docs/public/manifest.json": json.dumps({"name": "Acme Docs"}),
        "apps/storybook/package.json": json.dumps({"name": "@acme/storybook"}),
        "apps/marketing/package.json": json.dumps({"name": "@acme/marketing"}),
        "apps/marketing/app/globals.css": css_root("--brand: #0ea5e9"),
        "apps/dashboard/package.json": json.dumps({"name": "@acme/dashboard"}),
        "apps/dashboard/app/layout.tsx": "export const metadata = { title: 'Acme' }",
        "packages/ui/src/globals.css": css_root("--primary: #e5484d"),
        "packages/eslint-config/index.css": css_root("--brand: #000000"),
        "e2e/app/globals.css": css_root("--brand: #00ff00"),
    }

    def test_prefers_a_named_web_app_and_reads_the_shared_ui_package(self):
        detection = detect(self.MONOREPO)

        assert detection.app_root == "apps/dashboard/"
        assert detection.app_root_alternatives == ("apps/marketing/",)
        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.path == "packages/ui/src/globals.css"

    def test_reads_the_requested_app_root(self):
        detection = detect(self.MONOREPO, app_root="apps/marketing")

        assert detection.app_root == "apps/marketing/"
        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == "#0ea5e9"

    def test_rejects_an_app_root_outside_the_repository(self):
        with pytest.raises(UnknownAppRoot):
            detect(self.MONOREPO, app_root="apps/missing")

    def test_reads_at_most_fifteen_files_when_every_kind_has_candidates(self):
        files = {
            **{f"src/{index}/package.json": "{}" for index in range(3)},
            **{f"src/{index}/manifest.json": "{}" for index in range(3)},
            **{f"src/{index}/tailwind.config.js": "" for index in range(3)},
            **{f"src/{index}/index.html": "" for index in range(4)},
            **{f"src/{index}/globals.css": "" for index in range(6)},
            **{f"src/{index}/theme.ts": "" for index in range(3)},
            **{f"public/{index}/logo.svg": "<svg/>" for index in range(2)},
        }

        assert len(detect(files).files_read) == 15


class TestLogoCandidates:
    @parameterized.expand(
        [
            (
                "own logos, manifest icon and touch icon as raster, then svg, cut at five before the ico",
                {
                    "public/favicon.ico": "x",
                    "public/logo.svg": "<svg/>",
                    "public/apple-touch-icon.png": "x",
                    "public/icons/icon-512.png": "x",
                    "public/manifest.json": json.dumps({"icons": [{"src": "/icons/icon-512.png"}]}),
                    "public/brand/logo.webp": "x",
                    "public/logo.png": "x",
                },
                [
                    "public/brand/logo.webp",
                    "public/logo.png",
                    "public/icons/icon-512.png",
                    "public/apple-touch-icon.png",
                    "public/logo.svg",
                ],
            ),
            (
                "manifest icon relative to the manifest, missing icons skipped",
                {
                    "static/site.webmanifest": json.dumps(
                        {"icons": [{"src": "android-chrome-192x192.png"}, {"src": "/missing.png"}, {"src": 7}]}
                    ),
                    "static/android-chrome-192x192.png": "x",
                },
                ["static/android-chrome-192x192.png"],
            ),
            (
                "nested manifest: root-relative icons from the served root, relative ones from the manifest",
                {
                    "public/pwa/manifest.json": json.dumps(
                        {"icons": [{"src": "/icons/app.png"}, {"src": "maskable.png"}]}
                    ),
                    "public/icons/app.png": "x",
                    "public/pwa/maskable.png": "x",
                },
                ["public/icons/app.png", "public/pwa/maskable.png"],
            ),
            (
                "app files first, files over the media library limit and empty files skipped",
                {
                    "apps/web/package.json": "{}",
                    "apps/web/public/logo.png": "x",
                    "assets/logo.png": "x" * 100,
                    "apps/web/public/logo-hires.png": "x" * (MAX_IMAGE_BYTES + 1),
                    "apps/web/public/brand.png": "",
                    "public/manifest.json": json.dumps({"icons": [{"src": "/icon.png?v=2"}]}),
                    "public/icon.png": "x",
                },
                ["apps/web/public/logo.png", "assets/logo.png", "public/icon.png"],
            ),
            (
                "color variants and third-party directories skipped",
                {
                    "public/logo-dark.png": "x",
                    "public/logo_inverse.svg": "<svg/>",
                    "assets/logo-mono.png": "x",
                    "assets/brand-white.png": "x",
                    "public/providers/github/logo.png": "x",
                    "public/Integrations/logo.png": "x",
                    "public/partners/logo.png": "x",
                    "src/components/logo.png": "x",
                    "public/logo.png": "x",
                },
                ["public/logo.png"],
            ),
        ]
    )
    def test_ranks_logo_candidates(self, _name, files, expected_paths):
        assert [candidate.path for candidate in detect(files).logo_candidates] == expected_paths


class TestHostileContent:
    LARGEST_READ_FILE = MAX_FILE_BYTES - 64
    PARSE_SECONDS_LIMIT = 2.0

    @parameterized.expand(
        [
            ("hyphen run in a comment", "app/globals.css", "/* ", "-", " */"),
            ("custom properties without a semicolon", "app/globals.css", "", "--a:b ", ""),
            ("unclosed dark blocks", "app/globals.css", "", ".dark {", ""),
            ("body selectors without a block", "app/globals.css", "", "body,", ""),
            ("one declaration per line", "app/globals.css", ":root {\n", "--a: #e5484d;\n", "}"),
            ("deeply nested json", "package.json", "", "[", ""),
            ("manifest color padded with spaces", "public/manifest.json", '{"theme_color": "rgb(0 0 0', " ", 'x)"}'),
            ("unclosed font imports", "app/layout.tsx", "", "import {", ""),
            ("theme-color metas without an end", "index.html", "", '<meta name="theme-color" ', ""),
            ("unclosed rgb fills", "public/logo.svg", "<svg>", "fill=rgb(", "</svg>"),
        ]
    )
    def test_parses_a_hostile_file_of_the_largest_read_size_quickly(self, _name, path, prefix, unit, suffix):
        repeats = (self.LARGEST_READ_FILE - len(prefix) - len(suffix)) // len(unit)
        text = prefix + unit * repeats + suffix

        started = time.monotonic()
        detect({path: text})

        assert time.monotonic() - started < self.PARSE_SECONDS_LIMIT


class TestDeterminism:
    FILES = {
        "b/styles/globals.css": css_root("--brand: #2563eb"),
        "a/styles/globals.css": css_root("--brand: #e5484d"),
        "public/logo.svg": '<svg><path fill="#16a34a"/><path fill="#9333ea"/></svg>',
        "app/layout.tsx": 'import { Inter, Roboto } from "next/font/google"',
    }

    def test_ties_pick_the_same_values_whatever_the_tree_order(self):
        paths = list(self.FILES)
        detections = []
        for seed in range(5):
            random.Random(seed).shuffle(paths)
            detections.append(detect({path: self.FILES[path] for path in paths}))

        assert all(detection == detections[0] for detection in detections)
        assert detections[0].proposal.primary_color is not None
        assert detections[0].proposal.primary_color.path == "a/styles/globals.css"

    def test_tied_logo_fills_pick_the_same_color(self):
        detection = detect({"public/logo.svg": self.FILES["public/logo.svg"]})

        assert detection.proposal.primary_color is not None
        assert detection.proposal.primary_color.value == "#16a34a"
