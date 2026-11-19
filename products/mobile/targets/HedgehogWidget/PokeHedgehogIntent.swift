import AppIntents
import Foundation

struct PokeHedgehogIntent: AppIntent {
    static let title: LocalizedStringResource = "Change hedgehog"
    // The intent only makes sense from the widget, so keep it out of Shortcuts and Spotlight.
    static let isDiscoverable = false

    @Parameter(title: "Widget family")
    var family: String

    init() {}

    init(family: String) {
        self.family = family
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        let character = HogSelection.next(after: HogSelection.selected(family: family))
        SharedStore.defaults?.set(character, forKey: SharedStore.selectedHogKey(family: family))
        return .result()
    }
}
