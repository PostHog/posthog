import ExpoModulesCore
import WidgetKit

// The suite, keys and widget kind must match targets/HedgehogWidget and modules/hedgehog-widget/README.md.
// app.config.ts names the App Group "group." plus the bundle id, so each app variant (dev, preview, store) has its own.
private let suiteName = "group.\(Bundle.main.bundleIdentifier ?? "com.posthog.code.mobile")"
private let choreographyKey = "choreography"
private let widgetKind = "HedgehogWidget"

public class HedgehogWidgetModule: Module {
    public func definition() -> ModuleDefinition {
        Name("HedgehogWidget")

        Function("setChoreography") { (json: String) in
            UserDefaults(suiteName: suiteName)?.set(json, forKey: choreographyKey)
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
        }

        Function("clearChoreography") {
            UserDefaults(suiteName: suiteName)?.removeObject(forKey: choreographyKey)
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
        }
    }
}
