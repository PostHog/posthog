from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import Detection, detect

# Competitors with no released warehouse source. Every source declares its own `codebase_detection`,
# so only these live here. The wizard detects and reports them, and never offers them as a source.
COMPETITORS_WITHOUT_SOURCE: dict[str, Detection] = {
    "Heap": detect(
        npm=("@heap/react-native-heap", "@heap/heap-react-native-autocapture"),
        rubygems=("heap",),
        maven=(
            "io.heap.core:heap-android-core",
            "io.heap.autocapture:heap-autocapture-view",
            "com.heapanalytics.android:heap-android-client",
        ),
        swiftpm=("github.com/heap/heap-swift-core-sdk", "github.com/heap/heap-ios-autocapture-sdk"),
        cocoapods=("Heap", "HeapSwiftCore", "HeapIOSAutocapture"),
        script_hosts=("cdn.heapanalytics.com", "cdn.us.heap-api.com"),
        competes_with=(ProductKey.PRODUCT_ANALYTICS,),
    ),
    "Hotjar": detect(
        env=("^HOTJAR_",),
        script_hosts=("static.hotjar.com", "script.hotjar.com"),
        npm=("@hotjar/browser", "react-hotjar"),
        competes_with=(ProductKey.SESSION_REPLAY, ProductKey.HEATMAPS, ProductKey.SURVEYS),
    ),
}
