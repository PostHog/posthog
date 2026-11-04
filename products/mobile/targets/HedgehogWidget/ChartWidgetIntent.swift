import AppIntents
import WidgetKit

/// A pin from the catalog the app writes (`chart.catalog`). The configuration stores its id.
struct PinEntity: AppEntity {
    static var typeDisplayRepresentation: TypeDisplayRepresentation { "Pin" }
    static var defaultQuery: PinQuery { PinQuery() }

    let id: String
    let name: String
    let subtitle: String?

    init(id: String, name: String, subtitle: String?) {
        self.id = id
        self.name = name
        self.subtitle = subtitle
    }

    init(pin: ChartPin) {
        self.init(id: pin.id, name: pin.name, subtitle: pin.subtitle)
    }

    var displayRepresentation: DisplayRepresentation {
        guard let subtitle, !subtitle.isEmpty else {
            return DisplayRepresentation(title: "\(name)")
        }
        return DisplayRepresentation(title: "\(name)", subtitle: "\(subtitle)")
    }
}

struct PinQuery: EntityStringQuery {
    private var pickerPins: [PinEntity] {
        (ChartStore.catalog()?.pickerPins ?? []).map(PinEntity.init(pin:))
    }

    /// A stored id that left the catalog still resolves, so the widget can say the pin is gone instead of
    /// asking to choose one.
    func entities(for identifiers: [PinEntity.ID]) async throws -> [PinEntity] {
        let catalog = ChartStore.catalog()
        return identifiers.map { id in
            catalog?.pin(id: id).map(PinEntity.init(pin:)) ?? PinEntity(id: id, name: "This pin", subtitle: nil)
        }
    }

    func entities(matching string: String) async throws -> [PinEntity] {
        pickerPins.filter {
            $0.name.localizedCaseInsensitiveContains(string) || ($0.subtitle?.localizedCaseInsensitiveContains(string) ?? false)
        }
    }

    func suggestedEntities() async throws -> [PinEntity] {
        pickerPins
    }

    func defaultResult() async -> PinEntity? {
        pickerPins.first
    }
}

struct ChartWidgetIntent: WidgetConfigurationIntent {
    static var title: LocalizedStringResource { "Chart" }
    static var description: IntentDescription { "Choose a pin from your Views tab." }

    @Parameter(title: "Pin")
    var pin: PinEntity?

    @Parameter(title: "More pins", description: "Shown on the large widget")
    var extraPins: [PinEntity]?

    // Only the large widget draws the extra pins, so the other sizes do not ask for them.
    static var parameterSummary: some ParameterSummary {
        When(widgetFamily: .equalTo, .systemLarge) {
            Summary {
                \.$pin
                \.$extraPins
            }
        } otherwise: {
            Summary {
                \.$pin
            }
        }
    }
}
