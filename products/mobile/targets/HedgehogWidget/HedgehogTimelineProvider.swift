import Foundation
import WidgetKit

/// How the hedgehog gets from the previous entry to this one.
enum Motion: Codable, Equatable {
    case settle
    case glide(TimeInterval)
    case rise(TimeInterval)
    case drop(TimeInterval)
}

struct HedgehogEntry: TimelineEntry, Codable {
    let date: Date
    let tick: Tick
    let spin: Double
    let motion: Motion
    var orbit: Double? = nil

    func wearing(_ character: String?) -> HedgehogEntry {
        HedgehogEntry(date: date, tick: Tick(
            pose: tick.pose, frame: tick.frame, x: tick.x, y: tick.y, facing: tick.facing,
            hoggie: character
        ), spin: spin, motion: motion, orbit: orbit)
    }
}

struct HedgehogTimelineProvider: TimelineProvider {
    private static let entryLimit = 270
    private static let longestAnimation: TimeInterval = 2

    struct Plan {
        let entries: [HedgehogEntry]
        let reloadAt: Date
    }

    func placeholder(in context: Context) -> HedgehogEntry {
        HedgehogEntry(date: Date(), tick: FallbackChoreography.value.keyframes[0], spin: 0, motion: .settle)
    }

    func getSnapshot(in context: Context, completion: @escaping (HedgehogEntry) -> Void) {
        completion(placeholder(in: context).wearing(HogSelection.selected(family: String(describing: context.family))))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<HedgehogEntry>) -> Void) {
        let family = String(describing: context.family)
        let key = SharedStore.timelineKey(family: family)
        let cached = SharedStore.defaults?.data(forKey: key).flatMap {
            try? JSONDecoder().decode([HedgehogEntry].self, from: $0)
        } ?? []
        let plan = Self.plan(for: ChoreographyLoader.load(), now: Date(), previous: cached)
        if let data = try? JSONEncoder().encode(plan.entries) {
            SharedStore.defaults?.set(data, forKey: key)
        }
        let character = HogSelection.selected(family: family)
        completion(Timeline(
            entries: plan.entries.map { $0.wearing(character) },
            policy: .after(plan.reloadAt)
        ))
    }

    static func plan(for choreography: Choreography, now: Date, previous: [HedgehogEntry] = []) -> Plan {
        if let end = previous.last?.date, end > now, previous.allSatisfy({ ($0.orbit == 0 || $0.orbit == 360) && ($0.spin == 0 || $0.spin == 360) }) {
            let current = previous.lastIndex { $0.date <= now } ?? 0
            let remaining = previous[current...].map { entry in
                HedgehogEntry(date: entry.date, tick: entry.tick, spin: entry.spin,
                              motion: entry.motion == .settle ? .settle : .glide(longestAnimation), orbit: entry.orbit)
            }
            return Plan(entries: remaining, reloadAt: end)
        }

        let step = TimeInterval(max(choreography.keyframeSec, 2))
        let keyframes = choreography.keyframes
        var index = Int(floor(now.timeIntervalSince(choreography.startsAt) / step))
        func wrapped(_ index: Int) -> Int { ((index % keyframes.count) + keyframes.count) % keyframes.count }
        let anchor = previous.last { $0.date <= now }
        let start = (anchor?.tick ?? keyframes[wrapped(index)]).grounded
        // Bounded endpoints prevent skipped updates from combining several flips into one rapid spin.
        var spin = abs(((anchor?.spin ?? 0) / 360).rounded().truncatingRemainder(dividingBy: 2)) * 360
        var orbit = abs(((anchor?.orbit ?? 0) / 360).rounded().truncatingRemainder(dividingBy: 2)) * 360
        var entries = [HedgehogEntry(
            date: now, tick: Tick(pose: .idle, frame: 0, x: start.x, y: 0, facing: start.facing),
            spin: spin, motion: .settle, orbit: orbit
        )]

        func append(_ tick: Tick) {
            entries.append(HedgehogEntry(
                date: now.addingTimeInterval(Double(entries.count) * step), tick: tick,
                spin: spin, motion: .glide(min(step, longestAnimation)), orbit: orbit
            ))
        }

        while entries.count < entryLimit {
            index += 1
            let target = keyframes[wrapped(index)]
            let prior = entries[entries.count - 1].tick
            if target.pose == .walk && abs(target.x - prior.x) > 0.025 {
                let facing: Facing = target.x < prior.x ? .left : .right
                let distance = target.x - prior.x
                let steps = Int(ceil(abs(distance) / 0.06))
                for part in 1...steps where entries.count < entryLimit {
                    append(Tick(
                        pose: .walk, frame: target.frame, x: prior.x + distance * Double(part) / Double(steps),
                        y: 0, facing: facing
                    ))
                }
            } else {
                let jumping = target.y > 0 && keyframes[wrapped(index - 1)].y == 0
                if jumping {
                    orbit = orbit == 0 ? 360 : 0
                    if let turn = target.turn, turn != 0 {
                        spin = spin == 0 ? 360 : 0
                    }
                }
                append(Tick(pose: jumping ? .idle : target.pose, frame: jumping ? 0 : target.frame,
                            x: prior.x, y: 0, facing: prior.facing))
            }
        }
        return Plan(entries: entries, reloadAt: entries[entries.count - 1].date)
    }
}
