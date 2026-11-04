import { ActivityEvent, ActivityRow, buildActivityTimeline } from './emailActivity'

function event(uuid: string, timestamp: string, sessionId: string | null): ActivityEvent {
    return {
        uuid,
        event: '$pageview',
        timestamp,
        url: null,
        pathname: '/files',
        sessionId,
        eventType: null,
        elementsChain: '',
    }
}

describe('buildActivityTimeline', () => {
    it('splits at the send, starts the after part with the email block, folds repeats, and keeps other emails in order', () => {
        const timeline = buildActivityTimeline(
            [
                event('before', '2026-06-15T08:59:00Z', 's1'),
                event('after-1', '2026-06-15T09:03:00Z', 's2'),
                { ...event('after-2', '2026-06-15T09:04:00Z', 's2'), pathname: '/pricing' },
                { ...event('after-3', '2026-06-15T09:04:10Z', 's2'), pathname: '/pricing' },
            ],
            [
                { kind: 'sent', at: '2026-06-15T09:00:00Z', reason: null },
                { kind: 'delivered', at: '2026-06-15T09:00:02Z', reason: null },
                { kind: 'clicked', at: '2026-06-15T09:02:00Z', reason: null },
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
            rows.map((row) =>
                row.kind === 'emailGroup'
                    ? `emailGroup(${row.rows.length})`
                    : row.kind === 'event'
                      ? `event(${row.count})`
                      : row.kind
            )
        expect(shape(timeline.before)).toEqual(['session', 'event(1)'])
        expect(shape(timeline.after)).toEqual(['emailGroup(3)', 'session', 'event(1)', 'event(2)', 'otherEmail'])
    })
})
