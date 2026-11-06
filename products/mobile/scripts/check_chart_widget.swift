import CryptoKit
import Foundation

// Usage: check-chart

@main
struct CheckChartWidget {
    static var failures = 0

    static func check(_ name: String, _ passed: Bool, _ detail: @autoclosure () -> String = "") {
        if passed {
            print("ok    \(name)")
        } else {
            failures += 1
            print("FAIL  \(name) \(detail())")
        }
    }

    static func main() async throws {
        // Bucket labels are wall-clock times, so the in-progress rule depends on the zone. Pin one.
        NSTimeZone.default = TimeZone(identifier: "America/New_York")!
        let now = ChartDates.parse("2026-11-04T17:00:00Z")!

        try checkBoldNumber(now: now)
        try checkLineWithCompare(now: now)
        try checkBarInProgress(now: now)
        try checkTwoSeries(now: now)
        try checkPercentagePoints(now: now)
        checkFormats()
        checkRangeLabels()
        try checkCatalog()
        checkFetcher(now: now)
        await checkResponseLimits()
        try checkStore(now: now)
        try await checkRefresh(now: now)
        try checkState(now: now)
        try checkInsightFormats(now: now)

        if failures > 0 {
            print("\(failures) check(s) failed")
            exit(1)
        }
        print("Passed: big number, compare totals, bars with an open bucket, two series, formats, ranges, catalog, fetch, store, states")
    }

    static func days(from start: String, count: Int) -> [String] {
        let first = ChartDates.bucketStart(start)!
        let calendar = Calendar(identifier: .gregorian)
        return (0..<count).map { ChartDates.dayLabel(calendar.date(byAdding: .day, value: $0, to: first)!) }
    }

    static func json(_ object: Any) -> String {
        String(data: try! JSONSerialization.data(withJSONObject: object), encoding: .utf8)!
    }

    static func response(_ text: String) -> JSONObject {
        try! JSONSerialization.jsonObject(with: Data(text.utf8)) as! JSONObject
    }

    static func trends(
        display: String? = nil, dateFrom: String? = "-14d", interval: String = "day", series: Int = 1,
        math: String? = nil, format: String? = nil, prefix: String? = nil, suffix: String? = nil
    ) -> JSONObject {
        var filter: JSONObject = [:]
        if let display { filter["display"] = display }
        if let format { filter["aggregationAxisFormat"] = format }
        if let prefix { filter["aggregationAxisPrefix"] = prefix }
        if let suffix { filter["aggregationAxisPostfix"] = suffix }
        var node: JSONObject = ["kind": "EventsNode", "event": "$pageview"]
        if let math { node["math"] = math }
        var source: JSONObject = [
            "kind": "TrendsQuery", "interval": interval, "trendsFilter": filter,
            "series": Array(repeating: node, count: series),
        ]
        if let dateFrom { source["dateRange"] = ["date_from": dateFrom] }
        return ["kind": "InsightVizNode", "source": source]
    }

    static func checkBoldNumber(now: Date) throws {
        let labels = days(from: "2026-10-22", count: 14)
        let text = json([
            "id": 1, "short_id": "abc123", "last_refresh": "2026-11-04T16:48:00Z",
            "query": trends(display: "BoldNumber", math: "dau"),
            "resolved_date_range": ["date_from": "2026-10-22T00:00:00-04:00", "date_to": "2026-11-04T23:59:59.999999-05:00"],
            "result": [
                ["label": "Signups", "action": ["order": 0], "compare_label": "current", "aggregated_value": 1284,
                 "data": Array(repeating: 90, count: 14), "days": labels],
                ["label": "Signups", "action": ["order": 0], "compare_label": "previous", "aggregated_value": 1143,
                 "data": Array(repeating: 80, count: 14), "days": days(from: "2026-10-08", count: 14)],
            ],
        ] as JSONObject)
        let snapshot = try TrendsParser.snapshot(data: Data(text.utf8), pinId: "pin-1", now: now)
        check("big number: aggregate is the value", snapshot.valueText == "1,284", "\(String(describing: snapshot.valueText))")
        check("big number: delta against the previous aggregate", snapshot.deltaText == "12%" && abs((snapshot.deltaPercent ?? 0) - 12.336) < 0.01,
              "\(String(describing: snapshot.deltaText)) \(String(describing: snapshot.deltaPercent))")
        check("big number: basis is the previous period", snapshot.deltaBasis == "vs previous period")
        check("big number: pill reads up", snapshot.pillText == "▲ 12%", "\(String(describing: snapshot.pillText))")
        check("big number: draws a line from data", snapshot.chartKind == .line && snapshot.currentSeries.first?.points.count == 14)
        check("big number: range label", snapshot.rangeLabel == "Last 14 days", "\(String(describing: snapshot.rangeLabel))")
        check("big number: snapshot JSON round trip", try JSONDecoder().decode(ChartSnapshot.self, from: JSONEncoder().encode(snapshot)) == snapshot)
    }

    static func checkLineWithCompare(now: Date) throws {
        let current: [Double] = [72, 80, 77, 85, 91, 88, 79, 94, 98, 90, 101, 97, 108, 124]
        let previous: [Double] = [70, 75, 70, 80, 81, 80, 70, 84, 88, 80, 91, 87, 98, 101]
        let text = json([
            "last_refresh": "2026-11-04T15:30:00Z",
            "query": trends(display: "ActionsLineGraph"),
            "resolved_date_range": ["date_from": "2026-10-22T00:00:00-04:00", "date_to": "2026-11-04T23:59:59.999999-05:00"],
            "result": [
                ["label": "$pageview", "action": ["order": 0], "compare_label": "current", "data": current, "days": days(from: "2026-10-22", count: 14)],
                ["label": "$pageview", "action": ["order": 0], "compare_label": "previous", "data": previous, "days": days(from: "2026-10-08", count: 14)],
            ],
        ] as JSONObject)
        let snapshot = try TrendsParser.snapshot(data: Data(text.utf8), pinId: "pin-2", now: now)
        let total = current.reduce(0, +)
        let previousTotal = previous.reduce(0, +)
        let percent = (total - previousTotal) / previousTotal * 100
        check("line + compare: summable math totals the window", snapshot.valueText == TrendsParser.formatValue(total, .init()),
              "\(String(describing: snapshot.valueText)) vs \(total)")
        check("line + compare: delta against the previous total", abs((snapshot.deltaPercent ?? 0) - percent) < 1e-9 && snapshot.deltaBasis == "vs previous period")
        check("line + compare: current then previous series", snapshot.series.map(\.previous) == [false, true] && snapshot.series[1].label == "Previous period")
        check("line + compare: 14 points each", snapshot.series.allSatisfy { $0.points.count == 14 })
        check("line + compare: interval and range", snapshot.intervalLabel == "day" && snapshot.rangeLabel == "Last 14 days")
        check("line + compare: axis end labels", snapshot.axisLabels(limit: 60).map { [$0.0, $0.1] } == ["Oct 22", "Nov 4"],
              "\(String(describing: snapshot.axisLabels(limit: 60)))")
    }

    static func checkBarInProgress(now: Date) throws {
        let labels = days(from: "2026-10-29", count: 7)
        func snapshot(dateTo: String?) throws -> ChartSnapshot {
            var body: JSONObject = [
                "query": trends(display: "ActionsBar", dateFrom: "-7d"),
                "result": [["label": "Signups", "action": ["order": 0], "data": [10, 12, 9, 14, 20, 18, 3], "days": labels]],
            ]
            if let dateTo { body["resolved_date_range"] = ["date_from": "2026-10-29T00:00:00-04:00", "date_to": dateTo] }
            return try TrendsParser.snapshot(data: Data(json(body).utf8), pinId: "pin-3", now: now)
        }
        let open = try snapshot(dateTo: "2026-11-04T23:59:59.999999-05:00")
        check("bars: chart kind", open.chartKind == .bar)
        check("bars: open last bucket is not the value", open.valueText == "18", "\(String(describing: open.valueText))")
        check("bars: delta against the bucket before", open.deltaText == "10%" && (open.deltaPercent ?? 0) < 0 && open.pillText == "▼ 10%",
              "\(String(describing: open.deltaText)) \(String(describing: open.deltaPercent))")
        check("bars: basis names the bucket", open.deltaBasis == "vs Nov 2", "\(String(describing: open.deltaBasis))")
        check("bars: the open bucket still draws", open.series.first?.points.last?.value == 3)
        let closed = try snapshot(dateTo: "2026-11-03T23:59:59.999999-05:00")
        check("bars: a closed window uses its last bucket", closed.valueText == "3", "\(String(describing: closed.valueText))")
        let unresolved = try snapshot(dateTo: nil)
        check("bars: without a resolved range, today's bucket is open", unresolved.valueText == "18", "\(String(describing: unresolved.valueText))")
    }

    static func checkTwoSeries(now: Date) throws {
        let labels = days(from: "2026-10-22", count: 14)
        let text = json([
            "query": trends(display: "ActionsLineGraph", series: 2),
            "result": [
                ["label": "Signups", "action": ["order": 0], "data": Array(repeating: 5, count: 14), "days": labels],
                ["label": "Logins", "action": ["order": 1], "data": Array(repeating: 9, count: 14), "days": labels],
            ],
        ] as JSONObject)
        let snapshot = try TrendsParser.snapshot(data: Data(text.utf8), pinId: "pin-4", now: now)
        check("two series: no headline value", snapshot.valueText == nil && snapshot.pillText == nil)
        check("two series: both drawn in order", snapshot.series.map(\.label) == ["Signups", "Logins"])

        let six = json([
            "query": trends(series: 6),
            "result": (0..<6).map { ["label": "S\($0)", "action": ["order": $0], "data": [1, 2], "days": ["2026-11-03", "2026-11-04"]] as JSONObject },
        ] as JSONObject)
        let capped = try TrendsParser.snapshot(data: Data(six.utf8), pinId: "pin-5", now: now)
        check("many series: capped at five", capped.series.count == 5)

        let breakdown = json([
            "query": trends(),
            "result": [["label": "$pageview - $$_posthog_breakdown_other_$$", "breakdown_value": "$$_posthog_breakdown_other_$$",
                         "action": ["order": 0], "data": [1], "days": ["2026-11-04"]]],
        ] as JSONObject)
        let other = try TrendsParser.snapshot(data: Data(breakdown.utf8), pinId: "pin-6", now: now)
        check("breakdown placeholders read Other", other.series.first?.label == "$pageview - Other", "\(String(describing: other.series.first?.label))")
    }

    static func checkPercentagePoints(now: Date) throws {
        let text = json([
            "query": trends(dateFrom: "-7d", format: "percentage_scaled"),
            "resolved_date_range": ["date_from": "2026-10-28T00:00:00-04:00", "date_to": "2026-11-03T23:59:59-05:00"],
            "result": [["label": "Conversion", "action": ["order": 0], "data": [0.42, 0.45, 0.4567],
                        "days": ["2026-11-01", "2026-11-02", "2026-11-03"]]],
        ] as JSONObject)
        let snapshot = try TrendsParser.snapshot(data: Data(text.utf8), pinId: "pin-7", now: now)
        check("percentage: value scaled", snapshot.valueText == "45.67%", "\(String(describing: snapshot.valueText))")
        check("percentage: delta in points", snapshot.pillText == "▲ 0.7 pts", "\(String(describing: snapshot.pillText))")
    }

    static func checkFormats() {
        let nbsp = "\u{00a0}"
        let cases: [(String, Double, TrendsParser.ValueFormat, String)] = [
            ("numeric", 1284, .init(), "1,284"),
            ("numeric decimals", 1284.567, .init(), "1,284.57"),
            ("numeric large", 1_234_567, .init(), "1,234,567"),
            ("numeric small", 0.012345, .init(), "0.012"),
            ("percentage", 12.3, .init(style: "percentage"), "12.3%"),
            ("percentage_scaled", 0.4567, .init(style: "percentage_scaled"), "45.67%"),
            ("duration", 125, .init(style: "duration"), "2m\(nbsp)5s"),
            ("duration seconds", 45.2, .init(style: "duration"), "45.2s"),
            ("duration hours", 7384, .init(style: "duration"), "2h\(nbsp)3m\(nbsp)4s"),
            ("duration_ms", 850, .init(style: "duration_ms"), "850ms"),
            ("duration outside integer range", 1e20, .init(style: "duration"), "1e+20s"),
            ("negative duration outside integer range", -1e20, .init(style: "duration"), "-1e+20s"),
            ("duration_ms outside integer range", 1e23, .init(style: "duration_ms"), "1e+20s"),
            ("duration_ns outside integer range", 1e29, .init(style: "duration_ns"), "1e+20s"),
            ("duration at integer boundary", Double(Int.max), .init(style: "duration"), "9.22337e+18s"),
            ("prefix and postfix", 1284, .init(prefix: "~", suffix: " users"), "~1,284 users"),
            ("currency", 12.5, .init(style: "currency", prefix: "$"), "$12.50"),
            ("short", 1284, .init(style: "short"), "1.28\(nbsp)K"),
            ("decimal places", 3.14159, .init(decimalPlaces: 1), "3.1"),
        ]
        for (name, value, format, expected) in cases {
            let formatted = TrendsParser.formatValue(value, format)
            check("format \(name)", formatted == expected, "got \(formatted.debugDescription), want \(expected.debugDescription)")
        }
    }

    static func checkRangeLabels() {
        let cases: [(String?, String?, String?)] = [
            ("-14d", nil, "Last 14 days"),
            ("-7d", nil, "Last 7 days"),
            ("-30d", nil, "Last 30 days"),
            ("dStart", nil, "Today"),
            ("-1mStart", "-1mEnd", "Last month"),
            ("-3d", nil, "Last 3 days"),
            ("-1w", nil, "Last week"),
            ("2026-10-01", "2026-10-15", "Oct 1 to 15"),
            ("-1mStart", nil, nil),
        ]
        for (from, to, expected) in cases {
            let label = TrendsParser.savedRangeLabel(dateFrom: from, dateTo: to)
            check("range \(from ?? "nil")..\(to ?? "nil")", label == expected, "got \(String(describing: label))")
        }
        let resolved = TrendsParser.ResolvedRange(from: "2026-10-22T00:00:00-04:00", to: "2026-11-04T23:59:59-05:00")
        let unknown = TrendsParser.rangeLabel(source: ["dateRange": ["date_from": "-1mStart"]], resolved: resolved, interval: .day)
        check("range unknown falls back to the resolved window", unknown == "Oct 22 to Nov 4", "got \(String(describing: unknown))")
    }

    static let catalogJSON = """
    {
      "version": 1, "host": "https://us.posthog.com", "projectId": 2, "projectName": "PostHog App", "writtenAt": 1762270000000,
      "pins": [
        { "id": "pin-a", "kind": "insight", "name": "Signups", "subtitle": "Insight", "insightId": 123, "shortId": "abc123", "dashboardId": null, "eligible": true, "number": true, "chart": true, "reason": null },
        { "id": "pin-b", "kind": "dashboard", "name": "Product KPIs", "subtitle": "Product KPIs · Daily active users", "insightId": 456, "shortId": "def456", "dashboardId": 12, "eligible": true, "number": true, "chart": true, "reason": null },
        { "id": "pin-c", "kind": "insight", "name": "Checkout funnel", "subtitle": "Insight", "insightId": 789, "shortId": "ghi789", "dashboardId": null, "eligible": false, "number": false, "chart": false, "reason": "Not a chart over time" },
        { "id": "pin-d", "kind": "insight", "name": "Retention", "subtitle": "Insight", "insightId": null, "shortId": "jkl012", "dashboardId": null, "eligible": true, "number": true, "chart": true, "reason": null }
      ]
    }
    """

    static func checkCatalog() throws {
        let catalog = try require(ChartStore.decodeCatalog(catalogJSON), "catalog decodes")
        check("catalog: picker leaves out ineligible pins, keeps Views order", catalog.pickerPins.map(\.id) == ["pin-a", "pin-b", "pin-d"])
        check("catalog: another version is ignored", ChartStore.decodeCatalog(catalogJSON.replacingOccurrences(of: "\"version\": 1", with: "\"version\": 2")) == nil)
    }

    static let credentials = ChartCredentials(
        version: 1, host: "https://us.posthog.com", projectId: 2, projectName: "PostHog App",
        accessToken: "phx_example", expiresAt: nil, userUuid: "user-1"
    )

    static func checkFetcher(now: Date) {
        let catalog = ChartStore.decodeCatalog(catalogJSON)!
        let insight = catalog.pin(id: "pin-a")!
        let dashboard = catalog.pin(id: "pin-b")!
        let byShortId = catalog.pin(id: "pin-d")!
        check("fetch URL: insight by id", ChartFetcher.url(for: insight, host: "https://us.posthog.com/", projectId: 2)?.absoluteString
              == "https://us.posthog.com/api/projects/2/insights/123/?refresh=force_cache")
        check("fetch URL: dashboard tile", ChartFetcher.url(for: dashboard, host: "https://us.posthog.com", projectId: 2)?.absoluteString
              == "https://us.posthog.com/api/projects/2/insights/456/?refresh=force_cache&from_dashboard=12")
        check("fetch URL: by short id", ChartFetcher.url(for: byShortId, host: "https://us.posthog.com", projectId: 2)?.absoluteString
              == "https://us.posthog.com/api/projects/2/insights/?short_id=jkl012&refresh=force_cache")
        let request = ChartFetcher.request(for: insight, credentials: credentials, appVersion: "1.9.0")
        check("fetch headers", request?.value(forHTTPHeaderField: "Authorization") == "Bearer phx_example"
              && request?.value(forHTTPHeaderField: "Accept") == "application/json"
              && request?.value(forHTTPHeaderField: "User-Agent") == "posthog-mobile-widget/1.9.0 (ios)"
              && request?.timeoutInterval == 20)

        let empty = Data()
        check("status 401 is auth", ChartFetcher.outcome(status: 401, body: empty, pin: insight, now: now) == .failed(.auth))
        check("status 403 is auth", ChartFetcher.outcome(status: 403, body: empty, pin: insight, now: now) == .failed(.auth))
        check("status 404 is not_found", ChartFetcher.outcome(status: 404, body: empty, pin: insight, now: now) == .failed(.notFound))
        check("status 429 is rate_limited", ChartFetcher.outcome(status: 429, body: empty, pin: insight, now: now) == .failed(.rateLimited))
        check("status 503 is rate_limited", ChartFetcher.outcome(status: 503, body: empty, pin: insight, now: now) == .failed(.rateLimited))
        check("unparseable 200 is bad_data", ChartFetcher.outcome(status: 200, body: Data("<html>".utf8), pin: insight, now: now) == .failed(.badData))
        let miss = Data(json(["query": trends(), "result": NSNull(), "last_refresh": NSNull()] as JSONObject).utf8)
        check("cache miss is no_result", ChartFetcher.outcome(status: 200, body: miss, pin: insight, now: now) == .failed(.noResult))
        let limited = Data(json(["query": trends(), "result": NSNull(), "query_status": ["error": true, "error_code": "rate_limited"]] as JSONObject).utf8)
        check("rate-limited 200 is rate_limited", ChartFetcher.outcome(status: 200, body: limited, pin: insight, now: now) == .failed(.rateLimited))
        let failed = Data(json(["query": trends(), "result": [], "query_status": ["error": true]] as JSONObject).utf8)
        check("query error is bad_data", ChartFetcher.outcome(status: 200, body: failed, pin: insight, now: now) == .failed(.badData))
        let list = Data(json(["results": [
            ["short_id": "other", "query": trends(), "result": []],
            ["short_id": "jkl012", "query": trends(), "result": [["label": "A", "data": [4], "days": ["2026-11-03"]]]],
        ]] as JSONObject).utf8)
        if case .snapshot(let snapshot) = ChartFetcher.outcome(status: 200, body: list, pin: byShortId, now: now) {
            check("short id read takes the matching result", snapshot.pinId == "pin-d" && snapshot.series.first?.label == "A")
        } else {
            check("short id read takes the matching result", false)
        }
        let noMatch = Data(json(["results": [["short_id": "other", "query": trends(), "result": []]]] as JSONObject).utf8)
        check("short id read without a match is not_found", ChartFetcher.outcome(status: 200, body: noMatch, pin: byShortId, now: now) == .failed(.notFound))
        let funnel = Data(json(["query": ["kind": "InsightVizNode", "source": ["kind": "FunnelsQuery"]], "result": []] as JSONObject).utf8)
        if case .snapshot(let snapshot) = ChartFetcher.outcome(status: 200, body: funnel, pin: insight, now: now) {
            check("an empty funnel remains a valid snapshot", snapshot.display == "rows" && snapshot.rows?.isEmpty == true)
        } else { check("an empty funnel remains a valid snapshot", false) }
    }

    static func checkStore(now: Date) throws {
        let suite = "check-chart-widget-\(ProcessInfo.processInfo.processIdentifier)"
        let raw = try require(UserDefaults(suiteName: suite), "test suite")
        let key = SymmetricKey(size: .bits256)
        let store = ChartStorage(defaults: raw, key: key)
        defer { raw.removePersistentDomain(forName: suite) }
        check("app group from the extension id", AppGroup.appId(fromExtensionBundleId: "com.posthog.code.mobile.dev.HedgehogWidget") == "com.posthog.code.mobile.dev"
              && AppGroup.appId(fromExtensionBundleId: "com.posthog.code.mobile") == "com.posthog.code.mobile")
        store.set(catalogJSON, forKey: ChartStore.catalogKey)
        let catalog = try require(ChartStore.catalog(store: store), "stored catalog")
        let pin = try require(catalog.pin(id: "pin-a"), "stored pin")
        let dashboard = try require(catalog.pin(id: "pin-b"), "stored dashboard pin")
        check("store: catalog has no plaintext copy", raw.string(forKey: ChartStore.catalogKey) == nil && raw.data(forKey: ChartStore.catalogKey) != nil)
        let wrongKey = ChartStorage(defaults: raw, key: SymmetricKey(size: .bits256))
        check("store: a wrong key cannot read values", wrongKey.string(forKey: ChartStore.catalogKey) == nil)
        raw.set("legacy result", forKey: "chart.snapshot.legacy")
        _ = ChartStorage(defaults: raw, key: key)
        check("store: old plaintext is removed", raw.object(forKey: "chart.snapshot.legacy") == nil)
        check("store: catalog reads back", ChartStore.catalog(store: store)?.pins.count == 4)
        let snapshot = ChartSample.snapshot(pinId: "pin-a", value: "1,284", delta: 12, deltaText: "12%", values: [1, 2, 3], now: now)
        ChartRefresh.record(.failed(.network), pin: pin, credentials: credentials, at: now, store: store)
        check("store: a failure writes the error", ChartStore.error(pinId: "pin-a", store: store)?.kind == .network)
        check("store: error JSON uses the contract's kind names",
              store.string(forKey: "chart.snapshotError.pin-a")?.contains("\"network\"") == true)
        ChartRefresh.record(.snapshot(snapshot), pin: pin, credentials: credentials, at: now, store: store)
        check("store: a good read writes the snapshot", ChartStore.snapshot(pinId: "pin-a", store: store) == snapshot)
        check("store: a good read clears the error", ChartStore.error(pinId: "pin-a", store: store) == nil)
        let older = ChartSample.snapshot(pinId: "pin-a", value: "Old", delta: 0, deltaText: "", values: [0], now: now.addingTimeInterval(-60))
        ChartRefresh.record(.snapshot(older), pin: pin, credentials: credentials, at: now, store: store)
        check("store: older background read preserves the app snapshot", ChartStore.snapshot(pinId: "pin-a", store: store) == snapshot)
        ChartRefresh.record(.failed(.rateLimited), pin: pin, credentials: credentials, at: now, store: store)
        check("store: a failure keeps the snapshot", ChartStore.snapshot(pinId: "pin-a", store: store) == snapshot)
        check("store: snapshotError kind", store.string(forKey: "chart.snapshotError.pin-a")?.contains("rate_limited") == true)
        ChartRefresh.record(.failed(.noResult), pin: dashboard, credentials: credentials, at: now, store: store)
        check("store: a cache miss writes no_result", store.string(forKey: "chart.snapshotError.pin-b")?.contains("\"no_result\"") == true)
        ChartStore.save(ChartPinProject(projectId: 2, projectName: "PostHog App"), pinId: "pin-a", store: store)
        let marker = store.string(forKey: "chart.pinProject.pin-a").flatMap { try? JSONSerialization.jsonObject(with: Data($0.utf8)) as? JSONObject }
        check("store: pin project marker JSON", (marker?["projectId"] as? Int) == 2 && (marker?["projectName"] as? String) == "PostHog App")
        check("store: pin project marker reads back", ChartStore.pinProject(pinId: "pin-a", store: store) == ChartPinProject(projectId: 2, projectName: "PostHog App"))
        for kind in [ChartErrorKind.auth, .notFound] {
            ChartStore.save(snapshot, store: store)
            ChartRefresh.record(.failed(kind), pin: pin, credentials: credentials, at: now, store: store)
            check("store: access failures discard cached values", ChartStore.snapshot(pinId: pin.id, store: store) == nil)
        }
        for kind in [ChartErrorKind.auth, .notFound, .network] {
            ChartStore.save(snapshot, store: store)
            ChartRefresh.record(.failed(kind), pin: pin, credentials: credentials, at: now.addingTimeInterval(-60), store: store)
            check("store: a delayed failure preserves newer app data", ChartStore.snapshot(pinId: pin.id, store: store) == snapshot
                  && ChartStore.error(pinId: pin.id, store: store) == nil)
        }
        let credentialsJSON = #"{"version":1,"host":"https://eu.posthog.com","projectId":7,"projectName":"Shop","accessToken":"pha_example","expiresAt":null,"userUuid":"u"}"#
        check("credentials decode with a null expiry", ChartStore.decodeCredentials(Data(credentialsJSON.utf8))?.isExpired(at: now) == false)

        for (target, changedCatalog) in [
            (pin, catalogJSON.replacingOccurrences(of: "\"insightId\": 123", with: "\"insightId\": 321")),
            (dashboard, catalogJSON.replacingOccurrences(of: "\"dashboardId\": 12", with: "\"dashboardId\": 13")),
            (pin, catalogJSON.replacingOccurrences(of: "\"insightId\": 123", with: "\"displayMode\": \"rows\", \"insightId\": 123")),
        ] {
            let currentSnapshot = ChartSample.snapshot(pinId: target.id, value: "654", delta: 0, deltaText: "No change", values: [654], now: now)
            let oldSnapshot = ChartSample.snapshot(pinId: target.id, value: "123", delta: 0, deltaText: "No change", values: [123], now: now)
            ChartStore.save(currentSnapshot, store: store)
            store.set(changedCatalog, forKey: ChartStore.catalogKey)
            for outcome in [ChartFetchOutcome.failed(.notFound), .snapshot(oldSnapshot)] {
                ChartRefresh.record(outcome, pin: target, credentials: credentials, at: now, store: store)
                check("store: a changed target discards late outcomes", ChartStore.snapshot(pinId: target.id, store: store) == currentSnapshot
                      && ChartStore.error(pinId: target.id, store: store) == nil)
            }
        }
    }

    struct ResponseBytes: AsyncSequence, AsyncIteratorProtocol {
        typealias Element = UInt8
        var count: Int

        func makeAsyncIterator() -> Self { self }

        mutating func next() async -> UInt8? {
            guard count > 0 else { return nil }
            count -= 1
            return 65
        }
    }

    static func checkResponseLimits() async {
        for (length, expectedLength, accepted) in [(16, 16, true), (16, -1, true), (17, -1, false), (17, 16, false), (0, 17, false)] {
            do {
                let data = try await ChartFetcher.readBody(ResponseBytes(count: length), expectedLength: Int64(expectedLength), limit: 16)
                check("response limit: \(length) bytes, declared \(expectedLength)", accepted && data == Data(repeating: 65, count: length))
            } catch ChartFetcher.ResponseError.tooLarge {
                check("response limit: \(length) bytes, declared \(expectedLength)", !accepted)
            } catch {
                check("response limit: unexpected error", false, "\(error)")
            }
        }
    }

    actor PendingFetches {
        private var pending: [Int: CheckedContinuation<ChartFetchOutcome, Never>] = [:]
        private var arrivals: [Int: CheckedContinuation<Void, Never>] = [:]

        func fetch(_ pin: ChartPin) async -> ChartFetchOutcome {
            await withCheckedContinuation { continuation in
                pending[pin.insightId!] = continuation
                arrivals.removeValue(forKey: pin.insightId!)?.resume()
            }
        }

        func waitForRequest(_ insightId: Int) async {
            if pending[insightId] != nil { return }
            await withCheckedContinuation { arrivals[insightId] = $0 }
        }

        func complete(_ insightId: Int, with outcome: ChartFetchOutcome) {
            pending.removeValue(forKey: insightId)?.resume(returning: outcome)
        }
    }

    static func checkRefresh(now: Date) async throws {
        let suite = "check-chart-refresh-\(ProcessInfo.processInfo.processIdentifier)"
        let raw = try require(UserDefaults(suiteName: suite), "refresh test suite")
        let store = ChartStorage(defaults: raw, key: SymmetricKey(size: .bits256))
        defer { raw.removePersistentDomain(forName: suite) }
        store.set(catalogJSON, forKey: ChartStore.catalogKey)
        let pin = try require(ChartStore.catalog(store: store)?.pin(id: "pin-b"), "original dashboard tile")
        let requests = PendingFetches()
        let refresh = ChartRefresh(store: store, currentCredentials: { credentials }, fetch: { pin, _, _ in await requests.fetch(pin) })
        let original = Task { await refresh.refresh(pin, credentials: credentials, now: now) }
        await requests.waitForRequest(456)

        store.set(catalogJSON.replacingOccurrences(of: "\"insightId\": 456", with: "\"insightId\": 654"), forKey: ChartStore.catalogKey)
        let replacement = try require(ChartStore.catalog(store: store)?.pin(id: pin.id), "replacement dashboard tile")
        let updated = Task { await refresh.refresh(replacement, credentials: credentials, now: now) }
        await requests.waitForRequest(654)
        let snapshot = ChartSample.snapshot(pinId: pin.id, value: "654", delta: 0, deltaText: "No change", values: [654], now: now)
        await requests.complete(654, with: .snapshot(snapshot))
        await updated.value
        check("refresh: a changed tile starts its own request", ChartStore.snapshot(pinId: pin.id, store: store) == snapshot)

        let oldSnapshot = ChartSample.snapshot(pinId: pin.id, value: "456", delta: 0, deltaText: "No change", values: [456], now: now)
        await requests.complete(456, with: .snapshot(oldSnapshot))
        await original.value
        check("refresh: the old tile cannot overwrite the new result", ChartStore.snapshot(pinId: pin.id, store: store) == snapshot)
        store.removeObject(forKey: "chart.snapshot.\(pin.id)")
        let signedOut = ChartRefresh(store: store, currentCredentials: { nil }, fetch: { _, _, _ in .snapshot(snapshot) })
        await signedOut.refresh(replacement, credentials: credentials, now: now)
        check("refresh: an ended session cannot repopulate the cache", ChartStore.snapshot(pinId: pin.id, store: store) == nil)

    }

    static func checkState(now: Date) throws {
        let catalog = try require(ChartStore.decodeCatalog(catalogJSON), "catalog")
        let links = ChartLinks(scheme: ChartLinks.scheme(forAppId: "com.posthog.code.mobile"), family: .medium)
        let signups = ChartSelection(id: "pin-a", name: "Signups")
        let nowMs = now.timeIntervalSince1970 * 1000
        func state(
            credentials: ChartCredentials? = credentials, catalog: ChartCatalog? = catalog,
            snapshots: [String: ChartSnapshot] = [:], errors: [String: ChartSnapshotError] = [:],
            projects: [String: ChartPinProject] = [:]
        ) -> ChartStoreState {
            ChartStoreState(
                credentials: credentials, catalog: catalog, snapshot: { snapshots[$0] }, error: { errors[$0] }, pinProject: { projects[$0] }
            )
        }
        func detail(_ content: ChartContent) -> String? {
            if case .message(_, let detail) = content.primary.state { return detail }
            return nil
        }
        func message(_ content: ChartContent) -> String? {
            if case .message(let text, _) = content.primary.state { return text }
            return nil
        }

        let signedOut = ChartResolver.content(primary: signups, extras: [], store: state(credentials: nil), links: links, now: now)
        check("state: signed out", message(signedOut) == "Sign in to see your pins" && signedOut.primary.link.absoluteString == "posthog://views")

        let expired = ChartCredentials(version: 1, host: credentials.host, projectId: 2, projectName: nil, accessToken: "x",
                                       expiresAt: nowMs + 30_000, userUuid: nil)
        check("state: expiring token counts as expired", expired.isExpired(at: now))
        check("state: expired token sends nothing", ChartResolver.pinsToFetch([signups], store: state(credentials: expired), now: now).isEmpty)
        check("state: expired token asks to open the app",
              message(ChartResolver.content(primary: signups, extras: [], store: state(credentials: expired), links: links, now: now)) == "Open PostHog to update")

        let unconfigured = ChartResolver.content(primary: nil, extras: [], store: state(), links: links, now: now)
        check("state: automatically uses the first eligible pin", unconfigured.primary.title == "Signups" && unconfigured.primary.state == .loading)
        let noCatalog = ChartResolver.content(primary: nil, extras: [], store: state(catalog: nil), links: links, now: now)
        check("state: missing catalog points to the app", message(noCatalog) == "Open PostHog to load your pins")
        let emptyCatalog = ChartCatalog(version: 1, host: catalog.host, projectId: 2, projectName: nil, writtenAt: 0, pins: [])
        let noPins = ChartResolver.content(primary: nil, extras: [], store: state(catalog: emptyCatalog), links: links, now: now)
        check("state: empty catalog explains the next step", message(noPins) == "No pinned views available")
        let defaults = ChartResolver.selections(primary: nil, extras: [signups], family: .large, catalog: catalog)
        check("selection: default participates in fetch and deduplication", defaults.0 == signups && defaults.1.isEmpty)
        let chosen = ChartResolver.selections(primary: ChartSelection(id: "pin-b", name: "Product KPIs"), extras: [], family: .medium, catalog: catalog)
        check("selection: explicit choice wins over the default", chosen.0?.id == "pin-b")

        let revenue = ChartSelection(id: "pin-x", name: "Revenue")
        let gone = ChartResolver.content(primary: revenue, extras: [], store: state(), links: links, now: now)
        check("state: pin missing from the catalog", message(gone) == "Revenue is no longer pinned")
        let moved = ChartResolver.content(primary: revenue, extras: [],
                                          store: state(projects: ["pin-x": ChartPinProject(projectId: 7, projectName: "Shop")]), links: links, now: now)
        check("state: a pin from another project says so", message(moved) == "In another project"
              && detail(moved) == "Switch to Shop in PostHog" && moved.primary.title == "Revenue")
        let sameProject = ChartResolver.content(primary: revenue, extras: [],
                                                store: state(projects: ["pin-x": ChartPinProject(projectId: 2, projectName: "PostHog App")]), links: links, now: now)
        check("state: a pin gone from its own project is no longer pinned", message(sameProject) == "Revenue is no longer pinned")
        let markers = ChartResolver.pinProjects([signups, revenue, ChartSelection(id: "pin-c", name: "C")], catalog: catalog)
        check("pin project markers: only pins the catalog lists", markers.map(\.pinId) == ["pin-a", "pin-c"]
              && markers.allSatisfy { $0.project == ChartPinProject(projectId: 2, projectName: "PostHog App") })

        let notFound = ChartResolver.content(primary: signups, extras: [],
                                             store: state(errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .notFound)]), links: links, now: now)
        check("state: deleted insight", message(notFound) == "Signups was unpinned or deleted. Touch and hold to pick another.")

        let auth = ChartResolver.content(primary: signups, extras: [],
                                         store: state(errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .auth)]), links: links, now: now)
        check("state: rejected token", message(auth) == "Open PostHog to update")

        let ineligible = ChartResolver.content(primary: ChartSelection(id: "pin-c", name: "Checkout funnel"), extras: [], store: state(), links: links, now: now)
        check("state: ineligible shows the reason", message(ineligible) == "Not a chart over time" && ineligible.primary.title == "Checkout funnel")

        let elsewhere = ChartCredentials(version: 1, host: credentials.host, projectId: 9, projectName: "Other", accessToken: "x", expiresAt: nil, userUuid: nil)
        let otherProject = ChartResolver.content(primary: signups, extras: [], store: state(credentials: elsewhere), links: links, now: now)
        if case .message(let text, let detail) = otherProject.primary.state {
            check("state: pin in another project", text == "In another project" && detail == "Switch to PostHog App in PostHog")
        } else {
            check("state: pin in another project", false)
        }
        check("state: another project sends nothing", ChartResolver.pinsToFetch([signups], store: state(credentials: elsewhere), now: now).isEmpty)

        let loading = ChartResolver.content(primary: signups, extras: [], store: state(), links: links, now: now)
        check("state: first read pending", loading.primary.state == .loading && loading.primary.title == "Signups" && loading.primary.link == links.pin(catalog.pin(id: "pin-a")!))

        let cached = ChartSample.snapshot(pinId: "pin-a", value: "1,284", delta: 12, deltaText: "12%", values: [1, 2], now: now.addingTimeInterval(-3600))
        let stale = ChartResolver.content(primary: signups, extras: [],
                                          store: state(snapshots: ["pin-a": cached], errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .network)]),
                                          links: links, now: now)
        check("state: a failed read keeps the cache", stale.primary.snapshot == cached
              && stale.primary.link.absoluteString == "posthog://views/insight/abc123?from=widget&family=medium")
        check("state: age turns stale after an hour", ChartAge.isStale(dataDate: cached.dataDate, at: now)
              && ChartAge.text(dataDate: cached.dataDate, at: now) == "Updated 1 h ago")
        check("state: age in minutes", ChartAge.text(dataDate: now.addingTimeInterval(-12 * 60), at: now) == "Updated 12 min ago")

        let noCache = ChartResolver.content(primary: signups, extras: [],
                                            store: state(errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .network)]), links: links, now: now)
        check("state: a failed first read says so", message(noCache) == "Couldn't refresh")

        let notComputed = ChartResolver.content(primary: signups, extras: [],
                                                store: state(errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .noResult)]), links: links, now: now)
        check("state: no result asks to open the insight", message(notComputed) == "Open it in PostHog to load this insight"
              && notComputed.primary.title == "Signups"
              && notComputed.primary.link.absoluteString == "posthog://views/insight/abc123?from=widget&family=medium")
        let cachedMiss = ChartResolver.content(primary: signups, extras: [],
                                               store: state(snapshots: ["pin-a": cached], errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .noResult)]),
                                               links: links, now: now)
        check("state: no result keeps the cache", cachedMiss.primary.snapshot == cached)
        check("fetch plan: no result reads again", ChartResolver.pinsToFetch(
            [signups], store: state(errors: ["pin-a": ChartSnapshotError(at: nowMs, kind: .noResult)]), now: now).count == 1)

        let dashboard = ChartResolver.content(primary: ChartSelection(id: "pin-b", name: "Product KPIs"), extras: [],
                                              store: state(snapshots: ["pin-b": cached]), links: links, now: now)
        check("link: dashboard pin", dashboard.primary.link.absoluteString == "posthog://views/dashboard/12?from=widget&family=medium")
        check("link: scheme per variant", ChartLinks.scheme(forAppId: "com.posthog.code.mobile.dev") == "posthog-dev"
              && ChartLinks.scheme(forAppId: "com.posthog.code.mobile.preview") == "posthog-preview")

        let fresh = ChartSample.snapshot(pinId: "pin-a", value: "1", delta: 0, deltaText: "No change", values: [1], now: now.addingTimeInterval(-60))
        let pins = ChartResolver.pinsToFetch(
            [signups, signups, ChartSelection(id: "pin-b", name: "Product KPIs"), ChartSelection(id: "pin-c", name: "Checkout funnel")],
            store: state(), now: now
        )
        check("fetch plan: each pin once, ineligible left out", pins.map(\.id) == ["pin-a", "pin-b"])
        check("fetch plan: a fresh snapshot is shared", ChartResolver.pinsToFetch([signups], store: state(snapshots: ["pin-a": fresh]), now: now).isEmpty)
        let rewritten = try require(ChartStore.decodeCatalog(catalogJSON.replacingOccurrences(of: "1762270000000", with: "\(Int(nowMs))")), "catalog")
        check("fetch plan: a newer catalog reads again", ChartResolver.pinsToFetch([signups], store: state(catalog: rewritten, snapshots: ["pin-a": fresh]), now: now).count == 1)
        check("fetch plan: a recent 429 waits", ChartResolver.pinsToFetch(
            [signups], store: state(errors: ["pin-a": ChartSnapshotError(at: nowMs - 10_000, kind: .rateLimited)]), now: now).isEmpty)

        let (_, extras) = ChartResolver.selections(
            primary: signups,
            extras: [signups, ChartSelection(id: "pin-b", name: "B"), ChartSelection(id: "pin-b", name: "B"), ChartSelection(id: "pin-d", name: "D"), ChartSelection(id: "pin-c", name: "C")],
            family: .large
        )
        check("large: two extra pins, no repeats", extras.map(\.id) == ["pin-b", "pin-d"])
        check("medium: no extra pins", ChartResolver.selections(primary: signups, extras: extras, family: .medium).1.isEmpty)
    }

    static func checkInsightFormats(now: Date) throws {
        let path = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("modules/chart-widget/fixtures/insights.json")
        let fixtures = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [JSONObject]
        let pin = ChartPin(id: "pin-example", kind: "insight", name: "Example", subtitle: nil,
                           insightId: 101, shortId: "example1", dashboardId: nil, eligible: true,
                           number: true, chart: true, reason: nil)
        for fixture in fixtures {
            let name = fixture["name"] as! String
            let response = fixture["response"] as! JSONObject
            let expected = fixture["expected"] as! JSONObject
            let snapshot = try InsightParser.snapshot(response: response, pin: pin, now: now)
            check("format: \(name) round trip", try JSONDecoder().decode(ChartSnapshot.self, from: JSONEncoder().encode(snapshot)) == snapshot)
            if let interval = expected["intervalLabel"] as? String { check("format: \(name) interval", snapshot.intervalLabel == interval) }
            check("format: \(name) display", snapshot.display == expected["display"] as? String)
            for (field, actual) in [("chartValueText", snapshot.chartValueText), ("axisLowText", snapshot.axisLowText), ("axisHighText", snapshot.axisHighText)] where expected[field] != nil {
                check("format: \(name) \(field)", actual == expected[field] as? String)
            }
            if let value = expected["valueText"] as? String { check("format: \(name) value", snapshot.valueText == value, snapshot.valueText ?? "nil") }
            if expected["valueText"] is NSNull { check("format: \(name) null value", snapshot.valueText == nil) }
            if let value = expected["firstAt"] as? String { check("format: \(name) date", snapshot.series.first?.points.first?.at == value) }
            if let value = expected["firstValue"] as? Double { check("format: \(name) first point", snapshot.series.first?.points.first?.value == value) }
            if expected["lastIsGap"] as? Bool == true { check("format: \(name) gap", snapshot.series.first?.points.last?.value == nil) }
            if let value = expected["firstRowValue"] as? String { check("format: \(name) first row", snapshot.rows?.first?.value == value) }
            if let count = expected["rowCount"] as? Int { check("format: \(name) rows", snapshot.rows?.count == count) }
            if let count = expected["seriesCount"] as? Int { check("format: \(name) series", snapshot.series.count == count) }
            if let value = expected["lastValue"] as? Double { check("format: \(name) last point", snapshot.series.first?.points.last?.value == value) }
        }
        check("SQL: long numeric text stays text", InsightParser.number(String(repeating: "1", count: 16000) + "!") == nil)
        check("SQL: decimals still parse", InsightParser.number(" -1.25e2 ") == -125)
        let start = ChartDates.parse("2026-01-01T00:00:00Z")!
        let formatter = ISO8601DateFormatter()
        let rows: [[Any]] = (0..<10_000).flatMap { index in
            let at = formatter.string(from: start.addingTimeInterval(Double(index) * 3600))
            return [[at, 1], [at, 2]]
        }
        let response: JSONObject = [
            "query": ["kind": "DataVisualizationNode", "source": ["kind": "HogQLQuery"], "display": "ActionsLineGraphCumulative"],
            "columns": ["at", "value"], "types": [["at", "DateTime"], ["value", "UInt64"]], "result": rows,
        ]
        let large = try InsightParser.snapshot(response: response, pin: pin, now: now)
        check("large SQL: only the latest 60 points", large.series.first?.points.count == 60)
        check("large SQL: cumulative includes earlier duplicate rows", large.series.first?.points.first?.value == 29_823
              && large.series.first?.points.last?.value == 30_000)

    }

    static func require<T>(_ value: T?, _ name: String) throws -> T {
        guard let value else {
            check(name, false, "missing")
            throw CheckError.missing(name)
        }
        return value
    }

    enum CheckError: Error {
        case missing(String)
    }
}
