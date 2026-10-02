import { OBJECTS, SPAWN } from './content'
import { isWalkable, type JoinedPlayer, LIMITS, World } from './world'

function makeWorld(): World {
    let nextId = 0
    return new World({ makeId: () => `id-${++nextId}`, random: () => 0.5 })
}

function join(world: World, address = 'address-1'): JoinedPlayer {
    const joined = world.join('web', address, 0)
    if (!joined.ok) {
        throw new Error(joined.error)
    }
    return joined.player
}

// Runs the world for the given time in ticks of 50 ms, and returns every position the hedgehog had.
function walk(world: World, token: string, from: number, milliseconds: number): Array<{ x: number; y: number }> {
    const positions: Array<{ x: number; y: number }> = []
    for (let now = from; now <= from + milliseconds; now += 50) {
        world.touch(token, now)
        world.tick(now)
        const you = world.snapshot(token).you!
        positions.push({ x: you.x, y: you.y })
    }
    return positions
}

describe('World', () => {
    it.each([
        ['walks around the pond to a spot behind it', { x: 11, y: 6.5 }, 0.01],
        ['walks around the campfire to its far side', { x: 20, y: 8 }, 0.01],
        ['stops at the edge of the pond when the target is in it', { x: 11, y: 10.6 }, 3.5],
        ['stops at the corner of the square when the target is far outside it', { x: 60, y: -20 }, 33.5],
    ])('%s', (_case, target, within) => {
        const world = makeWorld()
        const { token } = join(world)
        expect(world.snapshot(token).you).toMatchObject(SPAWN)

        world.moveTo(token, target.x, target.y)
        const positions = walk(world, token, 0, 8000)
        positions.forEach((position) => expect(isWalkable(position.x, position.y, 0.05)).toBe(true))
        const you = world.snapshot(token).you!
        expect(you.moving).toBe(false)
        expect(Math.hypot(you.x - target.x, you.y - target.y)).toBeLessThanOrEqual(within)
    })

    it('walks at one speed, with no jump between ticks', () => {
        const world = makeWorld()
        const { token } = join(world)
        world.moveTo(token, 3, 20)

        const positions = walk(world, token, 0, 1500)
        const steps = positions.slice(1).map((position, index) => {
            const previous = positions[index]!
            return Math.hypot(position.x - previous.x, position.y - previous.y)
        })
        // 7 units per second is 0.35 units per tick of 50 ms. The server rounds positions to 0.01.
        steps.forEach((step) => expect(step).toBeCloseTo(0.35, 1))
    })

    it('walks to an object and uses it on arrival', () => {
        const world = makeWorld()
        const { token } = join(world)
        expect(world.poke(token, 'ship', 0)).toEqual({ ok: false, error: 'too_far' })

        world.walkToUse(token, 'ship')
        walk(world, token, 0, 6000)

        expect(world.snapshot(token).objects.deploys).toBe(1)
        expect(world.snapshot(token).feed.at(-1)).toMatchObject({ kind: 'poke', objectId: 'ship' })
    })

    it('drops the plan to use an object when the player walks somewhere else', () => {
        const world = makeWorld()
        const { token } = join(world)
        const ship = OBJECTS.find((object) => object.id === 'ship')!

        world.walkToUse(token, 'ship')
        world.moveTo(token, ship.stand.x, ship.stand.y)
        walk(world, token, 0, 6000)

        expect(world.snapshot(token).you).toMatchObject({ x: ship.stand.x, y: ship.stand.y })
        expect(world.snapshot(token).objects.deploys).toBe(0)
    })

    it('keeps polling hedgehogs and removes idle ones', () => {
        const world = makeWorld()
        const active = join(world)
        const idle = join(world)

        const later = LIMITS.idleTimeoutMs + 1
        expect(world.touch(active.token, later)).not.toBeNull()
        const { departed } = world.tick(later)

        expect(departed).toEqual([{ id: idle.id, client: 'web', reason: 'idle', durationMs: later }])
        expect(world.snapshot(null).players.map((player) => player.id)).toEqual([active.id])
        expect(world.touch(idle.token, later)).toBeNull()
    })

    it.each([
        ['free text instead of a preset phrase', 'buy my crypto', 0, 'unknown_phrase'],
        ['a second phrase inside the cooldown', 'hi', LIMITS.sayCooldownMs - 1, 'cooldown'],
    ])('rejects %s', (_case, phraseId, delay, error) => {
        const world = makeWorld()
        const { token } = join(world)
        expect(world.say(token, 'quills', 0)).toEqual({ ok: true })
        const feedBefore = world.snapshot(token).feed

        expect(world.say(token, phraseId, delay)).toEqual({ ok: false, error })
        expect(world.snapshot(token).feed).toEqual(feedBefore)
    })

    it('shows a preset emote for a short time, and rejects any other', () => {
        const world = makeWorld()
        const { token } = join(world)

        expect(world.emote(token, '<img src=x>', 0)).toEqual({ ok: false, error: 'unknown_emote' })
        expect(world.emote(token, 'party', 0)).toEqual({ ok: true })
        expect(world.snapshot(token).you!.emote).toMatchObject({ emoji: '🎉' })

        world.touch(token, LIMITS.emoteMs)
        world.tick(LIMITS.emoteMs)
        expect(world.snapshot(token).you!.emote).toBeNull()
    })

    it('turns hedgehogs away once the club is full, and gives each one in it a different name', () => {
        const world = makeWorld()
        for (let i = 0; i < LIMITS.maxPlayers; i++) {
            join(world, `address-${i}`)
        }

        expect(world.join('web', 'one-more-address', 0)).toEqual({ ok: false, error: 'club_full' })
        const names = world.snapshot(null).players.map((player) => player.name)
        expect(new Set(names).size).toBe(LIMITS.maxPlayers)
        expect(names.filter((name) => /\d/.test(name))).toEqual([])
    })

    it('stops one address from taking every place, and frees a place when its hedgehog leaves', () => {
        const world = makeWorld()
        const fromOneAddress = Array.from({ length: LIMITS.maxPlayersPerAddress }, () => join(world, 'greedy'))

        expect(world.join('web', 'greedy', 0)).toEqual({ ok: false, error: 'too_many_from_address' })
        expect(world.join('web', 'someone-else', 0)).toMatchObject({ ok: true })

        world.leave(fromOneAddress[0]!.token, 0)
        expect(world.join('web', 'greedy', 0)).toMatchObject({ ok: true })
    })
})
