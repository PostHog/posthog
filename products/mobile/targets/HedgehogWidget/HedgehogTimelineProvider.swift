import Foundation
import WidgetKit

/// How the hedgehog's x gets from the previous entry to this one.
enum Motion: Codable, Equatable {
    case settle
    case glide(TimeInterval)
    // Saved by older builds. They still decode, so the last saved position anchors the next plan.
    case rise(TimeInterval)
    case drop(TimeInterval)
}

/// One hop: a loop around a point above the sprite. The sprite leaves the floor and comes back to the same spot.
/// WidgetKit renders a built-in rotation between entries but not a custom animatable path, so this stands in for the arc.
struct Hop: Codable, Equatable {
    /// Whole turns only. A change of one turn between two entries is one hop.
    var degrees: Double
    /// 0...1 of the renderer's available rise.
    var apex: Double
    /// Seconds after the entry begins until this hop takes off.
    var delay: TimeInterval
    /// Seconds in the air. Zero means the entry does not hop on this layer and its values change at once.
    var duration: TimeInterval

    static let grounded = Hop(degrees: 0, apex: 0, delay: 0, duration: 0)
}

struct HedgehogEntry: TimelineEntry, Codable {
    let date: Date
    let tick: Tick
    /// Flip turns, played with the main hop.
    let spin: Double
    let motion: Motion
    /// The main hop, then its bounces. Nil in timelines that older builds saved.
    var hops: [Hop]? = nil

    var airborne: Bool { hops?.contains { $0.duration > 0 } ?? false }

    func hop(_ layer: Int) -> Hop {
        guard let hops, hops.indices.contains(layer) else { return .grounded }
        return hops[layer]
    }

    func wearing(_ character: String?) -> HedgehogEntry {
        HedgehogEntry(date: date, tick: Tick(
            pose: tick.pose, frame: tick.frame, x: tick.x, y: tick.y, facing: tick.facing,
            hoggie: character
        ), spin: spin, motion: motion, hops: hops)
    }
}

struct HedgehogTimelineProvider: TimelineProvider {
    private static let entryLimit = 270
    private static let longestAnimation: TimeInterval = 2
    /// The main hop and two bounces. hedgehog-mode's rebounds stop after about two, and later ones would be too small to see.
    static let hopLayers = 3
    /// hedgehog-mode's AI walks 0.75 sprite heights per second; the script spreads x over 2.8 sprite heights.
    static let walkSpeed = 0.75 / 2.8
    /// A full jump in hedgehog-mode, used for scripts that only mark a jump with `y`.
    private static let legacyAirtime: TimeInterval = 0.9

    struct Plan {
        let entries: [HedgehogEntry]
        let reloadAt: Date
    }

    func placeholder(in context: Context) -> HedgehogEntry {
        HedgehogEntry(
            date: Date(), tick: FallbackChoreography.value.keyframes[0], spin: 0, motion: .settle,
            hops: Array(repeating: .grounded, count: Self.hopLayers)
        )
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
        if let end = previous.last?.date, end > now, previous.allSatisfy({ $0.hops?.count == hopLayers }) {
            let current = previous.lastIndex { $0.date <= now } ?? 0
            return Plan(entries: Array(previous[current...]), reloadAt: end)
        }

        let step = TimeInterval(max(choreography.keyframeSec, 2))
        let beat = min(step, longestAnimation)
        let keyframes = choreography.keyframes
        var index = Int(floor(now.timeIntervalSince(choreography.startsAt) / step))
        func wrapped(_ index: Int) -> Int { ((index % keyframes.count) + keyframes.count) % keyframes.count }
        let anchor = previous.last { $0.date <= now }
        let start = (anchor?.tick ?? keyframes[wrapped(index)]).grounded
        // Rotations restart from zero, so a timeline that ended mid-flip (or an older build's half turn) lands upright.
        var entries = [HedgehogEntry(
            date: now, tick: Tick(pose: .idle, frame: 0, x: start.x, y: 0, facing: start.facing),
            spin: 0, motion: .settle, hops: Array(repeating: .grounded, count: hopLayers)
        )]

        func append(_ tick: Tick, jump: Jump? = nil) {
            let prior = entries[entries.count - 1]
            var hops = Array(repeating: Hop.grounded, count: hopLayers)
            var spin = 0.0
            var travel = beat
            if let jump {
                // The loop rises on the side the hog faces.
                let direction: Double = tick.facing == .right ? -1 : 1
                var takeoff = 0.0
                for (layer, flight) in jump.flights.prefix(hopLayers).enumerated() {
                    // A bounce that does not fit in the beat is dropped: cutting it short would change its arc.
                    let airtime = layer == 0 ? min(flight.airtime, beat) : flight.airtime
                    guard airtime > 0, takeoff + airtime <= beat + 1e-9 else { break }
                    hops[layer] = Hop(
                        degrees: prior.hop(layer).degrees + direction * 360, apex: min(max(flight.apex, 0), 1),
                        delay: takeoff, duration: airtime
                    )
                    takeoff += airtime
                }
                spin = prior.spin + jump.turns * 360
                travel = takeoff
            }
            entries.append(HedgehogEntry(
                date: now.addingTimeInterval(Double(entries.count) * step), tick: tick,
                spin: spin, motion: .glide(travel), hops: hops
            ))
        }

        while entries.count < entryLimit {
            index += 1
            let target = keyframes[wrapped(index)]
            let next = resolve(target, after: keyframes[wrapped(index - 1)], from: entries[entries.count - 1].tick)
            // A plan that starts away from the script, or a script that does not close its loop, walks over at walking pace.
            let reach = walkSpeed * beat
            while entries.count < entryLimit, abs(next.tick.x - entries[entries.count - 1].tick.x) > reach + 0.01 {
                let prior = entries[entries.count - 1].tick
                let facing: Facing = next.tick.x < prior.x ? .left : .right
                append(Tick(pose: .walk, frame: target.frame, x: prior.x + (facing == .left ? -reach : reach), y: 0, facing: facing))
            }
            if entries.count < entryLimit {
                append(next.tick, jump: next.jump)
            }
        }
        presetAnchors(&entries)
        return Plan(entries: entries, reloadAt: entries[entries.count - 1].date)
    }

    struct Jump {
        let flights: [TickMotion.Bounce]
        let turns: Double
    }

    private struct Beat {
        let tick: Tick
        let jump: Jump?
    }

    /// Where the hog stands at the end of the keyframe's beat, and whether it jumps to get there.
    private static func resolve(_ target: Tick, after previous: Tick, from prior: Tick) -> Beat {
        let standing = Tick(pose: target.pose, frame: target.frame, x: target.x, y: 0, facing: target.facing)
        if let motion = target.motion {
            switch motion.kind {
            case "idle", "walk":
                return Beat(tick: standing, jump: nil)
            case "jump":
                let main = TickMotion.Bounce(airtime: motion.airtime ?? legacyAirtime, apex: motion.apex ?? 1)
                return Beat(
                    tick: airborne(target, x: target.x, facing: target.facing),
                    jump: Jump(flights: [main] + (motion.bounces ?? []), turns: (motion.turns ?? 0).rounded())
                )
            default:
                break
            }
        }

        // Older scripts mark a jump with y and a flip with half turns. Their airborne x is not a landing spot, so the hog
        // jumps in place and only walk keyframes move it.
        if target.y > 0 && previous.y == 0 {
            let turns: Double = (target.turn ?? 0) == 0 ? 0 : ((target.turn ?? 0) < 0 ? -1 : 1)
            return Beat(
                tick: airborne(target, x: prior.x, facing: prior.facing),
                jump: Jump(flights: [TickMotion.Bounce(airtime: legacyAirtime, apex: min(target.y, 1))], turns: turns)
            )
        }
        if target.pose == .walk && abs(target.x - prior.x) > 0.025 {
            return Beat(tick: Tick(pose: .walk, frame: target.frame, x: target.x, y: 0, facing: target.x < prior.x ? .left : .right), jump: nil)
        }
        return Beat(tick: Tick(pose: target.pose, frame: target.frame, x: prior.x, y: 0, facing: prior.facing), jump: nil)
    }

    /// hedgehog-mode shows `fall` whenever the hog is off the ground, which is most of a jump beat.
    private static func airborne(_ target: Tick, x: Double, facing: Facing) -> Tick {
        Tick(pose: .fall, frame: target.pose == .fall ? target.frame : 4, x: x, y: 0, facing: facing)
    }

    /// Gives each grounded entry the apex of the next hop on its layer. The anchor then moves while the rotation is a whole
    /// turn, where it has no visible effect, instead of spiralling during the hop.
    private static func presetAnchors(_ entries: inout [HedgehogEntry]) {
        for layer in 0..<hopLayers {
            var upcoming: Double? = nil
            for position in entries.indices.reversed() {
                var hops = entries[position].hops!
                if hops[layer].duration > 0 {
                    upcoming = hops[layer].apex
                } else if let upcoming {
                    hops[layer].apex = upcoming
                    entries[position].hops = hops
                }
            }
        }
    }
}
