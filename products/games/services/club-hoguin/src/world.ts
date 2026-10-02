import {
    BUG_SPECIES,
    EXPERIMENT_SIGNIFICANCE_VOTES,
    MAP_HEIGHT,
    MAP_ROWS,
    MAP_WIDTH,
    MAX_JOKES,
    NAME_ADJECTIVES,
    NAME_NOUNS,
    OBJECTS,
    type ObjectId,
    PHRASES,
    REPLAY_REELS,
    SKINS,
    SPAWN,
    type Skin,
    WALL,
    WATER,
    type WorldObject,
} from './content.ts'

export const CLIENT_KINDS = ['web', 'embed', 'mod'] as const
export type ClientKind = (typeof CLIENT_KINDS)[number]
export type Facing = 'left' | 'right'

export const LIMITS = {
    maxPlayers: 150,
    idleTimeoutMs: 20_000,
    sayCooldownMs: 1_500,
    pokeCooldownMs: 1_000,
    bubbleMs: 6_000,
    feedSize: 20,
    pokeReach: 2,
}

interface Player {
    id: string
    token: string
    name: string
    skin: Skin
    client: ClientKind
    x: number
    y: number
    path: Array<{ x: number; y: number }>
    facing: Facing
    joinedAt: number
    lastSeenAt: number
    bubble: { text: string; until: number } | null
    lastSayAt: number
    lastPokeAt: number
}

export interface PlayerView {
    id: string
    name: string
    skin: Skin
    client: ClientKind
    x: number
    y: number
    facing: Facing
    moving: boolean
    bubble: string | null
}

export interface FeedEntry {
    id: number
    at: number
    text: string
}

export interface ObjectState {
    lightsOn: boolean
    doorA: number
    doorB: number
    bugsCaught: number
    deploys: number
}

export interface Snapshot {
    you: PlayerView | null
    players: PlayerView[]
    feed: FeedEntry[]
    objects: ObjectState
    online: number
}

export interface JoinedPlayer {
    id: string
    token: string
    name: string
    skin: Skin
}

export interface DepartedPlayer {
    id: string
    client: ClientKind
    reason: 'left' | 'idle'
    durationMs: number
}

export type ActionResult = { ok: true } | { ok: false; error: string }
export type PokeResult = { ok: true; objectId: ObjectId } | { ok: false; error: string }

export interface WorldOptions {
    makeId: () => string
    random: () => number
}

export function isClientKind(value: unknown): value is ClientKind {
    return typeof value === 'string' && (CLIENT_KINDS as readonly string[]).includes(value)
}

export function isWalkable(x: number, y: number): boolean {
    if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= MAP_WIDTH || y >= MAP_HEIGHT) {
        return false
    }
    const tile = MAP_ROWS[y]?.[x]
    if (tile === WALL || tile === WATER) {
        return false
    }
    return !OBJECTS.some(
        (object) => x >= object.x && x < object.x + object.w && y >= object.y && y < object.y + object.h
    )
}

function distanceToObject(x: number, y: number, object: WorldObject): number {
    const dx = Math.max(object.x - x, 0, x - (object.x + object.w - 1))
    const dy = Math.max(object.y - y, 0, y - (object.y + object.h - 1))
    return Math.max(dx, dy)
}

// Breadth-first search over the tile grid. When the target is blocked or unreachable,
// the path ends on the reachable tile closest to it, so a click on an object walks up to it.
export function findPath(
    from: { x: number; y: number },
    to: { x: number; y: number }
): Array<{ x: number; y: number }> {
    const index = (x: number, y: number): number => y * MAP_WIDTH + x
    const distance = (x: number, y: number): number => Math.abs(x - to.x) + Math.abs(y - to.y)
    const parents = new Map<number, number>([[index(from.x, from.y), -1]])
    const queue: Array<[number, number]> = [[from.x, from.y]]
    let best: [number, number] = [from.x, from.y]
    for (let head = 0; head < queue.length; head++) {
        const [x, y] = queue[head] as [number, number]
        if (distance(x, y) < distance(best[0], best[1])) {
            best = [x, y]
        }
        if (x === to.x && y === to.y) {
            break
        }
        for (const [nx, ny] of [
            [x + 1, y],
            [x - 1, y],
            [x, y + 1],
            [x, y - 1],
        ] as Array<[number, number]>) {
            if (isWalkable(nx, ny) && !parents.has(index(nx, ny))) {
                parents.set(index(nx, ny), index(x, y))
                queue.push([nx, ny])
            }
        }
    }
    const path: Array<{ x: number; y: number }> = []
    for (let at = index(best[0], best[1]); at !== index(from.x, from.y); at = parents.get(at) as number) {
        path.unshift({ x: at % MAP_WIDTH, y: Math.floor(at / MAP_WIDTH) })
    }
    return path
}

export class World {
    private readonly makeId: () => string
    private readonly random: () => number
    private readonly players = new Map<string, Player>()
    private feed: FeedEntry[] = []
    private nextFeedId = 1
    private objects: ObjectState = { lightsOn: true, doorA: 0, doorB: 0, bugsCaught: 0, deploys: 0 }

    constructor(options: WorldOptions) {
        this.makeId = options.makeId
        this.random = options.random
    }

    join(client: ClientKind, now: number): JoinedPlayer | null {
        if (this.players.size >= LIMITS.maxPlayers) {
            return null
        }
        const spawn = this.spawnPoint()
        const player: Player = {
            id: this.makeId(),
            token: this.makeId(),
            name: this.uniqueName(),
            skin: this.pick(SKINS),
            client,
            x: spawn.x,
            y: spawn.y,
            path: [],
            facing: this.random() < 0.5 ? 'left' : 'right',
            joinedAt: now,
            lastSeenAt: now,
            bubble: null,
            lastSayAt: -Infinity,
            lastPokeAt: -Infinity,
        }
        this.players.set(player.token, player)
        this.post(now, `${player.name} waddled in`)
        return { id: player.id, token: player.token, name: player.name, skin: player.skin }
    }

    // Every authenticated request counts as a heartbeat, so a polling client never goes idle.
    touch(token: string, now: number): { id: string; client: ClientKind } | null {
        const player = this.players.get(token)
        if (!player) {
            return null
        }
        player.lastSeenAt = now
        return { id: player.id, client: player.client }
    }

    moveTo(token: string, x: unknown, y: unknown): ActionResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        if (typeof x !== 'number' || typeof y !== 'number' || !Number.isInteger(x) || !Number.isInteger(y)) {
            return { ok: false, error: 'invalid_target' }
        }
        player.path = findPath(player, { x, y })
        return { ok: true }
    }

    say(token: string, phraseId: unknown, now: number): ActionResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        const phrase = PHRASES.find((candidate) => candidate.id === phraseId)
        if (!phrase) {
            return { ok: false, error: 'unknown_phrase' }
        }
        if (now - player.lastSayAt < LIMITS.sayCooldownMs) {
            return { ok: false, error: 'cooldown' }
        }
        player.lastSayAt = now
        player.bubble = { text: phrase.text, until: now + LIMITS.bubbleMs }
        this.post(now, `${player.name}: ${phrase.text}`)
        return { ok: true }
    }

    // Without an object id, the hedgehog pokes the closest object in reach.
    poke(token: string, objectId: unknown, now: number): PokeResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        if (objectId !== undefined && !OBJECTS.some((object) => object.id === objectId)) {
            return { ok: false, error: 'unknown_object' }
        }
        const inReach = OBJECTS.filter(
            (object) =>
                (objectId === undefined || object.id === objectId) &&
                distanceToObject(player.x, player.y, object) <= LIMITS.pokeReach
        ).sort((a, b) => distanceToObject(player.x, player.y, a) - distanceToObject(player.x, player.y, b))
        const object = inReach[0]
        if (!object) {
            return { ok: false, error: 'too_far' }
        }
        if (now - player.lastPokeAt < LIMITS.pokeCooldownMs) {
            return { ok: false, error: 'cooldown' }
        }
        player.lastPokeAt = now
        this.post(now, this.pokeObject(object.id, player.name))
        return { ok: true, objectId: object.id }
    }

    leave(token: string, now: number): DepartedPlayer | null {
        const player = this.players.get(token)
        if (!player) {
            return null
        }
        this.players.delete(token)
        this.post(now, `${player.name} waddled off`)
        return { id: player.id, client: player.client, reason: 'left', durationMs: now - player.joinedAt }
    }

    tick(now: number): DepartedPlayer[] {
        const departed: DepartedPlayer[] = []
        for (const player of this.players.values()) {
            if (now - player.lastSeenAt > LIMITS.idleTimeoutMs) {
                this.players.delete(player.token)
                this.post(now, `${player.name} wandered off`)
                departed.push({
                    id: player.id,
                    client: player.client,
                    reason: 'idle',
                    durationMs: now - player.joinedAt,
                })
                continue
            }
            if (player.bubble && player.bubble.until <= now) {
                player.bubble = null
            }
            this.step(player)
        }
        return departed
    }

    snapshot(token: string | null): Snapshot {
        const views = [...this.players.values()].map((player) => this.view(player))
        const viewer = token ? this.players.get(token) : undefined
        return {
            you: viewer ? this.view(viewer) : null,
            players: views,
            feed: this.feed.slice(-LIMITS.feedSize),
            objects: { ...this.objects },
            online: views.length,
        }
    }

    private step(player: Player): void {
        const next = player.path.shift()
        if (!next) {
            return
        }
        if (next.x !== player.x) {
            player.facing = next.x < player.x ? 'left' : 'right'
        }
        player.x = next.x
        player.y = next.y
    }

    private pokeObject(objectId: ObjectId, name: string): string {
        switch (objectId) {
            case 'flag':
                this.objects.lightsOn = !this.objects.lightsOn
                return `${name} set cozy-lighting to ${this.objects.lightsOn ? 'true' : 'false'} for 100% of hogs`
            case 'replay':
                return `Now playing in the replay cinema: ${this.pick(REPLAY_REELS)}`
            case 'max':
                return `Max says: ${this.pick(MAX_JOKES)}`
            case 'bugs':
                this.objects.bugsCaught += 1
                return `${name} caught a ${this.pick(BUG_SPECIES)} and assigned it to themselves (${this.objects.bugsCaught} in the jar)`
            case 'door-a':
            case 'door-b':
                return this.voteDoor(objectId === 'door-a' ? 'A' : 'B', name)
            case 'ship':
                this.objects.deploys += 1
                return `${name} shipped to production. Deploys today: ${this.objects.deploys}`
        }
    }

    private voteDoor(door: 'A' | 'B', name: string): string {
        if (door === 'A') {
            this.objects.doorA += 1
        } else {
            this.objects.doorB += 1
        }
        const { doorA, doorB } = this.objects
        const total = doorA + doorB
        const leader = doorA === doorB ? 'It is a tie' : doorA > doorB ? 'A leads' : 'B leads'
        const verdict =
            total < EXPERIMENT_SIGNIFICANCE_VOTES ? 'not significant yet' : `ship door ${doorA >= doorB ? 'A' : 'B'}`
        return `${name} walked through door ${door}. ${leader} ${doorA} to ${doorB}, ${verdict}`
    }

    private view(player: Player): PlayerView {
        return {
            id: player.id,
            name: player.name,
            skin: player.skin,
            client: player.client,
            x: player.x,
            y: player.y,
            facing: player.facing,
            moving: player.path.length > 0,
            bubble: player.bubble?.text ?? null,
        }
    }

    private post(now: number, text: string): void {
        this.feed.push({ id: this.nextFeedId++, at: now, text })
        if (this.feed.length > LIMITS.feedSize) {
            this.feed = this.feed.slice(-LIMITS.feedSize)
        }
    }

    private spawnPoint(): { x: number; y: number } {
        for (let attempt = 0; attempt < 20; attempt++) {
            const x = SPAWN.x + Math.floor(this.random() * 7) - 3
            const y = SPAWN.y + Math.floor(this.random() * 5) - 2
            if (isWalkable(x, y)) {
                return { x, y }
            }
        }
        return { ...SPAWN }
    }

    private uniqueName(): string {
        const taken = new Set([...this.players.values()].map((player) => player.name))
        for (let attempt = 0; attempt < 10; attempt++) {
            const name = `${this.pick(NAME_ADJECTIVES)} ${this.pick(NAME_NOUNS)}`
            if (!taken.has(name)) {
                return name
            }
        }
        return `${this.pick(NAME_ADJECTIVES)} ${this.pick(NAME_NOUNS)} ${this.players.size + 1}`
    }

    private pick<T>(items: readonly T[]): T {
        return items[Math.floor(this.random() * items.length) % items.length] as T
    }
}
