from playwright.sync_api import Page

from products.dashboards.backend.facade import api as dashboards_api
from products.exports.backend.tasks.failure_handler import InvalidExportContext

PDF_PAGE_WIDTH = 1122
PDF_PAGE_HEIGHT = 794
MAX_PDF_TILES = 20
MAX_PDF_LAYOUT_HEIGHT = 50


def validate_dashboard_pdf(dashboard_id: int) -> None:
    layouts = dashboards_api.live_tile_layouts(dashboard_id, limit=MAX_PDF_TILES + 1)
    if len(layouts) > MAX_PDF_TILES:
        raise InvalidExportContext(f"PDF exports support up to {MAX_PDF_TILES} tiles. Export a smaller dashboard.")
    for tile_layouts in layouts:
        for layout in tile_layouts.values():
            height = layout.get("h", 1) if isinstance(layout, dict) else None
            if not isinstance(height, (int, float)) or not 0 < height <= MAX_PDF_LAYOUT_HEIGHT:
                raise InvalidExportContext(
                    "A dashboard tile is too tall to export as PDF. Reduce its height and retry."
                )


def render_dashboard_pdf(page: Page, path: str) -> None:
    # Grid DOM order can differ from its saved visual order; preserve it before print stacks the tiles.
    page.evaluate("""() => {
        document.querySelectorAll('.react-grid-layout').forEach(grid => {
            Array.from(grid.children)
                .filter(element => element.classList.contains('react-grid-item'))
                .map(element => ({ element, rect: element.getBoundingClientRect() }))
                .sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left)
                .forEach(({ element }, index) => { element.style.order = String(index) })
        })
    }""")
    page.emulate_media(media="print")
    page.set_viewport_size({"width": PDF_PAGE_WIDTH, "height": PDF_PAGE_HEIGHT})
    first_tile_space = page.evaluate(
        """pageHeight => {
            const tiles = Array.from(document.querySelectorAll('.react-grid-item'))
                .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
            const first = tiles[0];
            if (!first) { return pageHeight; }
            const available = Math.floor(pageHeight - first.getBoundingClientRect().top - 17);
            first.style.maxHeight = `${Math.max(0, available)}px`;
            const last = tiles[tiles.length - 1];
            const footer = document.querySelector('.Exporter-footer');
            const footerSpace = footer ? footer.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom : 0;
            const lastTileSpace = Math.floor((first === last ? available : pageHeight - 32) - footerSpace);
            last.style.maxHeight = `${Math.max(0, Math.min(last.getBoundingClientRect().height, lastTileSpace))}px`;
            return Math.min(available, lastTileSpace);
        }""",
        PDF_PAGE_HEIGHT,
    )
    if first_tile_space < 160:
        raise InvalidExportContext("The dashboard title is too tall to export as PDF. Shorten it and retry.")

    # Charts redraw after print resizes their tiles; capture only after that redraw.
    page.wait_for_timeout(500)
    document_height = page.evaluate("() => document.documentElement.scrollHeight")
    if document_height > MAX_PDF_TILES * PDF_PAGE_HEIGHT:
        raise InvalidExportContext("The dashboard is too large to export as PDF. Export a smaller dashboard.")
    page.pdf(path=path, format="A4", landscape=True, print_background=True)
