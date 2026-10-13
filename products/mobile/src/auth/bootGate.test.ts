import { type SplashGateInput, shouldHideSplash } from './bootGate'

const base: SplashGateInput = { sessionReady: true, firstScreenReady: false, firstSegment: undefined, timedOut: false }

describe('shouldHideSplash', () => {
    test.each<[string, Partial<SplashGateInput>, boolean]>([
        ['holds while the index route redirects', {}, false],
        ['holds while the inbox loads', { firstSegment: 'inbox' }, false],
        ['hides once the inbox is ready', { firstSegment: 'inbox', firstScreenReady: true }, true],
        ['hides on sign in without waiting', { firstSegment: 'sign-in' }, true],
        ['hides on a deep link to a report', { firstSegment: 'report' }, true],
        ['hides when the inbox times out', { firstSegment: 'inbox', timedOut: true }, true],
        ['holds before the session loads', { sessionReady: false, firstScreenReady: true, timedOut: true }, false],
        ['holds before the session loads on sign in', { sessionReady: false, firstSegment: 'sign-in' }, false],
    ])('%s', (_name, input, expected) => {
        expect(shouldHideSplash({ ...base, ...input })).toBe(expected)
    })
})
