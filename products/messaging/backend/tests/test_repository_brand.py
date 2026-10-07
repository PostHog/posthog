from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.services.repository_brand import RepositoryBrand, TreeEntry, detect_brand


class TestRepositoryBrand(SimpleTestCase):
    def detect(self, files: dict[str, str], repository_name: str = "juniper/juniper-studio") -> RepositoryBrand:
        return detect_brand(
            repository_name=repository_name,
            tree=[TreeEntry(path=path, size=len(text)) for path, text in files.items()],
            read_text=files.get,
        )

    def test_prefers_the_manifest_name_to_metadata_and_package_names(self) -> None:
        brand = self.detect(
            {
                "package.json": '{"name": "juniper-web"}',
                "app/layout.tsx": 'export const metadata = { applicationName: "Juniper App" }',
                "public/manifest.json": '{"name": "Juniper Studio", "short_name": "Juniper"}',
            }
        )

        assert brand.name == "Juniper Studio"

    @parameterized.expand(
        [
            ("metadata", {"app/layout.tsx": 'const metadata = {title: {default: "Juniper | Home"}}'}, "Juniper"),
            (
                "next.js title template",
                {
                    "app/layout.tsx": "export const metadata = { title: { template: '%s | Acme', default: 'Acme' } }",
                    "package.json": '{"name": "acme-dashboard-frontend"}',
                },
                "Acme",
            ),
            ("package", {"package.json": '{"name": "juniper-cloud"}'}, "Juniper Cloud"),
            (
                "brand starting with a noisy word",
                {"public/manifest.json": '{"name": "Home Assistant"}'},
                "Home Assistant",
            ),
            ("titled page", {"app/layout.tsx": 'const metadata = {title: "Home Assistant"}'}, "Home Assistant"),
            ("vite default title", {"index.html": "<title>Vite + React + TS</title>"}, "Juniper Studio"),
            (
                "generic manifest name",
                {"public/manifest.json": '{"name": "Web"}', "package.json": '{"name": "juniper-cloud"}'},
                "Juniper Cloud",
            ),
            ("package scope", {"package.json": '{"name": "@juniper/studio-app"}'}, "Juniper"),
            ("scaffold package", {"package.json": '{"name": "my-app"}'}, "Juniper Studio"),
            ("vite scaffold package", {"package.json": '{"name": "vite-project"}'}, "Juniper Studio"),
            ("turborepo root package", {"package.json": '{"name": "my-turborepo"}'}, "Juniper Studio"),
            ("workspace scope", {"package.json": '{"name": "@repo/web"}'}, "Juniper Studio"),
            (
                "repository",
                {"package.json": '{"name": "web"}', "index.html": "<title>Create Next App</title>"},
                "Juniper Studio",
            ),
        ]
    )
    def test_falls_back_through_the_name_sources(self, _case: str, files: dict[str, str], expected: str) -> None:
        assert self.detect(files).name == expected

    @parameterized.expand([("juniper/HeyGen", "HeyGen"), ("juniper/juniper.studio", "Juniper.studio")])
    def test_keeps_the_case_and_dots_of_a_repository_name(self, repository_name: str, expected: str) -> None:
        assert self.detect({}, repository_name=repository_name).name == expected

    @parameterized.expand(
        [
            ("brand before primary", ":root { --brand: #e5484d; --primary: #2563eb; }", "#e5484d"),
            ("light theme", ":root { --primary: #2563eb; } .dark { --primary: #e5484d; }", "#2563eb"),
            ("shadcn default", ":root { --primary: 222.2 47.4% 11.2%; }", None),
            ("shadcn v4 default", ":root { --primary: oklch(0.205 0 0); }", None),
            ("scss variable", "$main: #e5484d; $primary: $main;", "#e5484d"),
            ("css variable", ":root { --tone: #e5484d; --primary: var(--tone); }", "#e5484d"),
            ("tailwind v4", "@theme { --color-brand: var(--color-indigo-600); }", "#4f39f6"),
            ("oklch", ":root { --primary: oklch(63.7% 0.237 25.331); }", "#fb2c36"),
            ("malformed color", ":root { --brand: #12345; --primary: #2563eb; }", "#2563eb"),
            ("white", ":root { --primary: #fff; }", None),
            ("commented token", "/* --brand: #e5484d; */ :root { --primary: #2563eb; }", "#2563eb"),
            ("no final semicolon", ":root { --primary: #2563eb }", "#2563eb"),
            ("glob in a string", '@source "../components/*.tsx"; :root { --primary: #e5484d; } /* end */', "#e5484d"),
        ]
    )
    def test_resolves_primary_color_from_the_light_theme(self, _case: str, css: str, expected: str | None) -> None:
        assert self.detect({"app/globals.css": css}).primary_color == expected

    @parameterized.expand(
        [
            (
                "tailwind config",
                {"tailwind.config.ts": "export default { colors: {primary: {DEFAULT: '#2563eb'}} }"},
                "#2563eb",
            ),
            (
                "tailwind default shade",
                {"tailwind.config.ts": "export default { colors: {primary: {500: '#3b82f6', DEFAULT: '#2563eb'}} }"},
                "#2563eb",
            ),
            (
                "glob in a tailwind config string",
                {
                    "tailwind.config.js": 'module.exports = {content: ["./*.html"], colors: {primary: "#e5484d"}} /** end */'
                },
                "#e5484d",
            ),
            ("palette", {"tailwind.config.js": "module.exports = {colors: {brand: colors.indigo[600]}}"}, "#4f46e5"),
            ("manifest", {"public/manifest.json": '{"theme_color": "#2563eb"}'}, "#2563eb"),
            ("document", {"index.html": '<meta name="theme-color" content="#2563eb">'}, "#2563eb"),
            (
                "svg logo in a crowded repository",
                {
                    **{f"{kind}{index}/package.json": "{}" for kind in ("a", "b") for index in range(2)},
                    **{f"web{index}/public/manifest.json": "{}" for index in range(2)},
                    **{f"site{index}/tailwind.config.js": "module.exports = {}" for index in range(2)},
                    **{f"page{index}/index.html": "<html></html>" for index in range(3)},
                    **{f"style{index}/globals.css": "body {}" for index in range(5)},
                    **{f"theme{index}/theme.ts": "export const theme = {}" for index in range(2)},
                    "public/logo.svg": '<svg><path fill="#e5484d"/></svg>',
                },
                "#e5484d",
            ),
            (
                "gray yields to theme",
                {
                    "app/globals.css": ":root { --primary: #6b7280; }",
                    "public/manifest.json": '{"theme_color": "#e5484d"}',
                },
                "#e5484d",
            ),
        ]
    )
    def test_reads_primary_color_sources(self, _case: str, files: dict[str, str], expected: str) -> None:
        assert self.detect(files).primary_color == expected

    def test_chooses_the_web_app_and_uses_its_shared_theme(self) -> None:
        brand = self.detect(
            {
                "apps/docs/public/manifest.json": '{"name": "Docs"}',
                "apps/web/public/manifest.json": '{"name": "Juniper Cloud"}',
                "packages/ui/theme.css": ":root { --brand: #e5484d; }",
                "apps/admin/theme.css": ":root { --brand: #2563eb; }",
                **{f"apps/admin/tests/fixture{index}/package.json": "{}" for index in range(7)},
                **{f"apps/admin/vendor{index}/package.json": "x" * 400_001 for index in range(7)},
            }
        )
        assert (brand.name, brand.primary_color) == ("Juniper Cloud", "#e5484d")

    def test_ranks_shallow_own_raster_logos_before_manifest_icons_and_favicons(self) -> None:
        files = {
            "public/images/press/logo-large.png": "a larger raster image",
            "public/.well-known/oauth/desktop/logo.png": "raster",
            "public/manifest.json": '{"icons": [{"src": "/icon.png"}]}',
            "public/logo.svg": '<svg fill="#e5484d"/>',
            "public/favicon.ico": "ico",
            "public/favicon.png": "raster",
            "public/logo.webp": "raster",
            "public/icon.png": "raster",
            "public/logo-white.png": "raster",
            "public/providers/vendor/logo.png": "raster",
        }
        assert self.detect(files).logo_paths == (
            "public/logo.webp",
            "public/images/press/logo-large.png",
            "public/icon.png",
        )
