import { Dayjs, dayjs } from 'lib/dayjs'

import { describeRunAudience, getRunAudience } from './broadcastRunAudience'

describe('broadcastRunAudience', () => {
    const lastActivity = '2026-11-25T18:00:00Z'
    const soon = dayjs('2026-11-25T22:00:00Z')

    it.each<{ name: string; totals: Record<string, number>; now: Dayjs; text: string; stillSending: boolean }>([
        {
            name: 'people held by the frequency cap',
            totals: {
                triggered: 500,
                run_succeeded: 85,
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
            name: 'people sent once their hold ended, while others are still queued',
            totals: {
                triggered: 100,
                run_succeeded: 50,
                email_sent: 50,
                message_frequency_cap_held: 50,
                message_frequency_cap_hold_ended: 50,
            },
            now: soon,
            text: '100 in audience: 50 sent, 50 still to send',
            stillSending: true,
        },
        {
            name: 'a send that errored for everyone, also recorded as provider failures',
            totals: { triggered: 245, run_failed: 245, failed: 245, email_failed: 245 },
            now: soon,
            text: '245 in audience: 245 failed',
            stillSending: false,
        },
        {
            name: 'rejects reported after the send, while others are still queued',
            totals: { triggered: 100, run_succeeded: 90, email_sent: 90, email_failed: 10 },
            now: soon,
            text: '100 in audience: 90 sent, 10 still to send',
            stillSending: true,
        },
        {
            name: 'a send slowed by a sending limit',
            totals: { triggered: 100, run_succeeded: 40, email_sent: 40 },
            now: soon,
            text: '100 in audience: 40 sent, 60 still to send',
            stillSending: true,
        },
        {
            name: 'a run that finished with holds and skips',
            totals: {
                triggered: 100,
                run_succeeded: 99,
                run_failed: 1,
                email_sent: 90,
                message_frequency_cap_held: 12,
                message_frequency_capped: 5,
                email_missing_recipient: 3,
                email_bounce_prevented: 1,
                failed: 1,
                email_failed: 1,
            },
            now: soon,
            text: '100 in audience: 90 sent, 5 skipped by the frequency cap, 4 with no usable email address, 1 failed',
            stillSending: false,
        },
        {
            name: 'people the email step filtered out or the exit condition removed',
            totals: { triggered: 100, run_succeeded: 100, email_sent: 70, filtered: 20, early_exit: 10 },
            now: soon,
            text: "100 in audience: 70 sent, 20 skipped by the email step's filters, 10 left early because of the exit condition",
            stillSending: false,
        },
        {
            name: 'people whose run ended without a send this breakdown names, such as paused sending',
            totals: { triggered: 100, run_succeeded: 95, canceled: 5, email_sent: 60, email_paused: 40 },
            now: soon,
            text: '100 in audience: 60 sent, 40 not sent',
            stillSending: false,
        },
        {
            name: 'people still held when the run is too old to send them',
            totals: { triggered: 100, run_succeeded: 60, email_sent: 60, message_frequency_cap_held: 40 },
            now: dayjs('2026-12-05T18:00:00Z'),
            text: '100 in audience: 60 sent, 40 not sent',
            stillSending: false,
        },
        {
            name: 'people this run lost track of, long after the send',
            totals: { triggered: 100, run_succeeded: 90, email_sent: 90 },
            now: dayjs('2026-12-05T18:00:00Z'),
            text: '100 in audience: 90 sent, 10 not sent',
            stillSending: false,
        },
    ])('describes $name', ({ totals, now, text, stillSending }) => {
        const run = getRunAudience(totals, lastActivity, now)
        expect(run && describeRunAudience(run)).toEqual(text)
        expect(run?.stillSending).toEqual(stillSending)
    })

    it.each<[Record<string, number> | null]>([[null], [{}], [{ triggered: 0, email_sent: 3 }]])(
        'has nothing to say without an audience: %j',
        (totals) => {
            expect(getRunAudience(totals, lastActivity, soon)).toBeNull()
        }
    )
})
