import { type Choreography, createChoreography, dailySeed, FRAME_COUNTS, HOGGIES, type Tick } from './choreography'

const STARTS_AT = new Date('2026-10-13T00:00:00Z')
const GENERATED_AT = new Date('2026-10-13T08:00:00Z')
const SEEDS = [1, 20261013, 20261231, 4294967295]

function generate(seed: number): Choreography {
    return createChoreography({ seed, startsAt: STARTS_AT, generatedAt: GENERATED_AT })
}

// Each script simulates over 30 minutes of 60 Hz physics, so the read-only tests share one copy per seed.
const built = new Map<number, Choreography>()
function build(seed: number): Choreography {
    const choreography = built.get(seed) ?? generate(seed)
    built.set(seed, choreography)
    return choreography
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
        expect(generate(20261013)).toEqual(generate(20261013))
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
        'fills a 30-minute cycle of grounded keyframes whose motion explains every move, also across the wrap, for seed %i',
        (seed) => {
            const { keyframes, keyframeSec } = build(seed)
            expect(keyframes).toHaveLength(900)
            // A walk covers 0.75 sprites/s of a 2.8-sprite travel width; nothing else moves the hedgehog sideways.
            const walkReach = (0.75 * keyframeSec) / 2.8
            const unexplained = keyframes.filter((keyframe, index) => {
                const previous = keyframes[(index + keyframes.length - 1) % keyframes.length] as Tick
                const distance = Math.abs(keyframe.x - previous.x)
                const reach = keyframe.motion?.kind === 'walk' ? walkReach : keyframe.motion?.kind === 'idle' ? 0.02 : 0
                return keyframe.y !== 0 || distance > reach + 0.001
            })
            expect(unexplained).toEqual([])

            const jumps = keyframes.flatMap((keyframe) => (keyframe.motion?.kind === 'jump' ? [keyframe.motion] : []))
            const unfit = jumps.filter(
                (jump) =>
                    jump.airtime + jump.bounces.reduce((sum, bounce) => sum + bounce.airtime, 0) > keyframeSec ||
                    jump.apex <= 0 ||
                    jump.apex > 1 ||
                    jump.bounces.some((bounce, index) => bounce.apex >= (jump.bounces[index - 1] ?? jump).apex) ||
                    (jump.turns !== undefined && Math.abs(jump.turns) !== 1)
            )
            expect(unfit).toEqual([])
            expect(keyframes.every((keyframe) => keyframe.motion !== undefined && keyframe.turn === undefined)).toBe(
                true
            )
            expect(jumps.length).toBeGreaterThan(30)
            expect(jumps.filter((jump) => jump.turns).length).toBeGreaterThan(0)
        }
    )

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

    it.each(SEEDS)('lands every legacy reaction flip on its feet for seed %i', (seed) => {
        const { reaction } = build(seed)
        for (const ticks of [reaction.keyframes]) {
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
        // A 120 ms tick spans 7 or 8 physics steps, and 8 steps of walking move 0.035 of the width.
        const teleports = loops.flatMap((loop) =>
            loop.filter((tick, index) => index > 0 && Math.abs(tick.x - (loop[index - 1] as Tick).x) > 0.04)
        )
        expect(teleports).toEqual([])
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
