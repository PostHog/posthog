import { sessionsCloses, sessionsDrag, swipeDrag, swipeOutcome } from './feedPages'

describe('feed pages', () => {
    test.each([
        ['Moment, swipe left', 0, -120, 0, 'session'],
        ['Moment, swipe right', 0, 120, 0, 'stay'],
        ['Full recording, swipe right', 1, 120, 0, 'moment'],
        ['Full recording, swipe left', 1, -120, 0, 'sessions'],
        ['a short slow swipe', 1, -30, 200, 'stay'],
        ['a short fast flick', 1, -30, -900, 'sessions'],
    ] as const)('%s lands on %s', (_name, tabBase, translationX, velocityX, outcome) => {
        expect(swipeOutcome(tabBase, translationX, velocityX)).toBe(outcome)
    })

    test.each([
        ['Moment, half way to Full recording', 0, -120, { tab: 0.5, sessions: 0 }],
        ['Full recording, left drag moves only the Sessions page', 1, -100, { tab: 1, sessions: 0.25 }],
        ['Full recording, right drag moves the tab back', 1, 120, { tab: 0.5, sessions: 0 }],
        ['Moment, right drag goes nowhere', 0, 200, { tab: 0, sessions: 0 }],
    ] as const)('%s', (_name, tabBase, translationX, expected) => {
        expect(swipeDrag(tabBase, translationX, 400)).toEqual(expected)
    })

    test('the Sessions page follows a drag to the right and closes past the threshold', () => {
        expect(sessionsDrag(100, 400)).toBe(0.75)
        expect(sessionsDrag(-50, 400)).toBe(1)
        expect(sessionsCloses(100, 0)).toBe(true)
        expect(sessionsCloses(30, 100)).toBe(false)
    })
})
