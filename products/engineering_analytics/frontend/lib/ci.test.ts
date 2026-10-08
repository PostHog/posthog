import { ciStatusOf } from './ci'

describe('ci', () => {
    it.each([
        ['no runs', { runs: 0, passing: 0, failing: 0, pending: 0, inconclusive: 0 }, 'none'],
        ['a failure', { runs: 3, passing: 2, failing: 1, pending: 0, inconclusive: 0 }, 'failing'],
        ['failure beats pending', { runs: 5, passing: 2, failing: 1, pending: 2, inconclusive: 0 }, 'failing'],
        ['unsettled run', { runs: 3, passing: 1, failing: 0, pending: 2, inconclusive: 0 }, 'running'],
        ['all green', { runs: 3, passing: 3, failing: 0, pending: 0, inconclusive: 0 }, 'passing'],
        ['a cancelled run beside passes', { runs: 3, passing: 2, failing: 0, pending: 0, inconclusive: 1 }, 'passing'],
        ['every run cancelled', { runs: 3, passing: 0, failing: 0, pending: 0, inconclusive: 3 }, 'inconclusive'],
    ])('ciStatusOf derives %s', (_label, rollup, expected) => {
        expect(ciStatusOf(rollup)).toBe(expected)
    })
})
