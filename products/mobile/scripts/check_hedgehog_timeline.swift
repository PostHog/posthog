import Foundation

// Usage: check-hoglet [choreography.json ...]
// Each JSON file is checked like the built-in fallback, for example a script the app wrote.

@main
struct CheckHedgehogTimeline {
    static let step: TimeInterval = 2
    static let reach = HedgehogTimelineProvider.walkSpeed * step

    static func main() throws {
        var scripts: [(String, Choreography)] = [("fallback", FallbackChoreography.value), ("inline", try decode(inlineScript))]
        for path in CommandLine.arguments.dropFirst() {
            scripts.append((path, try ChoreographyLoader.decode(Data(contentsOf: URL(fileURLWithPath: path)))))
        }
        for (name, choreography) in scripts {
            let jumps = try checkMotionScript(choreography)
            print("\(name): \(choreography.keyframes.count) keyframes, \(jumps) jump entries checked")
        }
        checkLegacyScript()
        try checkOlderSavedTimeline()
        print("Passed: walk glides, jump airtime/bounces/flips, upright landings, resume and delayed refreshes, character cycling, scripts without motion, timelines from older builds")
    }

    /// Plans a motion-bearing script and checks every entry against the keyframe it plays.
    static func checkMotionScript(_ choreography: Choreography) throws -> Int {
        let now = choreography.startsAt.addingTimeInterval(120)
        let plan = HedgehogTimelineProvider.plan(for: choreography, now: now)
        let keyframes = choreography.keyframes
        func keyframe(_ index: Int) -> Tick { keyframes[((index % keyframes.count) + keyframes.count) % keyframes.count] }

        checkUpright(plan.entries)
        precondition(plan.entries[0].motion == .settle && !plan.entries[0].airborne && plan.entries[0].spin == 0)
        var index = Int(floor(now.timeIntervalSince(choreography.startsAt) / step))
        var jumps = 0
        for (from, to) in zip(plan.entries, plan.entries.dropFirst()) {
            precondition(to.date.timeIntervalSince(from.date) == step)
            index += 1
            let target = keyframe(index)
            guard abs(to.tick.x - target.x) < 1e-9 else {
                // A catch-up walk towards a keyframe that is out of reach; the keyframe plays after it.
                index -= 1
                precondition(to.tick.pose == .walk && !to.airborne && to.motion == .glide(step))
                precondition(abs(abs(to.tick.x - from.tick.x) - reach) < 1e-9)
                continue
            }
            guard let motion = target.motion else { continue }
            switch motion.kind {
            case "walk", "idle":
                precondition(!to.airborne && to.spin == 0)
                precondition(to.motion == .glide(step), "walk and idle entries glide over the whole beat")
                precondition(to.tick.facing == target.facing && to.tick.pose == target.pose && to.tick.frame == target.frame)
                precondition(abs(to.tick.x - from.tick.x) <= reach + 0.01, "no faster than hedgehog-mode's walk")
            case "jump":
                jumps += 1
                let flights = [TickMotion.Bounce(airtime: min(motion.airtime!, step), apex: motion.apex!)] + (motion.bounces ?? [])
                let direction: Double = target.facing == .right ? -1 : 1
                var takeoff = 0.0
                for layer in 0..<HedgehogTimelineProvider.hopLayers {
                    let hop = to.hop(layer)
                    guard layer < flights.count, takeoff + flights[layer].airtime <= step + 1e-9 else {
                        precondition(hop.duration == 0 && hop.degrees == 0)
                        continue
                    }
                    precondition(hop.delay == takeoff && hop.duration == flights[layer].airtime, "airtime drives the hop")
                    precondition(hop.apex == flights[layer].apex)
                    precondition(hop.degrees - from.hop(layer).degrees == direction * 360, "one whole loop per hop")
                    if !from.airborne {
                        precondition(from.hop(layer).apex == hop.apex, "the anchor moves before the hop, not during it")
                    }
                    takeoff += hop.duration
                }
                precondition(to.motion == .glide(takeoff), "drift glides over the time in the air")
                precondition(to.spin - from.spin == (motion.turns ?? 0) * 360)
                precondition(to.tick.pose == .fall && to.tick.y == 0 && to.tick.facing == target.facing)
            default:
                break
            }
        }

        try checkResume(choreography, plan: plan, now: now)
        return jumps
    }

    /// Every entry ends on the floor on whole turns, so a skipped or late update cannot leave the hog in the air.
    static func checkUpright(_ entries: [HedgehogEntry]) {
        for entry in entries {
            precondition(entry.tick.y == 0 && entry.tick.bubble == nil && entry.tick.hoggie == nil)
            precondition(entry.spin.truncatingRemainder(dividingBy: 360) == 0)
            precondition(entry.hops?.count == HedgehogTimelineProvider.hopLayers)
            for layer in 0..<HedgehogTimelineProvider.hopLayers {
                let hop = entry.hop(layer)
                precondition(hop.degrees.truncatingRemainder(dividingBy: 360) == 0)
                precondition(hop.delay + hop.duration <= step + 1e-9)
                precondition(hop.duration > 0 || entry.hop(layer).degrees == 0, "a grounded layer resets to zero")
            }
            if !entry.airborne {
                precondition(entry.spin == 0)
            }
        }
    }

    static func same(_ a: HedgehogEntry, _ b: HedgehogEntry) -> Bool {
        a.date == b.date && a.tick == b.tick && a.spin == b.spin && a.motion == b.motion && a.hops == b.hops
    }

    static func checkResume(_ choreography: Choreography, plan: HedgehogTimelineProvider.Plan, now: Date) throws {
        let saved = try JSONDecoder().decode([HedgehogEntry].self, from: JSONEncoder().encode(plan.entries))
        for elapsed in [0.5, 7.0, 200.0] {
            let date = now.addingTimeInterval(elapsed)
            let resumed = HedgehogTimelineProvider.plan(for: choreography, now: date, previous: saved)
            let current = saved.lastIndex { $0.date <= date }!
            precondition(resumed.entries.count == saved.count - current)
            precondition(zip(resumed.entries, saved[current...]).allSatisfy(same), "a refresh keeps the saved timeline")
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
                    precondition(original.spin == changed.spin && original.motion == changed.motion && original.hops == changed.hops)
                }
            }
            precondition(seen.count == HogSelection.characters.count)
        }

        let last = saved.last!
        for delay in [0.0, 60.0, 86400.0] {
            let next = HedgehogTimelineProvider.plan(for: choreography, now: last.date.addingTimeInterval(delay), previous: saved)
            precondition(next.entries[0].tick.x == last.tick.x, "a new timeline starts where the last one ended")
            precondition(next.entries[0].spin == 0 && !next.entries[0].airborne && next.entries[0].motion == .settle)
            checkUpright(next.entries)
            for (from, to) in zip(next.entries, next.entries.dropFirst()) where !to.airborne {
                precondition(abs(to.tick.x - from.tick.x) <= reach + 0.01)
            }
        }
    }

    /// A script without `motion`: jumps come from `y`, flips from `turn`, and walks still glide over the beat.
    static func checkLegacyScript() {
        let choreography = legacyScript
        let now = choreography.startsAt.addingTimeInterval(120)
        let plan = HedgehogTimelineProvider.plan(for: choreography, now: now)
        checkUpright(plan.entries)
        precondition(plan.entries.contains { $0.airborne && $0.spin != 0 }, "half-turn markers still flip")
        precondition(plan.entries.contains { $0.airborne && $0.spin == 0 }, "a jump without turn markers only hops")
        for (from, to) in zip(plan.entries, plan.entries.dropFirst()) {
            if to.airborne {
                precondition(to.hop(0).duration == 0.9 && to.hop(1).duration == 0 && to.tick.x == from.tick.x)
                precondition(to.tick.pose == .fall && to.motion == .glide(0.9))
            } else if to.tick.x != from.tick.x {
                precondition(to.tick.pose == .walk && to.motion == .glide(step))
                precondition(to.tick.facing == (to.tick.x < from.tick.x ? .left : .right))
                precondition(abs(to.tick.x - from.tick.x) <= reach + 0.01)
            }
        }
        let saved = try! JSONDecoder().decode([HedgehogEntry].self, from: JSONEncoder().encode(plan.entries))
        let resumed = HedgehogTimelineProvider.plan(for: choreography, now: now.addingTimeInterval(30), previous: saved)
        precondition(resumed.entries.allSatisfy { entry in saved.contains { same($0, entry) } })
    }

    /// Entries saved by an older build have no hops and may hold a half turn. The next plan starts upright where they were.
    static func checkOlderSavedTimeline() throws {
        let choreography = FallbackChoreography.value
        let now = choreography.startsAt.addingTimeInterval(120)
        let reference = now.timeIntervalSinceReferenceDate
        let json = """
        [{"date": \(reference - 1), "tick": {"pose": "jump", "frame": 4, "x": 0.73, "y": 0.8, "facing": "left", "bubble": "Hello", "turn": 0.5},
          "spin": 180, "orbit": 360, "motion": {"rise": {"_0": 1.5}}},
         {"date": \(reference + 20), "tick": {"pose": "idle", "frame": 0, "x": 0.73, "y": 0, "facing": "left"},
          "spin": 0, "orbit": 0, "motion": {"settle": {}}}]
        """
        let legacy = try JSONDecoder().decode([HedgehogEntry].self, from: Data(json.utf8))
        precondition(legacy.allSatisfy { $0.hops == nil })
        let migrated = HedgehogTimelineProvider.plan(for: choreography, now: now.addingTimeInterval(0.5), previous: legacy)
        precondition(migrated.entries[0].tick.x == 0.73 && migrated.entries[0].tick.facing == .left)
        checkUpright(migrated.entries)
    }

    static func decode(_ json: String) throws -> Choreography {
        try ChoreographyLoader.decode(Data(json.utf8))
    }

    /// The JSON contract, including a double jump without bounces and a kind this build does not know.
    static let inlineScript = """
    {"version": 1, "seed": 7, "generatedAt": "2026-10-15T00:00:00.000Z", "startsAt": "2026-10-15T00:00:00.000Z",
     "keyframeSec": 2, "tickMs": 120, "loopMinutes": 10, "loops": [], "reaction": {"keyframes": [], "ticks": []},
     "keyframes": [
      {"pose": "idle", "frame": 3, "x": 0.4, "y": 0, "facing": "right", "motion": {"kind": "idle"}},
      {"pose": "walk", "frame": 2, "x": 0.85, "y": 0, "facing": "right", "motion": {"kind": "walk"}},
      {"pose": "walk", "frame": 5, "x": 0.95, "y": 0, "facing": "right", "motion": {"kind": "walk"}},
      {"pose": "walk", "frame": 8, "x": 0.6, "y": 0, "facing": "left", "motion": {"kind": "walk"}},
      {"pose": "fall", "frame": 2, "x": 0.58, "y": 0, "facing": "left",
       "motion": {"kind": "jump", "airtime": 0.9, "apex": 1, "bounces": [{"airtime": 0.45, "apex": 0.25}, {"airtime": 0.22, "apex": 0.0625}, {"airtime": 0.11, "apex": 0.016}]}},
      {"pose": "fall", "frame": 6, "x": 0.58, "y": 0, "facing": "right", "motion": {"kind": "jump", "airtime": 0.9, "apex": 1, "bounces": [], "turns": 1}},
      {"pose": "fall", "frame": 6, "x": 0.58, "y": 0, "facing": "right", "motion": {"kind": "jump", "airtime": 1.5, "apex": 1, "bounces": [{"airtime": 0.45, "apex": 0.25}, {"airtime": 0.22, "apex": 0.0625}]}},
      {"pose": "wave", "frame": 10, "x": 0.58, "y": 0, "facing": "right", "motion": {"kind": "teleport"}},
      {"pose": "walk", "frame": 1, "x": 0.4, "y": 0, "facing": "left", "motion": {"kind": "walk"}}
     ]}
    """

    /// The built-in routine before `motion` existed.
    static let legacyScript: Choreography = {
        let fallback = FallbackChoreography.value
        var keyframes: [Tick] = []
        for step in 0...4 {
            keyframes.append(Tick(pose: .walk, frame: step * 2, x: 0.15 + Double(step) * 0.15, y: 0, facing: .right))
        }
        keyframes.append(Tick(pose: .jump, frame: 4, x: 0.8, y: 0.8, facing: .right, turn: 0.5))
        keyframes.append(Tick(pose: .jump, frame: 9, x: 0.85, y: 0, facing: .right, turn: 0.5))
        keyframes.append(Tick(pose: .wave, frame: 8, x: 0.85, y: 0, facing: .left, bubble: "Hi there!"))
        keyframes.append(Tick(pose: .idle, frame: 12, x: 0.85, y: 0, facing: .left))
        keyframes.append(Tick(pose: .jump, frame: 4, x: 0.72, y: 0.35, facing: .left))
        keyframes.append(Tick(pose: .jump, frame: 9, x: 0.62, y: 0, facing: .left))
        for step in 0...3 {
            keyframes.append(Tick(pose: .walk, frame: step * 3, x: 0.5 - Double(step) * 0.12, y: 0, facing: .left))
        }
        keyframes.append(Tick(pose: .idle, frame: 6, x: 0.15, y: 0, facing: .right))
        return Choreography(
            version: 1, seed: 0, generatedAt: fallback.startsAt, startsAt: fallback.startsAt, keyframeSec: 2,
            keyframes: keyframes, tickMs: 120, loopMinutes: 10, loops: [], reaction: fallback.reaction
        )
    }()
}
