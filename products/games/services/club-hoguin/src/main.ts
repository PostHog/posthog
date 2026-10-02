import { randomUUID } from 'node:crypto'
import { readdir, readFile } from 'node:fs/promises'
import { dirname, extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { Analytics } from './analytics.ts'
import { createClubHoguinServer, type StaticFile, trackDeparture, trackPoke } from './server.ts'
import { World } from './world.ts'

const TICK_MS = 50

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
            const file: StaticFile = { body: await readFile(path), contentType, cacheControl }
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
        process.env.POSTHOG_PROJECT_API_KEY || undefined,
        process.env.POSTHOG_HOST ?? 'https://us.i.posthog.com'
    )
    const world = new World({ makeId: randomUUID, random: Math.random })
    const server = createClubHoguinServer({
        world,
        analytics,
        staticFiles: await loadStaticFiles(),
        now: Date.now,
        trustedProxyHops,
    })

    setInterval(() => {
        const { departed, poked } = world.tick(Date.now())
        departed.forEach((player) => trackDeparture(analytics, player))
        poked.forEach((event) => trackPoke(analytics, event))
    }, TICK_MS)

    server.listen(port, host, () => {
        console.info(`club-hoguin: listening on http://${host}:${port}`)
    })
}

await main()
