import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { gzipSync } from 'node:zlib'

import type { Analytics } from './analytics.ts'
import {
    CAMPFIRE,
    DECORATIONS,
    EMOTES,
    EXPERIMENT_SIGNIFICANCE_VOTES,
    LAB_FOOTPRINT,
    LOOKS,
    OBJECTS,
    PHRASES,
    POND,
    SKINS,
    SPAWN,
    TEXT_MAP_ROWS,
    TEXT_MAP_UNITS_PER_ROW,
    WALK_BOUNDS,
    WALK_SPEED,
    WORLD_DEPTH,
    WORLD_WIDTH,
} from './content.ts'
import type { FramePainter } from './frame.ts'
import type { RateLimiter } from './rate-limiter.ts'
import {
    type ClientKind,
    type DepartedPlayer,
    isClientKind,
    isHat,
    isSkin,
    LIMITS,
    type PokeEvent,
    type World,
    type WorldEvent,
} from './world.ts'

const MAX_BODY_BYTES = 2_048
const TOKEN_HEADER = 'x-hoguin-token'

const SECURITY_HEADERS = {
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'no-referrer',
}

// frame-ancestors is open on purpose: anyone can embed the club in an iframe.
const PAGE_CSP =
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; " +
    "frame-ancestors *; base-uri 'none'; form-action 'none'"

const ERROR_STATUS: Record<string, number> = {
    unknown_player: 401,
    cooldown: 429,
    too_far: 409,
    club_full: 503,
    too_many_actions: 429,
    too_many_from_address: 429,
}

export interface StaticFile {
    body: Buffer
    // The body compressed with gzip, for the files that get smaller.
    gzipBody?: Buffer
    contentType: string
    cacheControl: string
}

export interface ServerDependencies {
    world: World
    analytics: Analytics
    staticFiles: ReadonlyMap<string, StaticFile>
    now: () => number
    trustedProxyHops: number
    rateLimiter: RateLimiter
    painter: FramePainter
    // Different on every start of the process. A client that sees it change knows the town began again.
    serverId: string
}

class HttpError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.status = status
    }
}

const MIN_GZIP_BYTES = 1_024
const STREAM_HEARTBEAT_MS = 10_000
const STREAM_RETRY_MS = 2_000

function acceptsGzip(request: IncomingMessage): boolean {
    return /\bgzip\b/.test(String(request.headers['accept-encoding'] ?? ''))
}

// Clients poll the state many times a second, and the state of a full town is tens of kilobytes of JSON.
// Level 1 is fast, and JSON with many alike rows gets small at any level.
function sendJson(request: IncomingMessage, response: ServerResponse, status: number, payload: unknown): void {
    const body = Buffer.from(JSON.stringify(payload))
    const isCompressed = body.length >= MIN_GZIP_BYTES && acceptsGzip(request)
    response.writeHead(status, {
        ...SECURITY_HEADERS,
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        vary: 'accept-encoding',
        ...(isCompressed ? { 'content-encoding': 'gzip' } : {}),
    })
    response.end(isCompressed ? gzipSync(body, { level: 1 }) : body)
}

async function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
    const chunks: Buffer[] = []
    let size = 0
    for await (const chunk of request) {
        const buffer = chunk as Buffer
        size += buffer.length
        if (size > MAX_BODY_BYTES) {
            throw new HttpError(413, 'body_too_large')
        }
        chunks.push(buffer)
    }
    if (size === 0) {
        return {}
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    } catch {
        throw new HttpError(400, 'invalid_json')
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new HttpError(400, 'invalid_json')
    }
    return parsed as Record<string, unknown>
}

function readToken(request: IncomingMessage): string | null {
    const value = request.headers[TOKEN_HEADER]
    return typeof value === 'string' && value.length > 0 ? value : null
}

// Behind a proxy, the socket address is the address of the proxy. Each trusted proxy appends the address
// it saw to x-forwarded-for, so the client address is that many entries from the end of the header.
// The client can write the entries before it, so the server does not read them.
function clientAddress(request: IncomingMessage, trustedProxyHops: number): string {
    const socketAddress = request.socket.remoteAddress ?? 'unknown'
    if (trustedProxyHops === 0) {
        return socketAddress
    }
    const header = request.headers['x-forwarded-for']
    const forwarded = (Array.isArray(header) ? header.join(',') : (header ?? ''))
        .split(',')
        .map((entry) => entry.trim())
        .filter((entry) => entry.length > 0)
    return forwarded[forwarded.length - trustedProxyHops] ?? socketAddress
}

export function trackDeparture(analytics: Analytics, departed: DepartedPlayer): void {
    analytics.capture(departed.id, 'club hoguin left', {
        client: departed.client,
        reason: departed.reason,
        duration_seconds: Math.round(departed.durationMs / 1000),
    })
}

export function trackPoke(analytics: Analytics, poked: PokeEvent): void {
    analytics.capture(poked.playerId, 'club hoguin object poked', {
        client: poked.client,
        object_id: poked.objectId,
    })
}

export function createClubHoguinServer({
    world,
    analytics,
    staticFiles,
    now,
    trustedProxyHops,
    rateLimiter,
    painter,
    serverId,
}: ServerDependencies): Server {
    const worldDescription = JSON.stringify({
        width: WORLD_WIDTH,
        depth: WORLD_DEPTH,
        walkBounds: WALK_BOUNDS,
        walkSpeed: WALK_SPEED,
        spawn: SPAWN,
        pond: POND,
        campfire: CAMPFIRE,
        decorations: DECORATIONS,
        lab: LAB_FOOTPRINT,
        objects: OBJECTS,
        phrases: PHRASES,
        emotes: EMOTES,
        skins: SKINS,
        looks: LOOKS,
        serverId,
        pokeReach: LIMITS.pokeReach,
        limits: LIMITS,
        significanceVotes: EXPERIMENT_SIGNIFICANCE_VOTES,
        textMap: { rows: TEXT_MAP_ROWS, unitsPerRow: TEXT_MAP_UNITS_PER_ROW },
    })

    function requirePlayer(request: IncomingMessage): { token: string; id: string; client: ClientKind } {
        const token = readToken(request)
        const player = token ? world.touch(token, now()) : null
        if (!token || !player) {
            throw new HttpError(401, 'unknown_player')
        }
        return { token, ...player }
    }

    function fail(error: string): never {
        throw new HttpError(ERROR_STATUS[error] ?? 400, error)
    }

    const worldDescriptionGzip = gzipSync(worldDescription)

    async function handleApi(request: IncomingMessage, response: ServerResponse, url: URL): Promise<void> {
        const pathname = url.pathname
        const method = request.method ?? 'GET'
        if (!rateLimiter.allow(clientAddress(request, trustedProxyHops), now())) {
            throw new HttpError(429, 'too_many_requests')
        }
        if (pathname === '/api/world' && method === 'GET') {
            const isCompressed = acceptsGzip(request)
            response.writeHead(200, {
                ...SECURITY_HEADERS,
                'content-type': 'application/json; charset=utf-8',
                'cache-control': 'public, max-age=300',
                vary: 'accept-encoding',
                ...(isCompressed ? { 'content-encoding': 'gzip' } : {}),
            })
            response.end(isCompressed ? worldDescriptionGzip : worldDescription)
            return
        }
        if (pathname === '/api/state' && method === 'GET') {
            const token = readToken(request)
            if (token && !world.touch(token, now())) {
                fail('unknown_player')
            }
            sendJson(request, response, 200, world.snapshot(token, now()))
            return
        }
        if (pathname === '/api/events' && method === 'GET') {
            const token = readToken(request)
            if (token && !world.touch(token, now())) {
                fail('unknown_player')
            }
            const since = Number(url.searchParams.get('since'))
            const events = Number.isFinite(since) ? world.eventsSince(since, now()) : null
            sendJson(request, response, 200, events ?? { resync: true, snapshot: world.snapshot(token, now()) })
            return
        }
        if (pathname === '/api/stream' && method === 'GET') {
            streamEvents(request, response, url)
            return
        }
        // The town as a picture, for a pane. The base64 form is for a client that can only read text.
        if ((pathname === '/api/frame.png' || pathname === '/api/frame.b64') && method === 'GET') {
            const token = readToken(request)
            const viewer = token ? world.touch(token, now()) : null
            if (token && !viewer) {
                fail('unknown_player')
            }
            const png = painter.paint(world.snapshot(null, now()), viewer?.id ?? null, now())
            const isText = pathname.endsWith('.b64')
            response.writeHead(200, {
                ...SECURITY_HEADERS,
                'content-type': isText ? 'text/plain; charset=utf-8' : 'image/png',
                'cache-control': 'no-store',
            })
            response.end(isText ? png.toString('base64') : png)
            return
        }
        if (method !== 'POST') {
            throw new HttpError(405, 'method_not_allowed')
        }
        const body = await readJson(request)
        switch (pathname) {
            case '/api/join': {
                if (!isClientKind(body.client)) {
                    fail('invalid_client')
                }
                if (body.skin !== undefined && !isSkin(body.skin)) {
                    fail('invalid_skin')
                }
                if (body.hat !== undefined && body.hat !== null && !isHat(body.hat)) {
                    fail('invalid_hat')
                }
                const joined = world.join(
                    body.client,
                    clientAddress(request, trustedProxyHops),
                    now(),
                    body.skin,
                    body.hat ?? null
                )
                if (!joined.ok) {
                    fail(joined.error)
                }
                analytics.capture(joined.player.id, 'club hoguin joined', { client: body.client })
                sendJson(request, response, 200, joined.player)
                return
            }
            case '/api/move': {
                const player = requirePlayer(request)
                // A move to an object walks to it and uses it. A move to a point only walks.
                const result =
                    body.objectId === undefined
                        ? world.moveTo(player.token, body.x, body.y, now())
                        : world.walkToUse(player.token, body.objectId, now())
                if (!result.ok) {
                    fail(result.error)
                }
                sendJson(request, response, 200, { ok: true })
                return
            }
            case '/api/look': {
                const player = requirePlayer(request)
                const result = world.changeLook(player.token, body.skin, body.hat ?? null, now())
                if (!result.ok) {
                    fail(result.error)
                }
                sendJson(request, response, 200, { ok: true })
                return
            }
            case '/api/emote': {
                const player = requirePlayer(request)
                const result = world.emote(player.token, body.emoteId, now())
                if (!result.ok) {
                    fail(result.error)
                }
                analytics.capture(player.id, 'club hoguin emote sent', {
                    client: player.client,
                    emote_id: String(body.emoteId),
                })
                sendJson(request, response, 200, { ok: true })
                return
            }
            case '/api/say': {
                const player = requirePlayer(request)
                const result = world.say(player.token, body.phraseId, now())
                if (!result.ok) {
                    fail(result.error)
                }
                analytics.capture(player.id, 'club hoguin phrase said', {
                    client: player.client,
                    phrase_id: String(body.phraseId),
                })
                sendJson(request, response, 200, { ok: true })
                return
            }
            case '/api/poke': {
                const player = requirePlayer(request)
                const result = world.poke(player.token, body.objectId, now())
                if (!result.ok) {
                    fail(result.error)
                }
                trackPoke(analytics, { playerId: player.id, client: player.client, objectId: result.objectId })
                sendJson(request, response, 200, { ok: true, objectId: result.objectId })
                return
            }
            case '/api/leave': {
                const token = readToken(request)
                const departed = token ? world.leave(token, now()) : null
                if (departed) {
                    trackDeparture(analytics, departed)
                }
                sendJson(request, response, 200, { ok: true })
                return
            }
        }
        throw new HttpError(404, 'not_found')
    }

    // Server-sent events: the client gets every event as it happens. A browser cannot set a header on the
    // stream, so the token rides in the query string. The open stream counts as the heartbeat of its player.
    function streamEvents(request: IncomingMessage, response: ServerResponse, url: URL): void {
        const token = readToken(request) ?? url.searchParams.get('token')
        if (token && !world.touch(token, now())) {
            fail('unknown_player')
        }
        response.writeHead(200, {
            ...SECURITY_HEADERS,
            'content-type': 'text/event-stream; charset=utf-8',
            'cache-control': 'no-store',
            connection: 'keep-alive',
            // Tells a reverse proxy not to hold the stream back.
            'x-accel-buffering': 'no',
        })
        const send = (name: string, data: unknown, id?: number): void => {
            response.write(`event: ${name}\n${id === undefined ? '' : `id: ${id}\n`}data: ${JSON.stringify(data)}\n\n`)
        }
        // Events that happen while the snapshot is being taken wait, so none is lost or sent twice.
        let snapshotSeq: number | null = null
        const pending: WorldEvent[] = []
        const unsubscribe = world.subscribe((event) => {
            if (snapshotSeq === null) {
                pending.push(event)
            } else if (event.seq > snapshotSeq) {
                send('event', event, event.seq)
            }
        })
        const since = Number(url.searchParams.get('since') ?? request.headers['last-event-id'])
        const backlog = Number.isFinite(since) ? world.eventsSince(since, now()) : null
        if (backlog) {
            backlog.events.forEach((event) => send('event', event, event.seq))
            send('sync', { seq: backlog.seq, at: backlog.at }, backlog.seq)
            snapshotSeq = backlog.seq
        } else {
            const snapshot = world.snapshot(token, now())
            send('snapshot', snapshot, snapshot.seq)
            snapshotSeq = snapshot.seq
        }
        const settled = snapshotSeq
        pending.filter((event) => event.seq > settled).forEach((event) => send('event', event, event.seq))
        response.write(`retry: ${STREAM_RETRY_MS}\n\n`)
        const heartbeat = setInterval(() => {
            if (token && !world.touch(token, now())) {
                response.end()
                return
            }
            send('sync', { seq: world.snapshot(null, now()).seq, at: now() })
        }, STREAM_HEARTBEAT_MS)
        request.on('close', () => {
            unsubscribe()
            clearInterval(heartbeat)
        })
    }

    function handleStatic(request: IncomingMessage, response: ServerResponse, pathname: string): void {
        const file = request.method === 'GET' || request.method === 'HEAD' ? staticFiles.get(pathname) : undefined
        if (!file) {
            throw new HttpError(404, 'not_found')
        }
        const isCompressed = file.gzipBody !== undefined && acceptsGzip(request)
        const headers: Record<string, string> = {
            ...SECURITY_HEADERS,
            'content-type': file.contentType,
            'cache-control': file.cacheControl,
            vary: 'accept-encoding',
        }
        if (isCompressed) {
            headers['content-encoding'] = 'gzip'
        }
        if (file.contentType.startsWith('text/html')) {
            headers['content-security-policy'] = PAGE_CSP
        }
        response.writeHead(200, headers)
        response.end(request.method === 'HEAD' ? undefined : isCompressed ? file.gzipBody : file.body)
    }

    return createServer((request, response) => {
        const url = new URL(request.url ?? '/', 'http://club-hoguin.invalid')
        const pathname = url.pathname
        const handle = async (): Promise<void> => {
            if (pathname === '/healthz') {
                sendJson(request, response, 200, { ok: true })
            } else if (pathname.startsWith('/api/')) {
                await handleApi(request, response, url)
            } else {
                handleStatic(request, response, pathname)
            }
        }
        handle().catch((error: unknown) => {
            if (response.headersSent) {
                response.destroy()
                return
            }
            if (error instanceof HttpError) {
                sendJson(request, response, error.status, { error: error.message })
                return
            }
            console.error('club-hoguin: request failed', error)
            sendJson(request, response, 500, { error: 'internal_error' })
        })
    })
}
