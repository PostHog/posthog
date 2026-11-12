import CryptoKit
import Foundation
import Security

final class ChartStorage {
    private let defaults: UserDefaults
    private let key: SymmetricKey?

    init(defaults: UserDefaults, key: SymmetricKey? = ChartStorage.loadKey()) {
        self.defaults = defaults
        self.key = key
        for name in defaults.dictionaryRepresentation().keys where name.hasPrefix("chart.") {
            if defaults.object(forKey: name) is String {
                defaults.removeObject(forKey: name)
            }
        }
    }

    var keys: [String] { Array(defaults.dictionaryRepresentation().keys) }

    func string(forKey name: String) -> String? {
        guard let key, let data = defaults.data(forKey: name),
            let box = try? AES.GCM.SealedBox(combined: data),
            let clear = try? AES.GCM.open(box, using: key, authenticating: Data(name.utf8))
        else { return nil }
        return String(data: clear, encoding: .utf8)
    }

    func set(_ value: String, forKey name: String) {
        guard let key,
            let box = try? AES.GCM.seal(Data(value.utf8), using: key, authenticating: Data(name.utf8)),
            let data = box.combined
        else { return }
        defaults.set(data, forKey: name)
    }

    func removeObject(forKey name: String) {
        defaults.removeObject(forKey: name)
    }

    private static func loadKey() -> SymmetricKey? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.posthog.code.mobile.chart-widget",
            kSecAttrAccount as String: "data-key",
            kSecAttrAccessGroup as String: AppGroup.suiteName,
        ]
        func read() -> SymmetricKey? {
            var result: CFTypeRef?
            let search = query.merging([
                kSecReturnData as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
            ]) { _, new in new }
            guard SecItemCopyMatching(search as CFDictionary, &result) == errSecSuccess,
                let data = result as? Data, data.count == 32
            else { return nil }
            return SymmetricKey(data: data)
        }
        if let key = read() { return key }
        let key = SymmetricKey(size: .bits256)
        let item = query.merging([
            kSecValueData as String: key.withUnsafeBytes { Data($0) },
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]) { _, new in new }
        let status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem { return read() }
        return status == errSecSuccess ? key : nil
    }
}
