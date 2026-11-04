import Foundation
import WidgetKit

struct ChartEntry: TimelineEntry {
    let date: Date
    let content: ChartContent
}

struct ChartTimelineProvider: AppIntentTimelineProvider {
    /// The second entry only moves the age label on; it reads nothing.
    private static let ageStep: TimeInterval = 15 * 60
    private static let reloadAfter: TimeInterval = 30 * 60

    func placeholder(in context: Context) -> ChartEntry {
        let now = Date()
        return ChartEntry(date: now, content: ChartSample.content(family: Self.family(context), now: now))
    }

    func snapshot(for configuration: ChartWidgetIntent, in context: Context) async -> ChartEntry {
        let now = Date()
        if context.isPreview {
            return ChartEntry(date: now, content: ChartSample.content(family: Self.family(context), now: now))
        }
        return ChartEntry(date: now, content: Self.content(configuration, family: Self.family(context), store: Self.storeState(), now: now))
    }

    func timeline(for configuration: ChartWidgetIntent, in context: Context) async -> Timeline<ChartEntry> {
        let now = Date()
        let family = Self.family(context)
        let (primary, extras) = Self.selections(configuration, family: family)
        let before = Self.storeState()
        for marker in ChartResolver.pinProjects([primary].compactMap { $0 } + extras, catalog: before.catalog) {
            ChartStore.save(marker.project, pinId: marker.pinId)
        }
        if let credentials = before.credentials {
            let pins = ChartResolver.pinsToFetch([primary].compactMap { $0 } + extras, store: before, now: now)
            await withTaskGroup(of: Void.self) { group in
                for pin in pins {
                    group.addTask { await ChartRefresh.shared.refresh(pin, credentials: credentials, now: now) }
                }
            }
        }
        let content = Self.content(configuration, family: family, store: Self.storeState(), now: now)
        let entries = [now, now.addingTimeInterval(Self.ageStep)].map { ChartEntry(date: $0, content: content) }
        return Timeline(entries: entries, policy: .after(now.addingTimeInterval(Self.reloadAfter)))
    }

    private static func family(_ context: Context) -> ChartFamily {
        switch context.family {
        case .systemSmall: .small
        case .systemLarge, .systemExtraLarge: .large
        default: .medium
        }
    }

    private static func selections(_ configuration: ChartWidgetIntent, family: ChartFamily) -> (ChartSelection?, [ChartSelection]) {
        let primary = configuration.pin.map { ChartSelection(id: $0.id, name: $0.name) }
        let extras = (configuration.extraPins ?? []).map { ChartSelection(id: $0.id, name: $0.name) }
        return ChartResolver.selections(primary: primary, extras: extras, family: family)
    }

    private static func storeState() -> ChartStoreState {
        let defaults = ChartStore.defaults
        return ChartStoreState(
            credentials: ChartStore.credentials(),
            catalog: ChartStore.catalog(store: defaults),
            snapshot: { ChartStore.snapshot(pinId: $0, store: defaults) },
            error: { ChartStore.error(pinId: $0, store: defaults) },
            pinProject: { ChartStore.pinProject(pinId: $0, store: defaults) }
        )
    }

    private static func content(_ configuration: ChartWidgetIntent, family: ChartFamily, store: ChartStoreState, now: Date) -> ChartContent {
        let (primary, extras) = selections(configuration, family: family)
        let links = ChartLinks(scheme: ChartLinks.scheme(forAppId: AppGroup.appId), family: family)
        return ChartResolver.content(primary: primary, extras: extras, store: store, links: links, now: now)
    }
}
