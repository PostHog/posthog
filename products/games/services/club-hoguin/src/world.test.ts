import { OBJECTS } from './content'
import { isWalkable, LIMITS, World } from './world'

function makeWorld(): World {
    let nextId = 0
    return new World({ makeId: () => `id-${++nextId}`, random: () => 0.5 })
}

function joinAt(world: World, x: number, y: number): string {
    const joined = world.join('web', 0)
    if (!joined) {
        throw new Error('join failed')
    }
    // Walk the hedgehog to a known tile so a test does not depend on the spawn point.
    world.moveTo(joined.token, x, y)
    for (let i = 0; i < 100; i++) {
        world.tick(0)
    }
    expect(world.snapshot(joined.token).you).toMatchObject({ x, y })
    return joined.token
}

describe('World', () => {
    it.each([
        ['walks around the pond to a target behind it', { x: 9, y: 4 }, { x: 9, y: 4 }],
        ['walks around an object to its far side', { x: 36, y: 11 }, { x: 36, y: 11 }],
        ['stops in front of an object when the target is inside it', { x: 20, y: 1 }, { x: 20, y: 3 }],
    ])('%s', (_case, target, expected) => {
        const world = makeWorld()
        const token = joinAt(world, 9, 9)

        world.moveTo(token, target.x, target.y)
        for (let i = 0; i < 100; i++) {
            world.tick(0)
            const you = world.snapshot(token).you!
            expect(isWalkable(you.x, you.y)).toBe(true)
        }
        expect(world.snapshot(token).you).toMatchObject({ ...expected, moving: false })
    })

    it('keeps polling hedgehogs and removes idle ones', () => {
        const world = makeWorld()
        const active = world.join('mod', 0)!
        const idle = world.join('web', 0)!

        const later = LIMITS.idleTimeoutMs + 1
        expect(world.touch(active.token, later)).not.toBeNull()
        const departed = world.tick(later)

        expect(departed).toEqual([{ id: idle.id, client: 'web', reason: 'idle', durationMs: later }])
        expect(world.snapshot(null).players.map((player) => player.id)).toEqual([active.id])
        expect(world.touch(idle.token, later)).toBeNull()
    })

    it.each([
        ['free text instead of a preset phrase', 'buy my crypto', 0, 'unknown_phrase'],
        ['a second phrase inside the cooldown', 'hi', LIMITS.sayCooldownMs - 1, 'cooldown'],
    ])('rejects %s', (_case, phraseId, delay, error) => {
        const world = makeWorld()
        const { token } = world.join('web', 0)!
        expect(world.say(token, 'quills', 0)).toEqual({ ok: true })
        const feedBefore = world.snapshot(token).feed

        expect(world.say(token, phraseId, delay)).toEqual({ ok: false, error })
        expect(world.snapshot(token).feed).toEqual(feedBefore)
    })

    it('lets a hedgehog poke only what is in reach', () => {
        const world = makeWorld()
        const flag = OBJECTS.find((object) => object.id === 'flag')!
        const token = joinAt(world, flag.x + LIMITS.pokeReach + 1, flag.y)

        expect(world.poke(token, 'flag', 0)).toEqual({ ok: false, error: 'too_far' })
        expect(world.snapshot(token).objects.lightsOn).toBe(true)

        world.moveTo(token, flag.x + 1, flag.y)
        world.tick(0)
        world.tick(0)
        expect(world.poke(token, undefined, 0)).toEqual({ ok: true, objectId: 'flag' })
        expect(world.snapshot(token).objects.lightsOn).toBe(false)
    })

    it('turns hedgehogs away once the club is full', () => {
        const world = makeWorld()
        for (let i = 0; i < LIMITS.maxPlayers; i++) {
            expect(world.join('web', 0)).not.toBeNull()
        }
        expect(world.join('web', 0)).toBeNull()
        expect(world.snapshot(null).online).toBe(LIMITS.maxPlayers)
    })
})
