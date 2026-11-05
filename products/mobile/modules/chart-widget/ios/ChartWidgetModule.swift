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
    case .status(let status):
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
  guard let defaults = ChartStore.storage else {
    return
  }
  for key in defaults.keys
  where snapshotKeyPrefixes.contains(where: { key.hasPrefix($0) }) {
    defaults.removeObject(forKey: key)
  }
}

public class ChartWidgetModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ChartWidget")

    AsyncFunction("getWidgetState") {
      if #available(iOS 17.0, *) { return try await chartWidgetState() }
      return ["installed": false, "pinIds": [], "usesDefault": false] as [String: Any]
    }

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
      if let defaults = ChartStore.storage {
        let catalog = (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any]
        let old = defaults.string(forKey: catalogKey).flatMap {
          (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
        }
        let oldPins = old?["pins"] as? [[String: Any]] ?? []
        let pins = catalog?["pins"] as? [[String: Any]] ?? []
        for key in defaults.keys where key.hasPrefix("chart.snapshot.") {
          let id = String(key.dropFirst("chart.snapshot.".count))
          if !pins.contains(where: { $0["id"] as? String == id && $0["eligible"] as? Bool == true })
          {
            defaults.removeObject(forKey: key)
          }
        }
        for pin in pins {
          guard let id = pin["id"] as? String else { continue }
          let previous = oldPins.first { $0["id"] as? String == id }
          let changed =
            String(describing: old?["host"]) != String(describing: catalog?["host"])
            || String(describing: old?["projectId"]) != String(describing: catalog?["projectId"])
            || ["insightId", "shortId", "dashboardId", "displayMode"].contains {
              String(describing: pin[$0]) != String(describing: previous?[$0])
            }
          let key = "chart.snapshot.\(id)"
          if changed {
            defaults.removeObject(forKey: key)
            defaults.removeObject(forKey: "chart.snapshotError.\(id)")
          }
          if pin["eligible"] as? Bool == true, let snapshot = pin["snapshot"] as? [String: Any],
            let at = snapshot["fetchedAt"] as? Double
          {
            let cached = defaults.string(forKey: key).flatMap {
              (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
            }
            if at >= (cached?["fetchedAt"] as? Double ?? 0),
              let data = try? JSONSerialization.data(withJSONObject: snapshot),
              let value = String(data: data, encoding: .utf8)
            {
              defaults.set(value, forKey: key)
              defaults.removeObject(forKey: "chart.snapshotError.\(id)")
            }
          }
        }
        var metadata = catalog ?? [:]
        metadata["pins"] = pins.map { pin in pin.filter { $0.key != "snapshot" } }
        if let data = try? JSONSerialization.data(withJSONObject: metadata),
          let value = String(data: data, encoding: .utf8)
        {
          defaults.set(value, forKey: catalogKey)
        }
      }
      WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
    }

    Function("clearCatalog") {
      ChartStore.storage?.removeObject(forKey: catalogKey)
      removeSnapshots()
      WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
    }

    Function("reloadWidgets") {
      WidgetCenter.shared.reloadTimelines(ofKind: widgetKind)
    }
  }
}
