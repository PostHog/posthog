import AppIntents
import WidgetKit

/// A pin from the catalog the app writes (`chart.catalog`). The configuration stores its id.
@available(iOS 17.0, *)
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

@available(iOS 17.0, *)
struct PinQuery: EntityStringQuery {
    private var pickerPins: [PinEntity] {
        (ChartStore.catalog()?.pins ?? []).map { pin in
            PinEntity(id: pin.id, name: pin.name, subtitle: pin.eligible ? pin.subtitle : pin.reason)
        }
    }

    /// A stored id that left the catalog still resolves, so the widget can say the pin is gone instead of
    /// asking to choose one.
    func entities(for identifiers: [PinEntity.ID]) async throws -> [PinEntity] {
        let catalog = ChartStore.catalog()
        return identifiers.map { id in
            catalog?.pin(id: id).map(PinEntity.init(pin:))
                ?? PinEntity(id: id, name: "This pin", subtitle: nil)
        }
    }

    func entities(matching string: String) async throws -> [PinEntity] {
        pickerPins.filter {
            string.isEmpty || $0.name.localizedCaseInsensitiveContains(string)
                || ($0.subtitle?.localizedCaseInsensitiveContains(string) ?? false)
        }
    }

    func suggestedEntities() async throws -> [PinEntity] {
        pickerPins
    }

    func defaultResult() async -> PinEntity? {
        ChartStore.catalog()?.pickerPins.first.map(PinEntity.init(pin:))
    }
}

@available(iOS 17.0, *)
struct ChartWidgetIntent: WidgetConfigurationIntent {
    static var title: LocalizedStringResource { "Chart" }
    static var description: IntentDescription {
        "Shows your first pinned view. Choose a different pin below."
    }

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

@available(iOS 17.0, *)
func chartWidgetState() async throws -> [String: Any] {
    let infos = try await withCheckedThrowingContinuation {
        (continuation: CheckedContinuation<[WidgetInfo], Error>) in
        WidgetCenter.shared.getCurrentConfigurations { continuation.resume(with: $0) }
    }.filter { $0.kind == "ChartWidget" }
    var ids = Set<String>()
    var usesDefault = false
    if #available(iOS 17.0, *) {
        for info in infos {
            if let intent = info.widgetConfigurationIntent(of: ChartWidgetIntent.self) {
                if let pin = intent.pin { ids.insert(pin.id) } else { usesDefault = true }
                if info.family == .systemLarge {
                    ids.formUnion((intent.extraPins ?? []).prefix(2).map(\.id))
                }
            } else {
                usesDefault = true
            }
        }
    }
    if usesDefault, let pin = ChartStore.catalog()?.pickerPins.first { ids.insert(pin.id) }
    ChartStore.retainSnapshots(ids)
    if infos.isEmpty { _ = ChartStore.clearCredentials() }
    return ["installed": !infos.isEmpty, "pinIds": Array(ids), "usesDefault": usesDefault]
}
