import Foundation
import WidgetKit

/// How the hedgehog gets from the previous entry to this one. The view turns it into SwiftUI animations.
enum Motion: Equatable {
    /// A pose change on the spot, or the first entry of a timeline.
    case settle
    /// Travel along the floor. It lasts until the next entry, so consecutive steps join into one glide.
    case glide(TimeInterval)
    case rise(TimeInterval)
    case drop(TimeInterval)
}

struct HedgehogEntry: TimelineEntry {
    let date: Date
    let tick: Tick
    /// Degrees of the flip in progress, clockwise on screen. Zero when the hedgehog is not flipping.
    let spin: Double
    let motion: Motion
}

struct HedgehogTimelineProvider: TimelineProvider {
    // Developers report that WidgetKit stops updating a timeline of more than about 400 entries, and that it shows
    // entries no faster than about every 2 seconds. The dense part shows every beat. The tail moves the hedgehog
    // once a minute if the system delays the next reload, which can happen because the daily reload budget is limited.
    private static let denseEntryLimit = 270
    private static let denseWindow: TimeInterval = 30 * 60
    private static let tailEntryCount = 40
    private static let tailStep: TimeInterval = 60
    private static let pokeWindow: TimeInterval = 120
    private static let reactionStep: TimeInterval = 2
    private static let longestAnimation: TimeInterval = 2

    struct Plan {
        let entries: [HedgehogEntry]
        let reloadAt: Date
        let reactionStart: Date?
    }

    /// A keyframe placed in time, before the provider works out how to animate into it.
    private struct Beat {
        let date: Date
        let tick: Tick
        let spin: Double
    }

    func placeholder(in context: Context) -> HedgehogEntry {
        HedgehogEntry(date: Date(), tick: FallbackChoreography.value.keyframes[0], spin: 0, motion: .settle)
    }

    func getSnapshot(in context: Context, completion: @escaping (HedgehogEntry) -> Void) {
        completion(placeholder(in: context))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<HedgehogEntry>) -> Void) {
        let family = String(describing: context.family)
        let poke = ChoreographyLoader.poke(family: family)
        let plan = Self.plan(for: ChoreographyLoader.load(), now: Date(), poke: poke)
        if let poke, let reactionStart = plan.reactionStart, poke.reactionStart != reactionStart {
            ChoreographyLoader.recordReactionStart(reactionStart, for: poke, family: family)
        }
        completion(Timeline(entries: plan.entries, policy: .after(plan.reloadAt)))
    }

    static func plan(for choreography: Choreography, now: Date, poke: Poke?) -> Plan {
        let step = TimeInterval(choreography.keyframeSec)
        let keyframes = choreography.keyframes
        let keyframeSpins = spins(for: keyframes)
        func stepIndex(at date: Date) -> Int {
            Int(floor(date.timeIntervalSince(choreography.startsAt) / step))
        }
        func beat(at index: Int) -> Beat {
            let wrapped = ((index % keyframes.count) + keyframes.count) % keyframes.count
            return Beat(
                date: choreography.startsAt.addingTimeInterval(TimeInterval(index) * step),
                tick: keyframes[wrapped],
                spin: keyframeSpins[wrapped]
            )
        }

        var beats: [Beat] = []
        var index = stepIndex(at: now)
        let windowEnd = now.addingTimeInterval(denseWindow)
        while beats.count < denseEntryLimit, beat(at: index).date < windowEnd {
            let next = beat(at: index)
            index += 1
            // An identical keyframe changes nothing on screen, so the previous entry stays up longer instead.
            if let last = beats.last, last.tick == next.tick, last.spin == next.spin {
                continue
            }
            beats.append(next)
        }
        let reloadAt = beat(at: index).date
        for minute in 0..<tailEntryCount {
            let date = reloadAt.addingTimeInterval(TimeInterval(minute) * tailStep)
            beats.append(Beat(date: date, tick: beat(at: stepIndex(at: date)).tick.grounded, spin: 0))
        }

        // The first entry animates from the beat before it, which is what the widget showed before this reload.
        func entries(from beats: [Beat]) -> [HedgehogEntry] {
            let onScreen = beats.first.map { beat(at: stepIndex(at: $0.date) - 1).tick }
            return Self.entries(from: beats, after: onScreen)
        }

        let reactionKeyframes = choreography.reaction.keyframes
        let reactionDuration = TimeInterval(reactionKeyframes.count) * reactionStep
        guard let poke, !reactionKeyframes.isEmpty,
              let reactionStart = reactionStart(for: poke, now: now, duration: reactionDuration)
        else {
            return Plan(entries: entries(from: beats), reloadAt: reloadAt, reactionStart: nil)
        }
        let reactionEnd = reactionStart.addingTimeInterval(reactionDuration)
        // A reaction that already ended stays recorded, so a later reload (for example the app syncing
        // a new choreography) does not play it again.
        guard reactionEnd > now else {
            return Plan(entries: entries(from: beats), reloadAt: reloadAt, reactionStart: reactionStart)
        }

        let current = beat(at: stepIndex(at: reactionStart)).tick
        let reactionTicks = reactionKeyframes.map { reacting($0, at: current) }
        let reactionSpins = spins(for: reactionTicks)
        let reaction = reactionTicks.indices.map { offset in
            Beat(
                date: reactionStart.addingTimeInterval(TimeInterval(offset) * reactionStep),
                tick: reactionTicks[offset],
                spin: reactionSpins[offset]
            )
        }
        let scheduledResume = beat(at: stepIndex(at: reactionEnd))
        let resume = Beat(date: reactionEnd, tick: scheduledResume.tick, spin: scheduledResume.spin)
        // WidgetKit shows the latest entry whose date has passed, so keep the scheduled entry that covers
        // the time before the reaction and drop the ones the reaction and resume entries replace.
        let before = beats.prefix { $0.date < reactionStart }
        let after = beats.filter { $0.date > reactionEnd }
        return Plan(
            entries: entries(from: Array(before) + reaction + [resume] + after),
            reloadAt: reloadAt,
            reactionStart: reactionStart
        )
    }

    private static func reactionStart(for poke: Poke, now: Date, duration: TimeInterval) -> Date? {
        if let started = poke.reactionStart {
            return started
        }
        let sincePoke = now.timeIntervalSince(poke.at)
        guard sincePoke >= 0, sincePoke < pokeWindow else {
            return nil
        }
        // WidgetKit may deliver the reload for a tap late. Play from the tap when the reload is prompt,
        // otherwise from now, so a throttled reload still shows the whole reaction.
        return sincePoke < duration ? poke.at : now
    }

    /// The angle of the flip in progress at each tick. A flip spans consecutive ticks that have a `turn`, so the angle
    /// adds up across them and is zero again on the first tick without one. That tick shows the hedgehog upright,
    /// because a flip always ends on whole turns.
    static func spins(for ticks: [Tick]) -> [Double] {
        var turns = 0.0
        return ticks.map { tick in
            if let turn = tick.turn, turn != 0 {
                turns += turn
            } else {
                turns = 0
            }
            return turns * 360
        }
    }

    private static func entries(from beats: [Beat], after onScreen: Tick?) -> [HedgehogEntry] {
        beats.indices.map { index in
            let beat = beats[index]
            let gap = index + 1 < beats.count ? beats[index + 1].date.timeIntervalSince(beat.date) : longestAnimation
            let previous = index > 0 ? beats[index - 1].tick : onScreen
            return HedgehogEntry(
                date: beat.date,
                tick: beat.tick,
                spin: beat.spin,
                motion: motion(from: previous, to: beat.tick, gap: gap)
            )
        }
    }

    /// Rising takes most of the gap to the next entry and falling is quick, so a jump hangs in the air briefly.
    static func motion(from previous: Tick?, to tick: Tick, gap: TimeInterval) -> Motion {
        guard let previous else {
            return .settle
        }
        if tick.y > previous.y {
            return .rise(min(gap * 0.75, 1.5))
        }
        if tick.y < previous.y {
            return .drop(min(gap * 0.3, 0.6))
        }
        if abs(tick.x - previous.x) > 0.001 {
            return .glide(min(gap, longestAnimation))
        }
        return .settle
    }

    /// Reaction keyframes are authored at x 0.5 facing right. Moving them to where the hedgehog stands
    /// keeps it from sliding to the center when it is poked, and mirroring the turn keeps a flip going forwards.
    private static func reacting(_ tick: Tick, at current: Tick) -> Tick {
        Tick(
            pose: tick.pose,
            frame: tick.frame,
            x: min(max(tick.x + current.x - 0.5, 0), 1),
            y: tick.y,
            facing: current.facing,
            bubble: tick.bubble,
            turn: tick.turn.map { current.facing == .left ? -$0 : $0 }
        )
    }
}
