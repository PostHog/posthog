import { type Choreography, createChoreography, dailySeed, FRAME_COUNTS, HOGGIES, type Tick } from './choreography'

const STARTS_AT = new Date('2026-10-13T00:00:00Z')
const GENERATED_AT = new Date('2026-10-13T08:00:00Z')
const SEEDS = [1, 20261013, 20261231, 4294967295]

function build(seed: number): Choreography {
    return createChoreography({ seed, startsAt: STARTS_AT, generatedAt: GENERATED_AT })
}

function allTicks(choreography: Choreography): Tick[] {
    return [
        ...choreography.keyframes,
        ...choreography.loops.flat(),
        ...choreography.reaction.keyframes,
        ...choreography.reaction.ticks,
        ...choreography.surprises.flatMap(({ keyframes, ticks }) => [...keyframes, ...ticks]),
    ]
}

describe('choreography', () => {
    it('is deterministic for a seed and varies between seeds', () => {
        expect(build(20261013)).toEqual(build(20261013))
        expect(build(20261013).keyframes).not.toEqual(build(20261014).keyframes)
        expect(build(20261013).loops).not.toEqual(build(20261014).loops)
    })

    it.each(SEEDS)('keeps every tick inside the widget and the sprite sheet for seed %i', (seed) => {
        const invalid = allTicks(build(seed)).filter(
            (tick) =>
                tick.x < 0 ||
                tick.x > 1 ||
                tick.y < 0 ||
                tick.y > 1 ||
                !Number.isInteger(tick.frame) ||
                tick.frame < 0 ||
                tick.frame >= FRAME_COUNTS[tick.pose] ||
                (tick.bubble?.length ?? 0) > 24 ||
                (tick.hoggie !== undefined && !HOGGIES.includes(tick.hoggie))
        )
        expect(invalid).toEqual([])
    })

    it.each(SEEDS)(
        'fills a 30-minute cycle of keyframes without teleporting, also across the wrap, for seed %i',
        (seed) => {
            const { keyframes } = build(seed)
            expect(keyframes).toHaveLength(900)
            const teleports = keyframes.filter(
                (keyframe, index) =>
                    Math.abs(keyframe.x - (keyframes[(index + keyframes.length - 1) % keyframes.length] as Tick).x) >
                    0.25
            )
            expect(teleports).toEqual([])
        }
    )

    it.each(SEEDS)('keeps the hedgehog busy on both platforms for seed %i', (seed) => {
        const { keyframes, loops } = build(seed)
        const roaming = keyframes.filter((tick) => !tick.hoggie)
        const travelling = roaming.filter((keyframe, index) => {
            const previous = roaming[index - 1]
            return previous && (Math.abs(keyframe.x - previous.x) > 0.005 || keyframe.y !== previous.y)
        })
        expect(travelling.length / roaming.length).toBeGreaterThan(0.5)

        let longestStill = 1
        let still = 1
        for (let index = 1; index < keyframes.length; index++) {
            still = JSON.stringify(keyframes[index]) === JSON.stringify(keyframes[index - 1]) ? still + 1 : 1
            longestStill = Math.max(longestStill, still)
        }
        expect(longestStill).toBeLessThanOrEqual(4)

        const idleLoops = loops.filter(
            (loop) => !loop[0]?.hoggie && loop.filter((tick) => tick.pose === 'idle').length > loop.length / 3
        )
        expect(idleLoops).toEqual([])
    })

    it.each(SEEDS)('reserves character changes for taps for seed %i', (seed) => {
        const { keyframes, loops, surprises } = build(seed)
        expect([...keyframes, ...loops.flat()].every((tick) => tick.hoggie === undefined)).toBe(true)
        expect(new Set(surprises.map((reaction) => reaction.keyframes[0]?.hoggie))).toEqual(new Set(HOGGIES))
        for (const reaction of surprises) {
            expect(reaction.keyframes.every((tick) => tick.x === 0.5 && tick.facing === 'right')).toBe(true)
            expect(reaction.ticks.every((tick) => tick.x === 0.5 && tick.facing === 'right')).toBe(true)
            expect(new Set([...reaction.keyframes, ...reaction.ticks].map((tick) => tick.hoggie)).size).toBe(1)
        }
    })

    it.each(SEEDS)('lands every flip on its feet for seed %i', (seed) => {
        const { keyframes, reaction } = build(seed)
        for (const ticks of [keyframes, reaction.keyframes]) {
            const unfinished: Tick[] = []
            let turns = 0
            let flips = 0
            ticks.forEach((tick, index) => {
                turns += tick.turn ?? 0
                if (tick.turn && !ticks[index + 1]?.turn) {
                    flips++
                    if (!Number.isInteger(turns) || tick.y !== 0) {
                        unfinished.push(tick)
                    }
                    turns = 0
                }
            })
            expect(unfinished).toEqual([])
            expect(flips).toBeGreaterThan(0)
        }
    })

    it.each(SEEDS)('closes every loop so Android can repeat it seamlessly for seed %i', (seed) => {
        const { loops } = build(seed)
        expect(loops).toHaveLength(16)
        for (const loop of [...loops, ...build(seed).surprises.map(({ ticks }) => ticks)]) {
            const first = loop[0] as Tick
            const last = loop[loop.length - 1] as Tick
            expect(loop.length).toBeGreaterThan(1)
            expect(loop.length).toBeLessThanOrEqual(120)
            expect(Math.abs(last.x - first.x)).toBeLessThanOrEqual(0.05)
            expect(last).toMatchObject({ y: 0, facing: first.facing })
        }
    })

    it.each(SEEDS)('stays inside the shared storage budget for seed %i', (seed) => {
        expect(JSON.stringify(build(seed)).length).toBeLessThan(200 * 1024)
    })

    it.each([
        ['2026-10-13T00:00:00Z', 20261013],
        ['2026-10-13T23:30:00-07:00', 20261014],
        ['2026-12-31T23:59:59Z', 20261231],
    ])('derives the UTC day seed from %s', (iso, seed) => {
        expect(dailySeed(new Date(iso))).toBe(seed)
    })
})
