// @ts-expect-error The browser copy of the walk calculation is plain JavaScript.
import { positionAt as positionAtInBrowser } from '../web/walk.js'
import { OBJECTS, SPAWN, WALK_SPEED } from './content'
import { positionAt } from './walk'
import { isWalkable, type JoinedPlayer, LIMITS, World, type WorldEvent } from './world'

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
        const you = world.snapshot(token, 0).you!
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
        expect(world.snapshot(token, 0).you).toMatchObject(SPAWN)

        world.moveTo(token, target.x, target.y, 0)
        const positions = walk(world, token, 0, 8000)
        positions.forEach((position) => expect(isWalkable(position.x, position.y, 0.05)).toBe(true))
        const you = world.snapshot(token, 0).you!
        expect(you.moving).toBe(false)
        expect(Math.hypot(you.x - target.x, you.y - target.y)).toBeLessThanOrEqual(within)
    })

    it('walks at one speed, with no jump between ticks', () => {
        const world = makeWorld()
        const { token } = join(world)
        world.moveTo(token, 3, 20, 0)

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

        world.walkToUse(token, 'ship', 0)
        walk(world, token, 0, 6000)

        expect(world.snapshot(token, 0).objects.deploys).toBe(1)
        expect(world.snapshot(token, 0).feed.at(-1)).toMatchObject({ kind: 'poke', objectId: 'ship' })
    })

    it('drops the plan to use an object when the player walks somewhere else', () => {
        const world = makeWorld()
        const { token } = join(world)
        const ship = OBJECTS.find((object) => object.id === 'ship')!

        world.walkToUse(token, 'ship', 0)
        world.moveTo(token, ship.stand.x, ship.stand.y, 0)
        walk(world, token, 0, 6000)

        expect(world.snapshot(token, 0).you).toMatchObject({ x: ship.stand.x, y: ship.stand.y })
        expect(world.snapshot(token, 0).objects.deploys).toBe(0)
    })

    it('lets a client that replays the walk event land where the server is, at every tick', () => {
        const world = makeWorld()
        const { token } = join(world)
        const events: WorldEvent[] = []
        world.subscribe((event) => events.push(event))

        world.moveTo(token, 11, 6.5, 100)
        const walk = events.find((event) => event.kind === 'walk')!
        expect(walk).toMatchObject({ kind: 'walk', at: 100, from: SPAWN })

        for (let now = 100; now <= 8000; now += 50) {
            world.touch(token, now)
            world.tick(now)
            const server = world.snapshot(token, now).you!
            for (const replay of [positionAt, positionAtInBrowser]) {
                const client = replay(walk, WALK_SPEED, now)
                expect(Math.hypot(client.x - server.x, client.y - server.y)).toBeLessThan(0.02)
                expect(client.moving).toBe(server.moving)
            }
        }
    })

    it('hands out the events after a number, and asks for a snapshot when they are gone', () => {
        const world = makeWorld()
        const first = join(world)
        expect(world.eventsSince(0, 0)).toMatchObject({ seq: 1, events: [{ kind: 'join', seq: 1 }] })
        expect(world.eventsSince(1, 0)).toMatchObject({ seq: 1, events: [] })
        expect(world.eventsSince(5, 0)).toBeNull()

        for (let i = 0; i < LIMITS.eventLog; i++) {
            world.leave(join(world, `address-${i % 5}`).token, 0)
        }
        const seq = world.snapshot(null, 0).seq
        expect(world.eventsSince(0, 0)).toBeNull()
        expect(world.eventsSince(seq - 1, 0)).toMatchObject({ events: [{ kind: 'leave', seq }] })
        expect(world.touch(first.token, 0)).not.toBeNull()
    })

    it('refuses a flood of actions from one player, and takes them again as time passes', () => {
        const world = makeWorld()
        const { token } = join(world)
        const results = Array.from({ length: LIMITS.actionBurst + 1 }, (_, i) => world.moveTo(token, 2 + i, 8, 0))
        expect(results.slice(0, -1).every((result) => result.ok)).toBe(true)
        expect(results.at(-1)).toEqual({ ok: false, error: 'too_many_actions' })
        expect(world.moveTo(token, 20, 8, 1000 / LIMITS.actionsPerSecond + 1)).toEqual({ ok: true })
    })

    it('changes the look of a hedgehog but not its name', () => {
        const world = makeWorld()
        const { token, name } = join(world)
        expect(world.changeLook(token, 'robohog', 'tophat', 0)).toEqual({ ok: true })
        expect(world.changeLook(token, 'robohog', 'crown', 0)).toEqual({ ok: false, error: 'invalid_look' })
        expect(world.snapshot(token, 0).you).toMatchObject({ name, skin: 'robohog', hat: null })
        expect(world.eventsSince(1, 0)!.events).toMatchObject([{ kind: 'look', skin: 'robohog', hat: null }])
    })

    it('keeps hedgehogs that send requests and removes idle ones', () => {
        const world = makeWorld()
        const active = join(world)
        const idle = join(world)

        const later = LIMITS.idleTimeoutMs + 1
        expect(world.touch(active.token, later)).not.toBeNull()
        const { departed } = world.tick(later)

        expect(departed).toEqual([{ id: idle.id, client: 'web', reason: 'idle', durationMs: later }])
        expect(world.snapshot(null, 0).players.map((player) => player.id)).toEqual([active.id])
        expect(world.touch(idle.token, later)).toBeNull()
    })

    it('removes a hedgehog soon after its stream closes unless the client comes back', () => {
        const world = makeWorld()
        const gone = join(world)
        const back = join(world)
        world.disconnect(gone.token, 0)
        world.disconnect(back.token, 0)
        expect(world.touch(back.token, 1)).not.toBeNull()

        const { departed } = world.tick(LIMITS.streamGraceMs + 1)

        expect(departed.map((player) => player.id)).toEqual([gone.id])
        expect(world.tick(LIMITS.idleTimeoutMs).departed).toEqual([])
    })

    it.each([
        ['free text instead of a preset phrase', 'buy my crypto', 0, 'unknown_phrase'],
        ['a second phrase inside the cooldown', 'hi', LIMITS.sayCooldownMs - 1, 'cooldown'],
    ])('rejects %s', (_case, phraseId, delay, error) => {
        const world = makeWorld()
        const { token } = join(world)
        expect(world.say(token, 'quills', 0)).toEqual({ ok: true })
        const feedBefore = world.snapshot(token, 0).feed

        expect(world.say(token, phraseId, delay)).toEqual({ ok: false, error })
        expect(world.snapshot(token, 0).feed).toEqual(feedBefore)
    })

    it('shows a preset emote for a short time, and rejects any other', () => {
        const world = makeWorld()
        const { token } = join(world)

        expect(world.emote(token, '<img src=x>', 0)).toEqual({ ok: false, error: 'unknown_emote' })
        expect(world.emote(token, 'party', 0)).toEqual({ ok: true })
        expect(world.snapshot(token, 0).you!.emote).toMatchObject({ emoji: '🎉' })
        expect(world.snapshot(token, 0).feed.at(-1)).toMatchObject({
            kind: 'emote',
            text: expect.stringMatching(/ 🎉$/),
        })

        world.touch(token, LIMITS.emoteMs)
        world.tick(LIMITS.emoteMs)
        expect(world.snapshot(token, 0).you!.emote).toBeNull()
    })

    it('turns hedgehogs away once the club is full, and gives each one in it a different name', () => {
        const world = makeWorld()
        for (let i = 0; i < LIMITS.maxPlayers; i++) {
            join(world, `address-${i}`)
        }

        expect(world.join('web', 'one-more-address', 0)).toEqual({ ok: false, error: 'club_full' })
        const names = world.snapshot(null, 0).players.map((player) => player.name)
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
