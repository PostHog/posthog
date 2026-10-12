from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import Detection, detect

# Competitors with no released warehouse source. Every source declares its own `codebase_detection`,
# so only these live here. The wizard detects and reports them, and never offers them as a source.
COMPETITORS_WITHOUT_SOURCE: dict[str, Detection] = {
    "Heap": detect(env=("^HEAP_",), competes_with=(ProductKey.PRODUCT_ANALYTICS,)),
    "Hotjar": detect(
        npm=("@hotjar/browser", "react-hotjar"),
        env=("^HOTJAR_",),
        competes_with=(ProductKey.SESSION_REPLAY, ProductKey.HEATMAPS, ProductKey.SURVEYS),
    ),
}
