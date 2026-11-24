import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VisualReviewApiError, VisualReviewClient } from './client.js'
import { reportNoRunNeeded } from './skip.js'

const input = {
    repo_id: 'repo-1',
    run_type: 'storybook',
    commit_sha: 'abcdef1234567890',
    branch: 'feature',
    pr_number: 7,
}

describe('reportNoRunNeeded', () => {
    let client: VisualReviewClient
    let output: string

    beforeEach(() => {
        output = ''
        vi.spyOn(process.stderr, 'write').mockImplementation((chunk: unknown): boolean => {
            output += String(chunk)
            return true
        })
        client = new VisualReviewClient({ apiUrl: 'https://vr.example.com', teamId: '1' })
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it.each(['posted', 'run_exists', 'status_gate_off'])(
        'exits 0 and prints the detail when the outcome is %s',
        async (outcome) => {
            const report = vi
                .spyOn(client, 'reportNoRunNeeded')
                .mockResolvedValue({ outcome, detail: `Detail for ${outcome}.` } as never)

            const exitCode = await reportNoRunNeeded(client, input)

            expect(exitCode).toBe(0)
            expect(report).toHaveBeenCalledWith(input)
            expect(output).toBe(`No storybook run needed for abcdef1234: Detail for ${outcome}.\n`)
        }
    )

    it('exits 1 when the backend could not post the status', async () => {
        vi.spyOn(client, 'reportNoRunNeeded').mockRejectedValue(
            new VisualReviewApiError(502, '{"detail": "GitHub did not accept the status"}')
        )

        const exitCode = await reportNoRunNeeded(client, input)

        expect(exitCode).toBe(1)
        expect(output).toContain('Could not report that abcdef1234 needs no storybook run: API error 502')
    })
})
