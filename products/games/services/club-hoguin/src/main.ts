import { randomUUID } from 'node:crypto'
import { readdir, readFile } from 'node:fs/promises'
import { dirname, extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

import { Analytics } from './analytics.ts'
import { Bots } from './bots.ts'
import { FramePainter } from './frame.ts'
import { decodePng } from './png.ts'
import { RateLimiter } from './rate-limiter.ts'
import { createClubHoguinServer, type StaticFile, trackDeparture, trackPoke } from './server.ts'
import { World } from './world.ts'

const TICK_MS = 50
const PRUNE_MS = 30_000
// A web client polls up to 10 times a second, and one address can hold 10 hedgehogs.
const REQUESTS_PER_SECOND_PER_ADDRESS = 300
const SHUTDOWN_GRACE_MS = 3_000

const CONTENT_TYPES: Record<string, string> = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.json': 'application/json',
}

async function loadStaticFiles(): Promise<Map<string, StaticFile>> {
    const webDir = fileURLToPath(new URL('../web/', import.meta.url))
    const spritesDir = join(
        dirname(fileURLToPath(import.meta.resolve('@posthog/hedgehog-mode/package.json'))),
        'assets'
    )
    const threeDir = dirname(fileURLToPath(import.meta.resolve('three')))
    const files: Array<[string, string, string, string]> = [
        ['/assets/sprites.png', join(spritesDir, 'sprites.png'), 'image/png', 'public, max-age=86400'],
        ['/assets/sprites.json', join(spritesDir, 'sprites.json'), 'application/json', 'public, max-age=86400'],
        // three.module.min.js imports three.core.min.js from its own folder, so the two files keep their names.
        ...['three.module.min.js', 'three.core.min.js'].map((name): [string, string, string, string] => [
            `/vendor/three/${name}`,
            join(threeDir, name),
            'text/javascript; charset=utf-8',
            'public, max-age=86400',
        ]),
    ]
    for (const name of await readdir(webDir)) {
        const contentType = CONTENT_TYPES[extname(name)]
        if (contentType) {
            files.push([name === 'index.html' ? '/' : `/${name}`, join(webDir, name), contentType, 'no-cache'])
        }
    }
    const loaded = await Promise.all(
        files.map(async ([route, path, contentType, cacheControl]) => {
            const body = await readFile(path)
            const file: StaticFile = { body, contentType, cacheControl }
            // A PNG is compressed already. Text gets a lot smaller.
            if (contentType !== 'image/png') {
                file.gzipBody = gzipSync(body)
            }
            return [route, file] as const
        })
    )
    return new Map(loaded)
}

async function main(): Promise<void> {
    const port = Number(process.env.PORT ?? 8642)
    const host = process.env.HOST ?? '0.0.0.0'
    const trustedProxyHops = Number(process.env.TRUSTED_PROXY_HOPS ?? 0)
    if (!Number.isInteger(trustedProxyHops) || trustedProxyHops < 0) {
        throw new Error('TRUSTED_PROXY_HOPS must be a whole number, 0 or more')
    }
    const analytics = new Analytics(
        process.env.CLUB_HOGUIN_POSTHOG_API_KEY || undefined,
        process.env.CLUB_HOGUIN_POSTHOG_HOST ?? 'https://us.i.posthog.com'
    )
    const serverId = randomUUID()
    const world = new World({ makeId: randomUUID, random: Math.random, serverId })
    const rateLimiter = new RateLimiter(REQUESTS_PER_SECOND_PER_ADDRESS, REQUESTS_PER_SECOND_PER_ADDRESS * 2)
    const staticFiles = await loadStaticFiles()
    const painter = new FramePainter({
        image: decodePng(staticFiles.get('/assets/sprites.png')!.body),
        frames: JSON.parse(staticFiles.get('/assets/sprites.json')!.body.toString('utf8')).frames,
    })
    const server = createClubHoguinServer({
        world,
        analytics,
        staticFiles,
        now: Date.now,
        trustedProxyHops,
        rateLimiter,
        painter,
        serverId,
    })

    const botCount = Number(process.env.CLUB_HOGUIN_BOTS ?? 0)
    const bots = botCount > 0 ? new Bots(world, botCount, Math.random) : null

    setInterval(() => {
        bots?.tick(Date.now())
        const { departed, poked } = world.tick(Date.now())
        departed.forEach((player) => trackDeparture(analytics, player))
        poked.forEach((event) => trackPoke(analytics, event))
    }, TICK_MS)
    setInterval(() => rateLimiter.prune(Date.now()), PRUNE_MS)

    // A container stops the server with SIGTERM. Node does not exit on SIGTERM by itself when it is process 1.
    for (const signal of ['SIGTERM', 'SIGINT'] as const) {
        process.on(signal, () => {
            console.info(`club-hoguin: ${signal}, shutting down`)
            server.close(() => process.exit(0))
            server.closeIdleConnections()
            setTimeout(() => process.exit(0), SHUTDOWN_GRACE_MS).unref()
        })
    }

    server.listen(port, host, () => {
        console.info(`club-hoguin: listening on http://${host}:${port}`)
    })
}

await main()
