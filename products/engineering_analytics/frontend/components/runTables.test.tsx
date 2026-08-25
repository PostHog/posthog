import { formatCost, runPrNumber } from './runTables'

describe('runTables', () => {
    describe('formatCost', () => {
        it.each([
            [null, '—'],
            [0, '$0.00'],
            // Sub-cent positives must not read as free: a short self-hosted job at the reference rate.
            [0.004, '<$0.01'],
            [0.009, '<$0.01'],
            [0.01, '$0.01'],
            [0.38, '$0.38'],
            [12.5, '$12.50'],
        ])('formats %p as %p', (usd, expected) => {
            expect(formatCost(usd)).toBe(expected)
        })
    })

    describe('runPrNumber', () => {
        // Both inputs signal "unattributed" differently: pr_number arrives as 0 (ClickHouse fills an
        // unmatched join with the type default, never NULL) while commit_pr_number arrives as null.
        // Collapsing that to `prNumber ?? commitPrNumber` would link every unattributed run to #0.
        it.each([
            ['association wins', 10, null, 10],
            ['association preferred over the merge commit', 10, 74028, 10],
            ['default-branch push falls back to the merge commit', 0, 74028, 74028],
            ['unattributed reads as no PR, not #0', 0, null, null],
            ['a zero merge-commit number is absent too', 0, 0, null],
        ])('%s', (_name, prNumber, commitPrNumber, expected) => {
            expect(runPrNumber(prNumber, commitPrNumber)).toBe(expected)
        })
    })
})
