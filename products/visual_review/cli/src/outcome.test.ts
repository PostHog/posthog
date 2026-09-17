import { beforeEach, describe, expect, it, vi } from 'vitest'

import { VisualReviewClient, type Run } from './client.js'
import { reportRunOutcome } from './outcome.js'

function run(summary: Partial<Run['summary']> = {}): Run {
    return {
        id: 'run-1',
        branch: 'master',
        summary: { total: 10, unchanged: 10, changed: 0, new: 0, removed: 0, unresolved: 0, ...summary },
    } as Run
}

describe('reportRunOutcome', () => {
    let client: VisualReviewClient
    let output: string

    beforeEach(() => {
        output = ''
        const capture = (chunk: unknown): boolean => {
            output += String(chunk)
            return true
        }
        vi.spyOn(process.stderr, 'write').mockImplementation(capture)
        vi.spyOn(process.stdout, 'write').mockImplementation(capture)
        client = new VisualReviewClient({ apiUrl: 'https://vr.example.com', teamId: '1' })
        vi.spyOn(client, 'getRunSnapshots').mockResolvedValue([
            { identifier: 'story--light', result: 'changed', diff_percentage: 12.07 },
            { identifier: 'story--dark', result: 'unchanged', diff_percentage: null },
        ] as never)
    })

    // A tolerated hash is reclassified `unchanged` server-side, so a clean master run really
    // does report changed=0 alongside a non-zero tolerated_matched (14 of them, in this repo).
    // Netting the two produced a negative count that read as drift and warned on every push.
    it('stays quiet on a clean observe run that has tolerated matches', async () => {
        const exitCode = await reportRunOutcome(
            client,
            run({ unchanged: 4115, total: 4115, tolerated_matched: 14 }),
            'https://vr.example.com/run-1',
            'observe'
        )

        expect(exitCode).toBe(0)
        expect(output).toContain('No visual changes')
        expect(output).not.toContain('::warning::')
    })

    // The mirror image: netting tolerated matches off real drift hid it entirely.
    it('warns about drift on a tolerating observe run even when tolerated matches exist', async () => {
        const exitCode = await reportRunOutcome(
            client,
            run({ unchanged: 4113, total: 4115, changed: 2, tolerated_matched: 14 }),
            'https://vr.example.com/run-1',
            'observe',
            true
        )

        expect(exitCode).toBe(0)
        expect(output).toContain('Unapproved snapshot drift on master')
        expect(output).toContain('changed: story--light (12.07% diff)')
    })

    // The merge-queue case. The tree in the run is the tree about to land, so drift there has
    // to stop the merge rather than warn about it after the fact.
    it('fails an observe run whose drift is not tolerated', async () => {
        const exitCode = await reportRunOutcome(
            client,
            run({ unchanged: 4113, total: 4115, changed: 2 }),
            'https://vr.example.com/run-1',
            'observe'
        )

        expect(exitCode).toBe(1)
        expect(output).toContain('Unapproved snapshot drift on master')
        expect(output).toContain('changed: story--light (12.07% diff)')
    })

    it('passes a clean observe run whose drift would not be tolerated', async () => {
        const exitCode = await reportRunOutcome(client, run(), 'https://vr.example.com/run-1', 'observe')

        expect(exitCode).toBe(0)
        expect(output).toContain('No visual changes')
        expect(output).not.toContain('::warning::')
    })

    it('gates a review run with unresolved changes', async () => {
        const exitCode = await reportRunOutcome(
            client,
            run({ unchanged: 8, changed: 2, unresolved: 2 }),
            'https://vr.example.com/run-1',
            'review'
        )

        expect(exitCode).toBe(1)
        expect(output).toContain('Visual changes detected')
    })

    it('passes a review run whose changes are all resolved', async () => {
        const exitCode = await reportRunOutcome(
            client,
            run({ unchanged: 8, changed: 2, unresolved: 0 }),
            'https://vr.example.com/run-1',
            'review'
        )

        expect(exitCode).toBe(0)
        expect(output).toContain('No visual changes')
    })

    it('still reports when the snapshot listing fails', async () => {
        vi.spyOn(client, 'getRunSnapshots').mockRejectedValue(new Error('boom'))

        const exitCode = await reportRunOutcome(
            client,
            run({ unchanged: 8, changed: 2, unresolved: 2 }),
            'https://vr.example.com/run-1',
            'review'
        )

        expect(exitCode).toBe(1)
        expect(output).toContain('Could not list changed snapshots: boom')
        expect(output).toContain('Visual changes detected')
    })
})
