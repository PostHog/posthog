import { authoredRunsOnly, ciStatusOf } from './ci'

describe('ci', () => {
    it.each([
        ['no runs', { runs: 0, passing: 0, failing: 0, pending: 0 }, 'none'],
        ['a failure', { runs: 3, passing: 2, failing: 1, pending: 0 }, 'failing'],
        ['failure beats pending', { runs: 5, passing: 2, failing: 1, pending: 2 }, 'failing'],
        ['unsettled run', { runs: 3, passing: 1, failing: 0, pending: 2 }, 'running'],
        ['all green', { runs: 3, passing: 3, failing: 0, pending: 0 }, 'passing'],
        // Every run settled cancelled or skipped: nothing failed and nothing is pending, but nothing
        // passed either. Reading this as 'passing' put such a PR in the "ready to merge" list.
        ['every run cancelled', { runs: 3, passing: 0, failing: 0, pending: 0 }, 'inconclusive'],
    ])('ciStatusOf derives %s', (_label, rollup, expected) => {
        expect(ciStatusOf(rollup)).toBe(expected)
    })

    it('authoredRunsOnly drops merge-queue gate attempts', () => {
        // Two gate attempts, each on its own rebase SHA the author never pushed. Counting them made
        // the PR detail page report more pushes than the PR list for the same PR.
        const runs = [
            { id: 1, is_merge_queue: false },
            { id: 2, is_merge_queue: true },
            { id: 3, is_merge_queue: true },
        ]

        expect(authoredRunsOnly(runs).map((run) => run.id)).toEqual([1])
    })
})
