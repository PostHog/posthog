import { ActivityEvent, ActivityRow, buildActivityTimeline, describeComeback, emailSentAt } from './emailActivity'

function event(uuid: string, timestamp: string, sessionId: string | null, name = '$pageview'): ActivityEvent {
    return {
        uuid,
        event: name,
        timestamp,
        url: null,
        pathname: '/files',
        sessionId,
        eventType: null,
        elementsChain: '',
    }
}

describe('emailActivity', () => {
    it('splits at the send, folds repeats, and keeps other emails in order', () => {
        const timeline = buildActivityTimeline(
            [
                event('before', '2026-06-15T08:59:00Z', 's1'),
                event('after-1', '2026-06-15T09:03:00Z', 's2'),
                { ...event('after-2', '2026-06-15T09:04:00Z', 's2'), pathname: '/pricing' },
                { ...event('after-3', '2026-06-15T09:04:10Z', 's2'), pathname: '/pricing' },
            ],
            [
                {
                    message_id: 'receipt',
                    created_at: '2026-06-15T09:05:00Z',
                    status: 'delivered',
                    status_at: '2026-06-15T09:05:01Z',
                    reason: null,
                    recipient: 'maya@example.com',
                    workflow_id: 'workflow',
                    template_id: 'template',
                    template_name: 'Payment receipt',
                    sending_domain: 'example.com',
                    opened: false,
                    clicked: false,
                },
            ],
            '2026-06-15T09:00:00Z'
        )

        const shape = (rows: ActivityRow[]): string[] =>
            rows.map((row) => (row.kind === 'event' ? `event(${row.count})` : row.kind))
        expect(shape(timeline.before)).toEqual(['event(1)'])
        expect(shape(timeline.after)).toEqual(['event(1)', 'event(2)', 'otherEmail'])
    })

    it('does not count a server-side event as the person coming back', () => {
        const clicked = { kind: 'clicked' as const, at: '2026-06-15T09:02:00Z', reason: null }

        expect(describeComeback([event('server', '2026-06-15T09:03:00Z', null, 'invoice_paid')], [clicked])).toBeNull()
        expect(describeComeback([event('page', '2026-06-15T09:03:00Z', null)], [clicked])).toBe(
            'Back in your app 1m after clicking the email'
        )
    })

    it('keeps a return to the app that came before a later open of the email', () => {
        const comeback = describeComeback(
            [event('return', '2026-06-15T09:03:00Z', 's1')],
            [
                { kind: 'clicked', at: '2026-06-15T09:02:00Z', reason: null },
                { kind: 'opened', at: '2026-06-15T10:00:00Z', reason: null },
            ]
        )

        expect(comeback).toBe('Back in your app 1m after clicking the email')
    })

    it('splits the activity at the send, or at the queue time when nothing went out', () => {
        const sent = { kind: 'sent' as const, at: '2026-06-15T09:05:00Z', reason: null }

        expect(emailSentAt({ created_at: '2026-06-15T09:00:00Z', timeline: [sent] })).toBe(sent.at)
        expect(emailSentAt({ created_at: '2026-06-15T09:00:00Z', timeline: [] })).toBe('2026-06-15T09:00:00Z')
    })
})
