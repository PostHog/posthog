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

    func wearing(_ character: String?) -> HedgehogEntry {
        HedgehogEntry(date: date, tick: Tick(
            pose: tick.pose, frame: tick.frame, x: tick.x, y: tick.y, facing: tick.facing,
            bubble: tick.bubble, turn: tick.turn, hoggie: character
        ), spin: spin, motion: motion)
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
        if let end = previous.last?.date, end > now {
            let current = previous.lastIndex { $0.date <= now } ?? 0
            return Plan(entries: Array(previous[current...]), reloadAt: end)
        }

        let step = TimeInterval(choreography.keyframeSec)
        let keyframes = choreography.keyframes
        let angles = spins(for: keyframes)
        let index = Int(floor(now.timeIntervalSince(choreography.startsAt) / step))
        func wrapped(_ index: Int) -> Int { ((index % keyframes.count) + keyframes.count) % keyframes.count }
        let start = previous.last?.tick.grounded ?? keyframes[wrapped(index)].grounded
        var entries = [HedgehogEntry(date: now, tick: start, spin: 0, motion: .settle)]
        for offset in 1..<(entryLimit - 1) {
            let target = keyframes[wrapped(index + offset)]
            let prior = entries[entries.count - 1].tick
            let x = prior.x + min(max(target.x - prior.x, -0.12), 0.12)
            let tick = Tick(
                pose: target.pose, frame: target.frame,
                x: x, y: target.y, facing: target.pose == .walk && x != prior.x ? (x < prior.x ? .left : .right) : target.facing,
                bubble: target.bubble, turn: target.turn
            )
            entries.append(HedgehogEntry(
                date: now.addingTimeInterval(Double(offset) * step), tick: tick,
                spin: angles[wrapped(index + offset)],
                motion: motion(from: prior, to: tick, gap: step)
            ))
        }
        let last = entries[entries.count - 1]
        let finishingFlip = last.spin.truncatingRemainder(dividingBy: 360) != 0
        let landedSpin = finishingFlip ? (last.spin > 0 ? ceil(last.spin / 360) : floor(last.spin / 360)) * 360 : last.spin
        let resting = Tick(
            pose: .idle, frame: 0, x: last.tick.x, y: 0, facing: last.tick.facing,
            turn: finishingFlip ? (landedSpin - last.spin) / 360 : nil
        )
        entries.append(HedgehogEntry(
            date: last.date.addingTimeInterval(step), tick: resting, spin: landedSpin,
            motion: motion(from: last.tick, to: resting, gap: step)
        ))
        return Plan(entries: entries, reloadAt: entries[entries.count - 1].date)
    }

    static func spins(for ticks: [Tick]) -> [Double] {
        var turns = 0.0
        return ticks.map { tick in
            turns = (tick.turn ?? 0) == 0 ? 0 : turns + (tick.turn ?? 0)
            return turns * 360
        }
    }

    static func motion(from previous: Tick?, to tick: Tick, gap: TimeInterval) -> Motion {
        guard let previous else { return .settle }
        if tick.y > previous.y { return .rise(min(gap * 0.75, 1.5)) }
        if tick.y < previous.y { return .drop(min(gap * 0.5, 1)) }
        if abs(tick.x - previous.x) > 0.001 { return .glide(min(gap, longestAnimation)) }
        return .settle
    }
}
