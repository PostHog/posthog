import {
    BUG_SPECIES,
    COLLIDERS,
    EMOTES,
    EXPERIMENT_SIGNIFICANCE_VOTES,
    type Hat,
    HATS,
    isInsideEllipse,
    isInsideRect,
    MAX_JOKES,
    NAMES,
    OBJECTS,
    type ObjectId,
    PHRASES,
    type Rect,
    REPLAY_REELS,
    SKINS,
    SPAWN,
    type Skin,
    WALK_BOUNDS,
    WALK_SPEED,
    WORLD_DEPTH,
    WORLD_WIDTH,
} from './content.ts'

export const CLIENT_KINDS = ['web', 'embed', 'mod'] as const
export type ClientKind = (typeof CLIENT_KINDS)[number]
export type Facing = 'left' | 'right'

export const LIMITS = {
    eventLog: 600,
    maxPlayers: 150,
    maxPlayersPerAddress: 10,
    idleTimeoutMs: 20_000,
    // A browser reconnects a dropped event stream within this time. A closed tab or a killed Chrome does not.
    streamGraceMs: 3_000,
    sayCooldownMs: 1_500,
    emoteCooldownMs: 800,
    pokeCooldownMs: 1_000,
    // The ship it button is for pressing a lot. One rocket every half second, from anyone.
    shipCooldownMs: 500,
    // What one player can do: a burst, then this many actions a second. Moves, phrases, emotes, and uses all count.
    actionsPerSecond: 10,
    actionBurst: 15,
    bubbleMs: 6_000,
    emoteMs: 2_500,
    feedSize: 20,
    pokeReach: 2.2,
}

export interface Point {
    x: number
    y: number
}

interface Player {
    id: string
    token: string
    name: string
    skin: Skin
    hat: Hat | null
    client: ClientKind
    // True for a hedgehog the server runs itself. Clients show it, so nobody mistakes one for a person.
    bot: boolean
    address: string
    x: number
    y: number
    path: Point[]
    // The object the hedgehog uses when it gets to the end of its path.
    intent: ObjectId | null
    facing: Facing
    joinedAt: number
    // The moment the hedgehog wanders off unless the client shows up before it.
    leaveAt: number
    lastStepAt: number
    bubble: { text: string; until: number } | null
    emote: { emoji: string; until: number; seq: number } | null
    lastSayAt: number
    lastEmoteAt: number
    lastPokeAt: number
    actions: { tokens: number; at: number }
}

export interface PlayerView {
    id: string
    name: string
    skin: Skin
    hat: Hat | null
    bot: boolean
    client: ClientKind
    x: number
    y: number
    // The points the hedgehog still walks through, in order. Clients move the hedgehog along them between polls.
    path: Point[]
    facing: Facing
    moving: boolean
    bubble: string | null
    emote: { emoji: string; seq: number } | null
}

export type FeedKind = 'join' | 'leave' | 'say' | 'poke'

export interface FeedEntry {
    id: number
    at: number
    text: string
    kind: FeedKind
    playerId: string
    objectId?: ObjectId
}

export interface ObjectState {
    lightsOn: boolean
    doorA: number
    doorB: number
    bugsCaught: number
    deploys: number
    nowPlaying: string | null
    maxSays: string | null
}

export interface Snapshot {
    you: PlayerView | null
    players: PlayerView[]
    feed: FeedEntry[]
    objects: ObjectState
    online: number
    // The number of the last event in this snapshot. A client asks for events after it.
    seq: number
    // The server clock when the snapshot was taken, so a client can line up its own clock.
    at: number
    serverId: string
}

// Every change in the town is one event. A client that has the snapshot and every event after it
// knows the town, and it walks every hedgehog by itself from the walk events.
export type WorldEventBody =
    | { kind: 'join'; player: PlayerView; text: string }
    | { kind: 'leave'; id: string; reason: 'left' | 'idle'; text: string }
    | { kind: 'walk'; id: string; from: Point; path: Point[] }
    | { kind: 'say'; id: string; phrase: string; text: string }
    | { kind: 'emote'; id: string; emoji: string }
    | { kind: 'look'; id: string; skin: Skin; hat: Hat | null }
    | { kind: 'poke'; id: string; objectId: ObjectId; objects: ObjectState; text: string }
export type WorldEvent = { seq: number; at: number } & WorldEventBody

export interface EventsSince {
    seq: number
    at: number
    events: WorldEvent[]
}

export interface JoinedPlayer {
    id: string
    token: string
    name: string
    skin: Skin
    hat: Hat | null
}

export interface DepartedPlayer {
    id: string
    client: ClientKind
    reason: 'left' | 'idle'
    durationMs: number
}

export interface PokeEvent {
    playerId: string
    client: ClientKind
    objectId: ObjectId
}

export type JoinResult =
    | { ok: true; player: JoinedPlayer }
    | { ok: false; error: 'club_full' | 'too_many_from_address' }
export type ActionResult = { ok: true } | { ok: false; error: string }
export type PokeResult = { ok: true; objectId: ObjectId } | { ok: false; error: string }

export interface WorldOptions {
    makeId: () => string
    random: () => number
    serverId?: string
}

export function isClientKind(value: unknown): value is ClientKind {
    return typeof value === 'string' && (CLIENT_KINDS as readonly string[]).includes(value)
}

export function isSkin(value: unknown): value is Skin {
    return typeof value === 'string' && (SKINS as readonly string[]).includes(value)
}

export function isHat(value: unknown): value is Hat {
    return typeof value === 'string' && (HATS as readonly string[]).includes(value)
}

// A hedgehog is a circle of this radius. It keeps this far from a wall, the pond, and every object.
const BODY_RADIUS = 0.45
// The side of one cell of the grid that the path search uses.
const CELL = 0.5
const COLUMNS = Math.ceil(WORLD_WIDTH / CELL)
const ROWS = Math.ceil(WORLD_DEPTH / CELL)

// With slack, a point that is up to that far inside a wall or an object still counts as walkable.
// A path is checked at points 0.1 units apart and a position is rounded to 0.01 units,
// so a walking hedgehog can be a few hundredths of a unit inside.
export function isWalkable(x: number, y: number, slack = 0): boolean {
    if (
        !Number.isFinite(x) ||
        !Number.isFinite(y) ||
        x < WALK_BOUNDS.minX - slack ||
        x > WALK_BOUNDS.maxX + slack ||
        y < WALK_BOUNDS.minY - slack ||
        y > WALK_BOUNDS.maxY + slack
    ) {
        return false
    }
    return !COLLIDERS.some((collider) =>
        collider.shape === 'rect'
            ? isInsideRect(collider, x, y, BODY_RADIUS - slack)
            : isInsideEllipse(collider, x, y, BODY_RADIUS - slack)
    )
}

const cellCenter = (column: number, row: number): Point => ({ x: (column + 0.5) * CELL, y: (row + 0.5) * CELL })

function isLineWalkable(from: Point, to: Point): boolean {
    const length = Math.hypot(to.x - from.x, to.y - from.y)
    const steps = Math.max(1, Math.ceil(length / 0.1))
    for (let step = 0; step <= steps; step++) {
        const t = step / steps
        if (!isWalkable(from.x + (to.x - from.x) * t, from.y + (to.y - from.y) * t)) {
            return false
        }
    }
    return true
}

function distanceToRect(x: number, y: number, rect: Rect): number {
    const dx = Math.max(rect.x - x, 0, x - (rect.x + rect.w))
    const dy = Math.max(rect.y - y, 0, y - (rect.y + rect.h))
    return Math.hypot(dx, dy)
}

const NEIGHBORS: ReadonlyArray<readonly [number, number]> = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
    [1, 1],
    [1, -1],
    [-1, 1],
    [-1, -1],
]

// For each cell, the neighbors that a hedgehog can walk to in a straight line from the center of the cell.
// A cell with a walkable center can still have a blocked corner, so each step between two cells is checked.
const OPEN_NEIGHBORS: ReadonlyArray<readonly number[]> = Array.from({ length: COLUMNS * ROWS }, (_cell, index) => {
    const column = index % COLUMNS
    const row = Math.floor(index / COLUMNS)
    const center = cellCenter(column, row)
    if (!isWalkable(center.x, center.y)) {
        return []
    }
    return NEIGHBORS.filter(([dx, dy]) => {
        const nextColumn = column + dx
        const nextRow = row + dy
        return (
            nextColumn >= 0 &&
            nextRow >= 0 &&
            nextColumn < COLUMNS &&
            nextRow < ROWS &&
            isLineWalkable(center, cellCenter(nextColumn, nextRow))
        )
    }).map(([dx, dy]) => (row + dy) * COLUMNS + column + dx)
})

// The cells that a hedgehog at this point can walk to in a straight line: the cell it is in, or one next to it.
function cellsInReach(from: Point): number[] {
    const column = Math.min(COLUMNS - 1, Math.max(0, Math.floor(from.x / CELL)))
    const row = Math.min(ROWS - 1, Math.max(0, Math.floor(from.y / CELL)))
    const cells: number[] = []
    for (const [dx, dy] of [[0, 0], ...NEIGHBORS] as Array<[number, number]>) {
        const nextColumn = column + dx
        const nextRow = row + dy
        if (nextColumn < 0 || nextRow < 0 || nextColumn >= COLUMNS || nextRow >= ROWS) {
            continue
        }
        const cell = nextRow * COLUMNS + nextColumn
        if (
            (OPEN_NEIGHBORS[cell] as readonly number[]).length > 0 &&
            isLineWalkable(from, cellCenter(nextColumn, nextRow))
        ) {
            cells.push(cell)
        }
    }
    return cells
}

// Breadth-first search over the cell grid, then the path is cut down to the corners that a straight walk needs.
// When the target is blocked or unreachable, the path ends on the reachable point closest to it,
// so a click on an object or on the pond walks up to it.
export function findPath(from: Point, to: Point): Point[] {
    if (isWalkable(to.x, to.y) && isLineWalkable(from, to)) {
        return [{ x: to.x, y: to.y }]
    }
    const parents = new Map<number, number>()
    const queue: number[] = cellsInReach(from)
    queue.forEach((cell) => parents.set(cell, -1))
    let best = -1
    let bestDistance = Math.hypot(from.x - to.x, from.y - to.y)
    for (let head = 0; head < queue.length; head++) {
        const cell = queue[head] as number
        const center = cellCenter(cell % COLUMNS, Math.floor(cell / COLUMNS))
        const distance = Math.hypot(center.x - to.x, center.y - to.y)
        if (distance < bestDistance) {
            best = cell
            bestDistance = distance
        }
        if (distance < CELL * 0.75) {
            break
        }
        for (const next of OPEN_NEIGHBORS[cell] as readonly number[]) {
            if (!parents.has(next)) {
                parents.set(next, cell)
                queue.push(next)
            }
        }
    }
    const cells: Point[] = []
    for (let at = best; at !== -1; at = parents.get(at) as number) {
        cells.unshift(cellCenter(at % COLUMNS, Math.floor(at / COLUMNS)))
    }
    if (isWalkable(to.x, to.y) && cells.length > 0 && isLineWalkable(cells[cells.length - 1] as Point, to)) {
        cells.push({ x: to.x, y: to.y })
    }
    const path: Point[] = []
    let anchor = from
    for (let index = 0; index < cells.length; index++) {
        const next = cells[index + 1]
        if (!next || !isLineWalkable(anchor, next)) {
            anchor = cells[index] as Point
            path.push(anchor)
        }
    }
    return path
}

const round = (value: number): number => Math.round(value * 100) / 100

export class World {
    private readonly makeId: () => string
    private readonly random: () => number
    private readonly serverId: string
    private readonly players = new Map<string, Player>()
    private feed: FeedEntry[] = []
    private nextFeedId = 1
    private nextEmoteSeq = 1
    private events: WorldEvent[] = []
    private lastShipAt = -Infinity
    private seq = 0
    private readonly listeners = new Set<(event: WorldEvent) => void>()
    private objects: ObjectState = {
        lightsOn: true,
        doorA: 0,
        doorB: 0,
        bugsCaught: 0,
        deploys: 0,
        nowPlaying: null,
        maxSays: null,
    }

    constructor(options: WorldOptions) {
        this.makeId = options.makeId
        this.random = options.random
        this.serverId = options.serverId ?? 'test'
    }

    // The address is the network address of the client. The cap per address stops one client from taking every place.
    // A name is only given for a bot, whose name fits its personality. A person gets one from the pool.
    join(
        client: ClientKind,
        address: string,
        now: number,
        skin?: Skin,
        hat: Hat | null = null,
        name?: string,
        bot = false
    ): JoinResult {
        if (this.players.size >= LIMITS.maxPlayers) {
            return { ok: false, error: 'club_full' }
        }
        const fromAddress = [...this.players.values()].filter((player) => player.address === address).length
        if (fromAddress >= LIMITS.maxPlayersPerAddress) {
            return { ok: false, error: 'too_many_from_address' }
        }
        const spawn = this.spawnPoint()
        const player: Player = {
            id: this.makeId(),
            token: this.makeId(),
            name: name && !this.isNameTaken(name) ? name : this.uniqueName(),
            skin: skin ?? this.pick(SKINS),
            // Only the default hedgehog wears a hat; a hat is drawn for its shape. A player who picks none gets a random one.
            hat: (skin ?? 'default') === 'default' ? (hat ?? (this.random() < 0.3 ? null : this.pick(HATS))) : null,
            client,
            bot,
            address,
            x: spawn.x,
            y: spawn.y,
            path: [],
            intent: null,
            facing: this.random() < 0.5 ? 'left' : 'right',
            joinedAt: now,
            leaveAt: now + LIMITS.idleTimeoutMs,
            lastStepAt: now,
            bubble: null,
            emote: null,
            lastSayAt: -Infinity,
            lastEmoteAt: -Infinity,
            lastPokeAt: -Infinity,
            actions: { tokens: LIMITS.actionBurst, at: now },
        }
        this.players.set(player.token, player)
        const text = this.post(now, 'join', player, `${player.name} waddled in`)
        this.emit(now, { kind: 'join', player: this.view(player), text })
        return {
            ok: true,
            player: { id: player.id, token: player.token, name: player.name, skin: player.skin, hat: player.hat },
        }
    }

    // Every authenticated request counts as a heartbeat, so a polling client never goes idle.
    touch(token: string, now: number): { id: string; client: ClientKind } | null {
        const player = this.players.get(token)
        if (!player) {
            return null
        }
        player.leaveAt = now + LIMITS.idleTimeoutMs
        return { id: player.id, client: player.client }
    }

    // The event stream of the player closed. The next request, usually a reconnect, extends the deadline again.
    disconnect(token: string, now: number): void {
        const player = this.players.get(token)
        if (player) {
            player.leaveAt = Math.min(player.leaveAt, now + LIMITS.streamGraceMs)
        }
    }

    // Takes one action from the budget of the player. False when the budget is empty.
    private spendAction(player: Player, now: number): boolean {
        const budget = player.actions
        budget.tokens = Math.min(
            LIMITS.actionBurst,
            budget.tokens + ((now - budget.at) / 1000) * LIMITS.actionsPerSecond
        )
        budget.at = now
        if (budget.tokens < 1) {
            return false
        }
        budget.tokens -= 1
        return true
    }

    moveTo(token: string, x: unknown, y: unknown, now: number): ActionResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        if (!this.spendAction(player, now)) {
            return { ok: false, error: 'too_many_actions' }
        }
        if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) {
            return { ok: false, error: 'invalid_target' }
        }
        this.startWalk(player, findPath(player, { x, y }), now)
        player.intent = null
        return { ok: true }
    }

    // Walks the hedgehog to the object. The hedgehog uses the object when it gets there.
    walkToUse(token: string, objectId: unknown, now: number): ActionResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        const object = OBJECTS.find((candidate) => candidate.id === objectId)
        if (!object) {
            return { ok: false, error: 'unknown_object' }
        }
        if (!this.spendAction(player, now)) {
            return { ok: false, error: 'too_many_actions' }
        }
        this.startWalk(player, findPath(player, object.stand), now)
        player.intent = object.id
        return { ok: true }
    }

    // Changes the skin and the hat. The name and the place stay, so friends still know who this is.
    changeLook(token: string, skin: unknown, hat: unknown, now: number): ActionResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        if (!isSkin(skin) || (hat !== null && !isHat(hat))) {
            return { ok: false, error: 'invalid_look' }
        }
        if (!this.spendAction(player, now)) {
            return { ok: false, error: 'too_many_actions' }
        }
        player.skin = skin
        player.hat = skin === 'default' ? hat : null
        this.emit(now, { kind: 'look', id: player.id, skin: player.skin, hat: player.hat })
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
        if (now - player.lastSayAt < LIMITS.sayCooldownMs || !this.spendAction(player, now)) {
            return { ok: false, error: 'cooldown' }
        }
        player.lastSayAt = now
        player.bubble = { text: phrase.text, until: now + LIMITS.bubbleMs }
        const text = this.post(now, 'say', player, `${player.name}: ${phrase.text}`)
        this.emit(now, { kind: 'say', id: player.id, phrase: phrase.text, text })
        return { ok: true }
    }

    emote(token: string, emoteId: unknown, now: number): ActionResult {
        const player = this.players.get(token)
        if (!player) {
            return { ok: false, error: 'unknown_player' }
        }
        const emote = EMOTES.find((candidate) => candidate.id === emoteId)
        if (!emote) {
            return { ok: false, error: 'unknown_emote' }
        }
        if (now - player.lastEmoteAt < LIMITS.emoteCooldownMs || !this.spendAction(player, now)) {
            return { ok: false, error: 'cooldown' }
        }
        player.lastEmoteAt = now
        player.emote = { emoji: emote.emoji, until: now + LIMITS.emoteMs, seq: this.nextEmoteSeq++ }
        this.emit(now, { kind: 'emote', id: player.id, emoji: emote.emoji })
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
                distanceToRect(player.x, player.y, object.footprint) <= LIMITS.pokeReach
        ).sort(
            (a, b) => distanceToRect(player.x, player.y, a.footprint) - distanceToRect(player.x, player.y, b.footprint)
        )
        const object = inReach[0]
        if (!object) {
            return { ok: false, error: 'too_far' }
        }
        const cooldown = object.id === 'ship' ? LIMITS.shipCooldownMs : LIMITS.pokeCooldownMs
        if (
            now - player.lastPokeAt < cooldown ||
            (object.id === 'ship' && now - this.lastShipAt < LIMITS.shipCooldownMs) ||
            !this.spendAction(player, now)
        ) {
            return { ok: false, error: 'cooldown' }
        }
        player.lastPokeAt = now
        if (object.id === 'ship') {
            this.lastShipAt = now
        }
        const text = this.post(now, 'poke', player, this.pokeObject(object.id, player.name), object.id)
        this.emit(now, { kind: 'poke', id: player.id, objectId: object.id, objects: { ...this.objects }, text })
        return { ok: true, objectId: object.id }
    }

    leave(token: string, now: number): DepartedPlayer | null {
        const player = this.players.get(token)
        if (!player) {
            return null
        }
        this.players.delete(token)
        const text = this.post(now, 'leave', player, `${player.name} waddled off`)
        this.emit(now, { kind: 'leave', id: player.id, reason: 'left', text })
        return { id: player.id, client: player.client, reason: 'left', durationMs: now - player.joinedAt }
    }

    tick(now: number): { departed: DepartedPlayer[]; poked: PokeEvent[] } {
        const departed: DepartedPlayer[] = []
        const poked: PokeEvent[] = []
        for (const player of this.players.values()) {
            if (now > player.leaveAt) {
                this.players.delete(player.token)
                const text = this.post(now, 'leave', player, `${player.name} wandered off`)
                this.emit(now, { kind: 'leave', id: player.id, reason: 'idle', text })
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
            if (player.emote && player.emote.until <= now) {
                player.emote = null
            }
            this.step(player, now)
            if (player.intent && player.path.length === 0) {
                const objectId = player.intent
                player.intent = null
                if (this.poke(player.token, objectId, now).ok) {
                    poked.push({ playerId: player.id, client: player.client, objectId })
                }
            }
        }
        return { departed, poked }
    }

    snapshot(token: string | null, now: number): Snapshot {
        const views = [...this.players.values()].map((player) => this.view(player))
        const viewer = token ? this.players.get(token) : undefined
        return {
            you: viewer ? this.view(viewer) : null,
            players: views,
            feed: this.feed.slice(-LIMITS.feedSize),
            objects: { ...this.objects },
            online: views.length,
            seq: this.seq,
            at: now,
            serverId: this.serverId,
        }
    }

    // The events after `since`, or null when they are older than the log keeps, so the client takes a snapshot.
    eventsSince(since: number, now: number): EventsSince | null {
        const oldest = this.events[0]
        if (since > this.seq || since < this.seq - this.events.length || (oldest && since < oldest.seq - 1)) {
            return null
        }
        return { seq: this.seq, at: now, events: this.events.filter((event) => event.seq > since) }
    }

    // Calls the listener for every event from now on. Returns a function that stops the calls.
    subscribe(listener: (event: WorldEvent) => void): () => void {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
    }

    // The walk starts exactly now, so a client that replays the walk event lands where the server does.
    private startWalk(player: Player, path: Point[], now: number): void {
        this.step(player, now)
        player.path = path
        this.emit(now, {
            kind: 'walk',
            id: player.id,
            from: { x: round(player.x), y: round(player.y) },
            path: player.path.map((point) => ({ x: round(point.x), y: round(point.y) })),
        })
    }

    private emit(now: number, event: WorldEventBody): void {
        const full: WorldEvent = { ...event, seq: ++this.seq, at: now }
        this.events.push(full)
        if (this.events.length > LIMITS.eventLog) {
            this.events = this.events.slice(-LIMITS.eventLog)
        }
        this.listeners.forEach((listener) => listener(full))
    }

    // Moves the hedgehog along its path by the distance it walks in the time since the last step.
    private step(player: Player, now: number): void {
        let budget = (WALK_SPEED * Math.max(0, now - player.lastStepAt)) / 1000
        player.lastStepAt = now
        while (budget > 0 && player.path.length > 0) {
            const next = player.path[0] as Point
            const distance = Math.hypot(next.x - player.x, next.y - player.y)
            if (Math.abs(next.x - player.x) > 0.01) {
                player.facing = next.x < player.x ? 'left' : 'right'
            }
            if (distance <= budget) {
                player.x = next.x
                player.y = next.y
                player.path.shift()
                budget -= distance
            } else {
                player.x += ((next.x - player.x) / distance) * budget
                player.y += ((next.y - player.y) / distance) * budget
                budget = 0
            }
        }
    }

    private pokeObject(objectId: ObjectId, name: string): string {
        switch (objectId) {
            case 'flag':
                this.objects.lightsOn = !this.objects.lightsOn
                return `${name} set night-mode to ${this.objects.lightsOn ? 'false' : 'true'} for 100% of hogs`
            case 'replay':
                this.objects.nowPlaying = this.pick(REPLAY_REELS)
                return `Now playing in the replay cinema: ${this.objects.nowPlaying}`
            case 'max':
                this.objects.maxSays = this.pick(MAX_JOKES)
                return `Max says: ${this.objects.maxSays}`
            case 'bugs':
                this.objects.bugsCaught += 1
                return `${name} caught a ${this.pick(BUG_SPECIES)} (${this.objects.bugsCaught} in the jar)`
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
            hat: player.hat,
            bot: player.bot,
            client: player.client,
            x: round(player.x),
            y: round(player.y),
            path: player.path.map((point) => ({ x: round(point.x), y: round(point.y) })),
            facing: player.facing,
            moving: player.path.length > 0,
            bubble: player.bubble?.text ?? null,
            emote: player.emote ? { emoji: player.emote.emoji, seq: player.emote.seq } : null,
        }
    }

    private post(now: number, kind: FeedKind, player: Player, text: string, objectId?: ObjectId): string {
        this.feed.push({ id: this.nextFeedId++, at: now, text, kind, playerId: player.id, objectId })
        if (this.feed.length > LIMITS.feedSize) {
            this.feed = this.feed.slice(-LIMITS.feedSize)
        }
        return text
    }

    private spawnPoint(): Point {
        for (let attempt = 0; attempt < 20; attempt++) {
            const x = SPAWN.x + (this.random() - 0.5) * 8
            const y = SPAWN.y + (this.random() - 0.5) * 4
            if (isWalkable(x, y)) {
                return { x, y }
            }
        }
        return { ...SPAWN }
    }

    private isNameTaken(name: string): boolean {
        return [...this.players.values()].some((player) => player.name === name)
    }

    private uniqueName(): string {
        const taken = new Set([...this.players.values()].map((player) => player.name))
        return this.pick(NAMES.filter((name) => !taken.has(name)))
    }

    private pick<T>(items: readonly T[]): T {
        return items[Math.floor(this.random() * items.length) % items.length] as T
    }
}
