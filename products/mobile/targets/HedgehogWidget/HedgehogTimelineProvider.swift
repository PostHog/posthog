import Foundation
import WidgetKit

struct HedgehogEntry: TimelineEntry {
    let date: Date
    let tick: Tick
}

struct HedgehogTimelineProvider: TimelineProvider {
    private static let entryCount = 90
    private static let pokeWindow: TimeInterval = 120
    private static let reactionStep: TimeInterval = 2

    func placeholder(in context: Context) -> HedgehogEntry {
        HedgehogEntry(date: Date(), tick: FallbackChoreography.value.keyframes[0])
    }

    func getSnapshot(in context: Context, completion: @escaping (HedgehogEntry) -> Void) {
        completion(placeholder(in: context))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<HedgehogEntry>) -> Void) {
        let family = String(describing: context.family)
        let poke = ChoreographyLoader.poke(family: family)
        let (entries, reactionStart) = Self.entries(for: ChoreographyLoader.load(), now: Date(), poke: poke)
        if let poke, let reactionStart, poke.reactionStart != reactionStart {
            ChoreographyLoader.recordReactionStart(reactionStart, for: poke, family: family)
        }
        completion(Timeline(entries: entries, policy: .after(entries.last?.date ?? Date())))
    }

    static func entries(for choreography: Choreography, now: Date, poke: Poke?) -> (entries: [HedgehogEntry], reactionStart: Date?) {
        let step = TimeInterval(choreography.keyframeSec)
        let currentStep = Int(floor(now.timeIntervalSince(choreography.startsAt) / step))
        let scheduled = (0..<entryCount).map { offset in
            let index = currentStep + offset
            return HedgehogEntry(
                date: choreography.startsAt.addingTimeInterval(TimeInterval(index) * step),
                tick: keyframe(at: index, in: choreography.keyframes)
            )
        }

        let reactionKeyframes = choreography.reaction.keyframes
        guard let poke, !reactionKeyframes.isEmpty else {
            return (scheduled, nil)
        }
        let reactionDuration = TimeInterval(reactionKeyframes.count) * reactionStep
        let reactionStart: Date
        if let started = poke.reactionStart {
            reactionStart = started
        } else {
            let sincePoke = now.timeIntervalSince(poke.at)
            guard sincePoke >= 0, sincePoke < pokeWindow else {
                return (scheduled, nil)
            }
            // WidgetKit may deliver the reload for a tap late. Play from the tap when the reload is prompt,
            // otherwise from now, so a throttled reload still shows the whole reaction.
            reactionStart = sincePoke < reactionDuration ? poke.at : now
        }
        let reactionEnd = reactionStart.addingTimeInterval(reactionDuration)
        // A reaction that already ended stays recorded, so a later reload (for example the app syncing
        // a new choreography) does not play it again.
        guard reactionEnd > now else {
            return (scheduled, reactionStart)
        }

        let current = keyframe(at: Int(floor(reactionStart.timeIntervalSince(choreography.startsAt) / step)), in: choreography.keyframes)
        let reaction = reactionKeyframes.enumerated().map { offset, tick in
            HedgehogEntry(
                date: reactionStart.addingTimeInterval(TimeInterval(offset) * reactionStep),
                tick: reacting(tick, at: current)
            )
        }
        let resume = HedgehogEntry(
            date: reactionEnd,
            tick: keyframe(at: Int(floor(reactionEnd.timeIntervalSince(choreography.startsAt) / step)), in: choreography.keyframes)
        )
        // WidgetKit shows the latest entry whose date has passed, so keep the scheduled entry that covers
        // the time before the reaction and drop the ones the reaction and resume entries replace.
        let before = scheduled.prefix { $0.date < reactionStart }
        let after = scheduled.filter { $0.date > reactionEnd }
        return (Array(before) + reaction + [resume] + after, reactionStart)
    }

    /// Reaction keyframes are authored at x 0.5 facing right. Moving them to where the hedgehog stands
    /// keeps it from sliding to the center when it is poked.
    private static func reacting(_ tick: Tick, at current: Tick) -> Tick {
        Tick(
            pose: tick.pose,
            frame: tick.frame,
            x: min(max(tick.x + current.x - 0.5, 0), 1),
            y: tick.y,
            facing: current.facing,
            bubble: tick.bubble
        )
    }

    private static func keyframe(at index: Int, in keyframes: [Tick]) -> Tick {
        let count = keyframes.count
        return keyframes[((index % count) + count) % count]
    }
}
