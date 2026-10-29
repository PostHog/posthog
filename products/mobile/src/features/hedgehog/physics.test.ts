import { FRAME_COUNTS } from './choreography'
import { GROUND_JUMP_APEX, type HedgehogAction, HedgehogSimulation, type PhysicsEvent } from './physics'

const WIDTH = 2.8

function simulation(options: {
    x?: number
    cadenceSec?: number
    actions?: Partial<Record<HedgehogAction, number>>
}): HedgehogSimulation {
    return new HedgehogSimulation({
        random: () => 0.25,
        cadenceSec: options.cadenceSec ?? 1,
        width: WIDTH,
        start: { x: options.x ?? 1, facing: 'right' },
        actions: options.actions ?? { wait: 1 },
        frameCounts: FRAME_COUNTS,
    })
}

function landings(events: PhysicsEvent[]): Extract<PhysicsEvent, { type: 'landing' }>[] {
    return events.filter((event): event is Extract<PhysicsEvent, { type: 'landing' }> => event.type === 'landing')
}

describe('hedgehog physics', () => {
    it('jumps, bounces and settles like the Matter.js body in hedgehog-mode', () => {
        const hog = simulation({})
        hog.stopAI()
        hog.perform('jump')
        const poses = new Set<string>()
        while (!hog.settled) {
            hog.advance()
            if (!hog.state.grounded) {
                poses.add(hog.state.pose)
            }
        }
        const [main, firstBounce, ...rest] = landings(hog.events)
        // Gravity 25 sprites/s^2 and a 11.25 sprites/s impulse fly 0.9 s without drag; frictionAir 1 % per step
        // shortens that to 48 steps and the apex to about 2.05 sprites.
        expect(main?.airtimeSteps).toBe(48)
        expect(GROUND_JUMP_APEX).toBeCloseTo(2.05, 2)
        expect(main?.apex).toBeCloseTo(GROUND_JUMP_APEX, 5)
        // Restitution 0.5 halves the impact speed, so each bounce flies about half as long and a fifth as high.
        expect((firstBounce?.airtimeSteps ?? 0) / 48).toBeCloseTo(0.44, 1)
        expect((firstBounce?.apex ?? 0) / GROUND_JUMP_APEX).toBeCloseTo(0.18, 1)
        expect(rest).toHaveLength(1)
        expect(rest[0]?.bounced).toBe(false)
        expect(hog.step).toBeLessThan(120)
        expect([...poses]).toEqual(['fall'])
    })

    it('walks at 0.75 sprites per second and turns around at the edges instead of wrapping', () => {
        const hog = simulation({ x: 1, cadenceSec: 100, actions: { walk: 1 } })
        hog.run(60)
        expect(hog.state).toMatchObject({ facing: 'left', pose: 'walk' })
        expect(Math.abs((1 - hog.state.x) / WIDTH - 0.75 / WIDTH)).toBeLessThan(0.01)
        const xs: number[] = []
        for (let step = 0; step < 200; step++) {
            hog.advance()
            xs.push(hog.state.x)
        }
        expect(Math.min(...xs)).toBeGreaterThanOrEqual(0)
        expect(Math.max(...xs)).toBeLessThanOrEqual(WIDTH)
        expect(hog.state.facing).toBe('right')
        const jumps = xs.slice(1).filter((x, index) => Math.abs(x - (xs[index] as number)) > 0.02)
        expect(jumps).toEqual([])
    })

    it('picks one action per cadence, and a wave holds the AI for its animation and a 1 s rest', () => {
        const hog = simulation({ cadenceSec: 1, actions: { wave: 1 } })
        hog.run(600)
        const steps = hog.events.filter((event) => event.type === 'action').map((event) => event.step)
        expect(steps).toEqual([0, 120, 240, 360, 480])

        const walker = simulation({ cadenceSec: 1, actions: { walk: 10, wait: 3 } })
        walker.run(600)
        const decisions = walker.events.filter((event) => event.type === 'action').map((event) => event.step)
        expect(decisions).toEqual([0, 60, 120, 180, 240, 300, 360, 420, 480, 540])
    })
})
