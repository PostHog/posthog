import type { QuarantineSourceRunApi } from '../generated/api.schemas'
import { sourceRunPrNumber } from './runPredicates'

function sourceRun(branch: string, prNumber: number | null): QuarantineSourceRunApi {
    return { id: 'run', branch, commit_sha: 'abc', created_at: '2026-01-01T00:00:00Z', pr_number: prNumber }
}

describe('sourceRunPrNumber', () => {
    test.each([
        ['merge-queue batch', 'trunk-merge/pr-121142/929572be-e2f5-4d9c-aca3-8ee7b777a173', 122057, 121142],
        [
            'merge-queue bisection',
            'trunk-merge/pr-121113/0cab0e58-11f4-4093-b568-b5271275f099-bisection',
            122001,
            121113,
        ],
        ['feature branch', 'fix/web-report-runs-newest-first', 120910, 120910],
        ['branch that only starts like a queue branch', 'trunk-merge/pr-abc/x', 120910, 120910],
        ['run without a PR', 'master', null, null],
    ])('%s', (_name, branch, prNumber, expected) => {
        expect(sourceRunPrNumber(sourceRun(branch, prNumber))).toBe(expected)
    })
})
