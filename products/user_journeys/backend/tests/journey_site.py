"""An invented two-page site, in variants, served on 127.0.0.1 for journey run tests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class SiteVariant(StrEnum):
    BASELINE = "baseline"
    # Three more menu items push "Sign up" past the end of the fixed-width menu.
    OVERFLOWING_MENU = "overflowing_menu"
    HIDDEN_SIGN_UP = "hidden_sign_up"
    NO_SIGN_UP = "no_sign_up"
    COVERED_SIGN_UP = "covered_sign_up"
    RECOLORED_MENU = "recolored_menu"


_MENU_ITEMS = ["Home", "Products", "Pricing", "Docs"]
_EXTRA_MENU_ITEMS = ["Changelog", "Community", "Careers"]


def _index_page(variant: SiteVariant) -> str:
    items = _MENU_ITEMS + (_EXTRA_MENU_ITEMS if variant == SiteVariant.OVERFLOWING_MENU else [])
    links = "".join(f'<a class="nav-item" href="#{item.lower()}">{item}</a>' for item in items)
    sign_up_style = ' style="display: none"' if variant == SiteVariant.HIDDEN_SIGN_UP else ""
    sign_up = (
        ""
        if variant == SiteVariant.NO_SIGN_UP
        else f'<a class="nav-signup" href="/signup.html"{sign_up_style}>Sign up</a>'
    )
    menu_color = "#c2410c" if variant == SiteVariant.RECOLORED_MENU else "#1d4ed8"
    cover = (
        '<div class="cookie-banner" style="position: fixed; inset: 0 0 auto 0; height: 120px; '
        'background: #111827; color: white; padding: 16px">We use cookies.</div>'
        if variant == SiteVariant.COVERED_SIGN_UP
        else ""
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Hedgehog supplies</title>
<style>
  body {{ margin: 0; font-family: sans-serif; }}
  .menu {{ display: flex; gap: 8px; width: 560px; overflow: hidden; white-space: nowrap;
           background: {menu_color}; padding: 12px; margin: 24px; }}
  .menu a {{ color: white; text-decoration: none; padding: 8px 14px; flex: none;
             border: 1px solid rgba(255, 255, 255, 0.4); border-radius: 4px; }}
  .menu .nav-signup {{ background: #facc15; color: #111827; font-weight: bold; }}
  main {{ margin: 24px; }}
</style>
</head>
<body>
{cover}
<nav class="menu">{links}{sign_up}</nav>
<main><h1>Supplies for hedgehogs</h1><p>Everything a hedgehog needs.</p></main>
</body>
</html>
"""


_SIGN_UP_PAGE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Sign up</title>
<style>body { margin: 24px; font-family: sans-serif; } button { padding: 12px 20px; }</style>
</head>
<body>
<h1>Create your account</h1>
<button id="create-account" onclick="document.getElementById('done').hidden = false">Create account</button>
<p id="done" hidden>Account created.</p>
</body>
</html>
"""


def write_site(root: Path, variant: SiteVariant) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(_index_page(variant))
    (root / "signup.html").write_text(_SIGN_UP_PAGE)


class _QuietHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        # `/redirect?to=<url>` answers with a redirect to any URL, like an open redirect on a real site.
        parts = urlsplit(self.path)
        if parts.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", parse_qs(parts.query)["to"][0])
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve_site(root: Path, variant: SiteVariant) -> Iterator[str]:
    """Serve one variant on its own port and yield its origin, so variants differ only by origin."""
    site_root = root / variant.value
    write_site(site_root, variant)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(site_root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
