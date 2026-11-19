import type { SnapshotBlock } from '@/api/snapshots'
import type { FeedItem, FeedSource, FeedTimeline } from '@/features/replay/feed/feedModel'
import type { SessionSignals } from '@/features/replay/feed/sessionRows'

interface DemoReplay {
    id: string
    source: Exclude<FeedSource, 'newest'>
    path: string
    title: string
    reason: string
    person: string
    page: string
    button: string
    result: string
}

const RECORDINGS: DemoReplay[] = [
    {
        id: 'demo-replay-invite',
        source: 'highlights',
        path: '/workspace/members',
        title: 'Invited a teammate',
        reason: 'Completed the first teammate invite',
        person: 'Avery',
        page: 'Workspace members',
        button: 'Send invite',
        result: 'Invite sent to blake@example.com',
    },
    {
        id: 'demo-replay-checkout',
        source: 'rage',
        path: '/checkout',
        title: 'Got stuck applying a discount',
        reason: 'Clicked the discount button repeatedly',
        person: 'Blake',
        page: 'Order summary',
        button: 'Apply discount',
        result: 'The discount could not be applied',
    },
    {
        id: 'demo-replay-export',
        source: 'errors',
        path: '/reports/weekly',
        title: 'Export failed on the weekly report',
        reason: 'Hit an error while downloading a report',
        person: 'Casey',
        page: 'Weekly report',
        button: 'Export report',
        result: 'The report export failed. Try again.',
    },
]

const VIEWPORT = { width: 390, height: 640 }
const DURATION = 24
const ACTION_AT = 7

export function demoReplayItems(source: FeedSource, anchor: number): FeedItem[] {
    return RECORDINGS.flatMap((replay, index): FeedItem[] => {
        if (source !== 'newest' && source !== replay.source) {
            return []
        }
        const start = anchor - (index + 1) * 60 * 60 * 1000
        const startedAt = new Date(start).toISOString()
        return [
            {
                recording: {
                    sessionId: replay.id,
                    personLabel: replay.person,
                    countryCode: null,
                    startedAt,
                    endedAt: new Date(start + DURATION * 1000).toISOString(),
                    durationSeconds: DURATION,
                    clickCount: replay.source === 'rage' ? 3 : 1,
                    consoleErrorCount: replay.source === 'errors' ? 1 : 0,
                    startPath: replay.path,
                    ongoing: false,
                    activityScore: null,
                },
                summary: {
                    observationId: replay.id,
                    title: replay.title,
                    text: replay.reason,
                    chapters: [],
                    keyMomentMs: ACTION_AT * 1000,
                    notability: null,
                    notabilityReason: replay.reason,
                    hasThumbnail: false,
                    scannedAt: null,
                },
                exports: [],
                readyAtLoad: true,
            },
        ]
    })
}

export function demoReplayTimeline(sessionId: string): FeedTimeline | undefined {
    const replay = RECORDINGS.find(({ id }) => id === sessionId)
    if (!replay) {
        return undefined
    }
    return {
        viewport: VIEWPORT,
        browser: 'Chrome',
        os: 'Android',
        events: [
            { key: 'opened', kind: 'pageview', seconds: 0, label: replay.path, target: null },
            { key: 'clicked', kind: 'click', seconds: ACTION_AT, label: replay.button, target: replay.button },
            ...(replay.source === 'rage'
                ? [
                      {
                          key: 'rage',
                          kind: 'rageclick' as const,
                          seconds: ACTION_AT + 1,
                          label: replay.button,
                          target: replay.button,
                      },
                  ]
                : []),
            ...(replay.source === 'errors'
                ? [
                      {
                          key: 'exception',
                          kind: 'exception' as const,
                          seconds: ACTION_AT + 1,
                          label: replay.result,
                          target: null,
                      },
                  ]
                : []),
        ],
    }
}

export function demoReplaySignals(sessionId: string): SessionSignals {
    const replay = RECORDINGS.find(({ id }) => id === sessionId)
    return {
        rage: replay?.source === 'rage' ? [{ seconds: ACTION_AT + 1, target: replay.button }] : [],
        errors: replay?.source === 'errors' ? [{ seconds: ACTION_AT + 1, type: null, value: replay.result }] : [],
    }
}

export interface DemoReplaySnapshots {
    block: SnapshotBlock
    text: string
}

function element(id: number, tagName: string, children: object[], style?: string): object {
    return { type: 2, id, tagName, childNodes: children, attributes: style ? { style } : {} }
}

function textNode(id: number, textContent: string): object {
    return { type: 3, id, textContent }
}

/** Invented rrweb snapshots for the same WebView player used by signed-in recordings. */
export function demoReplaySnapshots(sessionId: string, startTs: number): DemoReplaySnapshots | undefined {
    const replay = RECORDINGS.find(({ id }) => id === sessionId)
    if (!replay) {
        return undefined
    }
    const statusId = 12
    const buttonId = 9
    const page = element(2, 'html', [
        element(3, 'head', []),
        element(
            4,
            'body',
            [
                element(5, 'p', [textNode(6, 'PINE WORKSPACE')], 'font-weight:700;letter-spacing:2px;color:#345745'),
                element(7, 'h1', [textNode(8, replay.page)], 'margin:20px 0 18px;font-size:32px;line-height:1.1'),
                element(
                    buttonId,
                    'button',
                    [textNode(10, replay.button)],
                    'background:#214d38;color:white;border:0;border-radius:8px;padding:12px 18px;font:inherit'
                ),
                element(11, 'p', [textNode(statusId, 'Ready')], 'color:#345745;margin-top:20px'),
            ],
            'margin:0;padding:88px 28px;background:#f1f5ef;color:#172822;font:16px system-ui,sans-serif'
        ),
    ])
    const click = { source: 2, type: 2, id: buttonId, x: 84, y: 215 }
    const events = [
        { type: 4, timestamp: startTs, data: { href: `https://example.com${replay.path}`, ...VIEWPORT } },
        {
            type: 2,
            timestamp: startTs + 1,
            data: { node: { type: 0, id: 1, childNodes: [page] }, initialOffset: { left: 0, top: 0 } },
        },
        { type: 3, timestamp: startTs + ACTION_AT * 1000, data: click },
        ...(replay.source === 'rage'
            ? [300, 600].map((offset) => ({ type: 3, timestamp: startTs + ACTION_AT * 1000 + offset, data: click }))
            : []),
        {
            type: 3,
            timestamp: startTs + (ACTION_AT + 1) * 1000,
            data: { source: 0, texts: [{ id: statusId, value: replay.result }], attributes: [], removes: [], adds: [] },
        },
        { type: 3, timestamp: startTs + DURATION * 1000, data: { source: 3, id: 1, x: 0, y: 0 } },
    ]
    return {
        block: { index: 0, startTs, endTs: startTs + DURATION * 1000 },
        text: events.map((event) => JSON.stringify(['demo', event])).join('\n'),
    }
}
