import Foundation

// Mirrors the app's trends adapter, so a pin shows the same number on the widget as in Views:
// - src/model/adapters/insightSnapshot.ts: trendsEntries, seriesViews, pointsOf, compareOf, capabilitiesOf, numberParts,
//   inProgressFrom;
// - src/model/adapters/insightFormatting.ts: insightValueFormat, formatInsightValue;
// - src/features/views/snapshotChart.ts: snapshotChartSeries, deltaBasisText, resolvedRangeText, pinRangeLabel;
// - src/features/views/rangePresets.ts: RANGE_PRESETS, rangeLabel, formatRangeSpan.
// A change to one of those needs the same change here and in the Android widget.

typealias JSONObject = [String: Any]

enum TrendsParser {
    enum Failure: Error, Equatable {
        case notJSON, notTrends, noResult
    }

    static let pointLimit = 60
    static let seriesLimit = 5

    enum Interval: String {
        case hour, day, week, month

        static func of(_ value: Any?) -> Interval {
            (value as? String).flatMap(Interval.init(rawValue:)) ?? .day
        }

        var length: TimeInterval {
            switch self {
            case .hour: 3600
            case .day: 86400
            case .week: 7 * 86400
            case .month: 31 * 86400
            }
        }
    }

    struct Point {
        let at: String
        /// NaN for a bucket without a number.
        let value: Double
    }

    enum Compare {
        case current, previous
    }

    indirect enum Breakdown: Equatable {
        case none
        case text(String)
        case number(Double)
        case list([Breakdown])
    }

    struct SeriesView {
        let label: String
        let points: [Point]
        let compare: Compare?
        let seriesIndex: Double
        let breakdown: Breakdown
    }

    struct ValueFormat: Equatable {
        var style: String? = nil
        var prefix = ""
        var suffix = ""
        var decimalPlaces: Int? = nil
        var minDecimalPlaces: Int? = nil
    }

    enum DeltaBasis {
        case compare, previousBucket
    }

    enum DeltaUnit {
        case percent, points
    }

    struct Delta {
        let previous: Double
        let change: Double
        let percent: Double?
        let unit: DeltaUnit
        let basis: DeltaBasis
        let previousAt: String?
    }

    struct NumberParts {
        let value: Double
        let valueAt: String?
        let delta: Delta?
    }

    struct ResolvedRange {
        let from: String
        let to: String
    }

    static func snapshot(data: Data, pinId: String, now: Date) throws -> ChartSnapshot {
        guard let response = (try? JSONSerialization.jsonObject(with: data)) as? JSONObject else {
            throw Failure.notJSON
        }
        return try snapshot(response: response, pinId: pinId, now: now)
    }

    /// The snapshot of one good insight response: a `result` and no `query_status.error`, which the caller checks.
    static func snapshot(response: JSONObject, pinId: String, now: Date) throws -> ChartSnapshot {
        let query = response["query"]
        guard let source = sourceOf(query), source["kind"] as? String == "TrendsQuery" else {
            throw Failure.notTrends
        }
        guard let result = response["result"] as? [Any] else {
            throw Failure.noResult
        }
        let entries = result.compactMap { $0 as? JSONObject }
        let views = seriesViews(entries)
        let interval = Interval.of(source["interval"])
        let format = valueFormat(source: source)
        let resolved = resolvedRange(response)
        let firstCurrent = views.first { $0.compare != .previous }
        let inProgress = firstCurrent.flatMap { inProgressFrom($0.points, resolved: resolved, interval: interval, now: now) }
        let number = hasNumber(query: query, source: source, entries: entries)
            ? numberParts(source: source, entries: entries, format: format, inProgressAt: inProgress)
            : nil
        let delta = number?.delta.flatMap { deltaFields($0, interval: interval) }
        return ChartSnapshot(
            version: ChartSnapshot.supportedVersion,
            pinId: pinId,
            fetchedAt: (now.timeIntervalSince1970 * 1000).rounded(),
            lastRefreshAt: response["last_refresh"] as? String,
            rangeLabel: rangeLabel(source: source, resolved: resolved, interval: interval),
            intervalLabel: interval.rawValue,
            valueText: number.map { formatValue($0.value, format) },
            deltaPercent: delta?.percent,
            deltaText: delta?.text,
            deltaBasis: delta?.basis,
            series: chartSeries(views),
            chartKind: chartKind(query: query)
        )
    }

    static func sourceOf(_ query: Any?) -> JSONObject? {
        let node = query as? JSONObject
        return (node?["source"] as? JSONObject) ?? node
    }

    static func displayOf(_ query: Any?) -> String? {
        let display = (sourceOf(query)?["trendsFilter"] as? JSONObject)?["display"] ?? (query as? JSONObject)?["display"]
        return display as? String
    }

    private static let barDisplays: Set<String> = ["ActionsBar", "ActionsStackedBar", "ActionsUnstackedBar"]

    static func chartKind(query: Any?) -> ChartKind {
        displayOf(query).map(barDisplays.contains) == true ? .bar : .line
    }

    static func seriesNodes(_ source: JSONObject) -> [JSONObject] {
        (source["series"] as? [Any])?.compactMap { $0 as? JSONObject } ?? []
    }

    static func hasBreakdown(_ source: JSONObject) -> Bool {
        let filter = source["breakdownFilter"] as? JSONObject
        return isTruthy(filter?["breakdown"]) || (filter?["breakdowns"] as? [Any])?.isEmpty == false
    }

    /// `capabilitiesOf(...).number`: a big number, or one series or one result without a breakdown. With several series
    /// the first one would stand for the whole insight.
    static func hasNumber(query: Any?, source: JSONObject, entries: [JSONObject]) -> Bool {
        if displayOf(query) == "BoldNumber" {
            return true
        }
        let current = entries.filter { compareOf($0) != .previous }
        return !hasBreakdown(source) && (seriesNodes(source).count == 1 || current.count == 1)
    }

    // Distinct-user math counts a person once per bucket, so only these maths add up over a window.
    private static let summableMath: Set<String> = ["total", "sum", "first_time_for_user", "first_matching_event_for_user"]

    static func isSummable(_ source: JSONObject) -> Bool {
        let math = seriesNodes(source).first?["math"]
        if math == nil || math is NSNull {
            return true
        }
        return (math as? String).map(summableMath.contains) ?? false
    }

    static func resolvedRange(_ response: JSONObject) -> ResolvedRange? {
        let range = response["resolved_date_range"] as? JSONObject
        guard let from = range?["date_from"] as? String, let to = range?["date_to"] as? String,
              !from.isEmpty, !to.isEmpty
        else {
            return nil
        }
        return ResolvedRange(from: from, to: to)
    }

    static func compareOf(_ entry: JSONObject) -> Compare? {
        switch entry["compare_label"] as? String {
        case "previous": .previous
        case "current": .current
        default: nil
        }
    }

    static func seriesIndexOf(_ entry: JSONObject, fallback: Double) -> Double {
        finite((entry["action"] as? JSONObject)?["order"]) ?? fallback
    }

    static func breakdownOf(_ entry: JSONObject) -> Breakdown {
        let value = entry["breakdown_value"]
        if let parts = value as? [Any] {
            var list: [Breakdown] = []
            for part in parts {
                if part is NSNull {
                    list.append(.none)
                } else if let text = part as? String {
                    list.append(.text(text))
                } else if let number = finite(part) {
                    list.append(.number(number))
                } else {
                    return .none
                }
            }
            return .list(list)
        }
        if let text = value as? String {
            return .text(text)
        }
        return finite(value).map(Breakdown.number) ?? .none
    }

    static func pointsOf(_ entry: JSONObject?) -> [Point] {
        guard let entry, let days = entry["days"] as? [Any], let data = entry["data"] as? [Any] else {
            return []
        }
        let labels = days.compactMap { $0 as? String }
        let length = min(labels.count, data.count)
        return (0..<length).map { Point(at: labels[$0], value: finite(data[$0]) ?? .nan) }
    }

    static func seriesViews(_ entries: [JSONObject]) -> [SeriesView] {
        entries.enumerated().map { index, entry in
            let seriesIndex = seriesIndexOf(entry, fallback: Double(index))
            let label = (entry["label"] as? String).map(displaySeriesLabel) ?? "Series \(Int(seriesIndex) + 1)"
            return SeriesView(
                label: label,
                points: pointsOf(entry),
                compare: compareOf(entry),
                seriesIndex: seriesIndex,
                breakdown: breakdownOf(entry)
            )
        }
    }

    private static let breakdownOther = "$$_posthog_breakdown_other_$$"
    private static let breakdownNull = "$$_posthog_breakdown_null_$$"

    static func displaySeriesLabel(_ label: String) -> String {
        label.replacingOccurrences(of: breakdownOther, with: "Other").replacingOccurrences(of: breakdownNull, with: "None")
    }

    static func breakdownLabel(_ value: Breakdown) -> String? {
        switch value {
        case .none:
            return nil
        case .text(let text):
            return text == breakdownOther ? "Other" : text == breakdownNull ? "None" : text
        case .number(let number):
            return jsNumberString(number)
        case .list(let parts):
            let labels = parts.compactMap(breakdownLabel)
            return labels.isEmpty ? nil : labels.joined(separator: ", ")
        }
    }

    static func seriesLabel(_ series: SeriesView) -> String {
        guard let breakdown = breakdownLabel(series.breakdown), !breakdown.isEmpty, !series.label.contains(breakdown) else {
            return series.label
        }
        return "\(series.label) · \(breakdown)"
    }

    static func inProgressFrom(_ points: [Point], resolved: ResolvedRange?, interval: Interval, now: Date) -> String? {
        guard let last = points.last else { return nil }
        if let resolved {
            guard let end = ChartDates.parse(resolved.to) else { return nil }
            return end > now ? last.at : nil
        }
        guard let start = ChartDates.bucketStart(last.at) else { return nil }
        return start.addingTimeInterval(interval.length) > now ? last.at : nil
    }

    static func makeDelta(
        value: Double, previous: Double, basis: DeltaBasis, previousAt: String?, format: ValueFormat
    ) -> Delta {
        let change = value - previous
        let points = format.style == "percentage" || format.style == "percentage_scaled"
        return Delta(
            previous: previous,
            change: format.style == "percentage_scaled" ? change * 100 : change,
            percent: previous == 0 ? nil : change / abs(previous) * 100,
            unit: points ? .points : .percent,
            basis: basis,
            previousAt: previousAt
        )
    }

    private static func sumFinite(_ points: [Point]) -> Double? {
        let values = points.map(\.value).filter(\.isFinite)
        return values.isEmpty ? nil : values.reduce(0, +)
    }

    /// The big number and its delta, so that both always describe the same thing:
    /// - a server aggregate (`aggregated_value`) is the value; the previous period's aggregate gives the delta;
    /// - with a compare series and summable math, the window totals;
    /// - otherwise the last complete bucket, against the same bucket of the previous period, or else the bucket before it.
    static func numberParts(
        source: JSONObject, entries: [JSONObject], format: ValueFormat, inProgressAt: String?
    ) -> NumberParts? {
        guard let current = entries.first(where: { compareOf($0) != .previous }) else { return nil }
        let currentIndex = seriesIndexOf(current, fallback: 0)
        let currentBreakdown = breakdownOf(current)
        let previousEntry = entries.first {
            compareOf($0) == .previous && seriesIndexOf($0, fallback: 0) == currentIndex && breakdownOf($0) == currentBreakdown
        }
        if let aggregate = finite(current["aggregated_value"]) {
            let previousAggregate = finite(previousEntry?["aggregated_value"])
            return NumberParts(
                value: aggregate,
                valueAt: nil,
                delta: previousAggregate.map {
                    makeDelta(value: aggregate, previous: $0, basis: .compare, previousAt: nil, format: format)
                }
            )
        }
        let points = pointsOf(current)
        let previousPoints = pointsOf(previousEntry)
        if previousEntry != nil && isSummable(source) {
            guard let total = sumFinite(points) else { return nil }
            return NumberParts(
                value: total,
                valueAt: nil,
                delta: sumFinite(previousPoints).map {
                    makeDelta(value: total, previous: $0, basis: .compare, previousAt: nil, format: format)
                }
            )
        }
        let complete = inProgressAt != nil && points.last?.at == inProgressAt ? Array(points.dropLast()) : points
        guard let index = complete.lastIndex(where: { $0.value.isFinite }) else { return nil }
        let point = complete[index]
        let against: Point?
        if previousEntry != nil {
            against = previousPoints.indices.contains(index) ? previousPoints[index] : nil
        } else {
            against = index > 0 ? complete[index - 1] : nil
        }
        let delta = against.flatMap { against in
            against.value.isFinite
                ? makeDelta(
                    value: point.value, previous: against.value, basis: previousEntry != nil ? .compare : .previousBucket,
                    previousAt: against.at, format: format
                )
                : nil
        }
        return NumberParts(value: point.value, valueAt: point.at, delta: delta)
    }

    struct DeltaFields {
        let percent: Double
        let text: String
        let basis: String
    }

    static func deltaFields(_ delta: Delta, interval: Interval) -> DeltaFields? {
        let basis = deltaBasisText(delta, interval: interval)
        if delta.change == 0 {
            return DeltaFields(percent: 0, text: "No change", basis: basis)
        }
        if delta.unit == .points {
            guard delta.change.isFinite else { return nil }
            return DeltaFields(percent: delta.change, text: String(format: "%.1f pts", abs(delta.change)), basis: basis)
        }
        guard let percent = delta.percent, percent.isFinite else { return nil }
        let size = abs(percent)
        return DeltaFields(percent: percent, text: "\(number(size, maxDigits: size >= 10 ? 0 : 1))%", basis: basis)
    }

    static func deltaBasisText(_ delta: Delta, interval: Interval) -> String {
        guard delta.basis == .previousBucket, let previousAt = delta.previousAt,
              let date = ChartDates.bucketStart(previousAt)
        else {
            return "vs previous period"
        }
        return "vs \(ChartDates.axisLabel(date, interval: interval))"
    }

    static func chartSeries(_ views: [SeriesView]) -> [ChartSeries] {
        let current = Array(views.filter { $0.compare != .previous }.prefix(seriesLimit))
        guard let reference = current.first?.points, !reference.isEmpty else { return [] }
        func aligned(_ points: [Point]) -> [ChartPoint] {
            let padded = reference.indices.map { index in
                let point = points.indices.contains(index) ? points[index] : nil
                let value = point?.value
                return ChartPoint(at: point?.at ?? reference[index].at, value: value.flatMap { $0.isFinite ? $0 : nil })
            }
            return Array(padded.suffix(pointLimit))
        }
        var result = current.map { ChartSeries(label: seriesLabel($0), points: aligned($0.points), previous: false) }
        for view in views where view.compare == .previous {
            guard let partner = current.first(where: {
                $0.seriesIndex == view.seriesIndex && $0.breakdown == view.breakdown
            }) else { continue }
            let label = current.count == 1 ? "Previous period" : "\(seriesLabel(partner)), previous period"
            result.append(ChartSeries(label: label, points: aligned(view.points), previous: true))
        }
        return result
    }

    private struct Preset {
        let label: String
        let from: String
        let to: String?
    }

    private static let presets: [Preset] = [
        Preset(label: "Today", from: "dStart", to: nil),
        Preset(label: "Yesterday", from: "-1dStart", to: "-1dEnd"),
        Preset(label: "Last 24 hours", from: "-24h", to: nil),
        Preset(label: "Last 7 days", from: "-7d", to: nil),
        Preset(label: "Last 30 days", from: "-30d", to: nil),
        Preset(label: "Last 90 days", from: "-90d", to: nil),
        Preset(label: "This week", from: "wStart", to: nil),
        Preset(label: "This month", from: "mStart", to: nil),
        Preset(label: "Last month", from: "-1mStart", to: "-1mEnd"),
        Preset(label: "This year", from: "yStart", to: nil),
        Preset(label: "All time", from: "all", to: nil),
        Preset(label: "Last hour", from: "-1h", to: nil),
        Preset(label: "Last 48 hours", from: "-48h", to: nil),
        Preset(label: "Last 14 days", from: "-14d", to: nil),
        Preset(label: "Last 180 days", from: "-180d", to: nil),
        Preset(label: "Last week", from: "-1wStart", to: "-1wEnd"),
    ]

    private static let relativePattern = try! NSRegularExpression(pattern: #"^-(\d+)([hdwmy])$"#)
    private static let relativeNouns = ["h": "hour", "d": "day", "w": "week", "m": "month", "y": "year"]

    static func rangeLabel(source: JSONObject, resolved: ResolvedRange?, interval: Interval) -> String? {
        let range = (source["dateRange"] as? JSONObject) ?? ((source["filters"] as? JSONObject)?["dateRange"] as? JSONObject)
        let dateFrom = range?["date_from"] as? String
        let dateTo = range?["date_to"] as? String
        return savedRangeLabel(dateFrom: dateFrom, dateTo: dateTo) ?? resolved.map { resolvedRangeText($0, interval: interval) }
    }

    static func savedRangeLabel(dateFrom: String?, dateTo: String?) -> String? {
        guard let dateFrom, !dateFrom.isEmpty else { return nil }
        if let preset = presets.first(where: { $0.from == dateFrom && $0.to == dateTo }) {
            return preset.label
        }
        if dateTo == nil, let groups = ChartDates.groups(relativePattern, dateFrom),
           let amount = groups[1].flatMap({ Int($0) }), let noun = groups[2].flatMap({ relativeNouns[$0] })
        {
            return amount == 1 ? "Last \(noun)" : "Last \(amount) \(noun)s"
        }
        if ChartDates.wallTime(dateFrom) != nil {
            return ChartDates.span(dateFrom, dateTo ?? dateFrom)
        }
        return nil
    }

    static func resolvedRangeText(_ range: ResolvedRange, interval: Interval) -> String {
        if interval == .hour {
            return ChartDates.span(range.from, range.to)
        }
        return ChartDates.span(String(range.from.prefix(10)), String(range.to.prefix(10)))
    }

    private static func precision(_ value: Any?) -> Int? {
        guard let number = finite(value), number == number.rounded(), number >= 0, number <= 100 else { return nil }
        return Int(number)
    }

    static func valueFormat(source: JSONObject) -> ValueFormat {
        let filter = source["trendsFilter"] as? JSONObject
        return ValueFormat(
            style: filter?["aggregationAxisFormat"] as? String,
            prefix: filter?["aggregationAxisPrefix"] as? String ?? "",
            suffix: filter?["aggregationAxisPostfix"] as? String ?? "",
            decimalPlaces: precision(filter?["decimalPlaces"]),
            minDecimalPlaces: precision(filter?["minDecimalPlaces"])
        )
    }

    static func formatValue(_ value: Double, _ format: ValueFormat) -> String {
        let style = format.style
        let scaled = style == "percentage_scaled" ? value * 100 : value
        let significant = format.decimalPlaces ?? significantDecimals(scaled, minimum: format.minDecimalPlaces ?? 2)
        var formatted = number(scaled, maxDigits: significant, minDigits: format.minDecimalPlaces ?? 0)
        switch style {
        case "percentage", "percentage_scaled":
            formatted = "\(number(scaled, maxDigits: significant))%"
        case "currency":
            formatted = "$\(number(value, maxDigits: 2, minDigits: 2))"
        case "short":
            formatted = shortNumber(value)
        case "duration":
            formatted = duration(value * 1000)
        case "duration_ms":
            formatted = duration(value)
        case "duration_ns":
            if abs(value) < 1000 {
                formatted = "\(number(value, maxDigits: 2))ns"
            } else if abs(value) < 1_000_000 {
                formatted = "\(number(value / 1000, maxDigits: 2))µs"
            } else {
                formatted = duration(value / 1_000_000)
            }
        default:
            break
        }
        let prefix = style == "currency" && !format.prefix.isEmpty && formatted.hasPrefix(format.prefix) ? "" : format.prefix
        return "\(prefix)\(formatted)\(format.suffix)"
    }

    /// `toLocaleString('en-US')`: grouped thousands, halves rounded away from zero.
    static func number(_ value: Double, maxDigits: Int, minDigits: Int = 0) -> String {
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "en_US")
        formatter.numberStyle = .decimal
        formatter.usesGroupingSeparator = true
        formatter.roundingMode = .halfUp
        formatter.minimumFractionDigits = minDigits
        formatter.maximumFractionDigits = max(maxDigits, minDigits)
        return formatter.string(from: NSNumber(value: value)) ?? jsNumberString(value)
    }

    static func significantDecimals(_ value: Double, minimum: Int = 2) -> Int {
        guard value.isFinite, value != 0 else { return minimum }
        return min(max(minimum, 1 - Int(floor(log10(abs(value))))), 10)
    }

    static func shortNumber(_ value: Double) -> String {
        let magnitudes = ["", "K", "M", "B", "T", "P", "E", "Z", "Y"]
        var rounded = Double(String(format: "%.3g", value)) ?? value
        var magnitude = 0
        while abs(rounded) >= 1000 && magnitude < magnitudes.count - 1 {
            magnitude += 1
            rounded /= 1000
        }
        return magnitude > 0 ? "\(jsNumberString(rounded))\u{00a0}\(magnitudes[magnitude])" : jsNumberString(rounded)
    }

    static func duration(_ milliseconds: Double) -> String {
        let absolute = abs(milliseconds)
        guard absolute.isFinite else { return jsNumberString(milliseconds) }
        if absolute == 0 {
            return "0s"
        }
        if absolute < 60_000 {
            let value = absolute < 1000 ? milliseconds : milliseconds / 1000
            let decimals = min(max(0, 2 - Int(floor(log10(abs(value))))), 4)
            return "\(number(value, maxDigits: decimals))\(absolute < 1000 ? "ms" : "s")"
        }
        guard let seconds = Int(exactly: floor(absolute / 1000)) else {
            return "\(String(format: "%.6g", milliseconds / 1000))s"
        }
        let days = seconds / 86400
        let hours = (seconds % 86400) / 3600
        let minutes = (seconds % 3600) / 60
        let parts: [(Int, String)] = days > 0 ? [(days, "d"), (hours, "h")] : [(hours, "h"), (minutes, "m"), (seconds % 60, "s")]
        let text = parts.filter { $0.0 != 0 }.map { "\($0.0)\($0.1)" }.joined(separator: "\u{00a0}")
        return "\(milliseconds < 0 ? "-" : "")\(text)"
    }

    /// A JSON number that is not a boolean, as the adapters' `finite` reads it.
    static func finite(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let double = number.doubleValue
        return double.isFinite ? double : nil
    }

    /// JavaScript's `Boolean(value)` for a JSON value.
    static func isTruthy(_ value: Any?) -> Bool {
        switch value {
        case nil, is NSNull:
            return false
        case let number as NSNumber:
            if CFGetTypeID(number) == CFBooleanGetTypeID() {
                return number.boolValue
            }
            return number.doubleValue != 0 && !number.doubleValue.isNaN
        case let text as String:
            return !text.isEmpty
        default:
            return true
        }
    }

    /// `String(number)` in JavaScript, for whole numbers and short decimals.
    static func jsNumberString(_ value: Double) -> String {
        if value.isFinite && value == value.rounded() && abs(value) < 1e15 {
            return String(Int64(value))
        }
        return "\(value)"
    }
}

/// Dates as the app reads and writes them: src/lib/dates.ts (parseBucketStart, formatMonthDay),
/// src/ui/chart/chartMath.ts (formatAxisDate) and src/features/views/rangePresets.ts (formatRangeSpan).
enum ChartDates {
    private static let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    private static let utc = TimeZone(identifier: "UTC")!

    private static let isoPattern = try! NSRegularExpression(
        pattern: #"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?(Z|[+-]\d{2}(?::?\d{2})?)?$"#
    )
    private static let bucketPattern = try! NSRegularExpression(
        pattern: #"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$"#
    )
    private static let dayOnlyPattern = try! NSRegularExpression(pattern: #"^(\d{4})-(\d{2})-(\d{2})$"#)
    private static let dateTimePattern = try! NSRegularExpression(pattern: #"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})"#)

    static func groups(_ regex: NSRegularExpression, _ text: String) -> [String?]? {
        guard let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) else { return nil }
        return (0..<match.numberOfRanges).map { index in
            Range(match.range(at: index), in: text).map { String(text[$0]) }
        }
    }

    private static func calendar(_ zone: TimeZone) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        return calendar
    }

    private static func date(_ groups: [String?], zone: TimeZone) -> Date? {
        var components = DateComponents()
        components.year = groups[1].flatMap { Int($0) }
        components.month = groups[2].flatMap { Int($0) }
        components.day = groups[3].flatMap { Int($0) }
        components.hour = groups.count > 4 ? groups[4].flatMap { Int($0) } ?? 0 : 0
        components.minute = groups.count > 5 ? groups[5].flatMap { Int($0) } ?? 0 : 0
        components.second = groups.count > 6 ? groups[6].flatMap { Int($0) } ?? 0 : 0
        if groups.count > 7, let fraction = groups[7] {
            components.nanosecond = Int(String((fraction + "000000000").prefix(9)))
        }
        return calendar(zone).date(from: components)
    }

    private static func zone(offset: String) -> TimeZone? {
        if offset == "Z" {
            return utc
        }
        let digits = offset.dropFirst().filter(\.isNumber)
        guard let hours = Int(digits.prefix(2)) else { return nil }
        let minutes = Int(digits.dropFirst(2).prefix(2)) ?? 0
        let seconds = (hours * 3600 + minutes * 60) * (offset.hasPrefix("-") ? -1 : 1)
        return TimeZone(secondsFromGMT: seconds)
    }

    /// `Date.parse` for the server's ISO strings: a bare date is UTC midnight, a date and time without an offset is
    /// local time.
    static func parse(_ text: String) -> Date? {
        guard let groups = groups(isoPattern, text) else { return nil }
        let zone: TimeZone
        if let offset = groups[8] {
            guard let parsed = Self.zone(offset: offset) else { return nil }
            zone = parsed
        } else {
            zone = groups[4] == nil ? utc : .current
        }
        return date(groups, zone: zone)
    }

    /// `parseBucketStart`: a bucket label without an offset is wall-clock time, so it parses as local time.
    static func bucketStart(_ text: String) -> Date? {
        if let groups = groups(bucketPattern, text) {
            return date(groups, zone: .current)
        }
        return parse(text)
    }

    /// `formatAxisDate`: "14:00" for hours, "Oct 12" for days and weeks, "Oct 2026" for months.
    static func axisLabel(_ date: Date, interval: TrendsParser.Interval) -> String {
        let parts = calendar(.current).dateComponents([.year, .month, .day, .hour, .minute], from: date)
        let month = months[((parts.month ?? 1) - 1 + 12) % 12]
        switch interval {
        case .hour:
            return String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
        case .day, .week:
            return "\(month) \(parts.day ?? 1)"
        case .month:
            return "\(month) \(parts.year ?? 0)"
        }
    }

    static func dayLabel(_ date: Date) -> String {
        let parts = calendar(.current).dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 1, parts.day ?? 1)
    }

    struct WallTime {
        let year: Int
        let month: Int
        let day: Int
        let time: String?
    }

    /// The date and time as written, which for the server's resolved ranges is the project timezone.
    static func wallTime(_ value: String) -> WallTime? {
        if let day = groups(dayOnlyPattern, value) {
            return WallTime(year: Int(day[1] ?? "") ?? 0, month: Int(day[2] ?? "") ?? 0, day: Int(day[3] ?? "") ?? 0, time: nil)
        }
        if let dateTime = groups(dateTimePattern, value) {
            return WallTime(
                year: Int(dateTime[1] ?? "") ?? 0, month: Int(dateTime[2] ?? "") ?? 0, day: Int(dateTime[3] ?? "") ?? 0,
                time: "\(dateTime[4] ?? "00"):\(dateTime[5] ?? "00")"
            )
        }
        return nil
    }

    private static func monthDay(_ time: WallTime) -> String {
        "\(months.indices.contains(time.month - 1) ? months[time.month - 1] : "") \(time.day)"
    }

    /// `formatRangeSpan` with " to " between the ends: "Oct 13", "Oct 6 to 12", "Sep 29 to Oct 6",
    /// "Dec 29, 2025 to Jan 4, 2026", and times for windows of hours.
    static func span(_ from: String, _ to: String, separator: String = " to ") -> String {
        guard let a = wallTime(from), let b = wallTime(to) else {
            return "\(from)\(separator)\(to)"
        }
        if a.time != nil || b.time != nil {
            return "\(monthDay(a)) \(a.time ?? "00:00")\(separator)\(monthDay(b)) \(b.time ?? "00:00")"
        }
        if a.year != b.year {
            return "\(monthDay(a)), \(a.year)\(separator)\(monthDay(b)), \(b.year)"
        }
        if a.month == b.month && a.day == b.day {
            return monthDay(a)
        }
        if a.month == b.month {
            return "\(monthDay(a))\(separator)\(b.day)"
        }
        return "\(monthDay(a))\(separator)\(monthDay(b))"
    }
}
