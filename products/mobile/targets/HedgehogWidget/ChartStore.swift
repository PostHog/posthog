import Foundation
import Security

/// The chart widget's side of the store it shares with the app (modules/chart-widget/ios/ChartWidgetModule.swift).
/// Foundation and Security only, so scripts/check_chart_widget.swift can compile it.
enum ChartStore {
    static let catalogKey = "chart.catalog"
    static let keychainService = "com.posthog.code.mobile.chart-widget"
    static let keychainAccount = "credentials"

    static func snapshotKey(_ pinId: String) -> String { "chart.snapshot.\(pinId)" }
    static func snapshotErrorKey(_ pinId: String) -> String { "chart.snapshotError.\(pinId)" }
    static func pinProjectKey(_ pinId: String) -> String { "chart.pinProject.\(pinId)" }

    static var defaults: UserDefaults? { UserDefaults(suiteName: AppGroup.suiteName) }

    static func decodeCatalog(_ json: String) -> ChartCatalog? {
        guard let catalog = try? JSONDecoder().decode(ChartCatalog.self, from: Data(json.utf8)),
              catalog.version == ChartCatalog.supportedVersion
        else {
            return nil
        }
        return catalog
    }

    static func catalog(store: UserDefaults? = ChartStore.defaults) -> ChartCatalog? {
        store?.string(forKey: catalogKey).flatMap(decodeCatalog)
    }

    static func snapshot(pinId: String, store: UserDefaults? = ChartStore.defaults) -> ChartSnapshot? {
        guard let json = store?.string(forKey: snapshotKey(pinId)),
              let snapshot = try? JSONDecoder().decode(ChartSnapshot.self, from: Data(json.utf8)),
              snapshot.version == ChartSnapshot.supportedVersion
        else {
            return nil
        }
        return snapshot
    }

    static func save(_ snapshot: ChartSnapshot, store: UserDefaults? = ChartStore.defaults) {
        guard let data = try? JSONEncoder().encode(snapshot), let json = String(data: data, encoding: .utf8) else {
            return
        }
        store?.set(json, forKey: snapshotKey(snapshot.pinId))
        store?.removeObject(forKey: snapshotErrorKey(snapshot.pinId))
    }

    static func error(pinId: String, store: UserDefaults? = ChartStore.defaults) -> ChartSnapshotError? {
        guard let json = store?.string(forKey: snapshotErrorKey(pinId)) else { return nil }
        return try? JSONDecoder().decode(ChartSnapshotError.self, from: Data(json.utf8))
    }

    static func save(_ error: ChartSnapshotError, pinId: String, store: UserDefaults? = ChartStore.defaults) {
        guard let data = try? JSONEncoder().encode(error), let json = String(data: data, encoding: .utf8) else {
            return
        }
        store?.set(json, forKey: snapshotErrorKey(pinId))
    }

    static func pinProject(pinId: String, store: UserDefaults? = ChartStore.defaults) -> ChartPinProject? {
        guard let json = store?.string(forKey: pinProjectKey(pinId)) else { return nil }
        return try? JSONDecoder().decode(ChartPinProject.self, from: Data(json.utf8))
    }

    /// Writes only a changed marker, because every timeline call resolves its pins again.
    static func save(_ project: ChartPinProject, pinId: String, store: UserDefaults? = ChartStore.defaults) {
        guard pinProject(pinId: pinId, store: store) != project,
              let data = try? JSONEncoder().encode(project), let json = String(data: data, encoding: .utf8)
        else {
            return
        }
        store?.set(json, forKey: pinProjectKey(pinId))
    }

    static func decodeCredentials(_ data: Data) -> ChartCredentials? {
        guard let credentials = try? JSONDecoder().decode(ChartCredentials.self, from: data),
              credentials.version == ChartCredentials.supportedVersion,
              !credentials.accessToken.isEmpty
        else {
            return nil
        }
        return credentials
    }

    /// The app writes the item with `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, so a refresh while the phone is
    /// locked still reads it. An App Group id is also a keychain access group.
    static func credentials(accessGroup: String = AppGroup.suiteName) -> ChartCredentials? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
            kSecAttrAccessGroup as String: accessGroup,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return decodeCredentials(data)
    }
}
