import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { Analytics } from './analytics.ts'
import { createClubHoguinServer, type StaticFile, trackDeparture } from './server.ts'
import { World } from './world.ts'

const TICK_MS = 120

async function loadStaticFiles(): Promise<Map<string, StaticFile>> {
    const webDir = fileURLToPath(new URL('../web/', import.meta.url))
    const spritesDir = join(
        dirname(fileURLToPath(import.meta.resolve('@posthog/hedgehog-mode/package.json'))),
        'assets'
    )
    const files: Array<[string, string, string, string]> = [
        ['/', join(webDir, 'index.html'), 'text/html; charset=utf-8', 'no-cache'],
        ['/client.js', join(webDir, 'client.js'), 'text/javascript; charset=utf-8', 'no-cache'],
        ['/style.css', join(webDir, 'style.css'), 'text/css; charset=utf-8', 'no-cache'],
        ['/assets/sprites.png', join(spritesDir, 'sprites.png'), 'image/png', 'public, max-age=86400'],
        ['/assets/sprites.json', join(spritesDir, 'sprites.json'), 'application/json', 'public, max-age=86400'],
    ]
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
        for (const departed of world.tick(Date.now())) {
            trackDeparture(analytics, departed)
        }
    }, TICK_MS)

    server.listen(port, host, () => {
        console.info(`club-hoguin: listening on http://${host}:${port}`)
    })
}

await main()
