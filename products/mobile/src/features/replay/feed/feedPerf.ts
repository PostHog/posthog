import { router } from 'expo-router'

import { setFeatureFlags } from '@/lib/featureFlags'

/**
 * Timing marks for the feed, off unless the bundle is built with `EXPO_PUBLIC_REPLAY_FEED_PERF=1`. A measuring build
 * reads them through the Hermes inspector from `globalThis.__replayFeedPerf`. The same switch turns on the feed's
 * debug hooks, so a production-mode bundle (`expo start --no-dev --minify`) can be driven and measured.
 */
export const FEED_PERF = process.env.EXPO_PUBLIC_REPLAY_FEED_PERF === '1'
export const FEED_DEBUG = __DEV__ || FEED_PERF

export interface FeedPerfMark {
    name: string
    /** `Date.now()` on the thread that saw it, so marks from the UI thread and the JS thread compare. */
    at: number
    detail?: Record<string, number | string>
}

const marks: FeedPerfMark[] = []
const LIMIT = 2000

export function perfMark(name: string, at: number = Date.now(), detail?: Record<string, number | string>): void {
    if (!FEED_PERF) {
        return
    }
    marks.push({ name, at, detail })
    if (marks.length > LIMIT) {
        marks.shift()
    }
}

if (FEED_PERF) {
    ;(globalThis as { __replayFeedPerf?: unknown }).__replayFeedPerf = {
        marks,
        clear: () => {
            marks.length = 0
        },
        // A minified bundle has no module names, and its flags come only from the server, so the harness turns the
        // feed on and opens it through these.
        flags: (flags: Record<string, boolean>) => setFeatureFlags(flags),
        open: (href: string) => router.push(href as never),
    }
    // A stalled JS thread delays this interval; each stall over 40 ms is a mark with its length.
    let last = Date.now()
    setInterval(() => {
        const now = Date.now()
        if (now - last > 40) {
            perfMark('jsStall', now, { ms: now - last })
        }
        last = now
    }, 16)
}
