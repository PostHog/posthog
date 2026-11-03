import { type SplashGateInput, shouldHideSplash } from './bootGate'

const base: SplashGateInput = { sessionReady: true, firstScreenReady: false, segments: [], timedOut: false }

describe('shouldHideSplash', () => {
    test.each<[string, Partial<SplashGateInput>, boolean]>([
        ['holds while the index route redirects', {}, false],
        ['holds while the inbox tab loads', { segments: ['(tabs)', 'inbox'] }, false],
        ['hides once the inbox is ready', { segments: ['(tabs)', 'inbox'], firstScreenReady: true }, true],
        ['hides on the chats tab without waiting', { segments: ['(tabs)', 'chats'] }, true],
        ['hides on sign in without waiting', { segments: ['sign-in'] }, true],
        ['hides on a deep link to a report', { segments: ['report', '[id]'] }, true],
        ['hides when the inbox times out', { segments: ['(tabs)', 'inbox'], timedOut: true }, true],
        ['holds before the session loads', { sessionReady: false, firstScreenReady: true, timedOut: true }, false],
        ['holds before the session loads on sign in', { sessionReady: false, segments: ['sign-in'] }, false],
    ])('%s', (_name, input, expected) => {
        expect(shouldHideSplash({ ...base, ...input })).toBe(expected)
    })
})
