import { formatShare, shareChange, shareDelta } from './shares'

describe('shares', () => {
    it.each([
        [0.477, '48%'],
        [0.32, '32%'],
        [0.145, '15%'],
        [0.0145, '1.5%'],
        [0.1, '10%'],
        [0.0996, '10%'],
        [0.011, '1.1%'],
        [0.0799, '8.0%'],
        [0.005, '0.5%'],
        [0, '0%'],
        [1, '100%'],
    ])('shows a share of %s as %s', (share, label) => {
        expect(formatShare(share)).toEqual(label)
    })

    it.each([
        // The rows from the movers tables that used to read 0% then 0% with +0.5 pts, and 1% then 0% with +1.1 pts.
        [0.005, 0, 0.5],
        [0.011, 0.0004, 1.1],
        [0.41, 0.371, 4],
        [0.12, 0.095, 2.5],
        [0.472, 0.468, 0],
        // 0.145 reads 15%, so against 14% the change is a point, not the 0 that 14.499999... rounding gave.
        [0.145, 0.14, 1],
        [0.2, 0.25, -5],
        [0.4, null, null],
        [null, 0.4, null],
    ])('takes the change from %s to %s as the shown values differ: %s points', (share, previous, points) => {
        expect(shareChange(share, previous)).toEqual(points)
    })

    it.each([
        [0.25, 0, '+25 pts', 'up'],
        [0.005, 0.0124, '-0.7 pts', 'down'],
        [0.472, 0.468, 'No change', 'flat'],
    ])('labels %s against %s as %s', (share, previous, label, direction) => {
        expect(shareDelta(share, previous, 'tooltip')).toMatchObject({ label, direction })
    })
})
