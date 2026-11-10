import type { LiveQueryKey } from '@/api/live'

// Live demo traffic for hedgebox.net, a fictional file-sharing site. Every id, path and number is invented. A seeded
// generator writes events up to the moment of each read, and each read answers in the shape of its live query, so demo
// mode runs the same adapters as a project. Without reads, nothing moves: Pause stops the demo, and the next read
// catches up on the gap, as a live read does.

const SECOND = 1000
const MINUTE = 60 * SECOND
const WINDOW_MINUTES = 30
const MAX_DEPARTED_VISITORS = 100
/** A demo read takes this long, so the first load shows the skeleton. */
export const LIVE_DEMO_READ_MS = 350

type Weights = Record<string, number>

const PAGE_WEIGHTS: Weights = {
    '/': 118,
    '/pricing': 74,
    '/blog/what-is-a-hedgebox': 61,
    '/docs/sharing': 47,
    '/signup': 38,
    '/login': 35,
    '/features': 31,
    '/changelog': 18,
    '/blog/launch-week': 16,
    '/about': 11,
    '/files': 9,
    '/docs/getting-started': 6,
    '/account': 4,
}
const REFERRER_WEIGHTS: Weights = {
    'google.com': 168,
    $direct: 131,
    'news.ycombinator.com': 72,
    'twitter.com': 36,
    'github.com': 31,
    'bing.com': 16,
    'reddit.com': 14,
    'duckduckgo.com': 9,
}
const DEVICE_WEIGHTS: Weights = { Mobile: 58, Desktop: 39, Tablet: 3 }
const BROWSER_WEIGHTS: Record<string, Weights> = {
    Desktop: { Chrome: 55, Safari: 14, Firefox: 13, 'Microsoft Edge': 10, Brave: 5, Opera: 3 },
    Mobile: { 'Mobile Safari': 48, 'Chrome Mobile': 38, 'Samsung Internet': 7, 'Firefox Mobile': 3 },
    Tablet: { 'Mobile Safari': 70, 'Chrome Mobile': 30 },
}
const COUNTRY_WEIGHTS: Weights = { US: 38, GB: 14, DE: 11, CA: 8, BR: 7, IN: 6, FR: 5, NL: 4, AU: 4, ES: 3 }
const EVENT_WEIGHTS: Weights = {
    $pageview: 66,
    $screen: 11,
    file_uploaded: 9,
    share_link_created: 7,
    file_downloaded: 5,
    folder_created: 2,
}
const SCREENS = ['File browser', 'Upload', 'Share sheet', 'Folder detail', 'Settings']
const EVENT_PATHS: Record<string, string> = {
    file_uploaded: '/files',
    share_link_created: '/files/shared',
    file_downloaded: '/s/k2xq9',
    folder_created: '/files',
}

interface DemoPerson {
    distinctId: string
    deviceId: string
    device: string
    browser: string
    country: string
    referrer: string
    sessionId: string | null
}

interface DemoEvent {
    uuid: string
    event: string
    person: DemoPerson
    at: number
    path: string | null
    screen: string | null
    url: string | null
}

function domainOf(path: string): string {
    if (path.startsWith('/docs')) {
        return 'docs.hedgebox.net'
    }
    return /^\/(login|signup|files|account|s\/)/.test(path) ? 'app.hedgebox.net' : 'hedgebox.net'
}

function minuteIso(at: number): string {
    return new Date(Math.floor(at / MINUTE) * MINUTE).toISOString()
}

export class LiveDemo {
    private seed: number
    private events: DemoEvent[] = []
    private active: DemoPerson[] = []
    private left: DemoPerson[] = []
    private pages: Weights = { ...PAGE_WEIGHTS }
    private nextAt: number
    private driftMinute: number

    constructor(seed: number, start: number) {
        this.seed = seed
        this.nextAt = start - WINDOW_MINUTES * MINUTE
        this.driftMinute = Math.floor(this.nextAt / MINUTE)
        for (let index = 0; index < 12; index++) {
            this.active.push(this.newPerson())
        }
        this.advance(start)
    }

    respond(key: LiveQueryKey, now: number): unknown {
        this.advance(now)
        const from = Math.floor(now / MINUTE) * MINUTE - (WINDOW_MINUTES - 1) * MINUTE
        const inWindow = this.events.filter((event) => event.at >= from && event.at <= now)
        const pageviews = inWindow.filter((event) => event.event === '$pageview')
        switch (key) {
            case 'usersPageviews':
                return { results: this.activityRows(inWindow) }
            case 'device':
                return this.breakdown(
                    inWindow,
                    (p) => p.device,
                    (p) => p.deviceId
                )
            case 'browser':
                return this.breakdown(
                    inWindow,
                    (p) => p.browser,
                    (p) => p.deviceId
                )
            case 'geo':
                return this.breakdown(
                    inWindow,
                    (p) => p.country,
                    (p) => p.distinctId
                )
            case 'referrer': {
                const rows: unknown[][] = []
                for (const [minute, events] of this.groupByMinute(pageviews)) {
                    const counts = new Map<string, number>()
                    for (const event of events) {
                        counts.set(event.person.referrer, (counts.get(event.person.referrer) ?? 0) + 1)
                    }
                    for (const [domain, count] of counts) {
                        rows.push([minute, domain, count])
                    }
                }
                return { results: rows }
            }
            case 'paths': {
                const minutes = Array.from({ length: WINDOW_MINUTES }, (_, index) => from + index * MINUTE)
                const perPath = new Map<string, number[]>()
                for (const event of pageviews) {
                    const data = perPath.get(event.path ?? '') ?? Array<number>(WINDOW_MINUTES).fill(0)
                    const index = Math.floor((event.at - from) / MINUTE)
                    data[index] = (data[index] ?? 0) + 1
                    perPath.set(event.path ?? '', data)
                }
                const total = (data: number[]): number => data.reduce((sum, value) => sum + value, 0)
                return {
                    results: [...perPath.entries()]
                        .sort(([, a], [, b]) => total(b) - total(a))
                        .slice(0, 10)
                        .map(([path, data]) => ({
                            breakdown_value: path,
                            data,
                            days: minutes.map((at) => new Date(at).toISOString()),
                        })),
                }
            }
            case 'recentEvents':
                return {
                    results: inWindow
                        .slice(-50)
                        .reverse()
                        .map((event) => [
                            event.uuid,
                            event.event,
                            event.person.distinctId,
                            event.at,
                            event.url,
                            event.screen,
                            event.path,
                            event.person.sessionId,
                        ]),
                }
            case 'usersOnline': {
                const recent = this.events.filter((event) => event.at > now - MINUTE && event.at <= now)
                return { results: [[new Set(recent.map((event) => event.person.distinctId)).size]] }
            }
        }
    }

    private groupByMinute(events: DemoEvent[]): Map<string, DemoEvent[]> {
        const groups = new Map<string, DemoEvent[]>()
        for (const event of events) {
            const minute = minuteIso(event.at)
            const group = groups.get(minute) ?? []
            group.push(event)
            groups.set(minute, group)
        }
        return groups
    }

    private activityRows(events: DemoEvent[]): number[][] {
        const seen = new Set<string>()
        return [...this.groupByMinute(events)].map(([minute, group]) => {
            const ids = new Set(group.map((event) => event.person.distinctId))
            const before = seen.size
            for (const id of ids) {
                seen.add(id)
            }
            return [
                Date.parse(minute),
                ids.size,
                seen.size - before,
                group.filter((event) => event.event === '$pageview').length,
            ]
        })
    }

    private breakdown(
        events: DemoEvent[],
        labelOf: (person: DemoPerson) => string,
        idOf: (person: DemoPerson) => string
    ): { results: [string, number][][][] } {
        const ids = new Map<string, Set<string>>()
        for (const { person } of events) {
            const label = labelOf(person)
            const group = ids.get(label) ?? new Set<string>()
            group.add(idOf(person))
            ids.set(label, group)
        }
        return { results: [[Array.from(ids, ([label, group]) => [label, group.size])]] }
    }

    /** Writes the events up to `now`. After a long pause it starts at the window, so a resume never replays hours. */
    private advance(now: number): void {
        this.nextAt = Math.max(this.nextAt, now - (WINDOW_MINUTES + 1) * MINUTE)
        while (this.nextAt <= now) {
            const minute = Math.floor(this.nextAt / MINUTE)
            while (this.driftMinute < minute) {
                this.driftMinute += 1
                this.drift()
            }
            this.events.push(this.makeEvent(this.nextAt))
            this.nextAt += 1200 + this.random() * 2400
        }
        const oldest = now - (WINDOW_MINUTES + 1) * MINUTE
        const firstKept = this.events.findIndex((event) => event.at >= oldest)
        this.events = firstKept < 0 ? [] : this.events.slice(firstKept)
    }

    /** Page weights wander toward their base, so ranks swap now and then. */
    private drift(): void {
        for (const [path, base] of Object.entries(PAGE_WEIGHTS)) {
            const current = this.pages[path] ?? base
            const step = (this.random() - 0.5) * 2 * Math.max(2.5, base * 0.12)
            this.pages[path] = Math.max(1, current + (base - current) * 0.15 + step)
        }
    }

    private makeEvent(at: number): DemoEvent {
        // About one visitor in nine leaves per event; most newcomers are new, some come back within the window.
        if (this.random() < 0.11) {
            const [gone] = this.active.splice(Math.floor(this.random() * this.active.length), 1)
            if (gone) {
                if (this.left.length === MAX_DEPARTED_VISITORS) {
                    this.left.shift()
                }
                this.left.push(gone)
            }
            const back = this.left.length > 0 && this.random() < 0.25
            this.active.push(
                back
                    ? (this.left.splice(Math.floor(this.random() * this.left.length), 1)[0] as DemoPerson)
                    : this.newPerson()
            )
        }
        const person = this.active[Math.floor(this.random() * this.active.length)] as DemoPerson
        let event = this.weighted(EVENT_WEIGHTS)
        if (event === '$screen' && person.device === 'Desktop') {
            event = '$pageview'
        }
        const path =
            event === '$pageview'
                ? this.weighted(this.pages)
                : event === '$screen'
                  ? null
                  : (EVENT_PATHS[event] ?? null)
        return {
            uuid: this.uuid(),
            event,
            person,
            at,
            path,
            screen: event === '$screen' ? this.pick(SCREENS) : null,
            url: path ? `https://${domainOf(path)}${path}` : null,
        }
    }

    private newPerson(): DemoPerson {
        const device = this.weighted(DEVICE_WEIGHTS)
        return {
            distinctId: this.uuid(),
            deviceId: this.uuid(),
            device,
            browser: this.weighted(BROWSER_WEIGHTS[device] ?? BROWSER_WEIGHTS.Desktop ?? {}),
            country: this.weighted(COUNTRY_WEIGHTS),
            referrer: this.weighted(REFERRER_WEIGHTS),
            sessionId: this.random() < 0.82 ? this.uuid() : null,
        }
    }

    /** Mulberry32: small, fast and the same sequence for the same seed. */
    private random(): number {
        this.seed = (this.seed + 0x6d2b79f5) | 0
        let t = Math.imul(this.seed ^ (this.seed >>> 15), 1 | this.seed)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }

    private pick<T>(list: readonly T[]): T {
        return list[Math.floor(this.random() * list.length)] as T
    }

    private weighted(weights: Weights): string {
        const entries = Object.entries(weights)
        let remaining = this.random() * entries.reduce((sum, [, weight]) => sum + weight, 0)
        for (const [key, weight] of entries) {
            remaining -= weight
            if (remaining < 0) {
                return key
            }
        }
        return entries[entries.length - 1]?.[0] ?? ''
    }

    private hex(length: number): string {
        let text = ''
        for (let index = 0; index < length; index++) {
            text += '0123456789abcdef'[Math.floor(this.random() * 16)]
        }
        return text
    }

    private uuid(): string {
        return `0192${this.hex(4)}-${this.hex(4)}-7${this.hex(3)}-${this.pick(['8', '9', 'a', 'b'])}${this.hex(3)}-${this.hex(12)}`
    }
}

const DEMO_SEED = 1105
let shared: LiveDemo | null = null

/** One simulator for the app session, so leaving and reopening Live continues the same traffic. */
export function liveDemo(now: number = Date.now()): LiveDemo {
    shared ??= new LiveDemo(DEMO_SEED, now)
    return shared
}
