import { ApiError } from 'lib/api'

import { PushTokenRow, parsePushTokenCsv, runPushTokenImport, sleepUnlessAborted } from './pushTokenImport'

const rows = (count: number): PushTokenRow[] =>
    Array.from({ length: count }, (_, index) => ({
        line: index + 2,
        distinct_id: `user-${index}`,
        device_token: `token-${index}`,
    }))

const run = (
    send: Parameters<typeof runPushTokenImport>[0]['send'],
    count: number
): ReturnType<typeof runPushTokenImport> =>
    runPushTokenImport({
        rows: rows(count),
        send,
        sleep: () => Promise.resolve(),
        onChunkDone: () => {},
        stop: new AbortController().signal,
    })

describe('push token import', () => {
    it('reads columns by name, skips unusable lines, and drops repeats', () => {
        const csv = [
            'Device_Token , DISTINCT_ID,plan',
            'tok-a,ü-1,pro',
            '',
            'tok-a,ü-1,pro',
            'tok-b,,pro',
            ',user-2,pro',
            `${'x'.repeat(4097)},user-3,pro`,
            ' tok-c , user-4 ,free',
        ].join('\n')

        expect(parsePushTokenCsv(csv)).toEqual({
            rows: [
                { line: 2, distinct_id: 'ü-1', device_token: 'tok-a' },
                { line: 8, distinct_id: 'user-4', device_token: 'tok-c' },
            ],
            rejected: [
                { line: 5, distinct_id: '', device_token: 'tok-b', reason: 'No distinct ID' },
                { line: 6, distinct_id: 'user-2', device_token: '', reason: 'No device token' },
                {
                    line: 7,
                    distinct_id: 'user-3',
                    device_token: 'x'.repeat(4097),
                    reason: 'Device token is longer than 4096 characters',
                },
            ],
            duplicates: 1,
        })
    })

    it.each([
        ['no header', 'user-1,tok-a\n'],
        ['a header without device_token', 'distinct_id,token\nuser-1,tok-a\n'],
        ['only a header', 'distinct_id,device_token\n'],
    ])('refuses a file with %s', (_, csv) => {
        expect(() => parsePushTokenCsv(csv)).toThrow()
    })

    it('sends 1000 rows per request and matches each failure the API reports back to its line', async () => {
        const sent: [number, boolean][] = []
        const outcome = await run(async (subscriptions, options) => {
            sent.push([subscriptions.length, options.create_missing_persons])
            const failed = subscriptions
                .filter((s) => s.distinct_id === 'user-1500' || s.distinct_id === 'user-2400')
                .map((s) => ({
                    distinct_id: s.distinct_id,
                    device_token_suffix: s.device_token.slice(-6),
                    reason: s.distinct_id === 'user-1500' ? ('unknown_person' as const) : ('not_stored' as const),
                    detail: '',
                }))
            return {
                imported: subscriptions.length - failed.length,
                dry_run: false,
                failed,
                failed_distinct_ids: failed.map((f) => f.distinct_id),
            }
        }, 2500)

        expect(sent).toEqual([
            [1000, false],
            [1000, false],
            [500, false],
        ])
        expect(outcome.imported).toBe(2498)
        expect(outcome.failed.map((row) => [row.line, row.distinct_id, row.reason, row.unknownPerson])).toEqual([
            [1502, 'user-1500', 'No person has this distinct ID', true],
            [2402, 'user-2400', 'Not stored, import it again', false],
        ])
    })

    it('retries rate limits and server errors, then gives up on the batch but not the import', async () => {
        // One entry per call: an error to throw, or null to succeed.
        const calls: (ApiError | null)[] = [
            new ApiError('slow down', 429, new Headers({ 'Retry-After': '2' })),
            new ApiError('boom', 500),
            null,
            ...Array.from({ length: 5 }, () => new ApiError('down', 503)),
        ]
        const outcome = await run(async (subscriptions) => {
            const error = calls.shift()
            if (error) {
                throw error
            }
            return { imported: subscriptions.length, dry_run: false, failed: [], failed_distinct_ids: [] }
        }, 1500)

        // The first batch gets through after a rate limit and a 500, the second exhausts its retries.
        expect(outcome.imported).toBe(1000)
        expect(outcome.failed).toHaveLength(500)
        expect(outcome.stoppedReason).toBeNull()
    })

    it('stops during a rate limit wait instead of sleeping it out', async () => {
        const stop = new AbortController()
        let calls = 0
        const started = Date.now()
        const outcome = await runPushTokenImport({
            rows: rows(2500),
            send: async (subscriptions) => {
                calls++
                if (calls === 1) {
                    return { imported: subscriptions.length, dry_run: false, failed: [], failed_distinct_ids: [] }
                }
                setTimeout(() => stop.abort(), 0)
                throw new ApiError('slow down', 429, new Headers({ 'Retry-After': '60' }))
            },
            sleep: sleepUnlessAborted,
            onChunkDone: () => {},
            stop: stop.signal,
        })

        expect(Date.now() - started).toBeLessThan(5000)
        expect(calls).toBe(2)
        expect(outcome).toMatchObject({ imported: 1000, stoppedReason: 'cancelled' })
        expect(outcome.failed).toHaveLength(1500)
    })

    it('stops on a permission error and marks every unsent row', async () => {
        const outcome = await run(async () => {
            throw new ApiError('denied', 403, undefined, { detail: 'You do not have permission.' })
        }, 1500)

        expect(outcome).toMatchObject({ imported: 0, stoppedReason: 'You do not have permission.' })
        expect(outcome.failed).toHaveLength(1500)
    })
})
