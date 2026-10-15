import Foundation

@main
struct CheckHedgehogTimeline {
    static func main() throws {
        let choreography = FallbackChoreography.value
        let now = choreography.startsAt.addingTimeInterval(120)
        let plan = HedgehogTimelineProvider.plan(for: choreography, now: now)
        precondition(plan.entries.contains { $0.spin != 0 })
        precondition(plan.entries.allSatisfy {
            $0.tick.y == 0 && $0.tick.bubble == nil && ($0.spin == 0 || $0.spin == 360)
                && ($0.orbit == 0 || $0.orbit == 360)
        })
        for (from, to) in zip(plan.entries, plan.entries.dropFirst()) {
            precondition(abs(to.tick.x - from.tick.x) <= 0.060001)
            if to.tick.x != from.tick.x {
                precondition(to.motion == .glide(to.date.timeIntervalSince(from.date)))
                precondition(to.tick.facing == (to.tick.x < from.tick.x ? .left : .right))
            }
            precondition(abs(to.spin - from.spin) <= 360)
            precondition(abs(to.orbit! - from.orbit!) <= 360)
        }
        let stepping = plan.entries.map { entry in
            HedgehogEntry(date: entry.date, tick: entry.tick, spin: entry.spin, motion: .glide(1.6), orbit: entry.orbit)
        }
        let smoothed = HedgehogTimelineProvider.plan(for: choreography, now: now.addingTimeInterval(0.5), previous: stepping)
        precondition(smoothed.entries.allSatisfy { $0.motion == .glide(2) })
        for (old, new) in zip(stepping, smoothed.entries) {
            precondition(old.date == new.date && old.tick == new.tick && old.spin == new.spin && old.orbit == new.orbit)
        }
        let encoded = try JSONEncoder().encode(plan.entries)
        let saved = try JSONDecoder().decode([HedgehogEntry].self, from: encoded)

        for elapsed in [0.5, 7.0, 200.0] {
            let date = now.addingTimeInterval(elapsed)
            let resumed = HedgehogTimelineProvider.plan(for: choreography, now: date, previous: saved)
            let expected = saved.last { $0.date <= date }!
            precondition(resumed.entries[0].tick == expected.tick)
            precondition(resumed.entries[0].spin == expected.spin)
            precondition(resumed.entries[0].date == expected.date)
            precondition(resumed.reloadAt == plan.reloadAt)
            var character: String? = nil
            var seen = Set<String>()
            for _ in 0..<HogSelection.characters.count {
                let next = HogSelection.next(after: character)
                precondition(next != character)
                seen.insert(next)
                character = next
                let dressed = resumed.entries.map { $0.wearing(character) }
                precondition(dressed.allSatisfy { $0.tick.hoggie == character })
                for (original, changed) in zip(resumed.entries, dressed) {
                    precondition(original.tick.x == changed.tick.x && original.tick.y == changed.tick.y)
                    precondition(original.spin == changed.spin && original.motion == changed.motion)
                }
            }
            precondition(seen.count == HogSelection.characters.count)
        }

        let last = plan.entries.last!
        precondition(last.tick.y == 0 && last.spin.truncatingRemainder(dividingBy: 360) == 0)
        for delay in [0.0, 60.0, 86400.0] {
            let next = HedgehogTimelineProvider.plan(for: choreography, now: last.date.addingTimeInterval(delay), previous: saved)
            precondition(next.entries.first!.tick.x == last.tick.x)
            for (from, to) in zip(next.entries, next.entries.dropFirst()) {
                precondition(abs(to.tick.x - from.tick.x) <= 0.060001)
                precondition(to.date.timeIntervalSince(from.date) == Double(choreography.keyframeSec))
                precondition(to.tick.hoggie == nil)
            }
        }
        let airborne = HedgehogEntry(
            date: now, tick: Tick(pose: .jump, frame: 4, x: 0.73, y: 0.8, facing: .left, bubble: "Hello", turn: 0.5),
            spin: 180, motion: .rise(1.5)
        )
        let legacy = [airborne, HedgehogEntry(date: now.addingTimeInterval(20), tick: airborne.tick, spin: 180, motion: .settle)]
        let migrated = HedgehogTimelineProvider.plan(for: choreography, now: now.addingTimeInterval(0.5), previous: legacy)
        precondition(migrated.entries[0].tick.x == airborne.tick.x)
        precondition(migrated.entries.allSatisfy { $0.tick.y == 0 && $0.tick.bubble == nil && $0.spin.truncatingRemainder(dividingBy: 360) == 0 })
        for elapsed in [2.0, 8.0, 60.0, 600.0, 86400.0] {
            let resumed = HedgehogTimelineProvider.plan(for: choreography, now: now.addingTimeInterval(elapsed), previous: saved)
            precondition(resumed.entries[0].tick.y == 0)
            precondition(resumed.entries[0].spin.truncatingRemainder(dividingBy: 360) == 0)
        }
        print("Passed: persistent selection, tap/reload continuity, delayed/skipped updates, legacy flip recovery, silent snapshots and bounded travel")
    }
}
