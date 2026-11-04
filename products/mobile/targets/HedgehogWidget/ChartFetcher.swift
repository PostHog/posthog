import Foundation

enum ChartFetchOutcome: Equatable, Sendable {
    case snapshot(ChartSnapshot)
    case failed(ChartErrorKind)
}

/// One cache-only insight read with the app's session. The widget never sends `blocking` or `force_blocking`: it only
/// reads what the server already computed, the cheap lane in docs/VIEWS.md "Refresh".
struct ChartFetcher {
    static let timeout: TimeInterval = 20

    // Ephemeral, so responses read with the user's token never land in a disk cache.
    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout
        configuration.waitsForConnectivity = false
        configuration.urlCache = nil
        return URLSession(configuration: configuration)
    }()

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    static func url(for pin: ChartPin, host: String, projectId: Int) -> URL? {
        let base = host.hasSuffix("/") ? String(host.dropLast()) : host
        if let insightId = pin.insightId {
            var components = URLComponents(string: "\(base)/api/projects/\(projectId)/insights/\(insightId)/")
            var items = [URLQueryItem(name: "refresh", value: "force_cache")]
            if pin.isDashboard, let dashboardId = pin.dashboardId {
                items.append(URLQueryItem(name: "from_dashboard", value: String(dashboardId)))
            }
            components?.queryItems = items
            return components?.url
        }
        guard let shortId = pin.shortId, !shortId.isEmpty else { return nil }
        var components = URLComponents(string: "\(base)/api/projects/\(projectId)/insights/")
        components?.queryItems = [
            URLQueryItem(name: "short_id", value: shortId),
            URLQueryItem(name: "refresh", value: "force_cache"),
        ]
        return components?.url
    }

    static func request(for pin: ChartPin, credentials: ChartCredentials, appVersion: String) -> URLRequest? {
        guard let url = url(for: pin, host: credentials.host, projectId: credentials.projectId) else { return nil }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.setValue("Bearer \(credentials.accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("posthog-mobile-widget/\(appVersion) (ios)", forHTTPHeaderField: "User-Agent")
        return request
    }

    static func outcome(status: Int, body: Data, pin: ChartPin, now: Date) -> ChartFetchOutcome {
        switch status {
        case 200:
            return parse(body, pin: pin, now: now)
        case 401, 403:
            return .failed(.auth)
        case 404:
            return .failed(.notFound)
        case 429, 503:
            return .failed(.rateLimited)
        case 500...:
            // Other server errors pass like a dropped connection, so the cache stays on screen.
            return .failed(.network)
        default:
            return .failed(.badData)
        }
    }

    /// Only a response with a result and no error may change the snapshot (`hasGoodResult` in insightSnapshot.ts). A
    /// rate-limited answer is a 200 with `result: null`.
    private static func parse(_ body: Data, pin: ChartPin, now: Date) -> ChartFetchOutcome {
        guard let json = (try? JSONSerialization.jsonObject(with: body)) as? JSONObject else {
            return .failed(.badData)
        }
        var response = json
        if pin.insightId == nil {
            let results = (json["results"] as? [Any])?.compactMap { $0 as? JSONObject } ?? []
            guard let match = results.first(where: { $0["short_id"] as? String == pin.shortId }) else {
                return .failed(.notFound)
            }
            response = match
        }
        let status = response["query_status"] as? JSONObject
        if status?["error_code"] as? String == "rate_limited" {
            return .failed(.rateLimited)
        }
        if TrendsParser.isTruthy(status?["error"]) {
            return .failed(.badData)
        }
        if response["result"] == nil || response["result"] is NSNull {
            return .failed(.noResult)
        }
        guard let snapshot = try? TrendsParser.snapshot(response: response, pinId: pin.id, now: now) else {
            return .failed(.badData)
        }
        return .snapshot(snapshot)
    }

    func fetch(pin: ChartPin, credentials: ChartCredentials, now: Date) async -> ChartFetchOutcome {
        guard let request = Self.request(for: pin, credentials: credentials, appVersion: Self.appVersion) else {
            return .failed(.badData)
        }
        do {
            let (data, response) = try await Self.session.data(for: request)
            guard let http = response as? HTTPURLResponse else { return .failed(.network) }
            return Self.outcome(status: http.statusCode, body: data, pin: pin, now: now)
        } catch {
            return .failed(.network)
        }
    }
}

/// Reads each pin once at a time in this process, so widgets that show the same pin share one request.
actor ChartRefresh {
    static let shared = ChartRefresh()

    private var running: [String: Task<Void, Never>] = [:]

    func refresh(_ pin: ChartPin, credentials: ChartCredentials, now: Date) async {
        if let task = running[pin.id] {
            await task.value
            return
        }
        let task = Task {
            let outcome = await ChartFetcher().fetch(pin: pin, credentials: credentials, now: now)
            Self.record(outcome, pinId: pin.id, at: now)
        }
        running[pin.id] = task
        await task.value
        running[pin.id] = nil
    }

    static func record(_ outcome: ChartFetchOutcome, pinId: String, at now: Date, store: UserDefaults? = ChartStore.defaults) {
        switch outcome {
        case .snapshot(let snapshot):
            ChartStore.save(snapshot, store: store)
        case .failed(let kind):
            ChartStore.save(ChartSnapshotError(at: (now.timeIntervalSince1970 * 1000).rounded(), kind: kind), pinId: pinId, store: store)
        }
    }
}
