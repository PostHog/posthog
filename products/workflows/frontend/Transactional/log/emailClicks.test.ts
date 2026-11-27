import type {
    TransactionalEmailClickSessionApi,
    TransactionalEmailLogDetailApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { emailOutcomeRows, landingPath, linkLabel, sessionSummary } from './emailClicks'

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

    it.each([
        ['https://app.example.com/billing?tab=plans', 'app.example.com/billing?tab=plans'],
        ['https://app.example.com', 'app.example.com'],
        ['not a url', 'not a url'],
    ])('labels the link %s as %s', (link, label) => {
        expect(linkLabel(link)).toBe(label)
    })

    it('shows the landing page without the run tag', () => {
        expect(landingPath(SESSION)).toBe('/billing?tab=plans')
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
