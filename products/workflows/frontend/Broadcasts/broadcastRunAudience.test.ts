import { Dayjs, dayjs } from 'lib/dayjs'

import { describeRunAudience, getRunAudience } from './broadcastRunAudience'

describe('broadcastRunAudience', () => {
    const started = '2026-11-25T18:00:00Z'
    const soon = dayjs('2026-11-25T22:00:00Z')

    it.each<{ name: string; totals: Record<string, number>; now: Dayjs; text: string; stillSending: boolean }>([
        {
            name: 'people held by the frequency cap',
            totals: {
                triggered: 500,
                email_sent: 10,
                email_opted_out: 60,
                email_suppressed: 15,
                message_frequency_cap_held: 420,
            },
            now: soon,
            text: '500 in audience: 10 sent, 415 waiting on the frequency cap, 60 opted out, 15 on the suppression list',
            stillSending: true,
        },
        {
            name: 'a send that errored for everyone, also recorded as provider failures',
            totals: { triggered: 245, failed: 245, email_failed: 245 },
            now: soon,
            text: '245 in audience: 245 failed',
            stillSending: false,
        },
        {
            name: 'a send slowed by a sending limit',
            totals: { triggered: 100, email_sent: 40 },
            now: soon,
            text: '100 in audience: 40 sent, 60 still to send',
            stillSending: true,
        },
        {
            name: 'a run that finished with holds and skips',
            totals: {
                triggered: 100,
                email_sent: 90,
                message_frequency_cap_held: 12,
                message_frequency_capped: 5,
                email_missing_recipient: 3,
                email_bounce_prevented: 1,
                email_failed: 1,
            },
            now: soon,
            text: '100 in audience: 90 sent, 5 skipped by the frequency cap, 4 with no usable email address, 1 failed',
            stillSending: false,
        },
        {
            name: 'people this run lost track of, long after the send',
            totals: { triggered: 100, email_sent: 90 },
            now: dayjs('2026-12-05T18:00:00Z'),
            text: '100 in audience: 90 sent, 10 not sent',
            stillSending: false,
        },
        {
            name: 'people still held when the run is too old to send them',
            totals: { triggered: 100, email_sent: 60, message_frequency_cap_held: 40 },
            now: dayjs('2026-12-05T18:00:00Z'),
            text: '100 in audience: 60 sent, 40 not sent',
            stillSending: false,
        },
    ])('describes $name', ({ totals, now, text, stillSending }) => {
        const run = getRunAudience(totals, started, now)
        expect(run && describeRunAudience(run)).toEqual(text)
        expect(run?.stillSending).toEqual(stillSending)
    })

    it.each<[Record<string, number> | null]>([[null], [{}], [{ triggered: 0, email_sent: 3 }]])(
        'has nothing to say without an audience: %j',
        (totals) => {
            expect(getRunAudience(totals, started, soon)).toBeNull()
        }
    )
})
