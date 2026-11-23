import { act, renderHook } from '@testing-library/react-native'
import { requireOptionalNativeModule } from 'expo'
import { AppState, type AppStateStatus, Platform } from 'react-native'

import { chatDictationPhrases } from './chatDictationPhrases'
import { useChatDictation } from './useChatDictation'

jest.mock('expo', () => ({
    ...jest.requireActual('expo'),
    requireOptionalNativeModule: jest.fn(),
}))
const mockLocale = jest.fn(() => 'en-US')
jest.mock('expo-localization', () => ({ getLocales: () => [{ languageTag: mockLocale() }] }))

type Event = 'start' | 'end' | 'result' | 'error'
const listeners = new Map<Event, Set<(payload?: unknown) => void>>()
const recognizer = {
    supportsOnDeviceRecognition: jest.fn(() => true),
    isRecognitionAvailable: jest.fn(() => true),
    getSupportedLocales: jest.fn(async () => ({ installedLocales: ['en-US'], locales: ['en-US'] })),
    getMicrophonePermissionsAsync: jest.fn(async () => ({ granted: false, canAskAgain: true })),
    requestMicrophonePermissionsAsync: jest.fn(async () => ({ granted: true })),
    addListener: jest.fn((event: Event, listener: (payload?: unknown) => void) => {
        const eventListeners = listeners.get(event) ?? new Set()
        eventListeners.add(listener)
        listeners.set(event, eventListeners)
        return { remove: () => eventListeners.delete(listener) }
    }),
    start: jest.fn(),
    stop: jest.fn(),
    abort: jest.fn(),
    getStateAsync: jest.fn(async () => 'inactive'),
}

function emit(event: Event, payload?: unknown): void {
    act(() => {
        for (const listener of listeners.get(event) ?? []) {
            listener(payload)
        }
    })
}

function speech(transcript: string, isFinal = false): void {
    emit('result', { isFinal, results: [{ transcript }] })
}

describe('chat dictation', () => {
    let changeAppState: (state: AppStateStatus) => void
    const onTranscript = jest.fn()

    beforeEach(() => {
        jest.useFakeTimers()
        jest.clearAllMocks()
        jest.replaceProperty(Platform, 'OS', 'ios')
        jest.mocked(requireOptionalNativeModule).mockReturnValue(recognizer)
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
            changeAppState = handler
            return { remove: jest.fn() }
        })
    })

    afterEach(() => {
        emit('end')
        listeners.clear()
        jest.restoreAllMocks()
    })

    afterAll(() => jest.useRealTimers())

    function renderDictation(): ReturnType<typeof renderHook<ReturnType<typeof useChatDictation>, string>> {
        return renderHook((scopeKey: string) => useChatDictation({ onTranscript, scopeKey }), {
            initialProps: 'chat-a',
        })
    }

    test('hides dictation when the installed binary lacks the native module', () => {
        jest.mocked(requireOptionalNativeModule).mockReturnValue(null)
        const { result } = renderDictation()
        expect(result.current.available).toBe(false)
        act(() => result.current.toggle())
        expect(result.current.phase).toBe('idle')
    })

    test('blocks Android versions where the native package would use the default recognizer', () => {
        jest.replaceProperty(Platform, 'OS', 'android')
        jest.spyOn(Platform, 'Version', 'get').mockReturnValue(32)
        const { result } = renderDictation()
        expect(result.current.available).toBe(false)
        expect(requireOptionalNativeModule).not.toHaveBeenCalled()
    })

    test('Android checks the on-device recognizer without depending on the default speech service', async () => {
        jest.replaceProperty(Platform, 'OS', 'android')
        jest.spyOn(Platform, 'Version', 'get').mockReturnValue(33)
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        expect(recognizer.isRecognitionAvailable).not.toHaveBeenCalled()
        expect(recognizer.getSupportedLocales).toHaveBeenCalledWith({})
        expect(recognizer.start).toHaveBeenCalledWith(expect.objectContaining({ requiresOnDeviceRecognition: true }))
    })

    test('leaves the draft untouched if the service reports an unexpected error', async () => {
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        emit('start')
        speech('An incomplete thought')
        emit('error', { error: 'network' })
        emit('end')
        expect(result.current.error).toMatch(/On-device dictation is unavailable/)
        expect(result.current.preview).toBe('')
        expect(onTranscript).not.toHaveBeenCalled()
        expect(recognizer.start).toHaveBeenCalledTimes(1)
    })

    test.each([
        { tag: 'en-US-u-hc-h23', installed: ['en', 'en_US'], expected: 'en_US' },
        { tag: 'en-US-u-hc-h23', installed: ['en-GB', 'en'], expected: 'en' },
        { tag: 'zh-Hans-CN', installed: ['zh-Hant-CN', 'zh_CN'], expected: 'zh_CN' },
        { tag: 'zh-Hant-TW-x-local', installed: ['zh', 'zh-TW'], expected: 'zh-TW' },
        { tag: 'zh-TW', installed: ['zh-Hant-TW', 'zh-TW'], expected: 'zh-TW' },
        { tag: 'zh-Hant-TW', installed: ['zh-Hans-TW', 'zh-Hant-HK', 'zh'], expected: undefined },
    ])('matches installed speech models for $tag', async ({ tag, installed, expected }) => {
        mockLocale.mockReturnValueOnce(tag)
        recognizer.getSupportedLocales.mockResolvedValueOnce({ locales: installed, installedLocales: installed })
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        if (expected) {
            expect(recognizer.start).toHaveBeenCalledWith(expect.objectContaining({ lang: expected }))
        } else {
            expect(recognizer.start).not.toHaveBeenCalled()
            expect(result.current.error).toMatch(/device language/)
        }
    })

    test('requires an installed locale before requesting the microphone', async () => {
        recognizer.getSupportedLocales.mockResolvedValueOnce({ locales: ['en-US'], installedLocales: ['fr-FR'] })
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        expect(result.current.error).toMatch(/device language/)
        expect(recognizer.requestMicrophonePermissionsAsync).not.toHaveBeenCalled()
        expect(recognizer.start).not.toHaveBeenCalled()
    })

    test('starts without reopening the system dialog if microphone access is already granted', async () => {
        recognizer.getMicrophonePermissionsAsync.mockResolvedValueOnce({ granted: true, canAskAgain: true })
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        expect(recognizer.start).toHaveBeenCalledTimes(1)
        expect(recognizer.requestMicrophonePermissionsAsync).not.toHaveBeenCalled()
    })

    test.each(['grant', 'deny', 'leave', 'switch chat'] as const)(
        'handles Android permission result when the app backgrounds to %s',
        async (outcome) => {
            jest.replaceProperty(Platform, 'OS', 'android')
            jest.spyOn(Platform, 'Version', 'get').mockReturnValue(36)
            let answerPermission: (value: { granted: boolean }) => void = () => {}
            recognizer.requestMicrophonePermissionsAsync.mockReturnValueOnce(
                new Promise((resolve) => {
                    answerPermission = resolve
                })
            )
            const { result, rerender } = renderDictation()
            await act(async () => result.current.toggle())
            expect(recognizer.requestMicrophonePermissionsAsync).toHaveBeenCalled()
            act(() => changeAppState('background'))

            await act(async () => answerPermission({ granted: outcome !== 'deny' }))
            expect(recognizer.start).not.toHaveBeenCalled()
            if (outcome === 'leave') {
                await act(async () => jest.advanceTimersByTime(1500))
            }
            if (outcome === 'switch chat') {
                rerender('chat-b')
            }
            await act(async () => changeAppState('active'))
            if (outcome === 'grant') {
                expect(recognizer.start).toHaveBeenCalledTimes(1)
            } else {
                expect(result.current.phase).toBe('idle')
                expect(recognizer.start).not.toHaveBeenCalled()
                expect(result.current.error).toBe(
                    outcome === 'deny' ? 'Allow microphone access in Settings to use dictation.' : null
                )
            }
        }
    )

    test('returns to idle after microphone permission is denied', async () => {
        recognizer.requestMicrophonePermissionsAsync.mockResolvedValueOnce({ granted: false })
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        expect(result.current.phase).toBe('idle')
        expect(result.current.error).toMatch(/microphone access/)
        expect(recognizer.start).not.toHaveBeenCalled()
    })

    test('previews partial results and inserts one final transcript when the native session ends', async () => {
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        expect(recognizer.start).toHaveBeenCalledWith(
            expect.objectContaining({
                lang: 'en-US',
                requiresOnDeviceRecognition: true,
                contextualStrings: chatDictationPhrases(''),
                recordingOptions: { persist: false },
            })
        )
        expect(result.current.phase).toBe('starting')
        emit('start')
        expect(result.current.phase).toBe('listening')
        speech('Track the')
        expect(result.current.preview).toBe('Track the')
        expect(onTranscript).not.toHaveBeenCalled()

        act(() => {
            result.current.toggle()
            result.current.toggle()
        })
        expect(recognizer.stop).toHaveBeenCalledTimes(1)
        expect(result.current.phase).toBe('finishing')
        speech('Track the cohort.', true)
        emit('end')
        emit('end')
        expect(result.current.preview).toBe('')
        expect(result.current.phase).toBe('idle')
        expect(onTranscript).toHaveBeenCalledTimes(1)
        expect(onTranscript).toHaveBeenCalledWith('Track the cohort.')
    })

    test('keeps successive final segments when the recognizer stops on its own', async () => {
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        emit('start')
        speech('Track the cohort.', true)
        speech(' Then open an insight.', true)
        emit('end')
        expect(recognizer.stop).not.toHaveBeenCalled()
        expect(onTranscript).toHaveBeenCalledTimes(1)
        expect(onTranscript).toHaveBeenCalledWith('Track the cohort. Then open an insight.')
    })

    test('inserts the last preview if the recognizer ends without delivering a final result', async () => {
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        emit('start')
        speech('Some partial speech')
        emit('end')
        expect(result.current.error).toBeNull()
        expect(onTranscript).toHaveBeenCalledWith('Some partial speech')
    })

    test('does not start recognition if permission resolves after changing chats', async () => {
        let grantPermission: (value: { granted: boolean }) => void = () => {}
        recognizer.requestMicrophonePermissionsAsync.mockReturnValueOnce(
            new Promise((resolve) => {
                grantPermission = resolve
            })
        )
        const { result, rerender } = renderDictation()
        await act(async () => result.current.toggle())
        expect(recognizer.requestMicrophonePermissionsAsync).toHaveBeenCalled()

        rerender('chat-b')
        await act(async () => grantPermission({ granted: true }))
        expect(recognizer.start).not.toHaveBeenCalled()
        expect(result.current.phase).toBe('idle')
    })

    test('aborts a delayed native start after leaving and ignores its transcript', async () => {
        const { result, rerender } = renderDictation()
        await act(async () => result.current.toggle())
        expect(recognizer.start).toHaveBeenCalled()
        rerender('chat-b')
        emit('start')
        expect(recognizer.abort).toHaveBeenCalledTimes(1)
        speech('Old chat transcript', true)
        emit('end')
        expect(onTranscript).not.toHaveBeenCalled()

        await act(async () => result.current.toggle())
        emit('start')
        speech('New chat transcript', true)
        emit('end')
        expect(onTranscript).toHaveBeenCalledTimes(1)
        expect(onTranscript).toHaveBeenCalledWith('New chat transcript')
    })

    test('waits for a full minute of inactivity before stopping a stalled recognizer', async () => {
        const { result } = renderDictation()
        await act(async () => result.current.toggle())
        emit('start')
        act(() => jest.advanceTimersByTime(59000))
        speech('I am still speaking')
        act(() => jest.advanceTimersByTime(59000))
        expect(result.current.phase).toBe('listening')
        expect(recognizer.stop).not.toHaveBeenCalled()
        act(() => jest.advanceTimersByTime(1000))
        expect(result.current.phase).toBe('finishing')
        expect(recognizer.stop).toHaveBeenCalledTimes(1)
    })

    test.each(['inactive', 'stopping', 'unavailable'] as const)(
        'recovers after a missing end event when the first teardown check is %s',
        async (firstState) => {
            if (firstState === 'unavailable') {
                recognizer.getStateAsync.mockRejectedValueOnce(new Error('State unavailable'))
            } else {
                recognizer.getStateAsync.mockResolvedValueOnce(firstState)
            }
            const { result } = renderDictation()
            await act(async () => result.current.toggle())
            emit('start')
            speech('What is our retention?')
            act(() => result.current.toggle())
            act(() => jest.advanceTimersByTime(2500))
            expect(result.current.phase).toBe('idle')
            expect(onTranscript).toHaveBeenCalledWith('What is our retention?')

            await act(async () => result.current.toggle())
            expect(result.current.error).toMatch(/still stopping/)
            speech('Stale final result', true)
            expect(onTranscript).toHaveBeenCalledTimes(1)

            await act(async () => jest.advanceTimersByTime(2500))
            if (firstState !== 'inactive') {
                await act(async () => result.current.toggle())
                expect(result.current.error).toMatch(/still stopping/)
                await act(async () => jest.advanceTimersByTime(2500))
            }
            await act(async () => result.current.toggle())
            emit('start')
            expect(result.current.phase).toBe('listening')
        }
    )

    test.each(['missing start', 'late start', 'chat change'] as const)(
        'lets the next chat dictate after a native start timeout with %s',
        async (scenario) => {
            const { result, rerender } = renderDictation()
            await act(async () => result.current.toggle())
            if (scenario === 'chat change') {
                rerender('chat-b')
            }
            act(() => jest.advanceTimersByTime(8000))
            expect(result.current.phase).toBe('idle')
            expect(result.current.error).toBe(
                scenario === 'chat change' ? null : 'Dictation stopped unexpectedly. Try again.'
            )

            if (scenario === 'late start') {
                emit('end')
                await act(async () => result.current.toggle())
                expect(result.current.error).toMatch(/still stopping/)
                emit('start')
                expect(recognizer.abort).toHaveBeenCalledTimes(2)
                speech('Stale final result', true)
                expect(onTranscript).not.toHaveBeenCalled()
            }

            await act(async () => jest.advanceTimersByTime(2500))
            rerender('chat-b')
            await act(async () => result.current.toggle())
            emit('start')
            speech('New chat transcript', true)
            emit('end')
            expect(onTranscript).toHaveBeenCalledTimes(1)
            expect(onTranscript).toHaveBeenCalledWith('New chat transcript')
        }
    )

    test('discards results when the app backgrounds or the hook unmounts', async () => {
        const { result, unmount } = renderDictation()
        await act(async () => result.current.toggle())
        expect(result.current.error).toBeNull()
        expect(recognizer.start).toHaveBeenCalledTimes(1)
        emit('start')
        speech('Before backgrounding', true)
        act(() => changeAppState('background'))
        expect(result.current.phase).toBe('idle')
        expect(recognizer.abort).toHaveBeenCalledTimes(1)
        emit('end')
        expect(onTranscript).not.toHaveBeenCalled()

        act(() => changeAppState('active'))
        await act(async () => result.current.toggle())
        emit('start')
        unmount()
        expect(recognizer.abort).toHaveBeenCalledTimes(2)
        speech('After unmounting', true)
        emit('end')
        expect(onTranscript).not.toHaveBeenCalled()
    })
})
