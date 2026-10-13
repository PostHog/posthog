import AppIntents
import Foundation

struct PokeHedgehogIntent: AppIntent {
    static let title: LocalizedStringResource = "Poke the hedgehog"
    // The intent only makes sense from the widget, so keep it out of Shortcuts and Spotlight.
    static let isDiscoverable = false

    // Each widget family keeps its own poke, so tapping the small widget does not make the medium one react.
    @Parameter(title: "Widget family")
    var family: String

    init() {}

    init(family: String) {
        self.family = family
    }

    func perform() async throws -> some IntentResult {
        SharedStore.defaults?.set(Date().timeIntervalSince1970, forKey: SharedStore.pokedAtKey(family: family))
        return .result()
    }
}
