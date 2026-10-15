import Foundation
import os

// The shapes below follow "Choreography JSON (version 1)" in modules/hedgehog-widget/README.md.
// The app's JavaScript writes the JSON, so a change here needs the same change there.

enum Pose: String, Codable {
    case idle, walk, jump, wave, action, fall

    var frameCount: Int {
        switch self {
        case .idle: 25
        case .walk: 11
        case .jump: 10
        case .wave: 26
        case .action: 16
        case .fall: 9
        }
    }
}

enum Facing: String, Codable {
    case left, right
}

struct Tick: Codable, Equatable {
    let pose: Pose
    let frame: Int
    let x: Double
    let y: Double
    let facing: Facing
    let bubble: String?
    /// Turns added on the way into this tick, clockwise on screen. A flip is two ticks of half a turn each.
    let turn: Double?
    let hoggie: String?

    init(pose: Pose, frame: Int, x: Double, y: Double, facing: Facing, bubble: String? = nil, turn: Double? = nil, hoggie: String? = nil) {
        self.pose = pose
        self.frame = frame
        self.x = x
        self.y = y
        self.facing = facing
        self.bubble = bubble
        self.turn = turn
        self.hoggie = hoggie
    }

    /// Feet on the floor and no flip, for an entry shown without the keyframes around it.
    var grounded: Tick {
        Tick(pose: y > 0 ? .idle : pose, frame: frame, x: x, y: 0, facing: facing, bubble: bubble, hoggie: hoggie)
    }

    /// An out-of-range frame would name a sprite that does not exist and render nothing.
    var spriteName: String {
        let index = ((frame % pose.frameCount) + pose.frameCount) % pose.frameCount
        return String(format: "hog_%@_%02d", pose.rawValue, index)
    }
}

struct Reaction: Codable {
    let keyframes: [Tick]
    let ticks: [Tick]
}

struct Choreography: Codable {
    let version: Int
    let seed: Int
    let generatedAt: Date
    let startsAt: Date
    let keyframeSec: Int
    let keyframes: [Tick]
    let tickMs: Int
    let loopMinutes: Int
    let loops: [[Tick]]
    let reaction: Reaction
    var surprises: [Reaction]? = nil

    func reaction(at poke: Date) -> Reaction {
        guard let surprises, !surprises.isEmpty else { return reaction }
        let index = Int(poke.timeIntervalSince1970 * 1000) % surprises.count
        return surprises[(index + surprises.count) % surprises.count]
    }

    static let supportedVersion = 1
}

enum SharedStore {
    static let suiteName = "group.com.posthog.code.mobile"
    static let choreographyKey = "choreography"

    static var defaults: UserDefaults? { UserDefaults(suiteName: suiteName) }

    static func selectedHogKey(family: String) -> String { "selectedHog.\(family)" }
    static func timelineKey(family: String) -> String { "timeline.v2.\(family)" }
}

enum HogSelection {
    static let characters = ["coffee_cup", "party", "wizard", "explorer", "asleep", "superhero", "reading", "float"]

    static func next(after current: String?) -> String {
        guard let current, let index = characters.firstIndex(of: current) else { return characters[0] }
        return characters[(index + 1) % characters.count]
    }

    static func selected(family: String) -> String? {
        SharedStore.defaults?.string(forKey: SharedStore.selectedHogKey(family: family))
    }
}

enum ChoreographyLoader {
    private static let logger = Logger(subsystem: "com.posthog.code.mobile.HedgehogWidget", category: "choreography")

    static func load() -> Choreography {
        guard let json = SharedStore.defaults?.string(forKey: SharedStore.choreographyKey) else {
            return FallbackChoreography.value
        }
        do {
            let choreography = try decoder.decode(Choreography.self, from: Data(json.utf8))
            guard choreography.version == Choreography.supportedVersion,
                  !choreography.keyframes.isEmpty,
                  choreography.keyframeSec > 0
            else {
                logger.error("Unsupported choreography: version \(choreography.version), \(choreography.keyframes.count) keyframes, keyframeSec \(choreography.keyframeSec)")
                return FallbackChoreography.value
            }
            return choreography
        } catch {
            logger.error("Choreography does not decode: \(String(describing: error), privacy: .public)")
            return FallbackChoreography.value
        }
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        // JavaScript's toISOString() writes fractional seconds, which the built-in .iso8601 strategy rejects.
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let whole = ISO8601DateFormatter()
        whole.formatOptions = [.withInternetDateTime]
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let text = try container.decode(String.self)
            if let date = fractional.date(from: text) ?? whole.date(from: text) {
                return date
            }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Not an ISO 8601 date: \(text)")
        }
        return decoder
    }()
}

enum FallbackChoreography {
    static let value: Choreography = {
        // A fixed start keeps every widget on the device on the same keyframe for the same beat.
        let startsAt = Date(timeIntervalSince1970: 1_767_225_600)
        var keyframes: [Tick] = []
        for step in 0...4 {
            keyframes.append(Tick(pose: .walk, frame: step * 2, x: 0.15 + Double(step) * 0.15, y: 0, facing: .right))
        }
        keyframes.append(Tick(pose: .jump, frame: 4, x: 0.8, y: 0.8, facing: .right, turn: 0.5))
        keyframes.append(Tick(pose: .jump, frame: 9, x: 0.85, y: 0, facing: .right, turn: 0.5))
        keyframes.append(Tick(pose: .wave, frame: 8, x: 0.85, y: 0, facing: .left, bubble: "Hi there!"))
        keyframes.append(Tick(pose: .wave, frame: 14, x: 0.85, y: 0, facing: .left, bubble: "Hi there!"))
        keyframes.append(Tick(pose: .idle, frame: 12, x: 0.85, y: 0, facing: .left))
        keyframes.append(Tick(pose: .jump, frame: 4, x: 0.72, y: 0.35, facing: .left))
        keyframes.append(Tick(pose: .jump, frame: 9, x: 0.62, y: 0, facing: .left))
        for step in 0...3 {
            keyframes.append(Tick(pose: .walk, frame: step * 3, x: 0.5 - Double(step) * 0.12, y: 0, facing: .left))
        }
        keyframes.append(Tick(pose: .idle, frame: 6, x: 0.15, y: 0, facing: .right))

        let reaction = Reaction(
            keyframes: [
                Tick(pose: .jump, frame: 4, x: 0.5, y: 0.8, facing: .right, turn: 0.5),
                Tick(pose: .jump, frame: 9, x: 0.5, y: 0, facing: .right, turn: 0.5),
                Tick(pose: .wave, frame: 10, x: 0.5, y: 0, facing: .right, bubble: "Hey!"),
                Tick(pose: .idle, frame: 0, x: 0.5, y: 0, facing: .right),
            ],
            ticks: []
        )

        return Choreography(
            version: Choreography.supportedVersion,
            seed: 0,
            generatedAt: startsAt,
            startsAt: startsAt,
            keyframeSec: 2,
            keyframes: keyframes,
            tickMs: 120,
            loopMinutes: 10,
            loops: [],
            reaction: reaction,
            surprises: ["party", "wizard", "superhero"].map { hoggie in
                Reaction(
                    keyframes: [
                        Tick(pose: .wave, frame: 10, x: 0.5, y: 0, facing: .right, bubble: "Hi there!", hoggie: hoggie),
                        Tick(pose: .jump, frame: 4, x: 0.5, y: 0.2, facing: .right, hoggie: hoggie),
                        Tick(pose: .idle, frame: 0, x: 0.5, y: 0, facing: .right, bubble: "Ta-da!", hoggie: hoggie),
                    ],
                    ticks: []
                )
            }
        )
    }()
}
