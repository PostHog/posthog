import Foundation

enum AppGroup {
    private static let extensionSuffix = ".HedgehogWidget"

    // app.config.ts names the App Group "group." plus the app's bundle id, and this extension's bundle id is the
    // app's id plus ".HedgehogWidget", so each app variant reads its own store.
    static func appId(fromExtensionBundleId widgetId: String) -> String {
        widgetId.hasSuffix(extensionSuffix) ? String(widgetId.dropLast(extensionSuffix.count)) : widgetId
    }

    static let appId: String = appId(
        fromExtensionBundleId: Bundle.main.bundleIdentifier ?? "com.posthog.code.mobile\(extensionSuffix)"
    )

    static let suiteName = "group.\(appId)"
}
