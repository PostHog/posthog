import { ApiError } from 'lib/api'

import { PushTokenRow, parsePushTokenCsv, runPushTokenImport } from './pushTokenImport'

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
        isCancelled: () => false,
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

    it('sends 1000 rows per request and reports rows the API could not store', async () => {
        const sent: number[] = []
        const outcome = await run(async (subscriptions) => {
            sent.push(subscriptions.length)
            const failed = subscriptions.some((s) => s.distinct_id === 'user-1500') ? ['user-1500'] : []
            return { imported: subscriptions.length - failed.length, failed_distinct_ids: failed }
        }, 2500)

        expect(sent).toEqual([1000, 1000, 500])
        expect(outcome.imported).toBe(2499)
        expect(outcome.failed.map((row) => [row.distinct_id, row.reason])).toEqual([
            ['user-1500', 'Not stored, import it again'],
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
            return { imported: subscriptions.length, failed_distinct_ids: [] }
        }, 1500)

        // The first batch gets through after a rate limit and a 500, the second exhausts its retries.
        expect(outcome.imported).toBe(1000)
        expect(outcome.failed).toHaveLength(500)
        expect(outcome.stoppedReason).toBeNull()
    })

    it('stops on a permission error and marks every unsent row', async () => {
        const outcome = await run(async () => {
            throw new ApiError('denied', 403, undefined, { detail: 'You do not have permission.' })
        }, 1500)

        expect(outcome).toMatchObject({ imported: 0, stoppedReason: 'You do not have permission.' })
        expect(outcome.failed).toHaveLength(1500)
    })
})
