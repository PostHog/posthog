import { type Choreography, createChoreography, dailySeed, FRAME_COUNTS, type Tick } from './choreography'

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
                (tick.bubble?.length ?? 0) > 24
        )
        expect(invalid).toEqual([])
    })

    it.each(SEEDS)('fills a day of keyframes without teleporting for seed %i', (seed) => {
        const { keyframes } = build(seed)
        expect(keyframes).toHaveLength(24 * 60)
        const teleports = keyframes.filter(
            (keyframe, index) => index > 0 && Math.abs(keyframe.x - (keyframes[index - 1] as Tick).x) > 0.25
        )
        expect(teleports).toEqual([])
    })

    it.each(SEEDS)('closes every loop so Android can repeat it seamlessly for seed %i', (seed) => {
        const { loops } = build(seed)
        expect(loops).toHaveLength(24)
        for (const loop of loops) {
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
