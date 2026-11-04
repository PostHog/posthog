import ExpoModulesCore
import Security
import WidgetKit

// The suite, keys, keychain item and widget kind must match targets/HedgehogWidget/Chart*.swift and
// modules/chart-widget/README.md.
// app.config.ts names the App Group "group." plus the bundle id, so each app variant (dev, preview, store) has its own.
private let suiteName = "group.\(Bundle.main.bundleIdentifier ?? "com.posthog.code.mobile")"
private let catalogKey = "chart.catalog"
private let snapshotKeyPrefixes = ["chart.snapshot.", "chart.snapshotError.", "chart.pinProject."]
private let widgetKind = "ChartWidget"
private let keychainService = "com.posthog.code.mobile.chart-widget"
private let keychainAccount = "credentials"

enum ChartWidgetKeychainError: Error, CustomStringConvertible {
    case status(OSStatus)

    var description: String {
        switch self {
        case let .status(status):
            return "The widget session could not be saved to the keychain (OSStatus \(status))"
        }
    }
}

// An App Group id is also a keychain access group of every target in that group, so the widget extension reads this
// item without a keychain-sharing entitlement.
private func credentialsItem() -> [String: Any] {
    [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: keychainService,
        kSecAttrAccount as String: keychainAccount,
        kSecAttrAccessGroup as String: suiteName,
    ]
}

private func writeCredentials(_ json: String) throws {
    // The widget refreshes on a timer while the phone is locked, so the item must stay readable after the first unlock.
    let attributes: [String: Any] = [
        kSecValueData as String: Data(json.utf8),
        kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
    ]
    var status = SecItemUpdate(credentialsItem() as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
        let item = credentialsItem().merging(attributes) { _, new in new }
        status = SecItemAdd(item as CFDictionary, nil)
    }
    if status != errSecSuccess {
        throw ChartWidgetKeychainError.status(status)
    }
}

private func deleteCredentials() -> OSStatus {
    SecItemDelete(credentialsItem() as CFDictionary)
}

private func removeSnapshots() {
    guard let defaults = UserDefaults(suiteName: suiteName) else {
        return
    }
    for key in defaults.dictionaryRepresentation().keys
    where snapshotKeyPrefixes.contains(where: { key.hasPrefix($0) }) {
        defaults.removeObject(forKey: key)
    }
}

public class ChartWidgetModule: Module {
    public func definition() -> ModuleDefinition {
        Name("ChartWidget")

        Function("setCredentials") { (json: String) throws in
            try writeCredentials(json)
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
        }

        Function("clearCredentials") { () throws in
            let status = deleteCredentials()
            // Charts of the previous account must not show to whoever signs in next, even when the delete failed.
            removeSnapshots()
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
            if status != errSecSuccess && status != errSecItemNotFound {
                throw ChartWidgetKeychainError.status(status)
            }
        }

        Function("setCatalog") { (json: String) in
            UserDefaults(suiteName: suiteName)?.set(json, forKey: catalogKey)
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
        }

        Function("clearCatalog") {
            UserDefaults(suiteName: suiteName)?.removeObject(forKey: catalogKey)
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
        }

        Function("reloadWidgets") {
            WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
        }
    }
}
