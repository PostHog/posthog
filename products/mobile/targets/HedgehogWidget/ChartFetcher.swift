import Foundation

enum ChartFetchOutcome: Equatable, Sendable {
    case snapshot(ChartSnapshot)
    case failed(ChartErrorKind)
}

/// One cache-only insight read with the app's session. The widget never sends `blocking` or `force_blocking`: it only
/// reads what the server already computed, the cheap lane in docs/VIEWS.md "Refresh".
struct ChartFetcher {
    static let timeout: TimeInterval = 20
    static let maxResponseBytes = 1_048_576

    enum ResponseError: Error {
        case tooLarge
    }

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

    static func readBody<Bytes: AsyncSequence>(
        _ bytes: Bytes, expectedLength: Int64, limit: Int = maxResponseBytes
    ) async throws -> Data where Bytes.Element == UInt8 {
        guard expectedLength <= Int64(limit) else { throw ResponseError.tooLarge }
        var data = Data()
        if expectedLength > 0 {
            data.reserveCapacity(Int(expectedLength))
        }
        for try await byte in bytes {
            guard data.count < limit else { throw ResponseError.tooLarge }
            data.append(byte)
        }
        return data
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
        guard let snapshot = try? InsightParser.snapshot(response: response, pin: pin, now: now) else {
            return .failed(.badData)
        }
        return .snapshot(snapshot)
    }

    func fetch(pin: ChartPin, credentials: ChartCredentials, now: Date) async -> ChartFetchOutcome {
        guard let request = Self.request(for: pin, credentials: credentials, appVersion: Self.appVersion) else {
            return .failed(.badData)
        }
        do {
            let (bytes, response) = try await Self.session.bytes(for: request)
            defer { bytes.task.cancel() }
            guard let http = response as? HTTPURLResponse else { return .failed(.network) }
            guard http.statusCode == 200 else {
                return Self.outcome(status: http.statusCode, body: Data(), pin: pin, now: now)
            }
            let data = try await Self.readBody(bytes, expectedLength: response.expectedContentLength)
            return Self.outcome(status: http.statusCode, body: data, pin: pin, now: now)
        } catch ResponseError.tooLarge {
            return .failed(.badData)
        } catch {
            return .failed(.network)
        }
    }
}

/// Widgets share a request only while their pin points at the same insight and dashboard context.
actor ChartRefresh {
    static let shared = ChartRefresh()

    private struct RequestKey: Hashable {
        let pinId: String
        let url: URL
        let displayMode: String?
        let accessToken: String
        let userUuid: String?
    }

    private let store: ChartStorage?
    private let currentCredentials: @Sendable () -> ChartCredentials?
    private let fetch: @Sendable (ChartPin, ChartCredentials, Date) async -> ChartFetchOutcome
    private var running: [RequestKey: Task<Void, Never>] = [:]

    init(
        store: ChartStorage? = ChartStore.storage,
        currentCredentials: @escaping @Sendable () -> ChartCredentials? = { ChartStore.credentials() },
        fetch: @escaping @Sendable (ChartPin, ChartCredentials, Date) async -> ChartFetchOutcome = {
            await ChartFetcher().fetch(pin: $0, credentials: $1, now: $2)
        }
    ) {
        self.store = store
        self.currentCredentials = currentCredentials
        self.fetch = fetch
    }

    private static func key(for pin: ChartPin, credentials: ChartCredentials) -> RequestKey? {
        ChartFetcher.url(for: pin, host: credentials.host, projectId: credentials.projectId).map {
            RequestKey(pinId: pin.id, url: $0, displayMode: pin.displayMode,
                       accessToken: credentials.accessToken, userUuid: credentials.userUuid)
        }
    }

    func refresh(_ pin: ChartPin, credentials: ChartCredentials, now: Date) async {
        guard let key = Self.key(for: pin, credentials: credentials) else { return }
        if let task = running[key] {
            await task.value
            return
        }
        let task = Task {
            let outcome = await fetch(pin, credentials, now)
            guard currentCredentials() == credentials else { return }
            Self.record(outcome, pin: pin, credentials: credentials, at: now, store: store)
        }
        running[key] = task
        await task.value
        running[key] = nil
    }

    static func record(
        _ outcome: ChartFetchOutcome, pin: ChartPin, credentials: ChartCredentials, at now: Date,
        store: ChartStorage? = ChartStore.storage
    ) {
        guard let catalog = ChartStore.catalog(store: store), catalog.belongs(to: credentials),
              let current = catalog.pin(id: pin.id), current.eligible,
              let originalKey = key(for: pin, credentials: credentials),
              key(for: current, credentials: credentials) == originalKey
        else {
            return
        }
        switch outcome {
        case .snapshot(let snapshot):
            ChartStore.save(snapshot, store: store)
        case .failed(let kind):
            let startedAt = (now.timeIntervalSince1970 * 1000).rounded()
            if let snapshot = ChartStore.snapshot(pinId: pin.id, store: store), snapshot.fetchedAt > startedAt { return }
            if kind == .auth || kind == .notFound {
                store?.removeObject(forKey: ChartStore.snapshotKey(pin.id))
            }
            ChartStore.save(ChartSnapshotError(at: (now.timeIntervalSince1970 * 1000).rounded(), kind: kind), pinId: pin.id, store: store)
        }
    }
}
