import Foundation

@main
struct CheckHedgehogTimeline {
    static func main() throws {
        let choreography = FallbackChoreography.value
        let now = choreography.startsAt.addingTimeInterval(120)
        let plan = HedgehogTimelineProvider.plan(for: choreography, now: now)
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
                precondition(abs(to.tick.x - from.tick.x) <= 0.120001)
                precondition(to.date.timeIntervalSince(from.date) == Double(choreography.keyframeSec))
                precondition(to.tick.hoggie == nil)
            }
        }
        print("Passed: persistent selection, tap/reload continuity, delayed refresh and bounded travel")
    }
}
