import Foundation

// What each chart widget shows, decided from the store without WidgetKit, so scripts/check_chart_widget.swift can run it.

enum ChartFamily: String {
    case small, medium, large
}

struct ChartSelection: Equatable {
    let id: String
    let name: String
}

struct ChartSlot: Equatable {
    enum State: Equatable {
        case ready(ChartSnapshot)
        case loading
        case message(String, detail: String?)
    }

    /// The pin's name, when it is known and the message does not already say it.
    let title: String?
    let state: State
    let link: URL

    var snapshot: ChartSnapshot? {
        if case .ready(let snapshot) = state {
            return snapshot
        }
        return nil
    }
}

struct ChartContent: Equatable {
    let primary: ChartSlot
    let extras: [ChartSlot]

    /// The oldest data on screen, so the one age label is true for every number (`statusLine` in freshness.ts).
    var oldestData: Date? {
        ([primary] + extras).compactMap { $0.snapshot?.dataDate }.min()
    }
}

/// Deep links into the app's Views routes (docs/VIEWS.md "Routes").
struct ChartLinks {
    let scheme: String
    let family: ChartFamily

    /// `scheme` per app id in src/lib/appVariants.json: the store app id plus the variant's `idSuffix`.
    private static let schemes: [(suffix: String, scheme: String)] = [
        (".dev", "posthog-dev"),
        (".preview", "posthog-preview"),
    ]

    static func scheme(forAppId appId: String) -> String {
        schemes.first { appId.hasSuffix($0.suffix) }?.scheme ?? "posthog"
    }

    var root: URL {
        URL(string: "\(scheme)://views")!
    }

    func pin(_ pin: ChartPin) -> URL {
        let query = "from=widget&family=\(family.rawValue)"
        if pin.isDashboard, let dashboardId = pin.dashboardId {
            return URL(string: "\(scheme)://views/dashboard/\(dashboardId)?\(query)") ?? root
        }
        if let shortId = pin.shortId?.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed), !shortId.isEmpty {
            return URL(string: "\(scheme)://views/insight/\(shortId)?\(query)") ?? root
        }
        return root
    }
}

struct ChartStoreState {
    let credentials: ChartCredentials?
    let catalog: ChartCatalog?
    let snapshot: (String) -> ChartSnapshot?
    let error: (String) -> ChartSnapshotError?
    let pinProject: (String) -> ChartPinProject?
}

enum ChartResolver {
    /// A pin read in the last 5 minutes is not read again, so widgets that show the same pin share one request. The
    /// same floor as an automatic read in Views (docs/VIEWS.md "Refresh").
    static let shareWindow: TimeInterval = 5 * 60
    static let rateLimitPause: TimeInterval = 60

    static let signedOut = ChartSlot.State.message("Sign in to see your pins", detail: "Open PostHog to sign in")
    static let reauthenticate = ChartSlot.State.message("Open PostHog to update", detail: nil)
    static let notConfigured = ChartSlot.State.message("No pinned views available", detail: "Open Views to pin an insight or choose a dashboard tile")
    static let noResult = ChartSlot.State.message("Open it in PostHog to load this insight", detail: nil)

    static func selections(primary: ChartSelection?, extras: [ChartSelection], family: ChartFamily, catalog: ChartCatalog? = nil) -> (ChartSelection?, [ChartSelection]) {
        let primary = primary ?? catalog?.pickerPins.first.map { ChartSelection(id: $0.id, name: $0.name) }
        guard family == .large else { return (primary, []) }
        var seen = Set(primary.map { [$0.id] } ?? [])
        var unique: [ChartSelection] = []
        for extra in extras where !seen.contains(extra.id) {
            seen.insert(extra.id)
            unique.append(extra)
        }
        return (primary, Array(unique.prefix(2)))
    }

    static func needsFetch(snapshot: ChartSnapshot?, error: ChartSnapshotError?, catalog: ChartCatalog, now: Date) -> Bool {
        let nowMs = now.timeIntervalSince1970 * 1000
        if let error {
            return !(error.kind == .rateLimited && nowMs - error.at < rateLimitPause * 1000)
        }
        guard let snapshot else { return true }
        // A catalog written after the read can point the pin at another tile.
        return nowMs - snapshot.fetchedAt >= shareWindow * 1000 || snapshot.fetchedAt < catalog.writtenAt
    }

    static func pinProjects(_ selections: [ChartSelection], catalog: ChartCatalog?) -> [(pinId: String, project: ChartPinProject)] {
        guard let catalog else { return [] }
        let project = ChartPinProject(projectId: catalog.projectId, projectName: catalog.projectName)
        return selections.filter { catalog.pin(id: $0.id) != nil }.map { ($0.id, project) }
    }

    static func pinsToFetch(_ selections: [ChartSelection], store: ChartStoreState, now: Date) -> [ChartPin] {
        guard let credentials = store.credentials, !credentials.isExpired(at: now),
              let catalog = store.catalog, catalog.belongs(to: credentials)
        else {
            return []
        }
        var seen = Set<String>()
        var pins: [ChartPin] = []
        for selection in selections where !seen.contains(selection.id) {
            seen.insert(selection.id)
            guard let pin = catalog.pin(id: selection.id), pin.eligible, pin.insightId != nil || pin.shortId != nil,
                  needsFetch(snapshot: store.snapshot(pin.id), error: store.error(pin.id), catalog: catalog, now: now)
            else {
                continue
            }
            pins.append(pin)
        }
        return pins
    }

    static func content(
        primary: ChartSelection?, extras: [ChartSelection], store: ChartStoreState, links: ChartLinks, now: Date
    ) -> ChartContent {
        guard let credentials = store.credentials else {
            return ChartContent(primary: ChartSlot(title: nil, state: signedOut, link: links.root), extras: [])
        }
        if credentials.isExpired(at: now) {
            return ChartContent(primary: ChartSlot(title: primary?.name, state: reauthenticate, link: links.root), extras: [])
        }
        let (primary, extras) = selections(
            primary: primary, extras: extras, family: links.family,
            catalog: store.catalog.flatMap { $0.belongs(to: credentials) ? $0 : nil }
        )
        return ChartContent(
            primary: slot(primary, credentials: credentials, store: store, links: links),
            extras: extras.map { slot($0, credentials: credentials, store: store, links: links) }
        )
    }

    static func slot(
        _ selection: ChartSelection?, credentials: ChartCredentials, store: ChartStoreState, links: ChartLinks
    ) -> ChartSlot {
        guard let selection else {
            if store.catalog == nil {
                return ChartSlot(title: nil, state: .message("Open PostHog to load your pins", detail: nil), link: links.root)
            }
            return ChartSlot(title: nil, state: notConfigured, link: links.root)
        }
        // The app writes the catalog after its first pin list read.
        guard let catalog = store.catalog else {
            return ChartSlot(title: selection.name, state: .loading, link: links.root)
        }
        guard let pin = catalog.pin(id: selection.id) else {
            if let project = store.pinProject(selection.id), project.projectId != credentials.projectId {
                return otherProject(title: selection.name, projectName: project.projectName, links: links)
            }
            return ChartSlot(title: nil, state: .message("\(selection.name) is no longer pinned", detail: nil), link: links.root)
        }
        guard catalog.belongs(to: credentials) else {
            return otherProject(title: pin.name, projectName: catalog.projectName, links: links)
        }
        guard pin.eligible else {
            return ChartSlot(
                title: pin.name, state: .message(pin.reason ?? "Not supported on the widget yet", detail: nil), link: links.root
            )
        }
        let error = store.error(pin.id)
        switch error?.kind {
        case .auth:
            return ChartSlot(title: pin.name, state: reauthenticate, link: links.root)
        case .notFound:
            return ChartSlot(
                title: nil,
                state: .message("\(pin.name) was unpinned or deleted. Touch and hold to pick another.", detail: nil),
                link: links.root
            )
        default:
            break
        }
        if let snapshot = store.snapshot(pin.id) {
            return ChartSlot(title: pin.name, state: .ready(snapshot), link: links.pin(pin))
        }
        if let error {
            // Opening the insight in the app computes it; the widget then reads the result.
            return ChartSlot(title: pin.name, state: failure(error.kind), link: error.kind == .noResult ? links.pin(pin) : links.root)
        }
        return ChartSlot(title: pin.name, state: .loading, link: links.pin(pin))
    }

    private static func otherProject(title: String, projectName: String?, links: ChartLinks) -> ChartSlot {
        ChartSlot(
            title: title,
            state: .message("In another project", detail: "Switch to \(projectName ?? "that project") in PostHog"),
            link: links.root
        )
    }

    static func failure(_ kind: ChartErrorKind) -> ChartSlot.State {
        switch kind {
        case .badData:
            return .message("Can't show this insight here", detail: nil)
        case .auth:
            return reauthenticate
        case .notFound:
            return .message("Not found", detail: nil)
        case .network, .rateLimited:
            return .message("Couldn't refresh", detail: "Trying again soon")
        case .noResult:
            return noResult
        }
    }
}

extension ChartSnapshot {
    var dataDate: Date {
        if let lastRefreshAt, let computed = ChartDates.parse(lastRefreshAt) {
            return computed
        }
        return Date(timeIntervalSince1970: fetchedAt / 1000)
    }

    var interval: TrendsParser.Interval {
        TrendsParser.Interval.of(intervalLabel)
    }

    var currentSeries: [ChartSeries] { series.filter { !$0.previous } }

    var hasPoints: Bool {
        currentSeries.contains { series in series.points.contains { $0.value != nil } }
    }

    var pillText: String? {
        guard let deltaText else { return nil }
        guard let deltaPercent, deltaPercent != 0 else { return deltaText }
        return "\(deltaPercent > 0 ? "▲" : "▼") \(deltaText)"
    }

    func trimmed(to limit: Int) -> [ChartSeries] {
        series.map { ChartSeries(label: $0.label, points: Array($0.points.suffix(limit)), previous: $0.previous) }
    }

    func axisLabels(limit: Int) -> (String, String)? {
        guard let points = currentSeries.first?.points.suffix(limit), let first = points.first, let last = points.last,
              let start = ChartDates.bucketStart(first.at), let end = ChartDates.bucketStart(last.at)
        else {
            return nil
        }
        return (ChartDates.axisLabel(start, interval: interval), ChartDates.axisLabel(end, interval: interval))
    }
}

enum ChartAge {
    static let staleAfter: TimeInterval = 60 * 60

    /// `statusLine` in src/features/views/freshness.ts.
    static func text(dataDate: Date, at now: Date) -> String {
        let age = max(0, now.timeIntervalSince(dataDate))
        if age < 60 {
            return "Updated just now"
        }
        let minutes = max(1, Int(age / 60))
        if minutes < 60 {
            return "Updated \(minutes) min ago"
        }
        let hours = minutes / 60
        if hours < 24 {
            return "Updated \(hours) h ago"
        }
        let days = hours / 24
        return days == 1 ? "Updated 1 day ago" : "Updated \(days) days ago"
    }

    static func isStale(dataDate: Date, at now: Date) -> Bool {
        now.timeIntervalSince(dataDate) > staleAfter
    }
}

/// The gallery's preview: made-up numbers, never a user's.
enum ChartSample {
    static func snapshot(
        pinId: String, value: String, delta: Double, deltaText: String, values: [Double], now: Date
    ) -> ChartSnapshot {
        let calendar = Calendar(identifier: .gregorian)
        let days = values.indices.map { index in
            ChartDates.dayLabel(calendar.date(byAdding: .day, value: index - values.count + 1, to: now) ?? now)
        }
        let previous = values.map { ($0 * 0.88).rounded() }
        let computed = now.addingTimeInterval(-12 * 60)
        return ChartSnapshot(
            version: ChartSnapshot.supportedVersion,
            pinId: pinId,
            fetchedAt: (now.timeIntervalSince1970 * 1000).rounded(),
            lastRefreshAt: ISO8601DateFormatter().string(from: computed),
            rangeLabel: "Last 14 days",
            intervalLabel: "day",
            valueText: value,
            deltaPercent: delta,
            deltaText: deltaText,
            deltaBasis: "vs previous period",
            series: [
                ChartSeries(label: "Sample", points: zip(days, values).map { ChartPoint(at: $0, value: $1) }, previous: false),
                ChartSeries(label: "Previous period", points: zip(days, previous).map { ChartPoint(at: $0, value: $1) }, previous: true),
            ],
            chartKind: .line
        )
    }

    static func content(family: ChartFamily, now: Date) -> ChartContent {
        let links = ChartLinks(scheme: "posthog", family: family)
        let signups = snapshot(
            pinId: "sample-signups", value: "1,284", delta: 12, deltaText: "12%",
            values: [72, 80, 77, 85, 91, 88, 79, 94, 98, 90, 101, 97, 108, 124], now: now
        )
        let primary = ChartSlot(title: "Signups", state: .ready(signups), link: links.root)
        guard family == .large else { return ChartContent(primary: primary, extras: []) }
        let active = snapshot(
            pinId: "sample-active", value: "342", delta: 4.1, deltaText: "4.1%",
            values: [310, 322, 318, 330, 326, 335, 329, 338, 331, 340, 336, 344, 339, 342], now: now
        )
        let pageviews = snapshot(
            pinId: "sample-pageviews", value: "18,902", delta: -3.2, deltaText: "3.2%",
            values: [19800, 19650, 19900, 19500, 19620, 19400, 19300, 19450, 19200, 19100, 19250, 19000, 18950, 18902], now: now
        )
        return ChartContent(primary: primary, extras: [
            ChartSlot(title: "Daily active users", state: .ready(active), link: links.root),
            ChartSlot(title: "Pageviews", state: .ready(pageviews), link: links.root),
        ])
    }
}
