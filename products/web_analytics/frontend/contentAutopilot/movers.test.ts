import { moverDelta } from './movers'

describe('movers', () => {
    it.each([
        [0.25, '+25 pts', 'up'],
        [-0.75, '-75 pts', 'down'],
        [0.0124, '+1.2 pts', 'up'],
        [-0.0004, '<0.1 pts', 'down'],
        [0, 'No change', 'flat'],
    ])('labels a change of %s as %s', (change, label, direction) => {
        expect(moverDelta(change, 30)).toMatchObject({ label, direction })
    })
})
