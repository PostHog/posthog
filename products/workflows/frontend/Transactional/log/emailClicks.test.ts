import type {
    TransactionalEmailClickSessionApi,
    TransactionalEmailLogDetailApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { emailOutcomeRows, emailWentOut, landingPath, linkLabel, sessionSummary } from './emailClicks'

const SESSION: TransactionalEmailClickSessionApi = {
    session_id: 'session-1',
    landed_at: '2026-06-15T09:05:10Z',
    landing_url: 'https://app.example.com/billing?tab=plans&ph_workflow_run=msg-1',
    duration_seconds: 250,
    pageview_count: 3,
    device_type: 'Desktop',
    browser: 'Chrome',
    city: null,
}

describe('emailClicks', () => {
    it('lists delivery and the first open with their events, then each click', () => {
        const email = {
            timeline: [
                { kind: 'sent', at: '2026-06-15T09:00:00Z', reason: null },
                { kind: 'delivered', at: '2026-06-15T09:00:02Z', reason: null },
                { kind: 'opened', at: '2026-06-15T09:01:00Z', reason: null },
                { kind: 'opened', at: '2026-06-15T09:02:00Z', reason: null },
                { kind: 'clicked', at: '2026-06-15T09:05:00Z', reason: null },
            ],
        } as TransactionalEmailLogDetailApi
        const click = {
            at: '2026-06-15T09:05:00Z',
            link_url: 'https://app.example.com/billing',
            event_uuid: 'click-event',
            session: SESSION,
            no_session_reason: null,
        }

        const rows = emailOutcomeRows(
            email,
            [click],
            [{ uuid: 'opened-event', event: '$workflows_email_opened', timestamp: '2026-06-15T09:01:00Z' }]
        )

        expect(rows.map((row) => [row.kind, row.at, row.eventUuid])).toEqual([
            ['delivered', '2026-06-15T09:00:02Z', null],
            ['opened', '2026-06-15T09:01:00Z', 'opened-event'],
            ['click', '2026-06-15T09:05:00Z', 'click-event'],
        ])
        expect(rows[2]).toMatchObject({ link: click.link_url, session: SESSION })
    })

    it('puts each step in time order and links only the event at its time', () => {
        const email = {
            timeline: [
                { kind: 'delivered', at: '2026-06-15T09:00:02Z', reason: null },
                { kind: 'clicked', at: '2026-06-15T09:05:00Z', reason: null },
                { kind: 'opened', at: '2026-06-15T09:30:00Z', reason: null },
            ],
        } satisfies Pick<TransactionalEmailLogDetailApi, 'timeline'>
        const click = {
            at: '2026-06-15T09:05:00Z',
            link_url: null,
            event_uuid: null,
            session: null,
            no_session_reason: 'link_unknown' as const,
        }

        const rows = emailOutcomeRows(
            email,
            [click],
            [
                { uuid: 'delivered-event', event: '$workflows_email_delivered', timestamp: '2026-06-15T09:00:02.000Z' },
                { uuid: 'later-open', event: '$workflows_email_opened', timestamp: '2026-06-15T09:40:00Z' },
            ]
        )

        expect(rows.map((row) => [row.kind, row.eventUuid])).toEqual([
            ['delivered', 'delivered-event'],
            ['click', null],
            ['opened', null],
        ])
    })

    it.each([
        ['went out without a stored copy', ['queued', 'sent', 'clicked'] as const, true],
        ['failed before it went out', ['queued', 'failed'] as const, false],
    ])('shows what a send led to when it %s', (_name, kinds, shown) => {
        const timeline = kinds.map((kind) => ({ kind, at: '2026-06-15T09:00:00Z', reason: null }))

        expect(emailWentOut({ timeline })).toBe(shown)
    })

    it.each([
        ['https://app.example.com/billing?tab=plans', 'app.example.com/billing?tab=plans'],
        ['https://app.example.com', 'app.example.com'],
        ['https://app.example.com/#/settings', 'app.example.com/#/settings'],
        ['not a url', 'not a url'],
    ])('labels the link %s as %s', (link, label) => {
        expect(linkLabel(link)).toBe(label)
    })

    it.each([
        [SESSION.landing_url, '/billing?tab=plans'],
        ['https://app.example.com/?ph_workflow_run=msg-1#/billing', '/#/billing'],
    ])('shows the landing page %s without the run tag as %s', (landingUrl, path) => {
        expect(landingPath({ ...SESSION, landing_url: landingUrl })).toBe(path)
    })

    it.each([
        ['with its totals', SESSION, 'Desktop · Chrome · 4m 10s · 3 pages'],
        [
            'before its totals are ready',
            { ...SESSION, duration_seconds: null, pageview_count: null },
            'Desktop · Chrome',
        ],
    ])('sums up a session %s', (_name, session, summary) => {
        expect(sessionSummary(session).replace(/\s/g, ' ')).toBe(summary)
    })
})
