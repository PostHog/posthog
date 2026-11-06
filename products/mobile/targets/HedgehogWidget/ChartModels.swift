import Foundation

// The JSON shapes of the chart widget's shared store, as modules/chart-widget/README.md describes them. The app's
// JavaScript writes the catalog and the credentials and the Android widget writes the same snapshot shape, so a change
// here needs the same change on both sides.

struct ChartCredentials: Codable, Equatable, Sendable {
    static let supportedVersion = 1

    let version: Int
    let host: String
    let projectId: Int
    let projectName: String?
    let accessToken: String
    /// Epoch ms. Nil for a personal API key, which never expires.
    let expiresAt: Double?
    let userUuid: String?

    /// A minute of slack, so the token cannot expire between this check and the server reading it.
    func isExpired(at now: Date) -> Bool {
        guard let expiresAt else { return false }
        return now.timeIntervalSince1970 * 1000 > expiresAt - 60_000
    }
}

struct ChartPin: Codable, Equatable, Identifiable, Sendable {
    /// The pin's shortcut id. The widget configuration stores it.
    let id: String
    /// "insight" or "dashboard".
    let kind: String
    let name: String
    let subtitle: String?
    /// Nil until the app has read the insight; the widget then reads by `shortId`.
    let insightId: Int?
    let shortId: String?
    let dashboardId: Int?
    let eligible: Bool
    let number: Bool
    let chart: Bool
    let reason: String?

    var displayMode: String? = nil

    var isDashboard: Bool { kind == "dashboard" }
}

struct ChartCatalog: Codable, Equatable, Sendable {
    static let supportedVersion = 1

    let version: Int
    let host: String
    let projectId: Int
    let projectName: String?
    /// Epoch ms.
    let writtenAt: Double
    /// In Views order.
    let pins: [ChartPin]

    var pickerPins: [ChartPin] { pins.filter(\.eligible) }

    func pin(id: String) -> ChartPin? {
        pins.first { $0.id == id }
    }

    /// The token reads one project on one host; a catalog of another project needs the app to switch first.
    func belongs(to credentials: ChartCredentials) -> Bool {
        projectId == credentials.projectId && Self.normalized(host) == Self.normalized(credentials.host)
    }

    private static func normalized(_ host: String) -> String {
        let lowered = host.lowercased()
        return lowered.hasSuffix("/") ? String(lowered.dropLast()) : lowered
    }
}

enum ChartKind: String, Codable, Sendable {
    case line, bar
}

struct ChartPoint: Codable, Equatable, Sendable {
    /// The server's bucket label, such as "2026-10-22".
    let at: String
    /// Nil for a bucket without a number, because JSON has no NaN.
    let value: Double?
}

struct ChartSeries: Codable, Equatable, Sendable {
    let label: String
    let points: [ChartPoint]
    let previous: Bool
}

struct ChartRow: Codable, Equatable, Sendable {
    let label: String
    let value: String
}

struct ChartSnapshot: Codable, Equatable, Sendable {
    static let supportedVersion = 1

    let version: Int
    let pinId: String
    /// Epoch ms of the read that wrote this snapshot.
    let fetchedAt: Double
    let lastRefreshAt: String?
    var rangeLabel: String?
    /// The trends interval: "hour", "day", "week" or "month".
    var intervalLabel: String
    /// Nil when the insight has no single number, such as two series.
    var valueText: String?
    /// The signed change that sets the pill's direction: percent, or points for a percentage insight.
    let deltaPercent: Double?
    let deltaText: String?
    let deltaBasis: String?
    /// Up to five current series, then the previous-period series of those. Up to 60 points each.
    var series: [ChartSeries]
    var chartKind: ChartKind
    var chartValueText: String? = nil
    var axisLowText: String? = nil
    var axisHighText: String? = nil
    var display: String? = nil
    var rows: [ChartRow]? = nil
}

enum ChartErrorKind: String, Codable, Sendable {
    case network
    case auth
    case notFound = "not_found"
    case rateLimited = "rate_limited"
    case badData = "bad_data"
    /// A 200 without a result: the server has not computed the insight, and the widget never asks it to.
    case noResult = "no_result"
}

struct ChartSnapshotError: Codable, Equatable, Sendable {
    /// Epoch ms.
    let at: Double
    let kind: ChartErrorKind
}

/// The project a pin last appeared in (`chart.pinProject.<pinId>`). After a project switch the new catalog no longer
/// lists the pin, and this tells "in another project" apart from "unpinned".
struct ChartPinProject: Codable, Equatable, Sendable {
    let projectId: Int
    let projectName: String?
}
